#!/usr/bin/env python3
"""Check an OpenCode runtime configuration against a versioned source profile."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ADAPTERS_DIR = Path(__file__).resolve().parents[1]
if str(ADAPTERS_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTERS_DIR))

from common import validate_profile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = "openai"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_sources(profile_name: str) -> tuple[dict, dict]:
    routing_path = ROOT / "policy" / "routing.toml"
    profile_path = ROOT / "profiles" / f"{profile_name}.toml"
    try:
        routing = load_toml(routing_path)
    except OSError as error:
        raise SystemExit(f"Cannot read routing policy: {routing_path}") from error
    try:
        profile = load_toml(profile_path)
    except OSError as error:
        raise SystemExit(f"Cannot read profile: {profile_path}") from error
    roles = routing.get("roles", {})
    if not isinstance(roles, dict):
        raise SystemExit(f"Invalid routing roles in {routing_path}")
    validate_profile(profile, profile_path, set(roles), "opencode")
    return routing, profile


def config_path_for(target: Path, profile_name: str, config: Path | None) -> tuple[Path, Path]:
    if config is not None:
        config_path = config.expanduser()
        if target != Path.home() / ".config" / "opencode":
            return target.expanduser(), config_path
        # A directly supplied profile config is useful with an isolated fixture.
        if config_path.parent.name == profile_name and config_path.name == "opencode.json":
            return config_path.parent.parent.parent, config_path
        return target.expanduser(), config_path
    target = target.expanduser()
    return target, target / "profiles" / profile_name / "opencode.json"


def _actual_model_and_variant(config: object) -> tuple[object, object]:
    if not isinstance(config, dict):
        return None, None
    model = config.get("model")
    variant = config.get("variant")
    if isinstance(model, dict):
        variant = model.get("variant", variant)
        model = model.get("model")
    return model, variant


def _compare_value(drifts: list[str], label: str, expected: object, actual: object) -> None:
    if expected != actual:
        drifts.append(f"{label}: expected {expected!r}, actual {actual!r}")


def _compare_agent(
    drifts: list[str], label: str, expected: dict, actual: object, *, require_variant: bool
) -> None:
    if not isinstance(actual, dict):
        drifts.append(f"{label}: expected a managed agent mapping")
        return
    _compare_value(drifts, f"{label} model", expected.get("model"), actual.get("model"))
    if require_variant:
        _compare_value(drifts, f"{label} variant", expected.get("variant"), actual.get("variant"))


def compare_runtime(
    config: dict, profile: dict, routing: dict, target: Path, profile_name: str
) -> list[str]:
    drifts: list[str] = []
    control_plane = profile["control_plane"]
    primary_model, primary_variant = _actual_model_and_variant(config)
    _compare_value(
        drifts,
        "primary model",
        control_plane["primary"]["model"],
        primary_model,
    )
    _compare_value(
        drifts,
        "primary effort",
        control_plane["primary"]["effort"],
        primary_variant,
    )
    _compare_value(drifts, "small_model", control_plane["small_model"], config.get("small_model"))

    agents = config.get("agent")
    if not isinstance(agents, dict):
        drifts.append("managed agents: expected an agent mapping")
        agents = {}
    for name, expected in control_plane["builtins"].items():
        _compare_agent(
            drifts,
            f"built-in {name}",
            {"model": expected["model"], "variant": expected["effort"]},
            agents.get(name),
            require_variant=True,
        )
    for role, expected in profile["models"].items():
        _compare_agent(
            drifts,
            f"managed subagent {role}",
            expected,
            agents.get(role),
            require_variant="variant" in expected,
        )

    instructions = config.get("instructions")
    expected_instructions = [
        str(target / "profiles" / "_shared" / "orchestration-core.md"),
        str(target / "profiles" / profile_name / "orchestration.md"),
    ]
    if not isinstance(instructions, list) or not all(isinstance(value, str) for value in instructions):
        drifts.append("instruction files: expected a list of paths")
    else:
        managed = [
            value
            for value in instructions
            if value in expected_instructions
            or value.endswith("/profiles/_shared/orchestration-core.md")
            or value.endswith(f"/profiles/{profile_name}/orchestration.md")
        ]
        if managed != expected_instructions:
            drifts.append(
                "instruction files: expected managed paths "
                f"{expected_instructions!r}, actual managed paths {managed!r}"
            )

    return drifts


def check_runtime(profile_name: str, target: Path, config: Path | None) -> int:
    routing, profile = load_sources(profile_name)
    target, config_path = config_path_for(target, profile_name, config)
    try:
        raw = config_path.read_text()
        runtime = json.loads(raw)
    except FileNotFoundError:
        print(f"OpenCode runtime config is missing: {config_path}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError):
        print(f"OpenCode runtime config is unreadable JSON: {config_path}", file=sys.stderr)
        return 1
    if not isinstance(runtime, dict):
        print(f"OpenCode runtime config must be a JSON object: {config_path}", file=sys.stderr)
        return 1

    drifts = compare_runtime(runtime, profile, routing, target, profile_name)
    if not drifts:
        print(f"OpenCode runtime for profile {profile_name!r} is synchronized.")
        return 0

    print(f"OpenCode runtime drift detected for profile {profile_name!r}:")
    for drift in drifts:
        print(f"DRIFT: {drift}")
    print("Action: run ./scripts/install-opencode against this target after reviewing the diff.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.home() / ".config" / "opencode",
        help="OpenCode target root containing profiles/<name>/opencode.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="specific OpenCode JSON config; overrides the profile config under --target",
    )
    args = parser.parse_args(argv)
    return check_runtime(args.profile, args.target, args.config)


if __name__ == "__main__":
    raise SystemExit(main())
