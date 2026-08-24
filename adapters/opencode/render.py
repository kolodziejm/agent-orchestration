#!/usr/bin/env python3.11
"""Render harness-agnostic policies into OpenCode artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (ROOT / "generated" / "opencode").resolve()
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def frontmatter(role: str, config: dict) -> str:
    lines = [
        "---",
        f"description: {config['description']}",
        f"mode: {config.get('mode', 'subagent')}",
        "permission:",
        f"  edit: {config['edit']}",
        "  bash:",
        f"    \"*\": {config['bash']}",
        "  task:",
        "    \"*\": deny",
    ]
    for target in config.get("delegates", []):
        key = f'"{target}"' if "*" in target else target
        lines.append(f"    {key}: allow")
    lines.extend(["---", ""])
    return "\n".join(lines)


def assert_safe_output(output: Path) -> Path:
    output = output.expanduser().resolve()
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


def render_into(output: Path) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]

    (output / "agents").mkdir(parents=True)
    (output / "profiles" / "_shared").mkdir(parents=True)

    for role, config in roles.items():
        contract_path = ROOT / "roles" / f"{role}.md"
        if not contract_path.is_file():
            raise SystemExit(f"Missing role contract: {contract_path}")
        rendered = frontmatter(role, config) + contract_path.read_text()
        (output / "agents" / f"{role}.md").write_text(rendered)

    shutil.copy2(
        ROOT / "policy" / "orchestration.md",
        output / "profiles" / "_shared" / "orchestration-core.md",
    )

    expected_roles = set(roles)
    profile_names = []
    for profile_path in sorted((ROOT / "profiles").glob("*.toml")):
        profile = load_toml(profile_path)
        if profile.get("harness", "opencode") != "opencode":
            continue
        name = profile["name"]
        profile_names.append(name)
        models = profile["models"]
        if set(models) != expected_roles:
            missing = sorted(expected_roles - set(models))
            extra = sorted(set(models) - expected_roles)
            raise SystemExit(f"Profile {name} mismatch: missing={missing}, extra={extra}")

        destination = output / "profiles" / name
        destination.mkdir(parents=True)
        addendum = ROOT / "profiles" / profile["addendum"]
        shutil.copy2(addendum, destination / "orchestration.md")
        (destination / "agent-routing.json").write_text(
            json.dumps({"agent": {role: dict(value) for role, value in models.items()}}, indent=2, sort_keys=True)
            + "\n"
        )

    (output / "manifest.json").write_text(
        json.dumps(
            {"format_version": 1, "roles": sorted(roles), "profiles": sorted(profile_names)},
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
    try:
        render_into(staged)
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
            shutil.rmtree(old)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.output)
