#!/usr/bin/env python3
"""Render harness-agnostic policies into OpenCode artifacts."""

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
from common import assert_safe_rename, validate_capabilities

ROOT = Path(__file__).resolve().parents[2]
# Unresolved on purpose: resolving here would make the argparse default
# already-resolved, so a symlink swapped in at "generated/opencode" would
# never hit the is_symlink() check below when --output is omitted.
DEFAULT_OUTPUT = ROOT / "generated" / "opencode"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

VALID_HARNESSES = {"opencode", "codex", "claude-code"}


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
    return shared_assert_safe_output(output, DEFAULT_OUTPUT, TEMP_ROOT)


def render_into(output: Path) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]

    for role, config in roles.items():
        validate_capabilities(role, config, "opencode")

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
        harness = profile.get("harness", "opencode")
        if harness not in VALID_HARNESSES:
            raise SystemExit(f"Invalid harness in {profile_path}: {harness!r}")
        if harness != "opencode":
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

    if not profile_names:
        # An empty profile set would make the installer delete every managed
        # profile it finds on disk instead of leaving them alone.
        raise SystemExit(
            "No profile with harness = \"opencode\" matched under profiles/; "
            "refusing to render an empty profile set"
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
