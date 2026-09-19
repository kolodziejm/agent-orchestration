import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "harnesses" / "validate.py"
CANONICAL_CATALOG = ROOT / "evaluations" / "configurations" / "pi-openai-adaptive.json"


class EvaluationValidationTests(unittest.TestCase):
    def documents(self):
        unavailable = {"status": "NOT_COLLECTED", "reason": "fixture does not execute"}
        corpus = {
            "kind": "evaluation-corpus", "version": 1, "corpus_id": "portable",
            "tasks": [{
                "task_id": "task-1", "task_class": "repository-bugfix", "title": "Fixture",
                "workspace_ref": "fixture:task-1", "prompt": "Make a deterministic change.",
                "acceptance": [{"acceptance_id": "unit", "command": ["python", "-m", "unittest"], "expected_exit_code": 0}],
            }],
        }
        plan = {
            "kind": "evaluation-plan", "version": 1, "plan_id": "pair-1", "corpus_ref": "portable",
            "variants": [
                {"variant_id": "control", "configuration_ref": "config-control"},
                {"variant_id": "candidate", "configuration_ref": "config-candidate"},
            ],
            "task_refs": ["task-1"],
        }
        catalog = {
            "kind": "evaluation-configuration-catalog", "version": 1,
            "catalog_id": "fixture-configurations", "activation": "EXPERIMENT_ONLY",
            "opt_in": True, "harness": "pi", "profile_ref": "openai",
            "configurations": [
                {
                    "configuration_id": configuration_id, "summary": "Fixture configuration",
                    "activation": "EXPERIMENT_ONLY",
                    "turn_budget": {"value": "TASK_CALIBRATED", "enforcement": "PROMPT_ONLY"},
                    "plan_scaffold": {"value": "NATIVE", "enforcement": "OPERATOR_OWNED"},
                    "action_space": {"value": "FULL", "enforcement": "ADAPTER_ENFORCED"},
                    "context_policy": {"value": "NATIVE", "enforcement": "OPERATOR_OWNED"},
                }
                for configuration_id in ("config-control", "config-candidate")
            ],
        }
        result = {
            "kind": "evaluation-result", "version": 1, "result_id": "result-1",
            "plan_ref": "pair-1", "task_ref": "task-1", "variant_ref": "control", "run_index": 1,
            "metrics": {
                name: copy.deepcopy(unavailable)
                for name in (
                    "task_success", "accepted_diff", "first_pass_validation", "cost",
                    "wall_time_ms", "turns", "tool_calls", "peak_context_tokens",
                    "compactions", "no_edit_termination", "manual_takeover", "policy_violations",
                )
            },
            "acceptance_evidence": [{"acceptance_ref": "unit", **copy.deepcopy(unavailable)}],
        }
        return corpus, catalog, plan, result

    def run_entrypoint(self, mutate=None):
        corpus, catalog, plan, result = self.documents()
        if mutate:
            mutate(corpus, catalog, plan, result)
        with tempfile.TemporaryDirectory() as temporary:
            evaluation_root = Path(temporary)
            for directory, name, document in (
                ("corpora", "corpus.json", corpus),
                ("configurations", "catalog.json", catalog),
                ("plans", "plan.json", plan),
                ("results", "result.json", result),
            ):
                path = evaluation_root / directory
                path.mkdir()
                (path / name).write_text(json.dumps(document), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATE), "--evaluations-root", str(evaluation_root)],
                cwd=ROOT, text=True, capture_output=True,
            )

    def assert_schema_rejected(self, mutate):
        completed = self.run_entrypoint(mutate)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Schema validation failed", completed.stderr)

    def test_real_entrypoint_accepts_explicit_uncollected_values(self):
        completed = self.run_entrypoint()
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_real_entrypoint_accepts_experiment_only_configuration_catalog(self):
        completed = self.run_entrypoint()
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_canonical_catalog_changes_one_dimension_per_candidate(self):
        catalog = json.loads(CANONICAL_CATALOG.read_text(encoding="utf-8"))
        dimensions = ("turn_budget", "plan_scaffold", "action_space", "context_policy")
        baseline, *candidates = catalog["configurations"]
        self.assertEqual(baseline["configuration_id"], "pi-openai-task-calibrated-baseline")
        for candidate in candidates:
            changed = [name for name in dimensions if candidate[name] != baseline[name]]
            self.assertEqual(len(changed), 1, candidate["configuration_id"])

    def test_real_entrypoint_rejects_wrong_metric_type(self):
        self.assert_schema_rejected(
            lambda _corpus, _catalog, _plan, result: result["metrics"].__setitem__(
                "turns", {"status": "OBSERVED", "value": "one"}
            )
        )

    def test_real_entrypoint_rejects_missing_required_metric(self):
        self.assert_schema_rejected(
            lambda _corpus, _catalog, _plan, result: result["metrics"].pop("tool_calls")
        )

    def test_real_entrypoint_rejects_unsupported_status_and_value(self):
        mutations = (
            lambda result: result["metrics"].__setitem__("turns", {"status": "ESTIMATED", "value": 1}),
            lambda result: result["metrics"].__setitem__("accepted_diff", {"status": "OBSERVED", "value": "yes"}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_schema_rejected(
                    lambda _corpus, _catalog, _plan, result: mutate(result)
                )

    def test_real_entrypoint_rejects_invalid_plan_and_result_references(self):
        cases = (
            (lambda _corpus, _catalog, plan, _result: plan.__setitem__("corpus_ref", "missing"), "Invalid corpus_ref"),
            (lambda _corpus, _catalog, _plan, result: result.__setitem__("plan_ref", "missing"), "Invalid plan_ref"),
        )
        for mutate, message in cases:
            with self.subTest(message=message):
                completed = self.run_entrypoint(mutate)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(message, completed.stderr)

    def test_real_entrypoint_rejects_unknown_catalog_profile(self):
        completed = self.run_entrypoint(
            lambda _corpus, catalog, _plan, _result: catalog.__setitem__(
                "profile_ref", "missing"
            )
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Invalid profile_ref", completed.stderr)

    def test_real_entrypoint_rejects_duplicate_configuration_ids(self):
        def duplicate(_corpus, catalog, _plan, _result):
            catalog["configurations"].append(copy.deepcopy(catalog["configurations"][0]))

        completed = self.run_entrypoint(duplicate)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Duplicate configuration_id", completed.stderr)

    def test_real_entrypoint_rejects_unsupported_dimension_value(self):
        self.assert_schema_rejected(
            lambda _corpus, catalog, _plan, _result: catalog["configurations"][0][
                "action_space"
            ].__setitem__("value", "TOOLS_FIRST")
        )

    def test_real_entrypoint_rejects_unresolved_configuration_ref(self):
        completed = self.run_entrypoint(
            lambda _corpus, _catalog, plan, _result: plan["variants"][0].__setitem__(
                "configuration_ref", "missing"
            )
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Invalid configuration_ref", completed.stderr)

    def test_real_entrypoint_rejects_non_experimental_activation(self):
        mutations = (
            lambda catalog: catalog.__setitem__("activation", "ACTIVE"),
            lambda catalog: catalog.__setitem__("opt_in", False),
            lambda catalog: catalog["configurations"][0].__setitem__("activation", "ACTIVE"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_schema_rejected(
                    lambda _corpus, catalog, _plan, _result: mutate(catalog)
                )


if __name__ == "__main__":
    unittest.main()
