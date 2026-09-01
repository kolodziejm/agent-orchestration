import importlib.util
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "adapters" / "codex" / "render.py"
ROUTING = ROOT / "policy" / "routing.toml"
PROFILE = ROOT / "profiles" / "openai.toml"


def load_renderer():
    spec = importlib.util.spec_from_file_location("codex_render", RENDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load renderer module from {RENDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_snapshot(output: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(RENDER), "--output", str(output), "--profile", "openai"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


class CodexRenderContractTests(unittest.TestCase):
    def test_snapshot_contains_the_ten_canonical_role_contracts(self):
        """REGRESSION CONTRACT: Codex exposes exactly the ten canonical roles; TEST LAYER: renderer integration test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            render_snapshot(output)

            self.assertEqual(set(path.stem for path in (output / "agents").glob("*.toml")), set(roles))
            self.assertEqual(len(list((output / "agents").glob("*.toml"))), 10)
            self.assertTrue((output / "AGENTS.md").is_file())
            self.assertFalse((output / "manifest.json").exists())

    def test_snapshot_maps_openai_models_reasoning_and_sandbox_permissions(self):
        """REGRESSION CONTRACT: Codex receives the profile model, reasoning, and sandbox mapping; TEST LAYER: renderer integration test."""
        with ROUTING.open("rb") as handle:
            routing = tomllib.load(handle)
        with PROFILE.open("rb") as handle:
            profile = tomllib.load(handle)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            render_snapshot(output)

            for role, config in routing["roles"].items():
                with (output / "agents" / f"{role}.toml").open("rb") as handle:
                    agent = tomllib.load(handle)
                model = profile["models"][role]
                expected_effort = {"max": "xhigh"}.get(model["variant"], model["variant"])
                expected_sandbox = "read-only" if config["edit"] == "deny" else "workspace-write"

                self.assertEqual(agent["model"], model["model"].removeprefix("openai/"))
                self.assertEqual(agent["model_reasoning_effort"], expected_effort)
                self.assertEqual(agent["sandbox_mode"], expected_sandbox)

    def test_developer_instructions_preserve_every_role_contract_exactly(self):
        """REGRESSION CONTRACT: Codex preserves each complete role contract; TEST LAYER: generated artifact contract test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            render_snapshot(output)

            for role in roles:
                with (output / "agents" / f"{role}.toml").open("rb") as handle:
                    agent = tomllib.load(handle)
                self.assertEqual(agent["developer_instructions"], (ROOT / "roles" / f"{role}.md").read_text())

    def test_rendering_is_deterministic(self):
        """REGRESSION CONTRACT: identical canonical inputs produce byte-identical Codex snapshots; TEST LAYER: renderer integration test."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            render_snapshot(first)
            render_snapshot(second)

            first_files = sorted(path.relative_to(first) for path in first.rglob("*"))
            second_files = sorted(path.relative_to(second) for path in second.rglob("*"))
            self.assertEqual(first_files, second_files)
            self.assertEqual(
                [path.read_bytes() for path in sorted(first.rglob("*")) if path.is_file()],
                [path.read_bytes() for path in sorted(second.rglob("*")) if path.is_file()],
            )

    def test_agents_file_preserves_planner_and_reviewer_delegation_instructions(self):
        """REGRESSION CONTRACT: Codex instructions preserve planner/spec-writer and reviewer/explorer delegation; TEST LAYER: generated artifact contract test."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            render_snapshot(output)

            with (output / "agents" / "planner.toml").open("rb") as handle:
                planner = tomllib.load(handle)
            with (output / "agents" / "reviewer.toml").open("rb") as handle:
                reviewer = tomllib.load(handle)

            self.assertIn("delegate one focused read-only investigation to `explorer`", planner["developer_instructions"])
            self.assertIn("delegate their mechanical drafting to `spec-writer`", planner["developer_instructions"])
            self.assertIn("delegate one focused read-only investigation to `explorer`", reviewer["developer_instructions"])
            self.assertIn("Never invoke `worker`", reviewer["developer_instructions"])

            agents = (output / "AGENTS.md").read_text()
            self.assertIn("# Shared orchestration policy", agents)
            self.assertIn("# OpenAI profile orchestration", agents)

    def test_renderer_rejects_non_openai_model_mapping(self):
        """REGRESSION CONTRACT: Codex never silently accepts a non-OpenAI model identifier; TEST LAYER: renderer unit test."""
        renderer = load_renderer()
        self.assertEqual(renderer.codex_model("openai/gpt-5.6-luna"), "gpt-5.6-luna")
        with self.assertRaises(SystemExit):
            renderer.codex_model("deepseek/deepseek-v4-flash")

    def test_renderer_rejects_ask_edit_permission(self):
        """REGRESSION CONTRACT: Codex does not silently widen unsupported edit='ask'; TEST LAYER: renderer unit test."""
        renderer = load_renderer()

        with self.assertRaisesRegex(SystemExit, "edit permission"):
            renderer.sandbox_mode({"edit": "ask"})

    def test_renderer_rejects_unsafe_output_path_without_removing_existing_artifacts(self):
        """REGRESSION CONTRACT: unsafe output paths are rejected before existing artifacts can be removed; TEST LAYER: renderer integration test."""
        renderer = load_renderer()
        existing_artifact = ROOT / "README.md"

        with self.assertRaisesRegex(SystemExit, "Refusing unsafe output path"):
            renderer.render(ROOT)

        self.assertTrue(existing_artifact.is_file())

    def test_renderer_preserves_existing_output_when_rendering_fails(self):
        """REGRESSION CONTRACT: a failed Codex render leaves the previous output intact; TEST LAYER: renderer unit/integration boundary test."""
        renderer = load_renderer()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            output.mkdir()
            marker = output / "previous.txt"
            marker.write_text("previous snapshot")

            with mock.patch.object(renderer, "render_into", side_effect=RuntimeError("simulated render failure")):
                with self.assertRaisesRegex(RuntimeError, "simulated render failure"):
                    renderer.render(output)

            self.assertEqual(marker.read_text(), "previous snapshot")
            self.assertEqual(list(output.parent.glob(f".{output.name}.old-*")), [])


if __name__ == "__main__":
    unittest.main()
