#!/usr/bin/env python3
"""Generate isolated OMP profile bundles from canonical routing and model sources."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import tomllib
from pathlib import Path

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required (tomllib).")

ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = ROOT / "harnesses"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))
from common import assert_safe_output, validate_profile

DEFAULT_ROOT = ROOT / "build" / "omp"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
PROFILES = {
    "hybrid": ("hybrid.toml", "hybrid", {"openai", "deepseek"}),
    "openai": ("openai.toml", "openai", {"openai"}),
    "deepseek": ("deepseek.toml", "deepseek", {"deepseek"}),
    "glm": ("pi-glm.toml", "pi-glm", {"zai"}),
}
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def model_selector(token: str, providers: set[str], effort: str | None = None) -> str:
    if not isinstance(token, str) or token.count("/") != 1:
        raise SystemExit(f"Malformed OMP model token: {token!r}")
    provider, model_id = token.split("/", 1)
    if provider not in providers or not SAFE_TOKEN.fullmatch(model_id):
        raise SystemExit(f"Unsupported or unsafe OMP model token: {token!r}")
    provider = "openai-codex" if provider == "openai" else provider
    value = f"{provider}/{model_id}"
    return f"{value}:{effort}" if effort else value


def load(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"Cannot load profile source {path}: {error}") from error


def generate(output: Path, name: str) -> None:
    if name not in PROFILES:
        raise SystemExit(f"Unsupported OMP profile: {name!r}")
    source_name, expected_name, providers = PROFILES[name]
    profile_path = ROOT / "profiles" / source_name
    profile = load(profile_path)
    if profile.get("name") != expected_name:
        raise SystemExit(f"OMP profile source {profile_path} must declare name = {expected_name!r}")
    if name in {"deepseek", "glm"} and profile.get("harness") != "pi":
        raise SystemExit(f"OMP profile source {profile_path} must declare harness = \"pi\"")
    routing = load(ROOT / "policy" / "routing.toml")
    roles = routing.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise SystemExit("Invalid canonical routing roles")
    validate_profile(profile, profile_path, set(roles), "opencode", require_role_variants=True)
    cp = profile["control_plane"]
    role_models = {"default": cp["primary"], "smol": {"model": cp["small_model"]},
                   "plan": cp["builtins"]["plan"]}
    for role, model in profile["models"].items():
        role_models[role] = {"model": model["model"], "effort": model["variant"]}
    lines = ["modelRoles:"]
    for role, model in role_models.items():
        effort = model.get("effort")
        selector = model_selector(model["model"], providers, effort)
        lines.append(f"  {role}: {json.dumps(selector)}")
    target = assert_safe_output(output, DEFAULT_ROOT / name, TEMP_ROOT)
    target.mkdir(parents=True, exist_ok=True)
    (target / "config.yml").write_text("\n".join(lines) + "\n")

    agent_dir = target / "agents"
    agent_dir.mkdir(exist_ok=True)
    manifest = {"format_version": 1, "profile": name, "source": source_name,
                "agents": sorted(roles), "files": ["config.yml"]}
    for role, config in roles.items():
        model = profile["models"][role]
        tools = {
            "worker": ["read", "grep", "find", "edit", "write", "bash"],
            "worker-complex": ["read", "grep", "find", "edit", "write", "bash"],
            "validator": ["read", "grep", "find", "bash", "eval"],
            "debugger": ["read", "grep", "find", "bash"],
            "explorer": ["read", "grep", "find", "bash"],
            "planner": ["read", "grep", "find"],
            "design-partner": ["read", "grep", "find"],
            "reviewer": ["read", "grep", "find"],
            "ux-critic": ["read", "grep", "find"],
        }[role]
        front = ["---", f"name: {json.dumps(role)}", f"description: {json.dumps(config['description'])}",
                 f"model: {json.dumps('@' + role)}", f"thinking-level: {model['variant']}",
                 f"tools: {json.dumps(tools)}", "---", ""]
        (agent_dir / f"{role}.md").write_text("\n".join(front))
        manifest["files"].append(f"agents/{role}.md")
    manifest["control_plane"] = {"build": {"installed": False,
        "model": model_selector(cp["builtins"]["build"]["model"], providers, cp["builtins"]["build"]["effort"]),
        "note": "OMP has no native build role equivalent; this is intent only."}}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="hybrid")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    generate(args.output or DEFAULT_ROOT / args.profile, args.profile)
