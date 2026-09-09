import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "adapters" / "claude-code" / "render.py"
INSTALL = ROOT / "adapters" / "claude-code" / "install.py"


def load_install_module():
    spec = importlib.util.spec_from_file_location("claude_code_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClaudeCodeInstallPlanTests(unittest.TestCase):
    def test_merge_preserves_unrelated_claude_md_and_removes_stale_managed_roles(self):
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
                "profiles": ["claude"],
            }
            target.mkdir()
            (target / install.MANIFEST_NAME).write_text(json.dumps(previous))
            (target / "agents").mkdir(parents=True)
            (target / "agents" / "obsolete-managed-role.md").write_text("stale")
            (target / "agents" / "custom-agent.md").write_text("keep me")

            unrelated = "# My notes\n\nSome unrelated content.\n"
            managed = (rendered / "_shared" / "orchestration-core.md").read_text()
            (target / "CLAUDE.md").write_text(unrelated + "\n" + managed)

            files, deletions = install.desired_state(rendered, target)
            claude_md = files[target / "CLAUDE.md"]
            self.assertIn(unrelated.strip(), claude_md)
            self.assertIn("<!-- agent-orchestration:start -->", claude_md)
            self.assertEqual(claude_md.count("<!-- agent-orchestration:start -->"), 1)
            self.assertIn(target / "agents" / "worker.md", files)
            self.assertIn(target / "agents" / "obsolete-managed-role.md", deletions)
            self.assertNotIn(target / "agents" / "custom-agent.md", deletions)

    def test_appends_managed_section_when_claude_md_has_no_markers(self):
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
            target.mkdir()
            (target / "CLAUDE.md").write_text("# Project notes\n\nExisting content.\n")

            files, _ = install.desired_state(rendered, target)
            claude_md = files[target / "CLAUDE.md"]
            self.assertIn("Existing content.", claude_md)
            self.assertIn("<!-- agent-orchestration:start -->", claude_md)

    def test_merge_rejects_dangling_start_marker(self):
        install = load_install_module()
        existing = f"before\n{install.MARKER_START}\nno end marker here\n"
        with self.assertRaises(SystemExit):
            install.merge_claude_md(existing, "section")

    def test_merge_rejects_dangling_end_marker(self):
        install = load_install_module()
        existing = f"before\n{install.MARKER_END}\nno start marker here\n"
        with self.assertRaises(SystemExit):
            install.merge_claude_md(existing, "section")

    def test_merge_rejects_two_complete_marker_pairs(self):
        install = load_install_module()
        pair = f"{install.MARKER_START}\nmanaged\n{install.MARKER_END}\n"
        existing = pair + pair
        with self.assertRaises(SystemExit):
            install.merge_claude_md(existing, "section")

    def test_merge_rejects_end_before_start(self):
        install = load_install_module()
        existing = f"{install.MARKER_END}\nstuff\n{install.MARKER_START}\n"
        with self.assertRaises(SystemExit):
            install.merge_claude_md(existing, "section")

    def test_unsafe_profile_name_in_installed_manifest_is_rejected_before_mutation(self):
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
            target.mkdir()
            unsafe_manifest = {"format_version": 1, "roles": [], "profiles": ["../../x"]}
            manifest_bytes = json.dumps(unsafe_manifest).encode()
            (target / install.MANIFEST_NAME).write_bytes(manifest_bytes)

            with self.assertRaises(SystemExit):
                install.desired_state(rendered, target)

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
            target.mkdir(parents=True)
            claude_md = target / "CLAUDE.md"
            claude_md.write_text("original notes\n")
            original_bytes = claude_md.read_bytes()

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
                            install.install(target, dry_run=False)

            self.assertEqual(claude_md.read_bytes(), original_bytes)
            self.assertFalse((target / install.MANIFEST_NAME).exists())
            backups_root = fake_home / ".local" / "state" / "agent-orchestration" / "backups"
            self.assertTrue(backups_root.exists())
            backed_up = list(backups_root.rglob("CLAUDE.md"))
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

    def test_merge_of_empty_existing_yields_exactly_the_managed_section(self):
        install = load_install_module()
        section = f"{install.MARKER_START}\nmanaged\n{install.MARKER_END}\n"
        self.assertEqual(install.merge_claude_md("", section), section)

    def test_merge_without_trailing_newline_does_not_glue_existing_and_section(self):
        install = load_install_module()
        section = f"{install.MARKER_START}\nmanaged\n{install.MARKER_END}\n"
        result = install.merge_claude_md("notes", section)
        self.assertTrue(result.startswith("notes\n"))
        self.assertEqual(result.splitlines()[0], "notes")
        self.assertIn(section, result)

    def test_merge_is_idempotent_for_content_outside_markers(self):
        install = load_install_module()
        section = f"{install.MARKER_START}\nmanaged v1\n{install.MARKER_END}\n"
        existing = "# Notes\n\nSome unrelated content.\n"
        once = install.merge_claude_md(existing, section)
        twice = install.merge_claude_md(once, section)
        self.assertEqual(once, twice)

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
                    result = install.install(target, dry_run=False)

            self.assertEqual(result, 0)
            managed_content = (target / "agents" / "explorer.md").read_text()
            self.assertNotEqual(managed_content, user_written)

            backups_root = fake_home / ".local" / "state" / "agent-orchestration" / "backups"
            backed_up = list(backups_root.rglob("explorer.md"))
            self.assertEqual(len(backed_up), 1)
            self.assertEqual(backed_up[0].read_text(), user_written)


if __name__ == "__main__":
    unittest.main()
