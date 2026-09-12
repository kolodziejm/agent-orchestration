#!/usr/bin/env python3
"""Render a supported Pi profile using the pi-subagents v0.67.0 baseline."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required (tomllib).")

ADAPTERS_DIR = Path(__file__).resolve().parents[1]
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

from common import assert_safe_output as shared_assert_safe_output
from common import assert_safe_rename, validate_capabilities, validate_profile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = ROOT / "generated" / "pi"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
WORKFLOW_NAME = "feature-workflow-pilot"
SUPPORTED_PROFILES = {
    "hybrid": frozenset({"openai", "deepseek"}),
    "openai": frozenset({"openai"}),
    "deepseek": frozenset({"deepseek"}),
}
PROFILE_STATUS_EXTENSIONS = {
    "hybrid": (("deepseek-price-status.js", "deepseek-price-status.js"),),
    "openai": (
        ("codex-pace-status.js", "codex-pace-core.mjs"),
        ("codex-pace-loader.ts", "codex-pace-loader.ts"),
    ),
}
PROFILE_STATUS_ENTRYPOINTS = {
    "hybrid": "./deepseek-price-status.js",
    "openai": "./codex-pace-loader.ts",
}
READ_TOOLS = ["read", "grep", "find", "ls"]
# Pi's MCP directTools expose these concrete names. This is intentionally a
# role-specific exception rather than a general capability abstraction: the
# orchestrator supplies the already-running browser/session before delegation.
UX_CRITIC_TOOLS = [
    # Pi built-in image-capable filesystem read, for opening saved screenshots.
    "read",
    # Playwright MCP (safe navigation, interaction, state inspection, and evidence).
    "browser_navigate",
    "browser_navigate_back",
    "browser_snapshot",
    "browser_find",
    "browser_click",
    "browser_fill_form",
    "browser_type",
    "browser_press_key",
    "browser_select_option",
    "browser_hover",
    "browser_drag",
    "browser_mouse_wheel",
    "browser_wait_for",
    "browser_resize",
    "browser_take_screenshot",
    "browser_start_video",
    "browser_stop_video",
    # Appium MCP 1.90 direct tools (prepared session only).
    "appium_get_active_element",
    "appium_find_element",
    "appium_get_text",
    "appium_get_element_attribute",
    "appium_get_page_source",
    "appium_gesture",
    "appium_drag_and_drop",
    "appium_set_value",
    "appium_mobile_press_key",
    "appium_mobile_keyboard",
    "appium_get_window_size",
    "appium_orientation",
    "appium_context",
    "appium_alert",
    "appium_screenshot",
    "appium_screen_recording",
]
SAFE_MODEL_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def pi_model(model: str, allowed_providers: frozenset[str]) -> str:
    if not isinstance(model, str) or model.count("/") != 1:
        raise SystemExit(f"Malformed Pi model token: {model!r}")
    provider, model_id = model.split("/", 1)
    if provider not in allowed_providers:
        raise SystemExit(f"Unsupported Pi model provider prefix: {provider!r}")
    if SAFE_MODEL_PART.fullmatch(provider) is None or SAFE_MODEL_PART.fullmatch(model_id) is None:
        raise SystemExit(f"Unsafe Pi model token: {model!r}")
    destination = "openai-codex" if provider == "openai" else provider
    return f"{destination}/{model_id}"


def tools_for(role: str, config: dict) -> list[str]:
    if role == "ux-critic":
        return list(UX_CRITIC_TOOLS)

    tools = list(READ_TOOLS)
    if config["edit"] == "allow":
        tools.extend(["edit", "write"])
    # Pi cannot represent the canonical `ask` capability. These narrowly scoped
    # exceptions need commands for their contracts while preserving role-specific
    # source-editing boundaries.
    if config["bash"] == "allow" or role in {"validator", "debugger", "planner"}:
        tools.append("bash")
    delegates = set(config.get("delegates", []))
    if delegates & {"explorer", "spec-writer"}:
        tools.append("subagent")
    return tools


def frontmatter(role: str, config: dict, model_config: dict, allowed_providers: frozenset[str]) -> str:
    return "\n".join(
        [
            "---",
            f"name: {json.dumps(role)}",
            f"description: {json.dumps(config['description'])}",
            f"model: {pi_model(model_config['model'], allowed_providers)}",
            f"thinking: {model_config['variant']}",
            f"tools: {', '.join(tools_for(role, config))}",
            "defaultContext: fresh",
            "systemPromptMode: replace",
            "inheritProjectContext: false",
            "inheritSkills: false",
            "---",
            "",
        ]
    )


def control_plane(profile: dict, allowed_providers: frozenset[str]) -> dict:
    source = profile["control_plane"]
    return {
        "profile": profile["name"],
        "primary": {
            "model": pi_model(source["primary"]["model"], allowed_providers),
            "thinking": source["primary"]["effort"],
        },
        "small_model": pi_model(source["small_model"], allowed_providers),
        "builtins": {
            name: {
                "model": pi_model(config["model"], allowed_providers),
                "thinking": config["effort"],
            }
            for name, config in source["builtins"].items()
        },
        "installed": {
            "primary": "launcher",
            "roles": "agent-files",
            "small_model": False,
            "builtins": False,
        },
        "note": (
            "The profile launcher selects the primary model and pi-subagents agent files "
            "configure child roles. Pi cannot install the small-model or built-in mappings; "
            "those values are recorded as control-plane intent."
        ),
    }


def assert_safe_output(output: Path, profile_name: str = "hybrid") -> Path:
    return shared_assert_safe_output(output, DEFAULT_OUTPUT_ROOT / profile_name, TEMP_ROOT)


def render_into(output: Path, profile_name: str = "hybrid") -> None:
    allowed_providers = SUPPORTED_PROFILES.get(profile_name)
    if allowed_providers is None:
        raise SystemExit(f"Unsupported Pi profile: {profile_name!r}")
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]
    profile_path = ROOT / "profiles" / f"{profile_name}.toml"
    profile = load_toml(profile_path)
    validate_profile(
        profile,
        profile_path,
        set(roles),
        "pi",
        require_role_variants=True,
    )

    for role, config in roles.items():
        validate_capabilities(role, config, "pi")
        if config.get("mode") != "subagent":
            raise SystemExit(f"Pi adapter only renders subagent roles: {role!r}")

    (output / "agents").mkdir(parents=True)
    (output / "_shared").mkdir(parents=True)
    (output / "workflows").mkdir(parents=True)

    policy = (ROOT / "policy" / "orchestration.md").read_text().rstrip()
    addendum = (ROOT / "profiles" / profile["addendum"]).read_text().rstrip()
    (output / "_shared" / "orchestration-core.md").write_text(
        f"{policy}\n\n{addendum}\n"
    )
    (output / "_shared" / "control-plane.json").write_text(
        json.dumps(control_plane(profile, allowed_providers), indent=2, sort_keys=True) + "\n"
    )
    (output / "_shared" / "degradations.md").write_text(
        """# Pi adapter degradations

- Supported pi-subagents releases at or above the v0.67.0 minimum-tested baseline reject `permissions.bash` and always allow shell calls
  when the `bash` tool is present. For canonical `bash = \"ask\"` roles other than validator,
  debugger, and planner this adapter omits `bash`, enforcing a stricter no-shell ceiling. Install and configure
  a separate permission wrapper if command-level allow/deny behavior is required; headless
  children still cannot forward an `ask` decision to the parent UI.
- The profile launcher selects the primary session and Pi user agent files configure
  subagents. Pi cannot install the small model or built-in build/plan mappings; their
  mapped values are recorded in `control-plane.json` as profile intent and are not installed.
- Validator, debugger, and planner receive `bash` despite canonical `bash = "ask"` because
  their contracts require mechanical checks or repository commands. Debugger remains source-edit
  read-only; planner retains its existing edit/write/subagent capabilities.
- UX-Critic is an on-demand, read-only runtime audit. Its Pi agent file has an
  explicit allowlist of verified Playwright MCP and Appium MCP interaction,
  inspection, screenshot, and recording tools, plus Pi's built-in image-capable
  `read` for opening saved screenshots. `read` is its only filesystem capability;
  it receives no `edit`, `write`, or shell tools. The primary must supply the
  running URL/session, device, scope, identity, reference, and screenshot
  destination first.
- The selected profile has no concrete `vision-*` role among its ten canonical roles.
  Wildcard visual delegation is therefore guidance only; no nonexistent agent is
  advertised in a strict tool allowlist.
"""
    )

    workflow = ROOT / "policy" / "workflows" / f"{WORKFLOW_NAME}.md"
    if not workflow.is_file():
        raise SystemExit(f"Missing optional workflow artifact: {workflow}")
    shutil.copy2(workflow, output / "workflows" / workflow.name)

    for role, config in roles.items():
        contract = ROOT / "roles" / f"{role}.md"
        if not contract.is_file():
            raise SystemExit(f"Missing role contract: {contract}")
        (output / "agents" / f"{role}.md").write_text(
            frontmatter(role, config, profile["models"][role], allowed_providers) + contract.read_text()
        )

    launcher = ROOT / "adapters" / "pi" / "templates" / f"pi-{profile_name}"
    if not launcher.is_file():
        raise SystemExit(f"Missing Pi launcher template: {launcher}")
    launcher_output = output / launcher.name
    shutil.copy2(launcher, launcher_output)
    launcher_output.chmod(0o755)

    managed_extensions: list[str] = []
    status_extensions = PROFILE_STATUS_EXTENSIONS.get(profile_name)
    if status_extensions:
        extension_output = output / "extensions" / "agent-orchestration"
        extension_output.mkdir(parents=True)
        extension_source = ROOT / "adapters" / "pi" / "extensions"
        for source_name, output_name in status_extensions:
            source = extension_source / source_name
            if not source.is_file():
                raise SystemExit(f"Missing Pi status extension source: {source}")
            shutil.copy2(source, extension_output / output_name)
            managed_extensions.append(f"extensions/agent-orchestration/{output_name}")
        package_output = extension_output / "package.json"
        package_output.write_text(json.dumps({
            "type": "module",
            "pi": {"extensions": [PROFILE_STATUS_ENTRYPOINTS[profile_name]]},
        }, indent=2) + "\n")
        managed_extensions.append("extensions/agent-orchestration/package.json")

    (output / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "adapter": "pi-subagents",
                "adapter_format": "0.67.0",
                "roles": sorted(roles),
                "profiles": [profile_name],
                "launchers": [launcher.name],
                "managed_extensions": managed_extensions,
                "workflows": [WORKFLOW_NAME],
                "shared": [
                    "orchestration-core.md",
                    "control-plane.json",
                    "degradations.md",
                ],
            },
            indent=2,
        )
        + "\n"
    )


def render(output: Path, profile_name: str = "hybrid") -> None:
    if profile_name not in SUPPORTED_PROFILES:
        raise SystemExit(f"Unsupported Pi profile: {profile_name!r}")
    output = assert_safe_output(output, profile_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.render-", dir=output.parent))
    staged = staging_root / "result"
    old = output.parent / f".{output.name}.old-{uuid.uuid4().hex}"
    allowed_root = ROOT if output == (DEFAULT_OUTPUT_ROOT / profile_name).resolve() else TEMP_ROOT
    try:
        render_into(staged, profile_name)
        had_old = output.exists()
        if had_old:
            assert_safe_rename(output, allowed_root)
            assert_safe_rename(old, allowed_root)
            output.rename(old)
        try:
            assert_safe_rename(staged, allowed_root)
            assert_safe_rename(output, allowed_root)
            staged.rename(output)
        except BaseException:
            if had_old and old.exists() and not output.exists():
                assert_safe_rename(old, allowed_root)
                assert_safe_rename(output, allowed_root)
                old.rename(output)
            raise
        if old.exists():
            assert_safe_rename(old, allowed_root)
            shutil.rmtree(old)
    finally:
        if staging_root.exists():
            assert_safe_rename(staging_root, allowed_root)
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="hybrid")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    render(args.output or DEFAULT_OUTPUT_ROOT / args.profile, args.profile)
