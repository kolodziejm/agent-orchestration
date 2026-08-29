import json
import importlib.util
import contextlib
import io
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTING = ROOT / "policy" / "routing.toml"
PROFILES = ROOT / "profiles"
ROLES = ROOT / "roles"
RENDER = ROOT / "adapters" / "opencode" / "render.py"
INSTALL = ROOT / "adapters" / "opencode" / "install.py"


def load_install_module():
    spec = importlib.util.spec_from_file_location("opencode_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_render_module():
    spec = importlib.util.spec_from_file_location("opencode_render", RENDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load renderer module from {RENDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ROUTING.open("rb") as handle:
            cls.routing = tomllib.load(handle)
        cls.roles = cls.routing["roles"]

    def test_every_role_has_a_contract(self):
        for role in self.roles:
            self.assertTrue((ROLES / f"{role}.md").is_file(), role)

    def test_role_contracts_are_provider_agnostic(self):
        forbidden = ("openai/", "deepseek/", "zai-coding-plan/")
        for path in ROLES.glob("*.md"):
            content = path.read_text()
            for token in forbidden:
                self.assertNotIn(token, content, f"{token} found in {path}")

    def test_nested_delegation_boundaries(self):
        self.assertEqual(set(self.roles["planner"]["delegates"]), {"explorer", "spec-writer"})
        self.assertEqual(self.roles["reviewer"]["delegates"], ["explorer"])
        self.assertEqual(self.roles["spec-writer"]["delegates"], [])
        self.assertEqual(self.roles["explorer"]["delegates"], [])
        self.assertEqual(self.roles["worker"]["delegates"], ["vision-*"])
        self.assertEqual(self.roles["worker-complex"]["delegates"], ["vision-*"])

    def test_profiles_map_every_role(self):
        expected = set(self.roles)
        for path in PROFILES.glob("*.toml"):
            with path.open("rb") as handle:
                profile = tomllib.load(handle)
            self.assertEqual(set(profile["models"]), expected, path.name)


class OpenCodeRenderTests(unittest.TestCase):
    def test_renderer_produces_agent_contracts_and_profile_fragments(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = subprocess.run(
                [sys.executable, str(RENDER), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            planner = (output / "agents" / "planner.md").read_text()
            self.assertIn("mode: subagent", planner)
            self.assertIn('"*": deny', planner)
            self.assertIn("explorer: allow", planner)
            self.assertIn("spec-writer: allow", planner)
            self.assertNotIn("model:", planner)

            complex_worker = (output / "agents" / "worker-complex.md").read_text()
            self.assertIn('"vision-*": allow', complex_worker)

            openai = json.loads((output / "profiles" / "openai" / "agent-routing.json").read_text())
            self.assertEqual(openai["agent"]["worker"]["variant"], "high")
            self.assertEqual(openai["agent"]["worker-complex"]["variant"], "max")
            self.assertEqual(openai["agent"]["spec-writer"]["model"], "openai/gpt-5.6-luna")

            core = output / "profiles" / "_shared" / "orchestration-core.md"
            self.assertEqual(core.read_text(), (ROOT / "policy" / "orchestration.md").read_text())

            validator = (output / "agents" / "validator.md").read_text()
            debugger = (output / "agents" / "debugger.md").read_text()
            self.assertIn('bash:\n    "*": ask', validator)
            self.assertIn('bash:\n    "*": ask', debugger)

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

    def test_keyboard_interrupt_during_atomic_replace_restores_previous_output(self):
        renderer = load_render_module()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot"
            output.mkdir()
            marker = output / "previous.txt"
            marker.write_text("previous snapshot")
            original_rename = Path.rename

            def interrupt_staged_rename(path, target):
                if path.name == "result":
                    raise KeyboardInterrupt("simulated interruption")
                return original_rename(path, target)

            with mock.patch.object(Path, "rename", interrupt_staged_rename):
                with self.assertRaises(KeyboardInterrupt):
                    renderer.render(output)

            self.assertTrue(output.is_dir())
            self.assertEqual((output / "previous.txt").read_text(), "previous snapshot")
            self.assertEqual(list(output.parent.glob(f".{output.name}.old-*")), [])


class OpenCodeInstallPlanTests(unittest.TestCase):
    def test_unconfigured_generated_profile_is_not_added_to_installed_manifest(self):
        """REGRESSION CONTRACT: install only configured profiles; TEST LAYER: installer plan unit test."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "rendered"
            target = root / "target"
            subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)
            generated_profiles = json.loads((rendered / "manifest.json").read_text())["profiles"]
            self.assertIn("openai", generated_profiles)
            target.mkdir()
            profile = target / "profiles" / "glm"
            profile.mkdir(parents=True)
            (profile / "opencode.json").write_text(json.dumps({}))
            self.assertFalse((target / "profiles" / "openai" / "opencode.json").exists())

            files, _ = install.desired_state(rendered, target)

            installed = json.loads(files[target / install.MANIFEST_NAME])
            self.assertEqual(installed["profiles"], ["glm"])

    def test_merge_preserves_unrelated_config_and_removes_stale_managed_roles(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "rendered"
            target = root / "target"
            subprocess.run(
                [sys.executable, str(RENDER), "--output", str(rendered)],
                cwd=ROOT,
                check=True,
            )

            previous = {
                "format_version": 1,
                "roles": ["worker", "obsolete-managed-role"],
                "profiles": ["openai", "glm", "retired-profile"],
            }
            target.mkdir()
            (target / install.MANIFEST_NAME).write_text(json.dumps(previous))
            custom_instruction = "/tmp/custom-instruction.md"
            for name in previous["profiles"]:
                profile = target / "profiles" / name
                profile.mkdir(parents=True)
                config = {
                    "provider": {"sentinel": {"enabled": True}},
                    "agent": {
                        "custom-agent": {"model": "custom/model"},
                        "obsolete-managed-role": {"model": "old/model"},
                    },
                    "instructions": [
                        custom_instruction,
                        str(target / "profiles" / "_shared" / "orchestration-core.md"),
                        str(profile / "orchestration.md"),
                    ],
                }
                (profile / "opencode.json").write_text(json.dumps(config))

            files, deletions = install.desired_state(rendered, target)
            openai_path = target / "profiles" / "openai" / "opencode.json"
            merged = json.loads(files[openai_path])
            self.assertEqual(merged["provider"], {"sentinel": {"enabled": True}})
            self.assertIn("custom-agent", merged["agent"])
            self.assertIn("worker", merged["agent"])
            self.assertNotIn("obsolete-managed-role", merged["agent"])
            self.assertIn(custom_instruction, merged["instructions"])
            self.assertEqual(merged["instructions"].count(custom_instruction), 1)
            self.assertIn(target / "agents" / "obsolete-managed-role.md", deletions)

    def test_removed_profile_loses_all_managed_agents_and_artifacts(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "rendered"
            target = root / "target"
            subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)

            manifest = json.loads((rendered / "manifest.json").read_text())
            previous = dict(manifest)
            current = dict(manifest)
            current["profiles"] = [name for name in manifest["profiles"] if name != "glm"]
            (rendered / "manifest.json").write_text(json.dumps(current))
            target.mkdir()
            (target / install.MANIFEST_NAME).write_text(json.dumps(previous))

            for name in previous["profiles"]:
                profile = target / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "opencode.json").write_text(
                    json.dumps(
                        {
                            "agent": {
                                **{role: {"model": "managed/model"} for role in previous["roles"]},
                                "custom-agent": {"model": "custom/model"},
                            },
                            "instructions": [str(profile / "orchestration.md")],
                        }
                    )
                )
                (profile / "orchestration.md").write_text("managed")

            files, deletions = install.desired_state(rendered, target)
            glm_config = json.loads(files[target / "profiles" / "glm" / "opencode.json"])
            self.assertEqual(glm_config["agent"], {"custom-agent": {"model": "custom/model"}})
            self.assertIn(target / "profiles" / "glm" / "orchestration.md", deletions)

            (target / "profiles" / "glm" / "opencode.json").unlink()
            _, deletions_without_config = install.desired_state(rendered, target)
            self.assertIn(target / "profiles" / "glm" / "orchestration.md", deletions_without_config)

    def test_symlinked_destination_is_rejected_before_diff_can_disclose_contents(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            secret = root / "private.txt"
            secret.write_text("TOP_SECRET_SHOULD_NOT_APPEAR")
            (target / "agents").mkdir(parents=True)
            (target / "agents" / "worker.md").symlink_to(secret)
            for name in ("openai", "glm"):
                profile = target / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "opencode.json").write_text("{}")

            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--target",
                    str(target),
                    "--dry-run",
                    "--skip-validate",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(secret.read_text(), result.stdout)
            self.assertNotIn(secret.read_text(), result.stderr)
            self.assertIn("Refusing", result.stderr)

    def test_keyboard_interrupt_during_mutation_rolls_back_all_files(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            originals = {}
            for name in ("openai", "glm"):
                profile = target / "profiles" / name
                profile.mkdir(parents=True)
                config_path = profile / "opencode.json"
                config_path.write_text(json.dumps({"sentinel": name}))
                originals[config_path] = config_path.read_bytes()

            original_write_text = Path.write_text
            calls = 0

            def interrupt_second_write(path, data, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise KeyboardInterrupt("simulated interruption")
                return original_write_text(path, data, *args, **kwargs)

            with mock.patch.object(Path, "write_text", interrupt_second_write):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(KeyboardInterrupt):
                        install.install(target, dry_run=False, validate=False)

            for path, content in originals.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertFalse((target / install.MANIFEST_NAME).exists())


class OpenCodeInstallValidationTests(unittest.TestCase):
    def test_validation_checks_only_locally_configured_profiles(self):
        """REGRESSION CONTRACT: validate configured profiles only; TEST LAYER: installer integration test."""
        install = load_install_module()
        renderer = load_render_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "rendered"
            target = root / "target"
            subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)
            generated_profiles = json.loads((rendered / "manifest.json").read_text())["profiles"]
            self.assertIn("openai", generated_profiles)
            target.mkdir()
            profile = target / "profiles" / "glm"
            profile.mkdir(parents=True)
            (profile / "opencode.json").write_text(json.dumps({}))
            self.assertFalse((target / "profiles" / "openai" / "opencode.json").exists())

            validation_calls = []

            def run(command, **kwargs):
                if command[:2] == [sys.executable, str(RENDER)]:
                    output = Path(command[command.index("--output") + 1])
                    renderer.render(output)
                else:
                    validation_calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(install.subprocess, "run", side_effect=run):
                with contextlib.redirect_stdout(io.StringIO()):
                    install.install(target, dry_run=False, validate=True)

            self.assertEqual(
                [call[0] for call in validation_calls],
                [["opencode", "debug", "config"]],
            )
            self.assertEqual(
                {
                    Path(call[1]["env"]["OPENCODE_CONFIG"]).parent.name
                    for call in validation_calls
                },
                {"glm"},
            )
            self.assertNotIn(
                "openai",
                {
                    Path(call[1]["env"]["OPENCODE_CONFIG"]).parent.name
                    for call in validation_calls
                },
            )


if __name__ == "__main__":
    unittest.main()
