import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "adapters" / "pi" / "render.py"
INSTALL = ROOT / "adapters" / "pi" / "install.py"


def load_install_module():
    spec = importlib.util.spec_from_file_location("pi_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_pi_runtime(target: Path, version: str = "0.67.0") -> Path:
    package = target / "npm" / "node_modules" / "pi-subagents" / "package.json"
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text(json.dumps({"name": "pi-subagents", "version": version}) + "\n")
    return package


class PiInstallTests(unittest.TestCase):
    def test_first_install_requires_adoption_and_dry_run_never_mutates(self):
        """This test will fail when unmanaged role collisions can be overwritten implicitly."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "agent"
            collision = target / "agents" / "worker.md"
            collision.parent.mkdir(parents=True)
            collision.write_text("user worker\n")

            with self.assertRaisesRegex(SystemExit, "adoption required"):
                install.install(target, dry_run=True)
            self.assertEqual(collision.read_text(), "user worker\n")

            result = install.install(target, dry_run=True, adopt=True)
            self.assertEqual(result, 0)
            self.assertEqual(collision.read_text(), "user worker\n")
            self.assertFalse((target / ".agent-orchestration.pi-manifest.json").exists())

            unrelated_agent = target / "agents" / "user-specialist.md"
            unrelated_agent.write_text("user specialist\n")
            settings = target / "settings.json"
            settings.write_text(
                '{"packages":["user-package"],"extensions":["user.ts"]}\n'
            )
            fake_home = Path(directory) / "home"
            fake_home.mkdir()
            with mock.patch.object(Path, "home", return_value=fake_home):
                write_pi_runtime(target)
                install.install(target, dry_run=False, adopt=True)

                manifest_path = target / ".agent-orchestration.pi-manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["roles"].append("retired-role")
                manifest_path.write_text(json.dumps(manifest))
                stale = target / "agents" / "retired-role.md"
                stale.write_text("retired\n")
                collision.write_text("locally changed managed worker\n")
                install.install(target, dry_run=False)

            self.assertFalse(stale.exists())
            self.assertEqual(unrelated_agent.read_text(), "user specialist\n")
            self.assertEqual(
                settings.read_text(),
                '{"packages":["user-package"],"extensions":["user.ts"]}\n',
            )
            backup_roots = {
                path.parents[2]
                for path in (
                    fake_home / ".local" / "state" / "agent-orchestration" / "backups"
                ).rglob("agents/worker.md")
            }
            self.assertEqual(len(backup_roots), 2)

    def test_validation_failure_or_interruption_restores_the_exact_target_tree(self):
        """This test will fail when rollback leaves managed files or directories behind."""
        install = load_install_module()
        for error in (RuntimeError("invalid"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    fake_home = root / "home"
                    fake_home.mkdir()
                    target = root / "agent"
                    target.mkdir()
                    write_pi_runtime(target)
                    settings = target / "settings.json"
                    settings.write_text('{"packages":["user-package"],"extensions":["user.ts"]}\n')
                    before = sorted(
                        path.relative_to(target) for path in target.rglob("*")
                    )

                    with mock.patch.object(Path, "home", return_value=fake_home):
                        with mock.patch.object(
                            install, "validate_installed", side_effect=error
                        ):
                            with self.assertRaises(type(error)):
                                install.install(target, dry_run=False)

                    after = sorted(path.relative_to(target) for path in target.rglob("*"))
                    self.assertEqual(after, before)
                    self.assertEqual(
                        settings.read_text(),
                        '{"packages":["user-package"],"extensions":["user.ts"]}\n',
                    )

    def test_real_install_requires_supported_local_runtime_before_target_mutation(self):
        """This test will fail when invalid runtime metadata is accepted or checked too late."""
        install = load_install_module()
        cases = (
            ("absent", None, "Missing Pi runtime metadata"),
            ("malformed", "malformed", "Malformed Pi runtime metadata"),
            ("invalid-version", "not-semver", "Malformed Pi runtime metadata"),
            ("too-old", "0.66.9", "minimum supported version is 0.67.0"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, version, message in cases:
                with self.subTest(runtime=name):
                    fake_home = root / f"home-{name}"
                    fake_home.mkdir()
                    target = root / f"target-{name}"
                    target.mkdir()
                    sentinel = target / "user-file.txt"
                    sentinel.write_text("preserve me\n")
                    package = target / install.PI_RUNTIME_PACKAGE
                    if version == "malformed":
                        package.parent.mkdir(parents=True, exist_ok=True)
                        package.write_text("not json\n")
                    elif version is not None:
                        write_pi_runtime(target, version)

                    with mock.patch.object(Path, "home", return_value=fake_home):
                        with self.assertRaisesRegex(SystemExit, message):
                            install.install(target, dry_run=False)

                    self.assertEqual(sentinel.read_text(), "preserve me\n")
                    self.assertFalse(
                        (fake_home / ".local" / "state" / "agent-orchestration" / "backups").exists()
                    )

    def test_real_install_accepts_minimum_and_newer_runtime_releases(self):
        """This test will fail when the supported baseline is treated as an exact version."""
        install = load_install_module()
        for version in ("0.67.0", "1.2.3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fake_home = root / "home"
                fake_home.mkdir()
                target = root / "agent"
                target.mkdir()
                write_pi_runtime(target, version)

                with mock.patch.object(Path, "home", return_value=fake_home):
                    result = install.install(target, dry_run=False)

                self.assertEqual(result, 0)
                self.assertTrue((target / install.MANIFEST_NAME).is_file())
