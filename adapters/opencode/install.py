#!/usr/bin/env python3.11
"""Install generated OpenCode policy artifacts with diff, backup, rollback, and validation."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "adapters" / "opencode" / "render.py"
MANIFEST_NAME = ".agent-orchestration.manifest.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def text_diff(current: Path, desired: str, label: str) -> str:
    before = current.read_text().splitlines(keepends=True) if current.exists() else []
    after = desired.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(current), tofile=label))


def managed_instruction_paths(target: Path, profiles: set[str]) -> set[str]:
    paths = {str(target / "profiles" / "_shared" / "orchestration-core.md")}
    paths.update(str(target / "profiles" / name / "orchestration.md") for name in profiles)
    return paths


def validate_manifest(manifest: dict, label: str) -> None:
    if manifest.get("format_version") != 1:
        raise SystemExit(f"Unsupported {label} format_version")
    for key in ("roles", "profiles"):
        values = manifest.get(key)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise SystemExit(f"Invalid {label} {key}")
        if len(values) != len(set(values)):
            raise SystemExit(f"Duplicate names in {label} {key}")
        for value in values:
            if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
                raise SystemExit(f"Unsafe name in {label} {key}: {value!r}")


def load_and_preflight_manifests(rendered: Path, target: Path) -> tuple[dict, dict]:
    current_manifest = json.loads((rendered / "manifest.json").read_text())
    validate_manifest(current_manifest, "generated manifest")

    manifest_path = target / MANIFEST_NAME
    assert_safe_destination(manifest_path, target)
    previous_manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {"format_version": 1, "roles": [], "profiles": []}
    )
    validate_manifest(previous_manifest, "installed manifest")

    roles = set(current_manifest["roles"]) | set(previous_manifest["roles"])
    profiles = set(current_manifest["profiles"]) | set(previous_manifest["profiles"])
    paths = {
        target / MANIFEST_NAME,
        target / "profiles" / "_shared" / "orchestration-core.md",
    }
    paths.update(target / "agents" / f"{role}.md" for role in roles)
    for name in profiles:
        paths.add(target / "profiles" / name / "opencode.json")
        paths.add(target / "profiles" / name / "orchestration.md")
    for path in paths:
        assert_safe_destination(path, target)
    return current_manifest, previous_manifest


def desired_state(rendered: Path, target: Path) -> tuple[dict[Path, str], set[Path]]:
    files: dict[Path, str] = {}
    deletions: set[Path] = set()

    current_manifest, previous_manifest = load_and_preflight_manifests(rendered, target)
    manifest_path = target / MANIFEST_NAME
    current_roles = set(current_manifest["roles"])
    previous_roles = set(previous_manifest.get("roles", []))
    current_profiles = set(current_manifest["profiles"])
    previous_profiles = set(previous_manifest.get("profiles", []))
    stale_roles = previous_roles - current_roles
    all_managed_instructions = managed_instruction_paths(target, current_profiles | previous_profiles)

    for role in current_roles:
        source = rendered / "agents" / f"{role}.md"
        files[target / "agents" / source.name] = source.read_text()
    for role in stale_roles:
        deletions.add(target / "agents" / f"{role}.md")

    core = rendered / "profiles" / "_shared" / "orchestration-core.md"
    files[target / "profiles" / "_shared" / core.name] = core.read_text()

    for name in sorted(current_profiles | previous_profiles):
        profile_dir = rendered / "profiles" / name
        config_path = target / "profiles" / name / "opencode.json"
        if name not in current_profiles:
            deletions.add(target / "profiles" / name / "orchestration.md")
        if not config_path.exists():
            if name in current_profiles:
                raise SystemExit(f"Missing target profile config: {config_path}")
            continue

        config = json.loads(config_path.read_text())
        agents = config.setdefault("agent", {})
        roles_to_remove = stale_roles if name in current_profiles else previous_roles
        for role in roles_to_remove:
            agents.pop(role, None)

        existing_instructions = config.get("instructions", [])
        unrelated_instructions = [
            value for value in existing_instructions if value not in all_managed_instructions
        ]

        if name in current_profiles:
            fragment = json.loads((profile_dir / "agent-routing.json").read_text())
            agents.update(fragment["agent"])
            addendum_target = target / "profiles" / name / "orchestration.md"
            files[addendum_target] = (profile_dir / "orchestration.md").read_text()
            config["instructions"] = [
                str(target / "profiles" / "_shared" / "orchestration-core.md"),
                str(addendum_target),
                *unrelated_instructions,
            ]
        else:
            config["instructions"] = unrelated_instructions

        files[config_path] = json.dumps(config, indent=2) + "\n"

    files[manifest_path] = json.dumps(current_manifest, indent=2) + "\n"
    return files, deletions - set(files)


def assert_safe_destination(path: Path, target: Path) -> None:
    resolved_target = target.resolve()
    try:
        path.resolve(strict=False).relative_to(resolved_target)
    except ValueError as error:
        raise SystemExit(f"Refusing path outside target: {path}") from error
    if path.is_symlink():
        raise SystemExit(f"Refusing to replace symlink: {path}")
    current = path.parent
    while current != target:
        if current.is_symlink():
            raise SystemExit(f"Refusing path below symlinked directory: {current}")
        if current == current.parent:
            raise SystemExit(f"Refusing path outside target: {path}")
        current = current.parent


def install(target: Path, dry_run: bool, validate: bool) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        rendered = Path(directory) / "opencode"
        subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)
        files, deletions = desired_state(rendered, target)
        changed = {
            path: content
            for path, content in files.items()
            if not path.exists() or path.read_text() != content
        }
        deleted = {path for path in deletions if path.exists()}

        if not changed and not deleted:
            print("OpenCode configuration is already synchronized.")
            return 0

        for path, content in changed.items():
            print(text_diff(path, content, f"generated:{path.relative_to(target)}"), end="")
        for path in sorted(deleted):
            print(text_diff(path, "", f"deleted:{path.relative_to(target)}"), end="")

        if dry_run:
            print(f"DRY RUN: {len(changed)} write(s), {len(deleted)} deletion(s).")
            return 0

        affected = set(changed) | deleted
        for path in affected:
            assert_safe_destination(path, target)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = (
            Path.home() / ".local" / "state" / "agent-orchestration" / "backups" / stamp / "opencode"
        )
        originals: dict[Path, bytes | None] = {
            path: path.read_bytes() if path.exists() else None for path in affected
        }

        # Complete every backup before the first mutation.
        for path, original in originals.items():
            if original is None:
                continue
            backup = backup_root / path.relative_to(target)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original)

        try:
            for path, content in changed.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            for path in deleted:
                path.unlink()

            if validate:
                for name in sorted(json.loads((rendered / "manifest.json").read_text())["profiles"]):
                    config = target / "profiles" / name / "opencode.json"
                    env = os.environ.copy()
                    env["OPENCODE_CONFIG"] = str(config)
                    subprocess.run(
                        ["opencode", "debug", "config"],
                        cwd=Path.home(),
                        env=env,
                        stdout=subprocess.DEVNULL,
                        check=True,
                    )
        except BaseException:
            for path, original in originals.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original)
            print("Installation failed; all changed files were rolled back.", file=sys.stderr)
            raise

        print(f"Installed {len(changed)} write(s), {len(deleted)} deletion(s). Backup: {backup_root}")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=Path.home() / ".config" / "opencode")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-validate", action="store_true")
    args = parser.parse_args()
    raise SystemExit(install(args.target, args.dry_run, not args.skip_validate))
