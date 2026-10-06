"""Behavioral contracts for the generated DeepSeek Harness patch and artifacts."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
GENERATE = ROOT / "harnesses" / "dsh" / "generate.py"
ROUTING = ROOT / "policy" / "routing.toml"
PROFILE = ROOT / "profiles" / "dsh.toml"
TEMPLATE = ROOT / "harnesses" / "dsh" / "templates" / "preset-plugins.yml"
SHELL = "bash"


class _LoaderExpression(str):
    """The Cordis `!!js` loader expression, retained as text for assertions."""


class _DshLoader(yaml.SafeLoader):
    """Isolated loader: other test modules also claim the Cordis `!!js` tag."""


_DshLoader.add_constructor(
    "tag:yaml.org,2002:js",
    lambda loader, node: _LoaderExpression(loader.construct_scalar(node)),
)


def load_yaml(text: str):
    return yaml.load(text, Loader=_DshLoader)


def build_temp_repo(destination: Path) -> Path:
    """Copy the subset of the repo the generator resolves ROOT against."""
    for name in ("harnesses", "policy", "profiles"):
        shutil.copytree(ROOT / name, destination / name)
    return destination


def load_generator():
    spec = importlib.util.spec_from_file_location("dsh_generate", GENERATE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load generator module from {GENERATE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_snapshot(output: Path, shell: str = SHELL, cwd: Path = ROOT) -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATE), "--output", str(output), "--profile", "dsh", "--shell", shell],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def load_patch(path: Path) -> dict:
    document = load_yaml(path.read_text())
    if not isinstance(document, list) or len(document) != 1:
        raise AssertionError(f"Expected exactly one top-level patch entry: {document!r}")
    return document[0]


def preset_config(patch_path: Path) -> dict:
    entry = load_patch(patch_path)
    rows = entry["insert"]
    if len(rows) != 1:
        raise AssertionError(f"Expected exactly one inserted row: {rows!r}")
    return rows[0]["config"]


def find_row(rows: list, row_id: str) -> dict:
    for row in rows:
        if row["id"] == row_id:
            return row
        nested = row.get("config")
        if isinstance(nested, list):
            hit = find_row(nested, row_id)
            if hit is not None:
                return hit
    return None


def lanes(config: dict) -> dict:
    """Return the canonical role lanes keyed by tool name."""
    result = {}
    for plugin in config["plugins"]:
        nested = plugin.get("config")
        candidates = nested if isinstance(nested, list) else [plugin]
        for row in candidates:
            if row["id"].startswith("lane-"):
                result[row["config"]["toolName"]] = row["config"]
    return result


class DshGenerateContractTests(unittest.TestCase):
    def test_snapshot_contains_the_lane_patch_and_control_plane_note(self):
        """REGRESSION CONTRACT: the dsh adapter emits lane definitions only; TEST LAYER: generator integration test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)

            self.assertTrue((output / "patch" / "cordis.patch.yml").is_file())
            self.assertTrue((output / "_shared" / "control-plane.md").is_file())
            self.assertFalse((output / "agents").exists())
            self.assertFalse((output / "_shared" / "orchestration-core.md").exists())
            self.assertFalse((output / "_shared" / "adapter.md").exists())
            self.assertFalse((output / "AGENTS.md").exists())
            self.assertFalse((output / "workflows").exists())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["format_version"], 1)
            self.assertEqual(manifest["roles"], sorted(roles))
            self.assertEqual(manifest["profiles"], ["dsh"])
            self.assertEqual(manifest["presets"], ["agent-orchestration"])
            self.assertNotIn("workflows", manifest)
            self.assertFalse(manifest["control_plane"])

    def test_patch_declares_the_preset_with_one_lane_per_role(self):
        """REGRESSION CONTRACT: the home patch declares the preset and all nine lanes; TEST LAYER: generated-artifact test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)
            config = preset_config(output / "patch" / "cordis.patch.yml")

            self.assertEqual(config["id"], "agent-orchestration")
            self.assertEqual(config["order"], 50)
            lanes_by_tool = lanes(config)
            self.assertEqual(
                set(lanes_by_tool),
                {f"subagent_{role.replace('-', '_')}" for role in roles},
            )
            for row in config["plugins"]:
                self.assertIsNotNone(row.get("id"))
            # The vendored bundled-standard plugin rows survive verbatim.
            self.assertIsNotNone(find_row(config["plugins"], "delegation"))
            self.assertIsNotNone(find_row(config["plugins"], "agent-instructions"))
            self.assertIsNotNone(find_row(config["plugins"], "delegation"))

    def test_lanes_install_model_and_effort_without_persona_or_depth(self):
        """REGRESSION CONTRACT: each lane pins model and effort, and carries no prompt or depth; TEST LAYER: generated-artifact test."""
        with PROFILE.open("rb") as handle:
            profile = tomllib.load(handle)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)
            lanes_by_tool = lanes(preset_config(output / "patch" / "cordis.patch.yml"))

            for role, model_config in profile["models"].items():
                lane = lanes_by_tool[f"subagent_{role.replace('-', '_')}"]
                provider, model = model_config["model"].split("/", 1)
                self.assertEqual(lane["provider"], "spawn")
                self.assertEqual(lane["backgroundMode"], "continuable")
                self.assertEqual(lane["agentOptions"]["provider"], provider)
                self.assertEqual(lane["agentOptions"]["model"], model)
                self.assertEqual(
                    lane["agentOptions"]["reasoningEffort"], model_config["variant"]
                )
                self.assertNotIn("persona", lane, role)
                self.assertNotIn("maxDepth", lane, role)

    def test_capability_filters_match_the_canonical_routing(self):
        """REGRESSION CONTRACT: edit and shell ceilings follow routing.toml and nothing else; TEST LAYER: generated-artifact test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)
            lanes_by_tool = lanes(preset_config(output / "patch" / "cordis.patch.yml"))

            for role, config in roles.items():
                lane = lanes_by_tool[f"subagent_{role.replace('-', '_')}"]
                deny = set(lane.get("toolFilter", {}).get("deny", []))
                if config["edit"] == "deny":
                    self.assertEqual({"write", "edit"} <= deny, True, role)
                else:
                    self.assertFalse({"write", "edit"} & deny, role)
                if config["bash"] == "deny":
                    self.assertIn(SHELL, deny, role)
                else:
                    self.assertNotIn(SHELL, deny, role)
                self.assertFalse(
                    {name for name in deny if name.startswith("subagent_")},
                    f"{role} carries a cross-lane deny",
                )

    def test_windows_generation_denies_the_platform_shell(self):
        """REGRESSION CONTRACT: a bash = deny role loses pwsh on win32 generation; TEST LAYER: generator unit test."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output, shell="pwsh")
            lanes_by_tool = lanes(preset_config(output / "patch" / "cordis.patch.yml"))

            self.assertIn("pwsh", lanes_by_tool["subagent_ux_critic"]["toolFilter"]["deny"])
            self.assertNotIn("bash", lanes_by_tool["subagent_ux_critic"]["toolFilter"]["deny"])

    def test_preset_keeps_the_vendored_workspace_instruction_budget(self):
        """REGRESSION CONTRACT: no instruction artifact is installed, so the vendored budget is untouched; TEST LAYER: generated-artifact invariant."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)
            config = preset_config(output / "patch" / "cordis.patch.yml")
            installed = find_row(config["plugins"], "agent-instructions")["config"]["maxBytes"]

            self.assertEqual(installed, 65536)
            self.assertFalse((output / "AGENTS.md").exists())

    def test_control_plane_note_records_intent_without_policy_bytes(self):
        """REGRESSION CONTRACT: the note records model/effort intent and nothing else; TEST LAYER: generated-artifact test."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)
            note = (output / "_shared" / "control-plane.md").read_text()
            self.assertIn("# DeepSeek Harness control-plane intent", note)
            self.assertIn("deepseek-official/deepseek-flash (max)", note)
            self.assertNotIn("delegation installs", note.lower())
            self.assertFalse((output / "agents").exists())
            self.assertFalse((output / "AGENTS.md").exists())

    def test_generation_is_deterministic(self):
        """REGRESSION CONTRACT: two generations are byte-identical; TEST LAYER: determinism test."""
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            generate_snapshot(first)
            generate_snapshot(second)
            first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
            second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual(
                    (first / relative).read_bytes(), (second / relative).read_bytes(), relative
                )

    def test_a_profile_naming_another_harness_is_rejected(self):
        """REGRESSION CONTRACT: dsh refuses a foreign profile before writing output; TEST LAYER: generator failure test."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            profile = repo / "profiles" / "dsh.toml"
            profile.write_text(profile.read_text().replace('harness = "dsh"', 'harness = "pi"'))
            output = Path(directory) / "out" / "dsh"
            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "dsh" / "generate.py"), "--output", str(output)],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("will not generate it", result.stderr)
            self.assertFalse(output.exists())

    def test_a_missing_plugin_template_fails_closed(self):
        """REGRESSION CONTRACT: a missing or malformed plugin template stops generation; TEST LAYER: generator failure test."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            (repo / "harnesses" / "dsh" / "templates" / "preset-plugins.yml").unlink()
            output = Path(directory) / "out" / "dsh"
            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "dsh" / "generate.py"), "--output", str(output)],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing preset plugin template", result.stderr)
            self.assertFalse(output.exists())

    def test_unsafe_output_path_is_refused(self):
        """REGRESSION CONTRACT: the generator refuses a path outside build/ or the temp root; TEST LAYER: path-safety test."""
        module = load_generator()
        with self.assertRaises(SystemExit):
            module.generate(ROOT / "README.md")

    def test_loader_expression_tags_survive_the_template(self):
        """REGRESSION CONTRACT: the vendored `!!js` rows are emitted verbatim; TEST LAYER: generated-artifact test."""
        template = TEMPLATE.read_text()
        self.assertIn("!!js process.platform", template)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dsh"
            generate_snapshot(output)
            self.assertIn(
                "!!js process.platform",
                (output / "patch" / "cordis.patch.yml").read_text(),
            )
            config = preset_config(output / "patch" / "cordis.patch.yml")
            self.assertIsInstance(
                find_row(config["plugins"], "tool-bash")["disabled"], _LoaderExpression
            )


if __name__ == "__main__":
    unittest.main()
