import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "harnesses" / "omp" / "install.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("omp_install", INSTALL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(root: Path, profile="hybrid", agents=("planner", "worker"), text="first"):
    root.mkdir(parents=True, exist_ok=True)
    files = ["config.yml", *(f"agents/{role}.md" for role in agents)]
    (root / "config.yml").write_text(f"modelRoles:\n  default: {text}\n")
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


if __name__ == "__main__":
    unittest.main()
