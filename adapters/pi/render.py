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
SUPPORTED_PROFILES = {"openai": "openai", "deepseek": "deepseek"}
READ_TOOLS = ["read", "grep", "find", "ls"]
SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def pi_model(model: str, provider: str) -> str:
    mappings = {"openai": ("openai/", "openai-codex/"), "deepseek": ("deepseek/", "deepseek/")}
    if provider not in mappings:
        raise SystemExit(f"Unsupported Pi provider: {provider!r}")
    prefix, destination = mappings[provider]
    if not model.startswith(prefix) or len(model) == len(prefix):
        raise SystemExit(f"Pi {provider} profile requires an {prefix}<model-id> model, got {model!r}")
    mapped = f"{destination}{model[len(prefix):]}"
    if not SAFE_MODEL.fullmatch(mapped):
        raise SystemExit(f"Unsafe Pi model token: {mapped!r}")
    return mapped


def tools_for(role: str, config: dict) -> list[str]:
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


def frontmatter(role: str, config: dict, model_config: dict, provider: str) -> str:
    return "\n".join(
        [
            "---",
            f"name: {json.dumps(role)}",
            f"description: {json.dumps(config['description'])}",
            f"model: {pi_model(model_config['model'], provider)}",
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


def control_plane(profile: dict, provider: str) -> dict:
    source = profile["control_plane"]
    return {
        "profile": profile["name"],
        "primary": {
            "model": pi_model(source["primary"]["model"], provider),
            "thinking": source["primary"]["effort"],
        },
        "small_model": pi_model(source["small_model"], provider),
        "builtins": {
            name: {
                "model": pi_model(config["model"], provider),
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


def assert_safe_output(output: Path, profile_name: str = "openai") -> Path:
    return shared_assert_safe_output(output, DEFAULT_OUTPUT_ROOT / profile_name, TEMP_ROOT)


def render_into(output: Path, profile_name: str = "openai") -> None:
    provider = SUPPORTED_PROFILES.get(profile_name)
    if provider is None:
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
        json.dumps(control_plane(profile, provider), indent=2, sort_keys=True) + "\n"
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
            frontmatter(role, config, profile["models"][role], provider) + contract.read_text()
        )

    launcher = ROOT / "adapters" / "pi" / "templates" / f"pi-{profile_name}"
    if not launcher.is_file():
        raise SystemExit(f"Missing Pi launcher template: {launcher}")
    launcher_output = output / launcher.name
    shutil.copy2(launcher, launcher_output)
    launcher_output.chmod(0o755)

    (output / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "adapter": "pi-subagents",
                "adapter_format": "0.67.0",
                "roles": sorted(roles),
                "profiles": [profile_name],
                "launchers": [launcher.name],
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


def render(output: Path, profile_name: str = "openai") -> None:
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
    parser.add_argument("--profile", default="openai")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    render(args.output or DEFAULT_OUTPUT_ROOT / args.profile, args.profile)
