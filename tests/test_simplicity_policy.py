import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimplicityPolicyTests(unittest.TestCase):
    def test_core_policy_requires_evidence_before_complexity(self):
        """Complexity must be justified by requirements, evidence, or a real safety boundary."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()

        for phrase in (
            "## Simplicity and evidence-gated complexity",
            "smallest end-to-end slice",
            "an explicit requirement or acceptance criterion",
            "an observed failure",
            "a security, data-loss, destructive-operation, or external trust boundary",
            "Controlled internal misuse may fail naturally.",
            "A fallback requires explicit degraded behavior",
            "Generalization requires at least two current consumers or an approved shared contract.",
        ):
            self.assertIn(phrase, policy)

    def test_review_units_use_cognitive_coherence_not_hard_size_limits(self):
        """Line accounting may inform review but must not force artificial stack boundaries."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()
        start = policy.index("## Reviewable-PR delivery contract")
        end = policy.index("## Implementation", start)
        delivery = policy[start:end]

        for phrase in (
            "one coherent reviewer question",
            "observable behavior",
            "Line and file counts are diagnostics, not approval gates or hard ceilings.",
            "unused scaffolding",
            "partial abstractions",
            "reviewed generated artifact contributes to cognitive review burden",
            "Split when the unit contains independently valuable behavior",
        ):
            self.assertIn(phrase, delivery)

        for obsolete in ("`<=400`", "401–800", "`>800`", "absolute ceiling"):
            self.assertNotIn(obsolete, delivery)

    def test_large_workflow_plans_progressively_without_mandatory_ceremony(self):
        """Large initiatives should learn from working slices instead of pre-authoring a long stack."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()
        workflow = (ROOT / "policy" / "workflows" / "feature-workflow-pilot.md").read_text()

        self.assertIn("Plan only the next one to three implementation units concretely.", workflow)
        self.assertIn("Later units remain a revisable roadmap", workflow)
        self.assertIn("one authoritative planning artifact by default", workflow)
        self.assertIn("Mindmaps, execution matrices, HTML reports, evidence ledgers, and retrospectives are optional", workflow)
        self.assertIn("only when independent evidence lanes provide concrete leverage", policy)
        self.assertNotIn("MUST use 2–4 parallel", policy)
        self.assertNotIn("without separate per-run review authorization", policy)

    def test_workers_learn_with_focused_self_checks_and_reviewers_demote_speculation(self):
        """Implementation gets a tight feedback loop while independent validation stays independent."""
        worker = (ROOT / "roles" / "worker.md").read_text()
        complex_worker = (ROOT / "roles" / "worker-complex.md").read_text()
        validator = (ROOT / "roles" / "validator.md").read_text()
        reviewer = (ROOT / "roles" / "reviewer.md").read_text()

        for contract in (worker, complex_worker):
            self.assertIn("focused development tests and checks as `SELF-CHECKS`", contract)
            self.assertIn("happy path before speculative hardening", contract)
            self.assertIn("requirement, observed failure, or safety boundary", contract)

        self.assertIn("independently rerun the smallest acceptance matrix", validator)
        self.assertIn("Prefer a real integration boundary over a fake that reimplements the external system", validator)
        self.assertIn("concrete and plausible failure path", reviewer)
        self.assertIn("Speculative hardening ideas are `Info` or follow-up suggestions", reviewer)
        self.assertIn("simplification, deletion, or natural failure", reviewer)


if __name__ == "__main__":
    unittest.main()
