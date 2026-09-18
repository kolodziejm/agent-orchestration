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
GENERATE = ROOT / "harnesses" / "pi" / "generate.py"


UX_CRITIC_TOOLS = [
    "read",
    "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_find",
    "browser_click", "browser_fill_form", "browser_type", "browser_press_key",
    "browser_select_option", "browser_hover", "browser_drag", "browser_mouse_wheel",
    "browser_wait_for", "browser_resize", "browser_take_screenshot", "browser_start_video",
    "browser_stop_video", "appium_get_active_element", "appium_find_element", "appium_get_text",
    "appium_get_element_attribute", "appium_get_page_source", "appium_gesture", "appium_drag_and_drop",
    "appium_set_value", "appium_mobile_press_key", "appium_mobile_keyboard", "appium_get_window_size",
    "appium_orientation", "appium_context", "appium_alert", "appium_screenshot", "appium_screen_recording",
]
VALIDATOR_MCP_TOOLS = [
    "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_find",
    "browser_click", "browser_fill_form", "browser_type", "browser_press_key",
    "browser_select_option", "browser_hover", "browser_drag", "browser_mouse_wheel",
    "browser_wait_for", "browser_resize", "browser_take_screenshot",
    "appium_get_active_element", "appium_find_element", "appium_get_text",
    "appium_get_element_attribute", "appium_get_page_source", "appium_gesture",
    "appium_drag_and_drop", "appium_set_value", "appium_mobile_press_key",
    "appium_mobile_keyboard", "appium_get_window_size", "appium_orientation",
    "appium_context", "appium_alert", "appium_screenshot",
]


EXPECTED = {
    "openai": {
        "models": {
            role: f"openai-codex/gpt-5.6-{'sol' if role in {'debugger', 'planner', 'reviewer'} else 'luna'}"
            for role in (
                "worker", "worker-complex", "validator", "debugger", "explorer",
                "planner", "design-partner", "reviewer", "ux-critic",
            )
        },
        "efforts": {
            "worker": "high", "worker-complex": "max", "validator": "medium",
            "debugger": "high", "explorer": "medium", "planner": "high",
            "design-partner": "high", "reviewer": "high",
            "ux-critic": "high",
        },
    },
    "hybrid": {
        "models": {
            role: (
                "openai-codex/gpt-5.6-sol"
                if role in {"planner", "reviewer"}
                else "deepseek/deepseek-flash"
            )
            for role in (
                "worker", "worker-complex", "validator", "debugger", "explorer",
                "planner", "design-partner", "reviewer", "ux-critic",
            )
        },
        "efforts": {
            "worker": "high", "worker-complex": "max", "validator": "high",
            "debugger": "high", "explorer": "low", "planner": "high",
            "design-partner": "high", "reviewer": "high",
            "ux-critic": "high",
        },
    },
    "deepseek": {
        "models": {role: "deepseek/deepseek-flash" for role in (
            "worker", "worker-complex", "validator", "debugger", "explorer",
            "planner", "design-partner", "reviewer", "ux-critic",
        )},
        "efforts": {
            "worker": "high", "worker-complex": "max", "validator": "high",
            "debugger": "max", "explorer": "low", "planner": "max",
            "design-partner": "high", "reviewer": "max",
            "ux-critic": "high",
        },
    },
    "glm": {
        "models": {
            "worker": "zai/glm-5.3-flash",
            "worker-complex": "zai/glm-5.3-flash",
            "validator": "zai/glm-5.3-flash",
            "debugger": "zai/glm-5.3",
            "explorer": "zai/glm-5.3-flash",
            "planner": "zai/glm-5.3",
            "design-partner": "zai/glm-5.3-flash",
            "reviewer": "zai/glm-5.3",
            "ux-critic": "zai/glm-5.3-flash",
        },
        "efforts": {
            "worker": "high", "worker-complex": "max", "validator": "high",
            "debugger": "high", "explorer": "high", "planner": "high",
            "design-partner": "high", "reviewer": "high",
            "ux-critic": "high",
        },
    },
}


class PiGenerateTests(unittest.TestCase):
    def test_readme_documents_profile_switching_and_native_cli_boundary(self):
        """Operators must know the exact process switch and the native CLI policy boundary."""
        readme = (ROOT / "README.md").read_text()
        for text in (
            "exit the current Pi process",
            "pi-hybrid",
            "pi-openai",
            "pi-deepseek",
            "pi-glm",
            "--model",
            "--thinking",
            "--append-system-prompt",
            "agent-orchestration/_shared/orchestration-core.md",
            "fails closed",
            "before_agent_start",
            "git-read.ts",
            "migration-only stale",
            "acceptanceRole: read-only",
            "acceptance inference only",
            "no hard read-only sandbox",
            "cannot forward an `ask` decision",
            "built-in `bash`",
            "policy-level",
            "framework-neutral",
            "not runtime enforcement",
            "exact child target `explorer`",
            "Pi subagent watchdog",
            "startup: 120 seconds",
            "idle: 5 minutes",
            "total runtime: 30 minutes",
            "subagents:rpc:stop",
            "last meaningful progress",
            "retries cancellation every 30 seconds",
            "watchdog-owned safety retry is not child-lane continuation",
            "Nested agents and workflow-owned agents are not covered",
        ):
            with self.subTest(text=text):
                self.assertIn(text, readme)
        for removed in (
            "Pi profile status indicators",
            "DS peak ×1",
            "DS off-peak ×0.5",
            "GLM peak ×3",
            "GLM off-peak ×1",
            "pace unavailable",
            "loads the managed `primary-policy.js`",
        ):
            with self.subTest(text=removed):
                self.assertNotIn(removed, readme)

    def test_manifest_uses_internal_bundle_schema_without_runtime_identity(self):
        """The manifest version names the internal bundle schema, never a runtime package."""
        expected_keys = {
            "format_version", "roles", "profiles", "launchers",
            "managed_extensions", "workflows", "shared",
        }
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["format_version"], 1)
                self.assertEqual(set(manifest), expected_keys)
                self.assertNotIn("adapter", manifest)
                self.assertNotIn("adapter_format", manifest)
                for guidance in ("_shared/degradations.md", "_shared/control-plane.json"):
                    content = (output / guidance).read_text()
                    self.assertNotIn("pi-subagents", content)
                    self.assertNotIn("0.67.0", content)

    def test_every_profile_generates_no_managed_extension_bundle(self):
        """REGRESSION CONTRACT: no bundle generates an extension directory/package and managed_extensions is empty."""
        retired = (
            "deepseek-price-status.js",
            "glm-price-status.js",
            "codex-pace-status.js",
            "codex-pace-core.mjs",
            "codex-pace-loader.ts",
            "primary-policy.js",
            "git-read.ts",
        )
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((output / "extensions").exists())
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["managed_extensions"], [])
                bundle = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
                for name in retired:
                    self.assertNotIn(name, bundle)
                self.assertNotIn("before_agent_start", bundle)

        self.assertFalse((ROOT / "harnesses/pi/extensions").exists())
        self.assertFalse((ROOT / "tests/test_pi_primary_policy.py").exists())
        self.assertFalse((ROOT / "tests/test_pi_git_read.py").exists())

    def test_generator_bootstraps_no_pi_sandbox_for_either_profile(self):
        """This test will fail when either Pi profile bundle loads the removed sandbox integration."""
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bundle = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
                self.assertNotIn("pi-sandbox", bundle)

    def test_generator_emits_isolated_exact_profile_routing(self):
        """This test will fail when either Pi profile routes a role to the wrong model or effort."""
        for profile_name, expected in EXPECTED.items():
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["profiles"], [profile_name])
                for role, effort in expected["efforts"].items():
                    frontmatter = (output / "agents" / f"{role}.md").read_text().split("---", 2)[1]
                    self.assertIn(f"model: {expected['models'][role]}", frontmatter)
                    self.assertIn(f"thinking: {effort}", frontmatter)

                control = json.loads((output / "_shared" / "control-plane.json").read_text())
                if profile_name == "deepseek":
                    self.assertEqual(control["primary"], {"model": "deepseek/deepseek-flash", "thinking": "max"})
                    self.assertEqual(control["small_model"], "deepseek/deepseek-flash")
                    self.assertEqual(control["builtins"]["build"], {"model": "deepseek/deepseek-flash", "thinking": "high"})
                    self.assertEqual(control["builtins"]["plan"], {"model": "deepseek/deepseek-flash", "thinking": "max"})
                elif profile_name == "hybrid":
                    self.assertEqual(control["primary"], {"model": "openai-codex/gpt-5.6-sol", "thinking": "medium"})
                    self.assertEqual(control["small_model"], "deepseek/deepseek-flash")
                    self.assertEqual(control["builtins"]["build"], {"model": "openai-codex/gpt-5.6-sol", "thinking": "medium"})
                    self.assertEqual(control["builtins"]["plan"], {"model": "openai-codex/gpt-5.6-sol", "thinking": "high"})
                elif profile_name == "openai":
                    self.assertEqual(control["small_model"], "openai-codex/gpt-5.6-luna")
                else:
                    self.assertEqual(control["primary"], {"model": "zai/glm-5.3", "thinking": "high"})
                    self.assertEqual(control["small_model"], "zai/glm-5.3-flash")
                    self.assertEqual(control["builtins"]["build"], {"model": "zai/glm-5.3", "thinking": "high"})
                    self.assertEqual(control["builtins"]["plan"], {"model": "zai/glm-5.3", "thinking": "high"})

    def test_generator_fails_closed_for_unknown_profile_and_model_provider_prefix(self):
        """This test will fail when unsupported profiles or malformed provider tokens are guessed."""
        result = subprocess.run(
            [sys.executable, str(GENERATE), "--profile", "unknown", "--output", tempfile.gettempdir() + "/pi-unknown"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported Pi profile", result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            for name in ("harnesses", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            profile = repo / "profiles" / "openai.toml"
            profile.write_text(profile.read_text().replace(
                "openai/gpt-5.6-luna", "deepseek/deepseek-flash", 1
            ))
            result = subprocess.run(
                [sys.executable, str(repo / "harnesses/pi/generate.py"), "--profile", "openai", "--output", str(Path(directory) / "out")],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported Pi model provider prefix", result.stderr)

        for bad_model in ("anthropic/claude", "deepseek//deepseek-flash", "deepseek/../flash"):
            with self.subTest(model=bad_model), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory) / "repo"
                for name in ("harnesses", "policy", "profiles", "roles"):
                    shutil.copytree(ROOT / name, repo / name)
                profile = repo / "profiles" / "hybrid.toml"
                profile.write_text(profile.read_text().replace("deepseek/deepseek-flash", bad_model, 1))
                result = subprocess.run(
                    [sys.executable, str(repo / "harnesses/pi/generate.py"), "--profile", "hybrid", "--output", str(Path(directory) / "out")],
                    text=True, capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "Unsupported|Malformed|Unsafe")

    def test_launchers_select_roots_share_sessions_forward_args_and_contain_no_credentials(self):
        """This test will fail when a launcher leaks state, drops arguments, or embeds credentials."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_pi = fake_home / ".nvm/versions/node/v24.15.0/bin/pi"
            fake_pi.parent.mkdir(parents=True)
            fake_pi.write_text("#!/bin/sh\nprintf '%s\\n' \"$PI_CODING_AGENT_DIR\" \"$PI_CODING_AGENT_SESSION_DIR\" \"$AGENT_ORCHESTRATION_PROFILE\" \"$@\"\n")
            fake_pi.chmod(0o755)
            fake_node = fake_pi.with_name("node")
            fake_node.write_text("#!/bin/sh\nexec \"$@\"\n")
            fake_node.chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(fake_home)
            cases = (
                ("hybrid", fake_home / ".pi/agent", "openai-codex/gpt-5.6-sol", "medium"),
                ("openai", fake_home / ".pi/profiles/openai", "openai-codex/gpt-5.6-sol", "medium"),
                ("deepseek", fake_home / ".pi/profiles/deepseek", "deepseek/deepseek-flash", "max"),
                ("glm", fake_home / ".pi/profiles/glm", "zai/glm-5.3", "high"),
            )
            for profile_name, expected_root, expected_model, expected_thinking in cases:
                with self.subTest(profile=profile_name):
                    output = root / profile_name
                    subprocess.run([sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)], check=True)
                    launcher = output / f"pi-{profile_name}"
                    self.assertTrue(os.access(launcher, os.X_OK))
                    content = launcher.read_text().lower()
                    for secret in ("api_key", "token=", "authorization:", "auth.json"):
                        self.assertNotIn(secret, content)
                    policy = expected_root / "agent-orchestration" / "_shared" / "orchestration-core.md"
                    policy.parent.mkdir(parents=True, exist_ok=True)
                    policy.write_text("SHARED ORCHESTRATION POLICY\n")
                    result = subprocess.run([str(launcher), "--prompt", "two words", "--", "literal"], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    lines = result.stdout.splitlines()
                    self.assertEqual(
                        lines[:3],
                        [str(expected_root), str(fake_home / ".pi/agent/sessions"), profile_name],
                    )
                    self.assertEqual(lines[3:7], ["--model", expected_model, "--thinking", expected_thinking])
                    self.assertEqual(lines[7], "--append-system-prompt")
                    self.assertEqual(lines[8], "SHARED ORCHESTRATION POLICY")
                    self.assertEqual(lines[9:], ["--prompt", "two words", "--", "literal"])
            fake_pi.unlink()
            missing = subprocess.run(
                [str(root / "openai" / "pi-openai")],
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(missing.returncode, 127)
            self.assertIn(str(fake_pi), missing.stderr)

    def test_launchers_use_node_colocated_with_pi_when_ambient_node_is_too_old(self):
        """A direct launcher must not resolve Pi's env-node shebang through the ambient PATH."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            pi_bin = fake_home / ".nvm/versions/node/v24.15.0/bin"
            pi_bin.mkdir(parents=True)
            fake_pi = pi_bin / "pi"
            fake_pi.write_text("#!/usr/bin/env node\n// requires Node 24\n")
            fake_pi.chmod(0o755)
            colocated_node = pi_bin / "node"
            colocated_node.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' colocated-node \"$PI_CODING_AGENT_DIR\" \"$@\"\n"
            )
            colocated_node.chmod(0o755)
            old_bin = root / "old-bin"
            old_bin.mkdir()
            old_node = old_bin / "node"
            old_node.write_text("#!/bin/sh\nprintf '%s\\n' ambient-node >&2\nexit 42\n")
            old_node.chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(fake_home)
            env["PATH"] = f"{old_bin}:/usr/bin:/bin"

            output = root / "hybrid"
            subprocess.run(
                [sys.executable, str(GENERATE), "--profile", "hybrid", "--output", str(output)],
                cwd=ROOT, check=True,
            )
            policy = fake_home / ".pi/agent/agent-orchestration/_shared/orchestration-core.md"
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text("SHARED ORCHESTRATION POLICY\n")
            result = subprocess.run(
                [str(output / "pi-hybrid"), "--version"],
                env=env, text=True, capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("ambient-node", result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], "colocated-node")
            self.assertIn(str(fake_pi), result.stdout.splitlines())

    def test_profile_launchers_bake_primary_model_thinking_and_append_shared_policy(self):
        """REGRESSION CONTRACT: a launcher selects its primary model/thinking and passes the shared policy natively."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            pi_bin = fake_home / ".nvm/versions/node/v24.15.0/bin"
            pi_bin.mkdir(parents=True)
            fake_pi = pi_bin / "pi"
            fake_node = pi_bin / "node"
            fake_node.write_text("#!/bin/sh\nexec \"$@\"\n")
            fake_node.chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(fake_home)
            expected_primary = {
                "hybrid": ("openai-codex/gpt-5.6-sol", "medium"),
                "openai": ("openai-codex/gpt-5.6-sol", "medium"),
                "deepseek": ("deepseek/deepseek-flash", "max"),
                "glm": ("zai/glm-5.3", "high"),
            }
            for profile_name, (model, thinking) in expected_primary.items():
                with self.subTest(profile=profile_name):
                    output = root / profile_name
                    subprocess.run(
                        [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                        cwd=ROOT, check=True,
                    )
                    launcher = output / f"pi-{profile_name}"
                    text = launcher.read_text()
                    self.assertNotIn("__AGENT_ORCHESTRATION_PRIMARY", text)
                    self.assertIn(f'--model "{model}"', text)
                    self.assertIn(f'--thinking "{thinking}"', text)
                    self.assertIn(f'export AGENT_ORCHESTRATION_PROFILE="{profile_name}"', text)
                    self.assertIn('--append-system-prompt "$policy"', text)
                    self.assertIn(
                        'policy_path="$PI_CODING_AGENT_DIR/agent-orchestration/_shared/orchestration-core.md"',
                        text,
                    )
                    control = json.loads((output / "_shared" / "control-plane.json").read_text())
                    self.assertEqual(control["primary"], {"model": model, "thinking": thinking})
                    self.assertEqual(control["installed"]["primary"], "launcher")

            # An installed-style launcher must pass the byte-exact generated policy and forward user args.
            policy_text = (root / "hybrid" / "_shared" / "orchestration-core.md").read_text()
            installed_policy = fake_home / ".pi/agent" / "agent-orchestration" / "_shared" / "orchestration-core.md"
            installed_policy.parent.mkdir(parents=True, exist_ok=True)
            installed_policy.write_text(policy_text)
            argv_path = root / "argv.bin"
            fake_pi.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\0' \"$@\" > {argv_path}\n"
            )
            fake_pi.chmod(0o755)
            result = subprocess.run(
                [str(root / "hybrid" / "pi-hybrid"), "--prompt", "keep both words"],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = [part.decode() for part in argv_path.read_bytes().split(b"\0") if part]
            self.assertEqual(argv[:2], ["--model", "openai-codex/gpt-5.6-sol"])
            self.assertEqual(argv[2:4], ["--thinking", "medium"])
            self.assertEqual(argv[4], "--append-system-prompt")
            self.assertEqual(argv[5], policy_text.rstrip("\n"))
            self.assertEqual(argv[6:], ["--prompt", "keep both words"])

    def test_pi_tool_allowlists_preserve_shell_and_delegation_boundaries(self):
        """This test will fail when Pi drops required tools or widens a role boundary."""
        expected_tools = {
            "worker": "read, grep, find, ls, edit, write, bash",
            "worker-complex": "read, grep, find, ls, edit, write, bash",
            "validator": ", ".join(["read", "grep", "find", "ls", "bash", *VALIDATOR_MCP_TOOLS]),
            "debugger": "read, grep, find, ls, bash",
            "explorer": "read, grep, find, ls, bash",
            "planner": "read, grep, find, ls, subagent",
            "design-partner": "read, grep, find, ls",
            "reviewer": "read, grep, find, ls, subagent",
            "ux-critic": ", ".join(UX_CRITIC_TOOLS),
        }
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                for role, tools in expected_tools.items():
                    frontmatter = (output / "agents" / f"{role}.md").read_text().split("---", 2)[1]
                    tools_line = next(line for line in frontmatter.splitlines() if line.startswith("tools: "))
                    self.assertEqual(tools_line, f"tools: {tools}")
                    delegation_tools = [
                        name.strip()
                        for name in tools_line.removeprefix("tools: ").split(",")
                        if name.strip() == "subagent"
                    ]
                    if role in {"planner", "reviewer"}:
                        self.assertEqual(delegation_tools, ["subagent"])
                    else:
                        self.assertEqual(delegation_tools, [])
                    acceptance_role_lines = [
                        line for line in frontmatter.splitlines() if line.startswith("acceptanceRole:")
                    ]
                    if role == "explorer":
                        self.assertEqual(acceptance_role_lines, ["acceptanceRole: read-only"])
                        self.assertNotIn("git_read", tools_line)
                    else:
                        self.assertEqual(acceptance_role_lines, [])

    def test_ux_critic_pi_allowlist_is_runtime_only_and_excludes_unsafe_tools(self):
        """REGRESSION CONTRACT: Pi UX-Critic remains runtime-only and cannot regain repository, shell, or lifecycle access."""
        forbidden = {
            "grep", "find", "ls", "edit", "write", "bash", "subagent",
            "browser_run_code_unsafe", "browser_evaluate", "browser_file_upload",
            "browser_drop", "browser_tabs", "appium_session_management",
            "appium_select_device", "appium_prepare_ios_simulator", "appium_app_lifecycle",
            "appium_mobile_device_control", "appium_mobile_permissions", "appium_mobile_file",
            "appium_driver_settings", "appium_perform_actions", "appium_mobile_clipboard",
        }
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                frontmatter = (output / "agents" / "ux-critic.md").read_text().split("---", 2)[1]
                tools_line = next(line for line in frontmatter.splitlines() if line.startswith("tools: "))
                self.assertEqual(tools_line, f"tools: {', '.join(UX_CRITIC_TOOLS)}")
                self.assertTrue(set(UX_CRITIC_TOOLS).isdisjoint(forbidden))

    def test_explorer_bash_degradation_is_explicit_and_git_reader_is_gone(self):
        """REGRESSION CONTRACT: explorer uses built-in bash instead of the removed git reader and the ask degradation is documented."""
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(GENERATE), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                degradation = (output / "_shared/degradations.md").read_text()
                self.assertIn("no hard read-only sandbox", degradation)
                self.assertIn("cannot forward an `ask` decision", degradation)
                self.assertIn("acceptanceRole: read-only", degradation)
                self.assertIn("does not grant or revoke tools", degradation)
                self.assertIn("policy-level boundary", degradation)
                self.assertIn("framework-neutral", degradation)
                self.assertIn("not runtime enforcement", degradation)
                self.assertIn("exact child target `explorer`", degradation)
                explorer = (output / "agents" / "explorer.md").read_text()
                self.assertIn("acceptanceRole: read-only", explorer)
                self.assertIn("tools: read, grep, find, ls, bash", explorer)
                self.assertNotIn("git_read", explorer)
                for role in EXPECTED[profile_name]["models"]:
                    if role != "explorer":
                        content = (output / "agents" / f"{role}.md").read_text()
                        self.assertNotIn("git_read", content)
                        self.assertNotIn("acceptanceRole:", content)

    def test_generator_emits_complete_default_hybrid_pi_bundle(self):
        """This test will fail when the Pi bundle omits a canonical artifact or role."""
        with (ROOT / "policy" / "routing.toml").open("rb") as handle:
            routing_roles = tomllib.load(handle)["roles"]
            roles = set(routing_roles)
        with (ROOT / "profiles" / "hybrid.toml").open("rb") as handle:
            profile = tomllib.load(handle)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pi"
            result = subprocess.run(
                [sys.executable, str(GENERATE), "--output", str(output)],
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
            self.assertEqual(manifest["profiles"], ["hybrid"])
            shared_policy = (output / "_shared" / "orchestration-core.md").read_text()
            for phrase in (
                "Delegated agents MUST NOT watch, poll, retry, sleep, or otherwise wait",
                "at most one one-shot status query",
                "terminal success maps to `PASS`",
                "pending, queued, running, unknown, or otherwise non-terminal maps immediately to `BLOCKED`",
                "Waiting or retry loops remain owned by the primary",
                "hard cancellation can terminate both the execution lane and the in-flight process/tool call",
                "the operation is forbidden and returns `BLOCKED`",
                "/agents` → `Running agents` → select the agent → press `x`, then `x` again to confirm",
                "Stopped output is partial/incomplete",
                "Global Esc does not unambiguously target a background agent",
                "`steer_subagent` is not cancellation",
            ):
                self.assertIn(phrase, shared_policy)
            for role, config in routing_roles.items():
                content = (output / "agents" / f"{role}.md").read_text()
                frontmatter = content.split("---", 2)[1]
                if role == "ux-critic":
                    expected_tools = UX_CRITIC_TOOLS
                else:
                    expected_tools = ["read", "grep", "find", "ls"]
                    if role == "explorer":
                        expected_tools.append("bash")
                    if config["edit"] == "allow":
                        expected_tools += ["edit", "write"]
                    if config["bash"] == "allow" or role in {"validator", "debugger"}:
                        expected_tools.append("bash")
                    if "explorer" in config.get("delegates", []):
                        expected_tools.append("subagent")
                model = profile["models"][role]
                expected_model = model["model"].replace("openai/", "openai-codex/", 1)
                self.assertIn(f"model: {expected_model}", frontmatter)
                self.assertIn(f"thinking: {model['variant']}", frontmatter)
                self.assertIn(f"tools: {', '.join(expected_tools)}", frontmatter)
                self.assertIn("defaultContext: fresh", frontmatter)
                self.assertIn("inheritProjectContext: false", frontmatter)
                self.assertIn("inheritSkills: false", frontmatter)
                self.assertNotIn("subagentOnlyExtensions:", frontmatter)
                self.assertIn((ROOT / "roles" / f"{role}.md").read_text(), content)

    def test_bundle_documents_pi_permission_and_control_plane_degradation(self):
        """This test will fail when operators cannot see Pi's unavoidable semantic gaps."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pi"
            subprocess.run(
                [sys.executable, str(GENERATE), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )

            note = (output / "_shared" / "degradations.md").read_text().lower()
            self.assertIn("permissions.bash", note)
            self.assertIn("operator-owned runtime state", note)
            self.assertIn("do not copy or claim", note)
            self.assertIn("omits `bash`", note)
            self.assertIn("primary", note)
            self.assertIn("not installed", note)

    def test_glm_uses_a_pi_specific_source_without_colliding_with_generic_glm(self):
        """Pi GLM must not repurpose the generic OpenCode profiles/glm.toml source."""
        generic = (ROOT / "profiles" / "glm.toml").read_text()
        pi_source = (ROOT / "profiles" / "pi-glm.toml").read_text()
        self.assertNotIn('harness = "pi"', generic)
        self.assertIn('name = "pi-glm"', pi_source)
        self.assertIn('harness = "pi"', pi_source)
        self.assertIn('addendum = "pi-glm.md"', pi_source)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "glm"
            result = subprocess.run(
                [sys.executable, str(GENERATE), "--profile", "glm", "--output", str(output)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((output / "manifest.json").read_text())["profiles"], ["glm"])
            bundle = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
            self.assertNotIn("opencode-go", bundle)
            self.assertNotIn("profiles/glm.toml", bundle)


if __name__ == "__main__":
    unittest.main()
