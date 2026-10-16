"""The review-map manifest: `review-map.json` beside graphs.json.

build_graph.py, gen_diffs.py, and assemble.py each record the inputs of their last
run there under their own section, so refresh.py can rebuild the page from the
directory alone after a branch moves. A path inside that directory is stored
relative to it, any other path (a repository, a template elsewhere) absolutely.
The file is written with sorted keys, so the same inputs give the same bytes.

It also holds the checks every script applies to the PR keys, ranges, and
repositories it hands to git (check_pr), so a value from the command line or a
manifest can never become a git option, and the page history assemble.py and
refresh.py number builds by (history). Python 3 standard library only.
"""

from __future__ import annotations

import hashlib
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


DATA_BLOCK = re.compile(r'<script type="application/json" id="(review-config|graph-data|diff-data)">(.*?)</script>', re.DOTALL)


def digest(graph: dict, diffs: dict) -> str:
    """What a page shows, as one hash: every changed file's PR key, path, and fingerprint (its diff's hash without one)."""
    owner = {node["id"]: pr["key"] for pr in graph.get("prs", []) for node in pr.get("nodes", [])}
    items = sorted((owner.get(node_id, ""), entry.get("path", ""),
                    entry.get("fp") or "diff:" + hashlib.sha256(entry.get("diff", "").encode("utf-8")).hexdigest()[:12])
                   for node_id, entries in diffs.items() for entry in entries)
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def history(pages) -> tuple[int, str] | None:
    """(generation, digest) of the first of `pages` that is an assembled review map, else None.

    Each page carries its generation in its config (0 before generations existed) and its data, so the page a build
    replaces tells the build its number: the same digest keeps it, any other content counts one up. This works for
    every build path (refresh.py or the scripts by hand) and needs nothing besides the page itself.
    """
    for page in pages:
        if page is None or not Path(page).is_file():
            continue
        try:
            blocks = {m.group(1): json.loads(m.group(2)) for m in DATA_BLOCK.finditer(Path(page).read_text(encoding="utf-8"))}
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        config, graph, diffs = blocks.get("review-config"), blocks.get("graph-data"), blocks.get("diff-data")
        if isinstance(config, dict) and isinstance(graph, dict) and isinstance(diffs, dict):
            gen = config.get("generation", 0)
            return (gen if isinstance(gen, int) and not isinstance(gen, bool) and gen >= 0 else 0), digest(graph, diffs)
    return None
