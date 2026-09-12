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
                "worker-complex": ("openai/gpt-5.6-luna", "max"),
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
        self.assertIn("Independent ready mutation lanes are parallel-by-default", policy)
        self.assertIn("safe isolation", policy)
        self.assertIn("record a concise reason", policy)
        self.assertIn("broad mechanical evidence gathering", policy)
        self.assertIn("two or three genuinely independent evidence scopes", policy)
        self.assertIn("`worker` and `worker-complex` may author or update tests", policy)
        self.assertIn("must not execute tests, lint, typecheck, build, browser/device checks", policy)
        self.assertIn("`validator` exclusively executes verification", policy)
        self.assertNotIn("SELF-CHECK", policy)
        self.assertNotIn("self-check", policy)

        for contradictory_wording in (
            "low- or medium-risk",
            "Everything else is non-trivial",
            "Apart from trivial work",
            "For a trivial inline edit as defined above",
            "After implementation, give `validator`",
        ):
            self.assertNotIn(contradictory_wording, policy)

    def test_role_contracts_separate_authoring_acceptance_and_heuristic_ux_audits(self):
        worker = (ROOT / "roles" / "worker.md").read_text()
        complex_worker = (ROOT / "roles" / "worker-complex.md").read_text()
        validator = (ROOT / "roles" / "validator.md").read_text()
        ux_critic = (ROOT / "roles" / "ux-critic.md").read_text()
        planner = (ROOT / "roles" / "planner.md").read_text()
        reviewer = (ROOT / "roles" / "reviewer.md").read_text()

        for contract in (worker, complex_worker):
            self.assertIn("author or update tests", contract)
            self.assertIn("must not execute tests, lint, typecheck, build, browser/device checks", contract)
            self.assertNotIn("SELF-CHECK", contract)
            self.assertNotIn("self-check", contract)
        self.assertIn("predefined deterministic acceptance", validator)
        self.assertIn("browser/device checks", validator)
        self.assertIn("`PASS`, `FAIL`, or `BLOCKED`", validator)
        self.assertIn("heuristic usability, accessibility, platform-fit, and parity", ux_critic)
        self.assertIn("explicitly requests or authorizes", ux_critic)
        self.assertIn("primary orchestrator", ux_critic)
        self.assertIn("Never run automatically after implementation, validation, or review", ux_critic)
        self.assertIn("target flow and named web/mobile surfaces", ux_critic)
        self.assertIn("already-running web URL", ux_critic)
        self.assertIn("already-prepared Appium session and device", ux_critic)
        self.assertIn("screenshot artifact destination", ux_critic)
        self.assertIn("physically traverse", ux_critic.casefold())
        self.assertIn("meaningful checkpoints", ux_critic)
        self.assertIn("native vision", ux_critic)
        self.assertIn("STATUS: BLOCKED", ux_critic)
        self.assertIn("Do not execute automated tests, lint, typecheck, formatters, builds", ux_critic)
        self.assertIn("mechanical release gate", ux_critic)
        self.assertIn("close implementation acceptance", ux_critic)

        routing = tomllib.loads((ROOT / "policy" / "routing.toml").read_text())
        self.assertEqual(routing["roles"]["ux-critic"]["edit"], "deny")
        self.assertEqual(routing["roles"]["ux-critic"]["bash"], "deny")
        orchestration = (ROOT / "policy" / "orchestration.md").read_text()
        self.assertIn("On-demand UX critic authorization and handoff", orchestration)
        self.assertIn("must never be launched automatically after implementation, validation, or review", orchestration)
        for contract in (planner, reviewer):
            self.assertIn("broad mechanical evidence gathering", contract)
            self.assertIn("two or three genuinely independent evidence scopes", contract)
            self.assertIn("parallel fanout", contract)

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
