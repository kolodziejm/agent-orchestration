import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policy" / "orchestration.md"
ROLE_CONTRACTS = {
    role: (ROOT / "roles" / f"{role}.md").read_text()
    for role in ("planner", "reviewer", "validator")
}


class OpenSpecRoutingPolicyTests(unittest.TestCase):
    def test_supported_renderers_preserve_the_global_openspec_rule(self):
        """This test will fail when an adapter omits policy or role-contract content."""
        policy = POLICY.read_text()
        start = policy.index("## OpenSpec orchestration")
        end = policy.index("\n## Proportional workflow", start)
        openspec_rule = policy[start:end]

        renderers = (
            (
                "opencode",
                [ROOT / "adapters" / "opencode" / "render.py"],
                "profiles/_shared/orchestration-core.md",
            ),
            (
                "codex",
                [ROOT / "adapters" / "codex" / "render.py", "--profile", "openai"],
                "AGENTS.md",
            ),
            (
                "claude-code",
                [ROOT / "adapters" / "claude-code" / "render.py"],
                "_shared/orchestration-core.md",
            ),
            (
                "pi-hybrid",
                [ROOT / "adapters" / "pi" / "render.py", "--profile", "hybrid"],
                "_shared/orchestration-core.md",
            ),
            (
                "pi-openai",
                [ROOT / "adapters" / "pi" / "render.py", "--profile", "openai"],
                "_shared/orchestration-core.md",
            ),
            (
                "pi-deepseek",
                [ROOT / "adapters" / "pi" / "render.py", "--profile", "deepseek"],
                "_shared/orchestration-core.md",
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, command, artifact in renderers:
                output = root / name
                result = subprocess.run(
                    [sys.executable, *map(str, command), "--output", str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, f"{name}: {result.stderr}")
                rendered = (output / artifact).read_text()
                self.assertIn(openspec_rule, rendered, name)

                for role, contract in ROLE_CONTRACTS.items():
                    role_artifact = output / "agents" / (
                        f"{role}.toml" if name == "codex" else f"{role}.md"
                    )
                    self.assertTrue(role_artifact.is_file(), f"{name}: {role}")
                    if name == "codex":
                        rendered_contract = tomllib.loads(
                            role_artifact.read_text()
                        )["developer_instructions"]
                        self.assertEqual(rendered_contract, contract, f"{name}: {role}")
                    else:
                        self.assertIn(contract, role_artifact.read_text(), f"{name}: {role}")


if __name__ == "__main__":
    unittest.main()
