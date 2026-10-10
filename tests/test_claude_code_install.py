import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GENERATE = ROOT / "harnesses" / "claude-code" / "generate.py"
INSTALL = ROOT / "harnesses" / "claude-code" / "install.py"
MARKER_START = "<!-- agent-orchestration:start -->"
MARKER_END = "<!-- agent-orchestration:end -->"
MANAGED_SECTION = (
    MARKER_START + "\n" + (ROOT / "policy" / "orchestration.md").read_text() + MARKER_END + "\n"
)


def load_install_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("claude_code_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClaudeCodeInstallPlanTests(unittest.TestCase):
    def test_install_writes_definitions_and_a_truthful_control_plane_note(self):
        """This test will fail when Claude installation ships a retired instruction artifact or claims primary control."""
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

            files, deletions = install.desired_state(generated, target, adopt=True)
            self.assertNotIn(target / "workflows" / "feature-workflow-pilot.md", files)
            self.assertIn(target / "agents" / "worker.md", files)
            self.assertNotIn(target / "agents" / "_shared", files)
            self.assertIn(target / "_shared" / "orchestration-core.md", deletions)

            control_note = target / "_shared" / "control-plane.md"
            self.assertIn(control_note, files)
            self.assertIn("cannot install the primary", files[control_note].lower())

            manifest = json.loads(files[target / install.MANIFEST_NAME])
            self.assertNotIn("workflows", manifest)
            self.assertFalse(manifest["control_plane"])

    def test_install_replaces_a_managed_claude_md_section_in_place(self):
        """This test will fail when an upgrade rewrites user bytes around the managed section or leaves old policy bytes behind."""
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

            target.mkdir()
            before = "# My notes\n\nSome unrelated content.\n\n"
            after = "\n\n## Notes after the section\n"
            (target / "CLAUDE.md").write_text(
                f"{before}{MARKER_START}\nold policy bytes\n{MARKER_END}{after}"
            )
            (target / "_shared").mkdir()
            (target / "_shared" / "orchestration-core.md").write_text("legacy core\n")

            files, deletions = install.desired_state(generated, target, adopt=True)
            self.assertEqual(
                files[target / "CLAUDE.md"], before + MANAGED_SECTION.rstrip("\n") + after
            )
            self.assertIn(target / "_shared" / "orchestration-core.md", deletions)
            self.assertNotIn(target / "CLAUDE.md", deletions)

            second_target = root / "second-target"
            second_target.mkdir()
            second_files, _ = install.desired_state(generated, second_target, adopt=True)
            self.assertEqual(second_files[second_target / "CLAUDE.md"], MANAGED_SECTION)

    def test_install_appends_the_policy_to_a_user_owned_claude_md(self):
        """This test will fail when installing the policy changes user bytes, needs adoption, or a repeat install writes again."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            target = root / "target"
            target.mkdir()
            claude_md = target / "CLAUDE.md"
            user_bytes = b"# My rules\r\n\r\nKeep answers short.\r\n"
            claude_md.write_bytes(user_bytes)

            with mock.patch.object(Path, "home", return_value=fake_home):
                with contextlib.redirect_stdout(io.StringIO()):
                    install.install(target, dry_run=False)
                installed = claude_md.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()) as second_out:
                    install.install(target, dry_run=False)

            self.assertEqual(installed, user_bytes + b"\n" + MANAGED_SECTION.encode())
            self.assertEqual(claude_md.read_bytes(), installed)
            self.assertIn("already synchronized", second_out.getvalue())

    def test_malformed_managed_markers_refuse_the_install_without_writes(self):
        """This test will fail when the installer rewrites an instruction file whose managed bytes it cannot identify."""
        install = load_install_module()
        for content in (
            f"before\n{MARKER_START}\nno end marker here\n",
            f"{MARKER_END}\nstuff\n{MARKER_START}\n",
            f"{MARKER_START}\nmanaged\n{MARKER_END}\n" * 2,
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fake_home = root / "fake-home"
                fake_home.mkdir()
                target = root / "target"
                target.mkdir()
                claude_md = target / "CLAUDE.md"
                claude_md.write_text(content)

                with mock.patch.object(Path, "home", return_value=fake_home):
                    with contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(SystemExit, "malformed"):
                            install.install(target, dry_run=False)

                self.assertEqual(claude_md.read_text(), content)
                self.assertEqual(list(target.iterdir()), [claude_md])

    def test_first_install_leaves_a_user_owned_claude_md_untouched(self):
        """This test will fail when a dry run changes or refuses an unmarked user instruction file."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            claude_md = target / "CLAUDE.md"
            claude_md.write_text("user-owned instructions\n")

            result = subprocess.run(
                [sys.executable, str(INSTALL), "--target", str(target), "--dry-run"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(claude_md.read_text(), "user-owned instructions\n")

    def test_first_install_reports_unmanaged_role_collision_until_adopted(self):
        """This test will fail when first install overwrites a managed-name file without adoption."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            role_path = target / "agents" / "worker.md"
            role_path.parent.mkdir(parents=True)
            role_path.write_text("user-owned role\n")

            result = subprocess.run(
                [sys.executable, str(INSTALL), "--target", str(target), "--dry-run"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(role_path), result.stderr)
            self.assertIn("--adopt", result.stderr)
            self.assertEqual(role_path.read_text(), "user-owned role\n")

    def test_stale_managed_roles_are_removed_and_unrelated_agents_survive(self):
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
                "profiles": ["claude"],
            }
            target.mkdir()
            (target / install.MANIFEST_NAME).write_text(json.dumps(previous))
            (target / "agents").mkdir(parents=True)
            (target / "agents" / "obsolete-managed-role.md").write_text("stale")
            (target / "agents" / "custom-agent.md").write_text("keep me")

            files, deletions = install.desired_state(generated, target)
            self.assertIn(target / "agents" / "worker.md", files)
            self.assertIn(target / "agents" / "obsolete-managed-role.md", deletions)
            self.assertNotIn(target / "agents" / "custom-agent.md", deletions)

    def test_unsafe_profile_name_in_installed_manifest_is_rejected_before_mutation(self):
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
            target.mkdir()
            unsafe_manifest = {"format_version": 1, "roles": [], "profiles": ["../../x"]}
            manifest_bytes = json.dumps(unsafe_manifest).encode()
            (target / install.MANIFEST_NAME).write_bytes(manifest_bytes)

            with self.assertRaises(SystemExit):
                install.desired_state(generated, target)

            self.assertEqual(
                (target / install.MANIFEST_NAME).read_bytes(),
                manifest_bytes,
            )
            self.assertEqual(list(target.iterdir()), [target / install.MANIFEST_NAME])

    def test_symlinked_destination_is_rejected(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            secret = root / "private.txt"
            secret.write_text("TOP_SECRET_SHOULD_NOT_APPEAR")
            (target / "agents").mkdir(parents=True)
            (target / "agents" / "worker.md").symlink_to(secret)

            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--target",
                    str(target),
                    "--dry-run",
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
            (target / "agents").mkdir(parents=True)
            explorer = target / "agents" / "explorer.md"
            explorer.write_text("original notes\n")
            original_bytes = explorer.read_bytes()

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
                            install.install(target, dry_run=False, adopt=True)

            self.assertEqual(explorer.read_bytes(), original_bytes)
            self.assertFalse((target / install.MANIFEST_NAME).exists())
            backups_root = fake_home / ".local" / "state" / "agent-orchestration" / "backups"
            self.assertTrue(backups_root.exists())
            backed_up = list(backups_root.rglob("explorer.md"))
            self.assertEqual(len(backed_up), 1)
            self.assertEqual(backed_up[0].read_bytes(), original_bytes)

    def test_second_install_is_idempotent_and_reports_already_synchronized(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            target = root / "target"
            target.mkdir()

            with mock.patch.object(Path, "home", return_value=fake_home):
                with contextlib.redirect_stdout(io.StringIO()) as first_out:
                    first_result = install.install(target, dry_run=False)
                with contextlib.redirect_stdout(io.StringIO()) as second_out:
                    second_result = install.install(target, dry_run=False)

            self.assertEqual(first_result, 0)
            self.assertEqual(second_result, 0)
            self.assertNotIn("already synchronized", first_out.getvalue())
            self.assertIn("already synchronized", second_out.getvalue())

    def test_preexisting_unmanaged_role_file_is_overwritten_and_backed_up(self):
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            target = root / "target"
            (target / "agents").mkdir(parents=True)
            user_written = "# My own explorer notes\nDo not touch.\n"
            (target / "agents" / "explorer.md").write_text(user_written)

            with mock.patch.object(Path, "home", return_value=fake_home):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = install.install(target, dry_run=False, adopt=True)

            self.assertEqual(result, 0)
            managed_content = (target / "agents" / "explorer.md").read_text()
            self.assertNotEqual(managed_content, user_written)

            backups_root = fake_home / ".local" / "state" / "agent-orchestration" / "backups"
            backed_up = list(backups_root.rglob("explorer.md"))
            self.assertEqual(len(backed_up), 1)
            self.assertEqual(backed_up[0].read_text(), user_written)

    def test_backups_use_unique_directories_when_installs_share_a_timestamp(self):
        """This test will fail when two Claude Code backups collide in one timestamp directory."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            target = root / "target"
            (target / "agents").mkdir(parents=True)
            explorer = target / "agents" / "explorer.md"
            explorer.write_text("user notes\n")

            fixed = mock.Mock()
            fixed.strftime.return_value = "20260101T000000Z"
            fake_datetime = mock.Mock()
            fake_datetime.now.return_value = fixed

            with mock.patch.object(Path, "home", return_value=fake_home):
                with mock.patch.object(install, "datetime", fake_datetime):
                    install.install(target, dry_run=False, adopt=True)
                    explorer.write_text("changed user notes\n")
                    install.install(target, dry_run=False)

            backups = list(
                (fake_home / ".local" / "state" / "agent-orchestration" / "backups").rglob(
                    "explorer.md"
                )
            )
            self.assertEqual(len(backups), 2)
            self.assertEqual(len({path.parents[2].name for path in backups}), 2)


if __name__ == "__main__":
    unittest.main()
