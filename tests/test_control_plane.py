import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"


class ProfileControlPlaneTests(unittest.TestCase):
    def test_profiles_are_versioned_and_openai_control_plane_is_explicit(self):
        profiles = {}
        for path in PROFILES.glob("*.toml"):
            with path.open("rb") as handle:
                profiles[path.stem] = tomllib.load(handle)

        self.assertNotIn("pi", profiles)
        self.assertGreaterEqual(len(profiles), 3)

        for name, profile in profiles.items():
            self.assertEqual(profile["version"], 1, name)
            control_plane = profile["control_plane"]
            self.assertEqual(set(control_plane), {"primary", "small_model", "builtins"}, name)
            self.assertEqual(set(control_plane["primary"]), {"model", "effort"}, name)
            self.assertIsInstance(control_plane["small_model"], str)
            self.assertEqual(set(control_plane["builtins"]), {"build", "plan"}, name)
            for builtin in control_plane["builtins"].values():
                self.assertEqual(set(builtin), {"model", "effort"}, name)
            supported = profile["capabilities"]["supported_variants"]
            expected_supported = (
                {"low", "high", "max"}
                if name in {"deepseek", "pi-glm", "dsh"}
                else {"low", "medium", "high", "max", "xhigh"}
            )
            self.assertEqual(set(supported), expected_supported, name)

        openai = profiles["openai"]
        expected = {
            "primary": {"model": "openai/gpt-6.1-sol", "effort": "medium"},
            "small_model": "openai/gpt-6-luna",
            "builtins": {
                "build": {"model": "openai/gpt-6.1-sol", "effort": "medium"},
                "plan": {"model": "openai/gpt-6.1-sol", "effort": "high"},
            },
        }
        self.assertEqual(openai["control_plane"], expected)

        self.assertEqual(
            {
                role: (config["model"], config.get("variant"))
                for role, config in openai["models"].items()
            },
            {
                "worker": ("openai/gpt-6-luna", "high"),
                "worker-complex": ("openai/gpt-6-luna", "max"),
                "debugger": ("openai/gpt-6.1-sol", "high"),
                "explorer": ("openai/gpt-6-luna", "medium"),
                "validator": ("openai/gpt-6-luna", "medium"),
                "planner": ("openai/gpt-6.1-sol", "high"),
                "reviewer": ("openai/gpt-6.1-sol", "high"),
                "design-partner": ("openai/gpt-6-luna", "high"),
                "ux-critic": ("openai/gpt-6-luna", "high"),
            },
        )

        glm = profiles["pi-glm"]
        self.assertEqual(glm["control_plane"], {
            "primary": {"model": "zai/glm-5.3", "effort": "high"},
            "small_model": "zai/glm-5.3-flash",
            "builtins": {
                "build": {"model": "zai/glm-5.3", "effort": "high"},
                "plan": {"model": "zai/glm-5.3", "effort": "high"},
            },
        })
        sol_roles = {"debugger", "planner", "reviewer"}
        for role, config in glm["models"].items():
            expected_model = (
                "zai/glm-5.3"
                if role in sol_roles
                else "zai/glm-5.3-flash"
            )
            expected_variant = "max" if role == "worker-complex" else "high"
            self.assertEqual((config["model"], config["variant"]), (expected_model, expected_variant), role)

    def test_generators_reject_a_profile_with_missing_control_plane_effort(self):
        """This test will fail when a generator silently ignores incomplete control-plane intent."""
        generators = (
            ROOT / "harnesses" / "opencode" / "generate.py",
            ROOT / "harnesses" / "codex" / "generate.py",
            ROOT / "harnesses" / "claude-code" / "generate.py",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("harnesses", "policy", "profiles"):
                shutil.copytree(ROOT / name, repo / name)
            for profile_name in ("openai", "claude", "dsh"):
                profile = repo / "profiles" / f"{profile_name}.toml"
                lines = profile.read_text().splitlines()
                lines.remove(next(line for line in lines if line.startswith("effort =")))
                profile.write_text("\n".join(lines) + "\n")

            for generator in generators:
                output = root / generator.parent.name
                command = [sys.executable, str(repo / generator.relative_to(ROOT)), "--output", str(output)]
                if generator.parent.name == "codex":
                    command.extend(["--profile", "openai"])
                result = subprocess.run(command, cwd=repo, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0, generator)
                self.assertIn("control", result.stderr.lower(), generator)
                self.assertFalse(output.exists(), generator)

    def test_ci_validates_pull_requests_and_main_pushes_without_duplicate_pr_pushes(self):
        """This fails when a pull-request branch also receives a duplicate push check."""
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("on:\n  pull_request:\n  push:\n    branches:\n      - main\n", workflow)
        self.assertNotIn("on:\n  push:\n  pull_request:", workflow)

    def test_generators_reject_unsupported_effort_without_querying_provider_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("harnesses", "policy", "profiles"):
                shutil.copytree(ROOT / name, repo / name)
            for profile_name in ("openai", "claude", "dsh"):
                profile = repo / "profiles" / f"{profile_name}.toml"
                lines = profile.read_text().splitlines()
                for index, line in enumerate(lines):
                    if line.startswith("variant ="):
                        lines[index] = 'variant = "provider-catalog-only"'
                        break
                profile.write_text("\n".join(lines) + "\n")

            generators = (
                ("opencode", ["harnesses/opencode/generate.py"]),
                ("codex", ["harnesses/codex/generate.py", "--profile", "openai"]),
                ("claude-code", ["harnesses/claude-code/generate.py"]),
                ("dsh", ["harnesses/dsh/generate.py", "--profile", "dsh"]),
            )
            for name, args in generators:
                output = root / name
                result = subprocess.run(
                    [sys.executable, *args, "--output", str(output)],
                    cwd=repo,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0, name)
                self.assertIn("unsupported", result.stderr.lower(), name)
                self.assertFalse(output.exists(), name)

    def test_generators_reject_effort_not_declared_by_the_selected_profile(self):
        """This test will fail when generators trust an unverified profile effort declaration."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("harnesses", "policy", "profiles"):
                shutil.copytree(ROOT / name, repo / name)
            profile = repo / "profiles" / "openai.toml"
            lines = profile.read_text().replace(
                'supported_variants = ["low", "medium", "high", "max", "xhigh"]',
                'supported_variants = ["medium"]',
            )
            profile.write_text(lines)
            output = root / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo / "harnesses" / "opencode" / "generate.py"),
                    "--output",
                    str(output),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported", result.stderr.lower())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
