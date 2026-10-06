#!/usr/bin/env python3
"""Install generated DeepSeek Harness agent definitions with diff, backup, and rollback.

Managed artifacts under the DeepSeek Harness home (``--target``, default
``$DSH_HOME`` or ``~/.dsh``):

- ``cordis.patch.yml`` — the DeepSeek Harness *home* patch layer, which
  declares the agent preset holding one subagent lane per canonical role. dsh
  applies it after every bundle layer and after the profile's own patch, so the
  adapter can declare its preset without editing a bundled preset or the
  configuration the in-app editor owns. The managed block is delimited by
  ``# agent-orchestration:start`` / ``# agent-orchestration:end``.
- ``.agent-orchestration/control-plane.md`` — the recorded model/effort intent.

A previously installed ``AGENTS.md`` managed section is stripped, and artifacts
an earlier adapter claimed (``.agent-orchestration/adapter.md``, role contracts,
workflow copies) are deleted; user content outside the managed markers is never
rewritten.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATE = ROOT / "harnesses" / "dsh" / "generate.py"
MANIFEST_NAME = ".agent-orchestration.manifest.json"
MANAGED_DIR = ".agent-orchestration"
PATCH_FILE = "cordis.patch.yml"
PRESET_ID = "agent-orchestration"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHELLS = ("bash", "pwsh")

AGENTS_MARKER_START = "<!-- agent-orchestration:start -->"
AGENTS_MARKER_END = "<!-- agent-orchestration:end -->"
AGENTS_MARKER_PATTERN = re.compile(
    re.escape(AGENTS_MARKER_START) + r".*?" + re.escape(AGENTS_MARKER_END), re.DOTALL
)
PATCH_MARKER_START = "# agent-orchestration:start"
PATCH_MARKER_END = "# agent-orchestration:end"
PATCH_MARKER_PATTERN = re.compile(
    re.escape(PATCH_MARKER_START) + r".*?" + re.escape(PATCH_MARKER_END), re.DOTALL
)


def text_diff(current: Path, desired: str, label: str) -> str:
    before = current.read_text().splitlines(keepends=True) if current.exists() else []
    after = desired.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=str(current), tofile=label))


def validate_manifest(manifest: dict, label: str) -> None:
    if manifest.get("format_version") != 1:
        raise SystemExit(f"Unsupported {label} format_version")
    for key in ("roles", "profiles", "presets"):
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


def _has_entry(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def assert_safe_destination(path: Path, target: Path) -> None:
    resolved_target = target.resolve()
    try:
        path.resolve(strict=False).relative_to(resolved_target)
    except ValueError as error:
        raise SystemExit(f"Refusing path outside target: {path}") from error
    if path.is_symlink():
        raise SystemExit(f"Refusing to replace symlink: {path}")
    current = path.parent
    while current != target and current != current.parent:
        if current.is_symlink():
            raise SystemExit(f"Refusing path below symlinked directory: {current}")
        current = current.parent


def managed_relatives(manifest: dict) -> list[str]:
    return [
        PATCH_FILE,
        MANIFEST_NAME,
        f"{MANAGED_DIR}/control-plane.md",
    ]


def unmanaged_collisions(manifest: dict, target: Path) -> list[str]:
    return [
        str(target / relative)
        for relative in managed_relatives(manifest)
        if _has_entry(target / relative)
    ]


def merge_patch_block(existing: str, block: str) -> str:
    """Replace the managed patch block, or append it, preserving the rest."""
    start = PATCH_MARKER_START
    end = PATCH_MARKER_END
    start_count = existing.count(start)
    end_count = existing.count(end)
    if start_count == 0 and end_count == 0:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing:
            existing += "\n"
        return existing + block
    if start_count == 1 and end_count == 1 and existing.index(start) < existing.index(end):
        return PATCH_MARKER_PATTERN.sub(lambda _match: block.strip("\n"), existing)
    raise SystemExit(
        f"{PATCH_FILE} contains malformed agent-orchestration markers "
        f"({start!r}: {start_count}, {end!r}: {end_count}); expected zero of both or "
        f"exactly one well-formed start-before-end pair. Repair {PATCH_FILE} manually "
        "before installing."
    )


def strip_agents_md(existing: str) -> str:
    """Remove the marker-delimited managed section, preserving every other byte.

    The adapter no longer installs instruction content into AGENTS.md, so an
    existing managed section is stripped instead of rewritten. Files without a
    marker pair, and files with dangling or duplicated markers, are returned
    unchanged: the installer never rewrites bytes it does not own.
    """
    start_count = existing.count(AGENTS_MARKER_START)
    end_count = existing.count(AGENTS_MARKER_END)
    if start_count != 1 or end_count != 1:
        return existing
    match = AGENTS_MARKER_PATTERN.search(existing)
    if match is None or existing.index(AGENTS_MARKER_START) > existing.index(AGENTS_MARKER_END):
        return existing
    before = existing[: match.start()]
    after = existing[match.end() :]
    if before.endswith("\n\n") and after.startswith("\n"):
        before = before[:-1]
        after = after[1:]
    elif after.startswith("\n"):
        after = after[1:]
    return before + after


def validate_patch_block(block: str, roles: list[str]) -> None:
    """Structural checks on the managed home-patch block.

    The home layer is loaded on every boot, so a malformed patch breaks the
    harness. These checks are deliberately textual: the block must be one
    top-level ``- insert:`` entry that declares every canonical role lane.
    """
    if "\t" in block:
        raise SystemExit("Refusing to install a patch block that contains tab characters")
    if not block.startswith(PATCH_MARKER_START + "\n"):
        raise SystemExit(f"Generated patch block must start with {PATCH_MARKER_START!r}")
    if not block.rstrip("\n").endswith(PATCH_MARKER_END):
        raise SystemExit(f"Generated patch block must end with {PATCH_MARKER_END!r}")
    top_level = [
        line for line in block.split("\n") if line.startswith("- ")
    ]
    if top_level != ["- insert:"]:
        raise SystemExit(
            f"Generated patch block must contain exactly one top-level '- insert:': {top_level!r}"
        )
    lanes = [line for line in block.split("\n") if line.startswith(f"{' ' * 12}- id: lane-")]
    if len(lanes) != len(roles):
        raise SystemExit(
            f"Generated patch block declares {len(lanes)} role lanes, expected {len(roles)}"
        )
    for role in roles:
        if f"- id: lane-{role}\n" not in block:
            raise SystemExit(f"Generated patch block is missing the {role!r} lane")


def verify_patch_yaml(text: str) -> str:
    """Validate the merged home patch as YAML when PyYAML is importable.

    ``!!js`` is the Cordis loader's expression tag, not standard YAML, so the
    check registers a constructor for it. The check is skipped when PyYAML is
    unavailable; it never rewrites the file.
    """
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return "skipped"

    class _LoaderExpression(str):
        pass

    yaml.SafeLoader.add_constructor(
        "tag:yaml.org,2002:js", lambda loader, node: _LoaderExpression(loader.construct_scalar(node))
    )
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SystemExit(
            f"Refusing to install: the merged {PATCH_FILE} is not a valid patch list: {error}"
        ) from error
    if not isinstance(document, list) or not all(isinstance(row, dict) for row in document):
        raise SystemExit(
            f"Refusing to install: the merged {PATCH_FILE} must be a YAML list of patch entries"
        )
    if not any(PATCH_MARKER_START in line for line in text.split("\n")):
        raise SystemExit(f"Refusing to install: the merged {PATCH_FILE} lost its managed block")
    return "validated"


def load_and_preflight_manifests(
    generated: Path, target: Path, adopt: bool = False
) -> tuple[dict, dict]:
    current_manifest = json.loads((generated / "manifest.json").read_text())
    validate_manifest(current_manifest, "generated manifest")
    if current_manifest["presets"] != [PRESET_ID]:
        raise SystemExit(
            f"Generated manifest must manage exactly [{PRESET_ID!r}]: "
            f"{current_manifest['presets']!r}"
        )

    manifest_path = target / MANIFEST_NAME
    assert_safe_destination(manifest_path, target)
    manifest_exists = _has_entry(manifest_path)
    previous_manifest = (
        json.loads(manifest_path.read_text())
        if manifest_exists
        else {"format_version": 1, "roles": [], "profiles": [], "workflows": [], "presets": []}
    )
    validate_manifest(previous_manifest, "installed manifest")

    for relative in managed_relatives(current_manifest) + managed_relatives(previous_manifest):
        assert_safe_destination(target / relative, target)

    if not manifest_exists and not adopt:
        collisions = unmanaged_collisions(current_manifest, target)
        if collisions:
            details = "\n".join(f"  - {path}" for path in collisions)
            raise SystemExit(
                "DeepSeek Harness adoption required: existing unmanaged managed names found:\n"
                f"{details}\nRun again with --adopt to take ownership."
            )
    return current_manifest, previous_manifest


def desired_state(
    generated: Path, target: Path, adopt: bool = False
) -> tuple[dict[Path, str], set[Path]]:
    files: dict[Path, str] = {}
    deletions: set[Path] = set()

    current_manifest, previous_manifest = load_and_preflight_manifests(
        generated, target, adopt
    )
    manifest_path = target / MANIFEST_NAME
    agents_path = target / "AGENTS.md"
    existing_agents = agents_path.read_text() if agents_path.exists() else ""
    if existing_agents:
        stripped = strip_agents_md(existing_agents)
        if stripped != existing_agents:
            files[agents_path] = stripped

    # Artifacts an earlier adapter claimed and now no longer installs.
    deletions.add(target / MANAGED_DIR / "adapter.md")
    for role in previous_manifest.get("roles", []):
        deletions.add(target / MANAGED_DIR / "agents" / f"{role}.md")
    for workflow in previous_manifest.get("workflows", []):
        deletions.add(target / MANAGED_DIR / "workflows" / f"{workflow}.md")

    patch_path = target / PATCH_FILE
    block = (generated / "patch" / PATCH_FILE).read_text()
    validate_patch_block(block, current_manifest["roles"])
    existing_patch = patch_path.read_text() if patch_path.exists() else ""
    files[patch_path] = merge_patch_block(existing_patch, block)

    files[target / MANAGED_DIR / "control-plane.md"] = (
        generated / "_shared" / "control-plane.md"
    ).read_text()

    files[manifest_path] = json.dumps(current_manifest, indent=2) + "\n"
    return files, deletions - set(files)


def write_text(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode is not None:
        os.chmod(path, mode)


def install(
    target: Path,
    dry_run: bool,
    adopt: bool = False,
    shell: str = "bash",
    skip_validate: bool = False,
) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        generated = Path(directory) / "dsh"
        subprocess.run(
            [sys.executable, str(GENERATE), "--output", str(generated), "--shell", shell],
            check=True,
        )
        files, deletions = desired_state(generated, target, adopt)
        if not skip_validate:
            outcome = verify_patch_yaml(files[target / PATCH_FILE])
            if outcome == "skipped":
                print(
                    "PyYAML is unavailable; the home patch passed structural checks only."
                )
        changed = {
            path: content
            for path, content in files.items()
            if not path.exists() or path.read_text() != content
        }
        deleted = {path for path in deletions if path.exists()}

        if not changed and not deleted:
            print("DeepSeek Harness configuration is already synchronized.")
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
        backup_root = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=backup_base)) / "dsh"
        originals: dict[Path, tuple[bytes, int] | None] = {
            path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            if path.exists()
            else None
            for path in affected
        }

        # Complete every backup before the first mutation.
        for path, original in originals.items():
            if original is None:
                continue
            backup = backup_root / path.relative_to(target)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original[0])

        try:
            for path, content in changed.items():
                mode = originals[path][1] if originals.get(path) else None
                write_text(path, content, mode)
            for path in deleted:
                path.unlink()
            for stale in (path.parent for path in deleted):
                try:
                    stale.rmdir()
                except OSError:
                    pass
        except BaseException:
            for path, original in originals.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_text(path, original[0].decode(), original[1])
            print("Installation failed; all changed files were rolled back.", file=sys.stderr)
            raise

        print(
            f"Installed {len(changed)} write(s), {len(deleted)} deletion(s). "
            f"Backup: {backup_root}"
        )
        print(
            f"Start a new DeepSeek Harness session and select the '{PRESET_ID}' agent preset "
            "to use the canonical role subagent lanes; an existing session keeps the "
            "preset it started on."
        )
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        default=Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="take ownership of existing managed names on first installation",
    )
    parser.add_argument(
        "--shell",
        choices=list(SHELLS),
        default="pwsh" if sys.platform == "win32" else "bash",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="skip the YAML re-parse of the merged home patch",
    )
    args = parser.parse_args()
    raise SystemExit(
        install(args.target, args.dry_run, args.adopt, args.shell, args.skip_validate)
    )
