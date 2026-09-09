import importlib.util
import json
import shutil
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


def parse_frontmatter_tools(content: str) -> list:
    """Parse the `tools:` frontmatter line into a list of tool tokens.

    No PyYAML dependency (so this always runs); only understands the
    single-line comma-separated form the renderer emits.
    """
    block = content.split("---", 2)[1]
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("tools:"):
            value = line[len("tools:") :].strip()
            return [token.strip() for token in value.split(",") if token.strip()]
    raise AssertionError("no tools: line found in frontmatter block")


def expected_tools(config: dict, native_vision: bool) -> list:
    tools = ["Read", "Grep", "Glob", "Bash"]
    if config["edit"] == "allow":
        tools.extend(["Edit", "Write"])
    for target in config.get("delegates", []):
        if target == "vision-*" and native_vision:
            continue
        tools.append(f"Agent({target})")
    return tools


def build_temp_repo(destination: Path) -> Path:
    """Copy the subset of the repo render.py resolves ROOT against, so a test
    can corrupt one profile without touching the real profiles/ directory."""
    for name in ("adapters", "policy", "profiles", "roles"):
        shutil.copytree(ROOT / name, destination / name)
    return destination


def set_toml_top_level_key(path: Path, key: str, value: str) -> None:
    """Overwrite (or insert) a simple top-level `key = "value"` line.

    Profile files only use scalar top-level keys before their first table
    header, so a line-level rewrite is sufficient without a TOML writer.
    """
    lines = [line for line in path.read_text().splitlines() if not line.strip().startswith(f"{key} =")]
    lines.insert(0, f"{key} = {json.dumps(value)}")
    path.write_text("\n".join(lines) + "\n")


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
        native_vision = self.profile.get("capabilities", {}).get("native_vision", False)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            for role, config in self.roles.items():
                agent_path = output / "agents" / f"{role}.md"
                self.assertTrue(agent_path.is_file(), role)
                content = agent_path.read_text()
                self.assertIn(f"name: {json.dumps(role)}", content)
                self.assertIn(f"description: {json.dumps(config['description'])}", content)
                model_config = self.profile["models"][role]
                self.assertIn(f"model: {model_config['model']}", content)
                self.assertIn(f"effort: {model_config['variant']}", content)

                # Parsed from frontmatter only, so a tool name mentioned in the
                # role's prose body cannot produce a false positive/negative.
                self.assertEqual(
                    parse_frontmatter_tools(content),
                    expected_tools(config, native_vision),
                    role,
                )

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

    def test_shared_orchestration_core_includes_profile_addendum_after_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            core = (output / "_shared" / "orchestration-core.md").read_text()
            policy = (ROOT / "policy" / "orchestration.md").read_text().strip()
            addendum = (ROOT / "profiles" / self.profile["addendum"]).read_text().strip()
            self.assertIn(policy, core)
            self.assertIn(addendum, core)
            self.assertLess(core.index(policy), core.index(addendum))

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

    def test_renderer_refuses_symlinked_output_path_and_leaves_target_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real-target"
            target.mkdir()
            marker = target / "marker.txt"
            marker.write_text("original")
            symlinked_output = root / "output-symlink"
            symlinked_output.symlink_to(target)

            result = subprocess.run(
                [sys.executable, str(RENDER), "--output", str(symlinked_output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing symlinked output path", result.stderr)
            self.assertTrue(symlinked_output.is_symlink())
            self.assertEqual(marker.read_text(), "original")

    def test_renderer_refuses_symlinked_default_output_and_leaves_target_untouched(self):
        """Regression: the argparse --output default must stay unresolved.

        A pre-resolved default silently follows a symlink at import time, so
        the later `output.is_symlink()` guard in assert_safe_output never
        sees the symlink when --output is omitted (only the explicit-path
        invocation was covered before).
        """
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            target = Path(directory) / "real-target"
            target.mkdir()
            marker = target / "marker.txt"
            marker.write_text("original")
            (repo / "generated").mkdir(parents=True, exist_ok=True)
            (repo / "generated" / "claude-code").symlink_to(target)

            result = subprocess.run(
                [sys.executable, str(repo / "adapters" / "claude-code" / "render.py")],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing symlinked output path", result.stderr)
            self.assertTrue((repo / "generated" / "claude-code").is_symlink())
            self.assertEqual(marker.read_text(), "original")

    def test_renderer_rejects_a_typoed_harness_value_instead_of_silently_ignoring_the_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            broken_profile = repo / "profiles" / "openai.toml"
            set_toml_top_level_key(broken_profile, "harness", "claude-cod")

            result = subprocess.run(
                [sys.executable, str(repo / "adapters" / "claude-code" / "render.py"), "--output", str(Path(directory) / "out")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(broken_profile), result.stderr)
            self.assertIn("claude-cod", result.stderr)

    def test_renderer_fails_instead_of_rendering_with_zero_matching_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            # No profile declares harness = "claude-code" once the only one that did is repointed elsewhere.
            set_toml_top_level_key(repo / "profiles" / "claude.toml", "harness", "codex")

            result = subprocess.run(
                [sys.executable, str(repo / "adapters" / "claude-code" / "render.py"), "--output", str(Path(directory) / "out")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("found 0", result.stderr)

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

    def test_tools_for_rejects_an_edit_permission_value_it_cannot_route(self):
        render_module = load_render_module()
        with self.assertRaisesRegex(SystemExit, "edit permission"):
            render_module.tools_for({"edit": "ask", "delegates": []}, native_vision=False)

    def test_require_subagent_mode_rejects_a_non_subagent_role(self):
        render_module = load_render_module()
        with self.assertRaisesRegex(SystemExit, "mode"):
            render_module.require_subagent_mode("worker", {"mode": "primary"})

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
