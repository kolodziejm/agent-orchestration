#!/usr/bin/env python3
"""Generate DeepSeek Harness agent definitions from the routing policy.

DeepSeek Harness (dsh) 0.2 has no per-role agent file: a preset is a
`@deepseek-ai/dsh-agent-preset` declaration row whose `config.plugins` list is
the agent's whole composition, and a subagent child joins its parent's standing
composition instead of selecting one. A canonical role is therefore selected by
the *tool* the parent calls.

This adapter maps the nine canonical roles onto nine
`@deepseek-ai/dsh-tool-subagent` lanes inside one generated preset, each pinned
to its routed model and reasoning effort and to the capability ceiling the route
can express:

- `agentOptions` pins the child's provider, model, and reasoning effort.
- `toolFilter` removes `write`/`edit` from read-only roles and the platform
  shell from roles that must not run commands.

The generated patch is installed as the DeepSeek Harness *home* layer
(`$DSH_HOME/cordis.patch.yml`), which dsh applies after every bundle and after
the profile's own patch, so the adapter never edits a bundled preset or the
configuration the in-app editor owns.

Degradations this adapter cannot remove, recorded truthfully in the generated
control-plane note:

- A preset cannot select the session's own model route, so the primary model,
  the small model, and the built-in build/plan mappings stay user settings.
- A tool filter is a composition guard, not an authority boundary.
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

HARNESSES_DIR = Path(__file__).resolve().parents[1]
if str(HARNESSES_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESSES_DIR))

from common import assert_safe_output as shared_assert_safe_output
from common import assert_safe_rename, validate_capabilities, validate_profile

ROOT = Path(__file__).resolve().parents[2]
# Unresolved on purpose: resolving here would make the argparse default
# already-resolved, so a symlink swapped in at "build/dsh" would never hit the
# is_symlink() check in assert_safe_output when --output is omitted.
DEFAULT_OUTPUT = ROOT / "build" / "dsh"
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

PROFILE_NAME = "dsh"
PRESET_ID = "agent-orchestration"
PRESET_ORDER = 50
PATCH_FILE = "cordis.patch.yml"

# Comment markers, not HTML ones: the installed artifact is a YAML patch list.
MARKER_START = "# agent-orchestration:start"
MARKER_END = "# agent-orchestration:end"

AGENT_PRESET_PLUGIN = "@deepseek-ai/dsh-agent-preset"
SUBAGENT_PLUGIN = "@deepseek-ai/dsh-tool-subagent"
ROLE_LANE_PREFIX = "subagent_"
PLUGIN_TEMPLATE = ROOT / "harnesses" / "dsh" / "templates" / "preset-plugins.yml"
# The vendored template stores the bundled standard preset's plugin rows at the
# indentation the generated preset uses, so it splices in verbatim.
PLUGIN_INDENT = " " * 8
LANE_INDENT = " " * 12
LANE_SENTINEL = f"{LANE_INDENT}# agent-orchestration:lanes\n"
SHELLS = ("bash", "pwsh")

SAFE_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+-]*$")
YAML_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}


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
    harness = profile.get("harness", "opencode")
    if harness != "dsh":
        raise SystemExit(
            f"Profile {name!r} declares harness = {harness!r}; dsh will not generate it"
        )
    return profile


def require_subagent_mode(role: str, config: dict) -> None:
    if config.get("mode") != "subagent":
        raise SystemExit(
            f"DeepSeek Harness only generates subagent roles: "
            f"{role!r} has mode {config.get('mode')!r}"
        )


def lane_tool_name(role: str) -> str:
    return ROLE_LANE_PREFIX + role.replace("-", "_")


def lane_row_id(role: str) -> str:
    """Stable row id for one role lane; ids must stay unique and stable."""
    return f"lane-{role}"


def split_model(selector: str, label: str) -> tuple[str, str]:
    if selector.count("/") != 1:
        raise SystemExit(f"Malformed dsh model route for {label}: {selector!r}")
    provider, model = selector.split("/", 1)
    if not provider or not model:
        raise SystemExit(f"Malformed dsh model route for {label}: {selector!r}")
    return provider, model


def yaml_scalar(value: str) -> str:
    """Quote a scalar unless it is safe as a YAML plain scalar.

    ``@`` is a reserved indicator at the start of a plain scalar, so plugin
    specifiers and model routes are single-quoted exactly as the shipped dsh
    patches quote them.
    """
    if SAFE_PLAIN.fullmatch(value) and value.lower() not in YAML_RESERVED:
        return value
    return "'" + value.replace("'", "''") + "'"


def lane_rows(roles: dict, models: dict, shell: str) -> list[str]:
    """Render one subagent lane row per canonical role."""
    blocks = []
    for role, config in roles.items():
        model_config = models[role]
        provider, model = split_model(model_config["model"], f"role {role}")
        deny: list[str] = []
        if config["edit"] == "deny":
            deny.extend(["write", "edit"])
        if config["bash"] == "deny":
            deny.append(shell)

        pad = LANE_INDENT
        block = [
            f"{pad}- id: {yaml_scalar(lane_row_id(role))}",
            f"{pad}  name: {yaml_scalar(SUBAGENT_PLUGIN)}",
            f"{pad}  config:",
            f"{pad}    provider: spawn",
            f"{pad}    toolName: {yaml_scalar(lane_tool_name(role))}",
            f"{pad}    backgroundMode: continuable",
            f"{pad}    agentOptions:",
            f"{pad}      provider: {yaml_scalar(provider)}",
            f"{pad}      model: {yaml_scalar(model)}",
            f"{pad}      reasoningEffort: {yaml_scalar(model_config['variant'])}",
        ]
        if deny:
            block.append(f"{pad}    toolFilter:")
            block.append(f"{pad}      deny:")
            block.extend(f"{pad}        - {yaml_scalar(name)}" for name in deny)
        blocks.append("\n".join(block))
    return blocks


def load_plugin_template() -> str:
    """Return the vendored bundled-standard plugin rows, indentation included."""
    if not PLUGIN_TEMPLATE.is_file():
        raise SystemExit(f"Missing preset plugin template: {PLUGIN_TEMPLATE}")
    text = PLUGIN_TEMPLATE.read_text()
    if not text.endswith("\n"):
        raise SystemExit(
            f"Preset plugin template must end with a newline: {PLUGIN_TEMPLATE}"
        )
    for number, line in enumerate(text.split("\n")[:-1], start=1):
        if line.strip() and not line.startswith(PLUGIN_INDENT):
            raise SystemExit(
                f"Preset plugin template line {number} is not indented at "
                f"{len(PLUGIN_INDENT)} spaces: {line!r}"
            )
    if text.count(LANE_SENTINEL) != 1:
        raise SystemExit(
            f"Preset plugin template must carry exactly one lane sentinel: {PLUGIN_TEMPLATE}"
        )
    return text


def preset_patch_text(profile: dict, roles: dict, shell: str) -> str:
    """Render the managed home-layer patch list that declares the preset."""
    description = (
        "Coding agent with the nine canonical roles installed as separate subagent "
        "lanes, each pinned to its routed model and reasoning effort."
    )
    header = [
        MARKER_START,
        "- insert:",
        f"    - id: preset-{PRESET_ID}",
        f"      name: {yaml_scalar(AGENT_PRESET_PLUGIN)}",
        "      config:",
        f"        id: {yaml_scalar(PRESET_ID)}",
        f"        name: {yaml_scalar('Orchestrated (agent-orchestration)')}",
        f"        description: {yaml_scalar(description)}",
        f"        order: {PRESET_ORDER}",
        "        plugins:",
    ]
    template = load_plugin_template()
    lanes = "\n".join(lane_rows(roles, profile["models"], shell))
    plugins = template.replace(LANE_SENTINEL, lanes + "\n")
    return "\n".join(header) + "\n" + plugins.rstrip("\n") + "\n" + MARKER_END + "\n"


def generate_control_plane(profile: dict) -> str:
    control_plane = profile["control_plane"]
    primary = control_plane["primary"]
    build = control_plane["builtins"]["build"]
    plan = control_plane["builtins"]["plan"]
    vision = (
        "native vision"
        if profile.get("capabilities", {}).get("native_vision")
        else "text-only route"
    )
    return "\n".join(
        [
            "# DeepSeek Harness control-plane intent",
            "",
            "DeepSeek Harness cannot install the primary control plane from an agent",
            "preset. The primary model, the small model, and the built-in build/plan",
            "mappings are host-plane model settings. This file records the selected",
            "profile intent; it is not installed runtime configuration.",
            "",
            f"- primary: {primary['model']} ({primary['effort']})",
            f"- small_model: {control_plane['small_model']}",
            f"- build: {build['model']} ({build['effort']})",
            f"- plan: {plan['model']} ({plan['effort']})",
            f"- vision: {vision}",
            "",
            "## Lane installs",
            "",
            "Each canonical role lane installs, on the generated preset:",
            "",
            "- the role's routed provider, model, and reasoning effort;",
            "- the capability ceiling the route can express, as a tool filter.",
            "",
            "## Degradations",
            "",
            "- A tool filter is a visibility mask, not an authority boundary.",
            "",
        ]
    )


def validate_inputs(profile_name: str, shell: str) -> None:
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]
    profile = load_profile(profile_name)
    validate_profile(
        profile,
        ROOT / "profiles" / f"{profile_name}.toml",
        set(roles),
        "dsh",
        require_role_variants=True,
    )
    for role, config in roles.items():
        validate_capabilities(role, config, "dsh")
        require_subagent_mode(role, config)
        split_model(profile["models"][role]["model"], f"role {role}")
    load_plugin_template()
    if shell not in SHELLS:
        raise SystemExit(f"Unsupported shell tool: {shell!r}")


def generate_into(output: Path, profile_name: str = PROFILE_NAME, shell: str = "bash") -> None:
    validate_inputs(profile_name, shell)
    routing = load_toml(ROOT / "policy" / "routing.toml")
    roles = routing["roles"]
    profile = load_profile(profile_name)

    (output / "_shared").mkdir(parents=True, exist_ok=True)
    (output / "patch").mkdir(parents=True, exist_ok=True)

    (output / "patch" / PATCH_FILE).write_text(preset_patch_text(profile, roles, shell))
    (output / "_shared" / "control-plane.md").write_text(generate_control_plane(profile))

    (output / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "roles": sorted(roles),
                "profiles": [profile["name"]],
                "presets": [PRESET_ID],
                "control_plane": False,
            },
            indent=2,
        )
        + "\n"
    )


def assert_safe_output(output: Path) -> Path:
    return shared_assert_safe_output(output, DEFAULT_OUTPUT, TEMP_ROOT)


def generate(output: Path, profile_name: str = PROFILE_NAME, shell: str = "bash") -> None:
    output = assert_safe_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.generate-", dir=output.parent))
    staged = staging_root / "result"
    old = output.parent / f".{output.name}.old-{uuid.uuid4().hex}"
    allowed_root = ROOT if output == DEFAULT_OUTPUT.resolve() else TEMP_ROOT
    try:
        generate_into(staged, profile_name, shell)
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
            if old.is_dir():
                shutil.rmtree(old)
            else:
                old.unlink()
    finally:
        if staging_root.exists():
            assert_safe_rename(staging_root, allowed_root)
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile", default=PROFILE_NAME)
    parser.add_argument(
        "--shell",
        choices=list(SHELLS),
        default="pwsh" if sys.platform == "win32" else "bash",
        help="platform shell tool, which decides which shell a bash = deny role loses",
    )
    args = parser.parse_args()
    generate(args.output, args.profile, args.shell)
