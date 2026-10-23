"""Drift contracts for the route skill's generated presets."""

from __future__ import annotations

import importlib.util
import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "harnesses" / "route_presets.py"


def load_module():
    spec = importlib.util.spec_from_file_location("route_presets_for_tests", MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


class RoutePresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.roles = set(load_toml(ROOT / "policy" / "routing.toml")["roles"])
        cls.profiles = {
            path: load_toml(path)
            for path in sorted((ROOT / "profiles").glob("*.toml"))
            if "route" in load_toml(path)
        }

    def test_committed_presets_match_the_profiles(self):
        """This test will fail when presets.json differs from what scripts/generate builds from the [route] profiles."""
        committed = (ROOT / "skills" / "route" / "presets.json").read_text(encoding="utf-8")
        self.assertEqual(
            committed,
            self.module.render_presets(),
            "skills/route/presets.json is stale; run scripts/generate",
        )
        self.assertEqual(
            sorted(json.loads(committed)),
            sorted(profile["name"] for profile in self.profiles.values()),
        )

    def test_route_profiles_cover_every_role_or_list_it_as_native(self):
        """This test will fail when a [route] profile lacks a routing role, or lists a native role that does not exist."""
        self.assertTrue(self.profiles)
        presets = json.loads((ROOT / "skills" / "route" / "presets.json").read_text(encoding="utf-8"))
        for path, profile in self.profiles.items():
            with self.subTest(profile=path.name):
                native = set(profile["route"].get("native", []))
                self.assertLessEqual(native, self.roles, "route.native names a role missing from routing.toml")
                self.assertGreaterEqual(set(profile["models"]), self.roles - native)
                self.assertEqual(set(presets[profile["name"]]["roles"]), self.roles - native)


if __name__ == "__main__":
    unittest.main()
