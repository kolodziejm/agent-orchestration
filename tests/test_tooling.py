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
    def test_generate_and_check_entrypoints_validate_pi_output_in_isolation(self):
        """This test will fail when Pi entrypoints stop generating or checking the untracked output."""
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

            for entrypoint in ("generate", "check", "install-pi"):
                self.assertTrue(
                    os.access(isolated / "scripts" / entrypoint, os.X_OK),
                    f"{entrypoint} is not executable",
                )

            generated = subprocess.run(
                [str(isolated / "scripts" / "generate")],
                cwd=isolated,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            for profile in ("openai", "deepseek"):
                manifest = json.loads(
                    (isolated / "build" / "pi" / profile / "manifest.json").read_text()
                )
                self.assertEqual(manifest["format_version"], 1)
                self.assertNotIn("adapter", manifest)
                self.assertNotIn("adapter_format", manifest)
                self.assertEqual(manifest["profiles"], [profile])
                self.assertTrue(manifest["roles"])
                self.assertTrue(
                    (isolated / "build" / "pi" / profile / "agents" / "worker.md").is_file()
                )
                for guidance in ("degradations.md", "control-plane.json"):
                    content = (
                        isolated / "build" / "pi" / profile / "_shared" / guidance
                    ).read_text()
                    self.assertNotIn("pi-subagents", content)
                    self.assertNotIn("0.67.0", content)

            readme = (isolated / "README.md").read_text()
            for phrase in (
                "internal orchestration bundle schema",
                "manifest-owned policy, agent, workflow, extension, and launcher artifacts",
                "does not install, select, migrate, or validate framework packages",
                "settings, catalogs, auth, MCP, themes, and provider state",
                "Active Tintinweb and other runtime packages remain operator-owned",
            ):
                self.assertIn(phrase, readme)
            self.assertNotIn("--source", readme)
            self.assertNotIn("--base", readme)
            self.assertNotIn("bootstrap", readme.lower())

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
        self.assertIn("jsonschema==4.25.1", dev_dependencies)
        self.assertIn("jsonschema==4.25.1", (ROOT / "requirements-dev.txt").read_text())
        lock_text = (ROOT / "uv.lock").read_text()
        self.assertIn('name = "jsonschema"', lock_text)
        self.assertIn('specifier = "==4.25.1"', lock_text)
        self.assertTrue((ROOT / "uv.lock").is_file())

    def test_source_validation_command_accepts_all_versioned_profiles(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "harnesses" / "validate.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validated", result.stdout.lower())

    def test_generate_defaults_to_untracked_build_and_check_verifies_two_root_determinism(self):
        """This test will fail when generation writes tracked snapshots or check depends on repo output."""
        generate = (ROOT / "scripts" / "generate").read_text()
        self.assertIn('OUTPUT_ROOT="${1:-$ROOT/build}"', generate)
        self.assertNotIn("generated/", generate)

        check = (ROOT / "scripts" / "check").read_text()
        self.assertIn('FIRST="$TMP/first"', check)
        self.assertIn('SECOND="$TMP/second"', check)
        self.assertIn('generate_all "$FIRST"', check)
        self.assertIn('generate_all "$SECOND"', check)
        self.assertIn('diff -ruN "$FIRST/$output" "$SECOND/$output"', check)
        self.assertNotIn("generated/", check)

        ignored = (ROOT / ".gitignore").read_text().splitlines()
        self.assertIn("build/", ignored)
        self.assertIn("generated/", ignored)

    def test_ci_exercises_the_reproducible_uv_check_entrypoint(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("astral-sh/setup-uv", workflow)
        self.assertIn("uv run --locked ./scripts/check", workflow)
        self.assertIn("generated-output determinism", workflow)


if __name__ == "__main__":
    unittest.main()
