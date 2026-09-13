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
PI_USAGE_MINIMUM_VERSION = (0, 31, 1)
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
DIRECT_DEEPSEEK_PROVIDER = {
    "checkedAt": 1_789_053_577_426,
    "lastModified": 1_789_043_590_000,
    "etag": 'W/"6fe6c05f6b94acbd34aa69e48a27e36e"',
    "models": [
        {
            "id": DEEPSEEK_MODEL_ID,
            "name": DEEPSEEK_MODEL_NAME,
            "provider": "deepseek",
            "baseUrl": "https://api.deepseek.com",
            "api": "openai-completions",
            "reasoning": True,
            "input": ["text", "image"],
            "contextWindow": 1_000_000,
            "maxTokens": 384_000,
            "thinkingLevelMap": {
                "minimal": None,
                "low": "low",
                "medium": None,
                "high": "high",
                "max": "max",
            },
            "compat": {
                "thinkingFormat": "deepseek",
                "supportsStore": False,
                "supportsDeveloperRole": False,
                "requiresReasoningContentOnAssistantMessages": True,
                "maxTokensField": "max_tokens",
            },
            "cost": {
                "input": 0.3,
                "output": 1.2,
                "cacheRead": 0.006,
                "cacheWrite": 0,
            },
        }
    ]
}
CATALOG_CREDENTIAL_KEYS = {
    "apikey", "password", "secret", "token", "credential", "credentials",
    "auth", "authorization",
}
PACKAGE_OBJECT_KEYS = {"source", "autoload", "extensions", "skills", "prompts", "themes"}
SAFE_MANAGED_EXTENSION = re.compile(
    r"^extensions/(?:[A-Za-z0-9][A-Za-z0-9._-]*/(?:config|package)\.json|"
    r"agent-orchestration/(?:deepseek-price-status\.js|codex-pace-status\.js|"
    r"codex-pace-core\.mjs|codex-pace-loader\.ts|delegation-ceiling-core\.js|"
    r"delegation-ceiling-planner\.js|delegation-ceiling-reviewer\.js))$"
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


def resolve_source_packages(
    source: Path, required_names: tuple[str, ...] = DEEPSEEK_REQUIRED_PACKAGE_NAMES
) -> tuple[list[object], dict[str, Path]]:
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

    missing = [name for name in required_names if name not in roots_by_name]
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
    inputs = model.get("input")
    if not isinstance(inputs, list) or not {"text", "image"}.issubset(inputs):
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} must support text and image input"
        )
    context_window = model.get("contextWindow")
    max_tokens = model.get("maxTokens")
    if not isinstance(context_window, int) or context_window < 1_000_000:
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} contextWindow is too small"
        )
    if not isinstance(max_tokens, int) or max_tokens < 384_000:
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} maxTokens is too small"
        )
    base_url = model.get("baseUrl", provider.get("baseUrl"))
    api = model.get("api", provider.get("api"))
    if base_url != "https://api.deepseek.com" or api != "openai-completions":
        raise SystemExit(
            f"Malformed DeepSeek models-store provider in {label}: "
            f"{DEEPSEEK_MODEL_ID} is not the official direct DeepSeek endpoint"
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
        _reject_catalog_credentials(provider, label)
    except SystemExit:
        return None
    return provider


def deepseek_catalog_content(source: Path | None, target: Path) -> str:
    """Seed the direct DeepSeek provider while retaining valid target catalog data."""
    target_store_path = target / DEEPSEEK_MODELS_STORE
    assert_safe_destination(target_store_path, target)
    if target_store_path.exists():
        target_store = _read_json_object(target_store_path, "target models-store.json")
        try:
            target_store_text = target_store_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SystemExit(f"Malformed target models-store.json: {target_store_path}") from error
        if _target_deepseek_entry(target_store, "target models-store.json") is not None:
            return target_store_text
    else:
        target_store = {}
    if source is None:
        source_provider = DIRECT_DEEPSEEK_PROVIDER
    else:
        source_store = _read_deepseek_store(
            source / DEEPSEEK_MODELS_STORE, "source models-store.json"
        )
        source_provider = source_store["deepseek"]
    if target_store_path.exists():
        target_store["deepseek"] = json.loads(json.dumps(source_provider))
        return json.dumps(target_store, indent=2) + "\n"
    return json.dumps(
        {"deepseek": json.loads(json.dumps(source_provider))},
        indent=2,
    ) + "\n"


def deepseek_source_files(source: Path, target: Path) -> tuple[str, str, dict[str, str]]:
    packages, roots = resolve_source_packages(source)
    _read_deepseek_store(source / DEEPSEEK_MODELS_STORE, "source models-store.json")
    catalog_content = deepseek_catalog_content(source, target)
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


def validated_mcp_content(path: Path, label: str) -> str:
    """Read an adapter-owned MCP config without interpreting its server schema."""
    if path.is_symlink():
        raise SystemExit(f"Refusing symlinked {label}: {path}")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, child in pairs:
            if key in parsed:
                raise ValueError("duplicate JSON key")
            parsed[key] = child
        return parsed

    def reject_constant(_value: str) -> object:
        raise ValueError("non-standard JSON number")

    try:
        content = path.read_text(encoding="utf-8")
        value = json.loads(
            content,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except FileNotFoundError as error:
        raise SystemExit(f"Missing {label}: {path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"Malformed {label}: {path}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"Malformed {label}: {path} must contain an object")
    servers = value.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise SystemExit(f"Malformed {label}: mcpServers must contain a non-empty object")
    for name, config in servers.items():
        if (
            not isinstance(name, str)
            or SAFE_NAME.fullmatch(name) is None
            or name in {".", ".."}
        ):
            raise SystemExit(f"Malformed {label}: unsafe MCP server name")
        if not isinstance(config, dict) or not config:
            raise SystemExit(f"Malformed {label}: MCP server {name!r} must contain an object")
    return content


def openai_source_files(source: Path) -> tuple[str, str, str, str, str, str]:
    """Build a provider-pure OpenAI root while keeping credential output redacted."""
    validate_pi_runtime(source, "source Pi")
    packages, roots = resolve_source_packages(
        source, ("pi-subagents", "@narumitw/pi-usage")
    )
    usage_manifest = _read_json_object(
        roots["@narumitw/pi-usage"] / "package.json", "source pi-usage package manifest"
    )
    usage_version = usage_manifest.get("version")
    if not isinstance(usage_version, str) or RELEASE_VERSION.fullmatch(usage_version) is None:
        raise SystemExit("Malformed source pi-usage package version")
    if tuple(int(part) for part in usage_version.split(".")) < PI_USAGE_MINIMUM_VERSION:
        minimum = ".".join(str(part) for part in PI_USAGE_MINIMUM_VERSION)
        raise SystemExit(f"Unsupported pi-usage runtime {usage_version}; minimum is {minimum}")
    usage_root = roots["@narumitw/pi-usage"]
    usage_index = usage_root / "dist" / "index.ts"
    pi_manifest = usage_manifest.get("pi")
    extensions = pi_manifest.get("extensions") if isinstance(pi_manifest, dict) else None
    if not isinstance(extensions, list) or not any(
        isinstance(entry, str)
        and not Path(entry).is_absolute()
        and (usage_root / entry).resolve() == usage_index.resolve()
        for entry in extensions
    ):
        raise SystemExit("Source pi-usage package is missing its Pi extension manifest")
    try:
        usage_exports = usage_index.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SystemExit(f"Missing source pi-usage public entrypoint: {usage_index}") from error
    for name in ("adapterForProvider", "resolveUsageAuth", "queryProviderUsage"):
        if name not in usage_exports:
            raise SystemExit(f"Source pi-usage entrypoint does not export {name}")

    settings = _read_json_object(source / "settings.json", "source Pi settings")
    settings["packages"] = packages
    settings["defaultProvider"] = "openai-codex"
    settings["defaultModel"] = "gpt-5.6-sol"
    settings["defaultThinkingLevel"] = "medium"

    catalog = _read_json_object(source / DEEPSEEK_MODELS_STORE, "source models-store.json")
    provider = catalog.get("openai-codex")
    if not isinstance(provider, dict) or not isinstance(provider.get("models"), list):
        raise SystemExit("Source models-store.json is missing openai-codex models")
    model_ids = {
        model.get("id") for model in provider["models"] if isinstance(model, dict)
    }
    if not {"gpt-5.6-sol", "gpt-5.6-luna"}.issubset(model_ids):
        raise SystemExit("Source openai-codex catalog is missing required models")
    _reject_catalog_credentials(provider, "source openai-codex models-store provider")

    auth = _read_json_object(source / "auth.json", "source Pi auth")
    credential = auth.get("openai-codex")
    if not isinstance(credential, dict) or credential.get("type") != "oauth":
        raise SystemExit("Source Pi OpenAI Codex OAuth is not ready")
    if not all(
        isinstance(credential.get(key), str) and credential[key]
        for key in ("access", "refresh")
    ):
        raise SystemExit("Source Pi OpenAI Codex OAuth is incomplete")

    runtime_manifest = (source / PI_RUNTIME_PACKAGE).read_text(encoding="utf-8")
    mcp_content = validated_mcp_content(source / "mcp.json", "source Pi MCP configuration")
    return (
        json.dumps(settings, indent=2) + "\n",
        json.dumps({"openai-codex": provider}, indent=2) + "\n",
        runtime_manifest,
        json.dumps({"openai-codex": credential}, indent=2) + "\n",
        str(usage_index),
        mcp_content,
    )


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
    previous_profiles = previous.get("profiles")
    current_profiles = current.get("profiles")
    legacy_main_migration = previous_profiles == ["openai"] and current_profiles == ["hybrid"]
    if manifest_exists and previous_profiles != current_profiles and not legacy_main_migration:
        raise SystemExit(
            "Pi profile mismatch: the target is managed for "
            f"{previous_profiles!r}, not {current_profiles!r}"
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
    status_entrypoints = {
        "hybrid": "./deepseek-price-status.js",
        "openai": "./codex-pace-loader.ts",
        "deepseek": None,
    }
    expected_status_entrypoint = status_entrypoints.get(profile)
    package_path = target / "extensions/agent-orchestration/package.json"
    try:
        status_package = json.loads(package_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Invalid installed Pi status extension package") from error
    expected_status_package = {
        "type": "module",
        "pi": {"extensions": [expected_status_entrypoint] if expected_status_entrypoint else []},
    }
    if status_package != expected_status_package:
        raise RuntimeError("Invalid installed Pi status extension package")
    if expected_status_entrypoint is not None:
        entrypoint_path = package_path.parent / expected_status_entrypoint
        if not entrypoint_path.is_file():
            raise RuntimeError("Missing installed Pi status extension entrypoint")

    child_extensions = {
        "planner": "delegation-ceiling-planner.js",
        "reviewer": "delegation-ceiling-reviewer.js",
    }
    managed_extensions = set(manifest.get("managed_extensions", []))
    for extension_name in (
        "delegation-ceiling-core.js",
        *child_extensions.values(),
        "package.json",
    ):
        managed_reference = f"extensions/agent-orchestration/{extension_name}"
        if managed_reference not in managed_extensions:
            raise RuntimeError("Pi child-only extension is not manifest-owned")
        if not (target / managed_reference).is_file():
            raise RuntimeError("Missing installed Pi child-only extension")
    for role, extension_name in child_extensions.items():
        agent_path = target / "agents" / f"{role}.md"
        expected_reference = f"../extensions/agent-orchestration/{extension_name}"
        reference = next(
            (
                line.split(": ", 1)[1]
                for line in agent_path.read_text().splitlines()
                if line.startswith("subagentOnlyExtensions: ")
            ),
            None,
        )
        if reference != expected_reference:
            raise RuntimeError(f"Invalid Pi child-only extension reference: {agent_path}")
        managed_reference = f"extensions/agent-orchestration/{extension_name}"
        if managed_reference not in managed_extensions:
            raise RuntimeError("Pi child-only extension is not manifest-owned")
        extension_path = agent_path.parent / reference
        if not extension_path.is_file():
            raise RuntimeError("Missing installed Pi child-only extension")
    launcher_name = f"pi-{profile}"
    launchers = [path for path in files if path.name == launcher_name]
    if launchers and (len(launchers) != 1 or not os.access(launchers[0], os.X_OK)):
        raise RuntimeError(f"Invalid Pi launcher installation: {launcher_name}")
    if profile in {"hybrid", "deepseek"}:
        try:
            catalog = json.loads((target / DEEPSEEK_MODELS_STORE).read_text())
            _deepseek_store_entry(catalog, "installed models-store.json", exact_name=False)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemExit) as error:
            raise RuntimeError("Invalid DeepSeek Pi models-store installation") from error
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
    if profile == "openai":
        validate_pi_runtime(target)
        try:
            settings = json.loads((target / "settings.json").read_text())
            catalog = json.loads((target / DEEPSEEK_MODELS_STORE).read_text())
            auth = json.loads((target / "auth.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Invalid OpenAI Pi bootstrap files") from error
        if settings.get("defaultProvider") != "openai-codex":
            raise RuntimeError("Invalid OpenAI Pi default provider")
        if set(catalog) != {"openai-codex"} or set(auth) != {"openai-codex"}:
            raise RuntimeError("OpenAI Pi profile is not provider-pure")
        if auth["openai-codex"].get("type") != "oauth":
            raise RuntimeError("OpenAI Pi OAuth is not ready")
        if stat.S_IMODE((target / "auth.json").stat().st_mode) != 0o600:
            raise RuntimeError("OpenAI Pi auth permissions are not private")
        mcp_path = target / "mcp.json"
        try:
            validated_mcp_content(mcp_path, "installed Pi MCP configuration")
        except SystemExit as error:
            raise RuntimeError("Invalid OpenAI Pi MCP configuration") from error
        if stat.S_IMODE(mcp_path.stat().st_mode) & 0o077:
            raise RuntimeError("OpenAI Pi MCP permissions are not private")


def private_mcp_mode(path: Path) -> int:
    """Retain a stricter owner-only mode, otherwise enforce read/write for the owner."""
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode in {0o200, 0o400, 0o600}:
            return mode
    return 0o600


def atomic_write_private(path: Path, content: str, mode: int) -> None:
    """Replace a sensitive file atomically with its private mode already applied."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(
    target: Path,
    dry_run: bool,
    adopt: bool = False,
    validate: bool = True,
    profile: str = "hybrid",
    bin_dir: Path | None = None,
    source: Path | None = None,
) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    source_files: tuple[str, str, dict[str, str]] | None = None
    openai_files: tuple[str, str, str, str, str, str] | None = None
    catalog_content: str | None = None
    if profile == "deepseek":
        source = (source or (Path.home() / ".pi" / "agent")).expanduser().resolve()
        validate_pi_runtime(source, "source Pi")
        for relative in ("settings.json", DEEPSEEK_MODELS_STORE, *DEEPSEEK_MANAGED_EXTENSIONS):
            assert_safe_destination(target / relative, target)
        source_files = deepseek_source_files(source, target)
        catalog_content = source_files[1]
    elif profile == "hybrid":
        catalog_source = source.expanduser().resolve() if source is not None else None
        catalog_content = deepseek_catalog_content(catalog_source, target)
    elif profile == "openai":
        source = (source or (Path.home() / ".pi" / "agent")).expanduser().resolve()
        if source.exists() or not dry_run:
            openai_files = openai_source_files(source)
    resolved_bin = None
    launcher_path = None
    if bin_dir is not None:
        bin_dir = bin_dir.expanduser()
        if bin_dir.is_symlink():
            raise SystemExit(f"Refusing symlinked launcher directory: {bin_dir}")
        resolved_bin = bin_dir.resolve()
        launcher_path = resolved_bin / f"pi-{profile}"
        assert_safe_destination(launcher_path, resolved_bin)
    if not dry_run and profile == "hybrid":
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
            rendered_manifest["managed_extensions"] = sorted(
                set(rendered_manifest.get("managed_extensions", []))
                | set(DEEPSEEK_MANAGED_EXTENSIONS)
            )
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
        if catalog_content is not None:
            files[target / DEEPSEEK_MODELS_STORE] = catalog_content
        sensitive_paths: dict[Path, str] = {}
        sensitive_modes: dict[Path, int] = {}
        if openai_files is not None:
            (
                settings_content, openai_catalog, runtime_manifest, auth_content,
                usage_entrypoint, mcp_content,
            ) = openai_files
            files[target / "settings.json"] = settings_content
            files[target / DEEPSEEK_MODELS_STORE] = openai_catalog
            files[target / PI_RUNTIME_PACKAGE] = runtime_manifest
            auth_path = target / "auth.json"
            files[auth_path] = auth_content
            sensitive_paths[auth_path] = "Credential"
            sensitive_modes[auth_path] = 0o600
            mcp_path = target / "mcp.json"
            assert_safe_destination(mcp_path, target)
            files[mcp_path] = mcp_content
            sensitive_paths[mcp_path] = "MCP"
            sensitive_modes[mcp_path] = private_mcp_mode(mcp_path)
            loader_path = target / "extensions/agent-orchestration/codex-pace-loader.ts"
            loader = files.get(loader_path)
            if loader is None or loader.count("__PI_USAGE_ENTRYPOINT__") != 1:
                raise SystemExit("Generated Codex pace loader has an invalid package placeholder")
            files[loader_path] = loader.replace("__PI_USAGE_ENTRYPOINT__", usage_entrypoint)
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
            or (path in sensitive_modes and stat.S_IMODE(path.stat().st_mode) != sensitive_modes[path])
            or (path == launcher_path and not os.access(path, os.X_OK))
        }
        deleted = {path for path in deletions if path.exists()}

        if not changed and not deleted:
            print("Pi configuration is already synchronized.")
            return 0
        for path, content in changed.items():
            if path in sensitive_paths:
                print(
                    f"{sensitive_paths[path]} synchronization required "
                    f"(contents redacted): {path}"
                )
                continue
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
                if path in sensitive_paths:
                    backup.chmod(0o600)

        try:
            for path, content in changed.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                if path in sensitive_modes:
                    atomic_write_private(path, content, sensitive_modes[path])
                else:
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
    parser.add_argument(
        "--profile", choices=("hybrid", "openai", "deepseek"), default="hybrid"
    )
    parser.add_argument("--target", type=Path)
    parser.add_argument(
        "--source",
        "--base",
        dest="source",
        type=Path,
        help="Pi root supplying a validated DeepSeek catalog/provider bootstrap",
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
        if args.profile == "hybrid"
        else Path.home() / ".pi" / "profiles" / args.profile
    )
    raise SystemExit(
        install(
            target, args.dry_run, args.adopt, not args.skip_validate,
            args.profile, args.bin_dir, args.source,
        )
    )
