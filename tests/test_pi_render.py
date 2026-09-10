import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "adapters" / "pi" / "render.py"


class PiRenderTests(unittest.TestCase):
    def test_renderer_emits_complete_openai_pi_bundle(self):
        """This test will fail when the Pi bundle omits a canonical artifact or role."""
        with (ROOT / "policy" / "routing.toml").open("rb") as handle:
            routing_roles = tomllib.load(handle)["roles"]
            roles = set(routing_roles)
        with (ROOT / "profiles" / "openai.toml").open("rb") as handle:
            profile = tomllib.load(handle)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pi"
            result = subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {path.stem for path in (output / "agents").glob("*.md")}, roles
            )
            self.assertTrue((output / "_shared" / "orchestration-core.md").is_file())
            self.assertTrue((output / "_shared" / "control-plane.json").is_file())
            self.assertTrue((output / "workflows" / "feature-workflow-pilot.md").is_file())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["roles"], sorted(roles))
            self.assertEqual(manifest["profiles"], ["openai"])
            for role, config in routing_roles.items():
                content = (output / "agents" / f"{role}.md").read_text()
                frontmatter = content.split("---", 2)[1]
                expected_tools = ["read", "grep", "find", "ls"]
                if config["edit"] == "allow":
                    expected_tools += ["edit", "write"]
                if config["bash"] == "allow":
                    expected_tools.append("bash")
                if set(config.get("delegates", [])) & {"explorer", "spec-writer"}:
                    expected_tools.append("subagent")
                model = profile["models"][role]
                self.assertIn(
                    f"model: openai-codex/{model['model'].removeprefix('openai/')}",
                    frontmatter,
                )
                self.assertIn(f"thinking: {model['variant']}", frontmatter)
                self.assertIn(f"tools: {', '.join(expected_tools)}", frontmatter)
                self.assertIn("defaultContext: fresh", frontmatter)
                self.assertIn("inheritProjectContext: false", frontmatter)
                self.assertIn("inheritSkills: false", frontmatter)
                self.assertNotIn("extensions:", frontmatter)
                self.assertIn((ROOT / "roles" / f"{role}.md").read_text(), content)

    def test_bundle_documents_pi_permission_and_control_plane_degradation(self):
        """This test will fail when operators cannot see Pi's unavoidable semantic gaps."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pi"
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )

            note = (output / "_shared" / "degradations.md").read_text().lower()
            self.assertIn("permissions.bash", note)
            self.assertIn("permission wrapper", note)
            self.assertIn("omits `bash`", note)
            self.assertIn("primary", note)
            self.assertIn("not installed", note)


if __name__ == "__main__":
    unittest.main()
