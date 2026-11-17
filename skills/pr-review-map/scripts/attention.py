"""Where a reviewer's attention goes: the reading budget, the size tiers, and the checks both share.

Imported by build_graph.py (first guess and overlay checks), assemble.py (the budget section), validate.py, and
refresh.py (stale focus ranges). Python 3 standard library only.

Attention (a node's `attention`): `mechanical` (read nothing: lockfiles, generated files, translations, docs, trivial
changes, pure moves), `pattern` (skim: tests, deploy config), `novel` (read), `risky` (read first: migrations by
default, whatever the overlay marks). An optional `focus` narrows a risky or novel file to the ranges that matter:
`[{"start": 12, "end": 30, "why": "…", "side": "old"}]`, lines on the new side unless `side` is `"old"` (code the PR
removes), the way tour steps and notes address lines.

The budget counts the changed lines of risky and novel nodes; a node with `focus` counts the lines of its ranges (the
union, never more than the node changes). The rest of such a node counts as skim.

Size (graphs.json `size`): `small` is one PR, no parts, at most SMALL_FILES changed files and SMALL_LINES changed lines;
`large` is more than LARGE_FILES files, more than LARGE_LINES lines, or more than LARGE_PRS PRs (a split PR counts once);
else `medium`. The overlay's `size` overrides it.
"""

from __future__ import annotations

import tours

CLASSES = ("mechanical", "pattern", "novel", "risky")
READ = ("risky", "novel")      # the classes the budget counts
SIDES = ("new", "old")
SIZES = ("small", "medium", "large")
SMALL_FILES, SMALL_LINES = 10, 400
LARGE_FILES, LARGE_LINES, LARGE_PRS = 60, 3000, 3
WHY_MAX = 200                  # characters of a focus range's reason


def count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def node_files(node: dict) -> int:
    return len(node.get("files") or [node.get("path")])


def node_lines(node: dict) -> int:
    return count(node.get("added")) + count(node.get("removed"))


def changed(graph: dict) -> list[tuple[dict, dict]]:
    """(pr, node) for every node the PR changes (reference nodes of unchanged files are not)."""
    return [(pr, node) for pr in graph.get("prs", []) for node in pr.get("nodes", []) if not node.get("unchanged")]


def focus_problems(focus: object) -> list[str]:
    """What is wrong with a node's `focus`: a non-empty list of {"start", "end", "why", "side"?} with 1 <= start <= end."""
    if not isinstance(focus, list) or not focus:
        return ["focus must be a non-empty list of {start, end, why} ranges"]
    problems = []
    for item in focus:
        if not (isinstance(item, dict) and set(item) <= {"start", "end", "why", "side"} and {"start", "end", "why"} <= set(item)):
            problems.append(f"focus entry {item!r} needs start, end, why (and optionally side)")
            continue
        start, end = item["start"], item["end"]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (start, end)) or not 1 <= start <= end:
            problems.append(f"focus entry {item!r}: start and end must be integers with 1 <= start <= end")
        if not isinstance(item["why"], str) or not item["why"].strip() or len(item["why"]) > WHY_MAX:
            problems.append(f"focus entry {item!r}: why must be text of 1 to {WHY_MAX} characters")
        if item.get("side", "new") not in SIDES:
            problems.append(f"focus entry {item!r}: side must be one of {list(SIDES)}")
    return problems


def focus_lines(focus: list[dict]) -> int:
    """Lines the ranges cover, overlapping ranges on one side counted once."""
    total = 0
    for side in SIDES:
        spans = sorted((r["start"], r["end"]) for r in focus if r.get("side", "new") == side)
        top = 0
        for start, end in spans:
            start = max(start, top + 1)
            if end >= start:
                total += end - start + 1
                top = end
    return total


def attention_of(node: dict) -> str:
    """A node's class; one a build without attention wrote counts as novel (the budget never hides what it cannot judge)."""
    value = node.get("attention")
    return value if value in CLASSES else "novel"


def read_lines(node: dict) -> int:
    """The lines of a risky or novel node the reader must read: all of them, or those of its focus ranges."""
    lines = node_lines(node)
    focus = node.get("focus")
    if isinstance(focus, list) and focus and not focus_problems(focus):
        return min(lines, focus_lines(focus))
    return lines


def budget(graph: dict) -> dict:
    """{"read": n, "total": m, "lines": {class: n}} over the changed nodes. `lines` splits `total` four ways: the
    lines to read of risky and novel nodes under their class, everything else (a focused node's remainder too) as pattern
    (skim) or mechanical (skip) as classed."""
    lines = {name: 0 for name in CLASSES}
    for _pr, node in changed(graph):
        name = attention_of(node)
        total = node_lines(node)
        if name in READ:
            part = read_lines(node)
            lines[name] += part
            lines["pattern"] += total - part
        else:
            lines[name] += total
    return {"read": lines["risky"] + lines["novel"], "total": sum(lines.values()), "lines": lines}


def size_of(files: int, lines: int, prs: int, parts: bool) -> str:
    """The tier for a change of `files` files and `lines` lines over `prs` PRs (a split PR once), `parts` when one is split."""
    if files > LARGE_FILES or lines > LARGE_LINES or prs > LARGE_PRS:
        return "large"
    if prs == 1 and not parts and files <= SMALL_FILES and lines <= SMALL_LINES:
        return "small"
    return "medium"


def size_totals(graph: dict) -> tuple[int, int, int, bool]:
    """(files, lines, PRs, has parts) of a graph: a split PR counts once with its whole-PR totals (its parts overlap)."""
    parents = [p for p in graph.get("parents") or [] if isinstance(p, dict)]
    part_keys = {key for p in parents for key in p.get("parts", [])}
    files = lines = prs = 0
    for pr in graph.get("prs", []):
        if pr.get("key") in part_keys:
            continue
        prs += 1
        for node in pr.get("nodes", []):
            if not node.get("unchanged"):
                files += node_files(node)
                lines += node_lines(node)
    for parent in parents:
        prs += 1
        members = [pr for pr in graph.get("prs", []) if pr.get("key") in parent.get("parts", [])]
        files += parent["files"] if isinstance(parent.get("files"), int) else sum(node_files(n) for pr in members for n in pr["nodes"] if not n.get("unchanged"))
        lines += (count(parent.get("added")) + count(parent.get("removed"))) if isinstance(parent.get("files"), int) \
            else sum(node_lines(n) for pr in members for n in pr["nodes"] if not n.get("unchanged"))
    return files, lines, prs, bool(parents)


def size_for(graph: dict) -> str:
    """The tier a page is built for: the graph's `size` when it names one, else a medium page (graphs from before tiers)."""
    return graph["size"] if graph.get("size") in SIZES else "medium"


def stale_focus(graph: dict, before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """(PR key, path) of every file with focus ranges whose change differs from the previous build's: the ranges were
    authored on code that changed, and refresh.py cannot tell where they moved (a file new since then was not authored on)."""
    out = []
    for pr in graph.get("prs", []):
        old, new = before.get(pr["key"], {}), after.get(pr["key"], {})
        for node in pr.get("nodes", []):
            if not node.get("focus"):
                continue
            for path in node.get("files") or [node.get("path")]:
                if path in old and path in new and old[path] != new[path]:
                    out.append((pr["key"], path))
    return out


def problems(graph: dict, diffs: object) -> tuple[list[str], list[str]]:
    """Errors and warnings about graphs.json `size` and the nodes' `attention` and `focus` (validate.py): a `size` or an
    `attention` outside its values, a malformed `focus` (errors), and (warning) a focus range that touches no hunk of the node's
    diff on its side, which the viewer then opens at the file's first line instead."""
    errors: list[str] = []
    warnings: list[str] = []
    if "size" in graph and graph["size"] not in SIZES:
        errors.append(f"size must be one of {list(SIZES)}, not {graph['size']!r}")
    for pr in graph.get("prs", []):
        for node in pr.get("nodes", []):
            where = f"node {node.get('id')} in PR {pr.get('key')}"
            if "attention" in node and node["attention"] not in CLASSES:
                errors.append(f"{where}: attention must be one of {list(CLASSES)}, not {node['attention']!r}")
            if "focus" not in node:
                continue
            found = focus_problems(node["focus"])
            errors.extend(f"{where}: {problem}" for problem in found)
            entries = diffs.get(node.get("id")) if isinstance(diffs, dict) else None
            if found or not isinstance(entries, list):
                continue
            for item in node["focus"]:
                side = item.get("side", "new")
                spans = [span for entry in entries if isinstance(entry, dict) for span in tours.hunk_spans(entry.get("diff", ""), side)]
                if not any(start <= item["end"] and item["start"] <= end for start, end in spans):
                    warnings.append(f"{where}: focus {item['start']}-{item['end']} ({side} side) is outside every hunk of its diff")
    return errors, warnings
