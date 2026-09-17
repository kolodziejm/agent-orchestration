#!/usr/bin/env python3
"""Render a supported Pi profile into an internal orchestration bundle."""

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
# The bundle format is this repository's internal orchestration schema, not a
# Pi host or runtime-package version.
BUNDLE_FORMAT_VERSION = 1
SUPPORTED_PROFILES = {
    "hybrid": frozenset({"openai", "deepseek"}),
    "openai": frozenset({"openai"}),
    "deepseek": frozenset({"deepseek"}),
    "glm": frozenset({"zai"}),
}
# The generic profiles/glm.toml belongs to other harnesses. Keep the Pi source
# profile separate and resolve the user-facing Pi identifier explicitly.
PROFILE_SOURCE_FILES = {
    "hybrid": "hybrid.toml",
    "openai": "openai.toml",
    "deepseek": "deepseek.toml",
    "glm": "pi-glm.toml",
}
PROFILE_SOURCE_NAMES = {
    "hybrid": "hybrid",
    "openai": "openai",
    "deepseek": "deepseek",
    "glm": "pi-glm",
}
PROFILE_STATUS_EXTENSIONS = {
    "hybrid": (("deepseek-price-status.js", "deepseek-price-status.js"),),
    "deepseek": (("deepseek-price-status.js", "deepseek-price-status.js"),),
    "openai": (
        ("codex-pace-status.js", "codex-pace-core.mjs"),
        ("codex-pace-loader.ts", "codex-pace-loader.ts"),
    ),
    "glm": (("glm-price-status.js", "glm-price-status.js"),),
}
PROFILE_STATUS_ENTRYPOINTS = {
    "hybrid": "./deepseek-price-status.js",
    "openai": "./codex-pace-loader.ts",
    "deepseek": "./deepseek-price-status.js",
    "glm": "./glm-price-status.js",
}
PROFILE_EXTENSION_FILES = ("git-read.ts", "primary-policy.js")
PI_OPERATIONAL_NOTE = """## Pi operational note

For every Pi Agent call, set `max_turns`. Source-changing `worker` and `worker-complex` calls default to `run_in_background: true`; foreground calls require a clearly brief, bounded scope and a low turn cap. Use conservative defaults of foreground ≤12 turns and background mutation ≤30 turns. Apply the canonical cap behavior: exceeding a slice requires a new orchestrator decision rather than automatic continuation. Every potentially blocking child tool call additionally uses its native timeout or an OS/harness-enforced timeout. `max_turns` alone is insufficient because it does not bound a single tool call. If enforceable timeout and termination are unavailable, do not delegate that operation; keep it bounded in the primary or return `BLOCKED`.
"""
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
# Validator gets a distinct deterministic acceptance list. It intentionally
# omits video/recording, lifecycle, session/device-management, and code-eval
# capabilities granted to neither mechanical acceptance nor a prepared UX run.
VALIDATOR_MCP_TOOLS = [
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
    if role == "explorer":
        tools.append("git_read")
    if config["edit"] == "allow":
        tools.extend(["edit", "write"])
    # Pi cannot represent the canonical `ask` capability. These narrowly scoped
    # exceptions need commands for their contracts while preserving role-specific
    # source-editing boundaries. Planner and design-partner deliberately have
    # no bash/edit/write capabilities under the canonical read-only contract.
    if config["bash"] == "allow" or role in {"validator", "debugger"}:
        tools.append("bash")
    if role == "validator":
        tools.extend(VALIDATOR_MCP_TOOLS)
    delegates = set(config.get("delegates", []))
    if delegates & {"explorer"}:
        tools.append("subagent")
    return tools


def frontmatter(role: str, config: dict, model_config: dict, allowed_providers: frozenset[str]) -> str:
    lines = [
        "---",
        f"name: {json.dumps(role)}",
        f"description: {json.dumps(config['description'])}",
        f"model: {pi_model(model_config['model'], allowed_providers)}",
        f"thinking: {model_config['variant']}",
        f"tools: {', '.join(tools_for(role, config))}",
    ]
    if role == "explorer":
        lines.append("acceptanceRole: read-only")
    lines.extend([
        "defaultContext: fresh",
        "systemPromptMode: replace",
        "inheritProjectContext: false",
        "inheritSkills: false",
        "---",
        "",
    ])
    return "\n".join(lines)


def control_plane(
    profile: dict,
    allowed_providers: frozenset[str],
    profile_name: str | None = None,
) -> dict:
    source = profile["control_plane"]
    return {
        "profile": profile_name or profile["name"],
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
            "The profile launcher selects the primary model and Pi agent files configure "
            "child roles. Canonical policy restricts planner and reviewer delegation to "
            "the exact child target `explorer`; runtimes without a public framework-neutral "
            "child-target enforcement API represent that restriction in policy and rendered "
            "tool lists, not runtime enforcement. Pi cannot install the small-model or "
            "built-in mappings; those values are recorded as control-plane intent."
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
    profile_path = ROOT / "profiles" / PROFILE_SOURCE_FILES[profile_name]
    profile = load_toml(profile_path)
    expected_name = PROFILE_SOURCE_NAMES[profile_name]
    if profile.get("name") != expected_name:
        raise SystemExit(
            f"Pi profile source {profile_path} must declare name = {expected_name!r}"
        )
    # The legacy OpenAI/DeepSeek/Hybrid sources are shared with other
    # adapters and may omit harness metadata. The Pi-specific GLM source is
    # owned by this adapter, so its harness declaration remains mandatory.
    if profile_name == "glm" and profile.get("harness") != "pi":
        raise SystemExit(
            f"Pi profile source {profile_path} must declare harness = \"pi\""
        )
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
        f"{policy}\n\n{addendum}\n\n{PI_OPERATIONAL_NOTE}"
    )
    (output / "_shared" / "control-plane.json").write_text(
        json.dumps(control_plane(profile, allowed_providers, profile_name), indent=2, sort_keys=True) + "\n"
    )
    (output / "_shared" / "degradations.md").write_text(
        """# Pi adapter degradations

- Pi's native child permission model rejects `permissions.bash` and always allows shell calls
  when the `bash` tool is present. For canonical `bash = \"ask\"` roles other than validator
  and debugger this adapter omits `bash`, enforcing a stricter no-shell ceiling. Command-level
  permissions remain operator-owned runtime state; this bundle and its installer do not copy or claim
  permission configuration or bridges. Headless children still cannot forward an `ask` decision to the parent UI.
- The profile launcher selects the primary session and Pi user agent files configure
  subagents. Pi cannot install the small model or built-in build/plan mappings; their
  mapped values are recorded in `control-plane.json` as profile intent and are not installed.
- Validator and debugger receive `bash` despite canonical `bash = "ask"` because their
  contracts require mechanical checks or repository commands. Planner and design-partner
  are structurally read-only and omit `bash`, `edit`, and `write`; reviewer remains
  read-only and explorer remains read-only. Debugger remains source-edit read-only.
- Validator has a separate deterministic browser/Appium MCP allowlist. Direct MCP tools
  require an available background/async child and a prepared URL/session; when that
  provider or session is unavailable, acceptance is reported as `BLOCKED`, never shifted
  to UX-Critic. The validator list excludes video/recording, evaluation, upload/drop/tab,
  lifecycle, device/session management, file, driver-settings, perform-actions, and clipboard
  controls. UX-Critic's independent allowlist remains unchanged.
- UX-Critic is an on-demand, read-only runtime audit. Its Pi agent file has an
  explicit allowlist of verified Playwright MCP and Appium MCP interaction,
  inspection, screenshot, and recording tools, plus Pi's built-in image-capable
  `read` for opening saved screenshots. `read` is its only filesystem capability;
  it receives no `edit`, `write`, or shell tools. The primary must supply the
  running URL/session, device, scope, identity, reference, and screenshot
  destination first.
- Planner and reviewer receive the `subagent` tool, and canonical policy restricts both to
  the exact child target `explorer`; all other canonical roles receive no `subagent` tool.
  On runtimes without a public framework-neutral child-target enforcement API, this is a
  policy-level boundary represented in role contracts and rendered tool lists, not runtime enforcement.
  The bundle does not claim fail-closed package integration. This boundary is
  not an OS sandbox or a command-level shell policy.
- Every other canonical role is a leaf and receives no `subagent` tool. When
  the primary cannot inspect images natively, it routes visual work directly
  to an existing image-capable role according to the shared policy.
- `explorer` receives the manifest-owned `git_read` child tool and still has no
  `bash` capability. Its frontmatter declares `acceptanceRole: read-only` for
  acceptance inference only; this metadata does not grant or revoke tools or
  command execution. The `git_read` capability remains read-only, worktree-bound,
  and exposes only status plus bounded worktree/staged/range diffs with patch,
  stat, or name-status views. It derives the boundary from the nearest
  non-symlinked `.git` directory or linked-worktree marker file and requires
  Git's reported top level to match it exactly; validated paths are passed
  directly after `--` under fixed literal-pathspec mode. Every Git process uses
  fixed argv/environment hardening, no network/hooks/pagers/external diff/textconv,
  a shared 10-second deadline, and aggregate 64 KiB/2,000-line caps across stdout
  and stderr. The extension deliberately uses a private bounded `spawn` helper
  instead of the host's unbounded `pi.exec` buffering; it never persists full output.
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
    extension_output = output / "extensions" / "agent-orchestration"
    extension_output.mkdir(parents=True)
    extension_source = ROOT / "adapters" / "pi" / "extensions"
    for source_name in PROFILE_EXTENSION_FILES:
        source = extension_source / source_name
        if not source.is_file():
            raise SystemExit(f"Missing Pi extension source: {source}")
        shutil.copy2(source, extension_output / source_name)
        managed_extensions.append(f"extensions/agent-orchestration/{source_name}")

    status_extensions = PROFILE_STATUS_EXTENSIONS.get(profile_name, ())
    for source_name, output_name in status_extensions:
        source = extension_source / source_name
        if not source.is_file():
            raise SystemExit(f"Missing Pi status extension source: {source}")
        shutil.copy2(source, extension_output / output_name)
        managed_extensions.append(f"extensions/agent-orchestration/{output_name}")
    package_output = extension_output / "package.json"
    status_entrypoint = PROFILE_STATUS_ENTRYPOINTS.get(profile_name)
    package_extensions = ["./primary-policy.js"] + ([status_entrypoint] if status_entrypoint else []) + ["./git-read.ts"]
    package_output.write_text(json.dumps({
        "type": "module",
        "pi": {"extensions": package_extensions},
    }, indent=2) + "\n")
    managed_extensions.append("extensions/agent-orchestration/package.json")

    (output / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": BUNDLE_FORMAT_VERSION,
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
