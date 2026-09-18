import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "harnesses" / "validate.py"


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
                {"variant_id": "control", "configuration_ref": "config:control"},
                {"variant_id": "candidate", "configuration_ref": "config:candidate"},
            ],
            "task_refs": ["task-1"],
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
        return corpus, plan, result

    def run_entrypoint(self, mutate=None):
        corpus, plan, result = self.documents()
        if mutate:
            mutate(corpus, plan, result)
        with tempfile.TemporaryDirectory() as temporary:
            evaluation_root = Path(temporary)
            for directory, name, document in (
                ("corpora", "corpus.json", corpus),
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

    def test_real_entrypoint_rejects_wrong_metric_type(self):
        self.assert_schema_rejected(
            lambda _corpus, _plan, result: result["metrics"].__setitem__(
                "turns", {"status": "OBSERVED", "value": "one"}
            )
        )

    def test_real_entrypoint_rejects_missing_required_metric(self):
        self.assert_schema_rejected(
            lambda _corpus, _plan, result: result["metrics"].pop("tool_calls")
        )

    def test_real_entrypoint_rejects_unsupported_status_and_value(self):
        mutations = (
            lambda result: result["metrics"].__setitem__("turns", {"status": "ESTIMATED", "value": 1}),
            lambda result: result["metrics"].__setitem__("accepted_diff", {"status": "OBSERVED", "value": "yes"}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_schema_rejected(lambda _corpus, _plan, result: mutate(result))

    def test_real_entrypoint_rejects_invalid_plan_and_result_references(self):
        cases = (
            (lambda _corpus, plan, _result: plan.__setitem__("corpus_ref", "missing"), "Invalid corpus_ref"),
            (lambda _corpus, _plan, result: result.__setitem__("plan_ref", "missing"), "Invalid plan_ref"),
        )
        for mutate, message in cases:
            with self.subTest(message=message):
                completed = self.run_entrypoint(mutate)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(message, completed.stderr)


if __name__ == "__main__":
    unittest.main()
