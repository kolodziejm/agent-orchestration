import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "policy" / "workflows" / "feature-workflow-pilot.md"
POLICY = ROOT / "policy" / "orchestration.md"


class FeatureWorkflowArtifactTests(unittest.TestCase):
    def test_feature_workflow_is_packaged_separately_without_inlining_into_base_prompts(self):
        """This test will fail when the detailed pilot remains in every base prompt."""
        self.assertTrue(WORKFLOW.is_file())
        workflow = WORKFLOW.read_text()
        policy = POLICY.read_text()
        self.assertIn("# Feature Workflow Pilot", workflow)
        self.assertNotIn("# Feature Workflow Pilot", policy)
        self.assertIn("workflows/feature-workflow-pilot.md", policy)
        self.assertIn("optional", policy.lower())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = {}
            commands = {
                "opencode": [ROOT / "adapters" / "opencode" / "render.py"],
                "codex": [ROOT / "adapters" / "codex" / "render.py", "--profile", "openai"],
                "claude-code": [ROOT / "adapters" / "claude-code" / "render.py"],
            }
            for name, parts in commands.items():
                output = root / name
                result = subprocess.run(
                    [sys.executable, *map(str, parts), "--output", str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs[name] = output

            self.assertEqual(
                (outputs["opencode"] / "workflows" / "feature-workflow-pilot.md").read_text(),
                workflow,
            )
            self.assertEqual(
                (outputs["codex"] / "workflows" / "feature-workflow-pilot.md").read_text(),
                workflow,
            )
            self.assertEqual(
                (outputs["claude-code"] / "workflows" / "feature-workflow-pilot.md").read_text(),
                workflow,
            )
            self.assertNotIn("# Feature Workflow Pilot", (outputs["opencode"] / "profiles" / "_shared" / "orchestration-core.md").read_text())
            self.assertNotIn("# Feature Workflow Pilot", (outputs["codex"] / "AGENTS.md").read_text())
            self.assertNotIn("# Feature Workflow Pilot", (outputs["claude-code"] / "_shared" / "orchestration-core.md").read_text())

            self.assertEqual(
                json.loads((outputs["opencode"] / "manifest.json").read_text())["workflows"],
                ["feature-workflow-pilot"],
            )


if __name__ == "__main__":
    unittest.main()
