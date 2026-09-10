#!/usr/bin/env python3
"""Safely install generated pi-subagents definitions into a Pi user directory."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "adapters" / "pi" / "render.py"
MANIFEST_NAME = ".agent-orchestration.pi-manifest.json"
MANAGED_ROOT = Path("agent-orchestration")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PI_RUNTIME_PACKAGE = Path("npm") / "node_modules" / "pi-subagents" / "package.json"
PI_MINIMUM_VERSION = (0, 67, 0)
RELEASE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DEEPSEEK_REQUIRED_PACKAGE_NAMES = (
    "pi-subagents",
    "@gotgenes/pi-permission-system",
    "@erichll/pi-auto-review",
)
DEEPSEEK_MANAGED_EXTENSIONS = (
    "extensions/subagent/config.json",
    "extensions/pi-permission-system/config.json",
    "extensions/pi-permission-system/package.json",
    "extensions/pi-auto-review/config.json",
)
DEEPSEEK_MODELS_STORE = "models-store.json"
DEEPSEEK_MODEL_ID = "deepseek-flash"
DEEPSEEK_MODEL_NAME = "DeepSeek V4.1 Flash"
DEEPSEEK_THINKING_LEVELS = ("low", "high", "max")
CATALOG_CREDENTIAL_KEYS = {
    "apikey", "password", "secret", "token", "credential", "credentials",
    "auth", "authorization",
}
PACKAGE_OBJECT_KEYS = {"source", "autoload", "extensions", "skills", "prompts", "themes"}
SAFE_MANAGED_EXTENSION = re.compile(
    r"^extensions/[A-Za-z0-9][A-Za-z0-9._-]*/(?:config|package)\.json$"
)


def validate_pi_runtime(target: Path, label: str = "Pi") -> tuple[int, int, int]:
    """Require a locally installed, supported pi-subagents release."""
    package_path = target / PI_RUNTIME_PACKAGE
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(
            f"Missing {label} runtime metadata: expected {package_path}"
        ) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Malformed {label} runtime metadata: {package_path}") from error

    name = package.get("name") if isinstance(package, dict) else None
    if name != "pi-subagents":
        raise SystemExit(
            f"Malformed {label} runtime metadata: {package_path} is not pi-subagents"
        )
    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or RELEASE_VERSION.fullmatch(version) is None:
        raise SystemExit(
            f"Malformed {label} runtime metadata: {package_path} has an invalid release version"
        )
    parsed = tuple(int(part) for part in version.split("."))
    if parsed < PI_MINIMUM_VERSION:
        minimum = ".".join(str(part) for part in PI_MINIMUM_VERSION)
        raise SystemExit(
            f"Unsupported pi-subagents runtime {version}; minimum supported version is {minimum}"
        )
    return parsed


def text_diff(current: Path, desired: str, label: str) -> str:
    before = current.read_text().splitlines(keepends=True) if current.exists() else []
    after = desired.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(current), tofile=label))


def _npm_package_name(spec: str) -> str:
    if not spec:
        raise SystemExit("Malformed Pi npm package spec")
    if spec.startswith("@"):
        slash = spec.find("/")
        if slash <= 1:
            raise SystemExit(f"Malformed Pi npm package spec: {spec!r}")
        version = spec.find("@", slash)
        name = spec if version < 0 else spec[:version]
    else:
        name = spec.split("@", 1)[0]
    if not name or name.endswith("/"):
        raise SystemExit(f"Malformed Pi npm package spec: {spec!r}")
    return name


def _package_source(entry: object, settings_path: Path) -> tuple[str, dict | None]:
    if isinstance(entry, str):
        return entry, None
    if not isinstance(entry, dict) or set(entry) - PACKAGE_OBJECT_KEYS:
        raise SystemExit(f"Malformed Pi package entry in {settings_path}: {entry!r}")
    source = entry.get("source")
    if not isinstance(source, str):
        raise SystemExit(f"Malformed Pi package entry in {settings_path}: missing string source")
    if "autoload" in entry and not isinstance(entry["autoload"], bool):
        raise SystemExit(f"Malformed Pi package entry in {settings_path}: invalid autoload")
    for key in PACKAGE_OBJECT_KEYS - {"source", "autoload"}:
        if key in entry and (
            not isinstance(entry[key], list)
            or not all(isinstance(value, str) for value in entry[key])
        ):
            raise SystemExit(f"Malformed Pi package entry in {settings_path}: invalid {key}")
    return source, dict(entry)


def resolve_source_packages(source: Path) -> tuple[list[object], dict[str, Path]]:
    settings_path = source / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Missing source Pi settings: {settings_path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Malformed source Pi settings: {settings_path}") from error
    packages = settings.get("packages") if isinstance(settings, dict) else None
    if not isinstance(packages, list):
        raise SystemExit(f"Malformed source Pi settings: {settings_path} packages must be an array")

    resolved_entries: list[object] = []
    roots_by_name: dict[str, Path] = {}
    seen_roots: set[Path] = set()
    for entry in packages:
        package_source, object_entry = _package_source(entry, settings_path)
        if package_source.startswith("npm:"):
            name = _npm_package_name(package_source.removeprefix("npm:").strip())
            root = source / "npm" / "node_modules" / name
        elif package_source.startswith("git:"):
            raise SystemExit(f"Unresolved source Pi package: {package_source!r}")
        else:
            candidate = Path(package_source).expanduser()
            root = candidate if candidate.is_absolute() else source / candidate
        root = root.resolve()
        manifest_path = root / "package.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise SystemExit(
                f"Unresolved source Pi package {package_source!r}: expected {manifest_path}"
            ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SystemExit(f"Malformed source Pi package manifest: {manifest_path}") from error
        package_name = manifest.get("name") if isinstance(manifest, dict) else None
        if not isinstance(package_name, str) or not package_name:
            raise SystemExit(f"Malformed source Pi package manifest: {manifest_path}")
        if package_source.startswith("npm:") and package_name != name:
            raise SystemExit(
                f"Source Pi package manifest name mismatch: expected {name!r} at {manifest_path}"
            )
        if package_name == "@erichll/pi-sandbox":
            continue
        previous_root = roots_by_name.get(package_name)
        if previous_root is not None and previous_root != root:
            raise SystemExit(
                f"Source Pi package {package_name!r} has a duplicate implementation: "
                f"{previous_root} and {root}"
            )
        roots_by_name[package_name] = root
        if root in seen_roots:
            continue
        seen_roots.add(root)
        if object_entry is None:
            resolved_entries.append(str(root))
        else:
            object_entry["source"] = str(root)
            resolved_entries.append(object_entry)

    missing = [name for name in DEEPSEEK_REQUIRED_PACKAGE_NAMES if name not in roots_by_name]
    if missing:
        raise SystemExit(f"Missing required source Pi package(s): {', '.join(missing)}")
    return resolved_entries, roots_by_name


def _package_source_value(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        source = entry.get("source")
        return source if isinstance(source, str) else None
    return None


def _package_source_path(entry: object, target: Path) -> Path | None:
    source = _package_source_value(entry)
    if source is None or source.startswith("git:"):
        return None
    if source.startswith("npm:"):
        try:
            name = _npm_package_name(source.removeprefix("npm:").strip())
        except SystemExit:
            return None
        return (target / "npm" / "node_modules" / name).resolve()
    candidate = Path(source).expanduser()
    return (candidate if candidate.is_absolute() else target / candidate).resolve()


def _validated_package_name(entry: object, target: Path) -> str | None:
    package_root = _package_source_path(entry, target)
    if package_root is None:
        return None
    try:
        manifest = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    name = manifest.get("name") if isinstance(manifest, dict) else None
    return name if isinstance(name, str) else None


def _canonical_package_source(entry: object, target: Path) -> str | None:
    source = _package_source_value(entry)
    if source is None:
        return None
    package_root = _package_source_path(entry, target)
    return str(package_root) if package_root is not None else source


def merge_deepseek_packages(
    target_packages: object, source_packages: list[object], target: Path
) -> list[object]:
    """Keep user packages while removing only a validated legacy sandbox package."""
    merged: list[object] = []
    seen_sources: set[str] = set()
    if isinstance(target_packages, list):
        for entry in target_packages:
            if _validated_package_name(entry, target) == "@erichll/pi-sandbox":
                continue
            merged.append(entry)
            canonical = _canonical_package_source(entry, target)
            if canonical is not None:
                seen_sources.add(canonical)
    for entry in source_packages:
        canonical = _canonical_package_source(entry, target)
        if canonical is not None and canonical in seen_sources:
            continue
        merged.append(entry)
        if canonical is not None:
            seen_sources.add(canonical)
    return merged


def _read_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Missing {label}: {path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Malformed {label}: {path}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"Malformed {label}: {path} must contain an object")
    return value


def _deepseek_model(provider: object, label: str, *, exact_name: bool = True) -> dict:
    if not isinstance(provider, dict):
        raise SystemExit(f"Malformed DeepSeek models-store provider in {label}")
    models = provider.get("models")
    if not isinstance(models, list):
        raise SystemExit(f"Malformed DeepSeek models-store provider in {label}: models must be an array")
    matches = [model for model in models if isinstance(model, dict) and model.get("id") == DEEPSEEK_MODEL_ID]
    if len(matches) != 1:
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"expected exactly one {DEEPSEEK_MODEL_ID} model"
        )
    model = matches[0]
    if exact_name and model.get("name") != DEEPSEEK_MODEL_NAME:
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} must be named {DEEPSEEK_MODEL_NAME}"
        )
    if not exact_name and (not isinstance(model.get("name"), str) or not model["name"].strip()):
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} is missing a display name"
        )
    if model.get("reasoning") is not True:
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} must support reasoning"
        )
    thinking = model.get("thinkingLevelMap")
    if not isinstance(thinking, dict):
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: missing thinkingLevelMap"
        )
    for level in DEEPSEEK_THINKING_LEVELS:
        value = thinking.get(level)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(
                f"Malformed DeepSeek models-store provider in {label}: "
                f"thinking level {level!r} is not usable"
            )
    return model


def _deepseek_store_entry(catalog: object, label: str, *, exact_name: bool = True) -> dict:
    if not isinstance(catalog, dict):
        raise SystemExit(f"Malformed DeepSeek models-store cache: {label} must contain an object")
    provider = catalog.get("deepseek")
    if provider is None:
        raise SystemExit(f"Malformed DeepSeek models-store cache: {label} is missing deepseek")
    _deepseek_model(provider, label, exact_name=exact_name)
    return provider


def _reject_catalog_credentials(value: object, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower().replace("_", "") in CATALOG_CREDENTIAL_KEYS:
                raise SystemExit(f"Refusing credentials in DeepSeek models-store cache: {label}")
            _reject_catalog_credentials(child, label)
    elif isinstance(value, list):
        for child in value:
            _reject_catalog_credentials(child, label)


def _read_deepseek_store(path: Path, label: str) -> dict:
    catalog = _read_json_object(path, label)
    provider = _deepseek_store_entry(catalog, label)
    _reject_catalog_credentials(provider, label)
    return catalog


def _target_deepseek_entry(catalog: dict, label: str) -> dict | None:
    provider = catalog.get("deepseek")
    if provider is None:
        return None
    try:
        _deepseek_model(provider, label, exact_name=False)
    except SystemExit:
        return None
    return provider


def deepseek_source_files(source: Path, target: Path) -> tuple[str, str, dict[str, str]]:
    packages, roots = resolve_source_packages(source)
    source_store_path = source / DEEPSEEK_MODELS_STORE
    source_store = _read_deepseek_store(source_store_path, "source models-store.json")
    source_provider = source_store["deepseek"]
    target_store_path = target / DEEPSEEK_MODELS_STORE
    assert_safe_destination(target_store_path, target)
    if target_store_path.exists():
        target_store = _read_json_object(target_store_path, "target models-store.json")
        try:
            target_store_text = target_store_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SystemExit(f"Malformed target models-store.json: {target_store_path}") from error
        target_entry = _target_deepseek_entry(target_store, "target models-store.json")
        if target_entry is not None:
            catalog_content = target_store_text
        else:
            target_store["deepseek"] = json.loads(json.dumps(source_provider))
            catalog_content = json.dumps(target_store, indent=2) + "\n"
    else:
        catalog_content = json.dumps(
            {"deepseek": json.loads(json.dumps(source_provider))},
            indent=2,
        ) + "\n"
    path = target / "settings.json"
    assert_safe_destination(path, target)
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SystemExit(f"Malformed Pi settings: {path}") from error
        if not isinstance(settings, dict):
            raise SystemExit(f"Malformed Pi settings: {path} must contain an object")
    else:
        settings = {}
    settings["packages"] = merge_deepseek_packages(
        settings.get("packages") if isinstance(settings, dict) else None,
        packages,
        target,
    )
    settings["defaultProvider"] = "deepseek"
    settings["defaultModel"] = "deepseek-flash"
    settings["defaultThinkingLevel"] = "high"

    managed: dict[str, str] = {}
    for relative in DEEPSEEK_MANAGED_EXTENSIONS:
        source_path = source / relative
        value = _read_json_object(source_path, "source Pi managed extension configuration")
        if relative == "extensions/pi-auto-review/config.json":
            value["model"] = "deepseek/deepseek-flash"
        elif relative == "extensions/pi-permission-system/config.json":
            paths = value.get("piInfrastructureReadPaths")
            if isinstance(paths, list):
                value["piInfrastructureReadPaths"] = [
                    f"{target}/*" if item == "~/.pi/agent/*" else item for item in paths
                ]
        elif relative == "extensions/pi-permission-system/package.json":
            pi = value.get("pi")
            extensions = pi.get("extensions") if isinstance(pi, dict) else None
            permission_root = roots["@gotgenes/pi-permission-system"]
            if not isinstance(extensions, list) or not all(
                isinstance(item, str)
                and Path(item).is_absolute()
                and Path(item).is_file()
                and (
                    Path(item).resolve() == permission_root
                    or permission_root in Path(item).resolve().parents
                )
                for item in extensions
            ):
                raise SystemExit(f"Malformed source Pi permission bridge: {source_path}")
            pi["extensions"] = [
                str(permission_root / Path(item).resolve().relative_to(permission_root))
                for item in extensions
            ]
        managed[relative] = json.dumps(value, indent=2) + "\n"
    return json.dumps(settings, indent=2) + "\n", catalog_content, managed


def _has_entry(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def validate_manifest(manifest: dict, label: str) -> None:
    if manifest.get("format_version") != 1:
        raise SystemExit(f"Unsupported {label} format_version")
    for key in ("roles", "profiles", "workflows", "shared", "launchers"):
        values = manifest.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise SystemExit(f"Invalid {label} {key}")
        if len(values) != len(set(values)):
            raise SystemExit(f"Duplicate names in {label} {key}")
        for value in values:
            if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
                raise SystemExit(f"Unsafe name in {label} {key}: {value!r}")
    extensions = manifest.get("managed_extensions", [])
    if not isinstance(extensions, list) or not all(
        isinstance(value, str) and SAFE_MANAGED_EXTENSION.fullmatch(value)
        for value in extensions
    ):
        raise SystemExit(f"Invalid {label} managed_extensions")
    if len(extensions) != len(set(extensions)):
        raise SystemExit(f"Duplicate names in {label} managed_extensions")


def assert_safe_destination(path: Path, target: Path) -> None:
    if path.is_symlink():
        raise SystemExit(f"Refusing to replace symlink: {path}")
    resolved_target = target.resolve()
    try:
        path.resolve(strict=False).relative_to(resolved_target)
    except ValueError as error:
        raise SystemExit(f"Refusing path outside target: {path}") from error
    current = path.parent
    while current != target:
        if current.is_symlink():
            raise SystemExit(f"Refusing path below symlinked directory: {current}")
        if current == current.parent:
            raise SystemExit(f"Refusing path outside target: {path}")
        current = current.parent


def managed_paths(manifest: dict, target: Path) -> set[Path]:
    paths = {target / "agents" / f"{role}.md" for role in manifest["roles"]}
    paths.update(
        target / MANAGED_ROOT / "workflows" / f"{name}.md"
        for name in manifest.get("workflows", [])
    )
    paths.update(
        target / MANAGED_ROOT / "_shared" / name
        for name in manifest.get("shared", [])
    )
    paths.add(target / MANIFEST_NAME)
    paths.update(target / relative for relative in manifest.get("managed_extensions", []))
    return paths


def load_and_preflight(rendered: Path, target: Path, adopt: bool) -> tuple[dict, dict]:
    current = json.loads((rendered / "manifest.json").read_text())
    validate_manifest(current, "generated manifest")
    manifest_path = target / MANIFEST_NAME
    assert_safe_destination(manifest_path, target)
    manifest_exists = _has_entry(manifest_path)
    previous = (
        json.loads(manifest_path.read_text())
        if manifest_exists
        else {
            "format_version": 1,
            "roles": [],
            "profiles": [],
            "workflows": [],
            "shared": [],
            "launchers": [],
            "managed_extensions": [],
        }
    )
    validate_manifest(previous, "installed manifest")
    if manifest_exists and previous.get("profiles") != current.get("profiles"):
        raise SystemExit(
            "Pi profile mismatch: the target is managed for "
            f"{previous.get('profiles')!r}, not {current.get('profiles')!r}"
        )

    for path in managed_paths(current, target) | managed_paths(previous, target):
        assert_safe_destination(path, target)

    if not manifest_exists and not adopt:
        collisions = sorted(
            str(path)
            for path in managed_paths(current, target) - {manifest_path}
            if _has_entry(path)
        )
        if collisions:
            details = "\n".join(f"  - {path}" for path in collisions)
            raise SystemExit(
                "Pi adoption required: existing unmanaged managed names found:\n"
                f"{details}\nRun again with --adopt to take ownership."
            )
    return current, previous


def desired_state(
    rendered: Path, target: Path, adopt: bool = False
) -> tuple[dict[Path, str], set[Path]]:
    current, previous = load_and_preflight(rendered, target, adopt)
    files: dict[Path, str] = {}
    for role in current["roles"]:
        source = rendered / "agents" / f"{role}.md"
        files[target / "agents" / source.name] = source.read_text()
    for name in current.get("workflows", []):
        source = rendered / "workflows" / f"{name}.md"
        files[target / MANAGED_ROOT / "workflows" / source.name] = source.read_text()
    for name in current.get("shared", []):
        source = rendered / "_shared" / name
        files[target / MANAGED_ROOT / "_shared" / name] = source.read_text()
    for relative in current.get("managed_extensions", []):
        files[target / relative] = (rendered / relative).read_text()
    files[target / MANIFEST_NAME] = json.dumps(current, indent=2) + "\n"

    stale = managed_paths(previous, target) - managed_paths(current, target)
    return files, stale - set(files)


def validate_installed(files: dict[Path, str], target: Path) -> None:
    manifest = json.loads((target / MANIFEST_NAME).read_text())
    validate_manifest(manifest, "installed manifest")
    missing = sorted(str(path) for path in files if not path.is_file())
    if missing:
        raise RuntimeError(f"Missing installed Pi artifacts: {missing}")
    mismatched = sorted(
        str(path) for path, expected in files.items() if path.read_text() != expected
    )
    if mismatched:
        raise RuntimeError(f"Mismatched installed Pi artifacts: {mismatched}")
    for role in manifest["roles"]:
        path = target / "agents" / f"{role}.md"
        content = path.read_text()
        if not content.startswith("---\n") or "\n---\n" not in content[4:]:
            raise RuntimeError(f"Invalid Pi agent frontmatter: {path}")
        frontmatter = content.split("---", 2)[1]
        names = [line for line in frontmatter.splitlines() if line.startswith("name: ")]
        if names != [f"name: {json.dumps(role)}"]:
            raise RuntimeError(f"Invalid Pi agent definition: {path}")
    profile = manifest["profiles"][0]
    launcher_name = f"pi-{profile}"
    launchers = [path for path in files if path.name == launcher_name]
    if launchers and (len(launchers) != 1 or not os.access(launchers[0], os.X_OK)):
        raise RuntimeError(f"Invalid Pi launcher installation: {launcher_name}")
    if profile == "deepseek":
        try:
            settings = json.loads((target / "settings.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Invalid DeepSeek Pi settings installation") from error
        packages = settings.get("packages", []) if isinstance(settings, dict) else []
        sources = [
            package if isinstance(package, str) else package.get("source")
            for package in packages
            if isinstance(package, (str, dict))
        ]
        installed_names = set()
        for source in sources:
            if isinstance(source, str):
                try:
                    package = json.loads((Path(source) / "package.json").read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(package, dict) and isinstance(package.get("name"), str):
                    installed_names.add(package["name"])
        if not set(DEEPSEEK_REQUIRED_PACKAGE_NAMES).issubset(installed_names):
            raise RuntimeError("Missing required DeepSeek Pi packages")
        try:
            catalog = json.loads((target / DEEPSEEK_MODELS_STORE).read_text())
            _deepseek_store_entry(catalog, "installed models-store.json", exact_name=False)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemExit) as error:
            raise RuntimeError("Invalid DeepSeek Pi models-store installation") from error


def install(
    target: Path,
    dry_run: bool,
    adopt: bool = False,
    validate: bool = True,
    profile: str = "openai",
    bin_dir: Path | None = None,
    source: Path | None = None,
) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    source_files: tuple[str, str, dict[str, str]] | None = None
    if profile == "deepseek":
        source = (source or (Path.home() / ".pi" / "agent")).expanduser().resolve()
        validate_pi_runtime(source, "source Pi")
        for relative in ("settings.json", DEEPSEEK_MODELS_STORE, *DEEPSEEK_MANAGED_EXTENSIONS):
            assert_safe_destination(target / relative, target)
        source_files = deepseek_source_files(source, target)
    resolved_bin = None
    launcher_path = None
    if bin_dir is not None:
        bin_dir = bin_dir.expanduser()
        if bin_dir.is_symlink():
            raise SystemExit(f"Refusing symlinked launcher directory: {bin_dir}")
        resolved_bin = bin_dir.resolve()
        launcher_path = resolved_bin / f"pi-{profile}"
        assert_safe_destination(launcher_path, resolved_bin)
    if not dry_run and profile == "openai":
        validate_pi_runtime(target)
    target_existed = target.exists()
    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        rendered = Path(directory) / "pi"
        subprocess.run(
            [sys.executable, str(RENDER), "--profile", profile, "--output", str(rendered)],
            check=True,
        )
        if source_files is not None:
            settings_content, catalog_content, extension_contents = source_files
            rendered_manifest_path = rendered / "manifest.json"
            rendered_manifest = json.loads(rendered_manifest_path.read_text())
            rendered_manifest["managed_extensions"] = list(DEEPSEEK_MANAGED_EXTENSIONS)
            rendered_manifest_path.write_text(json.dumps(rendered_manifest, indent=2) + "\n")
            for relative, content in extension_contents.items():
                destination = rendered / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content)
        files, deletions = desired_state(rendered, target, adopt)
        manifest_path = target / MANIFEST_NAME
        if launcher_path is None:
            previously_installed = (
                json.loads(manifest_path.read_text()).get("launchers", [])
                if _has_entry(manifest_path)
                else []
            )
            installed_manifest = json.loads(files[manifest_path])
            installed_manifest["launchers"] = previously_installed
            files[manifest_path] = json.dumps(installed_manifest, indent=2) + "\n"
        if profile == "deepseek":
            files[target / "settings.json"] = settings_content
            files[target / DEEPSEEK_MODELS_STORE] = catalog_content
        if launcher_path is not None:
            manifest_exists = _has_entry(manifest_path)
            installed_launchers: list[str] = []
            if manifest_exists:
                installed_manifest = json.loads(manifest_path.read_text())
                installed_launchers = installed_manifest.get("launchers", [])
            if (
                _has_entry(launcher_path)
                and launcher_path.name not in installed_launchers
                and not adopt
            ):
                raise SystemExit(
                    "Pi adoption required: existing unmanaged launcher found:\n"
                    f"  - {launcher_path}\nRun again with --adopt to take ownership."
                )
            launcher = (rendered / launcher_path.name).read_text()
            launcher = re.sub(
                r'^export PI_CODING_AGENT_DIR=.*$',
                f"export PI_CODING_AGENT_DIR={shlex.quote(str(target))}",
                launcher,
                count=1,
                flags=re.MULTILINE,
            )
            files[launcher_path] = launcher
        changed = {
            path: content
            for path, content in files.items()
            if not path.exists()
            or path.read_text() != content
            or (path == launcher_path and not os.access(path, os.X_OK))
        }
        deleted = {path for path in deletions if path.exists()}

        if not changed and not deleted:
            print("Pi configuration is already synchronized.")
            return 0
        for path, content in changed.items():
            relative = (
                path.relative_to(target)
                if path == target or target in path.parents
                else Path("launchers") / path.name
            )
            print(text_diff(path, content, f"generated:{relative}"), end="")
        for path in sorted(deleted):
            print(text_diff(path, "", f"deleted:{path.relative_to(target)}"), end="")
        if dry_run:
            print(f"DRY RUN: {len(changed)} write(s), {len(deleted)} deletion(s).")
            return 0

        affected = set(changed) | deleted
        for path in affected:
            root = resolved_bin if launcher_path is not None and path == launcher_path else target
            assert_safe_destination(path, root)
        originals = {
            path: (
                (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                if path.exists()
                else None
            )
            for path in affected
        }
        created_directories = {
            parent
            for path in affected
            for parent in path.parents
            if parent != target and target in parent.parents and not parent.exists()
        }
        if not target_existed:
            created_directories.add(target)
        if resolved_bin is not None and not resolved_bin.exists():
            created_directories.add(resolved_bin)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_base = Path.home() / ".local" / "state" / "agent-orchestration" / "backups"
        backup_base.mkdir(parents=True, exist_ok=True)
        backup_root = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=backup_base)) / "pi"
        for path, original in originals.items():
            if original is not None:
                prefix = "launcher" if launcher_path is not None and path == launcher_path else "target"
                relative = path.name if prefix == "launcher" else path.relative_to(target)
                backup = backup_root / prefix / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(original[0])

        try:
            for path, content in changed.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                if launcher_path is not None and path == launcher_path:
                    path.chmod(0o755)
            for path in deleted:
                path.unlink()
            if validate:
                validate_installed(files, target)
        except BaseException:
            for path, original in originals.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original[0])
                    path.chmod(original[1])
            for directory in sorted(
                created_directories, key=lambda path: len(path.parts), reverse=True
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            print("Installation failed; all changed files were rolled back.", file=sys.stderr)
            raise

        print(
            f"Installed {len(changed)} write(s), {len(deleted)} deletion(s). "
            f"Backup: {backup_root}"
        )
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("openai", "deepseek"), default="openai")
    parser.add_argument("--target", type=Path)
    parser.add_argument(
        "--source",
        "--base",
        dest="source",
        type=Path,
        help="working Pi profile used to bootstrap an isolated profile",
    )
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local" / "bin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="take ownership of existing managed names on first installation",
    )
    args = parser.parse_args()
    target = args.target or (
        Path.home() / ".pi" / "agent"
        if args.profile == "openai"
        else Path.home() / ".pi" / "profiles" / "deepseek"
    )
    raise SystemExit(
        install(
            target, args.dry_run, args.adopt, not args.skip_validate,
            args.profile, args.bin_dir, args.source,
        )
    )
