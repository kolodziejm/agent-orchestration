#!/usr/bin/env python3
"""Render harness-agnostic policies into Claude Code subagent artifacts.

Claude Code permission degradation notes (documented here because Claude Code
has no per-subagent equivalent):

- `bash = "ask"` in policy/routing.toml has no per-subagent enforcement in
  Claude Code; permission prompts are configured at the session level, not
  per agent file. `Bash` is therefore granted to every rendered agent,
  including read-only roles, since they need it for investigation
  (e.g. running read-only inspection commands). Session-level Claude Code
  permission settings remain the operator's responsibility.
- Claude Code uses a flat subagent topology. The orchestrator performs the
  delegation described by `delegates` and passes returned evidence in the
  handoff; rendered subagent files do not expose nested `Agent(<target>)`
  tools.
- All `delegates` entries are omitted because Claude Code's rendered
  subagents cannot invoke nested agents. Native vision support means the
  active Claude profile also needs no separate `vision-*` delegation.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required (tomllib).")

import argparse
import json
import re
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
# already-resolved, so a symlink swapped in at "generated/claude-code" would
# never hit the is_symlink() check below when --output is omitted.
DEFAULT_OUTPUT = ROOT / "generated" / "claude-code"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

BASE_TOOLS = ["Read", "Grep", "Glob", "Bash"]
VALID_HARNESSES = {"opencode", "codex", "claude-code"}

MARKER_START = "<!-- agent-orchestration:start -->"
MARKER_END = "<!-- agent-orchestration:end -->"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_claude_profile() -> dict:
    candidates = []
    for path in sorted((ROOT / "profiles").glob("*.toml")):
        profile = load_toml(path)
        harness = profile.get("harness", "opencode")
        if harness not in VALID_HARNESSES:
            raise SystemExit(f"Invalid harness in {path}: {harness!r}")
        if harness == "claude-code":
            candidates.append(profile)
    if len(candidates) != 1:
        raise SystemExit(
            "Expected exactly one profile with harness = \"claude-code\" under "
            f"profiles/, found {len(candidates)}"
        )
    return candidates[0]


def tools_for(config: dict, native_vision: bool) -> str:
    tools = list(BASE_TOOLS)
    edit = config["edit"]
    if edit == "allow":
        tools.extend(["Edit", "Write"])
    elif edit != "deny":
        raise SystemExit(f"Claude Code does not support routing edit permission: {edit!r}")
    # Claude Code agent files are subagents without reliable nested-agent
    # delegation. The orchestrator owns all Agent calls and passes evidence
    # in the handoff to each rendered role.
    return ", ".join(tools)


def require_subagent_mode(role: str, config: dict) -> None:
    # Claude Code agent files are always subagents; routing.toml roles with a
    # different mode have no primary-agent equivalent to render here.
    mode = config.get("mode")
    if mode != "subagent":
        raise SystemExit(
            f"Claude Code adapter only renders subagent roles: {role!r} has mode {mode!r}"
        )


SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()*-]*$")


def scalar_token(value: str, label: str) -> str:
    """Validate an unquoted-safe scalar (used for tools/model/effort)."""
    if not SAFE_TOKEN.fullmatch(value):
        raise SystemExit(f"Unsafe frontmatter {label} token: {value!r}")
    return value


def frontmatter(role: str, config: dict, model_config: dict, native_vision: bool) -> str:
    tools = ", ".join(
        scalar_token(token, "tools") for token in tools_for(config, native_vision).split(", ")
    )
    lines = [
        "---",
        f"name: {json.dumps(role)}",
        f"description: {json.dumps(config['description'])}",
        f"tools: {tools}",
        f"model: {scalar_token(model_config['model'], 'model')}",
        f"effort: {scalar_token(model_config['variant'], 'effort')}",
        "---",
        "",
    ]
    return "\n".join(lines)


def assert_safe_output(output: Path) -> Path:
    return shared_assert_safe_output(output, DEFAULT_OUTPUT, TEMP_ROOT)

def render_into(output: Path) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]

    profile = load_claude_profile()
    models = profile["models"]
    expected_roles = set(roles)
    if set(models) != expected_roles:
        missing = sorted(expected_roles - set(models))
        extra = sorted(set(models) - expected_roles)
        raise SystemExit(f"Profile {profile['name']} mismatch: missing={missing}, extra={extra}")
    native_vision = bool(profile.get("capabilities", {}).get("native_vision", False))

    for role, config in roles.items():
        validate_capabilities(role, config, "claude-code")

    (output / "agents").mkdir(parents=True)
    (output / "_shared").mkdir(parents=True)

    for role, config in roles.items():
        require_subagent_mode(role, config)
        contract_path = ROOT / "roles" / f"{role}.md"
        if not contract_path.is_file():
            raise SystemExit(f"Missing role contract: {contract_path}")
        rendered = frontmatter(role, config, models[role], native_vision) + contract_path.read_text()
        (output / "agents" / f"{role}.md").write_text(rendered)

    core = (ROOT / "policy" / "orchestration.md").read_text().rstrip()
    addendum = (ROOT / "profiles" / profile["addendum"]).read_text().rstrip()
    shared = "\n\n".join([core, addendum])
    (output / "_shared" / "orchestration-core.md").write_text(
        f"{MARKER_START}\n{shared}\n{MARKER_END}\n"
    )

    (output / "manifest.json").write_text(
        json.dumps(
            {"format_version": 1, "roles": sorted(roles), "profiles": [profile["name"]]},
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
