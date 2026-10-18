#!/usr/bin/env python3
"""Split one large pull request into a virtual stack of parts cut from its commits: propose and expand chunks.json.

Usage:
  python3 chunks.py propose --repo /abs/repo --range develop...feat/x --key M [--name "#251"] [--title "…"] \\
      --out chunks.json [--min-files 15] [--max-files 60] [--force]
  python3 chunks.py expand chunks.json

`propose` reads the PR's first-parent history (`git log --first-parent --reverse` with per-commit numstat, a merge
against its first parent) and groups consecutive commits by their conventional-commit scope (`feat(web): …` -> web;
without a scope its type; else a `[prefix]` or a task id such as ABC-123; a commit with none of them joins the commits
before it). A group under --min-files files merges into the neighbour that gives the smaller result, while that stays
at --max-files files or fewer; a group above --max-files splits at commit boundaries. It prints a table (part, key,
commits, files, scopes, first subjects) and writes a draft chunks.json for the owner to confirm or edit. It proposes
consecutive ranges only: it warns when a scope comes back after other scopes (interleaved history), and a merge of the
base branch gets a part of its own with a warning, since that part's diff is the base's changes, not the PR's.
Regrouping the history (an interactive rebase) stays a manual step outside the skill.

chunks.json:
  {"parent": {"key": "M", "repo": "/abs/repo", "range": "develop...feat/x", "name": "#251", "title": "…"},
   "parts": [{"key": "Ma", "to": "<full sha>", "label": "client-core"}, …]}

Part i is the range to(i-1)..to(i); part 1 starts at the merge base of the range's base and to(1) (at the base itself
for base..tip). Part keys end in a letter, so node ids (key + step number) of two parts cannot collide, and differ from
the parent key, which overlay references use for every part. `expand` checks the chain (each `to` comes after the one
before it on the branch) and prints each part's range, commits, files, and `--pr` arguments; build_graph.py and
gen_diffs.py take the file as --chunks (expand() and stack() below). See references/chunks.md. Only reads the
repository (log, rev-parse, merge-base, diff). Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing manifest.py must not leave a __pycache__ in the skill
import manifest  # noqa: E402

SHA = re.compile(r"[0-9a-fA-F]{7,40}")
# The group key of a commit subject: a conventional-commit header (`feat(web)!: …` -> web, `docs: …` -> docs, also a
# plain `Mobile: …` prefix), else a bracketed prefix (`[iOS] …`), else a task id (`ABC-123`).
HEADER = re.compile(r"^(?P<type>[A-Za-z][\w./-]*)(?:\((?P<scope>[^()]*)\))?!?:\s")
BRACKET = re.compile(r"^\[(?P<tag>[^\]]{1,30})\]")
TASK = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
LABEL_MAX = 40
SUGGEST_FILES, SUGGEST_NODES = 100, 60  # above either, build_graph.py suggests parts for a PR
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def git(repo: str, *args: str, check: bool = True, stdin: str | None = None) -> str | None:
    result = subprocess.run(["git", "-C", repo, "-c", "core.quotePath=false", *args], input=stdin,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        if check:
            raise SystemExit(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
        return None
    return result.stdout


def commit(repo: str, rev: str) -> str | None:
    """The full SHA of the commit `rev` names, or None."""
    out = git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}", check=False)
    return out.strip() or None if out else None


def short(repo: str, sha: str) -> str:
    out = git(repo, "rev-parse", "--short", "--end-of-options", sha, check=False)
    return (out or sha[:7]).strip()


def ancestor(repo: str, older: str, newer: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", "--end-of-options", older, newer, check=False) is not None


def sides(rng: str) -> tuple[str, str, bool]:
    """(base, tip, three dots) of a range."""
    three = "..." in rng
    base, tip = rng.split("..." if three else "..", 1)
    return base or "HEAD", tip or "HEAD", three


def start_of(repo: str, rng: str, first: str) -> str:
    """The commit part 1 starts from: the merge base of the range's base and `first` for base...tip, else the base."""
    base, _tip, three = sides(rng)
    if three:
        found = (git(repo, "merge-base", "--end-of-options", base, first, check=False) or "").strip()
    else:
        found = commit(repo, base) or ""
    if not found:
        raise SystemExit(f"cannot find where {rng!r} starts in {repo}; fetch the base or fix the range")
    return found


def part_key(parent: str, index: int) -> str:
    """The key of part index (0-based): the parent key plus a, b, …, z, aa, ab, … (always ending in a letter)."""
    letters, n = "", index
    while n >= 0:
        letters = LETTERS[n % 26] + letters
        n = n // 26 - 1
    return parent + letters


def next_key(data: dict) -> str:
    taken = {data["parent"]["key"], *(part["key"] for part in data["parts"])}
    index = len(data["parts"])
    while part_key(data["parent"]["key"], index) in taken:
        index += 1
    return part_key(data["parent"]["key"], index)


def key_ok(key) -> bool:
    """A part key: a PR key (manifest.KEY) that ends in an ASCII letter."""
    return isinstance(key, str) and bool(manifest.KEY.fullmatch(key)) and key[-1].isascii() and key[-1].isalpha()


def text_ok(value) -> bool:
    return isinstance(value, str) and not CONTROL.search(value)


def check(data, where: str = "chunks.json") -> dict:
    """The chunks data, checked for shape without git; SystemExit names the first problem."""
    def fail(message: str):
        raise SystemExit(f"{where}: {message}")

    if not isinstance(data, dict):
        fail('expected {"parent": {...}, "parts": [...]}')
    parent, parts = data.get("parent"), data.get("parts")
    if not isinstance(parent, dict) or not all(isinstance(parent.get(f), str) for f in ("key", "repo", "range")):
        fail('"parent" needs a key, an absolute repo path, and a range (strings)')
    manifest.check_pr(parent["key"], parent["repo"], parent["range"])
    for field in ("name", "title"):
        if field in parent and not text_ok(parent[field]):
            fail(f'parent "{field}" must be a string without control characters')
    if not isinstance(parts, list) or not parts:
        fail('"parts" must be a non-empty list')
    seen = {parent["key"]}
    for number, part in enumerate(parts, 1):
        if not isinstance(part, dict):
            fail(f"part {number} must be an object with key, to, and label")
        key, to = part.get("key"), part.get("to")
        if not key_ok(key):
            fail(f"part {number}: key {key!r} must be letters, digits, '_' or '-' and end in a letter (Ma, Mb, …)")
        if key in seen:
            fail(f"part {number}: key {key!r} is used twice or is the parent's key")
        seen.add(key)
        if not isinstance(to, str) or not SHA.fullmatch(to):
            fail(f"part {key}: to must be a commit SHA (7 to 40 hex digits; write the full SHA), not {to!r}")
        if not text_ok(part.get("label", "")):
            fail(f"part {key}: label must be a string without control characters")
    return data


def load(path: Path | str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"{path}: cannot read the chunks file: {error}") from error
    return check(data, str(path))


def part_name(parent_name: str, chunk: dict) -> str:
    """The default display name of a part: `#251 2/5 web`."""
    return f"{parent_name} {chunk['index']}/{chunk['count']}" + (f" {chunk['label']}" if chunk.get("label") else "")


def expand(data: dict, where: str = "chunks.json") -> dict:
    """Resolve chunks against the repository and check the chain.

    Returns {"parent": {key, repo, range, name?, title?, start, end, tip}, "parts": [{key, repo, range, label, chunk}]}
    with full SHAs: `start` is where part 1 starts, `end` the last part's end, `tip` the branch tip now. Each part's
    range is `from..to` and its chunk {of, index, count, from, to, commits, subjects (the first 5, oldest first),
    label}; `commits` counts the first-parent commits of the part.
    """
    parent, repo = data["parent"], data["parent"]["repo"]
    ends = []
    for part in data["parts"]:
        sha = commit(repo, part["to"])
        if not sha:
            raise SystemExit(f"{where}: part {part['key']} ends at {part['to']}, which is not a commit in {repo}; "
                             "fetch it or re-run chunks.py propose")
        ends.append(sha)
    start = start_of(repo, parent["range"], ends[0])
    out, previous = [], start
    for index, (part, end) in enumerate(zip(data["parts"], ends), 1):
        if end == previous or not ancestor(repo, previous, end):
            after = "the start of the range" if index == 1 else f"the end of part {data['parts'][index - 2]['key']}"
            raise SystemExit(f"{where}: part {part['key']} ends at {end[:7]}, which does not come after {after} "
                             f"({previous[:7]}); parts must follow the branch in order (re-run chunks.py propose)")
        log = git(repo, "log", "--first-parent", "--reverse", "--format=%s", "--end-of-options", f"{previous}..{end}") or ""
        subjects = log.splitlines()
        label = part.get("label", "")
        out.append({"key": part["key"], "repo": repo, "range": f"{previous}..{end}", "label": label,
                    "chunk": {"of": parent["key"], "index": index, "count": len(ends), "from": previous, "to": end,
                              "commits": len(subjects), "subjects": subjects[:5], "label": label}})
        previous = end
    return {"parent": {**parent, "start": start, "end": ends[-1], "tip": commit(repo, sides(parent["range"])[1]) or ""},
            "parts": out}


def stack(prs, files) -> tuple[list[dict], list[dict]]:
    """The PRs in merge order with each chunked parent replaced by its parts, and the expanded chunks files.

    `prs` are (key, repo, range) from --pr, `files` the --chunks paths. A --pr whose key is a chunks file's parent key
    marks where the parts go (its repository and range must be the file's); without one they follow the --pr entries.
    Each entry is {key, repo, range} plus, for a part, its label, chunk, and parent key.
    """
    entries = [{"key": key, "repo": repo, "range": rng} for key, repo, rng in prs]
    parents = []
    for path in files:
        expanded = expand(load(path), str(path))
        key = expanded["parent"]["key"]
        if any(p["parent"]["key"] == key for p in parents):
            raise SystemExit(f"--chunks: two files split PR {key}")
        parts = [{**part, "parent": key} for part in expanded["parts"]]
        at = next((i for i, e in enumerate(entries) if e["key"] == key and "chunk" not in e), None)
        if at is None:
            entries.extend(parts)
        else:
            entry = entries[at]
            if Path(entry["repo"]).resolve() != Path(expanded["parent"]["repo"]).resolve() or entry["range"] != expanded["parent"]["range"]:
                raise SystemExit(f"--pr {key} marks where the parts of {path} go but names another repository or range; "
                                 f"give {expanded['parent']['repo']} {expanded['parent']['range']}")
            entries[at:at + 1] = parts
        parents.append(expanded)
    keys = [entry["key"] for entry in entries]
    if len(set(keys)) != len(keys):
        raise SystemExit(f"PR keys must be unique, also across parts: {keys}")
    for expanded in parents:
        if expanded["parent"]["key"] in keys:
            raise SystemExit(f"PR {expanded['parent']['key']} is split into parts; its key cannot also name a PR")
    return entries, parents


def graph_errors(graph) -> list[str]:
    """What is wrong with the parts in graphs.json (assemble.py and validate.py): parents and chunk fields."""
    prs = graph.get("prs") if isinstance(graph, dict) else None
    if not isinstance(prs, list):
        return []
    prs = [pr for pr in prs if isinstance(pr, dict)]
    parents = graph.get("parents")
    chunked = [pr for pr in prs if "chunk" in pr]
    if parents is None and not chunked:
        return []
    if not isinstance(parents, list):
        return ['graphs.json "parents" must be a list when PRs carry "chunk"']
    errors, keys, known = [], [pr.get("key") for pr in prs], set()
    for parent in parents:
        if not isinstance(parent, dict) or not isinstance(parent.get("key"), str) or not manifest.KEY.fullmatch(parent["key"]):
            errors.append(f"parent {parent!r} needs a key of letters, digits, '_' or '-'")
            continue
        key = parent["key"]
        if key in keys or key in known:
            errors.append(f"parent key {key!r} is also a PR key or another parent's")
        known.add(key)
        parts = [pr for pr in prs if isinstance(pr.get("chunk"), dict) and pr["chunk"].get("of") == key]
        if not parts:
            errors.append(f"parent {key} has no parts")
        elif parent.get("parts") != [pr.get("key") for pr in parts]:
            errors.append(f"parent {key}: parts {parent.get('parts')!r} are not its part PRs in order {[pr.get('key') for pr in parts]!r}")
        at = [keys.index(pr.get("key")) for pr in parts]
        if at and at != list(range(at[0], at[0] + len(at))):
            errors.append(f"parent {key}: its parts must follow each other in the PR list")
        for index, pr in enumerate(parts, 1):
            chunk = pr["chunk"]
            if not key_ok(pr.get("key")):
                errors.append(f"part {pr.get('key')!r} of {key}: a part key must end in a letter")
            if chunk.get("index") != index or chunk.get("count") != len(parts):
                errors.append(f"part {pr.get('key')} of {key}: index/count {chunk.get('index')}/{chunk.get('count')}, expected {index}/{len(parts)}")
            if not all(isinstance(chunk.get(f), str) and SHA.fullmatch(chunk[f]) for f in ("from", "to")):
                errors.append(f"part {pr.get('key')} of {key}: from and to must be commit SHAs")
            elif index > 1 and chunk["from"] != parts[index - 2]["chunk"].get("to"):
                errors.append(f"part {pr.get('key')} of {key}: starts at {chunk['from'][:7]}, not where part "
                              f"{parts[index - 2].get('key')} ends ({str(parts[index - 2]['chunk'].get('to'))[:7]})")
            if not isinstance(chunk.get("commits"), int) or isinstance(chunk.get("commits"), bool) or not isinstance(chunk.get("subjects", []), list):
                errors.append(f"part {pr.get('key')} of {key}: commits must be an integer and subjects a list")
    for pr in chunked:
        chunk = pr.get("chunk")
        if not isinstance(chunk, dict) or chunk.get("of") not in known:
            errors.append(f"PR {pr.get('key')}: chunk names no parent in \"parents\"")
    return errors


# --- propose -------------------------------------------------------------------------------------------------------

def scope_of(subject: str) -> str:
    """The group key of a commit subject, lowercased; "" when it has none."""
    match = HEADER.match(subject)
    if match:
        return (match.group("scope") or match.group("type")).strip().lower()
    match = BRACKET.match(subject)
    if match:
        return match.group("tag").strip().lower()
    match = TASK.search(subject)
    return match.group(0) if match else ""


def history(repo: str, start: str, tip: str) -> list[dict]:
    """First-parent commits start..tip, oldest first: sha, parents, subject, and files (a merge against its first parent)."""
    out = git(repo, "log", "--first-parent", "--reverse", "-m", "--no-renames", "--numstat",
              "--format=%x1e%H%x1f%P%x1f%s", "--end-of-options", f"{start}..{tip}") or ""
    commits = []
    for block in out.split("\x1e")[1:]:
        head, _sep, body = block.partition("\n")
        sha, parents, subject = (head.split("\x1f", 2) + ["", ""])[:3]
        files = {}
        for line in body.splitlines():
            fields = line.split("\t", 2)
            if len(fields) == 3:
                files[fields[2]] = (int(fields[0]) if fields[0].isdigit() else 0, int(fields[1]) if fields[1].isdigit() else 0)
        commits.append({"sha": sha, "parents": parents.split(), "subject": subject, "files": files})
    return commits


def base_merge(repo: str, entry: dict, base: str) -> bool:
    """A merge commit that brings in the base branch: one of its other parents is an ancestor of the base."""
    return len(entry["parents"]) > 1 and any(ancestor(repo, p, base) for p in entry["parents"][1:])


def files_of(run: dict) -> set[str]:
    return set().union(*(set(c["files"]) for c in run["commits"]))


def scopes_in(commits: list[dict]) -> list[str]:
    out: list[str] = []
    for entry in commits:
        key = scope_of(entry["subject"])
        if key and key not in out:
            out.append(key)
    return out


def group(repo: str, commits: list[dict], base: str) -> list[dict]:
    """Consecutive commits with the same key form a run; a commit without a key joins the run before it, and a base
    merge forms a run of its own."""
    runs: list[dict] = []
    for entry in commits:
        if base_merge(repo, entry, base):
            runs.append({"keys": [], "commits": [entry], "merge": True})
            continue
        key, last = scope_of(entry["subject"]), runs[-1] if runs else None
        if last and not last["merge"] and (not key or not last["keys"] or last["keys"][-1] == key):
            last["commits"].append(entry)
            if key and not last["keys"]:
                last["keys"].append(key)
        else:
            runs.append({"keys": [key] if key else [], "commits": [entry], "merge": False})
    return runs


def merge_small(runs: list[dict], min_files: int, max_files: int) -> list[dict]:
    """Merge each run under min_files files (the smallest first, then the earliest) into the neighbour that gives the
    smaller union, the earlier one on a tie, while the union stays at max_files or fewer. Base merges never merge."""
    runs = list(runs)
    stuck: set[int] = set()
    while True:
        small = [i for i, run in enumerate(runs) if not run["merge"] and id(run) not in stuck and len(files_of(run)) < min_files]
        if not small:
            return runs
        i = min(small, key=lambda i: (len(files_of(runs[i])), i))
        options = []
        for j in (i - 1, i + 1):
            if 0 <= j < len(runs) and not runs[j]["merge"]:
                size = len(files_of(runs[i]) | files_of(runs[j]))
                if size <= max_files:
                    options.append((size, 0 if j < i else 1, j))
        if not options:
            stuck.add(id(runs[i]))
            continue
        j = min(options)[2]
        a, b = sorted((i, j))
        runs[a:b + 1] = [{"keys": runs[a]["keys"] + [k for k in runs[b]["keys"] if k not in runs[a]["keys"]],
                          "commits": runs[a]["commits"] + runs[b]["commits"], "merge": False}]


def split_big(runs: list[dict], max_files: int) -> list[dict]:
    """Split a run above max_files files at commit boundaries, each piece as large as fits."""
    out = []
    for run in runs:
        if run["merge"] or len(run["commits"]) == 1 or len(files_of(run)) <= max_files:
            out.append(run)
            continue
        pieces, current, seen = [], [], set()
        for entry in run["commits"]:
            files = set(entry["files"])
            if current and len(seen | files) > max_files:
                pieces.append(current)
                current, seen = [], set()
            current.append(entry)
            seen |= files
        pieces.append(current)
        for n, piece in enumerate(pieces, 1):
            out.append({"keys": scopes_in(piece) or run["keys"], "commits": piece, "merge": False, "piece": (n, len(pieces))})
    return out


def label_of(run: dict) -> str:
    if run["merge"]:
        text = run["commits"][0]["subject"]
    elif run["keys"]:
        text = " + ".join(run["keys"][:3]) + (" + …" if len(run["keys"]) > 3 else "")
    else:
        text = run["commits"][0]["subject"]
    if run.get("piece"):
        text += " ({}/{})".format(*run["piece"])
    return text if len(text) <= LABEL_MAX else text[: LABEL_MAX - 1].rstrip() + "…"


def propose(repo: str, rng: str, key: str, min_files: int = 15, max_files: int = 60) -> tuple[list[dict], list[str], dict]:
    """Proposed parts (runs with key, to, label, commits, files), warnings, and totals for one PR's range."""
    manifest.check_pr(key, repo, rng)
    base, tip_ref, _three = sides(rng)
    tip = commit(repo, tip_ref)
    if not tip:
        raise SystemExit(f"cannot resolve {tip_ref!r} in {repo}; fetch it or fix the range")
    start = start_of(repo, rng, tip)
    commits = history(repo, start, tip)
    if not commits:
        raise SystemExit(f"{rng}: no commits between {start[:7]} and {tip[:7]}")
    runs = split_big(merge_small(group(repo, commits, base), min_files, max_files), max_files)
    warnings, where = [], {}
    for index, run in enumerate(runs):
        run["key"], run["to"], run["label"] = part_key(key, index), run["commits"][-1]["sha"], label_of(run)
        for scope in run["keys"]:
            where.setdefault(scope, []).append(index + 1)
        if run["merge"]:
            warnings.append(f"part {index + 1} ({run['key']}) holds only the base merge {run['to'][:7]} "
                            f"\"{run['commits'][0]['subject']}\": its diff is the base branch's changes, not the PR's; skip it "
                            "when reading (folding it into a neighbour would put those changes into that part's diff)")
        elif len(run["commits"]) == 1 and len(files_of(run)) > max_files:
            warnings.append(f"part {index + 1} ({run['key']}): commit {run['to'][:7]} alone changes {len(files_of(run))} "
                            f"files (above --max-files {max_files}); it cannot be split further")
    for scope, parts in where.items():
        if parts != list(range(parts[0], parts[0] + len(parts))):
            warnings.append(f"scope {scope!r} appears in parts {', '.join(map(str, parts))} with other scopes between them "
                            "(interleaved history); merge the parts in chunks.json, or regroup the commits outside the skill")
    numstat = git(repo, "diff", "--numstat", "--no-renames", "--end-of-options", f"{start}..{tip}", "--") or ""
    totals = {"commits": len(commits), "files": len([line for line in numstat.splitlines() if line.strip()]), "start": start, "tip": tip}
    return runs, warnings, totals


def table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return ["  ".join(cell.ljust(widths[i]) if i < len(row) - 1 else cell for i, cell in enumerate(row)).rstrip() for row in rows]


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_propose(args) -> int:
    repo = str(Path(args.repo).resolve())
    if args.out.exists() and not args.force:
        raise SystemExit(f"{args.out} exists; it may hold the owner's edits. Pass --force to overwrite it")
    runs, warnings, totals = propose(repo, args.range, args.key, args.min_files, args.max_files)
    name = args.name or args.key
    verdict = (f"above {SUGGEST_FILES} files, parts are worth it" if totals["files"] > SUGGEST_FILES
               else f"at or below {SUGGEST_FILES} files a single map usually reads well (build_graph.py also suggests parts above {SUGGEST_NODES} nodes)")
    print(f"{args.key} ({name}): {totals['files']} files in {totals['commits']} commits, {totals['start'][:7]}..{totals['tip'][:7]}; {verdict}")
    rows = [["part", "key", "commits", "files", "scopes", "first subjects"]]
    for index, run in enumerate(runs, 1):
        subjects = "; ".join(c["subject"] for c in run["commits"][:2]) + (" …" if len(run["commits"]) > 2 else "")
        rows.append([f"{index}/{len(runs)}", run["key"], str(len(run["commits"])), str(len(files_of(run))),
                     clip(run["label"], 30), clip(subjects, 80)])
    for line in table(rows):
        print(line)
    parent = {"key": args.key, "repo": repo, "range": args.range}
    if args.name:
        parent["name"] = args.name
    if args.title:
        parent["title"] = args.title
    data = check({"parent": parent, "parts": [{"key": r["key"], "to": r["to"], "label": r["label"]} for r in runs]}, str(args.out))
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"draft -> {args.out}: confirm the parts with the owner (merge, split, or relabel them by editing the file; "
          "keys end in a letter, `to` is a full SHA), then pass --chunks to build_graph.py and gen_diffs.py")
    for warning in warnings:
        print(f"warning: {warning}")
    return 0


def cmd_expand(args) -> int:
    expanded = expand(load(args.file), str(args.file))
    parent, parts = expanded["parent"], expanded["parts"]
    repo, name = parent["repo"], parent.get("name") or parent["key"]
    print(f"{parent['key']} ({name}): {len(parts)} parts of {parent['range']}, {parent['start'][:7]}..{parent['end'][:7]}")
    if parent["tip"] and parent["tip"] != parent["end"]:
        print(f"warning: the branch tip is {parent['tip'][:7]}, not where the last part ends; refresh.py adds the commits after it as a new part")
    rows = [["part", "key", "range", "commits", "files", "label"]]
    for part in parts:
        chunk = part["chunk"]
        files = len([line for line in (git(repo, "diff", "--name-only", "--end-of-options", part["range"], "--") or "").splitlines() if line])
        rows.append([f"{chunk['index']}/{chunk['count']}", part["key"], f"{chunk['from'][:7]}..{chunk['to'][:7]}",
                     str(chunk["commits"]), str(files), part["label"]])
    for line in table(rows):
        print(line)
    print("per-part --pr arguments (change maps, a hand-built graph):")
    for part in parts:
        print(f"  --pr {part['key']} {repo} {part['range']} --name {part['key']} {json.dumps(part_name(name, part['chunk']), ensure_ascii=False)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    prop = sub.add_parser("propose", help="propose parts from the PR's commits and write a draft chunks.json")
    prop.add_argument("--repo", required=True)
    prop.add_argument("--range", required=True, help="base...tip (or base..tip), as for build_graph.py --pr")
    prop.add_argument("--key", required=True, help="the PR's key; parts get it plus a letter (Ma, Mb, …)")
    prop.add_argument("--name", help="display name of the PR (#251)")
    prop.add_argument("--title", help="title of the PR")
    prop.add_argument("--out", required=True, type=Path)
    prop.add_argument("--min-files", type=int, default=15, help="merge a group under this many files into a neighbour (default 15)")
    prop.add_argument("--max-files", type=int, default=60, help="split a group above this many files (default 60)")
    prop.add_argument("--force", action="store_true", help="overwrite an existing --out")
    exp = sub.add_parser("expand", help="check a chunks.json and print each part's range and --pr arguments")
    exp.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.command == "propose":
        if args.min_files < 0 or args.max_files < 1:
            raise SystemExit("--min-files must be 0 or more and --max-files 1 or more")
        return cmd_propose(args)
    return cmd_expand(args)


if __name__ == "__main__":
    sys.exit(main())
