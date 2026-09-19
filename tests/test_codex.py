import importlib.util
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATE = ROOT / "harnesses" / "codex" / "generate.py"
ROUTING = ROOT / "policy" / "routing.toml"
PROFILE = ROOT / "profiles" / "openai.toml"


def build_temp_repo(destination: Path) -> Path:
    """Copy the subset of the repo generate.py resolves ROOT against, so a test
    can corrupt "build/codex" without touching the real repo."""
    for name in ("harnesses", "policy", "profiles", "roles"):
        shutil.copytree(ROOT / name, destination / name)
    return destination


def load_generator():
    spec = importlib.util.spec_from_file_location("codex_generate", GENERATE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load generator module from {GENERATE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_snapshot(output: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATE), "--output", str(output), "--profile", "openai"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


class CodexGenerateContractTests(unittest.TestCase):
    def test_snapshot_contains_the_nine_canonical_role_contracts(self):
        """REGRESSION CONTRACT: Codex exposes exactly the nine canonical roles; TEST LAYER: generator integration test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            generate_snapshot(output)

            self.assertEqual(set(path.stem for path in (output / "agents").glob("*.toml")), set(roles))
            self.assertEqual(len(list((output / "agents").glob("*.toml"))), 9)
            self.assertTrue((output / "AGENTS.md").is_file())
            self.assertFalse((output / "manifest.json").exists())

    def test_snapshot_maps_openai_models_reasoning_and_sandbox_permissions(self):
        """REGRESSION CONTRACT: Codex receives the profile model, reasoning, and sandbox mapping; TEST LAYER: generator integration test."""
        with ROUTING.open("rb") as handle:
            routing = tomllib.load(handle)
        with PROFILE.open("rb") as handle:
            profile = tomllib.load(handle)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            generate_snapshot(output)

            for role, config in routing["roles"].items():
                with (output / "agents" / f"{role}.toml").open("rb") as handle:
                    agent = tomllib.load(handle)
                model = profile["models"][role]
                expected_effort = {"max": "xhigh"}.get(model["variant"], model["variant"])
                expected_sandbox = "read-only" if config["edit"] == "deny" else "workspace-write"

                self.assertEqual(agent["model"], model["model"].removeprefix("openai/"))
                self.assertEqual(agent["model_reasoning_effort"], expected_effort)
                self.assertEqual(agent["sandbox_mode"], expected_sandbox)

    def test_snapshot_exports_the_openai_control_plane_for_codex_setup(self):
        """This test will fail when Codex output omits primary and built-in profile intent."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            generate_snapshot(output)

            with (output / "control-plane.toml").open("rb") as handle:
                control_plane = tomllib.load(handle)
            self.assertEqual(
                control_plane,
                {
                    "primary": {"model": "gpt-5.6-sol", "effort": "medium"},
                    "small_model": "gpt-5.6-luna",
                    "builtins": {
                        "build": {"model": "gpt-5.6-sol", "effort": "medium"},
                        "plan": {"model": "gpt-5.6-sol", "effort": "high"},
                    },
                },
            )

    def test_developer_instructions_preserve_every_role_contract_exactly(self):
        """REGRESSION CONTRACT: Codex preserves each complete role contract; TEST LAYER: generated artifact contract test."""
        with ROUTING.open("rb") as handle:
            roles = tomllib.load(handle)["roles"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            generate_snapshot(output)

            for role in roles:
                with (output / "agents" / f"{role}.toml").open("rb") as handle:
                    agent = tomllib.load(handle)
                self.assertEqual(agent["developer_instructions"], (ROOT / "roles" / f"{role}.md").read_text())

    def test_generation_is_deterministic(self):
        """REGRESSION CONTRACT: identical canonical inputs produce byte-identical Codex snapshots; TEST LAYER: generator integration test."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            generate_snapshot(first)
            generate_snapshot(second)

            first_files = sorted(path.relative_to(first) for path in first.rglob("*"))
            second_files = sorted(path.relative_to(second) for path in second.rglob("*"))
            self.assertEqual(first_files, second_files)
            self.assertEqual(
                [path.read_bytes() for path in sorted(first.rglob("*")) if path.is_file()],
                [path.read_bytes() for path in sorted(second.rglob("*")) if path.is_file()],
            )

    def test_agents_file_preserves_planner_and_reviewer_delegation_instructions(self):
        """REGRESSION CONTRACT: Codex instructions preserve planner and reviewer/explorer delegation; TEST LAYER: generated artifact contract test."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            generate_snapshot(output)

            with (output / "agents" / "planner.toml").open("rb") as handle:
                planner = tomllib.load(handle)
            with (output / "agents" / "reviewer.toml").open("rb") as handle:
                reviewer = tomllib.load(handle)

            self.assertIn("broad mechanical evidence gathering", planner["developer_instructions"])
            self.assertIn("only for genuinely independent evidence areas", planner["developer_instructions"])
            self.assertIn("otherwise use one focused explorer or targeted direct reads", planner["developer_instructions"])
            self.assertIn("managed output", planner["developer_instructions"])
            self.assertNotIn("spec-writer", planner["developer_instructions"])
            self.assertIn("broad mechanical evidence gathering", reviewer["developer_instructions"])
            self.assertIn("only for genuinely independent evidence areas", reviewer["developer_instructions"])
            self.assertIn("otherwise use one focused explorer or targeted direct reads", reviewer["developer_instructions"])
            self.assertIn("Never invoke `worker`", reviewer["developer_instructions"])

            agents = (output / "AGENTS.md").read_text()
            self.assertIn("# Shared orchestration policy", agents)
            self.assertIn("# OpenAI profile orchestration", agents)

    def test_generator_rejects_non_openai_model_mapping(self):
        """REGRESSION CONTRACT: Codex never silently accepts a non-OpenAI model identifier; TEST LAYER: generator unit test."""
        generator = load_generator()
        self.assertEqual(generator.codex_model("openai/gpt-5.6-luna"), "gpt-5.6-luna")
        with self.assertRaises(SystemExit):
            generator.codex_model("deepseek/deepseek-v4-flash")

    def test_generator_rejects_pi_only_profile_before_generation(self):
        """This test will fail when Codex consumes a profile reserved for Pi."""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(GENERATE), "--profile", "deepseek", "--output", str(Path(directory) / "codex")],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("harness", result.stderr.lower())
            self.assertFalse((Path(directory) / "codex").exists())

    def test_generator_rejects_ask_edit_permission(self):
        """REGRESSION CONTRACT: Codex does not silently widen unsupported edit='ask'; TEST LAYER: generator unit test."""
        generator = load_generator()

        with self.assertRaisesRegex(SystemExit, "edit permission"):
            generator.sandbox_mode({"edit": "ask"})

    def test_generator_rejects_bash_deny_without_granting_shell(self):
        """This test will fail when Codex generates bash=deny as a shell-capable sandbox."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            policy = repo / "policy" / "routing.toml"
            policy.write_text(policy.read_text().replace('bash = "ask"', 'bash = "deny"'))
            output = Path(directory) / "output"

            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "codex" / "generate.py"), "--output", str(output)],
                cwd=repo,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot enforce bash = deny", result.stderr)
            self.assertFalse(output.exists())

    def test_generator_rejects_unsafe_output_path_without_removing_existing_artifacts(self):
        """REGRESSION CONTRACT: unsafe output paths are rejected before existing artifacts can be removed; TEST LAYER: generator integration test."""
        generator = load_generator()
        existing_artifact = ROOT / "README.md"

        with self.assertRaisesRegex(SystemExit, "Refusing unsafe output path"):
            generator.generate(ROOT)

        self.assertTrue(existing_artifact.is_file())

    def test_generator_preserves_existing_output_when_generation_fails(self):
        """REGRESSION CONTRACT: a failed Codex generation leaves the previous output intact; TEST LAYER: generator unit/integration boundary test."""
        generator = load_generator()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codex"
            output.mkdir()
            marker = output / "previous.txt"
            marker.write_text("previous snapshot")

            with mock.patch.object(generator, "generate_into", side_effect=RuntimeError("simulated generate failure")):
                with self.assertRaisesRegex(RuntimeError, "simulated generate failure"):
                    generator.generate(output)

            self.assertEqual(marker.read_text(), "previous snapshot")
            self.assertEqual(list(output.parent.glob(f".{output.name}.old-*")), [])

    def test_generator_refuses_symlinked_default_output_and_leaves_target_untouched(self):
        """REGRESSION CONTRACT: a pre-resolved --output default would silently follow a symlink at "build/codex" instead of hitting the is_symlink() guard when --output is omitted; TEST LAYER: generator integration test."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            target = Path(directory) / "real-target"
            target.mkdir()
            marker = target / "marker.txt"
            marker.write_text("original")
            (repo / "build").mkdir(parents=True, exist_ok=True)
            (repo / "build" / "codex").symlink_to(target)

            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "codex" / "generate.py")],
                cwd=repo,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing symlinked output path", result.stderr)
            self.assertTrue((repo / "build" / "codex").is_symlink())
            self.assertEqual(marker.read_text(), "original")

    def test_generator_rejects_symlinked_parent_under_repository_root(self):
        """This test will fail when a symlinked parent redirects generated output outside ROOT."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            redirected = Path(directory) / "redirected-build"
            redirected.mkdir()
            marker = redirected / "marker.txt"
            marker.write_text("original")
            (repo / "build").symlink_to(redirected, target_is_directory=True)

            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "codex" / "generate.py")],
                cwd=repo,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr.lower())
            self.assertEqual(marker.read_text(), "original")

    def test_generator_rejects_symlinked_parent_under_temporary_root(self):
        """This test will fail when a temporary-root symlink redirects generated output."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            redirected = root / "redirected"
            redirected.mkdir()
            marker = redirected / "marker.txt"
            marker.write_text("original")
            parent = root / "parent-link"
            parent.symlink_to(redirected, target_is_directory=True)
            output = parent / "output"

            result = subprocess.run(
                [sys.executable, str(GENERATE), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr.lower())
            self.assertEqual(marker.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
