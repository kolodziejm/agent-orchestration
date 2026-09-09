"""Shared safety and capability checks used by harness adapters."""

from __future__ import annotations

import os
from pathlib import Path


def _absolute(path: Path) -> Path:
    """Return an absolute lexical path without following symlinks."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _anchor_for(path: Path, root: Path) -> Path | None:
    """Find the lexical component that resolves to the allowed root.

    The temporary directory may be addressed through a system alias such as
    ``/tmp``. That alias is safe to preserve, while symlinks below the root
    remain rejected by ``_assert_no_symlink_components``.
    """
    root = root.resolve()
    current = path
    while True:
        if current.resolve(strict=False) == root and current.name == root.name:
            return current
        if current == current.parent:
            return None
        current = current.parent


def _assert_no_symlink_components(path: Path, root: Path) -> None:
    lexical = _absolute(path)
    if lexical.is_symlink():
        raise SystemExit(f"Refusing symlinked output path: {path}")
    anchor = _anchor_for(lexical, root)
    if anchor is None:
        raise SystemExit(f"Refusing path outside allowed root: {path}")

    current = lexical
    while current != anchor:
        if current.is_symlink():
            raise SystemExit(f"Refusing symlinked path component: {current}")
        current = current.parent


def assert_safe_output(output: Path, default_output: Path, temp_root: Path) -> Path:
    """Validate a renderer output and return its resolved destination.

    The repository's exact generated destination and descendants of the
    process temporary root are allowed. Existing symlink components below
    either allowed root are rejected before any directory is created.
    """
    lexical = _absolute(output)
    default_lexical = _absolute(default_output)
    temp_root = temp_root.resolve()
    resolved = lexical.resolve(strict=False)

    if lexical == default_lexical:
        _assert_no_symlink_components(lexical, default_lexical.parent.parent)
        return resolved

    try:
        resolved.relative_to(temp_root)
    except ValueError as error:
        raise SystemExit(
            f"Refusing unsafe output path: {resolved}. "
            f"Use {default_output} or a directory below {temp_root}."
        ) from error

    if resolved == temp_root:
        raise SystemExit(f"Refusing to replace temporary root: {resolved}")

    _assert_no_symlink_components(lexical, temp_root)
    return resolved


def assert_safe_rename(path: Path, allowed_root: Path) -> None:
    """Re-check a rename participant immediately before an atomic rename."""
    resolved = _absolute(path).resolve(strict=False)
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as error:
        raise SystemExit(f"Refusing rename outside allowed root: {path}") from error
    _assert_no_symlink_components(path, allowed_root)


def validate_capabilities(role: str, config: dict, harness: str) -> None:
    """Reject capability values a renderer cannot preserve semantically."""
    edit = config.get("edit")
    bash = config.get("bash")
    if edit not in {"allow", "ask", "deny"}:
        raise SystemExit(f"Invalid edit capability for {role}: {edit!r}")
    if bash not in {"allow", "ask", "deny"}:
        raise SystemExit(f"Invalid bash capability for {role}: {bash!r}")

    if harness in {"codex", "claude-code"} and bash == "deny":
        raise SystemExit(
            f"{harness} cannot enforce bash = deny for role {role}; refusing to render"
        )
