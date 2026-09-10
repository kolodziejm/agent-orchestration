import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "adapters" / "pi" / "render.py"


EXPECTED = {
    "openai": {
        "provider": "openai-codex/",
        "efforts": {
            "worker": "high", "worker-complex": "medium", "validator": "medium",
            "debugger": "high", "explorer": "medium", "planner": "high",
            "spec-writer": "medium", "design-partner": "high", "reviewer": "high",
            "ux-critic": "high",
        },
    },
    "deepseek": {
        "provider": "deepseek/",
        "efforts": {
            "worker": "high", "worker-complex": "max", "validator": "high",
            "debugger": "max", "explorer": "low", "planner": "max",
            "spec-writer": "low", "design-partner": "high", "reviewer": "max",
            "ux-critic": "high",
        },
    },
}


class PiRenderTests(unittest.TestCase):
    def test_renderer_bootstraps_no_pi_sandbox_for_either_profile(self):
        """This test will fail when either Pi profile bundle loads the removed sandbox integration."""
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bundle = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
                self.assertNotIn("pi-sandbox", bundle)

    def test_renderer_emits_isolated_exact_profile_routing(self):
        """This test will fail when either Pi profile routes a role to the wrong model or effort."""
        for profile_name, expected in EXPECTED.items():
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["profiles"], [profile_name])
                for role, effort in expected["efforts"].items():
                    frontmatter = (output / "agents" / f"{role}.md").read_text().split("---", 2)[1]
                    model = "deepseek-flash" if profile_name == "deepseek" else None
                    if model:
                        self.assertIn(f"model: {expected['provider']}{model}", frontmatter)
                    else:
                        self.assertIn(f"model: {expected['provider']}", frontmatter)
                    self.assertIn(f"thinking: {effort}", frontmatter)

                control = json.loads((output / "_shared" / "control-plane.json").read_text())
                if profile_name == "deepseek":
                    self.assertEqual(control["primary"], {"model": "deepseek/deepseek-flash", "thinking": "high"})
                    self.assertEqual(control["small_model"], "deepseek/deepseek-flash")
                    self.assertEqual(control["builtins"]["build"], {"model": "deepseek/deepseek-flash", "thinking": "high"})
                    self.assertEqual(control["builtins"]["plan"], {"model": "deepseek/deepseek-flash", "thinking": "max"})

    def test_renderer_fails_closed_for_unknown_profile_and_provider_mismatch(self):
        """This test will fail when unsupported Pi profiles or provider tokens are guessed."""
        result = subprocess.run(
            [sys.executable, str(RENDER), "--profile", "unknown", "--output", tempfile.gettempdir() + "/pi-unknown"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported Pi profile", result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            for name in ("adapters", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            profile = repo / "profiles" / "openai.toml"
            profile.write_text(profile.read_text().replace("openai/gpt-5.6-luna", "deepseek/deepseek-flash", 1))
            result = subprocess.run(
                [sys.executable, str(repo / "adapters/pi/render.py"), "--profile", "openai", "--output", str(Path(directory) / "out")],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires an openai/<model-id>", result.stderr)

    def test_launchers_select_roots_share_sessions_forward_args_and_contain_no_credentials(self):
        """This test will fail when a launcher leaks state, drops arguments, or embeds credentials."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_pi = fake_home / ".nvm/versions/node/v24.15.0/bin/pi"
            fake_pi.parent.mkdir(parents=True)
            fake_pi.write_text("#!/bin/sh\nprintf '%s\\n' \"$PI_CODING_AGENT_DIR\" \"$PI_CODING_AGENT_SESSION_DIR\" \"$@\"\n")
            fake_pi.chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(fake_home)
            for profile_name, expected_root in (
                ("openai", fake_home / ".pi/agent"),
                ("deepseek", fake_home / ".pi/profiles/deepseek"),
            ):
                output = root / profile_name
                subprocess.run([sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)], check=True)
                launcher = output / f"pi-{profile_name}"
                self.assertTrue(os.access(launcher, os.X_OK))
                content = launcher.read_text().lower()
                for secret in ("api_key", "token=", "authorization:", "auth.json"):
                    self.assertNotIn(secret, content)
                result = subprocess.run([str(launcher), "--prompt", "two words", "--", "literal"], env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(lines[:2], [str(expected_root), str(fake_home / ".pi/agent/sessions")])
                self.assertEqual(lines[-4:], ["--prompt", "two words", "--", "literal"])
            fake_pi.unlink()
            missing = subprocess.run(
                [str(root / "openai" / "pi-openai")],
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(missing.returncode, 127)
            self.assertIn(str(fake_pi), missing.stderr)

    def test_command_capable_ask_roles_get_bash_without_widening_other_roles(self):
        """This test will fail when Pi drops required shell access or widens another ask role."""
        expected_tools = {
            "validator": "read, grep, find, ls, bash",
            "debugger": "read, grep, find, ls, bash",
            "planner": "read, grep, find, ls, edit, write, bash, subagent",
            "reviewer": "read, grep, find, ls, subagent",
            "explorer": "read, grep, find, ls",
            "spec-writer": "read, grep, find, ls, edit, write",
        }
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                for role, tools in expected_tools.items():
                    frontmatter = (output / "agents" / f"{role}.md").read_text().split("---", 2)[1]
                    tools_line = next(line for line in frontmatter.splitlines() if line.startswith("tools: "))
                    self.assertEqual(tools_line, f"tools: {tools}")

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
                if config["bash"] == "allow" or role in {"validator", "debugger", "planner"}:
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
