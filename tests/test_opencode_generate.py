import json
import importlib.util
import contextlib
import io
import shutil
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
GENERATE = ROOT / "harnesses" / "opencode" / "generate.py"
INSTALL = ROOT / "harnesses" / "opencode" / "install.py"
MANAGED_SECTION = (
    "<!-- agent-orchestration:start -->\n"
    + (ROOT / "policy" / "orchestration.md").read_text()
    + "<!-- agent-orchestration:end -->\n"
)
REPOSITORY_SKILLS = {
    path.parent.name: path.read_bytes() for path in sorted((ROOT / "skills").glob("*/SKILL.md"))
}


def load_install_module():
    spec = importlib.util.spec_from_file_location("opencode_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_generate_module():
    spec = importlib.util.spec_from_file_location("opencode_generate", GENERATE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load generator module from {GENERATE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_temp_repo(destination: Path) -> Path:
    """Copy the subset of the repo generate.py resolves ROOT against, so a test
    can corrupt one profile without touching the real profiles/ directory."""
    for name in ("harnesses", "policy", "profiles"):
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


class OpenCodeGenerateTests(unittest.TestCase):
    def test_generator_intentionally_excludes_pi_profiles(self):
        """This test will fail when a Pi-only profile leaks into OpenCode output."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run([sys.executable, str(GENERATE), "--output", str(output)], cwd=ROOT, check=True)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertNotIn("deepseek", manifest["profiles"])
            self.assertFalse((output / "profiles" / "deepseek").exists())

    def test_generator_produces_agent_contracts_and_profile_fragments(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = subprocess.run(
                [sys.executable, str(GENERATE), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            planner = (output / "agents" / "planner.md").read_text()
            self.assertIn("mode: subagent", planner)
            self.assertIn('"*": deny', planner)
            self.assertNotIn("task:", planner)
            self.assertNotIn("spec-writer", planner)
            self.assertNotIn("model:", planner)
            self.assertEqual(planner.count("---"), 2)

            worker = (output / "agents" / "worker.md").read_text()
            complex_worker = (output / "agents" / "worker-complex.md").read_text()
            self.assertNotIn('"vision-*": allow', worker)
            self.assertNotIn('"vision-*": allow', complex_worker)
            self.assertNotIn("Agent(", worker)
            self.assertNotIn("Agent(", complex_worker)
            self.assertEqual(worker.count("---"), 2)
            self.assertEqual(complex_worker.count("---"), 2)

            openai = json.loads((output / "profiles" / "openai" / "agent-routing.json").read_text())
            self.assertEqual(openai["agent"]["worker"]["variant"], "high")
            self.assertEqual(openai["agent"]["worker-complex"]["variant"], "max")
            self.assertNotIn("spec-writer", openai["agent"])

            self.assertFalse((output / "profiles" / "_shared").exists())
            self.assertFalse((output / "workflows").exists())

            validator = (output / "agents" / "validator.md").read_text()
            debugger = (output / "agents" / "debugger.md").read_text()
            self.assertIn('bash:\n    "*": ask', validator)
            self.assertIn('bash:\n    "*": ask', debugger)


    def test_generator_exports_the_profile_control_plane_separately(self):
        """This test will fail when OpenCode drops primary, small-model, or built-in intent."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = subprocess.run(
                [sys.executable, str(GENERATE), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            control_plane = json.loads(
                (output / "profiles" / "openai" / "control-plane.json").read_text()
            )
            self.assertEqual(
                control_plane,
                {
                    "primary": {"model": "openai/gpt-6.1-sol", "variant": "medium"},
                    "small_model": "openai/gpt-6-luna",
                    "builtins": {
                        "build": {"model": "openai/gpt-6.1-sol", "variant": "medium"},
                        "plan": {"model": "openai/gpt-6.1-sol", "variant": "high"},
                    },
                },
            )

    def test_generator_rejects_repository_root_as_output(self):
        result = subprocess.run(
            [sys.executable, str(GENERATE), "--output", str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing unsafe output path", result.stderr)
        self.assertTrue((ROOT / "README.md").is_file())

    def test_generator_rejects_a_typoed_harness_value_instead_of_silently_dropping_the_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            broken_profile = repo / "profiles" / "glm.toml"
            set_toml_top_level_key(broken_profile, "harness", "opencde")

            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "opencode" / "generate.py"), "--output", str(Path(directory) / "out")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(broken_profile), result.stderr)
            self.assertIn("opencde", result.stderr)

    def test_generator_preserves_bash_deny_in_harness_capabilities(self):
        """This test will fail when OpenCode silently widens bash=deny while generation."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            policy = repo / "policy" / "routing.toml"
            policy.write_text(policy.read_text().replace('bash = "ask"', 'bash = "deny"'))
            output = Path(directory) / "output"
            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "opencode" / "generate.py"), "--output", str(output)],
                cwd=repo,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            validator = (output / "agents" / "validator.md").read_text()
            self.assertIn('"*": deny', validator)

    def test_generator_refuses_to_generate_an_empty_profile_set(self):
        """An empty profile set would make the installer uninstall every managed profile."""
        with tempfile.TemporaryDirectory() as directory:
            repo = build_temp_repo(Path(directory) / "repo")
            for name in ("openai.toml", "glm.toml"):
                set_toml_top_level_key(repo / "profiles" / name, "harness", "codex")
            # profiles/claude.toml already declares harness = "claude-code".

            result = subprocess.run(
                [sys.executable, str(repo / "harnesses" / "opencode" / "generate.py"), "--output", str(Path(directory) / "out")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("empty profile set", result.stderr)

    def test_keyboard_interrupt_during_atomic_replace_restores_previous_output(self):
        generator = load_generate_module()
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
                    generator.generate(output)

            self.assertTrue(output.is_dir())
            self.assertEqual((output / "previous.txt").read_text(), "previous snapshot")
            self.assertEqual(list(output.parent.glob(f".{output.name}.old-*")), [])

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
                [sys.executable, str(repo / "harnesses" / "opencode" / "generate.py")],
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


class OpenCodeInstallPlanTests(unittest.TestCase):
    def test_install_registers_no_instruction_file_and_strips_legacy_ones(self):
        """This test will fail when install keeps registering policy files or loses user config bytes."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated"
            target = root / "target"
            subprocess.run([sys.executable, str(GENERATE), "--output", str(generated)], check=True)

            config_path = target / "profiles" / "openai" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            legacy_core = str(target / "profiles" / "_shared" / "orchestration-core.md")
            config_path.write_text(
                json.dumps({"instructions": ["/tmp/unrelated.md", legacy_core]})
            )
            (target / "profiles" / "_shared").mkdir(parents=True)
            (target / "profiles" / "_shared" / "orchestration-core.md").write_text("legacy core\n")

            files, _ = install.desired_state(generated, target, adopt=True)
            merged = json.loads(files[config_path])
            self.assertEqual(merged["instructions"], ["/tmp/unrelated.md"])
            self.assertNotIn("workflows", json.loads(files[target / install.MANIFEST_NAME]))
            deletions = install.desired_state(generated, target, adopt=True)[1]
            self.assertIn(target / "profiles" / "_shared" / "orchestration-core.md", deletions)
            self.assertNotIn(target / "workflows" / "feature-workflow-pilot.md", files)

    def test_install_appends_the_policy_to_a_user_owned_agents_md(self):
        """This test will fail when installing the policy changes user bytes, needs adoption, or a repeat install writes again."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            target = root / "target"
            target.mkdir()
            agents_md = target / "AGENTS.md"
            user_bytes = b"# My rules\r\n\r\nKeep answers short.\r\n"
            agents_md.write_bytes(user_bytes)

            with mock.patch.object(Path, "home", return_value=fake_home):
                with contextlib.redirect_stdout(io.StringIO()):
                    install.install(target, dry_run=False, validate=False)
                installed = agents_md.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()) as second_out:
                    install.install(target, dry_run=False, validate=False)

            self.assertEqual(installed, user_bytes + b"\n" + MANAGED_SECTION.encode())
            self.assertEqual(agents_md.read_bytes(), installed)
            self.assertIn("already synchronized", second_out.getvalue())

    def test_first_install_reports_unmanaged_control_plane_collision_until_adopted(self):
        """This test will fail when first install overwrites runtime control settings without adoption."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            config_path = target / "profiles" / "openai" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            original = {
                "model": "user/primary",
                "small_model": "user/small",
                "agent": {"build": {"model": "user/build"}},
            }
            config_path.write_text(json.dumps(original))

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
            self.assertIn(f"{config_path} (model)", result.stderr)
            self.assertIn("--adopt", result.stderr)
            self.assertEqual(json.loads(config_path.read_text()), original)

    def test_merge_installs_control_plane_without_overwriting_unrelated_config(self):
        """This test will fail when installation generates roles but drops control-plane intent."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated"
            target = root / "target"
            subprocess.run([sys.executable, str(GENERATE), "--output", str(generated)], check=True)

            profile = target / "profiles" / "openai"
            profile.mkdir(parents=True)
            config_path = profile / "opencode.json"
            config_path.write_text(
                json.dumps(
                    {
                        "provider": {"sentinel": {"enabled": True}},
                        "model": "custom/primary",
                        "variant": "low",
                        "small_model": "custom/small",
                        "agent": {"custom-agent": {"model": "custom/agent"}},
                    }
                )
            )

            files, _ = install.desired_state(generated, target, adopt=True)
            merged = json.loads(files[config_path])
            self.assertEqual(merged["provider"], {"sentinel": {"enabled": True}})
            self.assertEqual(merged["model"], "openai/gpt-6.1-sol")
            self.assertEqual(merged["variant"], "medium")
            self.assertEqual(merged["small_model"], "openai/gpt-6-luna")
            self.assertEqual(merged["agent"]["custom-agent"], {"model": "custom/agent"})
            self.assertEqual(
                merged["agent"]["build"],
                {"model": "openai/gpt-6.1-sol", "variant": "medium"},
            )
            self.assertEqual(
                merged["agent"]["plan"],
                {"model": "openai/gpt-6.1-sol", "variant": "high"},
            )

    def test_first_install_reports_unmanaged_role_collision_until_adopted(self):
        """This test will fail when first install overwrites a managed-name file without adoption."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            role_path = target / "agents" / "worker.md"
            role_path.parent.mkdir()
            role_path.write_text("user-owned role\n")

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
            self.assertIn(str(role_path), result.stderr)
            self.assertIn("--adopt", result.stderr)
            self.assertEqual(role_path.read_text(), "user-owned role\n")

    def test_first_install_reports_unmanaged_profile_agent_collision(self):
        """This test will fail when first install silently replaces a profile agent entry."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            config_path = target / "profiles" / "openai" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"agent": {"worker": {"model": "user/model"}}}))

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
            self.assertIn(f"{config_path} (agent.worker)", result.stderr)
            self.assertIn("--adopt", result.stderr)
            self.assertIn("user/model", config_path.read_text())

    def test_unconfigured_generated_profile_is_not_added_to_installed_manifest(self):
        """REGRESSION CONTRACT: install only configured profiles; TEST LAYER: installer plan unit test."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated"
            target = root / "target"
            subprocess.run([sys.executable, str(GENERATE), "--output", str(generated)], check=True)
            generated_profiles = json.loads((generated / "manifest.json").read_text())["profiles"]
            self.assertIn("openai", generated_profiles)
            target.mkdir()
            profile = target / "profiles" / "glm"
            profile.mkdir(parents=True)
            (profile / "opencode.json").write_text(json.dumps({}))
            self.assertFalse((target / "profiles" / "openai" / "opencode.json").exists())

            files, _ = install.desired_state(generated, target)

            installed = json.loads(files[target / install.MANIFEST_NAME])
            self.assertEqual(installed["profiles"], ["glm"])

    def test_merge_preserves_unrelated_config_and_removes_stale_managed_roles(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated"
            target = root / "target"
            subprocess.run(
                [sys.executable, str(GENERATE), "--output", str(generated)],
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

            files, deletions = install.desired_state(generated, target)
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
            generated = root / "generated"
            target = root / "target"
            subprocess.run([sys.executable, str(GENERATE), "--output", str(generated)], check=True)

            manifest = json.loads((generated / "manifest.json").read_text())
            previous = dict(manifest)
            current = dict(manifest)
            current["profiles"] = [name for name in manifest["profiles"] if name != "glm"]
            (generated / "manifest.json").write_text(json.dumps(current))
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

            files, deletions = install.desired_state(generated, target)
            glm_config = json.loads(files[target / "profiles" / "glm" / "opencode.json"])
            self.assertEqual(glm_config["agent"], {"custom-agent": {"model": "custom/model"}})
            self.assertIn(target / "profiles" / "glm" / "orchestration.md", deletions)

            (target / "profiles" / "glm" / "opencode.json").unlink()
            _, deletions_without_config = install.desired_state(generated, target)
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
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir(parents=True)
            target = root / "target"
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
                with mock.patch.object(Path, "home", return_value=fake_home):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(KeyboardInterrupt):
                            install.install(target, dry_run=False, validate=False)

            for path, content in originals.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertFalse((target / install.MANIFEST_NAME).exists())
            backups_root = fake_home / ".local" / "state" / "agent-orchestration" / "backups"
            self.assertTrue(backups_root.exists())
            backed_up = list(backups_root.rglob("opencode.json"))
            self.assertEqual(len(backed_up), len(originals))
            for path in backed_up:
                self.assertIn("opencode", path.relative_to(backups_root).parts)

    def test_backups_use_unique_directories_when_installs_share_a_timestamp(self):
        """This test will fail when two OpenCode backups collide in one timestamp directory."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            target = root / "target"
            for name in ("openai", "glm"):
                profile = target / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "opencode.json").write_text("{}")

            fixed = mock.Mock()
            fixed.strftime.return_value = "20260101T000000Z"
            fake_datetime = mock.Mock()
            fake_datetime.now.return_value = fixed

            with mock.patch.object(Path, "home", return_value=fake_home):
                with mock.patch.object(install, "datetime", fake_datetime):
                    install.install(target, dry_run=False, validate=False)
                    (target / "profiles" / "openai" / "opencode.json").write_text("{}")
                    install.install(target, dry_run=False, validate=False)

            backups = list(
                (fake_home / ".local" / "state" / "agent-orchestration" / "backups").rglob(
                    "opencode.json"
                )
            )
            self.assertEqual(len(backups), 3)
            self.assertEqual(len({path.parents[3].name for path in backups}), 2)


@contextlib.contextmanager
def generator_with_extra_skill(install, name: str, content: bytes):
    """Make the installer's generator emit one skill the repository does not have,
    as an earlier repository version that still shipped it would."""
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        bundle = Path(command[command.index("--output") + 1])
        skill = bundle / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(content)
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["skills"] = sorted([*manifest["skills"], name])
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return result

    with mock.patch.object(install.subprocess, "run", side_effect=run):
        yield


class OpenCodeSkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.install = load_install_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolved, because the installer reports and mutates resolved target paths.
        self.root = Path(self.temp.name).resolve()
        self.fake_home = self.root / "fake-home"
        self.fake_home.mkdir()
        self.target = self.root / "target"
        self.backups = self.fake_home / ".local" / "state" / "agent-orchestration" / "backups"
        self.assertTrue(REPOSITORY_SKILLS, "the repository ships at least one skill")

    def run_install(self, **kwargs) -> str:
        with mock.patch.object(Path, "home", return_value=self.fake_home):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.install.install(self.target, validate=False, **kwargs)
        return output.getvalue()

    def foreign_skill_files(self) -> dict[Path, bytes]:
        files = {
            self.target / "skills" / "operator-skill" / "SKILL.md": b"---\nname: operator-skill\n---\nmine\r\n",
            self.target / "skills" / "operator-skill" / "scripts" / "run.sh": b"#!/bin/sh\n",
            self.target / "skills" / "loose-note.md": b"operator note\n",
        }
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return files

    def test_install_writes_each_skill_and_leaves_foreign_skills_alone(self):
        """This test will fail when installation skips or alters a repository skill, or touches a skill it does not own."""
        foreign = self.foreign_skill_files()

        self.run_install(dry_run=False)
        second = self.run_install(dry_run=False)

        for name, content in REPOSITORY_SKILLS.items():
            self.assertEqual((self.target / "skills" / name / "SKILL.md").read_bytes(), content)
        for path, content in foreign.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(
            sorted(path.name for path in (self.target / "skills").iterdir()),
            sorted([*REPOSITORY_SKILLS, "operator-skill", "loose-note.md"]),
        )
        manifest = json.loads((self.target / self.install.MANIFEST_NAME).read_text())
        self.assertEqual(manifest["skills"], sorted(REPOSITORY_SKILLS))
        self.assertIn("already synchronized", second)

    def test_dry_run_lists_every_skill_write_without_creating_it(self):
        """This test will fail when a preview hides a skill write or writes it."""
        report = self.run_install(dry_run=True)

        for name in REPOSITORY_SKILLS:
            self.assertIn(f"+++ generated:skills/{name}/SKILL.md", report)
        self.assertIn("DRY RUN", report)
        self.assertFalse((self.target / "skills").exists())

    def test_skill_dropped_from_a_later_bundle_is_removed_on_reinstall(self):
        """This test will fail when a deleted or renamed skill stays installed, or its removal reaches another skill."""
        foreign = self.foreign_skill_files()
        retired = self.target / "skills" / "retired-skill" / "SKILL.md"
        with generator_with_extra_skill(self.install, "retired-skill", b"retired skill\n"):
            self.run_install(dry_run=False)
        self.assertEqual(retired.read_bytes(), b"retired skill\n")
        manifest_path = self.target / self.install.MANIFEST_NAME
        self.assertIn("retired-skill", json.loads(manifest_path.read_text())["skills"])

        preview = self.run_install(dry_run=True)
        self.assertIn("+++ deleted:skills/retired-skill/SKILL.md", preview)
        self.assertEqual(retired.read_bytes(), b"retired skill\n")

        self.run_install(dry_run=False)

        self.assertFalse(retired.parent.exists())
        self.assertEqual(json.loads(manifest_path.read_text())["skills"], sorted(REPOSITORY_SKILLS))
        for name, content in REPOSITORY_SKILLS.items():
            self.assertEqual((self.target / "skills" / name / "SKILL.md").read_bytes(), content)
        for path, content in foreign.items():
            self.assertEqual(path.read_bytes(), content)
        backed_up = list(self.backups.rglob("skills/retired-skill/SKILL.md"))
        self.assertEqual([path.read_bytes() for path in backed_up], [b"retired skill\n"])

    def test_a_removed_skill_directory_holding_operator_files_is_kept(self):
        """This test will fail when removing a dropped skill deletes files the operator added beside it."""
        with generator_with_extra_skill(self.install, "retired-skill", b"retired skill\n"):
            self.run_install(dry_run=False)
        notes = self.target / "skills" / "retired-skill" / "notes.md"
        notes.write_bytes(b"operator notes\n")

        self.run_install(dry_run=False)

        self.assertFalse((self.target / "skills" / "retired-skill" / "SKILL.md").exists())
        self.assertEqual(notes.read_bytes(), b"operator notes\n")

    def test_first_install_reports_an_unmanaged_skill_collision_until_adopted(self):
        """This test will fail when a first install overwrites an operator's same-named skill without adoption."""
        name = sorted(REPOSITORY_SKILLS)[0]
        skill = self.target / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(b"operator-written skill\n")

        with self.assertRaises(SystemExit) as refused:
            self.run_install(dry_run=False)
        self.assertIn(str(skill), str(refused.exception))
        self.assertIn("--adopt", str(refused.exception))
        self.assertEqual(skill.read_bytes(), b"operator-written skill\n")
        self.assertFalse((self.target / self.install.MANIFEST_NAME).exists())

        self.run_install(dry_run=False, adopt=True)

        self.assertEqual(skill.read_bytes(), REPOSITORY_SKILLS[name])
        backed_up = list(self.backups.rglob(f"skills/{name}/SKILL.md"))
        self.assertEqual([path.read_bytes() for path in backed_up], [b"operator-written skill\n"])

    def test_upgrade_claims_hand_copied_skills_without_adoption(self):
        """This test will fail when a target installed before skills were managed refuses or mishandles hand-copied skills."""
        self.run_install(dry_run=False)
        manifest_path = self.target / self.install.MANIFEST_NAME
        earlier = json.loads(manifest_path.read_text())
        del earlier["skills"]
        manifest_path.write_text(json.dumps(earlier, indent=2) + "\n")
        identical, outdated = sorted(REPOSITORY_SKILLS)[0], sorted(REPOSITORY_SKILLS)[-1]
        outdated_path = self.target / "skills" / outdated / "SKILL.md"
        outdated_path.write_bytes(b"outdated hand copy\n")

        report = self.run_install(dry_run=False)

        self.assertEqual(json.loads(manifest_path.read_text())["skills"], sorted(REPOSITORY_SKILLS))
        self.assertEqual(outdated_path.read_bytes(), REPOSITORY_SKILLS[outdated])
        self.assertEqual(
            [path.read_bytes() for path in self.backups.rglob(f"skills/{outdated}/SKILL.md")],
            [b"outdated hand copy\n"],
        )
        if identical != outdated:
            self.assertNotIn(f"generated:skills/{identical}/SKILL.md", report)
            self.assertEqual(list(self.backups.rglob(f"skills/{identical}/SKILL.md")), [])

    def test_a_symlinked_skills_directory_is_refused_without_writing_through_it(self):
        """This test will fail when skills are written through a symlink to a directory outside the target."""
        outside = self.root / "outside"
        outside.mkdir()
        self.target.mkdir()
        (self.target / "skills").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(SystemExit, "Refusing"):
            self.run_install(dry_run=False, adopt=True)

        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.target / self.install.MANIFEST_NAME).exists())

    def test_interrupted_install_rolls_back_skill_writes_and_removals(self):
        """This test will fail when a failed install leaves a new skill behind or loses a removed one."""
        with generator_with_extra_skill(self.install, "retired-skill", b"retired skill\n"):
            self.run_install(dry_run=False)
        retired = self.target / "skills" / "retired-skill" / "SKILL.md"
        kept_name = sorted(REPOSITORY_SKILLS)[0]
        kept = self.target / "skills" / kept_name / "SKILL.md"
        kept.write_bytes(b"locally edited skill\n")
        manifest_path = self.target / self.install.MANIFEST_NAME
        manifest_before = manifest_path.read_bytes()

        original_unlink = Path.unlink

        def interrupt_removal(path, *args, **kwargs):
            if path == retired:
                raise KeyboardInterrupt("simulated interruption")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", interrupt_removal):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_install(dry_run=False)

        self.assertEqual(retired.read_bytes(), b"retired skill\n")
        self.assertEqual(kept.read_bytes(), b"locally edited skill\n")
        self.assertEqual(manifest_path.read_bytes(), manifest_before)


class OpenCodeInstallTimeoutTests(unittest.TestCase):
    def test_generator_timeout_is_finite_and_leaves_target_untouched(self):
        """This fails when a stalled repository generator can block installation indefinitely."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            sentinel = target / "sentinel.txt"
            sentinel.write_text("preserve me")
            calls = []

            def run(command, **kwargs):
                calls.append((command, kwargs))
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])

            with mock.patch.object(install.subprocess, "run", side_effect=run):
                with self.assertRaises(install.InstallTimeoutError) as raised:
                    install.install(target, dry_run=False, validate=False)

            self.assertEqual(calls[0][1]["timeout"], install.GENERATE_TIMEOUT_SECONDS)
            self.assertIn("OpenCode generator timed out", str(raised.exception))
            self.assertIn("no target files were changed", str(raised.exception))
            self.assertEqual(sentinel.read_text(), "preserve me")

    def test_config_validation_timeout_rolls_back_mutations_with_actionable_error(self):
        """This fails when a stalled config diagnostic leaves a partial installation behind."""
        install = load_install_module()
        generator = load_generate_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            config_path = target / "profiles" / "openai" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            original = json.dumps({"sentinel": "keep"})
            config_path.write_text(original)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            validation_calls = []

            def run(command, **kwargs):
                if command[:2] == [sys.executable, str(GENERATE)]:
                    output = Path(command[command.index("--output") + 1])
                    generator.generate(output)
                    return subprocess.CompletedProcess(command, 0)
                validation_calls.append((command, kwargs))
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])

            with mock.patch.object(install.subprocess, "run", side_effect=run):
                with mock.patch.object(Path, "home", return_value=fake_home):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(install.InstallTimeoutError) as raised:
                            install.install(target, dry_run=False, validate=True)

            self.assertEqual(
                validation_calls[0][0], ["opencode", "debug", "config"]
            )
            self.assertEqual(
                validation_calls[0][1]["timeout"],
                install.OPENCODE_CONFIG_TIMEOUT_SECONDS,
            )
            self.assertIn("opencode debug config", str(raised.exception))
            self.assertIn(str(config_path), str(raised.exception))
            self.assertIn("rolled back", str(raised.exception))
            self.assertEqual(config_path.read_text(), original)
            self.assertFalse((target / install.MANIFEST_NAME).exists())
            self.assertFalse((target / "agents" / "debugger.md").exists())


class OpenCodeInstallValidationTests(unittest.TestCase):
    def test_validation_checks_only_locally_configured_profiles(self):
        """REGRESSION CONTRACT: validate configured profiles only; TEST LAYER: installer integration test."""
        install = load_install_module()
        generator = load_generate_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated"
            target = root / "target"
            subprocess.run([sys.executable, str(GENERATE), "--output", str(generated)], check=True)
            generated_profiles = json.loads((generated / "manifest.json").read_text())["profiles"]
            self.assertIn("openai", generated_profiles)
            target.mkdir()
            profile = target / "profiles" / "glm"
            profile.mkdir(parents=True)
            (profile / "opencode.json").write_text(json.dumps({}))
            self.assertFalse((target / "profiles" / "openai" / "opencode.json").exists())

            validation_calls = []

            def run(command, **kwargs):
                if command[:2] == [sys.executable, str(GENERATE)]:
                    output = Path(command[command.index("--output") + 1])
                    generator.generate(output)
                else:
                    validation_calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(install.subprocess, "run", side_effect=run):
                fake_home = root / "fake-home"
                fake_home.mkdir()
                with mock.patch.object(Path, "home", return_value=fake_home):
                    with contextlib.redirect_stdout(io.StringIO()):
                        install.install(target, dry_run=False, validate=True)

            self.assertEqual(
                [call[0] for call in validation_calls],
                [["opencode", "debug", "config"]],
            )
            self.assertEqual(
                [call[1]["timeout"] for call in validation_calls],
                [install.OPENCODE_CONFIG_TIMEOUT_SECONDS],
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
