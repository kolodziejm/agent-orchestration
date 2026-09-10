#!/usr/bin/env python3
"""Safely install generated pi-subagents definitions into a Pi user directory."""

from __future__ import annotations

import argparse
import difflib
import json
import re
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


def validate_pi_runtime(target: Path) -> tuple[int, int, int]:
    """Require a locally installed, supported pi-subagents release."""
    package_path = target / PI_RUNTIME_PACKAGE
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(
            f"Missing Pi runtime metadata: expected {package_path}"
        ) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Malformed Pi runtime metadata: {package_path}") from error

    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or RELEASE_VERSION.fullmatch(version) is None:
        raise SystemExit(
            f"Malformed Pi runtime metadata: {package_path} has an invalid release version"
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


def _has_entry(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def validate_manifest(manifest: dict, label: str) -> None:
    if manifest.get("format_version") != 1:
        raise SystemExit(f"Unsupported {label} format_version")
    for key in ("roles", "profiles", "workflows", "shared"):
        values = manifest.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise SystemExit(f"Invalid {label} {key}")
        if len(values) != len(set(values)):
            raise SystemExit(f"Duplicate names in {label} {key}")
        for value in values:
            if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
                raise SystemExit(f"Unsafe name in {label} {key}: {value!r}")


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
        }
    )
    validate_manifest(previous, "installed manifest")

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
    files[target / MANIFEST_NAME] = json.dumps(current, indent=2) + "\n"

    stale = managed_paths(previous, target) - managed_paths(current, target)
    return files, stale - set(files)


def validate_installed(files: dict[Path, str], target: Path) -> None:
    manifest = json.loads((target / MANIFEST_NAME).read_text())
    validate_manifest(manifest, "installed manifest")
    missing = sorted(str(path) for path in files if not path.is_file())
    if missing:
        raise RuntimeError(f"Missing installed Pi artifacts: {missing}")
    for role in manifest["roles"]:
        path = target / "agents" / f"{role}.md"
        content = path.read_text()
        if not content.startswith("---\n") or "\n---\n" not in content[4:]:
            raise RuntimeError(f"Invalid Pi agent frontmatter: {path}")
        frontmatter = content.split("---", 2)[1]
        names = [line for line in frontmatter.splitlines() if line.startswith("name: ")]
        if names != [f"name: {json.dumps(role)}"]:
            raise RuntimeError(f"Invalid Pi agent definition: {path}")


def install(
    target: Path,
    dry_run: bool,
    adopt: bool = False,
    validate: bool = True,
) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    if not dry_run:
        validate_pi_runtime(target)
    target_existed = target.exists()
    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        rendered = Path(directory) / "pi"
        subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)
        files, deletions = desired_state(rendered, target, adopt)
        changed = {
            path: content
            for path, content in files.items()
            if not path.exists() or path.read_text() != content
        }
        deleted = {path for path in deletions if path.exists()}

        if not changed and not deleted:
            print("Pi configuration is already synchronized.")
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
        originals = {
            path: path.read_bytes() if path.exists() else None for path in affected
        }
        created_directories = {
            parent
            for path in affected
            for parent in path.parents
            if parent != target and target in parent.parents and not parent.exists()
        }
        if not target_existed:
            created_directories.add(target)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_base = Path.home() / ".local" / "state" / "agent-orchestration" / "backups"
        backup_base.mkdir(parents=True, exist_ok=True)
        backup_root = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=backup_base)) / "pi"
        for path, original in originals.items():
            if original is not None:
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
                validate_installed(files, target)
        except BaseException:
            for path, original in originals.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original)
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
    parser.add_argument("--target", type=Path, default=Path.home() / ".pi" / "agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="take ownership of existing managed names on first installation",
    )
    args = parser.parse_args()
    raise SystemExit(
        install(args.target, args.dry_run, args.adopt, not args.skip_validate)
    )
