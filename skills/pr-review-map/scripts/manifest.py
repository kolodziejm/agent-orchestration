"""The review-map manifest: `review-map.json` beside graphs.json.

build_graph.py, gen_diffs.py, and assemble.py each record the inputs of their last
run there under their own section, so refresh.py can rebuild the page from the
directory alone after a branch moves. A path inside that directory is stored
relative to it, any other path (a repository, a template elsewhere) absolutely.
The file is written with sorted keys, so the same inputs give the same bytes.
Python 3 standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

NAME = "review-map.json"
VERSION = 1


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
