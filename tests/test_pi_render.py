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
                if role in {"debugger", "planner", "reviewer"}
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


class PiRenderTests(unittest.TestCase):
    def test_readme_documents_profile_switching_and_status_semantics(self):
        """Operators must know the exact process switch and how to interpret both indicators."""
        readme = (ROOT / "README.md").read_text()
        for text in (
            "exit the current Pi process",
            "pi-hybrid",
            "pi-openai",
            "pi-deepseek",
            "pi-glm",
            "01:00–04:00 and 06:00–10:00 UTC Monday–Friday",
            "DS peak ×1",
            "DS off-peak ×0.5",
            "Hybrid and standalone DeepSeek",
            "GLM peak ×3",
            "GLM off-peak ×1",
            "06:00–10:00 UTC Monday–Friday",
            "×1.2",
            "×0.4",
            "consumed% − elapsed%",
            "projected end utilization",
            "pace unavailable",
            "acceptanceRole: read-only",
            "acceptance inference only",
        ):
            with self.subTest(text=text):
                self.assertIn(text, readme)

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
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
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

    def test_hybrid_deepseek_price_refresh_aligns_to_utc_minute_boundaries(self):
        """A session started mid-minute must update exactly when a pricing boundary begins."""
        source = ROOT / "adapters/pi/extensions/deepseek-price-status.js"
        script = """
import { millisecondsToNextUtcMinute } from %s;
console.log(JSON.stringify([
  millisecondsToNextUtcMinute(Date.parse("2026-09-07T00:59:00.000Z")),
  millisecondsToNextUtcMinute(Date.parse("2026-09-07T00:59:00.500Z")),
  millisecondsToNextUtcMinute(Date.parse("2026-09-07T00:59:59.999Z")),
]));
""" % json.dumps(source.as_uri())
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [60_000, 59_500, 1])

    def test_hybrid_deepseek_price_status_has_exact_utc_boundaries_and_weekends(self):
        """Hybrid pricing must follow the official weekday UTC periods without network data."""
        source = ROOT / "adapters/pi/extensions/deepseek-price-status.js"
        script = """
import { deepseekPricePeriod } from %s;
const cases = %s;
console.log(JSON.stringify(cases.map(([value]) => deepseekPricePeriod(new Date(value)))));
""" % (json.dumps(source.as_uri()), json.dumps([
            ["2026-09-07T00:59:59.999Z"],
            ["2026-09-07T01:00:00.000Z"],
            ["2026-09-07T03:59:59.999Z"],
            ["2026-09-07T04:00:00.000Z"],
            ["2026-09-07T05:59:59.999Z"],
            ["2026-09-07T06:00:00.000Z"],
            ["2026-09-07T09:59:59.999Z"],
            ["2026-09-07T10:00:00.000Z"],
            ["2026-09-12T02:00:00.000Z"],
            ["2026-09-13T07:00:00.000Z"],
        ]))
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            "DS off-peak ×0.5", "DS peak ×1", "DS peak ×1", "DS off-peak ×0.5",
            "DS off-peak ×0.5", "DS peak ×1", "DS peak ×1", "DS off-peak ×0.5",
            "DS off-peak ×0.5", "DS off-peak ×0.5",
        ])

    def test_glm_price_status_has_exact_utc_boundaries_and_weekends(self):
        """GLM-5.3 peak pricing is the weekday half-open UTC window only."""
        source = ROOT / "adapters/pi/extensions/glm-price-status.js"
        cases = [
            "2026-09-11T05:59:00.000Z",
            "2026-09-11T06:00:00.000Z",
            "2026-09-11T09:59:00.000Z",
            "2026-09-11T10:00:00.000Z",
            "2026-09-12T07:00:00.000Z",
            "2026-09-13T07:00:00.000Z",
        ]
        script = """
import { glmPricePeriod, millisecondsToNextUtcMinute } from %s;
const cases = %s;
console.log(JSON.stringify({
  labels: cases.map((value) => glmPricePeriod(new Date(value))),
  refresh: [
    millisecondsToNextUtcMinute(Date.parse("2026-09-11T06:00:00.000Z")),
    millisecondsToNextUtcMinute(Date.parse("2026-09-11T06:00:00.500Z")),
    millisecondsToNextUtcMinute(Date.parse("2026-09-11T06:00:59.999Z")),
  ],
}));
""" % (json.dumps(source.as_uri()), json.dumps(cases))
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "labels": [
                "GLM off-peak ×1", "GLM peak ×3", "GLM peak ×3",
                "GLM off-peak ×1", "GLM off-peak ×1", "GLM off-peak ×1",
            ],
            "refresh": [60_000, 59_500, 1],
        })

    def test_codex_weekly_pace_formats_schedule_and_rejects_unusable_reports(self):
        """Weekly pace uses the seven-day bucket and degrades silently for unsafe data."""
        source = ROOT / "adapters/pi/extensions/codex-pace-status.js"
        now = 1_800_000_000_000
        # The weekly window is halfway elapsed when it has 3.5 days remaining.
        valid = {
            "providerId": "openai-codex",
            "capturedAt": now - 60_000,
            "buckets": [{
                "id": "codex:secondary", "used": 60, "unit": "percent",
                "windowMinutes": 7 * 24 * 60,
                "resetsAt": (now + 3.5 * 24 * 60 * 60 * 1000) / 1000,
            }],
        }
        cases = [
            valid,
            {**valid, "buckets": [{**valid["buckets"][0], "used": 40}]},
            {**valid, "capturedAt": now - 16 * 60_000},
            {**valid, "buckets": []},
            {**valid, "buckets": [{**valid["buckets"][0], "used": "secret"}]},
            {**valid, "buckets": [{
                **valid["buckets"][0], "used": 0,
                "resetsAt": (now + (7 * 24 * 60 - 1) * 60 * 1000) / 1000,
            }]},
        ]
        script = """
import { codexWeeklyPace } from %s;
const cases = %s;
console.log(JSON.stringify(cases.map((report) => codexWeeklyPace(report, %d))));
""" % (json.dumps(source.as_uri()), json.dumps(cases), now)
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            "pace +10pp · proj 120%",
            "pace -10pp · proj 80%",
            None,
            None,
            None,
            "pace +0pp · proj —",
        ])

    def test_codex_pace_resolves_pi_usage_from_profile_settings(self):
        """The isolated root may share validated package code without an ambient node_modules lookup."""
        source = ROOT / "adapters/pi/extensions/codex-pace-status.js"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "shared/npm/node_modules/@narumitw/pi-usage"
            (package / "dist").mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({"name": "@narumitw/pi-usage"}))
            (package / "dist/index.ts").write_text("export {};\n")
            profile = root / "profile"
            profile.mkdir()
            (profile / "settings.json").write_text(json.dumps({
                "packages": [{"source": str(package), "autoload": True}],
            }))
            script = """
import { resolvePiUsageEntrypoint } from %s;
console.log(resolvePiUsageEntrypoint(%s));
""" % (json.dumps(source.as_uri()), json.dumps(str(profile)))
            result = subprocess.run(
                ["node", "--input-type=module", "--eval", script],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(), (package / "dist/index.ts").as_uri().replace("%40", "@")
            )

    def test_codex_pace_status_refreshes_safely_with_pi_usage_public_api(self):
        """The OpenAI adapter refreshes on lifecycle events and never publishes query errors."""
        source = ROOT / "adapters/pi/extensions/codex-pace-status.js"
        script = """
import extension from %s;
const handlers = {};
const statuses = [];
let timerCallback;
let queries = 0;
const now = 1800000000000;
const report = {
  providerId: "openai-codex", capturedAt: now,
  buckets: [{ unit: "percent", used: 60, windowMinutes: 10080,
    resetsAt: (now + 3.5 * 86400000) / 1000 }],
};
const usageApi = {
  adapterForProvider(id) { return id === "openai-codex" ? { id } : undefined; },
  async resolveUsageAuth(ctx, adapter) { return { marker: "resolved", model: ctx.model }; },
  async queryProviderUsage(adapter, auth, signal, timeout) {
    queries += 1;
    if (queries === 2) throw new Error("secret-response-body");
    return report;
  },
};
const pi = { on(name, callback) { handlers[name] = callback; } };
const ctx = {
  model: { provider: "openai-codex", id: "gpt-5.6-sol" },
  ui: { setStatus(key, value) { statuses.push([key, value]); } },
};
extension(pi, {
  usageApi,
  now: () => now,
  setInterval(callback, ms) { timerCallback = callback; return { unref() {} }; },
  clearInterval() {},
});
await handlers.session_start({}, ctx);
await handlers.model_select({ model: ctx.model }, ctx);
await timerCallback();
handlers.session_shutdown({}, ctx);
console.log(JSON.stringify({ queries, statuses }));
""" % json.dumps(source.as_uri())
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["queries"], 3)
        self.assertEqual(payload["statuses"], [
            ["agent-orchestration-codex-pace", "pace +10pp · proj 120%"],
            ["agent-orchestration-codex-pace", "pace unavailable"],
            ["agent-orchestration-codex-pace", "pace +10pp · proj 120%"],
            ["agent-orchestration-codex-pace", None],
        ])
        self.assertNotIn("secret-response-body", result.stdout + result.stderr)

    def test_deepseek_regression_contract_renders_only_its_canonical_status_adapter(self):
        """REGRESSION CONTRACT: standalone DeepSeek loads canonical pricing and no other provider status."""
        expected = {
            "hybrid": (
                [
                    "delegation-ceiling-core.js",
                    "delegation-ceiling-planner.js",
                    "delegation-ceiling-reviewer.js",
                    "deepseek-price-status.js",
                    "git-read.ts",
                    "package.json",
                    "primary-policy.js",
                ],
                {"type": "module", "pi": {"extensions": ["./primary-policy.js", "./deepseek-price-status.js", "./git-read.ts"]}},
            ),
            "openai": (
                [
                    "codex-pace-core.mjs",
                    "codex-pace-loader.ts",
                    "delegation-ceiling-core.js",
                    "delegation-ceiling-planner.js",
                    "delegation-ceiling-reviewer.js",
                    "git-read.ts",
                    "package.json",
                    "primary-policy.js",
                ],
                {"type": "module", "pi": {"extensions": ["./primary-policy.js", "./codex-pace-loader.ts", "./git-read.ts"]}},
            ),
            "deepseek": (
                [
                    "deepseek-price-status.js",
                    "delegation-ceiling-core.js",
                    "delegation-ceiling-planner.js",
                    "delegation-ceiling-reviewer.js",
                    "git-read.ts",
                    "package.json",
                    "primary-policy.js",
                ],
                {"type": "module", "pi": {"extensions": ["./primary-policy.js", "./deepseek-price-status.js", "./git-read.ts"]}},
            ),
            "glm": (
                [
                    "delegation-ceiling-core.js",
                    "delegation-ceiling-planner.js",
                    "delegation-ceiling-reviewer.js",
                    "git-read.ts",
                    "glm-price-status.js",
                    "package.json",
                    "primary-policy.js",
                ],
                {"type": "module", "pi": {"extensions": ["./primary-policy.js", "./glm-price-status.js", "./git-read.ts"]}},
            ),
        }
        for profile_name, (expected_names, expected_package) in expected.items():
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                extension_dir = output / "extensions/agent-orchestration"
                files = sorted(path.name for path in extension_dir.glob("*"))
                self.assertEqual(files, sorted(expected_names))
                manifest = json.loads((output / "manifest.json").read_text())
                managed = manifest.get("managed_extensions", [])
                expected_managed = [
                    f"extensions/agent-orchestration/{name}" for name in expected_names
                ]
                self.assertEqual(sorted(managed), sorted(expected_managed))
                if expected_package is not None:
                    self.assertEqual(
                        json.loads((extension_dir / "package.json").read_text()),
                        expected_package,
                    )

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

    def test_renderer_fails_closed_for_unknown_profile_and_model_provider_prefix(self):
        """This test will fail when unsupported profiles or malformed provider tokens are guessed."""
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
            profile.write_text(profile.read_text().replace(
                "openai/gpt-5.6-luna", "deepseek/deepseek-flash", 1
            ))
            result = subprocess.run(
                [sys.executable, str(repo / "adapters/pi/render.py"), "--profile", "openai", "--output", str(Path(directory) / "out")],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported Pi model provider prefix", result.stderr)

        for bad_model in ("anthropic/claude", "deepseek//deepseek-flash", "deepseek/../flash"):
            with self.subTest(model=bad_model), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory) / "repo"
                for name in ("adapters", "policy", "profiles", "roles"):
                    shutil.copytree(ROOT / name, repo / name)
                profile = repo / "profiles" / "hybrid.toml"
                profile.write_text(profile.read_text().replace("deepseek/deepseek-flash", bad_model, 1))
                result = subprocess.run(
                    [sys.executable, str(repo / "adapters/pi/render.py"), "--profile", "hybrid", "--output", str(Path(directory) / "out")],
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
            fake_pi.write_text("#!/bin/sh\nprintf '%s\\n' \"$PI_CODING_AGENT_DIR\" \"$PI_CODING_AGENT_SESSION_DIR\" \"$@\"\n")
            fake_pi.chmod(0o755)
            fake_node = fake_pi.with_name("node")
            fake_node.write_text("#!/bin/sh\nexec \"$@\"\n")
            fake_node.chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(fake_home)
            for profile_name, expected_root in (
                ("hybrid", fake_home / ".pi/agent"),
                ("openai", fake_home / ".pi/profiles/openai"),
                ("deepseek", fake_home / ".pi/profiles/deepseek"),
                ("glm", fake_home / ".pi/profiles/glm"),
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
                self.assertEqual(lines[2:], ["--prompt", "two words", "--", "literal"])
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
                [sys.executable, str(RENDER), "--profile", "hybrid", "--output", str(output)],
                cwd=ROOT, check=True,
            )
            result = subprocess.run(
                [str(output / "pi-hybrid"), "--version"],
                env=env, text=True, capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("ambient-node", result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], "colocated-node")
            self.assertIn(str(fake_pi), result.stdout.splitlines())

    def test_command_capable_ask_roles_get_bash_without_widening_other_roles(self):
        """This test will fail when Pi drops required shell access or widens another ask role."""
        expected_tools = {
            "validator": ", ".join(["read", "grep", "find", "ls", "bash", *VALIDATOR_MCP_TOOLS]),
            "debugger": "read, grep, find, ls, bash",
            "planner": "read, grep, find, ls, subagent",
            "reviewer": "read, grep, find, ls, subagent",
            "explorer": "read, grep, find, ls, git_read",
            "ux-critic": ", ".join(UX_CRITIC_TOOLS),
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
                    acceptance_role_lines = [
                        line for line in frontmatter.splitlines() if line.startswith("acceptanceRole:")
                    ]
                    if role == "explorer":
                        self.assertEqual(acceptance_role_lines, ["acceptanceRole: read-only"])
                        self.assertNotIn("bash", tools_line)
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
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                frontmatter = (output / "agents" / "ux-critic.md").read_text().split("---", 2)[1]
                tools_line = next(line for line in frontmatter.splitlines() if line.startswith("tools: "))
                self.assertEqual(tools_line, f"tools: {', '.join(UX_CRITIC_TOOLS)}")
                self.assertTrue(set(UX_CRITIC_TOOLS).isdisjoint(forbidden))

    def test_git_read_degradation_is_explicit_and_explorer_only(self):
        """REGRESSION CONTRACT: generated Pi bundles document the bounded Git exception without granting shell access."""
        for profile_name in EXPECTED:
            with self.subTest(profile=profile_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile_name
                result = subprocess.run(
                    [sys.executable, str(RENDER), "--profile", profile_name, "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                degradation = (output / "_shared/degradations.md").read_text()
                self.assertIn("64 KiB/2,000-line caps", degradation)
                self.assertIn("bounded `spawn` helper", degradation)
                self.assertIn("unbounded `pi.exec` buffering", degradation)
                self.assertIn("acceptanceRole: read-only", degradation)
                self.assertIn("does not grant or revoke tools", degradation)
                explorer = (output / "agents/explorer.md").read_text()
                self.assertIn("acceptanceRole: read-only", explorer)
                self.assertIn("tools: read, grep, find, ls, git_read", explorer)
                self.assertNotIn("tools: read, grep, find, ls, git_read, bash", explorer)
                for role in EXPECTED[profile_name]["models"]:
                    if role != "explorer":
                        self.assertNotIn("git_read", (output / "agents" / f"{role}.md").read_text())

    def test_child_ceiling_wrappers_register_exact_targets_and_dispose_lifecycle_handles(self):
        """This test will fail when a child guard widens targets or leaks a registration."""
        for role, expected in {
            "planner": ["explorer"],
            "reviewer": ["explorer"],
        }.items():
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                profile = root / "profile"
                package = profile / "npm/node_modules/pi-subagents"
                package.mkdir(parents=True)
                (package / "package.json").write_text(json.dumps({
                    "name": "pi-subagents",
                    "type": "module",
                    "exports": {"./capability-ceiling": "./capability-ceiling.js"},
                }))
                (package / "capability-ceiling.js").write_text(
                    "globalThis.calls = []; globalThis.disposals = [];\n"
                    "export function registerSubagentCapabilityCeiling(options) {\n"
                    "  globalThis.calls.push({sessionId: options.sessionId, source: options.source, allowedAgents: [...options.ceiling.allowedAgents]});\n"
                    "  return {dispose() { globalThis.disposals.push(options.source); }};\n"
                    "}\n"
                )
                wrapper = ROOT / "adapters/pi/extensions" / f"delegation-ceiling-{role}.js"
                script = """
import extension from %s;
const handlers = {};
extension({on(name, callback) { handlers[name] = callback; }});
const context = {sessionManager: {getSessionId: () => "session-1"}};
handlers.session_start({}, context);
handlers.session_start({}, context);
handlers.session_shutdown({}, context);
console.log(JSON.stringify({calls: globalThis.calls, disposals: globalThis.disposals}));
""" % json.dumps(wrapper.as_uri())
                environment = os.environ.copy()
                environment["PI_CODING_AGENT_DIR"] = str(profile)
                result = subprocess.run(
                    ["node", "--input-type=module", "--eval", script],
                    cwd=ROOT, env=environment, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(
                    [call["allowedAgents"] for call in payload["calls"]],
                    [expected, expected],
                )
                self.assertEqual(
                    [call["sessionId"] for call in payload["calls"]],
                    ["session-1", "session-1"],
                )
                self.assertEqual(len(payload["disposals"]), 2)

    def test_child_ceiling_rejects_public_export_resolution_failures_and_supports_absolute_package_sources(self):
        """This test will fail when the guard swallows package failures or reaches private paths."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile"
            package = root / "absolute-package"
            package.mkdir(parents=True)
            profile.mkdir()
            (package / "package.json").write_text(json.dumps({
                "name": "pi-subagents",
                "type": "module",
                "exports": {"./capability-ceiling": "./capability-ceiling.js"},
            }))
            (package / "capability-ceiling.js").write_text(
                "export function registerSubagentCapabilityCeiling(options) {\n"
                "  globalThis.received = options;\n"
                "  return {dispose() {}};\n"
                "}\n"
            )
            (profile / "settings.json").write_text(json.dumps({
                "packages": [{"source": str(package)}],
            }))
            wrapper = ROOT / "adapters/pi/extensions/delegation-ceiling-planner.js"
            script = """
import extension from %s;
const handlers = {};
extension({on(name, callback) { handlers[name] = callback; }});
handlers.session_start({}, {sessionManager: {getSessionId: () => "absolute"}});
const allowed = globalThis.received.ceiling.allowedAgents;
console.log(JSON.stringify({allowed, acceptsExplorer: allowed.includes("explorer"), deniesValidator: !allowed.includes("validator")}));
""" % json.dumps(wrapper.as_uri())
            environment = os.environ.copy()
            environment["PI_CODING_AGENT_DIR"] = str(profile)
            result = subprocess.run(
                ["node", "--input-type=module", "--eval", script],
                cwd=ROOT, env=environment, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {
                "allowed": ["explorer"],
                "acceptsExplorer": True,
                "deniesValidator": True,
            })

            broken = root / "broken-profile/npm/node_modules/pi-subagents"
            broken.mkdir(parents=True)
            (broken / "package.json").write_text(json.dumps({
                "name": "pi-subagents",
                "type": "module",
                "exports": {"./capability-ceiling": "./missing.js"},
            }))
            broken_environment = environment.copy()
            broken_environment["PI_CODING_AGENT_DIR"] = str(root / "broken-profile")
            broken_result = subprocess.run(
                ["node", "--input-type=module", "--eval", "import %s;" % json.dumps(wrapper.as_uri())],
                cwd=ROOT, env=broken_environment, text=True, capture_output=True,
            )
            self.assertNotEqual(broken_result.returncode, 0)
            self.assertTrue(
                "ERR_MODULE_NOT_FOUND" in broken_result.stderr
                or "missing.js" in broken_result.stderr
            )
            self.assertEqual(broken_result.stdout, "")

    def test_renderer_emits_complete_default_hybrid_pi_bundle(self):
        """This test will fail when the Pi bundle omits a canonical artifact or role."""
        with (ROOT / "policy" / "routing.toml").open("rb") as handle:
            routing_roles = tomllib.load(handle)["roles"]
            roles = set(routing_roles)
        with (ROOT / "profiles" / "hybrid.toml").open("rb") as handle:
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
            self.assertEqual(manifest["profiles"], ["hybrid"])
            for role, config in routing_roles.items():
                content = (output / "agents" / f"{role}.md").read_text()
                frontmatter = content.split("---", 2)[1]
                if role == "ux-critic":
                    expected_tools = UX_CRITIC_TOOLS
                else:
                    expected_tools = ["read", "grep", "find", "ls"]
                    if role == "explorer":
                        expected_tools.append("git_read")
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
                if role == "planner":
                    self.assertIn(
                        "subagentOnlyExtensions: ../extensions/agent-orchestration/delegation-ceiling-planner.js",
                        frontmatter,
                    )
                elif role == "reviewer":
                    self.assertIn(
                        "subagentOnlyExtensions: ../extensions/agent-orchestration/delegation-ceiling-reviewer.js",
                        frontmatter,
                    )
                else:
                    self.assertNotIn("subagentOnlyExtensions:", frontmatter)
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
                [sys.executable, str(RENDER), "--profile", "glm", "--output", str(output)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((output / "manifest.json").read_text())["profiles"], ["glm"])
            bundle = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
            self.assertNotIn("opencode-go", bundle)
            self.assertNotIn("profiles/glm.toml", bundle)


if __name__ == "__main__":
    unittest.main()
