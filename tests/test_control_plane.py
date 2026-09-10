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
                if name == "deepseek"
                else {"low", "medium", "high", "max", "xhigh"}
            )
            self.assertEqual(set(supported), expected_supported, name)

        openai = profiles["openai"]
        expected = {
            "primary": {"model": "openai/gpt-5.6-sol", "effort": "medium"},
            "small_model": "openai/gpt-5.6-luna",
            "builtins": {
                "build": {"model": "openai/gpt-5.6-sol", "effort": "medium"},
                "plan": {"model": "openai/gpt-5.6-sol", "effort": "high"},
            },
        }
        self.assertEqual(openai["control_plane"], expected)

        self.assertEqual(
            {
                role: (config["model"], config.get("variant"))
                for role, config in openai["models"].items()
            },
            {
                "worker": ("openai/gpt-5.6-luna", "high"),
                "worker-complex": ("openai/gpt-5.6-sol", "medium"),
                "debugger": ("openai/gpt-5.6-sol", "high"),
                "explorer": ("openai/gpt-5.6-luna", "medium"),
                "validator": ("openai/gpt-5.6-luna", "medium"),
                "planner": ("openai/gpt-5.6-sol", "high"),
                "reviewer": ("openai/gpt-5.6-sol", "high"),
                "spec-writer": ("openai/gpt-5.6-luna", "medium"),
                "design-partner": ("openai/gpt-5.6-luna", "high"),
                "ux-critic": ("openai/gpt-5.6-luna", "high"),
            },
        )

    def test_renderers_reject_a_profile_with_missing_control_plane_effort(self):
        """This test will fail when a renderer silently ignores incomplete control-plane intent."""
        renderers = (
            ROOT / "adapters" / "opencode" / "render.py",
            ROOT / "adapters" / "codex" / "render.py",
            ROOT / "adapters" / "claude-code" / "render.py",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("adapters", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            for profile_name in ("openai", "claude"):
                profile = repo / "profiles" / f"{profile_name}.toml"
                lines = profile.read_text().splitlines()
                lines.remove(next(line for line in lines if line.startswith("effort =")))
                profile.write_text("\n".join(lines) + "\n")

            for renderer in renderers:
                output = root / renderer.parent.name
                command = [sys.executable, str(repo / renderer.relative_to(ROOT)), "--output", str(output)]
                if renderer.parent.name == "codex":
                    command.extend(["--profile", "openai"])
                result = subprocess.run(command, cwd=repo, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0, renderer)
                self.assertIn("control", result.stderr.lower(), renderer)
                self.assertFalse(output.exists(), renderer)

    def test_core_policy_defaults_to_delegation_with_a_narrow_direct_work_exception(self):
        """This test will fail when direct primary work is broader than the approved exception."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()

        self.assertIn("Delegation is the default for repository discovery and source work.", policy)
        self.assertIn("small, clearly bounded, low-risk task", policy)
        self.assertIn("when delegation offers no concrete leverage", policy)
        self.assertIn("Before acting directly, the primary must briefly state why delegation is not useful.", policy)
        self.assertIn("broader discovery", policy)
        self.assertIn("multi-area or behavior-changing work", policy)
        self.assertIn("uncertain or context-heavy work", policy)
        self.assertIn("specialist", policy)
        self.assertIn("parallelism", policy)
        self.assertIn("independent risk separation", policy)
        self.assertIn("Delegated source-changing worker output always requires independent validator verification.", policy)

        for contradictory_wording in (
            "low- or medium-risk",
            "Everything else is non-trivial",
            "Apart from trivial work",
            "For a trivial inline edit as defined above",
            "After implementation, give `validator`",
        ):
            self.assertNotIn(contradictory_wording, policy)

    def test_renderers_reject_unsupported_effort_without_querying_provider_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("adapters", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            for profile_name in ("openai", "claude"):
                profile = repo / "profiles" / f"{profile_name}.toml"
                lines = profile.read_text().splitlines()
                for index, line in enumerate(lines):
                    if line.startswith("variant ="):
                        lines[index] = 'variant = "provider-catalog-only"'
                        break
                profile.write_text("\n".join(lines) + "\n")

            renderers = (
                ("opencode", ["adapters/opencode/render.py"]),
                ("codex", ["adapters/codex/render.py", "--profile", "openai"]),
                ("claude-code", ["adapters/claude-code/render.py"]),
            )
            for name, args in renderers:
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

    def test_renderers_reject_effort_not_declared_by_the_selected_profile(self):
        """This test will fail when adapters trust an unverified profile effort declaration."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("adapters", "policy", "profiles", "roles"):
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
                    str(repo / "adapters" / "opencode" / "render.py"),
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
