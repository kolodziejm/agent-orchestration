#!/usr/bin/env python3
"""Validate canonical routing and every versioned profile without provider calls."""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ADAPTERS_DIR = Path(__file__).resolve().parent
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

from common import validate_capabilities, validate_profile

ROOT = ADAPTERS_DIR.parent
VALID_HARNESSES = {"opencode", "codex", "claude-code", "pi"}
SCHEMA_ERROR_LIMIT = 8
VIRTUAL_DELEGATION_TARGETS = frozenset({"vision-*"})
ALLOWED_DELEGATES = {
    "planner": frozenset({"explorer", "spec-writer"}),
    "reviewer": frozenset({"explorer"}),
    "worker": frozenset({"vision-*"}),
    "worker-complex": frozenset({"vision-*"}),
}


def load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as error:
        raise SystemExit(f"Cannot read TOML source: {path}") from error


def load_json_schema(path: Path) -> dict:
    """Load and self-check one Draft 2020-12 schema before using it."""
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read JSON Schema source: {path}") from error
    if not isinstance(schema, dict):
        raise SystemExit(f"Invalid JSON Schema source: {path} must contain an object")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise SystemExit(f"Invalid Draft 2020-12 schema: {path}") from error
    return schema


def format_json_path(parts: Iterable[object]) -> str:
    """Format an instance path without allowing unbounded third-party text."""
    result = "$"
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        elif isinstance(part, str) and part.isidentifier():
            result += f".{part}"
        else:
            result += f"[{json.dumps(str(part), ensure_ascii=False)}]"
    return result


def validate_document(document: object, schema: dict, *, source: Path) -> None:
    """Raise a stable, bounded diagnostic for a schema-invalid document."""
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: (
            tuple((type(part).__name__, str(part)) for part in error.absolute_path),
            error.message,
        ),
    )
    if not errors:
        return
    shown = errors[:SCHEMA_ERROR_LIMIT]
    lines = [f"Schema validation failed for {source} ({len(errors)} error(s)):"]
    for error in shown:
        message = error.message.replace("\n", " ")[:240]
        lines.append(f"- {format_json_path(error.absolute_path)}: {message}")
    omitted = len(errors) - len(shown)
    if omitted:
        lines.append(f"- ... {omitted} additional schema error(s) omitted")
    raise SystemExit("\n".join(lines))


def validate_delegation_graph(roles: dict[str, dict]) -> None:
    """Validate only the canonical role graph and its fail-closed leaf boundary."""
    valid_targets = set(roles) | set(VIRTUAL_DELEGATION_TARGETS)
    for role in sorted(roles):
        config = roles[role]
        delegates = config.get("delegates", [])
        if not isinstance(delegates, list):
            # The schema normally emits this diagnostic first. Keep direct
            # callers fail-closed without leaking a Python iteration error.
            raise SystemExit(
                f"Delegation graph: invalid delegates for role {role!r}; expected an array"
            )
        for target in delegates:
            if not isinstance(target, str) or target not in valid_targets:
                raise SystemExit(
                    f"Delegation graph: unknown delegation target for role {role!r}: {target!r}"
                )

    colors = {role: 0 for role in sorted(roles)}
    stack: list[str] = []

    def visit(role: str) -> None:
        colors[role] = 1
        stack.append(role)
        for target in sorted(
            target for target in roles[role].get("delegates", []) if target in roles
        ):
            if colors[target] == 0:
                visit(target)
            elif colors[target] == 1:
                cycle = stack[stack.index(target):] + [target]
                raise SystemExit(
                    "Delegation graph: cycle detected: " + " -> ".join(cycle)
                )
        stack.pop()
        colors[role] = 2

    for role in sorted(roles):
        if colors[role] == 0:
            visit(role)

    for role in sorted(roles):
        delegates = roles[role].get("delegates", [])
        allowed = ALLOWED_DELEGATES.get(role)
        if allowed is None:
            if delegates:
                rendered = ", ".join(repr(target) for target in delegates)
                raise SystemExit(
                    f"Delegation graph: leaf role {role!r} must declare delegates = []; "
                    f"found [{rendered}]"
                )
            continue
        for target in delegates:
            if target not in allowed:
                raise SystemExit(
                    f"Delegation graph: delegation edge is not allowed: {role} -> {target}"
                )


def validate_routing(
    routing: dict,
    *,
    source: Path | None = None,
    schema: dict | None = None,
) -> dict:
    source = source or ROOT / "policy" / "routing.toml"
    validate_document(
        routing,
        schema or load_json_schema(ROOT / "schema" / "policy.schema.json"),
        source=source,
    )
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

    # Unknown targets and cycles intentionally precede policy-edge checks so
    # each failure category remains deterministic and independently useful.
    validate_delegation_graph(roles)
    for role, config in roles.items():
        if config["mode"] not in {"primary", "subagent"}:
            raise SystemExit(f"Invalid mode for role {role!r}: {config['mode']!r}")
        validate_capabilities(role, config, "opencode")
        contract = ROOT / "roles" / f"{role}.md"
        if not contract.is_file():
            raise SystemExit(f"Missing role contract: {contract}")
    return roles


def validate_sources() -> int:
    routing_path = ROOT / "policy" / "routing.toml"
    routing = load_toml(routing_path)
    policy_schema = load_json_schema(ROOT / "schema" / "policy.schema.json")
    profile_schema = load_json_schema(ROOT / "schema" / "profile.schema.json")
    roles = validate_routing(routing, source=routing_path, schema=policy_schema)
    profiles = []
    claude_profiles = []
    for path in sorted((ROOT / "profiles").glob("*.toml")):
        profile = load_toml(path)
        validate_document(profile, profile_schema, source=path)
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
