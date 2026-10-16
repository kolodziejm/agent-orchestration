"""The review-map manifest: `review-map.json` beside graphs.json.

build_graph.py, gen_diffs.py, and assemble.py each record the inputs of their last
run there under their own section, so refresh.py can rebuild the page from the
directory alone after a branch moves. A path inside that directory is stored
relative to it, any other path (a repository, a template elsewhere) absolutely.
The file is written with sorted keys, so the same inputs give the same bytes.

It also holds the checks every script applies to the PR keys, ranges, and
repositories it hands to git (check_pr), so a value from the command line or a
manifest can never become a git option. Python 3 standard library only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NAME = "review-map.json"
VERSION = 1
KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")  # also a command-line value, so no leading "-"
# A revision as git takes it on the command line: no white space or control character anywhere, and no leading "-",
# which git would read as an option (`--output=<file>` writes a file).
REV = re.compile(r"[^\s\x00-\x1f\x7f-][^\s\x00-\x1f\x7f]*")


def check_pr(key: str, repo: str, rng: str) -> None:
    """Refuse a PR key, repository path, or range git could misread; SystemExit names the bad value.

    A range is `base...tip` or `base..tip`; each side, when given, must be a plain revision (REV). Scripts also put
    `--end-of-options` before every revision they pass to git, so this is a second line of defence and a clear error.
    """
    if not KEY.fullmatch(key):
        raise SystemExit(f"PR key {key!r} must be letters, digits, '_' or '-', not starting with '-'")
    if not repo or repo.startswith("-") or re.search(r"[\x00-\x1f\x7f]", repo):
        raise SystemExit(f"PR {key}: repository path {repo!r} must not start with '-' or contain control characters")
    sep = "..." if "..." in rng else ".." if ".." in rng else None
    sides = rng.split(sep, 1) if sep else []
    if not sep or not all(not side or REV.fullmatch(side) for side in sides) or not REV.fullmatch(rng):
        raise SystemExit(f"PR {key}: range {rng!r} must be base...tip or base..tip with plain revisions "
                         "(no leading '-', white space, or control characters)")


def inside(directory: Path, path: Path) -> bool:
    """Whether `path` resolves to `directory` or below it."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def stored(directory: Path, path: Path | str | None) -> str | None:
    """How the manifest in `directory` records `path`: relative inside it, absolute elsewhere."""
    if path is None:
        return None
    absolute = Path(path).resolve()
    try:
        return absolute.relative_to(directory.resolve()).as_posix()
    except ValueError:
        return str(absolute)


def resolve(directory: Path, value: str | None) -> Path | None:
    """The path a manifest entry stands for."""
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else directory / path


def read(directory: Path) -> dict:
    path = directory / NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"{path} is not valid JSON: {error}") from error
    return data if isinstance(data, dict) else {}


def record(directory: Path, section: str, value: dict) -> Path:
    """Replace one script's section of the manifest in `directory`, keeping the others."""
    data = read(directory)
    data["version"] = VERSION
    data[section] = value
    path = directory / NAME
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path
