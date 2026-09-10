#!/usr/bin/env python3
"""Render the canonical orchestration policy into Codex artifacts."""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required (tomllib).")

import argparse
import json
import shutil
import tempfile
import tomllib
import uuid
from pathlib import Path

ADAPTERS_DIR = Path(__file__).resolve().parents[1]
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

from common import assert_safe_output as shared_assert_safe_output
from common import assert_safe_rename, validate_capabilities, validate_profile

ROOT = Path(__file__).resolve().parents[2]
# Unresolved on purpose: resolving here would make the argparse default
# already-resolved, so a symlink swapped in at "generated/codex" would
# never hit the is_symlink() check below when --output is omitted.
DEFAULT_OUTPUT = ROOT / "generated" / "codex"
DEFAULT_PROFILE = "openai"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

CODEX_MODEL_PREFIX = "openai/"
CODEX_REASONING_EFFORTS = {"max": "xhigh"}
WORKFLOW_NAME = "feature-workflow-pilot"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_profile(name: str) -> dict:
    path = ROOT / "profiles" / f"{name}.toml"
    if not path.is_file():
        raise SystemExit(f"Missing profile: {path}")

    profile = load_toml(path)
    if profile.get("name") != name:
        raise SystemExit(f"Profile name mismatch in {path}")

    return profile


def codex_model(model: str) -> str:
    if not model.startswith(CODEX_MODEL_PREFIX):
        raise SystemExit(f"Codex profile models must use {CODEX_MODEL_PREFIX!r}: {model!r}")

    return model.removeprefix(CODEX_MODEL_PREFIX)


def reasoning_effort(model_config: dict) -> str:
    variant = model_config.get("variant")
    if not isinstance(variant, str) or not variant:
        raise SystemExit(f"Missing profile reasoning variant: {model_config!r}")

    return CODEX_REASONING_EFFORTS.get(variant, variant)


def sandbox_mode(role_config: dict) -> str:
    if role_config.get("edit") == "deny":
        return "read-only"
    if role_config.get("edit") == "allow":
        return "workspace-write"

    raise SystemExit(
        "Codex does not support routing edit permission: "
        f"{role_config.get('edit')!r}"
    )


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_agent(role: str, role_config: dict, model_config: dict, contract: str) -> str:
    return "\n".join(
        [
            f"name = {toml_string(role)}",
            f"description = {toml_string(role_config['description'])}",
            f"model = {toml_string(codex_model(model_config['model']))}",
            f"model_reasoning_effort = {toml_string(reasoning_effort(model_config))}",
            f"sandbox_mode = {toml_string(sandbox_mode(role_config))}",
            f"developer_instructions = {toml_string(contract)}",
            "",
        ]
    )


def render_control_plane(profile: dict) -> str:
    """Render profile control intent using Codex model and effort names."""
    control_plane = profile["control_plane"]
    lines = [f"small_model = {toml_string(codex_model(control_plane['small_model']))}", ""]
    for section, config in (
        ("primary", control_plane["primary"]),
        ("builtins.build", control_plane["builtins"]["build"]),
        ("builtins.plan", control_plane["builtins"]["plan"]),
    ):
        lines.extend(
            [
                f"[{section}]",
                f"model = {toml_string(codex_model(config['model']))}",
                f"effort = {toml_string(config['effort'])}",
                "",
            ]
        )
    return "\n".join(lines)


def render_agents_file(profile: dict) -> str:
    policy = (ROOT / "policy" / "orchestration.md").read_text().rstrip()
    addendum = (ROOT / "profiles" / profile["addendum"]).read_text().rstrip()

    return "\n\n".join(
        [
            "# Agent Orchestration for Codex",
            "Generated from the canonical policy and the active profile. Do not edit manually.",
            policy,
            addendum,
        ]
    ) + "\n"


def validate_inputs(profile_name: str) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]
    profile = load_profile(profile_name)
    validate_profile(
        profile,
        ROOT / "profiles" / f"{profile_name}.toml",
        set(roles),
        "codex",
        require_role_variants=True,
    )
    models = profile.get("models", {})

    if set(models) != set(roles):
        missing = sorted(set(roles) - set(models))
        extra = sorted(set(models) - set(roles))
        raise SystemExit(f"Profile {profile_name} mismatch: missing={missing}, extra={extra}")

    for role, role_config in roles.items():
        validate_capabilities(role, role_config, "codex")
        contract_path = ROOT / "roles" / f"{role}.md"
        if not contract_path.is_file():
            raise SystemExit(f"Missing role contract: {contract_path}")
        render_agent(role, role_config, models[role], contract_path.read_text())

    render_agents_file(profile)


def render_into(output: Path, profile_name: str = DEFAULT_PROFILE) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]
    profile = load_profile(profile_name)
    models = profile["models"]

    for role, role_config in roles.items():
        validate_capabilities(role, role_config, "codex")

    (output / "agents").mkdir(parents=True, exist_ok=True)
    workflow_source = ROOT / "policy" / "workflows" / f"{WORKFLOW_NAME}.md"
    if not workflow_source.is_file():
        raise SystemExit(f"Missing optional workflow artifact: {workflow_source}")
    (output / "workflows").mkdir(parents=True, exist_ok=True)
    shutil.copy2(workflow_source, output / "workflows" / workflow_source.name)
    (output / "control-plane.toml").write_text(render_control_plane(profile))
    for role, role_config in roles.items():
        contract_path = ROOT / "roles" / f"{role}.md"
        if not contract_path.is_file():
            raise SystemExit(f"Missing role contract: {contract_path}")

        (output / "agents" / f"{role}.toml").write_text(
            render_agent(role, role_config, models[role], contract_path.read_text())
        )

    (output / "AGENTS.md").write_text(render_agents_file(profile))


def assert_safe_output(output: Path) -> Path:
    return shared_assert_safe_output(output, DEFAULT_OUTPUT, TEMP_ROOT)


def render(output: Path, profile_name: str = DEFAULT_PROFILE) -> None:
    output = assert_safe_output(output)
    validate_inputs(profile_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.render-", dir=output.parent))
    staged = staging_root / "result"
    old = output.parent / f".{output.name}.old-{uuid.uuid4().hex}"
    allowed_root = ROOT if output == DEFAULT_OUTPUT.resolve() else TEMP_ROOT
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
            if old.is_dir():
                shutil.rmtree(old)
            else:
                old.unlink()
    finally:
        if staging_root.exists():
            assert_safe_rename(staging_root, allowed_root)
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    args = parser.parse_args()
    render(args.output, args.profile)
