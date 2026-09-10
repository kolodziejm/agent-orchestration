#!/usr/bin/env python3
"""Render the OpenAI profile using the pi-subagents v0.67.0 tested baseline."""

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
DEFAULT_OUTPUT = ROOT / "generated" / "pi"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
WORKFLOW_NAME = "feature-workflow-pilot"
PROFILE_NAME = "openai"
READ_TOOLS = ["read", "grep", "find", "ls"]
SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def pi_model(model: str) -> str:
    prefix = "openai/"
    if not model.startswith(prefix) or len(model) == len(prefix):
        raise SystemExit(f"Pi adapter requires an openai/<model-id> model, got {model!r}")
    mapped = f"openai-codex/{model[len(prefix):]}"
    if not SAFE_MODEL.fullmatch(mapped):
        raise SystemExit(f"Unsafe Pi model token: {mapped!r}")
    return mapped


def tools_for(config: dict) -> list[str]:
    tools = list(READ_TOOLS)
    if config["edit"] == "allow":
        tools.extend(["edit", "write"])
    if config["bash"] == "allow":
        tools.append("bash")
    delegates = set(config.get("delegates", []))
    if delegates & {"explorer", "spec-writer"}:
        tools.append("subagent")
    return tools


def frontmatter(role: str, config: dict, model_config: dict) -> str:
    return "\n".join(
        [
            "---",
            f"name: {json.dumps(role)}",
            f"description: {json.dumps(config['description'])}",
            f"model: {pi_model(model_config['model'])}",
            f"thinking: {model_config['variant']}",
            f"tools: {', '.join(tools_for(config))}",
            "defaultContext: fresh",
            "systemPromptMode: replace",
            "inheritProjectContext: false",
            "inheritSkills: false",
            "---",
            "",
        ]
    )


def control_plane(profile: dict) -> dict:
    source = profile["control_plane"]
    return {
        "profile": profile["name"],
        "primary": {
            "model": pi_model(source["primary"]["model"]),
            "thinking": source["primary"]["effort"],
        },
        "small_model": pi_model(source["small_model"]),
        "builtins": {
            name: {
                "model": pi_model(config["model"]),
                "thinking": config["effort"],
            }
            for name, config in source["builtins"].items()
        },
        "installed": False,
        "note": (
            "pi-subagents agent files configure child roles only; primary, small-model, "
            "and built-in mappings are recorded as control-plane intent."
        ),
    }


def assert_safe_output(output: Path) -> Path:
    return shared_assert_safe_output(output, DEFAULT_OUTPUT, TEMP_ROOT)


def render_into(output: Path) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]
    profile_path = ROOT / "profiles" / f"{PROFILE_NAME}.toml"
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
        json.dumps(control_plane(profile), indent=2, sort_keys=True) + "\n"
    )
    (output / "_shared" / "degradations.md").write_text(
        """# Pi adapter degradations

- Supported pi-subagents releases at or above the v0.67.0 minimum-tested baseline reject `permissions.bash` and always allow shell calls
  when the `bash` tool is present. For every canonical `bash = \"ask\"` role this
  adapter omits `bash`, enforcing a stricter no-shell ceiling. Install and configure
  a separate permission wrapper if command-level allow/deny behavior is required; headless
  children still cannot forward an `ask` decision to the parent UI.
- Pi user agent files configure subagents, not the primary session, small model, or
  built-in build/plan agents. Their mapped values are recorded in `control-plane.json`
  as profile intent and are not installed by this adapter.
- The OpenAI profile has no concrete `vision-*` role among its ten canonical roles.
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
            frontmatter(role, config, profile["models"][role]) + contract.read_text()
        )

    (output / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "adapter": "pi-subagents",
                "adapter_format": "0.67.0",
                "roles": sorted(roles),
                "profiles": [PROFILE_NAME],
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


def render(output: Path) -> None:
    output = assert_safe_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.render-", dir=output.parent))
    staged = staging_root / "result"
    old = output.parent / f".{output.name}.old-{uuid.uuid4().hex}"
    allowed_root = ROOT if output == DEFAULT_OUTPUT.resolve() else TEMP_ROOT
    try:
        render_into(staged)
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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.output)
