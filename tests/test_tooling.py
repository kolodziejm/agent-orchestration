import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolingContractTests(unittest.TestCase):
    def test_render_and_check_entrypoints_validate_pi_snapshot_in_isolation(self):
        """This test will fail when Pi entrypoints stop producing or checking the snapshot."""
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory) / "project"
            shutil.copytree(
                ROOT,
                isolated,
                ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"),
            )
            python_stub = Path(directory) / "python-stub"
            python_stub.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "-m" ] && [ "$2" = "unittest" ]; then exit 0; fi\n'
                f"exec {shlex.quote(sys.executable)} \"$@\"\n"
            )
            python_stub.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "AGENT_ORCHESTRATION_UV_RUN": "1",
                    "PYTHON": str(python_stub),
                }
            )

            for entrypoint in ("render", "check", "install-pi"):
                self.assertTrue(
                    os.access(isolated / "scripts" / entrypoint, os.X_OK),
                    f"{entrypoint} is not executable",
                )

            rendered = subprocess.run(
                [str(isolated / "scripts" / "render")],
                cwd=isolated,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            manifest = json.loads(
                (isolated / "generated" / "pi" / "manifest.json").read_text()
            )
            self.assertEqual(manifest["adapter"], "pi-subagents")
            self.assertEqual(manifest["adapter_format"], "0.67.0")
            self.assertTrue(manifest["roles"])
            self.assertTrue(
                (isolated / "generated" / "pi" / "agents" / "worker.md").is_file()
            )

            checked = subprocess.run(
                [str(isolated / "scripts" / "check")],
                cwd=isolated,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_uv_project_declares_supported_python_and_pinned_test_dependency(self):
        """This test will fail when the documented reproducible uv environment is missing."""
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)

        metadata = project["project"]
        self.assertEqual(metadata["requires-python"], ">=3.11")
        dependencies = set(metadata.get("dependencies", []))
        dependency_groups = project.get("dependency-groups", {})
        dev_dependencies = set(dependency_groups.get("dev", []))
        self.assertTrue(
            "PyYAML==6.0.2" in dependencies or "PyYAML==6.0.2" in dev_dependencies
        )
        self.assertTrue((ROOT / "uv.lock").is_file())

    def test_source_validation_command_accepts_all_versioned_profiles(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "adapters" / "validate.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validated", result.stdout.lower())

    def test_ci_exercises_the_reproducible_uv_check_entrypoint(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("astral-sh/setup-uv", workflow)
        self.assertIn("uv run --locked ./scripts/check", workflow)


if __name__ == "__main__":
    unittest.main()
