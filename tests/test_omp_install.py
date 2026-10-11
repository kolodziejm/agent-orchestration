import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "harnesses" / "omp" / "install.py"
MANAGED_SECTION = (
    "<!-- agent-orchestration:start -->\n"
    + (ROOT / "policy" / "orchestration.md").read_text()
    + "<!-- agent-orchestration:end -->\n"
)
REPOSITORY_SKILLS = {
    path.parent.name: path.read_bytes() for path in sorted((ROOT / "skills").glob("*/SKILL.md"))
}


def load_installer():
    spec = importlib.util.spec_from_file_location("omp_install", INSTALL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(root: Path, profile="hybrid", agents=("planner", "worker"), text="first", skills=()):
    root.mkdir(parents=True, exist_ok=True)
    files = [
        "config.yml",
        *(f"agents/{role}.md" for role in agents),
        *(f"skills/{skill}/SKILL.md" for skill in skills),
    ]
    for skill in skills:
        path = root / "skills" / skill / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"skill {skill} {text}\r\n".encode())
    (root / "config.yml").write_text(f"modelRoles:\n  default: {text}\n")
    (root / "AGENTS.md").write_text(
        f"<!-- agent-orchestration:start -->\npolicy {text}\n<!-- agent-orchestration:end -->\n"
    )
    for role in agents:
        path = root / "agents" / f"{role}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"agent {role} {text}\n")
    (root / "manifest.json").write_text(json.dumps({"format_version": 1, "profile": profile, "files": files}))


class OmpInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installer = load_installer()
        self.bundle = self.root / "bundle"
        self.target = self.root / "profile" / "agent"
        bundle(self.bundle)

    def test_fresh_install_and_reinstall_updates_only_owned_files(self):
        """This test will fail when installation is not complete or a repeat changes unrelated state."""
        unrelated = self.target / "sessions" / "keep.json"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('{"keep":true}')
        self.installer.install("hybrid", self.target, generated=self.bundle)
        before = {p.relative_to(self.target): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        self.assertIn("modelRoles", (self.target / "config.yml").read_text())
        self.assertEqual(json.loads((self.target / self.installer.MANIFEST_NAME).read_text())["profile"], "hybrid")
        self.installer.install("hybrid", self.target, generated=self.bundle)
        after = {p.relative_to(self.target): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        bundle(self.bundle, agents=("planner",), text="updated")
        self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertFalse((self.target / "agents/worker.md").exists())
        self.assertEqual((self.target / "agents/planner.md").read_text(), "agent planner updated\n")
        self.assertEqual(unrelated.read_text(), '{"keep":true}')

    def test_first_install_collision_and_profile_mismatch_refuse_without_writes(self):
        """This test will fail when unmanaged bytes can be overwritten or another profile adopted."""
        claimed = self.target / "config.yml"
        claimed.parent.mkdir(parents=True)
        claimed.write_text("operator config\n")
        with self.assertRaises(SystemExit):
            self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertEqual(claimed.read_text(), "operator config\n")
        claimed.unlink()
        self.installer.install("hybrid", self.target, generated=self.bundle)
        manifest = self.target / self.installer.MANIFEST_NAME
        data = json.loads(manifest.read_text())
        data["profile"] = "openai"
        manifest.write_text(json.dumps(data))
        old = (self.target / "config.yml").read_bytes()
        bundle(self.bundle, profile="hybrid", text="changed")
        with self.assertRaises(SystemExit):
            self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertEqual((self.target / "config.yml").read_bytes(), old)

    def test_dry_run_does_not_create_target_and_symlink_escape_is_refused(self):
        """This test will fail when preview mutates the target or symlink destinations escape it."""
        self.installer.install("hybrid", self.target, dry_run=True, generated=self.bundle)
        self.assertFalse(self.target.exists())
        outside = self.root / "outside"
        outside.mkdir()
        self.target.mkdir(parents=True)
        (self.target / "agents").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SystemExit):
            self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertEqual(list(outside.iterdir()), [])

    def test_mid_write_failure_rolls_back_owned_and_unrelated_bytes(self):
        """This test will fail when a partial multi-file update survives an operation failure."""
        self.installer.install("hybrid", self.target, generated=self.bundle)
        unrelated = self.target / "operator.txt"
        unrelated.write_bytes(b"preserve")
        original = {p.relative_to(self.target): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        bundle(self.bundle, text="second")
        real_write = self.installer._atomic_write
        calls = 0

        def fail_second(path, content, mode):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated write failure")
            return real_write(path, content, mode)

        with mock.patch.object(self.installer, "_atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.installer.install("hybrid", self.target, generated=self.bundle)
        after = {p.relative_to(self.target): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(after, original)

    def test_install_appends_the_policy_to_a_user_owned_agents_md(self):
        """This test will fail when installing the policy changes user bytes, refuses a pre-existing file, or a repeat install writes again."""
        self.target.mkdir(parents=True)
        agents_md = self.target / "AGENTS.md"
        user_bytes = b"# My rules\r\n\r\nKeep answers short.\r\n"
        agents_md.write_bytes(user_bytes)

        with contextlib.redirect_stdout(io.StringIO()):
            self.installer.install("hybrid", self.target)
        installed = agents_md.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as second_out:
            self.installer.install("hybrid", self.target)

        self.assertEqual(installed, user_bytes + b"\n" + MANAGED_SECTION.encode())
        self.assertEqual(agents_md.read_bytes(), installed)
        self.assertIn("0 write(s), 0 removal(s)", second_out.getvalue())

    def test_previously_installed_append_system_is_removed(self):
        """This test will fail when a retired instruction artifact is left behind."""
        self.installer.install("hybrid", self.target, generated=self.bundle)
        append = self.target / "APPEND_SYSTEM.md"
        append.write_text("# Shared orchestration policy\noperator-visible policy bytes\n")
        manifest = self.target / self.installer.MANIFEST_NAME
        data = json.loads(manifest.read_text())
        self.assertNotIn("APPEND_SYSTEM.md", data["files"])
        data["files"] = sorted([*data["files"], "APPEND_SYSTEM.md"])
        manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

        self.installer.install("hybrid", self.target, generated=self.bundle)

        self.assertFalse(append.exists())
        installed = json.loads(manifest.read_text())
        self.assertNotIn("APPEND_SYSTEM.md", installed["files"])
        self.assertIn("modelRoles", (self.target / "config.yml").read_text())

    def test_legacy_append_system_is_removed_without_a_prior_manifest(self):
        """This test will fail when a retired instruction file survives an install with no prior manifest."""
        self.target.mkdir(parents=True)
        append = self.target / "APPEND_SYSTEM.md"
        append.write_text("# Shared orchestration policy\nlegacy bytes\n")
        unrelated = self.target / "operator.txt"
        unrelated.write_bytes(b"preserve")

        self.installer.install("hybrid", self.target, generated=self.bundle)

        self.assertFalse(append.exists())
        self.assertEqual(unrelated.read_bytes(), b"preserve")
        self.assertIn("modelRoles", (self.target / "config.yml").read_text())

    def test_malformed_manifest_and_unsafe_claims_fail_closed(self):
        """This test will fail when malformed prior ownership metadata authorizes deletion or overwrite."""
        self.installer.install("hybrid", self.target, generated=self.bundle)
        manifest = self.target / self.installer.MANIFEST_NAME
        data = json.loads(manifest.read_text())
        data["files"].append("../operator.txt")
        manifest.write_text(json.dumps(data))
        with self.assertRaises(SystemExit):
            self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertTrue((self.target / "agents/worker.md").exists())

    def tree(self) -> dict:
        return {
            path.relative_to(self.target): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }

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

    def test_generated_bundle_installs_each_repository_skill_beside_foreign_skills(self):
        """This test will fail when the real OMP bundle is installed without the repository skills, or a skill it does not own is touched."""
        self.assertTrue(REPOSITORY_SKILLS, "the repository ships at least one skill")
        foreign = self.foreign_skill_files()

        with contextlib.redirect_stdout(io.StringIO()):
            self.installer.install("hybrid", self.target)
        with contextlib.redirect_stdout(io.StringIO()) as second_out:
            self.installer.install("hybrid", self.target)

        for name, content in REPOSITORY_SKILLS.items():
            self.assertEqual((self.target / "skills" / name / "SKILL.md").read_bytes(), content)
        for path, content in foreign.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(
            sorted(path.name for path in (self.target / "skills").iterdir()),
            sorted([*REPOSITORY_SKILLS, "operator-skill", "loose-note.md"]),
        )
        claims = json.loads((self.target / self.installer.MANIFEST_NAME).read_text())["files"]
        self.assertEqual(
            [claim for claim in claims if claim.startswith("skills/")],
            [f"skills/{name}/SKILL.md" for name in sorted(REPOSITORY_SKILLS)],
        )
        self.assertIn("0 write(s), 0 removal(s)", second_out.getvalue())

    def test_dry_run_lists_every_skill_write_and_removal_without_changing_the_target(self):
        """This test will fail when a preview hides a skill write or removal, or performs it."""
        with contextlib.redirect_stdout(io.StringIO()) as fresh:
            self.installer.install("hybrid", self.target, dry_run=True)
        for name in REPOSITORY_SKILLS:
            self.assertIn(f"  write skills/{name}/SKILL.md", fresh.getvalue())
        self.assertFalse(self.target.exists())

        bundle(self.bundle, skills=("kept", "retired"))
        self.installer.install("hybrid", self.target, generated=self.bundle)
        before = self.tree()
        bundle(self.bundle, skills=("kept", "added"), text="second")
        with contextlib.redirect_stdout(io.StringIO()) as upgrade:
            self.installer.install("hybrid", self.target, dry_run=True, generated=self.bundle)
        self.assertIn("  write skills/added/SKILL.md", upgrade.getvalue())
        self.assertIn("  write skills/kept/SKILL.md", upgrade.getvalue())
        self.assertIn("  remove skills/retired/SKILL.md", upgrade.getvalue())
        self.assertEqual(self.tree(), before)

    def test_skill_dropped_from_a_later_bundle_is_removed_on_reinstall(self):
        """This test will fail when a deleted or renamed skill stays installed, or its removal reaches another skill."""
        foreign = self.foreign_skill_files()
        bundle(self.bundle, skills=("kept", "retired", "retired-with-notes"))
        self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertEqual(
            (self.target / "skills/retired/SKILL.md").read_bytes(), b"skill retired first\r\n"
        )
        notes = self.target / "skills" / "retired-with-notes" / "notes.md"
        notes.write_bytes(b"operator notes\n")

        bundle(self.bundle, skills=("kept",), text="second")
        self.installer.install("hybrid", self.target, generated=self.bundle)

        self.assertFalse((self.target / "skills" / "retired").exists())
        self.assertFalse((self.target / "skills/retired-with-notes/SKILL.md").exists())
        self.assertEqual(notes.read_bytes(), b"operator notes\n")
        self.assertEqual(
            (self.target / "skills/kept/SKILL.md").read_bytes(), b"skill kept second\r\n"
        )
        for path, content in foreign.items():
            self.assertEqual(path.read_bytes(), content)
        claims = json.loads((self.target / self.installer.MANIFEST_NAME).read_text())["files"]
        self.assertEqual(
            [claim for claim in claims if claim.startswith("skills/")], ["skills/kept/SKILL.md"]
        )

    def test_an_existing_skill_at_a_managed_name_is_refused_without_writes(self):
        """This test will fail when OMP overwrites an operator's same-named skill on a first install or an upgrade."""
        collision = self.target / "skills" / "kept" / "SKILL.md"
        collision.parent.mkdir(parents=True)
        collision.write_bytes(b"operator-written skill\n")
        bundle(self.bundle, skills=("kept",))
        with self.assertRaisesRegex(SystemExit, "collision") as first:
            self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertIn("skills/kept/SKILL.md", str(first.exception))
        self.assertEqual(self.tree(), {Path("skills/kept/SKILL.md"): b"operator-written skill\n"})

        collision.unlink()
        bundle(self.bundle)
        self.installer.install("hybrid", self.target, generated=self.bundle)
        collision.write_bytes(b"operator-written skill\n")
        before = self.tree()
        bundle(self.bundle, skills=("kept",), text="second")
        with self.assertRaisesRegex(SystemExit, "collision"):
            self.installer.install("hybrid", self.target, generated=self.bundle)
        self.assertEqual(self.tree(), before)

    def test_a_symlinked_skills_directory_is_refused_without_writing_through_it(self):
        """This test will fail when skills are written through a symlink to a directory outside the target."""
        outside = self.root / "outside"
        outside.mkdir()
        self.target.mkdir(parents=True)
        (self.target / "skills").symlink_to(outside, target_is_directory=True)
        bundle(self.bundle, skills=("kept",))

        with self.assertRaisesRegex(SystemExit, "symlink"):
            self.installer.install("hybrid", self.target, generated=self.bundle)

        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.target / self.installer.MANIFEST_NAME).exists())

    def test_mid_write_failure_rolls_back_skill_writes_and_removals(self):
        """This test will fail when a failed install leaves a new skill behind or loses a removed one."""
        bundle(self.bundle, skills=("kept", "retired"))
        self.installer.install("hybrid", self.target, generated=self.bundle)
        original = self.tree()
        bundle(self.bundle, skills=("added", "kept"), text="second")
        # Resolved, because the installer mutates resolved target paths.
        retired = (self.target / "skills" / "retired" / "SKILL.md").resolve()
        real_unlink = Path.unlink

        def fail_removal(path, *args, **kwargs):
            if path == retired:
                raise OSError("simulated removal failure")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", fail_removal):
            with self.assertRaisesRegex(OSError, "simulated removal failure"):
                self.installer.install("hybrid", self.target, generated=self.bundle)

        self.assertEqual(self.tree(), original)

    def test_skill_claims_outside_the_one_owned_file_shape_fail_closed(self):
        """This test will fail when a manifest can claim a skill path other than skills/<name>/SKILL.md."""
        for claim in (
            "skills/kept/notes.md",
            "skills/kept/nested/SKILL.md",
            "skills/SKILL.md",
            "skills/.hidden/SKILL.md",
            "skills/../agents/SKILL.md",
        ):
            with self.subTest(generated=claim):
                generated = self.root / "generated-claim"
                bundle(generated, skills=("kept",))
                manifest = json.loads((generated / "manifest.json").read_text())
                manifest["files"].append(claim)
                (generated / "manifest.json").write_text(json.dumps(manifest))
                target = self.root / "claim-target"
                with self.assertRaises(SystemExit):
                    self.installer.install("hybrid", target, generated=generated)
                self.assertFalse(target.exists())

        bundle(self.bundle, skills=("kept",))
        self.installer.install("hybrid", self.target, generated=self.bundle)
        manifest_path = self.target / self.installer.MANIFEST_NAME
        installed = manifest_path.read_text()
        for claim in ("skills/kept/notes.md", "skills/../agents/SKILL.md"):
            with self.subTest(installed=claim):
                data = json.loads(installed)
                data["files"].append(claim)
                manifest_path.write_text(json.dumps(data))
                before = self.tree()
                with self.assertRaises(SystemExit):
                    self.installer.install("hybrid", self.target, generated=self.bundle)
                self.assertEqual(self.tree(), before)


if __name__ == "__main__":
    unittest.main()
