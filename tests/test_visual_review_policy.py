"""Prompt contracts, not runtime proof: fail if visual-first review is lost."""
import unittest
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VisualReviewPolicyTests(unittest.TestCase):
    def test_change_map_precedes_human_findings_without_trivial_change_ceremony(self):
        policy = (ROOT / "policy/orchestration.md").read_text()
        for phrase in (
            "### Visual-first human review",
            "compact change map before findings",
            "multi-part structural or logic changes",
            "changed and unchanged pieces",
            "flows and decision hotspots",
            "flow, sequence, state, component, or dependency diagram",
            "not the whole system",
            "Trivial changes need no diagram",
            "not a diagram for every Low finding",
            "After the proportional change map and available visual evidence",
        ):
            self.assertIn(phrase, policy)
        self.assertNotIn("must first present a visible `Reviewer findings`", policy)

    def test_runtime_evidence_is_observed_temporary_and_published_only_to_authorized_target(self):
        policy = (ROOT / "policy/orchestration.md").read_text()
        for phrase in (
            "genuine comparable before/after runtime screenshots",
            "loading, empty, and error states",
            "short recording only when temporal behavior matters",
            "Never fabricate a before baseline",
            "exact revision, scenario, and viewport",
            "harness-managed temporary directory outside repositories and worktrees",
            "Never create or commit standalone screenshot/video evidence binaries",
            "no `.gitignore` changes",
            "native GitHub attachments",
            "one owned updateable `Visual review` comment",
            "exact target comment",
            "preserve human-authored content",
            "gh pr create/edit/comment --attach",
            "matching local Markdown paths",
            "read back the exact target",
            "retry only missing attachments",
            "not arbitrary remote publication or PR creation",
            "public repository attachments are public",
            "Missing tools, permissions, runtime, UI data, or a PR",
            "no forced PR creation",
        ):
            self.assertIn(phrase, policy)
        skill = (ROOT / "skills/change-report/SKILL.md").read_text()
        for phrase in (
            "compact change map before findings",
            "self-contained data URIs",
            "links to verified GitHub evidence without external embeds",
            "explicitly requested HTML",
            "Never fabricate a before baseline",
        ):
            self.assertIn(phrase, skill)


    def test_all_harness_profiles_render_visual_policy_and_role_ownership(self):
        """Fails if any packaged core/role drops the global evidence responsibility."""
        policy = (ROOT / "policy/orchestration.md").read_text()
        block = policy.split("### Visual-first human review\n", 1)[1].split("### Stacked PR titles", 1)[0]
        workflow = (ROOT / "policy/workflows/feature-workflow-pilot.md").read_text()
        commands = [
            ("opencode", []),
            ("codex", ["--profile", "openai"]),
            ("claude-code", []),
            *[(harness, ["--profile", profile]) for harness in ("pi", "omp")
              for profile in ("hybrid", "openai", "deepseek", "glm")],
        ]
        with tempfile.TemporaryDirectory(prefix="visual-review-") as directory:
            for index, (harness, args) in enumerate(commands):
                with self.subTest(harness=harness, args=args):
                    output = Path(directory) / str(index)
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "harnesses" / harness / "generate.py"),
                         *args, "--output", str(output)],
                        cwd=ROOT, text=True, capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    rendered = "\n".join(path.read_text() for path in output.rglob("*")
                                         if path.is_file() and path.suffix in (".md", ".toml"))
                    self.assertTrue(block in rendered, "Visual-first canonical block missing")
                    self.assertTrue("Validator owns runtime captures and visual proof" in rendered,
                                    "Validator visual-evidence ownership missing")
                    self.assertTrue("Reference visual paths/states and validator evidence" in rendered,
                                    "Reviewer read-only visual interpretation missing")
                    self.assertIn("canonical visual-first human review contract", workflow)
                    # OMP packages core/roles but has no optional-workflow artifact.
                    if harness != "omp":
                        self.assertEqual((output / "workflows/feature-workflow-pilot.md").read_text(), workflow)


if __name__ == "__main__":
    unittest.main()
