#!/usr/bin/env python3
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


def control_plane_field_labels(config_path: Path) -> tuple[str, ...]:
    return (
        f"{config_path} (model)",
        f"{config_path} (variant)",
        f"{config_path} (small_model)",
        f"{config_path} (agent.build)",
        f"{config_path} (agent.plan)",
    )


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


def unmanaged_collisions(
    current_manifest: dict, target: Path, rendered: Path | None = None
) -> list[str]:
    """Find managed names already present before this adapter was adopted."""
    collisions: list[str] = []
    roles = set(current_manifest["roles"])
    profiles = set(current_manifest["profiles"])
    workflows = set(current_manifest.get("workflows", []))

    for workflow in sorted(workflows):
        path = target / "workflows" / f"{workflow}.md"
        if _has_entry(path):
            collisions.append(str(path))

    for role in sorted(roles):
        path = target / "agents" / f"{role}.md"
        if _has_entry(path):
            collisions.append(str(path))

    shared = target / "profiles" / "_shared" / "orchestration-core.md"
    if _has_entry(shared):
        collisions.append(str(shared))

    for name in sorted(profiles):
        profile = target / "profiles" / name
        addendum = profile / "orchestration.md"
        if _has_entry(addendum):
            collisions.append(str(addendum))

        config_path = profile / "opencode.json"
        if not _has_entry(config_path):
            continue
        config = json.loads(config_path.read_text())
        agents = config.get("agent", {})
        if isinstance(agents, dict):
            collisions.extend(
                f"{config_path} (agent.{role})"
                for role in sorted(roles)
                if role in agents
            )
            if rendered is not None and current_manifest.get("control_plane", False):
                labels = control_plane_field_labels(config_path)
                control = json.loads(
                    (rendered / "profiles" / name / "control-plane.json").read_text()
                )
                if any(key in config for key in ("model", "variant", "small_model")):
                    labels = control_plane_field_labels(config_path)
                    collisions.extend(
                        label
                        for label, key in zip(labels[:3], ("model", "variant", "small_model"))
                        if key in config
                    )
                collisions.extend(
                    label
                    for label, key in zip(
                        labels[3:], ("build", "plan")
                    )
                    if key in agents
                )

    return collisions


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
    profiles = set(current_manifest["profiles"]) | set(previous_manifest["profiles"])
    paths = {
        target / MANIFEST_NAME,
        target / "profiles" / "_shared" / "orchestration-core.md",
    }
    paths.update(target / "agents" / f"{role}.md" for role in roles)
    paths.update(target / "workflows" / f"{workflow}.md" for workflow in current_manifest.get("workflows", []))
    paths.update(target / "workflows" / f"{workflow}.md" for workflow in previous_manifest.get("workflows", []))
    for name in profiles:
        paths.add(target / "profiles" / name / "opencode.json")
        paths.add(target / "profiles" / name / "orchestration.md")
    for path in paths:
        assert_safe_destination(path, target)

    if not manifest_exists and not adopt:
        collisions = unmanaged_collisions(current_manifest, target, rendered)
        if collisions:
            details = "\n".join(f"  - {path}" for path in collisions)
            raise SystemExit(
                "OpenCode adoption required: existing unmanaged managed names found:\n"
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
    current_profiles = set(current_manifest["profiles"])
    previous_profiles = set(previous_manifest.get("profiles", []))
    current_workflows = set(current_manifest.get("workflows", []))
    previous_workflows = set(previous_manifest.get("workflows", []))
    stale_roles = previous_roles - current_roles
    stale_workflows = previous_workflows - current_workflows
    all_managed_instructions = managed_instruction_paths(target, current_profiles | previous_profiles)
    previous_control_plane = bool(previous_manifest.get("control_plane", False))

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

    core = rendered / "profiles" / "_shared" / "orchestration-core.md"
    files[target / "profiles" / "_shared" / core.name] = core.read_text()

    for name in sorted(current_profiles | previous_profiles):
        profile_dir = rendered / "profiles" / name
        config_path = target / "profiles" / name / "opencode.json"
        if name not in current_profiles:
            deletions.add(target / "profiles" / name / "orchestration.md")
        if not config_path.exists():
            if name in previous_profiles and name in current_profiles:
                raise SystemExit(f"Missing target profile config: {config_path}")
            continue

        config = json.loads(config_path.read_text())
        agents = config.setdefault("agent", {})
        if not isinstance(agents, dict):
            raise SystemExit(f"Invalid OpenCode agent configuration: {config_path}")
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
            control = json.loads((profile_dir / "control-plane.json").read_text())
            config["model"] = control["primary"]["model"]
            config["variant"] = control["primary"]["variant"]
            config["small_model"] = control["small_model"]
            agents.update(control["builtins"])
            addendum_target = target / "profiles" / name / "orchestration.md"
            files[addendum_target] = (profile_dir / "orchestration.md").read_text()
            config["instructions"] = [
                str(target / "profiles" / "_shared" / "orchestration-core.md"),
                str(addendum_target),
                *unrelated_instructions,
            ]
        else:
            config["instructions"] = unrelated_instructions
            if previous_control_plane:
                config.pop("model", None)
                config.pop("variant", None)
                config.pop("small_model", None)
                agents.pop("build", None)
                agents.pop("plan", None)

        files[config_path] = json.dumps(config, indent=2) + "\n"

    installed_manifest = dict(current_manifest)
    installed_manifest["profiles"] = sorted(
        name for name in current_profiles if (target / "profiles" / name / "opencode.json").exists()
    )
    files[manifest_path] = json.dumps(installed_manifest, indent=2) + "\n"
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


def install(target: Path, dry_run: bool, validate: bool, adopt: bool = False) -> int:
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked target root: {target}")
    target = target.resolve()
    with tempfile.TemporaryDirectory(prefix="agent-orchestration-") as directory:
        rendered = Path(directory) / "opencode"
        subprocess.run([sys.executable, str(RENDER), "--output", str(rendered)], check=True)
        files, deletions = desired_state(rendered, target, adopt)
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
        backup_base = Path.home() / ".local" / "state" / "agent-orchestration" / "backups"
        backup_base.mkdir(parents=True, exist_ok=True)
        backup_root = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=backup_base)) / "opencode"
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
                installed_manifest = json.loads(files[target / MANIFEST_NAME])
                for name in installed_manifest["profiles"]:
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
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="take ownership of existing managed names on first installation",
    )
    args = parser.parse_args()
    raise SystemExit(install(args.target, args.dry_run, not args.skip_validate, args.adopt))
