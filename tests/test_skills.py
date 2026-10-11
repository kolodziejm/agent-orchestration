"""Behavioral contracts for the shared skill source, bundle, and cleanup helpers."""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "harnesses" / "common.py"


def load_common():
    spec = importlib.util.spec_from_file_location("harness_common_for_skill_tests", COMMON)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load shared helpers from {COMMON}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_skill(root: Path, name: str, content: bytes) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


class SkillSourceTests(unittest.TestCase):
    def setUp(self):
        self.common = load_common()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / "skills"
        patcher = mock.patch.object(self.common, "SKILLS_ROOT", self.skills)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_repository_skills_are_discovered_from_their_directories(self):
        """This test will fail when discovery hardcodes names or misses a repository skill."""
        expected = {
            path.parent.name: path.read_bytes()
            for path in sorted((ROOT / "skills").glob("*/SKILL.md"))
        }
        self.assertTrue(expected)
        with mock.patch.object(self.common, "SKILLS_ROOT", ROOT / "skills"):
            self.assertEqual(self.common.skill_sources(), expected)

    def test_skills_are_copied_as_exact_bytes_in_name_order_and_hidden_entries_are_ignored(self):
        """This test will fail when discovery or the bundle copy reorders, rewrites, or trips over hidden files."""
        crlf = b"---\r\nname: zeta\r\n---\r\nbody \xe2\x86\x92 end"
        write_skill(self.skills, "zeta", crlf)
        write_skill(self.skills, "alpha-2", b"alpha\n")
        (self.skills / ".DS_Store").write_bytes(b"\x00finder")
        (self.skills / "zeta" / ".DS_Store").write_bytes(b"\x00finder")

        sources = self.common.skill_sources()
        output = self.root / "bundle"
        output.mkdir()
        names = self.common.write_skills(output)

        self.assertEqual(list(sources), ["alpha-2", "zeta"])
        self.assertEqual(sources["zeta"], crlf)
        self.assertEqual(names, ["alpha-2", "zeta"])
        self.assertEqual(
            {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            },
            {"skills/alpha-2/SKILL.md": b"alpha\n", "skills/zeta/SKILL.md": crlf},
        )
        self.assertEqual(self.common.read_bundle_skill(output, "zeta"), crlf)

    def test_a_repository_without_a_skills_directory_has_no_skills(self):
        """This test will fail when a checkout without skills/ stops generating a bundle."""
        output = self.root / "bundle"
        output.mkdir()

        self.assertEqual(self.common.skill_sources(), {})
        self.assertEqual(self.common.write_skills(output), [])
        self.assertFalse((output / "skills").exists())

    def test_undistributable_skill_sources_are_refused(self):
        """This test will fail when a skill a bundle cannot carry whole is silently dropped or truncated."""
        outside = self.root / "outside"
        write_skill(outside, "linked", b"linked\n")

        def stray_file():
            (self.skills / "notes.md").write_text("not a skill directory\n")

        def missing_skill_file():
            (self.skills / "empty").mkdir()

        def extra_file():
            write_skill(self.skills, "with-script", b"skill\n")
            (self.skills / "with-script" / "helper.py").write_text("print()\n")

        def unsafe_name():
            write_skill(self.skills, "Bad_Name", b"skill\n")

        def overlong_name():
            write_skill(self.skills, "a" * 65, b"skill\n")

        def linked_directory():
            (self.skills / "linked").symlink_to(outside / "linked", target_is_directory=True)

        def linked_skill_file():
            (self.skills / "linked").mkdir()
            (self.skills / "linked" / "SKILL.md").symlink_to(outside / "linked" / "SKILL.md")

        def not_utf8():
            write_skill(self.skills, "binary", b"\xff\xfe not text")

        for build in (
            stray_file, missing_skill_file, extra_file, unsafe_name, overlong_name,
            linked_directory, linked_skill_file, not_utf8,
        ):
            with self.subTest(case=build.__name__):
                self.skills.mkdir()
                write_skill(self.skills, "valid", b"valid\n")
                build()
                output = self.root / f"bundle-{build.__name__}"
                output.mkdir()
                with self.assertRaises(SystemExit):
                    self.common.write_skills(output)
                self.assertEqual(list(output.iterdir()), [])
                shutil.rmtree(self.skills)

    def test_a_regenerated_bundle_drops_a_skill_the_repository_no_longer_has(self):
        """This test will fail when in-place generation leaves a removed skill in the bundle."""
        write_skill(self.skills, "kept", b"kept v1\n")
        write_skill(self.skills, "dropped", b"dropped\n")
        output = self.root / "bundle"
        output.mkdir()
        (output / "config.yml").write_text("unrelated bundle file\n")
        self.assertEqual(self.common.write_skills(output), ["dropped", "kept"])

        shutil.rmtree(self.skills / "dropped")
        (self.skills / "kept" / "SKILL.md").write_bytes(b"kept v2\n")
        self.assertEqual(self.common.write_skills(output), ["kept"])

        self.assertEqual(
            sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()),
            ["config.yml", "skills/kept/SKILL.md"],
        )
        self.assertEqual((output / "skills" / "kept" / "SKILL.md").read_bytes(), b"kept v2\n")

    def test_a_linked_bundle_skills_directory_is_refused_without_following_it(self):
        """This test will fail when generation deletes or writes through a symlinked skills output."""
        write_skill(self.skills, "kept", b"kept\n")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "operator.txt").write_text("preserve\n")
        output = self.root / "bundle"
        output.mkdir()
        (output / "skills").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(SystemExit):
            self.common.write_skills(output)

        self.assertEqual([path.name for path in outside.iterdir()], ["operator.txt"])


class SkillDirectoryCleanupTests(unittest.TestCase):
    def test_only_the_empty_directory_of_a_removed_skill_file_is_removed(self):
        """This test will fail when cleanup deletes operator files, another skill, or skills/ itself."""
        common = load_common()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            emptied = target / "skills" / "emptied"
            emptied.mkdir(parents=True)
            occupied = target / "skills" / "occupied"
            occupied.mkdir()
            (occupied / "operator-notes.md").write_text("keep\n")
            foreign = write_skill(target / "skills", "foreign", b"foreign\n")
            agents = target / "agents"
            agents.mkdir()
            nested = target / "skills" / "group" / "nested"
            nested.mkdir(parents=True)

            common.remove_empty_skill_directories(
                [
                    emptied / "SKILL.md",
                    occupied / "SKILL.md",
                    agents / "retired-role.md",
                    nested / "SKILL.md",
                    target / "skills" / "never-installed" / "SKILL.md",
                ],
                target,
            )

            self.assertFalse(emptied.exists())
            self.assertEqual((occupied / "operator-notes.md").read_text(), "keep\n")
            self.assertEqual(foreign.read_bytes(), b"foreign\n")
            self.assertTrue(agents.is_dir())
            self.assertTrue(nested.is_dir())
            self.assertTrue((target / "skills").is_dir())


if __name__ == "__main__":
    unittest.main()
