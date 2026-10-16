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
node id -> [{"path", "diff", "fp", "truncated"?, "binary"?}] with git headers stripped;
`truncated` holds the full line count of a diff cut at --max-lines. `fp` fingerprints
the file's change (see fingerprint()); the viewer compares it with the previous
build's to flag new and changed files and to clear read marks of changed ones. For
Vue, Svelte, and Astro files each hunk's @@ line names the last block tag before
the hunk, shortened to its name and lang (`<script lang="ts">`, `<template>`,
`</script>`), so the viewer highlights a hunk in the middle of a block in that
block's language. The arguments
go in the `gen_diffs` section of review-map.json beside --graph (scripts/manifest.py),
which refresh.py replays; --no-manifest skips that.
Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # importing manifest.py must not leave a __pycache__ in the skill
import manifest  # noqa: E402

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
# A diff driver for single-file components: the funcname on a hunk's @@ line is the last line before the hunk that
# starts with a block tag (git shows a pattern's first group, so the outer group holds the line). An opening tag means
# the hunk starts in that block; a closing one, outside every block (Svelte's markup). The line may hold only the start
# of a tag that spans lines, a `>` may sit inside an attribute (`generic="T extends Record<K, V>"`), and git keeps only
# its first 80 bytes, so normalise_sfc() rewrites it as a short tag with just the block name and lang.
SFC_ATTRIBUTES = "".join(f"*.{ext} diff=review-map-sfc\n" for ext in ("vue", "svelte", "astro"))
SFC_FUNCNAME = r"^(</?(template|script|style|i18n|docs)([[:space:]>].*)?)$"
SFC_EXT = (".vue", ".svelte", ".astro")
HUNK_HEAD = re.compile(r"^(@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@) ?(.*)$")
BLOCK_TAG = re.compile(r"^<(/?)(template|script|style|i18n|docs)(?=[\s>]|$)(.*)$", re.IGNORECASE)
LANG_ATTR = re.compile(r"""[\s"']lang\s*=\s*["']?([\w-]+)""", re.IGNORECASE)


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


def block_tag(text: str) -> str | None:
    """`<name lang="x">`, `<name>`, or `</name>` for a line that starts with an SFC block tag, else None."""
    match = BLOCK_TAG.match(text)
    if not match:
        return None
    closing, name, rest = match.group(1), match.group(2).lower(), match.group(3)
    if closing:
        return f"</{name}>"
    lang = LANG_ATTR.search(" " + rest)
    return f'<{name} lang="{lang.group(1)}">' if lang else f"<{name}>"


def old_lines(repo: str, rng: str, path: str | None) -> list[str] | None:
    """The lines of `path` in the version a range's diff starts from (the merge base for `A...B`), or None."""
    if not path:
        return None
    left, _sep, right = rng.partition("...") if "..." in rng else rng.partition("..")
    base = git(repo, "merge-base", left or "HEAD", right or "HEAD").strip() if "..." in rng else left or "HEAD"
    return git(repo, "show", f"{base}:{path}").split("\n")


def normalise_sfc(body: str, preimage) -> str:
    """Rewrite the block tag git put on each @@ line of a Vue/Svelte/Astro diff as a short `block_tag()`.

    When the text git gave has no lang attribute and is not a plain complete tag (it does not end in `>`, or it has
    attribute values that may hide a `>` or a cut-off lang), the whole tag is read from the file's old version
    (`preimage()`, read once and only then): the last line before the hunk that starts with that text, plus the
    lines after it up to the one that ends the tag.
    """
    lines = body.split("\n")
    old: list[str] | None = None
    for i, line in enumerate(lines):
        head = HUNK_HEAD.match(line)
        if not head or not head.group(3):
            continue
        text = head.group(3).rstrip()
        tag = block_tag(text)
        if tag is None:
            continue
        if not tag.startswith("</") and " lang=" not in tag and (not text.endswith(">") or '"' in text or "'" in text):
            if old is None:
                old = preimage() or []
            before = old[: max(0, int(head.group(2)) - 1)]
            at = next((j for j in range(len(before) - 1, -1, -1) if before[j].startswith(text) and BLOCK_TAG.match(before[j])), None)
            if at is not None:
                end = next((k for k in range(at, min(len(old), at + 12)) if old[k].rstrip().endswith(">")), at)
                tag = block_tag(" ".join(part.strip() for part in old[at:end + 1])) or tag
        lines[i] = f"{head.group(1)} {tag}"
    return "\n".join(lines)


def fingerprint(body: str, index: str = "") -> str:
    """Twelve hex digits that change exactly when a file's change does.

    The input is the file's diff body (headers stripped, before --max-lines cuts it)
    with each @@ line reduced to "@@": line numbers and the context name shift when
    lines above a hunk move, and that alone is no new change to read. A binary file
    adds its `index` line (blob ids, --full-index), since its body ("Binary files ...
    differ") is the same for every version. refresh.py fingerprints a diffs.json entry
    written before `fp` existed the same way, from its stored body; a binary or
    truncated one cannot match (no blob ids, a cut body), so it shows as changed once.
    """
    lines = ["@@" if line.startswith("@@") else line for line in body.split("\n")]
    if index:
        lines.append(index)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:12]


def split_files(diff: str) -> list[tuple[str, str, bool, str]]:
    """Split one `git diff` into (path, body, binary, fingerprint) per file, headers removed from the body."""
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
        index = ""
        for line in lines:
            if line.startswith("@@"):
                break
            if line.startswith("index "):
                index = line
            elif line.startswith("rename to "):
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
        files.append((path, body, binary, fingerprint(body, index if binary else "")))
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
    parser.add_argument("--no-manifest", action="store_true", help="do not record this run in review-map.json")
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
        diff = git(repo, *sfc_options(repo, folder.name), "diff", "--no-color", "--no-ext-diff", "--full-index", "-M",
                   f"-U{args.context}", rng)
        for path, body, binary, fp in split_files(diff):
            node_id = assign(path, pr["nodes"])
            if node_id is None:
                unassigned.append(f"{key}:{path}")
                continue
            if path.lower().endswith(SFC_EXT):
                old = next((line[6:].rstrip("\t") for line in body.split("\n") if line.startswith("--- a/")), None)
                body = normalise_sfc(body, lambda old=old, repo=repo, rng=rng: old_lines(repo, rng, old))
            entry: dict = {"path": path, "diff": body, "fp": fp}
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
    if not args.no_manifest:
        here = args.graph.resolve().parent
        manifest.record(here, "gen_diffs", {
            "graph": manifest.stored(here, args.graph), "out": manifest.stored(here, args.out),
            "prs": [{"key": key, "repo": str(Path(repo).resolve()), "range": rng} for key, repo, rng in args.pr],
            "context": args.context, "maxLines": args.max_lines, "strict": args.strict,
        })
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
