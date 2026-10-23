#!/usr/bin/env python3
"""Build skills/route/presets.json from the repository profiles that carry a [route] table."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESETS_FILE = ROOT / "skills" / "route" / "presets.json"


def build_presets(root: Path = ROOT) -> dict:
    """Return ``{profile name: {providerInstanceId, roles}}`` for every profile with a [route] table.

    A preset lists every role of policy/routing.toml except the roles the profile
    names in ``route.native``, with the profile's model and variant (or effort).
    """
    with (root / "policy" / "routing.toml").open("rb") as handle:
        roles = list(tomllib.load(handle)["roles"])
    presets: dict[str, dict] = {}
    for path in sorted((root / "profiles").glob("*.toml")):
        with path.open("rb") as handle:
            profile = tomllib.load(handle)
        route = profile.get("route")
        if route is None:
            continue
        native = route.get("native", [])
        unknown = sorted(set(native) - set(roles))
        if unknown:
            raise SystemExit(f"Profile {path.name} route.native names unknown roles: {unknown}")
        preset_roles: dict[str, dict] = {}
        for role in roles:
            if role in native:
                continue
            config = profile.get("models", {}).get(role)
            if config is None:
                raise SystemExit(
                    f"Profile {path.name} has a [route] table but no [models.{role}] "
                    "and does not list it in route.native"
                )
            entry: dict = {"model": config["model"]}
            option = config.get("variant", config.get("effort"))
            if option is not None:
                entry["options"] = {"variant": option}
            preset_roles[role] = entry
        presets[profile["name"]] = {
            "providerInstanceId": route["provider_instance"],
            "roles": preset_roles,
        }
    return presets


def render_presets(root: Path = ROOT) -> str:
    return json.dumps(build_presets(root), indent=2) + "\n"


def main() -> int:
    PRESETS_FILE.write_text(render_presets(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
