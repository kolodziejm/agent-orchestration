#!/usr/bin/env python3.11
"""Render harness-agnostic policies into Claude Code subagent artifacts.

Claude Code permission degradation notes (documented here because Claude Code
has no per-subagent equivalent):

- `bash = "ask"` in policy/routing.toml has no per-subagent enforcement in
  Claude Code; permission prompts are configured at the session level, not
  per agent file. `Bash` is therefore granted to every rendered agent,
  including read-only roles, since they need it for investigation
  (e.g. running read-only inspection commands). Session-level Claude Code
  permission settings remain the operator's responsibility.
- Delegation (`delegates` in routing.toml) is expressed as `Agent(<target>)`
  entries in the `tools` frontmatter field, since Claude Code enforces
  per-target subagent delegation that way rather than a permission map.
- `vision-*` delegates are omitted when the active profile declares native
  vision support (`[capabilities] native_vision = true`), since all Claude
  models are natively multimodal and profile-provided vision delegation is
  unnecessary.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (ROOT / "generated" / "claude-code").resolve()
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

BASE_TOOLS = ["Read", "Grep", "Glob", "Bash"]

MARKER_START = "<!-- agent-orchestration:start -->"
MARKER_END = "<!-- agent-orchestration:end -->"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_claude_profile() -> dict:
    candidates = []
    for path in sorted((ROOT / "profiles").glob("*.toml")):
        profile = load_toml(path)
        if profile.get("harness") == "claude-code":
            candidates.append(profile)
    if len(candidates) != 1:
        raise SystemExit(
            "Expected exactly one profile with harness = \"claude-code\" under "
            f"profiles/, found {len(candidates)}"
        )
    return candidates[0]


def tools_for(config: dict, native_vision: bool) -> str:
    tools = list(BASE_TOOLS)
    if config["edit"] == "allow":
        tools.extend(["Edit", "Write"])
    for target in config.get("delegates", []):
        if target == "vision-*" and native_vision:
            continue
        tools.append(f"Agent({target})")
    return ", ".join(tools)


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

    profile = load_claude_profile()
    models = profile["models"]
    expected_roles = set(roles)
    if set(models) != expected_roles:
        missing = sorted(expected_roles - set(models))
        extra = sorted(set(models) - expected_roles)
        raise SystemExit(f"Profile {profile['name']} mismatch: missing={missing}, extra={extra}")
    native_vision = bool(profile.get("capabilities", {}).get("native_vision", False))

    (output / "agents").mkdir(parents=True)
    (output / "_shared").mkdir(parents=True)

    for role, config in roles.items():
        contract_path = ROOT / "roles" / f"{role}.md"
        if not contract_path.is_file():
            raise SystemExit(f"Missing role contract: {contract_path}")
        rendered = frontmatter(role, config, models[role], native_vision) + contract_path.read_text()
        (output / "agents" / f"{role}.md").write_text(rendered)

    core = (ROOT / "policy" / "orchestration.md").read_text()
    (output / "_shared" / "orchestration-core.md").write_text(
        f"{MARKER_START}\n{core}\n{MARKER_END}\n"
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
