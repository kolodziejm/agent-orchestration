"""Behavioral contracts for generated OMP profile bundles."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from harnesses.omp import generate as omp

ROOT = Path(__file__).resolve().parents[1]


class OmpGenerateTests(unittest.TestCase):
    def generate(self, profile: str, destination: Path) -> None:
        omp.generate(destination, profile)

    def test_generated_model_roles_and_agent_boundaries(self):
        """This test will fail when generated permissions or documented effort metadata diverge from their sources."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.generate("hybrid", root / "hybrid")
            self.generate("glm", root / "glm")
            hybrid = yaml.safe_load((root / "hybrid" / "config.yml").read_text())["modelRoles"]
            self.assertEqual(hybrid["default"], "openai-codex/gpt-6.1-sol:medium")
            self.assertEqual(hybrid["smol"], "deepseek/deepseek-flash")
            self.assertEqual(hybrid["plan"], "openai-codex/gpt-6.1-sol:high")
            self.assertEqual(hybrid["worker-complex"], "deepseek/deepseek-flash:max")
            glm = yaml.safe_load((root / "glm" / "config.yml").read_text())["modelRoles"]
            self.assertEqual(glm["default"], "zai/glm-5.3:high")
            self.assertEqual(glm["ux-critic"], "zai/glm-5.3-flash:high")
            manifest = json.loads((root / "glm" / "manifest.json").read_text())
            self.assertFalse(manifest["control_plane"]["build"]["installed"])
            source_models = omp.load(ROOT / "profiles" / omp.PROFILES["glm"][0])["models"]
            self.assertEqual(set(manifest["agents"]), set(omp.load(ROOT / "policy/routing.toml")["roles"]))
            for role in manifest["agents"]:
                content = (root / "glm" / "agents" / f"{role}.md").read_text()
                frontmatter, body = content[4:].split("\n---\n", 1)
                self.assertEqual(body, "")
                metadata = yaml.safe_load(frontmatter)
                self.assertEqual(
                    set(metadata),
                    {"name", "description", "model", "thinking-level", "tools"},
                )
                self.assertNotIn("spawns", metadata)
                self.assertNotIn("task", metadata["tools"])
                self.assertEqual("edit" in metadata["tools"], role in {"worker", "worker-complex"})
                self.assertEqual("bash" in metadata["tools"], role not in {"planner", "reviewer", "design-partner", "ux-critic"})
                self.assertEqual(metadata["model"], f"@{role}")
                self.assertEqual(metadata["thinking-level"], source_models[role]["variant"])
            self.assertNotIn("APPEND_SYSTEM.md", manifest["files"])

    def test_all_profiles_are_deterministic(self):
        """This test will fail when identical inputs generate different bundle bytes."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for profile in omp.PROFILES:
                left, right = root / "left" / profile, root / "right" / profile
                self.generate(profile, left)
                self.generate(profile, right)
                left_files = {p.relative_to(left): p.read_bytes() for p in left.rglob("*") if p.is_file()}
                right_files = {p.relative_to(right): p.read_bytes() for p in right.rglob("*") if p.is_file()}
                self.assertEqual(left_files, right_files)

    def test_malformed_models_and_source_names_fail_before_output(self):
        """This test will fail when malformed provider tokens or a misidentified source are accepted."""
        for value in ("anthropic/model", "deepseek//model", "zai/../model"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                omp.model_selector(value, {"deepseek", "zai"})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profiles").mkdir()
            (root / "policy").mkdir()
            shutil.copy(ROOT / "policy/routing.toml", root / "policy/routing.toml")
            shutil.copy(ROOT / "profiles/hybrid.toml", root / "profiles/hybrid.toml")
            source = (root / "profiles/hybrid.toml").read_text().replace('name = "hybrid"', 'name = "openai"')
            (root / "profiles/hybrid.toml").write_text(source)
            with patch.object(omp, "ROOT", root), self.assertRaises(SystemExit):
                self.generate("hybrid", root / "output")
            self.assertFalse((root / "output").exists())

    def test_unsafe_output_is_rejected(self):
        """This test will fail when generation accepts a destination outside build/ or the temporary root."""
        with self.assertRaises(SystemExit):
            self.generate("openai", ROOT / "README.md")


if __name__ == "__main__":
    unittest.main()
