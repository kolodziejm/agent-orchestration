import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "adapters" / "validate.py"
ROUTING_SCHEMA = ROOT / "schema" / "policy.schema.json"
PROFILE_SCHEMA = ROOT / "schema" / "profile.schema.json"
FIXTURES = ROOT / "tests" / "fixtures" / "routing"


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

    def validate_fixture(self, name):
        path = FIXTURES / name
        return self.validator.validate_routing(
            self.validator.load_toml(path), source=path, schema=self.schema
        )

    def test_schema_rejects_wrong_field_types_before_graph_checks(self):
        with self.assertRaises(SystemExit) as raised:
            self.validate_fixture("wrong-field-types.toml")
        message = str(raised.exception)
        self.assertIn("Schema validation failed", message)
        self.assertIn("wrong-field-types.toml", message)
        self.assertIn("$.roles.validator.description", message)
        self.assertIn("$.roles.validator.delegates", message)

    def test_unknown_target_is_rejected_before_edge_policy(self):
        with self.assertRaises(SystemExit) as raised:
            self.validate_fixture("unknown-target.toml")
        message = str(raised.exception)
        self.assertIn("unknown delegation target", message)
        self.assertIn("planner", message)
        self.assertIn("missing-role", message)

    def test_cycle_reports_a_closed_deterministic_path_before_edge_policy(self):
        messages = []
        for _ in range(2):
            with self.assertRaises(SystemExit) as raised:
                self.validate_fixture("cycle.toml")
            messages.append(str(raised.exception))
        self.assertEqual(messages[0], messages[1])
        self.assertIn("cycle detected: planner -> reviewer -> planner", messages[0])

    def test_canonical_leaf_delegation_gets_a_leaf_specific_failure(self):
        with self.assertRaises(SystemExit) as raised:
            self.validate_fixture("illegal-leaf-delegation.toml")
        message = str(raised.exception)
        self.assertIn("leaf role 'validator'", message)
        self.assertIn("delegates = []", message)

    def test_current_routing_passes_schema_and_graph_validation(self):
        path = ROOT / "policy" / "routing.toml"
        roles = self.validator.validate_routing(
            self.validator.load_toml(path), source=path, schema=self.schema
        )
        self.assertEqual(
            roles["planner"]["delegates"], ["explorer", "spec-writer"]
        )
        self.assertEqual(roles["reviewer"]["delegates"], ["explorer"])

    def test_virtual_vision_target_is_not_traversed_as_a_graph_node(self):
        self.validator.validate_delegation_graph(
            {
                "worker": {"delegates": ["vision-*"]},
                "worker-complex": {"delegates": ["vision-*"]},
            }
        )

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

    def test_schema_diagnostics_are_sorted_and_bounded(self):
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
        self.assertEqual(lines[0], "Schema validation failed for synthetic-routing.toml (61 error(s)):")
        self.assertEqual(len(lines), 10)
        self.assertIn("additional schema error(s) omitted", lines[-1])
        self.assertLessEqual(lines[1], lines[2])

    def test_noncanonical_wildcards_are_unknown_targets(self):
        roles = {
            "planner": {
                "delegates": ["explorer-*"],
            }
        }
        with self.assertRaisesRegex(SystemExit, "unknown delegation target"):
            self.validator.validate_delegation_graph(roles)


if __name__ == "__main__":
    unittest.main()
