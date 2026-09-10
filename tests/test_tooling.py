import tomllib
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolingContractTests(unittest.TestCase):
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
