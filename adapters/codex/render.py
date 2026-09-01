#!/usr/bin/env python3.11
"""Render the canonical orchestration policy into Codex artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (ROOT / "generated" / "codex").resolve()
DEFAULT_PROFILE = "openai"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

CODEX_MODEL_PREFIX = "openai/"
CODEX_REASONING_EFFORTS = {"max": "xhigh"}


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
    models = profile.get("models", {})

    if set(models) != set(roles):
        missing = sorted(set(roles) - set(models))
        extra = sorted(set(models) - set(roles))
        raise SystemExit(f"Profile {profile_name} mismatch: missing={missing}, extra={extra}")

    for role, role_config in roles.items():
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

    (output / "agents").mkdir(parents=True, exist_ok=True)
    for role, role_config in roles.items():
        contract_path = ROOT / "roles" / f"{role}.md"
        if not contract_path.is_file():
            raise SystemExit(f"Missing role contract: {contract_path}")

        (output / "agents" / f"{role}.toml").write_text(
            render_agent(role, role_config, models[role], contract_path.read_text())
        )

    (output / "AGENTS.md").write_text(render_agents_file(profile))


def assert_safe_output(output: Path) -> Path:
    output = output.expanduser()
    if output.is_symlink():
        raise SystemExit(f"Refusing symlinked output path: {output}")

    output = output.resolve()
    if output == DEFAULT_OUTPUT:
        return output

    try:
        output.relative_to(TEMP_ROOT)
    except ValueError as error:
        raise SystemExit(
            f"Refusing unsafe output path: {output}. "
            f"Use {DEFAULT_OUTPUT} or a directory below {TEMP_ROOT}."
        ) from error
    if output == TEMP_ROOT:
        raise SystemExit(f"Refusing to replace temporary root: {output}")

    return output


def render(output: Path, profile_name: str = DEFAULT_PROFILE) -> None:
    output = assert_safe_output(output)
    validate_inputs(profile_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.render-", dir=output.parent))
    staged = staging_root / "result"
    old = output.parent / f".{output.name}.old-{uuid.uuid4().hex}"
    try:
        render_into(staged, profile_name)
        had_old = output.exists()
        if had_old:
            output.rename(old)
        try:
            staged.rename(output)
        except BaseException:
            if had_old and old.exists() and not output.exists():
                old.rename(output)
            raise
        if old.exists():
            if old.is_dir():
                shutil.rmtree(old)
            else:
                old.unlink()
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    args = parser.parse_args()
    render(args.output, args.profile)
