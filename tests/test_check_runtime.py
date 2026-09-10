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
        "instructions": [
            str(target / "profiles" / "_shared" / "orchestration-core.md"),
            str(target / "profiles" / "openai" / "orchestration.md"),
        ],
    }
    config_path = target / "profiles" / "openai" / "opencode.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config))
    (target / "profiles" / "_shared").mkdir(parents=True)
    return config_path


class CheckRuntimeTests(unittest.TestCase):
    def test_check_runtime_accepts_synchronized_fixture_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opencode"
            config_path = runtime_fixture(target)
            before = config_path.read_bytes()

            result = subprocess.run(
                [
                    str(SCRIPT),
                    "--profile",
                    "openai",
                    "--config",
                    str(config_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("synchronized", result.stdout.lower())
            self.assertEqual(config_path.read_bytes(), before)

    def test_check_runtime_reports_actionable_drift_without_leaking_config_secrets(self):
        """This test will fail when runtime drift is missed or diagnostics dump sensitive config."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opencode"
            config_path = runtime_fixture(target)
            config = json.loads(config_path.read_text())
            config["model"] = "wrong/primary"
            config["apiKey"] = "SECRET_SHOULD_NOT_APPEAR"
            config_path.write_text(json.dumps(config))

            result = subprocess.run(
                [
                    str(SCRIPT),
                    "--profile",
                    "openai",
                    "--target",
                    str(target),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            output = result.stdout + result.stderr
            self.assertIn("primary model", output.lower())
            self.assertIn("openai/gpt-5.6-sol", output)
            self.assertIn("wrong/primary", output)
            self.assertNotIn("SECRET_SHOULD_NOT_APPEAR", output)


if __name__ == "__main__":
    unittest.main()
