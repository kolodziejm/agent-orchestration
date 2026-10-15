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
REPOSITORY_SKILLS = {
    path.parent.name: path.read_bytes() for path in sorted((ROOT / "skills").glob("*/SKILL.md"))
}


def repository_skill_files() -> dict[str, bytes]:
    """Every supporting file a repository skill carries, relative to `skills/`, in
    bundle order: by skill name, then by path inside the skill. Hidden entries and
    bytecode caches are never distributed."""
    files: dict[str, bytes] = {}
    for name in REPOSITORY_SKILLS:
        directory = ROOT / "skills" / name
        for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
            relative = path.relative_to(directory)
            if (
                path.is_file()
                and relative.as_posix() != "SKILL.md"
                and not any(part.startswith(".") or part == "__pycache__" for part in relative.parts)
            ):
                files[f"{name}/{relative.as_posix()}"] = path.read_bytes()
    return files


REPOSITORY_SKILL_FILES = repository_skill_files()


def load_install_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("claude_code_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def generator_with_extra_skill(install, name: str, content: bytes, files: dict[str, bytes] | None = None):
    """Make the installer's generator emit one skill the repository does not have,
    with optional supporting files, as an earlier repository version that still
    shipped it would."""
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        bundle = Path(command[command.index("--output") + 1])
        skill = bundle / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(content)
        for relative, data in (files or {}).items():
            supporting = skill.parent / relative
            supporting.parent.mkdir(parents=True, exist_ok=True)
            supporting.write_bytes(data)
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["skills"] = sorted([*manifest["skills"], name])
        manifest["skill_files"] = [
            *manifest.get("skill_files", []),
            *(f"{name}/{relative}" for relative in sorted(files or {})),
        ]
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return result

    with mock.patch.object(install.subprocess, "run", side_effect=run):
        yield


class ClaudeCodeSkillInstallTests(unittest.TestCase):
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
                self.install.install(self.target, **kwargs)
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
        for relative, content in REPOSITORY_SKILL_FILES.items():
            self.assertEqual((self.target / "skills" / relative).read_bytes(), content)
        manifest = json.loads((self.target / self.install.MANIFEST_NAME).read_text())
        self.assertEqual(manifest["skills"], sorted(REPOSITORY_SKILLS))
        self.assertEqual(manifest["skill_files"], list(REPOSITORY_SKILL_FILES))
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

    def test_supporting_skill_files_are_installed_and_removed_with_their_skill(self):
        """This test will fail when a supporting skill file is skipped, outlives its dropped skill, leaves an emptied directory, or its removal reaches an operator file."""
        supporting = {"scripts/run.py": b"print('run')\r\n", "assets/deep/viewer.html": b"<p>view</p>\n"}
        with generator_with_extra_skill(self.install, "retired-skill", b"retired skill\n", supporting):
            self.run_install(dry_run=False)
        skill_dir = self.target / "skills" / "retired-skill"
        for relative, content in supporting.items():
            self.assertEqual((skill_dir / relative).read_bytes(), content)
        manifest_path = self.target / self.install.MANIFEST_NAME
        self.assertIn(
            "retired-skill/assets/deep/viewer.html",
            json.loads(manifest_path.read_text())["skill_files"],
        )
        operator = skill_dir / "scripts" / "operator.py"
        operator.write_bytes(b"operator\n")

        preview = self.run_install(dry_run=True)
        self.assertIn("deleted:skills/retired-skill/scripts/run.py", preview)
        self.assertIn("deleted:skills/retired-skill/assets/deep/viewer.html", preview)

        self.run_install(dry_run=False)

        self.assertFalse((skill_dir / "SKILL.md").exists())
        self.assertFalse((skill_dir / "scripts" / "run.py").exists())
        self.assertFalse((skill_dir / "assets").exists())
        self.assertEqual(operator.read_bytes(), b"operator\n")
        self.assertEqual(json.loads(manifest_path.read_text())["skill_files"], list(REPOSITORY_SKILL_FILES))
        backed_up = list(self.backups.rglob("skills/retired-skill/scripts/run.py"))
        self.assertEqual([path.read_bytes() for path in backed_up], [b"print('run')\r\n"])

    def test_first_install_reports_a_supporting_skill_file_collision_until_adopted(self):
        """This test will fail when a first install overwrites an operator file at a supporting skill path without adoption, or trusts an unsafe manifest claim."""
        collision = self.target / "skills" / "extra-skill" / "scripts" / "run.py"
        collision.parent.mkdir(parents=True)
        collision.write_bytes(b"operator script\n")
        with generator_with_extra_skill(
            self.install, "extra-skill", b"extra\n", {"scripts/run.py": b"bundled\n"}
        ):
            with self.assertRaises(SystemExit) as refused:
                self.run_install(dry_run=False)
            self.assertIn(str(collision), str(refused.exception))
            self.assertEqual(collision.read_bytes(), b"operator script\n")

            self.run_install(dry_run=False, adopt=True)
        self.assertEqual(collision.read_bytes(), b"bundled\n")

        manifest_path = self.target / self.install.MANIFEST_NAME
        tampered = json.loads(manifest_path.read_text())
        tampered["skill_files"].append("extra-skill/../../agents/worker.md")
        manifest_path.write_text(json.dumps(tampered, indent=2) + "\n")
        before = manifest_path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "skill_files"):
            self.run_install(dry_run=False)
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(collision.read_bytes(), b"bundled\n")

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
        earlier.pop("skill_files", None)
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
