"""Behavioral contracts for the DeepSeek Harness installer."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "harnesses" / "dsh" / "install.py"
GENERATE = ROOT / "harnesses" / "dsh" / "generate.py"
MANIFEST_NAME = ".agent-orchestration.manifest.json"


class _LoaderExpression(str):
    """The Cordis `!!js` loader expression, retained as text."""


class _DshLoader(yaml.SafeLoader):
    """Isolated loader: other test modules also claim the Cordis `!!js` tag."""


_DshLoader.add_constructor(
    "tag:yaml.org,2002:js",
    lambda loader, node: _LoaderExpression(loader.construct_scalar(node)),
)


def load_yaml(text: str):
    return yaml.load(text, Loader=_DshLoader)


def load_installer():
    spec = importlib.util.spec_from_file_location("dsh_install", INSTALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installer module from {INSTALL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DshInstallContractTests(unittest.TestCase):
    def setUp(self):
        self.installer = load_installer()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.home_env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.home_env.start()
        self.addCleanup(self.home_env.stop)
        self.target = self.root / "dsh"

    def bundle(self, destination: Path | None = None, shell: str = "bash") -> Path:
        generated = destination or (self.root / "generated")
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATE),
                "--output",
                str(generated),
                "--shell",
                shell,
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return generated

    def run_install(self, dry_run: bool = False, adopt: bool = False, shell: str = "bash"):
        """Run the installer with its unified diff suppressed."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.installer.install(self.target, dry_run, adopt, shell)
        return code, buffer.getvalue()

    @staticmethod
    def lane_rows(rows: list) -> list:
        found = []
        for row in rows:
            if row["id"].startswith("lane-"):
                found.append(row)
            nested = row.get("config")
            if isinstance(nested, list):
                found.extend(DshInstallContractTests.lane_rows(nested))
        return found

    def read_patch(self, target: Path | None = None) -> str:
        return ((target or self.target) / "cordis.patch.yml").read_text()

    def test_dry_run_reports_changes_without_writing_anything(self):
        """REGRESSION CONTRACT: a dry run creates no target artifact; TEST LAYER: installer integration test."""
        self.assertEqual(self.run_install(dry_run=True)[0], 0)
        self.assertFalse(self.target.exists())

    def test_fresh_install_writes_the_patch_and_control_plane_note_only(self):
        """REGRESSION CONTRACT: a fresh install writes the preset patch and the recorded intent; TEST LAYER: installer integration test."""
        self.assertEqual(self.run_install()[0], 0)

        manifest = json.loads((self.target / MANIFEST_NAME).read_text())
        self.assertEqual(manifest["presets"], ["agent-orchestration"])
        self.assertEqual(len(manifest["roles"]), 9)
        self.assertNotIn("workflows", manifest)
        self.assertTrue((self.target / ".agent-orchestration" / "control-plane.md").is_file())
        self.assertFalse((self.target / ".agent-orchestration" / "adapter.md").exists())
        self.assertFalse((self.target / ".agent-orchestration" / "agents").exists())
        self.assertFalse((self.target / "AGENTS.md").exists())

        patch = self.read_patch()
        self.assertEqual(patch.count("# agent-orchestration:start"), 1)
        self.assertEqual(patch.count("# agent-orchestration:end"), 1)
        self.assertEqual(patch.count("- id: lane-"), 9)
        document = load_yaml(patch)
        self.assertEqual(len(document), 1)
        self.assertEqual(list(document[0]), ["insert"])
        config = document[0]["insert"][0]["config"]
        self.assertEqual(config["id"], "agent-orchestration")
        self.assertEqual(len(config["plugins"]), 19)
        self.assertEqual(len(self.lane_rows(config["plugins"])), 9)

    def test_reinstall_is_idempotent(self):
        """REGRESSION CONTRACT: a second install changes no bytes; TEST LAYER: installer idempotency test."""
        self.run_install()
        before = {
            path.relative_to(self.target): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(self.run_install()[0], 0)
        after = {
            path.relative_to(self.target): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_unmanaged_collision_requires_adopt_and_preserves_user_content(self):
        """REGRESSION CONTRACT: first install refuses collisions, then preserves unmanaged content; TEST LAYER: adoption test."""
        self.target.mkdir()
        user_agents = "# Operator notes\n\nKeep this.\n"
        user_patch = "# Operator patch\n- id: operator-row\n  disabled: true\n"
        (self.target / "AGENTS.md").write_text(user_agents)
        (self.target / "cordis.patch.yml").write_text(user_patch)

        with self.assertRaises(SystemExit) as caught:
            self.run_install()
        self.assertIn("--adopt", str(caught.exception))
        self.assertEqual((self.target / "AGENTS.md").read_text(), user_agents)
        self.assertEqual((self.target / "cordis.patch.yml").read_text(), user_patch)
        self.assertFalse((self.target / MANIFEST_NAME).exists())

        self.assertEqual(self.run_install(adopt=True)[0], 0)
        agents_md = (self.target / "AGENTS.md").read_text()
        self.assertEqual(agents_md, user_agents)
        patch = self.read_patch()
        self.assertTrue(patch.startswith(user_patch))
        self.assertEqual(patch.count("- id: lane-"), 9)
        self.assertEqual(len(load_yaml(patch)), 2)

    def test_reinstall_replaces_the_managed_block_without_duplicating_it(self):
        """REGRESSION CONTRACT: reinstalling after a generated change keeps exactly one managed block; TEST LAYER: merge test."""
        self.run_install()
        before = self.read_patch()
        self.assertEqual(self.run_install(shell="pwsh")[0], 0)
        after = self.read_patch()

        self.assertEqual(after.count("# agent-orchestration:start"), 1)
        self.assertEqual(after.count("- id: lane-"), 9)
        self.assertIn("        - pwsh\n", after)
        self.assertNotIn("        - pwsh\n", before)
        self.assertEqual(len(load_yaml(after)), 1)

    def test_stale_managed_files_are_removed_and_unrelated_files_survive(self):
        """REGRESSION CONTRACT: the manifest, not the directory, owns deletions; TEST LAYER: lifecycle test."""
        self.run_install()
        managed_root = self.target / ".agent-orchestration"
        retired = managed_root / "agents" / "retired-role.md"
        retired.parent.mkdir(parents=True, exist_ok=True)
        retired.write_text("retired\n")
        adapter = managed_root / "adapter.md"
        adapter.write_text("retired adapter\n")
        unrelated = managed_root / "operator-notes.md"
        unrelated.write_text("unmanaged\n")
        manifest_path = self.target / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text())
        manifest["roles"] = manifest["roles"] + ["retired-role"]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        self.assertEqual(self.run_install(adopt=True)[0], 0)

        self.assertFalse(retired.exists())
        self.assertFalse(adapter.exists())
        self.assertTrue(unrelated.is_file())
        self.assertTrue((managed_root / "control-plane.md").is_file())

    def test_agents_md_is_stripped_and_dangling_markers_are_left_alone(self):
        """REGRESSION CONTRACT: only the marker-delimited block is removed; TEST LAYER: migration test."""
        self.target.mkdir()
        marker_start = "<!-- agent-orchestration:start -->"
        marker_end = "<!-- agent-orchestration:end -->"
        (self.target / MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "roles": [],
                    "profiles": ["dsh"],
                    "presets": ["agent-orchestration"],
                    "control_plane": False,
                }
            )
        )
        user_prefix = "# Operator notes\n\nKeep this.\n"
        (self.target / "AGENTS.md").write_text(
            f"{user_prefix}\n{marker_start}\nold policy\n{marker_end}\n"
        )

        self.assertEqual(self.run_install(adopt=True)[0], 0)

        agents_md = (self.target / "AGENTS.md").read_text()
        self.assertIn("# Operator notes", agents_md)
        self.assertIn("Keep this.", agents_md)
        self.assertNotIn(marker_start, agents_md)
        self.assertNotIn("old policy", agents_md)

        dangling = f"before\n{marker_start}\nno end marker\n"
        (self.target / "AGENTS.md").write_text(dangling)
        self.assertEqual(self.run_install()[0], 0)
        self.assertEqual((self.target / "AGENTS.md").read_text(), dangling)

    def test_a_patch_block_missing_a_lane_is_refused(self):
        """REGRESSION CONTRACT: the installer validates the generated patch block; TEST LAYER: failure test."""
        generated = self.bundle()
        patch = generated / "patch" / "cordis.patch.yml"
        lines = [line for line in patch.read_text().split("\n") if "lane-ux-critic" not in line]
        patch.write_text("\n".join(lines))

        with self.assertRaises(SystemExit) as caught:
            self.installer.desired_state(generated, self.target, adopt=True)
        self.assertIn("role lanes", str(caught.exception))

    def test_a_symlinked_managed_file_is_refused(self):
        """REGRESSION CONTRACT: a symlinked destination is never followed; TEST LAYER: path-safety test."""
        self.target.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "patch.yml").write_text("outside\n")
        (self.target / "cordis.patch.yml").symlink_to(outside / "patch.yml")

        with self.assertRaises(SystemExit) as caught:
            self.run_install(adopt=True)
        self.assertIn("Refusing", str(caught.exception))
        self.assertEqual((outside / "patch.yml").read_text(), "outside\n")

    def test_a_failed_write_rolls_every_changed_file_back(self):
        """REGRESSION CONTRACT: any write failure restores every original byte; TEST LAYER: rollback test."""
        self.target.mkdir()
        (self.target / "AGENTS.md").write_text("# Operator notes\n")
        original_patch = "# Operator patch\n"
        (self.target / "cordis.patch.yml").write_text(original_patch)
        agents_before = (self.target / "AGENTS.md").read_text()

        real_write = self.installer.write_text
        calls = {"count": 0}

        def fail_second(path, content, mode=None):
            calls["count"] += 1
            if calls["count"] == 3:
                raise RuntimeError("simulated failure")
            return real_write(path, content, mode)

        with mock.patch.object(self.installer, "write_text", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.run_install(adopt=True)

        self.assertEqual((self.target / "AGENTS.md").read_text(), agents_before)
        self.assertEqual((self.target / "cordis.patch.yml").read_text(), original_patch)
        self.assertFalse((self.target / MANIFEST_NAME).exists())

    def test_unknown_cli_flags_exit_two(self):
        """REGRESSION CONTRACT: a retired flag fails loudly instead of being ignored; TEST LAYER: CLI test."""
        result = subprocess.run(
            [sys.executable, str(INSTALL), "--base-composition", "x"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
