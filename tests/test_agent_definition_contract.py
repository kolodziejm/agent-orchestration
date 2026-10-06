"""Cross-harness contract: every generated bundle contains agent definitions only.

The repository generates one bundle per harness (and per profile where a harness
has more than one). This module asserts the single invariant the reset defines:
each bundle carries exactly one definition per routing role, every definition
carries the model and reasoning effort resolved from its profile, and no bundle
carries orchestration policy, role-contract bodies, delegation fields, or global
instruction/workflow artifacts.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATORS = ROOT / "harnesses"
ROUTING = ROOT / "policy" / "routing.toml"

# Every generated target: bundle name, generator, extra arguments, and the
# profile whose model/effort values must appear in the definitions.
TARGETS = (
    ("opencode", "opencode", [], None),
    ("codex", "codex", ["--profile", "openai"], "openai"),
    ("claude-code", "claude-code", [], "claude"),
    ("pi/hybrid", "pi", ["--profile", "hybrid"], "hybrid"),
    ("pi/openai", "pi", ["--profile", "openai"], "openai"),
    ("pi/deepseek", "pi", ["--profile", "deepseek"], "deepseek"),
    ("pi/glm", "pi", ["--profile", "glm"], "pi-glm"),
    ("omp/hybrid", "omp", ["--profile", "hybrid"], "hybrid"),
    ("omp/openai", "omp", ["--profile", "openai"], "openai"),
    ("omp/deepseek", "omp", ["--profile", "deepseek"], "deepseek"),
    ("omp/glm", "omp", ["--profile", "glm"], "pi-glm"),
    ("dsh", "dsh", [], "dsh"),
)

# Definition keys each harness may emit. A key outside its whitelist is either a
# reintroduced delegation field or new policy surface.
AGENT_KEYS = {
    "opencode": {"description", "mode", "permission"},
    "codex": {"name", "description", "model", "model_reasoning_effort", "sandbox_mode"},
    "claude-code": {"name", "description", "tools", "model", "effort"},
    "pi": {
        "name",
        "description",
        "model",
        "thinking",
        "tools",
        "acceptanceRole",
        "defaultContext",
        "systemPromptMode",
        "inheritProjectContext",
        "inheritSkills",
    },
    "omp": {"name", "description", "model", "thinking-level", "tools"},
}

FORBIDDEN_TOKENS = (
    "delegates",
    "permission.task",
    "spawns",
    "maxDepth",
    "orchestration-core",
    "APPEND_SYSTEM",
)

FORBIDDEN_SUFFIXES = (
    "/AGENTS.md",
    "/CLAUDE.md",
    "/APPEND_SYSTEM.md",
    "/orchestration-core.md",
    "/adapter.md",
    "/degradations.md",
)

LANE_PATTERN = re.compile(r"^\s{12}- id: (lane-\S+)$", re.MULTILINE)


def load_toml(path: Path):
    with path.open("rb") as handle:
        return tomllib.load(handle)


def profile_models(profile_name: str) -> dict:
    return load_toml(ROOT / "profiles" / f"{profile_name}.toml")["models"]


def parse_scalar(value: str):
    if value == "":
        return {}
    if value.startswith("[") or value.startswith("{"):
        return json.loads(value)
    if value.startswith('"'):
        return json.loads(value)
    return value


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return the parsed frontmatter mapping and the bytes after the closing marker."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise AssertionError(f"Missing frontmatter start: {text[:40]!r}")
    end = lines.index("---", 1) if "---" in lines[1:] else -1
    if end < 0:
        raise AssertionError("Missing frontmatter end")
    metadata: dict = {}
    current: str | None = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") and current is not None:
            parent = metadata[current]
            if isinstance(parent, dict):
                key, _, value = line.strip().partition(":")
                parent[key] = parse_scalar(value.strip())
            continue
        key, _, value = line.partition(":")
        current = key
        metadata[key] = parse_scalar(value.strip())
    return metadata, "\n".join(lines[end + 1 :])


class AgentDefinitionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roles = load_toml(ROUTING)["roles"]
        cls.temp = tempfile.TemporaryDirectory()
        cls.outputs: dict[str, Path] = {}
        root = Path(cls.temp.name)
        for name, harness, extra, _profile in TARGETS:
            destination = root / name
            command = [
                sys.executable,
                str(GENERATORS / harness / "generate.py"),
                *extra,
                "--output",
                str(destination),
            ]
            subprocess.run(command, check=True, capture_output=True, cwd=ROOT)
            cls.outputs[name] = destination

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def bundle_files(self, name: str) -> list[str]:
        root = self.outputs[name]
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )

    def test_every_bundle_contains_exactly_one_definition_per_role(self):
        """This test will fail when a harness emits a retired artifact or drops a role definition."""
        for name, harness, _extra, _profile in TARGETS:
            with self.subTest(target=name):
                files = self.bundle_files(name)
                for relative in files:
                    self.assertFalse(
                        relative.endswith(FORBIDDEN_SUFFIXES)
                        or relative.startswith("workflows/")
                        or "/workflows/" in relative,
                        f"{name} emitted a retired artifact: {relative}",
                    )
                if harness == "dsh":
                    patch = (self.outputs[name] / "patch" / "cordis.patch.yml").read_text()
                    lanes = LANE_PATTERN.findall(patch)
                    self.assertEqual(set(lanes), {f"lane-{role}" for role in self.roles})
                    self.assertEqual(len(lanes), len(self.roles))
                    self.assertFalse((self.outputs[name] / "agents").exists())
                    continue
                suffix = ".toml" if harness == "codex" else ".md"
                definitions = [relative for relative in files if relative.startswith("agents/")]
                self.assertEqual(
                    set(definitions),
                    {f"agents/{role}{suffix}" for role in self.roles},
                    name,
                )
                self.assertEqual(len(definitions), len(self.roles), name)

    def test_definitions_carry_no_policy_or_delegation_bytes(self):
        """This test will fail when a role body or a delegation field returns to a definition."""
        for name, harness, _extra, _profile in TARGETS:
            if harness == "dsh":
                continue
            with self.subTest(target=name):
                for path in sorted((self.outputs[name] / "agents").iterdir()):
                    text = path.read_text()
                    for token in FORBIDDEN_TOKENS:
                        self.assertNotIn(token, text, f"{name}/{path.name}")

    def test_markdown_definitions_have_no_body_and_whitelisted_keys(self):
        """This test will fail when a definition grows a prompt body or a foreign key."""
        for name, harness, _extra, _profile in TARGETS:
            if harness in {"codex", "dsh"}:
                continue
            with self.subTest(target=name):
                for path in sorted((self.outputs[name] / "agents").iterdir()):
                    metadata, body = parse_frontmatter(path.read_text())
                    self.assertEqual(body, "", f"{name}/{path.name} has a body")
                    self.assertEqual(
                        set(metadata) - AGENT_KEYS[harness],
                        set(),
                        f"{name}/{path.name} carries unexpected keys",
                    )
                    self.assertTrue(metadata["description"], f"{name}/{path.name}")
                    if harness == "opencode":
                        self.assertEqual(metadata["mode"], "subagent")
                        self.assertIn("edit", metadata["permission"])
                        self.assertNotIn("task", metadata["permission"])

    def test_codex_definitions_expose_model_and_effort_without_prompt_bytes(self):
        """This test will fail when codex regains developer_instructions or loses routing."""
        root = self.outputs["codex"]
        models = profile_models("openai")
        for role in self.roles:
            with self.subTest(role=role):
                text = (root / "agents" / f"{role}.toml").read_text()
                self.assertNotIn("developer_instructions", text)
                document = tomllib.loads(text)
                self.assertEqual(set(document), AGENT_KEYS["codex"])
                self.assertEqual(document["name"], role)
                self.assertEqual(
                    document["model"], models[role]["model"].removeprefix("openai/")
                )
                expected = {"max": "xhigh"}.get(models[role]["variant"], models[role]["variant"])
                self.assertEqual(document["model_reasoning_effort"], expected)

    def test_model_and_effort_resolve_into_every_harness_carrier(self):
        """This test will fail when a harness stops projecting profile model/effort."""
        for name, harness, _extra, profile_name in TARGETS:
            if harness in {"codex", "dsh", "opencode"}:
                continue
            with self.subTest(target=name):
                models = profile_models(profile_name)
                root = self.outputs[name]
                for role in self.roles:
                    metadata, _body = parse_frontmatter(
                        (root / "agents" / f"{role}.md").read_text()
                    )
                    if harness == "omp":
                        self.assertEqual(metadata["model"], f"@{role}")
                        self.assertEqual(metadata["thinking-level"], models[role]["variant"])
                    elif harness == "claude-code":
                        self.assertTrue(metadata["model"])
                        self.assertEqual(metadata["effort"], models[role]["variant"])
                    else:
                        self.assertTrue(metadata["model"])
                        self.assertEqual(metadata["thinking"], models[role]["variant"])

    def test_opencode_model_configuration_stays_in_profile_carriers(self):
        """This test will fail when opencode loses its per-profile model carriers."""
        root = self.outputs["opencode"]
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertNotIn("workflows", manifest)
        self.assertEqual(manifest["roles"], sorted(self.roles))
        for profile_name in manifest["profiles"]:
            models = profile_models(profile_name)
            profile = load_toml(ROOT / "profiles" / f"{profile_name}.toml")
            routing = json.loads(
                (root / "profiles" / profile_name / "agent-routing.json").read_text()
            )
            control = json.loads(
                (root / "profiles" / profile_name / "control-plane.json").read_text()
            )
            self.assertEqual(set(routing["agent"]), set(self.roles))
            for role, expected in models.items():
                self.assertEqual(routing["agent"][role]["model"], expected["model"])
                self.assertEqual(
                    routing["agent"][role].get("variant"), expected.get("variant")
                )
            self.assertEqual(
                control["primary"]["model"], profile["control_plane"]["primary"]["model"]
            )

    def test_omp_bundle_drops_append_system_and_spawn_fields(self):
        """This test will fail when omp regains an instruction file or a spawn field."""
        root = self.outputs["omp/hybrid"]
        models = profile_models("hybrid")
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertNotIn("APPEND_SYSTEM.md", manifest["files"])
        self.assertFalse((root / "APPEND_SYSTEM.md").exists())
        for role, expected in models.items():
            metadata, body = parse_frontmatter((root / "agents" / f"{role}.md").read_text())
            self.assertEqual(body, "")
            self.assertEqual(metadata["thinking-level"], expected["variant"])
            self.assertNotIn("task", metadata["tools"])

    def test_claude_code_bundle_stays_definition_only(self):
        """This test will fail when claude-code regains an instruction artifact."""
        root = self.outputs["claude-code"]
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertNotIn("workflows", manifest)
        self.assertTrue((root / "_shared" / "control-plane.md").is_file())
        self.assertFalse((root / "_shared" / "orchestration-core.md").exists())
        self.assertFalse((root / "CLAUDE.md").exists())

    def test_dsh_lane_rows_carry_routing_without_persona_or_depth(self):
        """This test will fail when dsh lanes regain persona/depth or lose routing."""
        root = self.outputs["dsh"]
        patch = (root / "patch" / "cordis.patch.yml").read_text()
        models = profile_models("dsh")
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertNotIn("workflows", manifest)
        definitions = {
            match.group(1): match.group(0)
            for match in re.finditer(r"^\s{12}- id: (lane-\S+)$", patch, re.MULTILINE)
        }
        self.assertEqual(sorted(definitions), [f"lane-{role}" for role in sorted(self.roles)])
        for role in self.roles:
            with self.subTest(role=role):
                start = patch.index(definitions[f"lane-{role}"])
                following = [
                    patch.index(lane)
                    for lane in definitions.values()
                    if patch.index(lane) > start
                ]
                block = patch[start : min(following)] if following else patch[start:]
                self.assertNotIn("persona:", block)
                self.assertNotIn("maxDepth:", block)
                self.assertIn(f"reasoningEffort: {models[role]['variant']}", block)
                provider, model = models[role]["model"].split("/", 1)
                self.assertIn(f"provider: {provider}", block)
                self.assertIn(f"model: {model}", block)
                denies = block.split("deny:", 1)[1] if "deny:" in block else ""
                self.assertNotIn("subagent_", denies)


if __name__ == "__main__":
    unittest.main()
