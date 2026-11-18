#!/usr/bin/env python3
"""Assemble the review-map page: viewer template + graph and diff data + authored narrative.

Usage:
  python3 assemble.py --graph graphs.json --diffs diffs.json --narrative narrative.html \\
      --title "Review: …" --lang pl --out report.html \\
      [--strings overrides.json] [--storage-key my-review] [--target artifact|local] \\
      [--template ../assets/viewer.html] [--previous previous.json] [--spot-check N] [--screens screens.json]

The narrative is HTML for <main>, split by one line `<!-- review-map:graph -->`:
everything before it (the title header and the brief) renders above the reading graph,
everything after it (architecture, request flow, changes per PR, before merging, footer)
below. assemble.py itself adds two sections to the end of the part above the line: for a
large change (graphs.json `size`, scripts/attention.py) the reading budget (lines to read
of those changed, a bar of the four attention classes, the files to read grouped by PR,
each opening at its focus, then a spot-check of --spot-check N (default 3, 0 off) skim files picked by attention.spot_pick,
seeded from the PR tips), then the merge order: one
line per PR with its key, name, title, tip SHA, file count, and +/-, all taken from
graphs.json (a PR split into parts gets one line with its parts under it), so the
numbers are never typed by hand and stay right after refresh.py. The table of contents
is built from each `<section id="…">` and its first <h2> (or its `data-toc` attribute).

--target artifact (default) emits the fragment the Claude Artifact page contract
expects: it starts with <title>, and diagrams in <pre class="mermaid"> are rendered
by the host. --target local emits a complete document and loads mermaid from cdnjs.
Both carry the theme switch (View › Theme: Auto, Light, Dark), applied before the
first paint; on a theme change the viewer redraws the diagrams itself for --target
local and, for --target artifact, only through a window.mermaid the host exposes.
The target is in review-config as "target".

UI strings come from assets/strings.json for --lang, overridden key by key by
--strings. JSON data is embedded in <script type="application/json"> blocks with
`</` written as `<\\/` and `<!--` as `<\\u0021--`, both valid JSON escapes that keep
the HTML parser out of the data.

The brief gets one generated progress line at its top (verdicts on the risks `id="risk-N"` and the decisions `id="dec-N"` of the
narrative, the must-read files, the spot-check; "Ready to merge" or "Not ready:" with counts) and a "Copy fix brief" button; the
viewer keeps it up to date from the reader's verdicts, which live in localStorage beside the notes.

--screens names a screens.json (scripts/screens.py, references/screenshots.md): the before/after screenshots, taken only
when the user asked for them. It is checked as `screens.py check` does (a failure stops the build), each image is embedded as a
data URI in a `screens-data` JSON block written like the others, and the viewer shows them in the brief after "What changes for
users". A pair whose `tip` differs from its PR's tip in graphs.json is marked stale (`taken at <sha>, code changed since`).
The path goes in review-map.json, which refresh.py replays (a `screens.json` beside review-map.json is picked up by refresh.py
even when it was added later).

--previous names the previous build's generation, tips, and file fingerprints
({"generation": n, "tips": {KEY: sha}, "files": {KEY: {path: fp}}}, written by
refresh.py); the page then shows what changed since that version.

Every page carries a generation, which the viewer uses to clear read marks of files
that changed since they were read and never on an older page. It comes from the page
this build replaces: --out if it exists, else the page the manifest last recorded
(manifest.history). The same content (every file's PR, path, and fingerprint) keeps
that page's generation, so rebuilding from the same data gives the same bytes; any
other content counts one up, whether the data came from refresh.py or the scripts by
hand; when the content differs, it is also above the generation of --previous. A page
with no readable page before it starts at 0 (or one above --previous). A generation is
an int from 0 to 2**31.

A PR `color` must be a palette slot (`var(--pal-3)`), a hex colour, or a colour
name: it lands in CSS. A PR split into parts (graphs.json `parents`, chunks.py)
must have contiguous parts numbered 1..n, each starting where the one before ends,
with keys that end in a letter; the parent's narrative class `c-<KEY>` takes its
first part's colour. Tours (graphs.json `tours`) must name known nodes and their files
(scripts/tours.py); a narrative button with `data-tour="<id>"` starts one.
The arguments, with the storage key and the spot-check size as resolved, go in the `assemble` section of
review-map.json beside --graph (scripts/manifest.py), which refresh.py replays;
--no-manifest skips that. Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing manifest.py must not leave a __pycache__ in the skill
import attention  # noqa: E402
import chunks  # noqa: E402
import manifest  # noqa: E402
import screens  # noqa: E402
import tours  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "viewer.html"
STRINGS_FILE = HERE.parent / "assets" / "strings.json"
MARKER = "<!-- review-map:graph -->"
PLACEHOLDER = re.compile(r"\{\{(S:[A-Za-z0-9_]+|[A-Z_]+)\}\}")
KEY = re.compile(r"^[A-Za-z0-9_-]+$")
COLOR = re.compile(r"var\(--pal-[1-8]\)|#[0-9A-Fa-f]{3,8}|[A-Za-z]{3,20}")
# The viewer draws the diagrams with it (and again in the other theme when the page turns light or dark).
MERMAID_LOCAL = '<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.15.0/mermaid.min.js"></script>\n'


def embed_json(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("<!--", "<\\u0021--")


def strip_tags(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", fragment).split())


def toc_entries(fragment: str) -> list[tuple[str, str]]:
    entries = []
    starts = [m for m in re.finditer(r"<section\b([^>]*)>", fragment, re.IGNORECASE)]
    for index, match in enumerate(starts):
        attrs = match.group(1)
        ident = re.search(r'\bid="([^"]+)"', attrs)
        if not ident:
            continue
        label = re.search(r'\bdata-toc="([^"]*)"', attrs)
        if label:
            text = label.group(1)
        else:
            end = starts[index + 1].start() if index + 1 < len(starts) else len(fragment)
            heading = re.search(r"<h2\b[^>]*>(.*?)</h2>", fragment[match.end():end], re.IGNORECASE | re.DOTALL)
            text = strip_tags(heading.group(1)) if heading else ident.group(1)
        entries.append((ident.group(1), text))
    return entries


def stat_counts(nodes: list[dict]) -> tuple[int, int, int]:
    """(files, added, removed) over the changed nodes of a PR; a group node stands for each of its files."""
    changed = [n for n in nodes if not n.get("unchanged")]

    def count(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0

    return (sum(len(n.get("files") or [n.get("path")]) for n in changed),
            sum(count(n.get("added")) for n in changed), sum(count(n.get("removed")) for n in changed))


def merge_order_meta(strings: dict, tip: str, counts: tuple[int, int, int]) -> str:
    files, added, removed = counts
    bits = [f"<code>{html.escape(str(tip))}</code>" if tip else "",
            html.escape(strings["mergeOrderFiles"].replace("{n}", str(files))),
            f"+{added}/\u2212{removed}"]
    return '<span class="meta">' + " · ".join(b for b in bits if b) + "</span>"


HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def first_line(diffs: dict, node: dict) -> tuple[str, int]:
    """(side, line) of the first changed hunk of a node's diff: where a reader opens a file with no `focus` (line 1 when the
    diff has no hunk, the old side for a file the PR deletes)."""
    for entry in diffs.get(node["id"]) or []:
        hunk = HUNK.search(entry.get("diff", ""))
        if hunk:
            return ("old", int(hunk.group(1))) if int(hunk.group(2)) == 0 else ("new", int(hunk.group(2)))
    return "new", 1


def plural_form(forms: object, n: int) -> str:
    """The form of a count string for n: `forms` is a string, or {one, few, many, other} (Polish when `few` or `many` is given,
    else English's one and other), the `other` form when the category has none."""
    if not isinstance(forms, dict):
        return str(forms)
    if "few" in forms or "many" in forms:
        category = "one" if n == 1 else "few" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "many"
    else:
        category = "one" if n == 1 else "other"
    return str(forms.get(category) or forms.get("other") or "")


def budget_entry(node: dict, diffs: dict, show_why: bool, strings: dict) -> str:
    """One line of a budget list: the file at its focus (else its first change) as a `path:lines` reference the viewer
    opens like any code link, the reason, and the lines to read ("· 39 lines", muted, right after the reason)."""
    focus = [r for r in node.get("focus") or [] if isinstance(r, dict)] if not attention.focus_problems(node.get("focus")) else []
    path = str(node.get("path"))
    if focus:
        top = focus[0]
        side, span = top.get("side", "new"), f"{top['start']}" + (f"-{top['end']}" if top["end"] != top["start"] else "")
        why = top["why"]
    else:
        side, line = first_line(diffs, node)
        span, why = str(line), node.get("role") or ""
    mark = ' data-side="old"' if side == "old" else ""
    text = f"<code{mark}>{html.escape(path)}:{span}</code>"
    note = f' <span class="b-why">{html.escape(str(why))}</span>' if show_why and why else ""
    lines = attention.read_lines(node)
    count = plural_form(strings["budgetLines"], lines).replace("{n}", str(lines))
    return f'<li>{text}{note} <span class="b-n">{html.escape(count)}</span></li>'


def budget_section(graph: dict, diffs: dict, strings: dict, spot: int = 0) -> str:
    """The generated "Reading budget" (large changes): lines to read of those changed, a stacked bar of the four classes, then
    the files to read, risky ones first with why, grouped by PR, then the spot-check of `spot` skim files (none when 0 or when
    the change has no skim file to sample). Empty when nothing changed."""
    figures = attention.budget(graph)
    total, read = figures["total"], figures["read"]
    if not total:
        return ""
    percent = max(1, round(100 * read / total)) if read else 0
    title = html.escape(strings["budgetTitle"])
    words = {"risky": strings["budgetMust"], "novel": strings["budgetRead"], "pattern": strings["budgetSkim"], "mechanical": strings["budgetSkip"]}
    order = ("risky", "novel", "pattern", "mechanical")
    summary = strings["budgetSummary"].replace("{n}", str(read)).replace("{m}", str(total)).replace("{p}", str(percent))
    bar = "".join(f'<span class="b-seg b-{name}" style="width:{100 * figures["lines"][name] / total:.2f}%" title="{html.escape(words[name])}: {figures["lines"][name]}"></span>'
                  for name in order if figures["lines"][name])
    label = html.escape(strings["budgetBar"].replace("{list}", ", ".join(f"{words[n]} {figures['lines'][n]}" for n in order)), quote=True)
    key = "".join(f'<li class="b-{name}"><i></i>{html.escape(words[name])} <b>{figures["lines"][name]}</b></li>' for name in order)
    blocks = []
    for name in ("risky", "novel"):
        groups = []
        for pr in graph["prs"]:
            nodes = [n for n in pr["nodes"] if not n.get("unchanged") and attention.attention_of(n) == name and attention.read_lines(n)]
            if nodes:
                items = "".join(budget_entry(n, diffs, name == "risky" or bool(n.get("focus")), strings) for n in nodes)
                groups.append(f'<div class="b-group" data-b="{"must" if name == "risky" else "read"}"><span class="who tag c-{html.escape(pr["key"])}">{html.escape(pr["key"])}</span> '
                              f'<ul class="b-list">{items}</ul></div>')
        if groups:
            count = sum(g.count("<li>") for g in groups)
            heading = f"{html.escape(words[name])} ({count})"
            blocks.append(f'<h3 class="b-{name}">{heading}</h3>\n' + "\n".join(groups) if name == "risky" else
                          f'<details class="b-more"{" open" if count <= 12 else ""}><summary>{heading}</summary><div class="body">' + "\n".join(groups) + "</div></details>")
    picks = attention.spot_pick(graph, spot)
    warn = ""
    if picks:
        groups = []
        for pr in graph["prs"]:
            mine = [node for owner, node in picks if owner is pr]
            if mine:
                groups.append(f'<div class="b-group" data-b="spot"><span class="who tag c-{html.escape(pr["key"])}">{html.escape(pr["key"])}</span> '
                              f'<ul class="b-list">{"".join(budget_entry(n, diffs, False, strings) for n in mine)}</ul></div>')
        blocks.append(f'<div class="b-spot"><h3 class="b-pattern">{html.escape(strings["spotTitle"])} ({len(picks)})</h3>\n'
                      f'<p class="b-spotnote">{html.escape(strings["spotNote"])}</p>\n' + "\n".join(groups) + "</div>")
        warn = '\n<div class="callout warn b-spotwarn" role="status" hidden></div>'
    return (f'<section id="budget" data-toc="{title}">\n<h2>{title}</h2>\n<p class="b-sum"><strong>{html.escape(summary)}</strong></p>{warn}\n'
            f'<div class="b-bar" role="img" aria-label="{label}">{bar}</div>\n<ul class="b-key">{key}</ul>\n' + "\n".join(blocks) + "\n</section>")


def count_text(strings: dict, key: str, n: int) -> str:
    return plural_form(strings[key], n).replace("{n}", str(n))


def progress_html(strings: dict, risks: int, decisions: int, must: int, spot: int) -> str:
    """The brief's progress line as the page starts out, with no verdict given: counters ("Risks 0/7 · Decisions 0/5 ·
    Must read 0/17 · Spot-check 0/3"), then "Not ready:" with what is open, and the "Copy fix brief" button (off until there
    is something to copy). The viewer rewrites the counters and the state from the reader's verdicts, so a page read without
    script shows this. Empty when the change has nothing to track."""
    if not (risks or decisions or must or spot):
        return ""
    counters = " · ".join(strings[key].replace("{n}", "0").replace("{m}", str(total)) for key, total in
                          (("progRisks", risks), ("progDecisions", decisions), ("progMust", must), ("progSpot", spot)) if total)
    state = ""
    if risks or decisions or spot:
        parts = [f'<button type="button" class="nt-b lnk pg-j" data-j="{jump}">{html.escape(count_text(strings, key, total))}</button>'
                 for jump, key, total in (("openRisk", "progOpenRisk", risks), ("openDec", "progOpenDec", decisions), ("openSpot", "progOpenSpot", spot)) if total]
        state = f'<span class="pg-state not" id="pg-state" aria-live="polite"><strong>{html.escape(strings["progNot"])}</strong> ' + ", ".join(parts) + "</span>"
    return (f'<div class="vd-prog" id="vd-prog" role="group" aria-label="{html.escape(strings["progLabel"], quote=True)}">'
            f'<span class="pg-n" id="pg-n">{html.escape(counters)}</span>{state}'
            f'<button type="button" class="nt-b" id="vd-copy" disabled>{html.escape(strings["fixCopy"])}</button></div>')


def with_progress(head: str, block: str) -> str:
    """`head` with the progress line right after the brief's heading (or its opening tag when it has none)."""
    found = re.search(r'<section\b[^>]*\bid="brief"[^>]*>(\s*<h2\b.*?</h2>)?', head, re.IGNORECASE | re.DOTALL)
    return head if not (found and block) else head[:found.end()] + "\n" + block + head[found.end():]


def merge_order(graph: dict, strings: dict, small: bool = False) -> str:
    """The generated header section: one line per PR in merge order (key, name, title, tip, files, +/-), from graphs.json,
    with the PR's authored `summary` (overlay `summaries`) under it when it has one. The name links to the PR's section,
    `id="pr-KEY"` in the narrative (the whole row follows the link); a small change has no such section, so its link goes to
    the graph.

    A PR split into parts is one line (its counts over the whole PR when build_graph.py wrote them, else the parts' sum)
    with its parts under it, each with its open button, label, counts, and range."""
    prs = {pr["key"]: pr for pr in graph["prs"]}
    parents = {parent["key"]: parent for parent in graph.get("parents") or []}
    part_of = {key: parent["key"] for parent in parents.values() for key in parent["parts"]}
    rows, done = [], set()

    def head(key: str, entry: dict, counts: tuple[int, int, int]) -> str:
        title = f' <span class="t">{html.escape(str(entry["title"]))}</span>' if entry.get("title") else ""
        summary = entry.get("summary")
        text = f'\n<p class="sum">{html.escape(summary)}</p>' if isinstance(summary, str) and summary.strip() else ""
        target = "graph" if small else f"pr-{key}"
        return (f'<span class="tag c-{key}">{html.escape(key)}</span> '
                f'<a class="mo-link" href="#{html.escape(target, quote=True)}"><strong>{html.escape(str(entry.get("name") or key))}</strong></a>{title} '
                + merge_order_meta(strings, entry.get("tip", ""), counts) + text)

    for pr in graph["prs"]:
        key = pr["key"]
        if key not in part_of:
            rows.append(f'<li class="c-{key}">{head(key, pr, stat_counts(pr["nodes"]))}</li>')
            continue
        parent = parents[part_of[key]]
        if parent["key"] in done:
            continue
        done.add(parent["key"])
        members = [prs[k] for k in parent["parts"]]
        sums = [stat_counts(m["nodes"]) for m in members]
        whole = tuple(parent.get(f) for f in ("files", "added", "removed"))
        counts = whole if all(isinstance(v, int) for v in whole) else tuple(sum(c[i] for c in sums) for i in range(3))
        parts = []
        for member, part_counts in zip(members, sums):
            chunk = member.get("chunk") or {}
            span = f"{str(chunk['from'])[:7]}..{str(chunk['to'])[:7]}" if chunk.get("from") and chunk.get("to") else ""
            parts.append(f'<li><button type="button" class="tag c-{member["key"]}" data-gopen="{html.escape(member["key"])}">'
                         f'{chunk.get("index", "")}/{chunk.get("count", "")}</button><span>{html.escape(chunk.get("label", ""))}</span>'
                         + merge_order_meta(strings, span, part_counts) + "</li>")
        rows.append(f'<li class="c-{parent["key"]}">{head(parent["key"], parent, counts)}\n<ol class="parts">\n'
                    + "\n".join(parts) + "\n</ol></li>")
    title = html.escape(strings["mergeOrderTitle"])
    return f'<section id="stack" data-toc="{title}">\n<h2>{title}</h2>\n<ol class="merge-order">\n' + "\n".join(rows) + "\n</ol>\n</section>"


def load_strings(lang: str, overrides: Path | None) -> dict:
    catalog = json.loads(STRINGS_FILE.read_text(encoding="utf-8"))
    base = dict(catalog.get(lang) or catalog["en"])
    if lang not in catalog:
        print(f"warning: no built-in strings for {lang!r}; starting from English, override them with --strings")
    if overrides:
        extra = json.loads(overrides.read_text(encoding="utf-8"))
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = {**base[key], **value}
            else:
                base[key] = value
    return base


def load_previous(path: Path) -> dict:
    """The previous build's {"generation": n, "tips": {KEY: sha}, "files": {KEY: {path: fp}}}, checked for shape."""
    data = json.loads(path.read_text(encoding="utf-8"))
    tips, files, gen = data.get("tips", {}), data.get("files"), data.get("generation", 0)
    ok = isinstance(tips, dict) and all(isinstance(v, str) for v in tips.values()) and isinstance(files, dict) and all(
        isinstance(v, dict) and all(isinstance(fp, str) for fp in v.values()) for v in files.values()) \
        and manifest.generation_ok(gen)
    if not ok:
        raise SystemExit(f'{path}: expected {{"generation": n, "tips": {{KEY: sha}}, "files": {{KEY: {{path: fingerprint}}}}}}')
    return {"generation": gen, "tips": tips, "files": files}


def check_graph(graph: dict, diffs: dict) -> None:
    if not isinstance(graph.get("prs"), list) or not graph["prs"]:
        raise SystemExit("graphs.json needs a non-empty prs list")
    ids: set[str] = set()
    for pr in graph["prs"]:
        if not KEY.fullmatch(str(pr.get("key", ""))):
            raise SystemExit(f"PR key {pr.get('key')!r} must be letters, digits, '_' or '-'")
        for node in pr.get("nodes", []):
            if node["id"] in ids:
                raise SystemExit(f"duplicate node id {node['id']!r}")
            ids.add(node["id"])
            if not isinstance(node.get("order"), int):
                raise SystemExit(f"node {node['id']} needs an integer order")
    for pr in graph["prs"]:
        for edge in pr.get("edges", []):
            if edge["from"] not in ids or edge["to"] not in ids:
                raise SystemExit(f"edge {edge} in PR {pr['key']} points to an unknown node")
    unknown = sorted(set(diffs) - ids)
    if unknown:
        raise SystemExit(f"diffs.json has entries for unknown nodes: {unknown[:10]}")
    problems = chunks.graph_errors(graph)
    if problems:
        raise SystemExit("graphs.json parts: " + "; ".join(problems[:5]))
    problems = tours.problems(graph, diffs)[0]
    if problems:
        raise SystemExit("graphs.json tours: " + "; ".join(problems[:5]))


def screens_block(path: Path, graph: dict) -> str:
    """The `screens-data` JSON block for a screens.json (empty text without one): every entry with its images as data URIs, its
    PR's name, and `stale` when the PR's tip is no longer the one the pair was taken at. SystemExit on a problem."""
    entries, warnings = screens.embed(path)
    for warning in warnings:
        print(f"warning: {warning}")
    tips = screens.tips_of(graph)
    names = {item["key"]: str(item.get("name") or item["key"]) for item in [*graph["prs"], *(graph.get("parents") or [])]}
    unknown = sorted({e["pr"] for e in entries if e["pr"] not in tips})
    if unknown:
        raise SystemExit(f"{path}: pr {unknown} is not a PR of graphs.json ({', '.join(sorted(tips))})")
    stale = set(screens.stale_ids(entries, tips))
    for entry in entries:
        entry["prName"] = names[entry["pr"]]
        entry["stale"] = entry["id"] in stale
    return f'<script type="application/json" id="screens-data">{embed_json({"screens": entries})}</script>\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--diffs", required=True, type=Path)
    parser.add_argument("--narrative", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--strings", type=Path, help="JSON object overriding UI strings key by key")
    parser.add_argument("--storage-key", help="localStorage namespace for read marks and review notes (default: from the title)")
    parser.add_argument("--target", choices=("artifact", "local"), default="artifact")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--previous", type=Path, help="the previous build's tips and fingerprints (written by refresh.py)")
    parser.add_argument("--spot-check", type=int, default=attention.SPOT_DEFAULT, metavar="N",
                        help=f"skim files of the spot-check sample, large changes only (default {attention.SPOT_DEFAULT}, 0 off, at most {attention.SPOT_MAX})")
    parser.add_argument("--screens", type=Path, help="screens.json: before/after screenshots to show in the brief (only when the user asked for them)")
    parser.add_argument("--no-manifest", action="store_true", help="do not record this run in review-map.json")
    args = parser.parse_args()

    if not 0 <= args.spot_check <= attention.SPOT_MAX:
        parser.error(f"--spot-check must be from 0 to {attention.SPOT_MAX}")
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    diffs = json.loads(args.diffs.read_text(encoding="utf-8"))
    check_graph(graph, diffs)
    previous = load_previous(args.previous) if args.previous else None
    narrative = args.narrative.read_text(encoding="utf-8")
    if narrative.count(MARKER) != 1:
        raise SystemExit(f"the narrative must contain exactly one {MARKER} line")
    head, body = (part.strip("\n") for part in narrative.split(MARKER))
    strings = load_strings(args.lang, args.strings)
    size = attention.size_for(graph)
    budget = budget_section(graph, diffs, strings, args.spot_check) if size == "large" else ""
    must, spot = (len(re.findall(r"<li>", "".join(re.findall(rf'<div class="b-group" data-b="{name}">.*?</div>', budget, re.DOTALL)))) for name in ("must", "spot"))
    head = with_progress(head, progress_html(strings, len(re.findall(r'<li\b[^>]*\bid="risk-[^"]*"', head)),
                                             len(re.findall(r'<li\b[^>]*\bid="dec-[^"]*"', head + body)), must, spot))
    head = "\n\n".join(part for part in (head, budget, merge_order(graph, strings, size == "small")) if part)

    prs = []
    pr_css = []
    for index, pr in enumerate(graph["prs"]):
        color = pr.get("color") or f"var(--pal-{index % 8 + 1})"
        if not isinstance(color, str) or not COLOR.fullmatch(color):
            raise SystemExit(f"PR {pr['key']}: color {color!r} must be var(--pal-1..8), a hex colour, or a colour name")
        prs.append({"key": pr["key"], "name": pr.get("name", pr["key"]), "title": pr.get("title", ""),
                    "repo": pr.get("repo", ""), "base": pr.get("base", ""), "tip": pr.get("tip", ""), "color": color})
        pr_css.append(f".c-{pr['key']}{{--c:{color}}}")
    first = {pr["key"]: prs[i]["color"] for i, pr in enumerate(graph["prs"])}
    for parent in graph.get("parents") or []:
        pr_css.append(f".c-{parent['key']}{{--c:{first[parent['parts'][0]]}}}")
    storage_key = args.storage_key or re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")[:60] or "review"
    config = {"lang": args.lang, "title": args.title, "storageKey": storage_key, "target": args.target, "strings": strings, "prs": prs}
    if previous is not None:
        config["previous"] = previous
    here = args.graph.resolve().parent
    last = None if args.no_manifest else manifest.read(here).get("assemble")
    before = manifest.history([args.out, manifest.resolve(here, last.get("out")) if isinstance(last, dict) and last.get("out") else None])
    floor = previous["generation"] + 1 if previous is not None else 0
    if before is None:
        generation = floor
    elif before[1] == manifest.digest(graph, diffs):
        generation = before[0]  # the same content keeps its number, with or without --previous
    else:
        generation = max(before[0] + 1, floor)
    config["generation"] = min(generation, manifest.MAX_GENERATION)

    toc = [*toc_entries(head), ("graph", strings["graphToc"]), *toc_entries(body)]
    toc_html = "\n".join(f'    <li><a href="#{html.escape(i)}">{t}</a></li>' for i, t in toc)
    hint = html.escape(strings["hint"])
    hint = hint.replace("{dep}", f'<span class="k-dep">{html.escape(strings["hintDep"])}</span>')
    hint = hint.replace("{use}", f'<span class="k-use">{html.escape(strings["hintUse"])}</span>')
    lang_attr = html.escape(args.lang, quote=True)
    if args.target == "local":
        doc_start = f'<!doctype html>\n<html lang="{lang_attr}">\n<meta charset="utf-8">\n'
        head_meta = '<meta name="viewport" content="width=device-width, initial-scale=1">'
        doc_end = (MERMAID_LOCAL if 'class="mermaid"' in narrative else "") + "</html>\n"
    else:
        doc_start = ""
        head_meta = '<meta name="claude:viewport-fit-sides" content="cover">'
        doc_end = ""

    values = {
        "DOC_START": doc_start,
        "HEAD_META": head_meta,
        "DOC_END": doc_end,
        "TITLE": html.escape(args.title),
        "PR_CSS": "\n".join(pr_css),
        "TOC": toc_html,
        "HINT": hint,
        "NARRATIVE_HEAD": head,
        "NARRATIVE_BODY": body,
        "CONFIG_JSON": embed_json(config),
        "GRAPH_JSON": embed_json(graph),
        "DIFF_JSON": embed_json(diffs),
        "SCREENS_BLOCK": screens_block(args.screens, graph) if args.screens else "",
    }

    def fill(match: re.Match) -> str:
        name = match.group(1)
        if name.startswith("S:"):
            value = strings.get(name[2:])
            if not isinstance(value, str):
                raise SystemExit(f"missing UI string {name[2:]!r}")
            return html.escape(value)
        if name not in values:
            raise SystemExit(f"template placeholder {{{{{name}}}}} has no value")
        return values[name]

    template = args.template.read_text(encoding="utf-8")
    if args.screens and "{{SCREENS_BLOCK}}" not in template:
        raise SystemExit(f"--screens needs a template with a {{{{SCREENS_BLOCK}}}} placeholder; {args.template} has none")
    page = PLACEHOLDER.sub(fill, template)
    args.out.write_text(page, encoding="utf-8")
    if not args.no_manifest:
        manifest.record(here, "assemble", {
            "graph": manifest.stored(here, args.graph), "diffs": manifest.stored(here, args.diffs),
            "narrative": manifest.stored(here, args.narrative), "title": args.title, "lang": args.lang,
            "strings": manifest.stored(here, args.strings), "storageKey": storage_key, "target": args.target,
            "spotCheck": args.spot_check, "screens": manifest.stored(here, args.screens),
            "template": None if args.template.resolve() == DEFAULT_TEMPLATE else manifest.stored(here, args.template),
            "out": manifest.stored(here, args.out), "previous": manifest.stored(here, args.previous),
        })
    print(f"wrote {args.out} ({len(page.encode('utf-8')) // 1024} KB, target {args.target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
