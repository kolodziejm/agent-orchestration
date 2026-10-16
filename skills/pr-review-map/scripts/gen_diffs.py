#!/usr/bin/env python3
"""Write diffs.json for a review map: the per-file diffs behind every graph node.

Usage:
  python3 gen_diffs.py --graph graphs.json --out diffs.json \\
      --pr S /path/to/repo main...feat/s \\
      --pr A /path/to/repo feat/s...feat/a [--context 4] [--max-lines 2000] [--strict]

Each --pr maps a PR key from graphs.json to a repository and a git range. Use
`base...tip` (three dots) for the diff GitHub shows. When the base branch moved
and the PR was never rebased onto it, pass `<merge-base>..tip` instead. The range
is read with `git diff`, so nothing is checked out.

A changed file is assigned to the node whose `path` equals it, whose `files` list
contains it, or whose `match` globs (or a glob-like `path`) match it. Output maps
node id -> [{"path", "diff", "truncated"?, "binary"?}] with git headers stripped;
`truncated` holds the full line count of a diff cut at --max-lines. For Vue, Svelte,
and Astro files git puts the last block tag before each hunk (`<script setup lang="ts">`,
`</script>`) on the hunk's @@ line, so the viewer highlights a hunk in the middle of a
block in that block's language.
Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HEADER_PREFIXES = (
    "diff --git ",
    "index ",
    "similarity index",
    "dissimilarity index",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "new file mode",
    "deleted file mode",
    "old mode",
    "new mode",
)
GLOB_CHARS = set("*?[")
# A diff driver for single-file components: the funcname on a hunk's @@ line is the last block tag at the start of a
# line before the hunk, whole with its lang attribute (git shows a pattern's first group, so the outer group holds the
# tag). An opening tag means the hunk starts in that block; a closing one, outside every block (Svelte's markup).
SFC_ATTRIBUTES = "".join(f"*.{ext} diff=review-map-sfc\n" for ext in ("vue", "svelte", "astro"))
SFC_FUNCNAME = r"^(</?(template|script|style|i18n|docs)([[:space:]][^>]*)?>)"


def git(repo: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo, "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
    return result.stdout


def sfc_options(repo: str, folder: str) -> list[str]:
    """`git -c` options that apply the SFC diff driver without touching the repository.

    The attributes go in a temporary core.attributesFile, followed by the user's own global
    attributes file so their diff drivers still win (and in-tree .gitattributes win over both).
    """
    configured = subprocess.run(["git", "-C", repo, "config", "--path", "--get", "core.attributesFile"],
                                capture_output=True, text=True).stdout.strip()
    home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    own = Path(configured or os.path.join(home, "git", "attributes"))
    text = SFC_ATTRIBUTES
    try:
        text += own.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pass
    path = Path(folder) / "attributes"
    path.write_text(text, encoding="utf-8")
    return ["-c", f"core.attributesFile={path}", "-c", f"diff.review-map-sfc.xfuncname={SFC_FUNCNAME}"]


def split_files(diff: str) -> list[tuple[str, str, bool]]:
    """Split one `git diff` into (path, body, binary) per file, headers removed."""
    chunks: list[list[str]] = []
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            chunks.append([line])
        elif chunks:
            chunks[-1].append(line)
    files = []
    for lines in chunks:
        path = None
        binary = False
        for line in lines:
            if line.startswith("@@"):
                break
            if line.startswith("rename to "):
                path = line[len("rename to "):]
            elif line.startswith("+++ ") and line[4:].rstrip("\t") != "/dev/null":
                path = line[4:].rstrip("\t").removeprefix("b/")
            elif line.startswith("--- ") and path is None and line[4:].rstrip("\t") != "/dev/null":
                path = line[4:].rstrip("\t").removeprefix("a/")
            elif line.startswith("Binary files "):
                binary = True
        if path is None:
            header = lines[0][len("diff --git "):]
            path = header.split(" b/", 1)[1] if " b/" in header else header
        body = "\n".join(
            line for line in lines if not line.startswith(HEADER_PREFIXES)
        ).rstrip("\n")
        files.append((path, body, binary))
    return files


def node_patterns(node: dict) -> list[str]:
    patterns = list(node.get("match", []))
    path = node.get("path", "")
    if any(char in path for char in GLOB_CHARS) or ", " in path:
        patterns.extend(part.strip() for part in path.split(",") if part.strip())
    return patterns


def assign(path: str, nodes: list[dict]) -> str | None:
    for node in nodes:
        if node.get("unchanged"):
            continue
        if node.get("path") == path or path in node.get("files", []):
            return node["id"]
    for node in nodes:
        if node.get("unchanged"):
            continue
        for pattern in node_patterns(node):
            if fnmatch.fnmatchcase(path, pattern):
                return node["id"]
            if not any(char in pattern for char in GLOB_CHARS) and path.endswith("/" + pattern):
                return node["id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pr", action="append", nargs=3, metavar=("KEY", "REPO", "RANGE"), required=True)
    parser.add_argument("--context", type=int, default=4, help="context lines per hunk (default 4)")
    parser.add_argument("--max-lines", type=int, default=2000, help="truncate a file's diff after this many lines (default 2000)")
    parser.add_argument("--strict", action="store_true", help="fail when a changed file maps to no node")
    args = parser.parse_args()

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    prs = {pr["key"]: pr for pr in graph["prs"]}
    ranges = {}
    for key, repo, rng in args.pr:
        if key not in prs:
            raise SystemExit(f"--pr {key}: no PR with that key in {args.graph}")
        if ".." not in rng:
            raise SystemExit(f"--pr {key}: range {rng!r} must be base...tip or base..tip")
        ranges[key] = (repo, rng)
    missing = [key for key in prs if key not in ranges]
    if missing:
        raise SystemExit(f"No --pr given for graph PR keys: {missing}")

    out: dict[str, list[dict]] = {}
    unassigned: list[str] = []
    folder = tempfile.TemporaryDirectory(prefix="review-map-")
    for key, pr in prs.items():
        repo, rng = ranges[key]
        diff = git(repo, *sfc_options(repo, folder.name), "diff", "--no-color", "--no-ext-diff", "-M", f"-U{args.context}", rng)
        for path, body, binary in split_files(diff):
            node_id = assign(path, pr["nodes"])
            if node_id is None:
                unassigned.append(f"{key}:{path}")
                continue
            entry: dict = {"path": path, "diff": body}
            lines = body.split("\n")
            if len(lines) > args.max_lines:
                entry["diff"] = "\n".join(lines[: args.max_lines])
                entry["truncated"] = len(lines)
            if binary:
                entry["binary"] = True
            out.setdefault(node_id, []).append(entry)

    folder.cleanup()
    ordered = {
        node["id"]: out[node["id"]]
        for pr in graph["prs"]
        for node in pr["nodes"]
        if node["id"] in out
    }
    args.out.write_text(json.dumps(ordered, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    without = [
        node["id"]
        for pr in graph["prs"]
        for node in pr["nodes"]
        if node["id"] not in ordered and not node.get("unchanged")
    ]
    files = sum(len(entries) for entries in ordered.values())
    print(f"diffs: {len(ordered)} nodes, {files} files -> {args.out}")
    if without:
        print(f"nodes without a diff (fix their path/files): {without}")
    if unassigned:
        print(f"changed files mapped to no node: {unassigned}")
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
