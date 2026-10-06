import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "harnesses" / "validate.py"
ROUTING_SCHEMA = ROOT / "schema" / "policy.schema.json"
PROFILE_SCHEMA = ROOT / "schema" / "profile.schema.json"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("routing_validator", VALIDATE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load validator module from {VALIDATE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RoutingValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()
        cls.schema = cls.validator.load_json_schema(ROUTING_SCHEMA)
        cls.profile_schema = cls.validator.load_json_schema(PROFILE_SCHEMA)

    def test_current_routing_carries_capability_data_only(self):
        """This test will fail when routing regains graph data or loses a role capability."""
        path = ROOT / "policy" / "routing.toml"
        roles = self.validator.validate_routing(
            self.validator.load_toml(path), source=path, schema=self.schema
        )
        self.assertEqual(
            sorted(roles),
            [
                "debugger",
                "design-partner",
                "explorer",
                "planner",
                "reviewer",
                "ux-critic",
                "validator",
                "worker",
                "worker-complex",
            ],
        )
        for role, config in roles.items():
            self.assertEqual(set(config), {"description", "mode", "edit", "bash"}, role)
            self.assertEqual(config["mode"], "subagent", role)
        self.assertEqual(
            [role for role, config in roles.items() if config["edit"] == "allow"],
            ["worker", "worker-complex"],
        )
        self.assertEqual(roles["planner"]["edit"], "deny")
        self.assertEqual(roles["planner"]["bash"], "deny")

    def test_stray_delegates_key_is_rejected(self):
        """This test will fail when a delegation key can be reintroduced into routing."""
        document = {
            "version": 1,
            "roles": {
                "worker": {
                    "description": "Routine implementation worker",
                    "mode": "subagent",
                    "edit": "allow",
                    "bash": "allow",
                    "delegates": ["explorer"],
                }
            },
        }
        with self.assertRaises(SystemExit) as raised:
            self.validator.validate_routing(
                document, source=Path("synthetic-routing.toml"), schema=self.schema
            )
        message = str(raised.exception)
        self.assertIn("Schema validation failed", message)
        self.assertIn("$.roles.worker", message)
        self.assertIn("'delegates' was unexpected", message)

        with self.assertRaises(SystemExit) as raised:
            self.validator.validate_routing(
                document,
                source=Path("synthetic-routing.toml"),
                schema={"type": "object"},
            )
        self.assertIn("Invalid routing entry for role 'worker'", str(raised.exception))

    def test_profile_schema_rejects_wrong_model_types_before_semantic_checks(self):
        profile = {
            "version": 1,
            "name": "synthetic",
            "addendum": "synthetic.md",
            "models": {"planner": {"model": 7}},
            "control_plane": {
                "primary": {"model": "provider/model", "effort": "low"},
                "small_model": "provider/small",
                "builtins": {
                    "build": {"model": "provider/model", "effort": "low"},
                    "plan": {"model": "provider/model", "effort": "low"},
                },
            },
            "capabilities": {"supported_variants": ["low"]},
        }
        with self.assertRaises(SystemExit) as raised:
            self.validator.validate_document(
                profile, self.profile_schema, source=Path("synthetic-profile.toml")
            )
        message = str(raised.exception)
        self.assertIn("Schema validation failed", message)
        self.assertIn("$.models.planner.model", message)

    def test_schema_diagnostics_are_bounded_and_deterministic(self):
        document = {
            "version": "bad",
            "roles": {
                f"role-{index}": {
                    "description": 7,
                    "mode": 7,
                    "edit": 7,
                    "bash": 7,
                    "delegates": "not-an-array",
                }
                for index in range(12)
            },
        }
        with self.assertRaises(SystemExit) as raised:
            self.validator.validate_document(
                document, self.schema, source=Path("synthetic-routing.toml")
            )
        message = str(raised.exception)
        lines = message.splitlines()
        self.assertTrue(lines[0].startswith("Schema validation failed for synthetic-routing.toml ("))
        self.assertEqual(len(lines), 10)
        self.assertIn("additional schema error(s) omitted", lines[-1])

        with self.assertRaises(SystemExit) as repeated:
            self.validator.validate_document(
                document, self.schema, source=Path("synthetic-routing.toml")
            )
        self.assertEqual(str(repeated.exception), message)


if __name__ == "__main__":
    unittest.main()
