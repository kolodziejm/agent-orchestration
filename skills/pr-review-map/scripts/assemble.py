#!/usr/bin/env python3
"""Assemble the review-map page: viewer template + graph and diff data + authored narrative.

Usage:
  python3 assemble.py --graph graphs.json --diffs diffs.json --narrative narrative.html \\
      --title "Review: …" --lang pl --out report.html \\
      [--strings overrides.json] [--storage-key my-review] [--target artifact|local] \\
      [--template ../assets/viewer.html] [--previous previous.json]

The narrative is HTML for <main>, split by one line `<!-- review-map:graph -->`:
everything before it (header, PR stack) renders above the reading graph, everything
after it (architecture, rules, per-PR sections, risks, verification, footer) below.
The table of contents is built from each `<section id="…">` and its first <h2>
(or its `data-toc` attribute).

--target artifact (default) emits the fragment the Claude Artifact page contract
expects: it starts with <title>, and diagrams in <pre class="mermaid"> are rendered
by the host. --target local emits a complete document and loads mermaid from cdnjs.

UI strings come from assets/strings.json for --lang, overridden key by key by
--strings. JSON data is embedded in <script type="application/json"> blocks with
`</` written as `<\\/` and `<!--` as `<\\u0021--`, both valid JSON escapes that keep
the HTML parser out of the data.

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
The arguments, with the storage key as resolved, go in the `assemble` section of
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
import chunks  # noqa: E402
import manifest  # noqa: E402
import tours  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "viewer.html"
STRINGS_FILE = HERE.parent / "assets" / "strings.json"
MARKER = "<!-- review-map:graph -->"
PLACEHOLDER = re.compile(r"\{\{(S:[A-Za-z0-9_]+|[A-Z_]+)\}\}")
KEY = re.compile(r"^[A-Za-z0-9_-]+$")
COLOR = re.compile(r"var\(--pal-[1-8]\)|#[0-9A-Fa-f]{3,8}|[A-Za-z]{3,20}")
MERMAID_LOCAL = """<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.15.0/mermaid.min.js"></script>
<script>
(function(){
  if(!window.mermaid)return;
  var t=document.documentElement.getAttribute('data-theme');
  var dark=t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches);
  mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:dark?'dark':'default'});
  mermaid.run({querySelector:'pre.mermaid'});
})();
</script>
"""


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
    parser.add_argument("--no-manifest", action="store_true", help="do not record this run in review-map.json")
    args = parser.parse_args()

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    diffs = json.loads(args.diffs.read_text(encoding="utf-8"))
    check_graph(graph, diffs)
    previous = load_previous(args.previous) if args.previous else None
    narrative = args.narrative.read_text(encoding="utf-8")
    if narrative.count(MARKER) != 1:
        raise SystemExit(f"the narrative must contain exactly one {MARKER} line")
    head, body = (part.strip("\n") for part in narrative.split(MARKER))
    strings = load_strings(args.lang, args.strings)

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
    config = {"lang": args.lang, "title": args.title, "storageKey": storage_key, "strings": strings, "prs": prs}
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
    page = PLACEHOLDER.sub(fill, template)
    args.out.write_text(page, encoding="utf-8")
    if not args.no_manifest:
        manifest.record(here, "assemble", {
            "graph": manifest.stored(here, args.graph), "diffs": manifest.stored(here, args.diffs),
            "narrative": manifest.stored(here, args.narrative), "title": args.title, "lang": args.lang,
            "strings": manifest.stored(here, args.strings), "storageKey": storage_key, "target": args.target,
            "template": None if args.template.resolve() == DEFAULT_TEMPLATE else manifest.stored(here, args.template),
            "out": manifest.stored(here, args.out), "previous": manifest.stored(here, args.previous),
        })
    print(f"wrote {args.out} ({len(page.encode('utf-8')) // 1024} KB, target {args.target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
