import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "adapters/pi/extensions/primary-policy.js"


class PiPrimaryPolicyTests(unittest.TestCase):
    def invoke(self, root: Path, prompt: str = "base", child: bool = False) -> dict:
        extension = root / "extensions/agent-orchestration/primary-policy.js"
        script = f"""
import extension from {json.dumps(extension.as_uri())};
const handlers = {{}};
const notices = [];
extension({{ on(name, callback) {{ handlers[name] = callback; }} }});
const result = handlers.before_agent_start(
  {{ systemPrompt: {json.dumps(prompt)} }},
  {{ ui: {{ notify(message, level) {{ notices.push([message, level]); }} }} }},
);
console.log(JSON.stringify({{ result: result ?? null, notices }}));
"""
        env = os.environ.copy()
        env["PI_CODING_AGENT_DIR"] = str(root)
        if child:
            env["PI_SUBAGENT_CHILD"] = "1"
        else:
            env.pop("PI_SUBAGENT_CHILD", None)
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def profile(self, policy: bytes = b"# Installed policy\n") -> Path:
        root = Path(tempfile.mkdtemp())
        extension_dir = root / "extensions/agent-orchestration"
        extension_dir.mkdir(parents=True)
        shutil.copy2(SOURCE, extension_dir / SOURCE.name)
        (extension_dir / "package.json").write_text('{"type":"module"}\n')
        shared = root / "agent-orchestration/_shared"
        shared.mkdir(parents=True)
        (shared / "orchestration-core.md").write_bytes(policy)
        return root

    def test_primary_reads_exact_installed_bytes_and_caches_them(self):
        policy = "# Fixture π\r\n\r\nkeep exact bytes\r\n".encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extension_dir = root / "extensions/agent-orchestration"
            extension_dir.mkdir(parents=True)
            shutil.copy2(SOURCE, extension_dir / SOURCE.name)
            (extension_dir / "package.json").write_text('{"type":"module"}\n')
            shared = root / "agent-orchestration/_shared"
            shared.mkdir(parents=True)
            policy_path = shared / "orchestration-core.md"
            policy_path.write_bytes(policy)
            script = f"""
import extension, {{ PRIMARY_POLICY_START, PRIMARY_POLICY_END }} from {json.dumps((extension_dir / SOURCE.name).as_uri())};
const handlers = {{}};
extension({{ on(name, callback) {{ handlers[name] = callback; }} }});
const first = handlers.before_agent_start({{ systemPrompt: "base" }}, {{}});
const fs = await import("node:fs");
fs.writeFileSync({json.dumps(str(policy_path))}, "changed\\n");
const second = handlers.before_agent_start({{ systemPrompt: "base" }}, {{}});
console.log(JSON.stringify({{ first, second, start: PRIMARY_POLICY_START, end: PRIMARY_POLICY_END }}));
"""
            env = os.environ.copy()
            env["PI_CODING_AGENT_DIR"] = str(root)
            env.pop("PI_SUBAGENT_CHILD", None)
            completed = subprocess.run(
                ["node", "--input-type=module", "--eval", script],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(completed.stdout)
            expected = (
                "base\n\n"
                + payload["start"]
                + "\n"
                + policy.decode()
                + payload["end"]
            )
            self.assertEqual(payload["first"]["systemPrompt"], expected)
            self.assertEqual(payload["second"]["systemPrompt"], expected)

    def test_child_is_a_no_op_and_existing_marker_prevents_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.profile()
            try:
                child = self.invoke(root, child=True)
                self.assertIsNone(child["result"])
                self.assertEqual(child["notices"], [])

                marked = "before\n\n<!-- agent-orchestration:primary-policy:start -->\nexisting"
                duplicate = self.invoke(root, prompt=marked)
                self.assertIsNone(duplicate["result"])
                self.assertEqual(duplicate["notices"], [])
            finally:
                shutil.rmtree(root)

    def test_invalid_policy_inputs_fail_closed_without_sensitive_diagnostics(self):
        cases = {
            "missing": lambda root: None,
            "empty": lambda root: (root / "agent-orchestration/_shared/orchestration-core.md").write_bytes(b" \n"),
            "oversize": lambda root: (root / "agent-orchestration/_shared/orchestration-core.md").write_bytes(b"x" * (256 * 1024 + 1)),
            "invalid-utf8": lambda root: (root / "agent-orchestration/_shared/orchestration-core.md").write_bytes(b"# valid prefix\xff\n"),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                root = self.profile()
                try:
                    if name == "missing":
                        (root / "agent-orchestration/_shared/orchestration-core.md").unlink()
                    else:
                        mutate(root)
                    result = self.invoke(root)
                    self.assertIsNone(result["result"])
                    self.assertEqual(result["notices"], [[
                        "agent-orchestration: primary policy unavailable", "error",
                    ]])
                    self.assertNotIn(str(root), json.dumps(result))
                finally:
                    shutil.rmtree(root)

        for name, linked_target in (
            ("linked", Path("outside.md")),
            ("escaping-directory", Path("outside-dir")),
        ):
            with self.subTest(case=name):
                root = self.profile()
                try:
                    outside = root.parent / linked_target
                    if name == "linked":
                        outside.write_bytes(b"outside\n")
                        policy = root / "agent-orchestration/_shared/orchestration-core.md"
                        policy.unlink()
                        policy.symlink_to(outside)
                    else:
                        outside.mkdir()
                        (outside / "orchestration-core.md").write_bytes(b"outside\n")
                        shared = root / "agent-orchestration/_shared"
                        shared.rename(root / "agent-orchestration/_shared-real")
                        shared.symlink_to(outside)
                    result = self.invoke(root)
                    self.assertIsNone(result["result"])
                    self.assertEqual(result["notices"], [[
                        "agent-orchestration: primary policy unavailable", "error",
                    ]])
                    self.assertNotIn(str(outside), json.dumps(result))
                finally:
                    shutil.rmtree(root)
                    if outside.is_dir():
                        shutil.rmtree(outside)
                    else:
                        outside.unlink(missing_ok=True)

    def test_profile_bundle_registration_is_primary_first_and_preserves_status_and_git_reader(self):
        expected_status = {
            "hybrid": "./deepseek-price-status.js",
            "openai": "./codex-pace-loader.ts",
            "deepseek": "./deepseek-price-status.js",
            "glm": "./glm-price-status.js",
        }
        for profile, status in expected_status.items():
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / profile
                completed = subprocess.run(
                    [
                        "python3", str(ROOT / "adapters/pi/render.py"),
                        "--profile", profile, "--output", str(output),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(completed.returncode, 0)
                package = json.loads(
                    (output / "extensions/agent-orchestration/package.json").read_text()
                )
                expected = ["./primary-policy.js"]
                if status:
                    expected.append(status)
                expected.append("./git-read.ts")
                self.assertEqual(package["pi"]["extensions"], expected)
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertIn(
                    "extensions/agent-orchestration/primary-policy.js",
                    manifest["managed_extensions"],
                )
                self.assertEqual(
                    (output / "extensions/agent-orchestration/primary-policy.js").read_bytes(),
                    SOURCE.read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
