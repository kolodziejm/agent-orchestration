"""Drift contracts for the route skill's generated presets."""

from __future__ import annotations

import importlib.util
import json
import tempfile
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
        committed = (ROOT / "skills" / "save-subscription" / "presets.json").read_text(encoding="utf-8")
        self.assertEqual(
            committed,
            self.module.render_presets(),
            "skills/save-subscription/presets.json is stale; run scripts/generate",
        )
        self.assertEqual(
            sorted(json.loads(committed)),
            sorted(profile["name"] for profile in self.profiles.values()),
        )

    def test_route_profiles_cover_every_role_or_list_it_as_native(self):
        """This test will fail when a [route] profile lacks a routing role, or lists a native role that does not exist."""
        self.assertTrue(self.profiles)
        presets = json.loads((ROOT / "skills" / "save-subscription" / "presets.json").read_text(encoding="utf-8"))
        for path, profile in self.profiles.items():
            with self.subTest(profile=path.name):
                native = set(profile["route"].get("native", []))
                self.assertLessEqual(native, self.roles, "route.native names a role missing from routing.toml")
                self.assertGreaterEqual(set(profile["models"]), self.roles - native)
                self.assertEqual(set(presets[profile["name"]]["roles"]), self.roles - native)

    def test_read_only_follows_the_edit_permission_of_the_routing_policy(self):
        """This test will fail when a preset role's readOnly flag differs from edit = "deny" in routing.toml."""
        policy = load_toml(ROOT / "policy" / "routing.toml")["roles"]
        denied = {role for role, config in policy.items() if config["edit"] == "deny"}
        self.assertTrue(denied)
        self.assertLess(denied, set(policy))
        presets = self.module.build_presets()
        self.assertTrue(presets)
        for name, preset in presets.items():
            for role, entry in preset["roles"].items():
                with self.subTest(preset=name, role=role):
                    self.assertIs(entry["readOnly"], role in denied)

    def test_read_only_is_derived_from_a_temporary_policy(self):
        """This test will fail when the generator hand-writes readOnly instead of reading edit from the policy."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "policy").mkdir()
            (root / "profiles").mkdir()
            (root / "policy" / "routing.toml").write_text(
                '[roles.a]\nedit = "allow"\n[roles.b]\nedit = "deny"\n', encoding="utf-8"
            )
            (root / "profiles" / "p.toml").write_text(
                'name = "p"\n[route]\nprovider_instance = "x"\n'
                '[models.a]\nmodel = "m/a"\n[models.b]\nmodel = "m/b"\nvariant = "high"\n',
                encoding="utf-8",
            )
            roles = self.module.build_presets(root)["p"]["roles"]
        self.assertEqual(roles["a"], {"model": "m/a", "readOnly": False})
        self.assertEqual(roles["b"], {"model": "m/b", "readOnly": True, "options": {"variant": "high"}})


if __name__ == "__main__":
    unittest.main()
