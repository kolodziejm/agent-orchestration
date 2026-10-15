"""Shared safety, capability, instruction-section, and skill helpers for harness integrations."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path


ORCHESTRATION_POLICY = Path(__file__).resolve().parents[1] / "policy" / "orchestration.md"
INSTRUCTION_MARKER_START = "<!-- agent-orchestration:start -->"
INSTRUCTION_MARKER_END = "<!-- agent-orchestration:end -->"

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"
SKILLS_DIR = "skills"
SKILL_FILE = "SKILL.md"
# The Agent Skills name rule: lowercase letters, digits, and single hyphens, at most
# 64 characters. Every installer's own manifest name check accepts this subset.
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX_LENGTH = 64
# One component of a path below a skill directory, and of every manifest claim on
# one: no hidden names, no `.`/`..`, nothing a shell or installer would reinterpret.
SKILL_PATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Generated caches that may appear in a skill directory but are never distributed.
SKILL_IGNORED_NAMES = frozenset({"__pycache__"})
# Bundle manifest key listing each supporting file a skill carries besides SKILL.md.
SKILL_FILES_KEY = "skill_files"

SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "max", "xhigh"})
HARNESS_SUPPORTED_EFFORTS = {
    "opencode": SUPPORTED_EFFORTS,
    "codex": frozenset({"low", "medium", "high", "max", "xhigh"}),
    "claude-code": frozenset({"low", "medium", "high", "max", "xhigh"}),
    "pi": SUPPORTED_EFFORTS,
    # The DeepSeek Harness DeepSeek route accepts off/low/high/max on every
    # pass-through model and the dsh adapter installs a role's effort on its
    # subagent lane; only the control-plane efforts stay recorded intent.
    "dsh": frozenset({"off", "low", "high", "max"}),
}


def managed_instruction_section() -> str:
    """Return the instruction artifact a bundle carries: the policy inside the markers."""
    policy = ORCHESTRATION_POLICY.read_text(encoding="utf-8")
    return f"{INSTRUCTION_MARKER_START}\n{policy}{INSTRUCTION_MARKER_END}\n"


def upsert_managed_section(existing: str | None, section: str, label: str) -> str:
    """Return a global instruction file's content with ``section`` as its managed section.

    The instruction file is user-owned, so only the bytes from the start marker
    through the end marker are ever replaced. A missing or empty file becomes the
    section alone, and a file without markers gets the section appended after one
    blank line. Anything other than zero markers or one start-before-end pair is
    refused: the installer cannot tell which of those bytes it owns.
    """
    if not existing:
        return section
    starts = existing.count(INSTRUCTION_MARKER_START)
    ends = existing.count(INSTRUCTION_MARKER_END)
    if starts == 0 and ends == 0:
        separator = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
        return existing + separator + section
    start = existing.find(INSTRUCTION_MARKER_START)
    end = existing.find(INSTRUCTION_MARKER_END)
    if starts != 1 or ends != 1 or start > end:
        raise SystemExit(
            f"{label} contains malformed agent-orchestration markers "
            f"({INSTRUCTION_MARKER_START!r}: {starts}, {INSTRUCTION_MARKER_END!r}: {ends}); "
            "expected none or exactly one start-before-end pair. Repair the file manually "
            "before installing; no files were changed."
        )
    return (
        existing[:start]
        + section.removesuffix("\n")
        + existing[end + len(INSTRUCTION_MARKER_END) :]
    )


def read_text_exact(path: Path) -> str:
    """Read text without newline translation, so bytes the caller leaves alone round-trip."""
    with path.open(newline="") as handle:
        return handle.read()


def _skill_package(name: str, directory: Path) -> dict[str, bytes]:
    """Return one skill directory as ``{path relative to it: bytes}``, ``SKILL.md`` first.

    Every regular file below the directory is part of the package. Hidden entries
    (``.DS_Store``) and Python bytecode caches are ignored because they are never
    authored; anything a bundle could not carry exactly is refused instead.
    """
    source = directory / SKILL_FILE
    if source.is_symlink() or not source.is_file():
        raise SystemExit(f"Skill {name!r} has no plain {SKILL_FILE}: {source}")
    files: dict[str, bytes] = {}
    pending = [directory]
    while pending:
        current = pending.pop()
        for entry in current.iterdir():
            if entry.name.startswith(".") or entry.name in SKILL_IGNORED_NAMES:
                continue
            relative = entry.relative_to(directory).as_posix()
            if entry.is_symlink():
                raise SystemExit(f"Skill {name!r} carries a symlink: {relative}")
            if not SKILL_PATH_PART.fullmatch(entry.name):
                raise SystemExit(f"Skill {name!r} carries an unsafe file name: {relative!r}")
            if entry.is_dir():
                pending.append(entry)
                continue
            if not entry.is_file():
                raise SystemExit(f"Skill {name!r} carries a non-regular file: {relative}")
            if not is_skill_claim(f"{name}/{relative}"):
                raise SystemExit(
                    f"Skill {name!r} carries a nested {SKILL_FILE}: {relative}; "
                    "a harness could discover it as a second skill"
                )
            content = entry.read_bytes()
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise SystemExit(f"Skill {name!r} file {relative} is not valid UTF-8: {error}") from error
            files[relative] = content
    return {SKILL_FILE: files.pop(SKILL_FILE), **dict(sorted(files.items()))}


def skill_sources() -> dict[str, dict[str, bytes]]:
    """Return every repository skill as ``{name: {relative path: bytes}}``, ordered by name.

    A skill is its ``skills/<name>/`` directory: ``SKILL.md`` plus any supporting
    files (scripts, references, assets) at any depth below it. Anything a bundle
    cannot carry whole is refused instead of being silently left out: a linked or
    misnamed entry, a directory without ``SKILL.md``, a non-UTF-8 file, or a nested
    ``SKILL.md``. Hidden entries such as ``.DS_Store`` and ``__pycache__`` are
    ignored, and a repository without a ``skills/`` directory has no skills.
    """
    if SKILLS_ROOT.is_symlink():
        raise SystemExit(f"Refusing symlinked skills directory: {SKILLS_ROOT}")
    if not SKILLS_ROOT.is_dir():
        return {}
    skills: dict[str, dict[str, bytes]] = {}
    for directory in sorted(SKILLS_ROOT.iterdir(), key=lambda path: path.name):
        name = directory.name
        if name.startswith("."):
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise SystemExit(f"Skill source is not a plain directory: {directory}")
        if not SKILL_NAME.fullmatch(name) or len(name) > SKILL_NAME_MAX_LENGTH:
            raise SystemExit(f"Unsafe skill directory name: {name!r}")
        skills[name] = _skill_package(name, directory)
    return skills


def is_skill_claim(relative: str) -> bool:
    """Whether a path relative to ``skills/`` is a file a skill may own.

    That is ``<name>/SKILL.md`` or a supporting file at any depth below
    ``<name>/``, every component a plain name. A ``SKILL.md`` anywhere else is not
    a claim: a harness that searches recursively would load it as another skill.
    """
    parts = relative.split("/")
    if len(parts) < 2 or not all(SKILL_PATH_PART.fullmatch(part) for part in parts):
        return False
    return parts[1:] == [SKILL_FILE] or SKILL_FILE not in parts[1:]


def skill_path(root: Path, name: str) -> Path:
    """Return the ``SKILL.md`` of a skill below a bundle or an installation target."""
    return root / SKILLS_DIR / name / SKILL_FILE


def skill_file_path(root: Path, relative: str) -> Path:
    """Return one skill file, given relative to ``skills/``, below a bundle or a target."""
    return root.joinpath(SKILLS_DIR, *relative.split("/"))


def write_skills(output: Path) -> tuple[list[str], list[str]]:
    """Copy every repository skill byte-for-byte into ``output``.

    Returns the skill names and, separately, every supporting file as a path
    relative to ``skills/`` (``<name>/scripts/run.py``); each skill's ``SKILL.md``
    is implied by its name. The ``skills/`` subtree of a bundle is wholly
    generated, so one left behind by an earlier in-place generation is replaced
    rather than merged; a skill or file dropped from the repository then never
    lingers in a bundle. No directory is created when the repository has no skills.
    """
    skills = skill_sources()
    destination = output / SKILLS_DIR
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise SystemExit(f"Refusing skills output that is not a plain directory: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    supporting: list[str] = []
    for name, files in skills.items():
        for relative, content in files.items():
            path = skill_file_path(output, f"{name}/{relative}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            if relative != SKILL_FILE:
                supporting.append(f"{name}/{relative}")
    return list(skills), supporting


def validate_skill_files(manifest: dict, label: str) -> None:
    """Refuse a manifest ``skill_files`` list that is not supporting files of its skills.

    The key is optional: a manifest written before skills carried supporting files
    claims only each skill's ``SKILL.md``.
    """
    values = manifest.get(SKILL_FILES_KEY, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise SystemExit(f"Invalid {label} {SKILL_FILES_KEY}")
    if len(values) != len(set(values)):
        raise SystemExit(f"Duplicate paths in {label} {SKILL_FILES_KEY}")
    skills = set(manifest.get("skills", []))
    for value in values:
        name, _, rest = value.partition("/")
        if name not in skills or rest == SKILL_FILE or not is_skill_claim(value):
            raise SystemExit(f"Unsafe path in {label} {SKILL_FILES_KEY}: {value!r}")


def claimed_skill_files(manifest: dict) -> list[str]:
    """Return every path relative to ``skills/`` that a manifest claims.

    Each listed skill owns its ``SKILL.md`` and the supporting files under
    ``skill_files``; nothing else below ``skills/`` is ever claimed.
    """
    return [
        *(f"{name}/{SKILL_FILE}" for name in manifest.get("skills", [])),
        *manifest.get(SKILL_FILES_KEY, []),
    ]


def read_bundle_skill_file(generated: Path, relative: str) -> bytes:
    """Return the exact bytes of a skill file a bundle manifest claims."""
    source = skill_file_path(generated, relative)
    current = source
    while current != generated and current != current.parent:
        if current.is_symlink():
            raise SystemExit(f"Missing or linked generated skill file: {source}")
        current = current.parent
    if not source.is_file():
        raise SystemExit(f"Missing or linked generated skill file: {source}")
    return source.read_bytes()


def read_bundle_skill(generated: Path, name: str) -> bytes:
    """Return the exact bytes of the ``SKILL.md`` of a skill a bundle manifest claims."""
    return read_bundle_skill_file(generated, f"{name}/{SKILL_FILE}")


def remove_empty_skill_directories(removed: Iterable[Path], target: Path) -> None:
    """Remove the directories a deleted skill file leaves empty, up to ``skills/<name>/``.

    For each removed path below ``skills/<name>/``, its directory and then each
    parent up to and including ``skills/<name>/`` is removed with ``rmdir`` until one
    is not empty. A directory that still holds operator files, every other skill,
    and ``skills/`` itself are left alone.
    """
    skills_root = target / SKILLS_DIR
    for path in removed:
        try:
            relative = path.relative_to(skills_root)
        except ValueError:
            continue
        if len(relative.parts) < 2:
            continue
        directory = path.parent
        while directory != skills_root:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent


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
    """Validate a generator output and return its resolved destination.

    The repository's exact build destination and descendants of the process
    temporary root are allowed. Existing symlink components below
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
    """Reject capability values a generator cannot preserve semantically."""
    edit = config.get("edit")
    bash = config.get("bash")
    if edit not in {"allow", "ask", "deny"}:
        raise SystemExit(f"Invalid edit capability for {role}: {edit!r}")
    if bash not in {"allow", "ask", "deny"}:
        raise SystemExit(f"Invalid bash capability for {role}: {bash!r}")

    if harness in {"codex", "claude-code"} and bash == "deny":
        # These roles are structurally read-only. Codex projects them to its
        # read-only sandbox and Claude Code omits Bash/Edit/Write. Keep the
        # exception narrow so an unsupported shell denial on another role is
        # still rejected rather than silently widened.
        if role not in {"planner", "design-partner", "ux-critic"}:
            raise SystemExit(
                f"{harness} cannot enforce bash = deny for role {role}; refusing to generate"
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
    if harness == "dsh" and primary_installable:
        # A dsh agent preset cannot select the session's own model route: the
        # host composition owns it and the user's model settings decide it.
        # Delegated children do get a per-role model through the delegation
        # tool rows, which is why the profile still routes every role.
        raise SystemExit(
            "DeepSeek Harness cannot install the primary control plane from a preset; "
            f"set primary_installable = false in {path}"
        )
