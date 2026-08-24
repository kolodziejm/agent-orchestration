import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
ROUTING = ROOT / "policy" / "routing.toml"
PROFILES = ROOT / "profiles"
RENDER = ROOT / "adapters" / "claude-code" / "render.py"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_render_module():
    spec = importlib.util.spec_from_file_location("claude_code_render", RENDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load render module from {RENDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClaudeCodeRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routing = load_toml(ROUTING)
        cls.roles = cls.routing["roles"]
        cls.profile = load_toml(PROFILES / "claude.toml")

    def test_profile_declares_harness_and_native_vision(self):
        self.assertEqual(self.profile.get("harness"), "claude-code")
        self.assertTrue(self.profile.get("capabilities", {}).get("native_vision"))

    def test_profile_roles_match_routing_roles(self):
        self.assertEqual(set(self.profile["models"]), set(self.roles))

    def test_renderer_produces_every_role_agent_with_expected_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            for role in self.roles:
                agent_path = output / "agents" / f"{role}.md"
                self.assertTrue(agent_path.is_file(), role)
                content = agent_path.read_text()
                self.assertIn(f"name: {json.dumps(role)}", content)
                self.assertIn(f"description: {json.dumps(self.roles[role]['description'])}", content)
                self.assertIn("tools:", content)
                self.assertIn("Read, Grep, Glob, Bash", content)
                model_config = self.profile["models"][role]
                self.assertIn(f"model: {model_config['model']}", content)
                self.assertIn(f"effort: {model_config['variant']}", content)

            worker = (output / "agents" / "worker.md").read_text()
            worker_frontmatter = worker.split("---", 2)[1]
            self.assertIn("Edit, Write", worker)
            # Native vision profile: no vision-* delegate entry in the tools frontmatter.
            self.assertNotIn("Agent(vision", worker_frontmatter)

            complex_worker = (output / "agents" / "worker-complex.md").read_text()
            self.assertNotIn("Agent(vision", complex_worker)

            validator = (output / "agents" / "validator.md").read_text()
            self.assertNotIn("Edit", validator)
            self.assertIn("Bash", validator)

            debugger = (output / "agents" / "debugger.md").read_text()
            self.assertIn("Bash", debugger)

            planner = (output / "agents" / "planner.md").read_text()
            self.assertIn("Agent(explorer)", planner)
            self.assertIn("Agent(spec-writer)", planner)

            reviewer = (output / "agents" / "reviewer.md").read_text()
            self.assertIn("Agent(explorer)", reviewer)
            self.assertNotIn("Agent(spec-writer)", reviewer)

            explorer = (output / "agents" / "explorer.md").read_text()
            self.assertNotIn("Agent(", explorer)
            self.assertNotIn("Edit", explorer)

    def test_delegates_map_to_agent_entries_per_routing(self):
        native_vision = self.profile.get("capabilities", {}).get("native_vision", False)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            for role, config in self.roles.items():
                content = (output / "agents" / f"{role}.md").read_text()
                for target in config.get("delegates", []):
                    if target == "vision-*" and native_vision:
                        self.assertNotIn(f"Agent({target})", content)
                        continue
                    self.assertIn(f"Agent({target})", content, f"{role} -> {target}")

    def test_role_contract_bodies_remain_provider_and_model_free(self):
        forbidden = ("sonnet", "opus", "haiku")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            for role in self.roles:
                content = (output / "agents" / f"{role}.md").read_text()
                body = content.split("---", 2)[2]
                for token in forbidden:
                    self.assertNotIn(token, body, f"{token} leaked into {role} body")

    def test_shared_orchestration_core_is_marker_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            core = (output / "_shared" / "orchestration-core.md").read_text()
            self.assertTrue(core.startswith("<!-- agent-orchestration:start -->"))
            self.assertTrue(core.rstrip("\n").endswith("<!-- agent-orchestration:end -->"))
            self.assertIn((ROOT / "policy" / "orchestration.md").read_text().strip(), core)

    def test_manifest_lists_all_roles_and_the_claude_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["format_version"], 1)
            self.assertEqual(set(manifest["roles"]), set(self.roles))
            self.assertEqual(manifest["profiles"], ["claude"])

    def test_renderer_rejects_repository_root_as_output(self):
        result = subprocess.run(
            [sys.executable, str(RENDER), "--output", str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing unsafe output path", result.stderr)
        self.assertTrue((ROOT / "README.md").is_file())

    def test_opencode_renderer_ignores_claude_code_profile(self):
        opencode_render = ROOT / "adapters" / "opencode" / "render.py"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(opencode_render), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertNotIn("claude", manifest["profiles"])
            self.assertFalse((output / "profiles" / "claude").exists())

    def test_frontmatter_scalar_values_are_json_quoted_and_survive_special_characters(self):
        render_module = load_render_module()
        tricky_description = 'Reviews: "high" risk changes # notes\nsecond line'
        config = {"description": tricky_description, "edit": "deny", "delegates": []}
        model_config = {"model": "sonnet", "variant": "high"}

        rendered = render_module.frontmatter("tricky-role", config, model_config, native_vision=False)

        name_line = f'name: {json.dumps("tricky-role")}'
        description_line = f"description: {json.dumps(tricky_description)}"
        self.assertIn(name_line, rendered)
        self.assertIn(description_line, rendered)

        # The value after "description: " must be a valid JSON (and therefore
        # valid double-quoted YAML flow) string that decodes back exactly.
        raw_value = description_line[len("description: ") :]
        self.assertEqual(json.loads(raw_value), tricky_description)

    @unittest.skipUnless(yaml is not None, "PyYAML is not installed; skipping full YAML round-trip")
    def test_frontmatter_round_trips_through_pyyaml(self):
        render_module = load_render_module()
        tricky_description = 'Reviews: "high" risk changes # notes\nsecond line'
        config = {"description": tricky_description, "edit": "deny", "delegates": []}
        model_config = {"model": "sonnet", "variant": "high"}

        rendered = render_module.frontmatter("tricky-role", config, model_config, native_vision=False)
        block = rendered.split("---", 2)[1]
        parsed = yaml.safe_load(block)
        self.assertEqual(parsed["name"], "tricky-role")
        self.assertEqual(parsed["description"], tricky_description)

    def test_renderer_produces_pyyaml_parseable_frontmatter_for_every_role(self):
        if yaml is None:
            self.skipTest("PyYAML is not installed; skipping full YAML round-trip")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            for role in self.roles:
                content = (output / "agents" / f"{role}.md").read_text()
                block = content.split("---", 2)[1]
                parsed = yaml.safe_load(block)
                self.assertEqual(parsed["name"], role)
                self.assertEqual(parsed["description"], self.roles[role]["description"])


if __name__ == "__main__":
    unittest.main()
