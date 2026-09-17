import importlib.util
import io
import json
import os
import subprocess
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


def write_deepseek_source(root: Path) -> Path:
    settings = {
        "defaultProvider": "openai-codex",
        "defaultModel": "gpt-source",
        "defaultThinkingLevel": "medium",
        "lastChangelogVersion": "0.67.0",
        "theme": "source-theme",
        "externalEditor": "fixture-editor",
        "tuiMode": "compact",
        "treeFilterMode": "directories",
        "doubleEscapeAction": "clear-input",
        "terminal": "fixture-terminal",
        "subagents": {"enabled": True, "maxChildren": 3},
        "packages": [
            "npm:pi-web-access",
            "npm:pi-subagents@0.67.0",
            "npm:@gotgenes/pi-permission-system@31.1.3",
            {"source": "npm:@erichll/pi-auto-review@0.17.0", "autoload": False,
             "extensions": ["src/index.ts"]},
            "./local/pi-sandbox",
        ],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "settings.json").write_text(json.dumps(settings) + "\n")
    (root / "themes").mkdir()
    (root / "themes/source-theme.json").write_text(
        '{"name":"source-theme","colors":{"accent":"#fff"}}\n'
    )
    (root / "mcp.json").write_text(json.dumps({
        "mcpServers": {
            "deepseek-fixture": {
                "command": "synthetic-deepseek-mcp",
                "env": {"DEEPSEEK_MCP_TOKEN": "deepseek-mcp-secret"},
            },
        },
        "adapterOwnedTopLevel": {"preserve": "exactly"},
    }, indent=2) + "\n")
    (root / "models-store.json").write_text(json.dumps({
        "deepseek": {
            "baseUrl": "https://api.deepseek.com",
            "api": "openai-completions",
            "compat": {"thinkingFormat": "deepseek"},
            "models": [{
                "id": "deepseek-flash",
                "name": "DeepSeek V4.1 Flash",
                "reasoning": True,
                "thinkingLevelMap": {"low": "low", "high": "high", "max": "max"},
                "input": ["text", "image"],
                "contextWindow": 1000000,
                "maxTokens": 384000,
                "cost": {"input": 0.2, "output": 0.8, "cacheRead": 0.02, "cacheWrite": 0.2},
            }],
            "checkedAt": 1700000000000,
            "lastModified": 1700000000000,
            "etag": "synthetic-deepseek-etag",
        }
    }) + "\n")
    packages = {
        "pi-web-access": ("pi-web-access", "1.0.0"),
        "pi-subagents": ("pi-subagents", "0.67.0"),
        "@gotgenes/pi-permission-system": ("@gotgenes/pi-permission-system", "31.1.3"),
        "@erichll/pi-auto-review": ("@erichll/pi-auto-review", "0.17.0"),
    }
    for relative, (name, version) in packages.items():
        manifest = root / "npm" / "node_modules" / relative / "package.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"name": name, "version": version, "pi": {"extensions": ["index.ts"]}}) + "\n")
        # Pi's autoloader invokes every declared extension as a factory. Keep
        # fixture package entrypoints valid under the installed runtime rather
        # than masking startup failures with production changes.
        (manifest.parent / "index.ts").write_text("export default function fixtureExtension() {}\n")
    local = root / "local" / "pi-sandbox"
    local.mkdir(parents=True)
    (local / "package.json").write_text(json.dumps({"name": "@erichll/pi-sandbox", "version": "0.17.1", "pi": {"extensions": ["index.ts"]}}) + "\n")

    managed = {
        "subagent/config.json": {"scheduledRuns": {"enabled": False}},
        "pi-sandbox/config.json": {"subagents": {"provider": "off"}},
        "pi-permission-system/config.json": {
            "piInfrastructureReadPaths": ["~/.pi/agent/*"],
            "permission": {"read": "allow"},
        },
        "pi-permission-system/package.json": {
            "name": "@gotgenes/pi-permission-system-bridge",
            "private": True,
            "pi": {"extensions": [str(root / "npm/node_modules/@gotgenes/pi-permission-system/index.ts")]},
        },
        "pi-auto-review/config.json": {
            "model": "openai-codex/gpt-source", "reasoning": "low"
        },
    }
    for relative, content in managed.items():
        path = root / "extensions" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content) + "\n")
    return root


def remove_sandbox_from_deepseek_source(source: Path) -> None:
    settings_path = source / "settings.json"
    settings = json.loads(settings_path.read_text())
    settings["packages"] = [
        entry
        for entry in settings["packages"]
        if (entry if isinstance(entry, str) else entry["source"]) != "./local/pi-sandbox"
    ]
    settings_path.write_text(json.dumps(settings) + "\n")
    (source / "extensions/pi-sandbox/config.json").unlink()


class PiInstallTests(unittest.TestCase):
    def test_installed_status_package_rejects_the_opposite_profile_entrypoint(self):
        """Installed validation must reject a package that selects the other provider's status."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            target = root / "hybrid"
            write_pi_runtime(target)
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="hybrid")
            package_path = target / "extensions/agent-orchestration/package.json"
            package_path.write_text(json.dumps({
                "type": "module",
                "pi": {"extensions": ["./codex-pace-loader.ts"]},
            }) + "\n")
            manifest = json.loads((target / install.MANIFEST_NAME).read_text())
            files = {
                path: path.read_text()
                for path in install.managed_paths(manifest, target)
                if path.is_file()
            }
            with self.assertRaisesRegex(RuntimeError, "status extension package"):
                install.validate_installed(files, target)

    def test_normal_launchers_autoload_only_their_profile_status_extension(self):
        """A normal generated launcher must discover its installed status package without -e."""
        pi = Path.home() / ".nvm/versions/node/v24.15.0/bin/pi"
        node = pi.with_name("node")
        if not pi.is_file() or not node.is_file():
            self.skipTest("Pi 0.85.1 launcher runtime is unavailable")
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            bin_dir = root / "bin"
            deepseek_source = write_deepseek_source(root / "deepseek-source")
            cases = (
                ("hybrid", root / "hybrid", None,
                 "agent-orchestration-deepseek-price", "agent-orchestration-codex-pace"),
                ("deepseek", root / "deepseek", deepseek_source,
                 "agent-orchestration-deepseek-price", "agent-orchestration-codex-pace"),
            )
            for profile, target, profile_source, expected, rejected in cases:
                with self.subTest(profile=profile), mock.patch.object(
                    Path, "home", return_value=fake_home
                ):
                    if profile == "hybrid":
                        write_pi_runtime(target)
                    install.install(
                        target, dry_run=False, profile=profile, source=profile_source,
                        bin_dir=bin_dir,
                    )
                env = os.environ.copy()
                env.update({
                    "AGENT_ORCHESTRATION_PI_EXECUTABLE": str(pi),
                    "AGENT_ORCHESTRATION_NODE_EXECUTABLE": str(node),
                    "PI_OFFLINE": "1",
                })
                result = subprocess.run(
                    [
                        str(bin_dir / f"pi-{profile}"), "--mode", "rpc", "--no-session",
                        "--offline", "--no-skills", "--no-prompt-templates", "--no-themes",
                        "--no-context-files",
                    ],
                    cwd=ROOT,
                    env=env,
                    input='{"type":"get_state"}\n',
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                status_keys = {
                    event.get("statusKey")
                    for event in events
                    if event.get("method") == "setStatus"
                }
                self.assertIn(expected, status_keys, result.stdout)
                self.assertNotIn(rejected, status_keys, result.stdout)

    def test_git_reader_is_manifest_owned_and_explorer_only_in_every_installed_profile(self):
        """REGRESSION CONTRACT: installation must load only the explorer Git reader and reject lifecycle tampering."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            cases = {
                "hybrid": (root / "hybrid", None),
                "deepseek": (root / "deepseek", write_deepseek_source(root / "deepseek-source")),
                "glm": (root / "glm", None),
            }
            for profile, (target, source) in cases.items():
                with self.subTest(profile=profile), mock.patch.object(Path, "home", return_value=fake_home):
                    if profile in {"hybrid", "glm"}:
                        write_pi_runtime(target)
                    install.install(target, dry_run=False, profile=profile, source=source)
                reader = target / "extensions/agent-orchestration/git-read.ts"
                primary = target / "extensions/agent-orchestration/primary-policy.js"
                package = json.loads((target / "extensions/agent-orchestration/package.json").read_text())
                manifest = json.loads((target / install.MANIFEST_NAME).read_text())
                self.assertTrue(reader.is_file())
                self.assertTrue(primary.is_file())
                self.assertIn("extensions/agent-orchestration/git-read.ts", manifest["managed_extensions"])
                self.assertIn("extensions/agent-orchestration/primary-policy.js", manifest["managed_extensions"])
                self.assertIn("./git-read.ts", package["pi"]["extensions"])
                self.assertIn("./primary-policy.js", package["pi"]["extensions"])
                self.assertEqual(package["pi"]["extensions"][0], "./primary-policy.js")
                explorer = (target / "agents/explorer.md").read_text()
                self.assertIn("acceptanceRole: read-only", explorer)
                self.assertEqual(
                    [line for line in explorer.splitlines() if line.startswith("acceptanceRole:")],
                    ["acceptanceRole: read-only"],
                )
                self.assertIn("tools: read, grep, find, ls, git_read", explorer)
                self.assertNotIn("tools: read, grep, find, ls, git_read, bash", explorer)
                for role in manifest["roles"]:
                    role_content = (target / "agents" / f"{role}.md").read_text()
                    if role != "explorer":
                        self.assertNotIn("acceptanceRole:", role_content)
                        self.assertNotIn("git_read", role_content)

            target, _source = cases["hybrid"]
            manifest_path = target / install.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text())
            manifest_path.write_text(json.dumps(manifest) + "\n")
            explorer_path = target / "agents/explorer.md"
            explorer_original = explorer_path.read_text()
            for tampered in (
                explorer_original.replace("acceptanceRole: read-only\n", ""),
                explorer_original.replace("acceptanceRole: read-only", "acceptanceRole: writer"),
            ):
                explorer_path.write_text(tampered)
                tampered_files = {
                    path: path.read_text()
                    for path in install.managed_paths(manifest, target)
                    if path.is_file()
                }
                with self.assertRaisesRegex(RuntimeError, "acceptanceRole"):
                    install.validate_installed(tampered_files, target)
            explorer_path.write_text(explorer_original)
            (target / "extensions/agent-orchestration/git-read.ts").unlink()
            files = {
                path: path.read_text()
                for path in install.managed_paths(manifest, target)
                if path.is_file()
            }
            with self.assertRaisesRegex(RuntimeError, "Git reader|child-only extension"):
                install.validate_installed(files, target)

    def test_hybrid_install_preserves_operator_settings_and_auth(self):
        """A hybrid install preserves operator settings and never copies source credentials."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            (source / "auth.json").write_text('{"deepseek":{"apiKey":"must-not-copy"}}\n')
            target = root / "hybrid"
            target.mkdir()
            write_pi_runtime(target)
            settings = target / "settings.json"
            settings.write_text('{"theme":"keep","packages":["user-package"]}\n')

            with mock.patch.object(Path, "home", return_value=fake_home):
                result = install.install(
                    target, dry_run=False, profile="hybrid", source=source,
                )

            self.assertEqual(result, 0)
            self.assertEqual(settings.read_text(), '{"theme":"keep","packages":["user-package"]}\n')
            self.assertFalse((target / "auth.json").exists())

    def test_deepseek_install_preserves_unrelated_catalog_entries(self):
        """Operator-owned catalog entries survive installation unchanged."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            target = root / "deepseek"
            target.mkdir()
            existing = {
                "user-provider": {"api": "openai-completions", "models": [{"id": "user-model"}]},
                "deepseek": {
                    "baseUrl": "https://api.deepseek.com",
                    "api": "openai-completions",
                    "checkedAt": 1800000000000, "lastModified": 1800000000000, "etag": "target-etag", "models": [{
                    "id": "deepseek-flash", "name": "DeepSeek V4.1 Flash (local newer)",
                    "reasoning": True,
                    "thinkingLevelMap": {"low": "low", "high": "high", "max": "max"},
                    "input": ["text", "image"],
                    "contextWindow": 2000000,
                    "maxTokens": 512000,
                }]},
            }
            catalog = target / "models-store.json"
            catalog.write_text(json.dumps(existing) + "\n")
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, adopt=True, profile="deepseek", source=source)
            configured = json.loads(catalog.read_text())
            self.assertEqual(configured["user-provider"], existing["user-provider"])

    def test_deepseek_install_never_copies_source_credentials(self):
        """Operator credentials remain private across installation."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            (source / "auth.json").write_text('{"deepseek":{"apiKey":"secret"}}\n')
            target = root / "deepseek"
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="deepseek", source=source)
            self.assertFalse((target / "auth.json").exists())

    def test_deepseek_catalog_rejects_embedded_credentials_without_mutating_target(self):
        """This test will fail when provider credentials can leak from a source catalog into an install."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_deepseek_source(root / "source")
            catalog = source / "models-store.json"
            value = json.loads(catalog.read_text())
            value["deepseek"]["apiKey"] = "must-not-copy"
            catalog.write_text(json.dumps(value) + "\n")
            target = root / "target"
            target.mkdir()
            sentinel = target / "sentinel"
            sentinel.write_text("preserve\n")
            fake_home = root / "home"
            fake_home.mkdir()
            with mock.patch.object(Path, "home", return_value=fake_home):
                with self.assertRaisesRegex(SystemExit, "credentials"):
                    install.install(target, dry_run=False, profile="deepseek", source=source)
            self.assertEqual(sentinel.read_text(), "preserve\n")

    def test_deepseek_missing_or_malformed_catalog_fails_before_target_mutation(self):
        """This test will fail when an invalid source catalog can produce a partial DeepSeek install."""
        install = load_install_module()
        for source_state in (
            "missing", "malformed", "missing-deepseek", "invalid-model",
            "invalid-name", "invalid-thinking",
        ):
            with self.subTest(source_state=source_state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = write_deepseek_source(root / "source")
                catalog = source / "models-store.json"
                if source_state == "missing":
                    catalog.unlink()
                elif source_state == "malformed":
                    catalog.write_text("not json\n")
                else:
                    value = json.loads(catalog.read_text())
                    if source_state == "missing-deepseek":
                        value.pop("deepseek")
                    elif source_state == "invalid-model":
                        value["deepseek"]["models"][0]["id"] = "wrong-model"
                    elif source_state == "invalid-name":
                        value["deepseek"]["models"][0]["name"] = "wrong-name"
                    else:
                        value["deepseek"]["models"][0]["thinkingLevelMap"]["high"] = None
                    catalog.write_text(json.dumps(value) + "\n")
                target = root / "target"
                target.mkdir()
                sentinel = target / "sentinel"
                sentinel.write_text("preserve\n")
                fake_home = root / "home"
                fake_home.mkdir()
                with mock.patch.object(Path, "home", return_value=fake_home):
                    with self.assertRaisesRegex(SystemExit, "catalog|models-store|DeepSeek"):
                        install.install(target, dry_run=False, profile="deepseek", source=source)
                self.assertEqual(sentinel.read_text(), "preserve\n")
                self.assertFalse((target / "settings.json").exists())

    def test_deepseek_catalog_symlink_is_refused_and_rollback_restores_catalog(self):
        """This test will fail when catalog links are overwritten or validation rollback leaves catalog changes."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            target = root / "target"
            target.mkdir()
            secret = root / "secret-models-store.json"
            secret.write_text("keep me\n")
            catalog = target / "models-store.json"
            catalog.symlink_to(secret)
            with self.assertRaisesRegex(SystemExit, "symlink"):
                install.install(target, dry_run=True, adopt=True, profile="deepseek", source=source)
            self.assertEqual(secret.read_text(), "keep me\n")

            catalog.unlink()
            catalog.write_text(json.dumps({"user": {"models": [{"id": "one"}]}}) + "\n")
            before = catalog.read_bytes()
            with mock.patch.object(Path, "home", return_value=fake_home), mock.patch.object(
                install, "validate_installed", side_effect=RuntimeError("invalid")
            ), self.assertRaisesRegex(RuntimeError, "invalid"):
                install.install(target, dry_run=False, adopt=True, profile="deepseek", source=source)
            self.assertEqual(catalog.read_bytes(), before)

    def test_deepseek_rejects_invalid_source_before_reading_or_mutating_target(self):
        """This test will fail when source validation is destination-dependent or occurs after target inspection."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "broken-source"
            source.mkdir()
            target = root / "target"
            target.mkdir()
            (target / "settings.json").symlink_to(root / "secret-settings.json")
            with self.assertRaisesRegex(SystemExit, "source Pi runtime metadata"):
                install.install(target, dry_run=False, profile="deepseek", source=source)
            self.assertEqual(list(source.iterdir()), [])
            self.assertTrue((target / "settings.json").is_symlink())

    def test_deepseek_rejects_an_imposter_runtime_and_duplicate_package_implementation(self):
        """This test will fail when source identity or one-implementation-per-package invariants are not enforced."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_deepseek_source(root / "source")
            runtime = source / install.PI_RUNTIME_PACKAGE
            manifest = json.loads(runtime.read_text())
            manifest["name"] = "not-pi-subagents"
            runtime.write_text(json.dumps(manifest) + "\n")
            with self.assertRaisesRegex(SystemExit, "pi-subagents"):
                install.install(root / "target", dry_run=True, profile="deepseek", source=source)

            source = write_deepseek_source(root / "source-duplicate")
            duplicate = source / "duplicate"
            duplicate.mkdir()
            (duplicate / "package.json").write_text(json.dumps({
                "name": "pi-web-access", "version": "2.0.0", "pi": {"extensions": ["index.ts"]}
            }) + "\n")
            settings_path = source / "settings.json"
            settings = json.loads(settings_path.read_text())
            settings["packages"].append("./duplicate")
            settings_path.write_text(json.dumps(settings) + "\n")
            with self.assertRaisesRegex(SystemExit, "duplicate implementation"):
                install.install(root / "target", dry_run=True, profile="deepseek", source=source)

    def test_deepseek_package_resolution_fails_closed_for_missing_or_invalid_entries(self):
        """This test will fail when unresolved, malformed, or duplicate package implementations enter target settings."""
        install = load_install_module()
        bad_entries = ["npm:@scope/missing@1.2.3", {"source": "npm:missing", "bogus": True}, 42]
        for index, entry in enumerate(bad_entries):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = write_deepseek_source(root / "source")
                settings = json.loads((source / "settings.json").read_text())
                settings["packages"].append(entry)
                (source / "settings.json").write_text(json.dumps(settings) + "\n")
                target = root / "target"
                with self.assertRaisesRegex(SystemExit, "package"):
                    install.install(target, dry_run=True, profile="deepseek", source=source)
                self.assertFalse(target.exists())

    def test_unmanaged_extension_config_survives_bundle_install(self):
        """This test will fail when migration deletes a sandbox config not owned by the prior manifest."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            target = root / "deepseek"

            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="deepseek", source=source)
                manifest_path = target / install.MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text())
                manifest_path.write_text(json.dumps(manifest) + "\n")
                user_config = target / "extensions/pi-sandbox/config.json"
                user_config.parent.mkdir(parents=True)
                user_config.write_text('{"userOwned": true}\n')
                remove_sandbox_from_deepseek_source(source)

                install.install(target, dry_run=False, profile="deepseek", source=source)

            self.assertEqual(user_config.read_text(), '{"userOwned": true}\n')

    def test_deepseek_managed_extensions_require_adoption_reject_symlinks_and_clean_only_stale_managed_files(self):
        """This test will fail when managed extension lifecycle can overwrite links or delete unrelated files."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            target = root / "target"
            collision = target / "extensions/subagent/config.json"
            collision.parent.mkdir(parents=True)
            collision.write_text("{}\n")
            with self.assertRaisesRegex(SystemExit, "adoption required"):
                install.install(target, dry_run=True, profile="deepseek", source=source)
            secret = root / "secret"
            secret.write_text("preserve\n")
            collision.unlink()
            collision.symlink_to(secret)
            with self.assertRaisesRegex(SystemExit, "symlink"):
                install.install(target, dry_run=True, adopt=True, profile="deepseek", source=source)
            self.assertEqual(secret.read_text(), "preserve\n")
            collision.unlink()
            unrelated = target / "extensions/custom/config.json"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("keep\n")
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, adopt=True, profile="deepseek", source=source)
                manifest_path = target / install.MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text())
                manifest["managed_extensions"].append("extensions/retired/config.json")
                manifest_path.write_text(json.dumps(manifest) + "\n")
                stale = target / "extensions/retired/config.json"
                stale.parent.mkdir(parents=True)
                stale.write_text("stale\n")
                install.install(target, dry_run=False, profile="deepseek", source=source)
            self.assertFalse(stale.exists())
            self.assertEqual(unrelated.read_text(), "keep\n")
    def test_launcher_install_requires_adoption_is_executable_idempotent_and_rolls_back(self):
        """This test will fail when launcher collisions bypass adoption or a failed install leaves changes."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            target = root / "deepseek"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            launcher = bin_dir / "pi-deepseek"
            launcher.write_text("user launcher\n")
            source = write_deepseek_source(root / "source")
            with mock.patch.object(Path, "home", return_value=fake_home):
                with self.assertRaisesRegex(SystemExit, "adoption required"):
                    install.install(target, dry_run=True, profile="deepseek", bin_dir=bin_dir, source=source)
                self.assertEqual(launcher.read_text(), "user launcher\n")
                install.install(target, dry_run=False, adopt=True, profile="deepseek", bin_dir=bin_dir, source=source)
                self.assertTrue(os.access(launcher, os.X_OK))
                before = launcher.read_bytes()
                install.install(target, dry_run=False, profile="deepseek", bin_dir=bin_dir, source=source)
                self.assertEqual(launcher.read_bytes(), before)
                launcher.write_text("locally changed\n")
                with mock.patch.object(install, "validate_installed", side_effect=RuntimeError("invalid")):
                    with self.assertRaisesRegex(RuntimeError, "invalid"):
                        install.install(target, dry_run=False, profile="deepseek", bin_dir=bin_dir, source=source)
                self.assertEqual(launcher.read_text(), "locally changed\n")

    def test_bundle_only_install_does_not_claim_an_uninstalled_launcher(self):
        """This test will fail when bundle metadata lets a later launcher collision bypass adoption."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            target = root / "deepseek"
            source = write_deepseek_source(root / "source")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            launcher = bin_dir / "pi-deepseek"
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="deepseek", source=source)
                launcher.write_text("unmanaged launcher\n")
                with self.assertRaisesRegex(SystemExit, "adoption required"):
                    install.install(
                        target,
                        dry_run=True,
                        profile="deepseek",
                        bin_dir=bin_dir,
                        source=source,
                    )
            self.assertEqual(launcher.read_text(), "unmanaged launcher\n")

    def test_profile_installation_is_isolated_and_rejects_profile_mismatch(self):
        """This test will fail when one Pi profile can overwrite or adopt another profile's target."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            hybrid_target = root / "hybrid"
            deepseek_target = root / "deepseek"
            glm_target = root / "glm"
            write_pi_runtime(hybrid_target)
            write_pi_runtime(deepseek_target)
            write_pi_runtime(glm_target)
            source = write_deepseek_source(root / "source")
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(hybrid_target, dry_run=False, profile="hybrid")
                install.install(deepseek_target, dry_run=False, profile="deepseek", source=source)
                install.install(glm_target, dry_run=False, profile="glm")
                with self.assertRaisesRegex(SystemExit, "profile mismatch"):
                    install.install(hybrid_target, dry_run=False, profile="deepseek", source=source)
                with self.assertRaisesRegex(SystemExit, "profile mismatch"):
                    install.install(glm_target, dry_run=False, profile="hybrid")
            hybrid_worker = (hybrid_target / "agents/worker.md").read_text()
            hybrid_complex = (hybrid_target / "agents/worker-complex.md").read_text()
            self.assertIn("deepseek/deepseek-flash", hybrid_worker)
            self.assertIn("deepseek/deepseek-flash", hybrid_complex)
            self.assertIn("thinking: max", hybrid_complex)
            self.assertIn("deepseek/deepseek-flash", (deepseek_target / "agents/worker.md").read_text())
            glm_bundle = "\n".join(
                path.read_text() for path in (glm_target / "agents").glob("*.md")
            )
            self.assertIn("zai/glm-5.3-flash", glm_bundle)
            self.assertNotIn("opencode-go", glm_bundle)

    def test_glm_install_accepts_private_post_login_auth_without_replacing_it(self):
        """Deferred /login state remains private and is untouched by a later synchronization."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            target = root / "glm"
            write_pi_runtime(target)
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="glm", bin_dir=root / "bin")
            auth = target / "auth.json"
            auth.write_text('{"zai":{"type":"api_key","key":"keep-secret"}}\n')
            auth.chmod(0o600)
            before = auth.read_bytes()
            output = io.StringIO()
            with mock.patch.object(Path, "home", return_value=fake_home), mock.patch(
                "sys.stdout", output
            ):
                install.install(target, dry_run=False, profile="glm", bin_dir=root / "bin")
            self.assertEqual(auth.read_bytes(), before)
            self.assertNotIn("keep-secret", output.getvalue())

    def test_deepseek_install_preserves_operator_runtime_state(self):
        """Opaque operator state survives installation unchanged."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            # These bytes intentionally are not JSON: installer code must not
            # inspect either opaque auth file while synchronizing the profile.
            source_auth = source / "auth.json"
            source_auth.write_bytes(b"\\xffsource-auth-opaque")
            target = root / "deepseek"
            target.mkdir()
            target_auth = target / "auth.json"
            target_auth.write_bytes(b"\\xfftarget-auth-opaque")
            existing_catalog = {
                "unrelated-provider": {"models": [{"id": "keep-me"}]},
                "deepseek": {
                    "baseUrl": "https://api.deepseek.com",
                    "api": "openai-completions",
                    "checkedAt": 1800000000000,
                    "lastModified": 1800000000000,
                    "etag": "target-etag",
                    "models": [{
                        "id": "deepseek-flash",
                        "name": "DeepSeek V4.1 Flash (local newer)",
                        "reasoning": True,
                        "thinkingLevelMap": {"low": "low", "high": "high", "max": "max"},
                        "input": ["text", "image"],
                        "contextWindow": 2000000,
                        "maxTokens": 512000,
                    }],
                },
            }
            catalog = target / "models-store.json"
            catalog.write_text(json.dumps(existing_catalog, indent=2) + "\n")
            catalog_before = catalog.read_bytes()
            preserved = {
                "sessions/history.bin": b"session-history",
                "cache/models.json": b"cache-state",
                "logs/pi.log": b"log-state",
                "analytics/usage.json": b"analytics-state",
                "history/mutable.json": b"mutable-history",
            }
            for relative, content in preserved.items():
                path = target / relative
                path.parent.mkdir(parents=True)
                path.write_bytes(content)
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(
                    target,
                    dry_run=False,
                    profile="deepseek",
                    source=source,
                    bin_dir=root / "bin",
                )
            self.assertEqual(catalog.read_bytes(), catalog_before)
            self.assertEqual(target_auth.read_bytes(), b"\\xfftarget-auth-opaque")
            self.assertEqual(source_auth.read_bytes(), b"\\xffsource-auth-opaque")
            for relative, content in preserved.items():
                self.assertEqual((target / relative).read_bytes(), content)
            settings = json.loads((target / "settings.json").read_text())
            self.assertEqual(
                (settings["defaultProvider"], settings["defaultModel"], settings["defaultThinkingLevel"]),
                ("deepseek", "deepseek-flash", "max"),
            )
            launcher = (root / "bin" / "pi-deepseek").read_text()
            self.assertIn(f"PI_CODING_AGENT_DIR={str(target.resolve())}", launcher)
            self.assertIn(
                'PI_CODING_AGENT_SESSION_DIR="$HOME/.pi/agent/sessions"',
                launcher,
            )

    def test_dry_run_redacts_operator_and_source_secrets(self):
        """Dry-run reports redact operator and source secrets while ignoring MCP state."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_deepseek_source(root / "source")
            target = root / "deepseek"
            target.mkdir()
            (target / "settings.json").write_text(json.dumps({
                "theme": "target-theme",
                "targetSecret": "target-settings-secret",
                "packages": [],
            }) + "\n")
            (target / "models-store.json").write_text(json.dumps({
                "deepseek": {"models": [{"id": "invalid"}]},
                "unrelated": {"token": "target-catalog-secret"},
            }) + "\n")
            (target / "mcp.json").write_text(json.dumps({
                "mcpServers": {"target": {"command": "target-mcp-secret"}},
            }) + "\n")
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                install.install(
                    target,
                    dry_run=True,
                    adopt=True,
                    profile="deepseek",
                    source=source,
                )
            report = output.getvalue()
            for secret in (
                "target-settings-secret", "target-catalog-secret", "target-mcp-secret",
                "deepseek-mcp-secret",
            ):
                self.assertNotIn(secret, report)
            self.assertGreaterEqual(report.count("(contents redacted)"), 2)

    def test_manifest_migration_preserves_operator_files_and_removes_retired_project_artifacts(self):
        """Legacy claims are dropped without touching operator files or stale project artifacts."""
        install = load_install_module()
        profiles = ("hybrid", "deepseek", "glm")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            for profile in profiles:
                with self.subTest(profile=profile):
                    target = root / profile
                    source = None
                    if profile == "hybrid":
                        write_pi_runtime(target)
                    elif profile == "deepseek":
                        source = write_deepseek_source(root / f"{profile}-source")
                    else:
                        write_pi_runtime(target)
                        source = write_deepseek_source(root / f"{profile}-source")
                    with mock.patch.object(Path, "home", return_value=fake_home):
                        install.install(target, dry_run=False, profile=profile, source=source)
                    manifest_path = target / install.MANIFEST_NAME
                    manifest = json.loads(manifest_path.read_text())
                    manifest["roles"].append("spec-writer")
                    manifest["managed_extensions"].append(
                        "extensions/agent-orchestration/planning-artifact-guard.js"
                    )
                    manifest["managed_extensions"].extend([
                        "extensions/pi-permission-system/config.json",
                        "extensions/pi-permission-system/package.json",
                    ])
                    manifest["managed_files"] = ["themes/custom-theme.json"]
                    manifest_path.write_text(json.dumps(manifest) + "\n")

                    retired_agent = target / "agents/spec-writer.md"
                    retired_agent.write_text("legacy project artifact\n")
                    retired_guard = target / "extensions/agent-orchestration/planning-artifact-guard.js"
                    retired_guard.write_text("legacy guard\n")
                    operator_files = {
                        target / "extensions/pi-permission-system/config.json": b"opaque permission config\n",
                        target / "extensions/pi-permission-system/package.json": b"opaque permission bridge\n",
                        target / "themes/custom-theme.json": b"opaque custom theme\n",
                        target / "auth.json": b"\\xffopaque auth\n",
                        target / "mcp.json": b"not json operator state\n",
                    }
                    for path, content in operator_files.items():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                        path.chmod(0o640)
                    if profile != "hybrid":
                        settings_path = target / "settings.json"
                        settings = json.loads(settings_path.read_text())
                        settings["theme"] = "custom-theme"
                        settings_path.write_text(json.dumps(settings) + "\n")
                    snapshots = {
                        path: (path.read_bytes(), path.stat().st_mode & 0o777,
                               path.stat().st_ino, path.stat().st_mtime_ns)
                        for path in operator_files
                    }

                    output = io.StringIO()
                    with mock.patch.object(Path, "home", return_value=fake_home), mock.patch(
                        "sys.stdout", output
                    ):
                        install.install(target, dry_run=False, profile=profile, source=source)
                    current = json.loads(manifest_path.read_text())
                    self.assertNotIn("spec-writer", current["roles"])
                    self.assertNotIn("extensions/agent-orchestration/planning-artifact-guard.js", current["managed_extensions"])
                    self.assertNotIn("extensions/pi-permission-system/config.json", current["managed_extensions"])
                    self.assertNotIn("extensions/pi-permission-system/package.json", current["managed_extensions"])
                    self.assertNotIn("managed_files", current)
                    self.assertFalse(retired_agent.exists())
                    self.assertFalse(retired_guard.exists())
                    for path, snapshot in snapshots.items():
                        self.assertEqual(
                            (path.read_bytes(), path.stat().st_mode & 0o777,
                             path.stat().st_ino, path.stat().st_mtime_ns),
                            snapshot,
                        )
                    if profile != "hybrid":
                        self.assertEqual(json.loads((target / "settings.json").read_text())["theme"], "custom-theme")

    def test_manifest_migration_rollback_restores_retired_artifacts_and_leaves_operator_files(self):
        """Validation failure restores project claims while operator state stays outside the transaction."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            target = root / "hybrid"
            write_pi_runtime(target)
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="hybrid")
            manifest_path = target / install.MANIFEST_NAME
            previous = json.loads(manifest_path.read_text())
            previous["roles"].append("spec-writer")
            previous["managed_extensions"].append(
                "extensions/agent-orchestration/planning-artifact-guard.js"
            )
            previous["managed_extensions"].extend([
                "extensions/pi-permission-system/config.json",
                "extensions/pi-permission-system/package.json",
            ])
            previous["managed_files"] = ["themes/custom-theme.json"]
            manifest_path.write_text(json.dumps(previous) + "\n")
            retired_agent = target / "agents/spec-writer.md"
            retired_agent.write_text("legacy agent\n")
            retired_guard = target / "extensions/agent-orchestration/planning-artifact-guard.js"
            retired_guard.write_text("legacy guard\n")
            operator_files = {
                target / "extensions/pi-permission-system/config.json": b"operator config\n",
                target / "extensions/pi-permission-system/package.json": b"operator bridge\n",
                target / "themes/custom-theme.json": b"operator theme\n",
                target / "auth.json": b"opaque auth\n",
                target / "mcp.json": b"opaque mcp\n",
            }
            for path, content in operator_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            before_operator = {path: path.read_bytes() for path in operator_files}
            with mock.patch.object(Path, "home", return_value=fake_home), mock.patch.object(
                install, "validate_installed", side_effect=RuntimeError("forced validation failure")
            ):
                with self.assertRaisesRegex(RuntimeError, "forced validation failure"):
                    install.install(target, dry_run=False, profile="hybrid")
            self.assertEqual(json.loads(manifest_path.read_text()), previous)
            self.assertEqual(retired_agent.read_text(), "legacy agent\n")
            self.assertEqual(retired_guard.read_text(), "legacy guard\n")
            for path, content in before_operator.items():
                self.assertEqual(path.read_bytes(), content)

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
