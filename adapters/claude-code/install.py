#!/usr/bin/env python3
"""Install generated Claude Code policy artifacts with diff, backup, and rollback."""

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
RENDER = ROOT / "adapters" / "claude-code" / "render.py"
MANIFEST_NAME = ".agent-orchestration.manifest.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MARKER_START = "<!-- agent-orchestration:start -->"
MARKER_END = "<!-- agent-orchestration:end -->"
MARKER_PATTERN = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)
CONTROL_PLANE_NOTE = Path("_shared") / "control-plane.md"


def text_diff(current: Path, desired: str, label: str) -> str:
    before = current.read_text().splitlines(keepends=True) if current.exists() else []
    after = desired.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(current), tofile=label))


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
    control_plane = manifest.get("control_plane", False)
    if not isinstance(control_plane, bool):
        raise SystemExit(f"Invalid {label} control_plane")
    workflows = manifest.get("workflows", [])
    if not isinstance(workflows, list) or not all(isinstance(value, str) for value in workflows):
        raise SystemExit(f"Invalid {label} workflows")
    if len(workflows) != len(set(workflows)):
        raise SystemExit(f"Duplicate names in {label} workflows")
    for value in workflows:
        if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
            raise SystemExit(f"Unsafe name in {label} workflows: {value!r}")


def _has_entry(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def unmanaged_collisions(current_manifest: dict, target: Path) -> list[str]:
    """Find managed names already present before this adapter was adopted."""
    collisions = [
        str(target / "agents" / f"{role}.md")
        for role in sorted(current_manifest["roles"])
        if _has_entry(target / "agents" / f"{role}.md")
    ]
    collisions.extend(
        str(target / "workflows" / f"{workflow}.md")
        for workflow in sorted(current_manifest.get("workflows", []))
        if _has_entry(target / "workflows" / f"{workflow}.md")
    )
    claude_md = target / "CLAUDE.md"
    if _has_entry(claude_md):
        collisions.append(str(claude_md))
    control_note = target / CONTROL_PLANE_NOTE
    if _has_entry(control_note):
        collisions.append(str(control_note))
    return collisions


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


def merge_claude_md(existing: str, section: str) -> str:
    """Replace the marker-delimited managed section, or append it, preserving the rest."""
    start_count = existing.count(MARKER_START)
    end_count = existing.count(MARKER_END)
    if start_count == 0 and end_count == 0:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing:
            existing += "\n"
        return existing + section
    if start_count == 1 and end_count == 1 and existing.index(MARKER_START) < existing.index(MARKER_END):
        return MARKER_PATTERN.sub(lambda _match: section.strip("\n"), existing)
    raise SystemExit(
        "CLAUDE.md contains malformed agent-orchestration markers "
        f"({MARKER_START!r}: {start_count}, {MARKER_END!r}: {end_count}); "
        "expected zero of both or exactly one well-formed start-before-end pair. "
        "Repair CLAUDE.md manually before installing."
    )


def load_and_preflight_manifests(
    rendered: Path, target: Path, adopt: bool = False
) -> tuple[dict, dict]:
    current_manifest = json.loads((rendered / "manifest.json").read_text())
    validate_manifest(current_manifest, "generated manifest")

    manifest_path = target / MANIFEST_NAME
    assert_safe_destination(manifest_path, target)
    manifest_exists = _has_entry(manifest_path)
    previous_manifest = (
        json.loads(manifest_path.read_text())
        if manifest_exists
        else {"format_version": 1, "roles": [], "profiles": []}
    )
    validate_manifest(previous_manifest, "installed manifest")

    roles = set(current_manifest["roles"]) | set(previous_manifest["roles"])
    paths = {
        target / MANIFEST_NAME,
        target / "CLAUDE.md",
    }
    paths.update(target / "agents" / f"{role}.md" for role in roles)
    paths.update(
        target / "workflows" / f"{workflow}.md"
        for workflow in current_manifest.get("workflows", [])
    )
    paths.update(
        target / "workflows" / f"{workflow}.md"
        for workflow in previous_manifest.get("workflows", [])
    )
    paths.add(target / CONTROL_PLANE_NOTE)
    for path in paths:
        assert_safe_destination(path, target)

    if not manifest_exists and not adopt:
        collisions = unmanaged_collisions(current_manifest, target)
        if collisions:
            details = "\n".join(f"  - {path}" for path in collisions)
            raise SystemExit(
                "Claude Code adoption required: existing unmanaged managed names found:\n"
                f"{details}\nRun again with --adopt to take ownership."
            )
    return current_manifest, previous_manifest


def desired_state(
    rendered: Path, target: Path, adopt: bool = False
) -> tuple[dict[Path, str], set[Path]]:
    files: dict[Path, str] = {}
    deletions: set[Path] = set()

    current_manifest, previous_manifest = load_and_preflight_manifests(rendered, target, adopt)
    manifest_path = target / MANIFEST_NAME
    current_roles = set(current_manifest["roles"])
    previous_roles = set(previous_manifest.get("roles", []))
    current_workflows = set(current_manifest.get("workflows", []))
    previous_workflows = set(previous_manifest.get("workflows", []))
    stale_roles = previous_roles - current_roles
    stale_workflows = previous_workflows - current_workflows

    claude_md_path = target / "CLAUDE.md"

    for role in current_roles:
        source = rendered / "agents" / f"{role}.md"
        files[target / "agents" / source.name] = source.read_text()
    for role in stale_roles:
        deletions.add(target / "agents" / f"{role}.md")

    for workflow in current_workflows:
        source = rendered / "workflows" / f"{workflow}.md"
        files[target / "workflows" / source.name] = source.read_text()
    for workflow in stale_workflows:
        deletions.add(target / "workflows" / f"{workflow}.md")

    section = (rendered / "_shared" / "orchestration-core.md").read_text()
    existing_claude_md = claude_md_path.read_text() if claude_md_path.exists() else ""
    files[claude_md_path] = merge_claude_md(existing_claude_md, section)
    control_note_source = rendered / CONTROL_PLANE_NOTE
    files[target / CONTROL_PLANE_NOTE] = control_note_source.read_text()

    files[manifest_path] = json.dumps(current_manifest, indent=2) + "\n"
    return files, deletions - set(files)


def install(target: Path, dry_run: bool, adopt: bool = False) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        rendered = Path(directory) / "claude-code"
        subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)
        files, deletions = desired_state(rendered, target, adopt)
        changed = {
            path: content
            for path, content in files.items()
            if not path.exists() or path.read_text() != content
        }
        deleted = {path for path in deletions if path.exists()}

        if not changed and not deleted:
            print("Claude Code configuration is already synchronized.")
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
        backup_base = Path.home() / ".local" / "state" / "agent-orchestration" / "backups"
        backup_base.mkdir(parents=True, exist_ok=True)
        backup_root = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=backup_base)) / "claude-code"
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
    parser.add_argument("--target", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="take ownership of existing managed names on first installation",
    )
    args = parser.parse_args()
    raise SystemExit(install(args.target, args.dry_run, args.adopt))
