#!/usr/bin/env python3
"""Validate versioned repository contracts without provider calls."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HARNESSES_DIR = Path(__file__).resolve().parent
if str(HARNESSES_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESSES_DIR))

from common import validate_capabilities, validate_profile

ROOT = HARNESSES_DIR.parent
VALID_HARNESSES = {"opencode", "codex", "claude-code", "pi"}
SCHEMA_ERROR_LIMIT = 8
ALLOWED_DELEGATES = {
    "planner": frozenset({"explorer"}),
    "reviewer": frozenset({"explorer"}),
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


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read JSON source: {path}") from error


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
    valid_targets = set(roles)
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

    edit_capable = {role for role, config in roles.items() if config["edit"] == "allow"}
    if edit_capable != {"worker", "worker-complex"}:
        rendered = ", ".join(sorted(edit_capable)) or "<none>"
        raise SystemExit(
            "Repository persistence policy: only worker and worker-complex may have "
            f"edit = allow; found {rendered}"
        )
    planner = roles.get("planner")
    if planner is None or planner["edit"] != "deny" or planner["bash"] != "deny":
        raise SystemExit(
            "Repository persistence policy: planner must have edit = deny and bash = deny"
        )
    if planner["delegates"] != ["explorer"]:
        raise SystemExit(
            "Repository persistence policy: planner may delegate only to explorer"
        )
    reviewer = roles.get("reviewer")
    if reviewer is None or reviewer["delegates"] != ["explorer"]:
        raise SystemExit(
            "Repository persistence policy: reviewer may delegate only to explorer"
        )

    for role, config in roles.items():
        if config["mode"] not in {"primary", "subagent"}:
            raise SystemExit(f"Invalid mode for role {role!r}: {config['mode']!r}")
        validate_capabilities(role, config, "opencode")
        contract = ROOT / "roles" / f"{role}.md"
        if not contract.is_file():
            raise SystemExit(f"Missing role contract: {contract}")
    return roles


def validate_evaluations(root: Path) -> int:
    schema = load_json_schema(ROOT / "schema" / "evaluation.schema.json")
    documents: dict[str, list[tuple[Path, dict]]] = {}
    for directory, kind in (
        ("corpora", "evaluation-corpus"),
        ("plans", "evaluation-plan"),
        ("results", "evaluation-result"),
    ):
        entries = []
        for path in sorted((root / directory).glob("*.json")):
            document = load_json(path)
            validate_document(document, schema, source=path)
            if not isinstance(document, dict) or document.get("kind") != kind:
                raise SystemExit(f"Invalid evaluation document kind in {path}: expected {kind!r}")
            entries.append((path, document))
        documents[directory] = entries

    def indexed(directory: str, key: str) -> dict[str, tuple[Path, dict]]:
        result = {}
        for path, document in documents[directory]:
            identifier = document[key]
            if identifier in result:
                raise SystemExit(f"Duplicate evaluation {key} {identifier!r}: {path}")
            result[identifier] = (path, document)
        return result

    corpora = indexed("corpora", "corpus_id")
    plans = indexed("plans", "plan_id")
    indexed("results", "result_id")
    tasks: dict[tuple[str, str], dict] = {}
    for corpus_id, (path, corpus) in corpora.items():
        for task in corpus["tasks"]:
            key = (corpus_id, task["task_id"])
            if key in tasks:
                raise SystemExit(f"Duplicate task_id {task['task_id']!r} in {path}")
            acceptance_ids = [item["acceptance_id"] for item in task["acceptance"]]
            if len(acceptance_ids) != len(set(acceptance_ids)):
                raise SystemExit(f"Duplicate acceptance_id in task {task['task_id']!r}: {path}")
            tasks[key] = task

    for plan_id, (path, plan) in plans.items():
        corpus_id = plan["corpus_ref"]
        if corpus_id not in corpora:
            raise SystemExit(f"Invalid corpus_ref {corpus_id!r} in {path}")
        variant_ids = [item["variant_id"] for item in plan["variants"]]
        if len(variant_ids) != len(set(variant_ids)):
            raise SystemExit(f"Duplicate variant_id in plan {plan_id!r}: {path}")
        for task_id in plan["task_refs"]:
            if (corpus_id, task_id) not in tasks:
                raise SystemExit(f"Invalid task_ref {task_id!r} in {path}")

    for path, result in documents["results"]:
        plan_entry = plans.get(result["plan_ref"])
        if plan_entry is None:
            raise SystemExit(f"Invalid plan_ref {result['plan_ref']!r} in {path}")
        plan = plan_entry[1]
        if result["task_ref"] not in plan["task_refs"]:
            raise SystemExit(f"Invalid task_ref {result['task_ref']!r} in {path}")
        if result["variant_ref"] not in {item["variant_id"] for item in plan["variants"]}:
            raise SystemExit(f"Invalid variant_ref {result['variant_ref']!r} in {path}")
        task = tasks[(plan["corpus_ref"], result["task_ref"])]
        expected = [item["acceptance_id"] for item in task["acceptance"]]
        actual = [item["acceptance_ref"] for item in result["acceptance_evidence"]]
        if actual != expected:
            raise SystemExit(f"Acceptance evidence refs must equal {expected!r} in {path}")
        for criterion, evidence in zip(task["acceptance"], result["acceptance_evidence"]):
            if evidence["status"] == "OBSERVED":
                expected_outcome = (
                    "PASSED" if evidence["actual_exit_code"] == criterion["expected_exit_code"] else "FAILED"
                )
                if evidence["outcome"] != expected_outcome:
                    raise SystemExit(f"Acceptance outcome conflicts with exit code in {path}")
    return sum(len(entries) for entries in documents.values())


def validate_sources(evaluations_root: Path | None = None) -> int:
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
    evaluation_count = validate_evaluations(evaluations_root or ROOT / "evaluations")
    print(
        f"Validated routing, {len(profiles)} versioned profiles, and "
        f"{evaluation_count} evaluation documents."
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluations-root", type=Path)
    arguments = parser.parse_args()
    raise SystemExit(validate_sources(arguments.evaluations_root))
