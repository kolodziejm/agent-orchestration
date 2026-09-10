import importlib.util
import json
import os
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


def write_deepseek_source(root: Path) -> Path:
    settings = {
        "defaultProvider": "openai-codex",
        "defaultModel": "gpt-source",
        "defaultThinkingLevel": "medium",
        "packages": [
            "npm:pi-web-access",
            "npm:pi-subagents@0.67.0",
            "npm:@gotgenes/pi-permission-system@31.1.3",
            {"source": "npm:@erichll/pi-auto-review@0.17.0", "autoload": False,
             "extensions": ["src/index.ts"]},
            "./local/pi-sandbox",
        ],
        "theme": "source-theme",
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "settings.json").write_text(json.dumps(settings) + "\n")
    (root / "models-store.json").write_text(json.dumps({
        "deepseek": {
            "baseUrl": "https://api.deepseek.example/v1",
            "api": "openai-completions",
            "compat": {"thinkingFormat": "deepseek"},
            "models": [{
                "id": "deepseek-flash",
                "name": "DeepSeek V4.1 Flash",
                "reasoning": True,
                "thinkingLevelMap": {"low": "low", "high": "high", "max": "max"},
                "input": ["text", "image"],
                "contextWindow": 1000000,
                "maxTokens": 128000,
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
        (manifest.parent / "index.ts").write_text("export default {};\n")
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


def package_names(settings: dict) -> dict[str, str]:
    names = {}
    for entry in settings.get("packages", []):
        package_source = entry if isinstance(entry, str) else entry.get("source")
        if isinstance(package_source, str):
            manifest = json.loads((Path(package_source) / "package.json").read_text())
            names[manifest["name"]] = package_source
    return names


class PiInstallTests(unittest.TestCase):
    def test_deepseek_migrates_prior_sandbox_install_by_exact_package_identity(self):
        """This test will fail when migration still requires or leaves the removed sandbox package/config."""
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
                manifest["managed_extensions"].append("extensions/pi-sandbox/config.json")
                manifest_path.write_text(json.dumps(manifest) + "\n")
                legacy_config = target / "extensions" / "pi-sandbox" / "config.json"
                legacy_config.parent.mkdir(parents=True)
                legacy_config.write_text('{"legacy": true}\n')

                legacy_sandbox = target / "legacy" / "pi-sandbox"
                legacy_sandbox.mkdir(parents=True)
                (legacy_sandbox / "package.json").write_text(
                    json.dumps({"name": "@erichll/pi-sandbox", "version": "0.17.1"}) + "\n"
                )
                npm_sandbox = target / "npm" / "node_modules" / "@erichll" / "pi-sandbox"
                npm_sandbox.mkdir(parents=True)
                (npm_sandbox / "package.json").write_text(
                    json.dumps({"name": "@erichll/pi-sandbox", "version": "0.17.1"}) + "\n"
                )
                similar_package = target / "legacy" / "pi-sandbox-extension"
                similar_package.mkdir(parents=True)
                (similar_package / "package.json").write_text(
                    json.dumps({"name": "@erichll/pi-sandbox-extension", "version": "1.0.0"}) + "\n"
                )
                user_package = target / "legacy" / "user-package"
                user_package.mkdir(parents=True)
                (user_package / "package.json").write_text(
                    json.dumps({"name": "@example/user-package", "version": "1.0.0"}) + "\n"
                )
                settings_path = target / "settings.json"
                settings = json.loads(settings_path.read_text())
                settings["packages"].extend(
                    ["npm:@erichll/pi-sandbox", str(legacy_sandbox), str(similar_package), str(user_package)]
                )
                settings["theme"] = "user-theme"
                settings_path.write_text(json.dumps(settings) + "\n")
                custom_config = target / "extensions" / "custom" / "config.json"
                custom_config.parent.mkdir(parents=True)
                custom_config.write_text('{"keep": true}\n')
                catalog_before = (target / "models-store.json").read_bytes()

                remove_sandbox_from_deepseek_source(source)
                install.install(target, dry_run=False, profile="deepseek", source=source)
                first_migration = {
                    path.relative_to(target): path.read_bytes()
                    for path in target.rglob("*")
                    if path.is_file()
                }
                install.install(target, dry_run=False, profile="deepseek", source=source)

            configured = json.loads((target / "settings.json").read_text())
            names = package_names(configured)
            self.assertNotIn("@erichll/pi-sandbox", names)
            self.assertIn("@erichll/pi-sandbox-extension", names)
            self.assertIn("@example/user-package", names)
            self.assertIn("pi-subagents", names)
            self.assertIn("@gotgenes/pi-permission-system", names)
            self.assertIn("@erichll/pi-auto-review", names)
            self.assertEqual(configured["theme"], "user-theme")
            self.assertFalse((target / "extensions/pi-sandbox/config.json").exists())
            self.assertEqual(custom_config.read_text(), '{"keep": true}\n')
            self.assertEqual((target / "models-store.json").read_bytes(), catalog_before)
            self.assertEqual(
                {
                    path.relative_to(target): path.read_bytes()
                    for path in target.rglob("*")
                    if path.is_file()
                },
                first_migration,
            )

    def test_deepseek_migration_preserves_unmanaged_pi_sandbox_config(self):
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

    def test_deepseek_bootstraps_from_source_packages_and_managed_extension_configs(self):
        """This test will fail when a fresh DeepSeek target cannot reuse the source Pi installation safely."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            source = write_deepseek_source(root / "source")
            target = root / "deepseek"
            bin_dir = root / "bin"
            with mock.patch.object(Path, "home", return_value=fake_home):
                result = install.install(
                    target, dry_run=False, profile="deepseek", source=source,
                    bin_dir=bin_dir,
                )
            self.assertEqual(result, 0)
            configured = json.loads((target / "settings.json").read_text())
            self.assertEqual(configured["defaultProvider"], "deepseek")
            self.assertEqual(configured["defaultModel"], "deepseek-flash")
            self.assertEqual(configured["defaultThinkingLevel"], "high")
            package_sources = [item if isinstance(item, str) else item["source"] for item in configured["packages"]]
            expected_roots = {
                str((source / "npm/node_modules/pi-subagents").resolve()),
                str((source / "npm/node_modules/@gotgenes/pi-permission-system").resolve()),
                str((source / "npm/node_modules/@erichll/pi-auto-review").resolve()),
            }
            self.assertTrue(expected_roots.issubset(set(package_sources)))
            self.assertNotIn(str((source / "local/pi-sandbox").resolve()), package_sources)
            self.assertFalse(any(path == "/opt/homebrew/lib/pi-security-packages" for path in package_sources))
            auto_review = json.loads((target / "extensions/pi-auto-review/config.json").read_text())
            self.assertEqual(auto_review["model"], "deepseek/deepseek-flash")
            permission = json.loads((target / "extensions/pi-permission-system/config.json").read_text())
            self.assertEqual(permission["piInfrastructureReadPaths"], [f"{target.resolve()}/*"])
            bridge = json.loads((target / "extensions/pi-permission-system/package.json").read_text())
            self.assertEqual(
                bridge["pi"]["extensions"],
                [str((source / "npm/node_modules/@gotgenes/pi-permission-system/index.ts").resolve())],
            )
            launcher = (bin_dir / "pi-deepseek").read_text()
            self.assertIn(f"PI_CODING_AGENT_DIR={str(target.resolve())}", launcher)
            self.assertNotIn("auth.json", "\n".join(str(path) for path in target.rglob("*")))
            source_catalog = json.loads((source / "models-store.json").read_text())
            target_catalog = json.loads((target / "models-store.json").read_text())
            self.assertEqual(
                target_catalog["deepseek"],
                source_catalog["deepseek"],
            )

    def test_deepseek_seeds_exact_model_catalog_and_preserves_unrelated_top_level_entries(self):
        """This test will fail when DeepSeek bootstrap loses catalog metadata or unrelated entries."""
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
                "deepseek": {"checkedAt": 1800000000000, "lastModified": 1800000000000, "etag": "target-etag", "models": [{
                    "id": "deepseek-flash", "name": "DeepSeek V4.1 Flash (local newer)",
                    "reasoning": True,
                    "thinkingLevelMap": {"low": "low", "high": "high", "max": "max"},
                    "contextWindow": 2000000,
                }]},
            }
            catalog = target / "models-store.json"
            catalog.write_text(json.dumps(existing) + "\n")
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, adopt=True, profile="deepseek", source=source)
            configured = json.loads(catalog.read_text())
            self.assertEqual(configured["user-provider"], existing["user-provider"])
            self.assertEqual(configured["deepseek"], existing["deepseek"])

    def test_deepseek_catalog_is_idempotent_and_auth_is_never_created_or_copied(self):
        """This test will fail when catalog bootstrap rewrites stable state or copies credentials."""
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
                first = (target / "models-store.json").read_bytes()
                install.install(target, dry_run=False, profile="deepseek", source=source)
            self.assertEqual((target / "models-store.json").read_bytes(), first)
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
            openai_target = root / "openai"
            deepseek_target = root / "deepseek"
            write_pi_runtime(openai_target)
            source = write_deepseek_source(root / "source")
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(openai_target, dry_run=False, profile="openai")
                install.install(deepseek_target, dry_run=False, profile="deepseek", source=source)
                with self.assertRaisesRegex(SystemExit, "profile mismatch"):
                    install.install(openai_target, dry_run=False, profile="deepseek", source=source)
            self.assertIn("openai-codex/", (openai_target / "agents/worker.md").read_text())
            self.assertIn("deepseek/deepseek-flash", (deepseek_target / "agents/worker.md").read_text())

    def test_deepseek_install_merges_required_packages_without_losing_user_configuration(self):
        """This test will fail when DeepSeek lacks its runtime packages or user settings are replaced."""
        install = load_install_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_home = root / "home"
            fake_home.mkdir()
            target = root / "deepseek"
            source = write_deepseek_source(root / "source")
            target.mkdir()
            settings = target / "settings.json"
            settings.write_text(json.dumps({
                "packages": ["user-package"],
                "extensions": ["user-extension.ts"],
                "theme": "user-theme",
            }) + "\n")
            with mock.patch.object(Path, "home", return_value=fake_home):
                install.install(target, dry_run=False, profile="deepseek", source=source)
            configured = json.loads(settings.read_text())
            self.assertEqual(configured["extensions"], ["user-extension.ts"])
            self.assertEqual(configured["theme"], "user-theme")
            package_sources = [item if isinstance(item, str) else item["source"] for item in configured["packages"]]
            self.assertIn(str((source / "npm/node_modules/pi-subagents").resolve()), package_sources)
            self.assertNotIn(str((source / "local/pi-sandbox").resolve()), package_sources)

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
