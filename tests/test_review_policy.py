"""Explicit policy contracts: these are prompt semantics, not runtime enforcement."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GlobalReviewPolicyTests(unittest.TestCase):
    def test_every_code_review_unit_gets_independent_validation_and_fresh_review(self):
        """Fails if code completion can skip either independent proof or leak author history."""
        policy = (ROOT / "policy/orchestration.md").read_text()
        reviewer = (ROOT / "roles/reviewer.md").read_text()
        validator = (ROOT / "roles/validator.md").read_text()
        for phrase in (
            "## AI-first risk-based review",
            "standing policy authorization across all profiles",
            "every completed source-changing PR or fallback review unit",
            "code, tests, configuration, dependencies, or product behavior",
            "one fresh-context AI reviewer",
            "not the author's reasoning or implementation history",
            "different model family is preferred where the current profile allows",
            "not authorization to change model mappings",
            "direct-primary exception permits bounded implementation, not a completion waiver",
            "Documentation-only units receive proportionate read-only review",
            "additional independent specialist reviewers require explicit authorization",
        ):
            self.assertIn(phrase, policy)
        self.assertIn("fresh context without the author's reasoning or implementation history", reviewer)
        self.assertIn("request targeted acceptance evidence through the orchestrator/validator", reviewer)
        self.assertIn("must not run commands secretly", reviewer)
        self.assertIn("including direct-primary changes", validator)
        for obsolete in (
            "## Review on demand", "Never launch it automatically after implementation",
            "a single quick check by the orchestrator suffices",
            "may use a targeted check instead", "ordinary review-on-demand policy",
            "Delegated source-changing worker output always requires independent validator",
            "Reviewer-approved planning-artifact corrections",
            "Except for the narrow direct-work exception above, the orchestrator must delegate repository discovery, source changes, mechanical validation",
        ):
            self.assertNotIn(obsolete, policy)
        self.assertNotIn("never an automatic post-implementation", reviewer)
        self.assertNotIn("Documentation-only validator prohibition", validator)

    def test_autonomous_repair_is_a_scoped_mandate_not_a_severity_waiver(self):
        """Fails if a reviewer can authorize fixes or rename findings to renew the budget."""
        policy = (ROOT / "policy/orchestration.md").read_text()
        for phrase in (
            "bounded autonomous repair mandate",
            "globally authorized by this policy",
            "concrete, evidenced, reachable issue",
            "uniquely determined low-risk fix restoring approved intent",
            "no new product interpretation, requirements, business rules, public contracts",
            "dependencies, architecture, security boundary, or scope",
            "Fix risk is distinct from finding severity",
            "not a blanket Low/Medium auto-fix rule",
            "stable finding ID, evidence, fix-risk, mandate rationale, owner, budget, and checks",
            "One bounded autonomous reviewer remediation round per review unit",
            "independent validation and targeted re-review",
            "No multiplying the budget by renaming findings or using a new reviewer",
            "New security or data-loss findings stop progress and escalate",
            "exact deterministic criterion and repair were preapproved",
            "outside the mandate, ambiguity, residual/unresolved issues, or budget exhaustion",
            "In-scope autonomously fixed items are reported, not retrospectively re-approved",
            "For nonmandated actionable findings",
            "silence is not approval",
            "Declined findings stay declined",
        ):
            self.assertIn(phrase, policy)
        for obsolete in (
            "Only an acceptance blocker may enter automatic repair",
            "Automatic repair handoffs are valid only for an acceptance blocker",
            "Do not delegate fixes until the user answers.",
            "even this narrow exception may enter automatic repair only",
            "only when it is a deterministic acceptance blocker",
        ):
            self.assertNotIn(obsolete, policy)
        for role in ("worker", "worker-complex"):
            contract = (ROOT / "roles" / f"{role}.md").read_text()
            self.assertIn("orchestrator-authorized bounded autonomous repair mandate", contract)
            self.assertIn("stable finding ID, evidence, fix-risk, mandate rationale, owner, budget, and checks", contract)
            self.assertIn("independent validation and one fresh-context AI review", contract)
        reviewer = (ROOT / "roles/reviewer.md").read_text()
        self.assertIn("only the orchestrator classifies and authorizes the bounded mandate", reviewer)
        self.assertNotIn("for each non-blocker finding before delegating", reviewer)

    def test_stack_and_completion_require_revision_bound_integration_and_human_decisions(self):
        """Fails when green units imply a green stack or a worker summary replaces the packet."""
        policy = (ROOT / "policy/orchestration.md").read_text()
        for phrase in (
            "Keep implementation and its tests together",
            "actual dependencies only",
            "per-unit validation and AI review do not prove full-stack integration",
            "proportionate integration validation of the full stack at the exact relevant revision",
            "high-risk dependency's human gate cannot be bypassed by preparing downstream code",
            "### Completion evidence and decision packet",
            "assembled by the orchestrator, not merely copied from a worker summary",
            "outcome and risk rationale",
            "actual validator and reviewer proof",
            "exact human review hotspots with reasons",
            "decisions/blockers and unverified aspects",
            "exact SHA or local diff revision",
            "later edits, rebase, or integration invalidate affected proof",
            "Short chat completion reports are standard",
            "HTML remains optional on explicit current request",
        ):
            self.assertIn(phrase, policy)
        planner = (ROOT / "roles/planner.md").read_text()
        self.assertIn("preliminary per-unit risk", planner)
        self.assertIn("global standing authorization", planner)
        self.assertNotIn("reviewer participation as explicitly user-authorized", planner)
        workflow = (ROOT / "policy/workflows/feature-workflow-pilot.md").read_text()
        self.assertNotIn("Every other actionable finding requires its own individual choice", workflow)
        self.assertNotIn("review remains separately authorized", workflow)

    def test_pre_post_reports_communicate_risk_and_proof_without_granting_authority(self):
        """Fails if optional HTML hides missing review or invents PRE, proof, or approval."""
        skill = " ".join((ROOT / "skills/change-report/SKILL.md").read_text().split())
        readme = " ".join((ROOT / "README.md").read_text().split())
        for phrase in (
            "preliminary per-unit low/standard/high risk",
            "proposed autonomy limits",
            "intended human review",
            "expected independent validator, fresh-context AI-review, and integration proofs",
            "report itself never grants authority",
            "after implementation, independent validation, and AI review",
            "top concise decision packet assembled by the orchestrator",
            "final risks versus the PRE baseline",
            "actual per-unit validator/reviewer evidence and full-stack integration",
            "automatic repairs and their mandate",
            "exact human review hotspots with reasons",
            "residual decisions/blockers and unverified aspects",
            "exact SHA or local diff revision",
            "later edits, rebase, or integration stale affected proof",
            "Short chat completion reports are standard",
            "HTML is optional and requires an explicit current-user request",
            "Never backfill or fabricate a PRE",
            "Do not mutate project source",
        ):
            self.assertIn(phrase, skill)
        for phrase in (
            "Global AI-first risk-based review",
            "standing policy authorization across all profiles",
            "one fresh-context AI reviewer",
            "bounded autonomous repair mandate",
            "PRE adds preliminary per-unit risk",
            "POST follows implementation, independent validation, and AI review",
            "exact SHA or local diff revision",
            "no auto-merge",
        ):
            self.assertIn(phrase, readme)
        self.assertNotIn("bounded low- or medium-risk change", readme)

    def test_review_unit_risk_is_independent_of_worker_label_and_diff_size(self):
        """Fails if AI approval substitutes for human gates or uncertainty can be low risk."""
        policy = (ROOT / "policy/orchestration.md").read_text()
        for phrase in (
            "blast radius, reversibility, and verifiability, not line count or worker label",
            "orchestrator assigns preliminary risk",
            "independent reviewer verifies it and may raise it",
            "Uncertainty is not low risk",
            "Low: local, reversible, and unambiguous",
            "no mandatory human full-diff reading",
            "Standard: targeted human review",
            "High: mandatory explicit human gate",
            "detailed critical-path review",
            "authentication, authorization, permissions, secrets",
            "payments, financial behavior, or sensitive data",
            "migrations, persistence, destructive operations, or recovery",
            "hard concurrency", "public contracts", "infrastructure or release",
            "orchestration, role, or model policy itself",
            "AI pass is neither human review nor human approval",
        ):
            self.assertIn(phrase, policy)
        reviewer = (ROOT / "roles/reviewer.md").read_text()
        self.assertIn("verify the preliminary low/standard/high risk tier", reviewer)


if __name__ == "__main__":
    unittest.main()
