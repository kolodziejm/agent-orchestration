#!/usr/bin/env python3
"""Validate canonical routing and every versioned profile without provider calls."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ADAPTERS_DIR = Path(__file__).resolve().parent
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

from common import validate_capabilities, validate_profile

ROOT = ADAPTERS_DIR.parent
VALID_HARNESSES = {"opencode", "codex", "claude-code", "pi"}


def load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as error:
        raise SystemExit(f"Cannot read TOML source: {path}") from error


def validate_routing(routing: dict) -> dict:
    if routing.get("version") != 1:
        raise SystemExit(f"Invalid routing version: {routing.get('version')!r}")
    roles = routing.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise SystemExit("Routing roles must be a non-empty table")
    required = {"description", "mode", "edit", "bash", "delegates"}
    for role, config in roles.items():
        if not isinstance(role, str) or not role:
            raise SystemExit(f"Invalid role name: {role!r}")
        if not isinstance(config, dict) or set(config) != required:
            raise SystemExit(f"Invalid routing entry for role {role!r}")
        if config["mode"] not in {"primary", "subagent"}:
            raise SystemExit(f"Invalid mode for role {role!r}: {config['mode']!r}")
        validate_capabilities(role, config, "opencode")
        contract = ROOT / "roles" / f"{role}.md"
        if not contract.is_file():
            raise SystemExit(f"Missing role contract: {contract}")
    return roles


def validate_sources() -> int:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = validate_routing(routing)
    profiles = []
    claude_profiles = []
    for path in sorted((ROOT / "profiles").glob("*.toml")):
        profile = load_toml(path)
        harness = profile.get("harness", "opencode")
        if harness not in VALID_HARNESSES:
            raise SystemExit(f"Invalid harness in {path}: {harness!r}")
        validate_profile(
            profile,
            path,
            set(roles),
            harness,
            require_role_variants=harness in {"claude-code", "pi"},
        )
        addendum = ROOT / "profiles" / profile["addendum"]
        if not addendum.is_file():
            raise SystemExit(f"Missing profile addendum: {addendum}")
        profiles.append(profile["name"])
        if harness == "claude-code":
            claude_profiles.append(profile["name"])

    if claude_profiles != ["claude"]:
        raise SystemExit(
            "Expected exactly one Claude Code profile named 'claude'; "
            f"found {claude_profiles!r}"
        )
    workflow = ROOT / "policy" / "workflows" / "feature-workflow-pilot.md"
    if not workflow.is_file():
        raise SystemExit(f"Missing optional workflow artifact: {workflow}")
    print(f"Validated routing and {len(profiles)} versioned profiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate_sources())
