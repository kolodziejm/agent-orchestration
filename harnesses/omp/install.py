#!/usr/bin/env python3
"""Install one generated OMP bundle into its isolated profile agent root."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath

HARNESSES_DIR = Path(__file__).resolve().parents[1]
if str(HARNESSES_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESSES_DIR))

from common import upsert_managed_section

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "harnesses" / "omp" / "generate.py"
PROFILES = ("hybrid", "openai", "deepseek", "glm")
MANIFEST_NAME = ".agent-orchestration.omp-manifest.json"
# User-owned and shared: only its managed section is ever written, so it is never
# a manifest claim, a collision, or a removal.
INSTRUCTION_FILE = "AGENTS.md"
# Frozen cleanup set: an earlier adapter installed this file and the current
# one does not. The fixed target-relative path is always removed when present
# (see `install`), independent of any prior manifest, while an installed
# manifest may still claim it and a generated manifest may not claim it again.
LEGACY_MANAGED_FILES = frozenset({"APPEND_SYSTEM.md"})


def _entry(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _load_generator():
    spec = importlib.util.spec_from_file_location("omp_generate", GENERATOR)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load OMP generator: {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_path(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise SystemExit(f"Unsafe managed path: {relative!r}")
    if candidate.as_posix() != relative:
        raise SystemExit(f"Non-canonical managed path: {relative!r}")
    path = root.joinpath(*candidate.parts)
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise SystemExit(f"Refusing symlink in managed path: {current}")
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as error:
        raise SystemExit(f"Managed path escapes target: {relative}") from error
    return path


def _read_manifest(path: Path, profile: str) -> list[str] | None:
    if not _entry(path):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Malformed installed OMP manifest: {path}") from error
    if (not isinstance(data, dict) or data.get("format_version") != 1
            or data.get("profile") != profile or not isinstance(data.get("files"), list)):
        raise SystemExit("Invalid or mismatched installed OMP manifest/profile")
    files = data["files"]
    if (not files or not all(isinstance(item, str) for item in files)
            or len(files) != len(set(files))):
        raise SystemExit("Invalid installed OMP manifest file claims")
    required = {"config.yml"}
    valid = lambda item: item in required or item in LEGACY_MANAGED_FILES or (
        item.startswith("agents/") and item.endswith(".md") and item.count("/") == 1
    )
    if not required.issubset(files) or not all(valid(item) for item in files):
        raise SystemExit("Unsafe installed OMP manifest file claims")
    for item in files:
        _safe_path(path.parent, item)
    return files


def _bundle(generated: Path, profile: str) -> dict[Path, bytes]:
    manifest_path = generated / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Malformed generated OMP manifest: {manifest_path}") from error
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("format_version") != 1
            or manifest.get("profile") != profile or not isinstance(files, list)
            or not files or not all(isinstance(item, str) for item in files)
            or len(files) != len(set(files))):
        raise SystemExit("Generated OMP manifest is invalid or does not match selected profile")
    required = {"config.yml"}
    valid = lambda item: item in required or (
        item.startswith("agents/") and item.endswith(".md") and item.count("/") == 1
    )
    if not required.issubset(files) or not all(valid(item) for item in files):
        raise SystemExit("Generated OMP manifest contains unsafe or incomplete file claims")
    result = {}
    for relative in files:
        source = _safe_path(generated, relative)
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"Missing or linked generated OMP file: {relative}")
        result[relative] = source.read_bytes()
    if not any(name.startswith("agents/") for name in result):
        raise SystemExit("Generated OMP bundle contains no agent definitions")
    return result


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def install(profile: str, target: Path, dry_run: bool = False, generated: Path | None = None) -> int:
    if profile not in PROFILES:
        raise SystemExit(f"Unsupported OMP profile: {profile!r}")
    target = target.expanduser()
    if target.is_symlink():
        raise SystemExit(f"Refusing symlinked OMP target: {target}")
    target = target.resolve(strict=False)
    temporary = None
    try:
        if generated is None:
            temporary = tempfile.TemporaryDirectory(prefix="omp-install-")
            generated = Path(temporary.name) / profile
            _load_generator().generate(generated, profile)
        desired = _bundle(generated, profile)
        manifest_path = _safe_path(target, MANIFEST_NAME)
        prior = _read_manifest(manifest_path, profile)
        prior = prior or []
        # The retired global instruction file is managed unconditionally: its fixed
        # relative path is always treated as owned so a missing or non-claiming prior
        # manifest cannot leave an earlier copy behind.
        legacy = set(LEGACY_MANAGED_FILES)
        destinations = {
            name: _safe_path(target, name) for name in set(prior) | set(desired) | legacy
        }
        if not prior:
            collisions = [name for name in desired if _entry(destinations[name])]
            if collisions:
                raise SystemExit("Unmanaged OMP file collision(s); no files changed:\n" + "\n".join(f"  - {name}" for name in sorted(collisions)))
        else:
            # A manifest grants ownership only of its own claims. Newly introduced names
            # remain operator-owned unless absent at preflight.
            collisions = [name for name in desired.keys() - set(prior) if _entry(destinations[name])]
            if collisions:
                raise SystemExit("Unmanaged OMP file collision(s); no files changed:\n" + "\n".join(f"  - {name}" for name in sorted(collisions)))
        stale = (set(prior) - set(desired)) | legacy
        for name in stale:
            path = destinations[name]
            if _entry(path) and not path.is_file():
                raise SystemExit(f"Refusing to remove non-file managed path: {name}")
        next_manifest = {"format_version": 1, "profile": profile, "files": sorted(desired)}
        desired[MANIFEST_NAME] = (json.dumps(next_manifest, indent=2, sort_keys=True) + "\n").encode()
        destinations[MANIFEST_NAME] = manifest_path
        # Merged after the collision checks and the manifest claims on purpose: a
        # pre-existing instruction file is expected and stays operator-owned.
        instruction_path = _safe_path(target, INSTRUCTION_FILE)
        desired[INSTRUCTION_FILE] = upsert_managed_section(
            instruction_path.read_bytes().decode("utf-8") if _entry(instruction_path) else None,
            _safe_path(generated, INSTRUCTION_FILE).read_text(encoding="utf-8"),
            str(instruction_path),
        ).encode("utf-8")
        destinations[INSTRUCTION_FILE] = instruction_path
        writes = {name: content for name, content in desired.items()
                  if not _entry(destinations[name]) or destinations[name].read_bytes() != content}
        removals = {name for name in stale if _entry(destinations[name])}
        print(f"OMP {profile}: {len(writes)} write(s), {len(removals)} removal(s)")
        if dry_run:
            for name in sorted(writes):
                print(f"  write {name}")
            for name in sorted(removals):
                print(f"  remove {name}")
            return 0
        originals = {name: (destinations[name].read_bytes(), stat.S_IMODE(destinations[name].stat().st_mode))
                     if _entry(destinations[name]) else None for name in set(writes) | removals}
        try:
            for name in sorted(writes):
                old = originals[name]
                _atomic_write(destinations[name], desired[name], old[1] if old else 0o644)
            for name in sorted(removals):
                destinations[name].unlink()
        except BaseException:
            for name, original in originals.items():
                path = destinations[name]
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write(path, original[0], original[1])
            raise
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="hybrid")
    parser.add_argument("--target", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target = args.target or Path.home() / ".omp" / "profiles" / args.profile / "agent"
    return install(args.profile, target, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
