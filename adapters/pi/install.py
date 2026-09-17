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
DEEPSEEK_MODELS_STORE = "models-store.json"
DEEPSEEK_MODEL_ID = "deepseek-flash"
DEEPSEEK_MODEL_NAME = "DeepSeek V4.1 Flash"
DEEPSEEK_THINKING_LEVELS = ("low", "high", "max")
GLM_PROVIDER_ID = "zai"
GLM_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
GLM_MODELS_STORE = "models-store.json"
GLM_MODEL_IDS = ("glm-5.3", "glm-5.3-flash")
GLM_THINKING_LEVELS = ("low", "high", "max")
DIRECT_GLM_PROVIDER = {
    "baseUrl": GLM_BASE_URL,
    "api": "openai-completions",
    "models": [
        {
            "id": "glm-5.3",
            "name": "GLM-5.3",
            "provider": GLM_PROVIDER_ID,
            "baseUrl": GLM_BASE_URL,
            "api": "openai-completions",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 1_000_000,
            "maxTokens": 131_072,
            "thinkingLevelMap": {
                "low": "low",
                "high": "high",
                "max": "max",
            },
        },
        {
            "id": "glm-5.3-flash",
            "name": "GLM-5.3 Flash",
            "provider": GLM_PROVIDER_ID,
            "baseUrl": GLM_BASE_URL,
            "api": "openai-completions",
            "reasoning": True,
            "input": ["text", "image"],
            "contextWindow": 1_000_000,
            "maxTokens": 131_072,
            "thinkingLevelMap": {
                "low": "low",
                "high": "high",
                "max": "max",
            },
        },
    ],
}
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
SAFE_MANAGED_EXTENSION = re.compile(
    r"^extensions/(?:[A-Za-z0-9][A-Za-z0-9._-]*/(?:config|package)\.json|"
    r"agent-orchestration/(?:deepseek-price-status\.js|glm-price-status\.js|"
    r"codex-pace-status\.js|codex-pace-core\.mjs|codex-pace-loader\.ts|"
    r"delegation-ceiling-core\.js|delegation-ceiling-planner\.js|"
    r"delegation-ceiling-reviewer\.js|git-read\.ts|primary-policy\.js))$"
)
SAFE_MANAGED_FILE = re.compile(r"^themes/[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
# Migration-only compatibility: these paths may appear in an older manifest,
# but are not rendered, copied, validated, or claimed by the current installer.
LEGACY_OPERATOR_MANAGED_EXTENSIONS = frozenset({
    "extensions/pi-permission-system/config.json",
    "extensions/pi-permission-system/package.json",
})
LEGACY_RETIRED_PLANNING_GUARD = "extensions/agent-orchestration/planning-artifact-guard.js"


def text_diff(current: Path, desired: str, label: str) -> str:
    before = current.read_text().splitlines(keepends=True) if current.exists() else []
    after = desired.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(current), tofile=label))


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
                raise SystemExit(f"Refusing credentials in models-store cache: {label}")
            _reject_catalog_credentials(child, label)
    elif isinstance(value, list):
        for child in value:
            _reject_catalog_credentials(child, label)


def _glm_model(provider: object, label: str, model_id: str, expected_input: list[str]) -> dict:
    if not isinstance(provider, dict):
        raise SystemExit(f"Malformed GLM models-store provider in {label}")
    models = provider.get("models")
    if not isinstance(models, list):
        raise SystemExit(f"Malformed GLM models-store provider in {label}: models must be an array")
    matches = [model for model in models if isinstance(model, dict) and model.get("id") == model_id]
    if len(matches) != 1:
        raise SystemExit(
            f"Malformed GLM models-store provider in {label}: "
            f"expected exactly one {model_id} model"
        )
    model = matches[0]
    if model.get("provider") != GLM_PROVIDER_ID:
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid provider")
    if model.get("baseUrl", provider.get("baseUrl")) != GLM_BASE_URL:
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid endpoint")
    if model.get("api", provider.get("api")) != "openai-completions":
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid API")
    if model.get("reasoning") is not True:
        raise SystemExit(f"Malformed GLM models-store provider in {label}: reasoning is not enabled")
    if model.get("input") != expected_input:
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid input modalities")
    if model.get("contextWindow") != 1_000_000:
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid context window")
    thinking = model.get("thinkingLevelMap")
    if thinking != {level: level for level in GLM_THINKING_LEVELS}:
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid thinking levels")
    return model


def _glm_store_entry(catalog: object, label: str) -> dict:
    if not isinstance(catalog, dict) or set(catalog) != {GLM_PROVIDER_ID}:
        raise SystemExit(
            f"Malformed GLM models-store cache: {label} must contain only {GLM_PROVIDER_ID}"
        )
    provider = catalog.get(GLM_PROVIDER_ID)
    if not isinstance(provider, dict):
        raise SystemExit(f"Malformed GLM models-store cache: {label} is missing {GLM_PROVIDER_ID}")
    if provider.get("baseUrl") != GLM_BASE_URL or provider.get("api") != "openai-completions":
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid endpoint")
    models = provider.get("models")
    if not isinstance(models, list) or len(models) != len(GLM_MODEL_IDS):
        raise SystemExit(f"Malformed GLM models-store provider in {label}: invalid model set")
    _glm_model(provider, label, "glm-5.3", ["text"])
    _glm_model(provider, label, "glm-5.3-flash", ["text", "image"])
    _reject_catalog_credentials(provider, label)
    return provider


def _target_glm_catalog_is_valid(catalog: object, label: str) -> bool:
    """Recognize a target catalog that contains only the official GLM provider.

    Foreign providers, malformed primary data, or embedded credentials are
    replaced by the credential-free direct catalog.
    """
    if not isinstance(catalog, dict):
        return False
    if GLM_PROVIDER_ID not in catalog:
        return False
    if any(key != GLM_PROVIDER_ID for key in catalog):
        return False
    try:
        primary = catalog[GLM_PROVIDER_ID]
        if not isinstance(primary, dict):
            return False
        if primary.get("baseUrl") != GLM_BASE_URL or primary.get("api") != "openai-completions":
            return False
        models = primary.get("models")
        if not isinstance(models, list) or len(models) != len(GLM_MODEL_IDS):
            return False
        _glm_model(primary, label, "glm-5.3", ["text"])
        _glm_model(primary, label, "glm-5.3-flash", ["text", "image"])
        for provider in catalog.values():
            _reject_catalog_credentials(provider, label)
    except SystemExit:
        return False
    return True


def glm_catalog_content(target: Path) -> str:
    """Retain valid GLM catalog state, otherwise seed a direct GLM catalog."""
    target_store_path = target / GLM_MODELS_STORE
    assert_safe_destination(target_store_path, target)
    if target_store_path.exists():
        target_store = _read_json_object(target_store_path, "target GLM models-store.json")
        try:
            target_store_text = target_store_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SystemExit(f"Malformed target GLM models-store.json: {target_store_path}") from error
        if _target_glm_catalog_is_valid(target_store, "target GLM models-store.json"):
            return target_store_text
    return json.dumps(
        {GLM_PROVIDER_ID: json.loads(json.dumps(DIRECT_GLM_PROVIDER))},
        indent=2,
    ) + "\n"


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
    legacy_extensions = (
        {LEGACY_RETIRED_PLANNING_GUARD}
        if label == "installed manifest"
        else set()
    )
    if not isinstance(extensions, list) or not all(
        isinstance(value, str)
        and (SAFE_MANAGED_EXTENSION.fullmatch(value) or value in legacy_extensions)
        for value in extensions
    ):
        raise SystemExit(f"Invalid {label} managed_extensions")
    if len(extensions) != len(set(extensions)):
        raise SystemExit(f"Duplicate names in {label} managed_extensions")
    managed_files = manifest.get("managed_files", [])
    if not isinstance(managed_files, list) or not all(
        isinstance(value, str) and SAFE_MANAGED_FILE.fullmatch(value)
        for value in managed_files
    ):
        raise SystemExit(f"Invalid {label} managed_files")
    if len(managed_files) != len(set(managed_files)):
        raise SystemExit(f"Duplicate names in {label} managed_files")
    if any(value in {"themes/dark.json", "themes/light.json"} for value in managed_files):
        raise SystemExit(f"Built-in Pi themes cannot be managed in {label}")
    if label == "generated manifest":
        if any(value in LEGACY_OPERATOR_MANAGED_EXTENSIONS or value == LEGACY_RETIRED_PLANNING_GUARD for value in extensions):
            raise SystemExit("Generated manifest contains retired or operator-owned Pi paths")
        if managed_files:
            raise SystemExit("Generated manifest cannot claim operator-owned Pi files")


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
    paths.update(target / relative for relative in manifest.get("managed_files", []))
    return paths


def legacy_operator_paths(manifest: dict, target: Path) -> set[Path]:
    """Return prior operator-owned claims that must survive manifest migration."""
    paths = {
        target / relative
        for relative in manifest.get("managed_extensions", [])
        if relative in LEGACY_OPERATOR_MANAGED_EXTENSIONS
    }
    paths.update(target / relative for relative in manifest.get("managed_files", []))
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

    operator_paths = legacy_operator_paths(previous, target)
    for path in (managed_paths(current, target) | managed_paths(previous, target)) - operator_paths:
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
    for relative in current.get("managed_files", []):
        source = rendered / relative
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"Missing or linked generated Pi managed file: {source}")
        files[target / relative] = source.read_text(encoding="utf-8")
    files[target / MANIFEST_NAME] = json.dumps(current, indent=2) + "\n"

    stale = managed_paths(previous, target) - managed_paths(current, target)
    stale -= legacy_operator_paths(previous, target)
    return files, stale - set(files)


def validate_installed(files: dict[Path, str], target: Path) -> None:
    manifest_path = target / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"Invalid installed Pi manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest, "installed manifest")

    # ``files`` also contains compatibility bootstrap and operator-runtime
    # paths for profiles that still synthesize them.  Post-install validation
    # must remain scoped to the rendered bundle and any launcher being written;
    # those runtime paths are deliberately opaque to this check.
    bundle_paths = managed_paths(manifest, target) - legacy_operator_paths(manifest, target)
    bundle_files = {
        path: expected for path, expected in files.items() if path in bundle_paths
    }
    launchers = [
        path
        for path in files
        if path not in bundle_paths and path.name in manifest["launchers"]
    ]
    validation_paths = bundle_paths | set(launchers)
    linked = sorted(str(path) for path in validation_paths if path.is_symlink())
    if linked:
        raise RuntimeError(f"Symlinked installed Pi artifacts: {linked}")
    missing_paths = [path for path in validation_paths if not path.is_file()]
    if missing_paths:
        missing = sorted(str(path) for path in missing_paths)
        child_names = {
            "delegation-ceiling-core.js",
            "delegation-ceiling-planner.js",
            "delegation-ceiling-reviewer.js",
            "git-read.ts",
            "package.json",
        }
        if any(path.name in child_names for path in missing_paths):
            raise RuntimeError(f"Missing installed Pi child-only extension: {missing}")
        raise RuntimeError(f"Missing installed Pi artifacts: {missing}")
    expected_files = {**bundle_files, **{path: files[path] for path in launchers}}
    mismatched = sorted(
        str(path) for path, expected in expected_files.items() if path.read_text() != expected
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
        tool_lines = [line for line in frontmatter.splitlines() if line.startswith("tools: ")]
        if len(tool_lines) != 1:
            raise RuntimeError(f"Invalid Pi agent tool allowlist: {path}")
        tool_names = [name.strip() for name in tool_lines[0].removeprefix("tools: ").split(",") if name.strip()]
        acceptance_role_lines = [
            line for line in frontmatter.splitlines() if line.startswith("acceptanceRole:")
        ]
        if role == "explorer":
            if acceptance_role_lines != ["acceptanceRole: read-only"]:
                raise RuntimeError("Invalid Pi explorer acceptanceRole")
            if "git_read" not in tool_names or "bash" in tool_names:
                raise RuntimeError("Invalid Pi explorer Git reader allowlist")
        else:
            if acceptance_role_lines:
                raise RuntimeError(f"Pi acceptanceRole leaked to role: {role}")
            if "git_read" in tool_names:
                raise RuntimeError(f"Pi Git reader leaked to role: {role}")
    profile = manifest["profiles"][0]
    status_entrypoints = {
        "hybrid": "./deepseek-price-status.js",
        "openai": "./codex-pace-loader.ts",
        "deepseek": "./deepseek-price-status.js",
        "glm": "./glm-price-status.js",
    }
    expected_status_entrypoint = status_entrypoints.get(profile)
    managed_extensions = set(manifest.get("managed_extensions", []))
    package_relative = "extensions/agent-orchestration/package.json"
    if package_relative not in managed_extensions:
        raise RuntimeError("Pi status extension package is not manifest-owned")
    package_path = target / package_relative
    try:
        status_package = json.loads(package_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Invalid installed Pi status extension package") from error
    expected_status_package = {
        "type": "module",
        "pi": {
            "extensions": ["./primary-policy.js"]
            + ([expected_status_entrypoint] if expected_status_entrypoint else [])
            + ["./git-read.ts"],
        },
    }
    if status_package != expected_status_package:
        raise RuntimeError("Invalid installed Pi status extension package")
    if expected_status_entrypoint is not None:
        entrypoint_path = package_path.parent / expected_status_entrypoint
        entrypoint_relative = (
            f"extensions/agent-orchestration/{expected_status_entrypoint.removeprefix('./')}"
        )
        if entrypoint_relative not in managed_extensions:
            raise RuntimeError("Pi status extension is not manifest-owned")
        if not entrypoint_path.is_file() or entrypoint_path.is_symlink():
            raise RuntimeError("Missing installed Pi status extension entrypoint")

    child_extensions = {
        "planner": "delegation-ceiling-planner.js",
        "reviewer": "delegation-ceiling-reviewer.js",
    }
    primary_extension = "extensions/agent-orchestration/primary-policy.js"
    if primary_extension not in managed_extensions:
        raise RuntimeError("Pi primary policy extension is not manifest-owned")
    primary_path = target / primary_extension
    if primary_path.is_symlink() or not primary_path.is_file():
        raise RuntimeError("Missing installed Pi primary policy extension")

    for extension_name in (
        "delegation-ceiling-core.js",
        *child_extensions.values(),
        "git-read.ts",
        "package.json",
    ):
        managed_reference = f"extensions/agent-orchestration/{extension_name}"
        if managed_reference not in managed_extensions:
            raise RuntimeError("Pi child-only extension is not manifest-owned")
        managed_path = target / managed_reference
        if managed_path.is_symlink() or not managed_path.is_file():
            raise RuntimeError("Missing installed Pi child-only extension")
    for role, extension_name in child_extensions.items():
        agent_path = target / "agents" / f"{role}.md"
        expected_reference = f"../extensions/agent-orchestration/{extension_name}"
        references = []
        for line in agent_path.read_text().splitlines():
            if line.startswith("subagentOnlyExtensions: "):
                references.extend(
                    item.strip() for item in line.split(": ", 1)[1].split(",") if item.strip()
                )
        if expected_reference not in references:
            raise RuntimeError(f"Invalid Pi child-only extension reference: {agent_path}")
        managed_reference = f"extensions/agent-orchestration/{extension_name}"
        if managed_reference not in managed_extensions:
            raise RuntimeError("Pi child-only extension is not manifest-owned")
        extension_path = agent_path.parent / expected_reference
        if not extension_path.is_file():
            raise RuntimeError("Missing installed Pi child-only extension")
    invalid_launchers = [
        path for path in launchers
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK)
    ]
    if invalid_launchers:
        names = sorted(path.name for path in invalid_launchers)
        raise RuntimeError(f"Invalid Pi launcher installation: {names}")


def install(
    target: Path,
    dry_run: bool,
    adopt: bool = False,
    validate: bool = True,
    profile: str = "hybrid",
    bin_dir: Path | None = None,
    source: Path | None = None,
) -> int:
    """Synchronize only the rendered bundle and its declared launcher.

    ``source`` remains in the call contract while older CLI layers are retired;
    it is intentionally unused.  The rendered manifest is the only source of
    target ownership, so operator runtime state is opaque to this transaction.
    """
    del source
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()

    resolved_bin = None
    launcher_paths: set[Path] = set()
    if bin_dir is not None:
        bin_dir = bin_dir.expanduser()
        if bin_dir.is_symlink():
            raise SystemExit(f"Refusing symlinked launcher directory: {bin_dir}")
        resolved_bin = bin_dir.resolve()

    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        rendered = Path(directory) / "pi"
        subprocess.run(
            [sys.executable, str(RENDER), "--profile", profile, "--output", str(rendered)],
            check=True,
        )
        rendered_manifest_path = rendered / "manifest.json"
        try:
            rendered_manifest = json.loads(rendered_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SystemExit(f"Malformed generated Pi manifest: {rendered_manifest_path}") from error
        validate_manifest(rendered_manifest, "generated manifest")

        files, deletions = desired_state(rendered, target, adopt)
        manifest_path = target / MANIFEST_NAME
        declared_launchers = rendered_manifest.get("launchers", [])
        if resolved_bin is None:
            previously_installed = (
                json.loads(manifest_path.read_text(encoding="utf-8")).get("launchers", [])
                if _has_entry(manifest_path)
                else []
            )
            installed_manifest = json.loads(files[manifest_path])
            installed_manifest["launchers"] = previously_installed
            files[manifest_path] = json.dumps(installed_manifest, indent=2) + "\n"
        else:
            installed_launchers = (
                json.loads(manifest_path.read_text(encoding="utf-8")).get("launchers", [])
                if _has_entry(manifest_path)
                else []
            )
            for launcher_name in declared_launchers:
                launcher_path = resolved_bin / launcher_name
                assert_safe_destination(launcher_path, resolved_bin)
                if (
                    _has_entry(launcher_path)
                    and launcher_name not in installed_launchers
                    and not adopt
                ):
                    raise SystemExit(
                        "Pi adoption required: existing unmanaged launcher found:\n"
                        f"  - {launcher_path}\nRun again with --adopt to take ownership."
                    )
                launcher_source = rendered / launcher_name
                if not launcher_source.is_file() or launcher_source.is_symlink():
                    raise SystemExit(f"Missing or linked generated Pi launcher: {launcher_source}")
                launcher = launcher_source.read_text(encoding="utf-8")
                # GLM's launcher is intentionally tied to its canonical isolated
                # profile root. Other profiles retain the existing --target
                # override used by isolated installer fixtures.
                if profile != "glm":
                    launcher = re.sub(
                        r'^export PI_CODING_AGENT_DIR=.*$',
                        f"export PI_CODING_AGENT_DIR={shlex.quote(str(target))}",
                        launcher,
                        count=1,
                        flags=re.MULTILINE,
                    )
                files[launcher_path] = launcher
                launcher_paths.add(launcher_path)

        changed = {
            path: content
            for path, content in files.items()
            if not path.exists()
            or path.read_bytes() != content.encode("utf-8")
            or (path in launcher_paths and not os.access(path, os.X_OK))
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
            root = resolved_bin if path in launcher_paths else target
            assert_safe_destination(path, root)
        originals = {
            path: (
                (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                if path.exists()
                else None
            )
            for path in affected
        }
        created_directories: set[Path] = set()
        for path in affected:
            parent = path.parent
            while not parent.exists():
                created_directories.add(parent)
                if parent == parent.parent:
                    break
                parent = parent.parent
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_base = Path.home() / ".local" / "state" / "agent-orchestration" / "backups"
        backup_base.mkdir(parents=True, exist_ok=True)
        backup_root = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=backup_base)) / "pi"
        for path, original in originals.items():
            if original is not None:
                prefix = "launcher" if path in launcher_paths else "target"
                relative = path.name if prefix == "launcher" else path.relative_to(target)
                backup = backup_root / prefix / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(original[0])

        try:
            for path, content in changed.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                if path in launcher_paths:
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
        "--profile", choices=("hybrid", "openai", "deepseek", "glm"), default="hybrid"
    )
    parser.add_argument("--target", type=Path)
    parser.add_argument(
        "--source",
        "--base",
        dest="source",
        type=Path,
        help="Deprecated staging option; accepted for compatibility but ignored",
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
