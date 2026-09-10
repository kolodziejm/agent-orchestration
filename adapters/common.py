"""Shared safety and capability checks used by harness adapters."""

from __future__ import annotations

import os
from pathlib import Path


SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "max", "xhigh"})
HARNESS_SUPPORTED_EFFORTS = {
    "opencode": SUPPORTED_EFFORTS,
    "codex": frozenset({"low", "medium", "high", "max", "xhigh"}),
    "claude-code": frozenset({"low", "medium", "high", "max", "xhigh"}),
}


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


def _validate_model_config(
    label: str,
    config: object,
    harness: str,
    *,
    effort_key: str,
    require_effort: bool,
) -> None:
    if not isinstance(config, dict):
        raise SystemExit(f"Invalid profile {label}: expected a table")
    unknown = set(config) - {"model", effort_key}
    if unknown:
        raise SystemExit(f"Invalid profile fields for {label}: {sorted(unknown)}")

    model = config.get("model")
    if not isinstance(model, str) or not model:
        raise SystemExit(f"Invalid profile {label} model: {model!r}")

    effort = config.get(effort_key)
    if effort is None and not require_effort:
        return
    if not isinstance(effort, str) or not effort:
        raise SystemExit(f"Invalid profile {label} effort: {effort!r}")
    supported = HARNESS_SUPPORTED_EFFORTS.get(harness)
    if supported is None or effort not in supported:
        raise SystemExit(
            f"Unsupported {harness} effort for {label}: {effort!r}; "
            f"supported values are {sorted(supported or ())}"
        )


def validate_profile(
    profile: dict,
    path: Path,
    expected_roles: set[str],
    harness: str,
    *,
    require_role_variants: bool = False,
) -> None:
    """Validate the versioned profile contract before a harness writes output."""
    allowed_profile_keys = {
        "version",
        "name",
        "addendum",
        "harness",
        "capabilities",
        "models",
        "control_plane",
    }
    unknown_profile_keys = set(profile) - allowed_profile_keys
    if unknown_profile_keys:
        raise SystemExit(
            f"Invalid profile fields in {path}: {sorted(unknown_profile_keys)}"
        )
    if profile.get("version") != 1:
        raise SystemExit(f"Invalid profile version in {path}: {profile.get('version')!r}")
    if not isinstance(profile.get("name"), str) or not profile["name"]:
        raise SystemExit(f"Invalid profile name in {path}")
    if not isinstance(profile.get("addendum"), str) or not profile["addendum"]:
        raise SystemExit(f"Invalid profile addendum in {path}")

    models = profile.get("models")
    if not isinstance(models, dict) or set(models) != expected_roles:
        actual = set(models) if isinstance(models, dict) else set()
        missing = sorted(expected_roles - actual)
        extra = sorted(actual - expected_roles)
        raise SystemExit(
            f"Profile {profile.get('name', path.stem)} mismatch: "
            f"missing={missing}, extra={extra}"
        )
    for role, model_config in models.items():
        _validate_model_config(
            f"{profile['name']} role {role}",
            model_config,
            harness,
            effort_key="variant",
            require_effort=require_role_variants,
        )

    control_plane = profile.get("control_plane")
    if not isinstance(control_plane, dict):
        raise SystemExit(f"Invalid profile control_plane in {path}: expected a table")
    if set(control_plane) != {"primary", "small_model", "builtins"}:
        raise SystemExit(
            f"Invalid profile control_plane in {path}: expected primary, small_model, and builtins"
        )
    _validate_model_config(
        f"{profile['name']} control_plane.primary",
        control_plane["primary"],
        harness,
        effort_key="effort",
        require_effort=True,
    )
    small_model = control_plane["small_model"]
    if not isinstance(small_model, str) or not small_model:
        raise SystemExit(f"Invalid profile {profile['name']} control_plane.small_model")

    builtins = control_plane["builtins"]
    if not isinstance(builtins, dict) or set(builtins) != {"build", "plan"}:
        raise SystemExit(
            f"Invalid profile {profile['name']} control_plane.builtins: expected build and plan"
        )
    for builtin, model_config in builtins.items():
        _validate_model_config(
            f"{profile['name']} control_plane.builtins.{builtin}",
            model_config,
            harness,
            effort_key="effort",
            require_effort=True,
        )

    capabilities = profile.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise SystemExit(f"Invalid profile capabilities in {path}")
    unknown_capabilities = set(capabilities) - {
        "native_vision",
        "primary_installable",
        "supported_variants",
    }
    if unknown_capabilities:
        raise SystemExit(
            f"Invalid profile capability fields in {path}: {sorted(unknown_capabilities)}"
        )
    supported_variants = capabilities.get("supported_variants")
    if (
        not isinstance(supported_variants, list)
        or not supported_variants
        or not all(isinstance(value, str) and value for value in supported_variants)
        or len(supported_variants) != len(set(supported_variants))
    ):
        raise SystemExit(f"Invalid profile supported_variants in {path}")
    for label, config in [
        *[(f"{profile['name']} role {role}", value) for role, value in models.items()],
        (f"{profile['name']} control_plane.primary", control_plane["primary"]),
        *[
            (f"{profile['name']} control_plane.builtins.{name}", value)
            for name, value in builtins.items()
        ],
    ]:
        effort_key = "variant" if "role" in label else "effort"
        effort = config.get(effort_key)
        if effort is not None and effort not in supported_variants:
            raise SystemExit(
                f"Profile {profile['name']} {effort_key} {effort!r} for {label} "
                f"is not in supported_variants"
            )
    primary_installable = capabilities.get("primary_installable", True)
    if not isinstance(primary_installable, bool):
        raise SystemExit(f"Invalid profile primary_installable capability in {path}")
    if harness == "claude-code" and primary_installable:
        raise SystemExit(
            "Claude Code cannot install the primary control plane; "
            f"set primary_installable = false in {path}"
        )
