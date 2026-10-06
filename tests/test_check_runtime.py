import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-runtime"


def runtime_fixture(target: Path) -> Path:
    with (ROOT / "policy" / "routing.toml").open("rb") as handle:
        routing = tomllib.load(handle)
    with (ROOT / "profiles" / "openai.toml").open("rb") as handle:
        profile = tomllib.load(handle)
    control = profile["control_plane"]
    agents = {
        role: dict(config) for role, config in profile["models"].items()
    }
    agents.update(
        {
            name: {"model": config["model"], "variant": config["effort"]}
            for name, config in control["builtins"].items()
        }
    )
    config = {
        "model": control["primary"]["model"],
        "variant": control["primary"]["effort"],
        "small_model": control["small_model"],
        "agent": agents,
    }
    config_path = target / "profiles" / "openai" / "opencode.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config))
    return config_path


def run_check_runtime(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class CheckRuntimeTests(unittest.TestCase):
    def test_check_runtime_accepts_synchronized_fixture_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opencode"
            config_path = runtime_fixture(target)
            before = config_path.read_bytes()

            result = run_check_runtime(
                ["--profile", "openai", "--config", str(config_path)]
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("synchronized", result.stdout.lower())
            self.assertEqual(config_path.read_bytes(), before)

    def test_legacy_instruction_registration_is_reported_as_drift(self):
        """This test will fail when a retired instruction path is silently accepted."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opencode"
            config_path = runtime_fixture(target)
            config = json.loads(config_path.read_text())
            config["instructions"] = [
                "/operator/notes.md",
                str(target / "profiles" / "_shared" / "orchestration-core.md"),
            ]
            config_path.write_text(json.dumps(config))

            result = run_check_runtime(
                ["--profile", "openai", "--config", str(config_path)]
            )

            self.assertNotEqual(result.returncode, 0)
            output = result.stdout + result.stderr
            self.assertIn("legacy instruction file is still registered", output)

    def test_check_runtime_reports_actionable_drift_without_leaking_config_secrets(self):
        """This test will fail when runtime drift is missed or diagnostics dump sensitive config."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opencode"
            config_path = runtime_fixture(target)
            config = json.loads(config_path.read_text())
            config["model"] = "wrong/primary"
            config["apiKey"] = "SECRET_SHOULD_NOT_APPEAR"
            config_path.write_text(json.dumps(config))

            result = run_check_runtime(
                ["--profile", "openai", "--target", str(target)]
            )

            self.assertNotEqual(result.returncode, 0)
            output = result.stdout + result.stderr
            self.assertIn("primary model", output.lower())
            self.assertIn("openai/gpt-6.1-sol", output)
            self.assertIn("wrong/primary", output)
            self.assertNotIn("SECRET_SHOULD_NOT_APPEAR", output)


if __name__ == "__main__":
    unittest.main()
