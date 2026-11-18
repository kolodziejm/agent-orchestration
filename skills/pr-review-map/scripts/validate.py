#!/usr/bin/env python3
"""Validate an assembled review-map page before publishing it.

Usage:
  python3 validate.py report.html [--skip-node] [--allow-host cdnjs.cloudflare.com]

Checks, each an error unless noted:
  * a non-empty <title>
  * every inline classic <script> compiles in node (`new Function(code)`) and every
    <script type="application/json"> block passes JSON.parse in node and json.loads
  * no script body contains `<!--` or `</script` (the HTML parser would end or
    swallow the block)
  * balanced div, section, details, table, main, nav, ul, ol, pre outside scripts,
    styles, and comments
  * external <script src>/<link href> hosts are on the allowlist (default cdnjs)
  * no unfilled `{{…}}` template placeholder
  * graph/diff consistency: unique node ids, edges to known nodes, integer order,
    a non-empty `conflict` list where given, of {"sha", "kind": merged|picked, "lines": n >= 0}
    entries (or bare SHAs, as older builds wrote), diff entries only for known nodes, string fingerprints,
    a whole-PR diff (`whole`) with a string diff; a node without a diff is a warning
  * a PR's (or split PR's) `summary`, when present, non-empty text
  * parts of a PR split by its commits (`parents`, `chunk`): contiguous, numbered
    1..n, each starting where the one before ends, keys ending in a letter
  * areas (`clusters` per PR, node `cluster`): well-formed, unique ids, and every node's cluster
    listed by its PR; fewer than 4 or more than 15 areas, an area with no node of its
    own (only tests or hubs), or a PR above 40 core nodes without areas is a warning
  * tours (graph "tours", scripts/tours.py): at most 8 of 3 to 15 steps with unique
    ids, each step's node known, its path a file of that node in the diff data, its
    side new or old, and its lines 1 <= a <= b or none; lines outside every hunk on
    their side are a warning (the viewer opens the whole file), as is a narrative
    data-tour button that names no tour
  * `size` (small, medium, or large) and each node's `attention` (mechanical, pattern, novel, or risky) and `focus`
    ([{"start", "end", "why", "side"?}], 1 <= start <= end, side new or old) within their values; a focus range outside
    every hunk of the node's diff is a warning (scripts/attention.py)
  * `spotCheck` (graph, the spot-check override: [{"pr", "id"}]): each entry names a changed node of that PR whose
    attention is `pattern` (scripts/attention.py)
  * the page's `<section id="brief">` (warning when missing: a page from before the brief still passes)
  * the optional `screens-data` block (assemble.py --screens): {"screens": [...]} entries with an id, a title, a PR key of the
    graph, and before/after each null or an image data URI of type image/png, image/jpeg, or image/webp whose bytes begin with
    that format's magic number (not both null); a pair marked `stale` (taken at a tip the PR has left) is a warning
  * the previous version's data (review-config "previous", from refresh.py), when
    present: {"generation": n, "tips": {KEY: sha}, "files": {KEY: {path: fingerprint}}};
    review-config "generation", when present, an integer from 0 to 2**31
Python 3 standard library plus node on PATH (skip node only where it is missing).
"""

from __future__ import annotations

import argparse
import json
import re
import base64
import binascii
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True  # importing chunks.py must not leave a __pycache__ in the skill
import attention  # noqa: E402
import chunks  # noqa: E402
import manifest  # noqa: E402
import screens  # noqa: E402
import tours  # noqa: E402

SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
BALANCED = ("div", "section", "details", "table", "main", "nav", "ul", "ol", "pre")
NODE_CHECK = r"""
const fs = require('fs');
const blocks = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const errors = [];
blocks.forEach((b, i) => {
  try {
    if (b.kind === 'json') JSON.parse(b.code); else new Function(b.code);
  } catch (e) {
    errors.push(`script #${i} (${b.kind}${b.id ? ' #' + b.id : ''}): ${e.message}`);
  }
});
process.stdout.write(JSON.stringify(errors));
"""


def reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant {name}")


LATE = {"docs", "config", "i18n"}
OVERVIEW_CORE = 40  # build_graph.py and the viewer: above this many core nodes the map opens on its overview of areas
SHORT_SHA = re.compile(r"[0-9a-f]{7,40}")
RESOLUTIONS = ("merged", "picked")  # build_graph.py: how a merge resolved a node's files


def resolution_ok(item) -> bool:
    """A `conflict` entry: {"sha", "kind": merged|picked, "lines": n >= 0}, or a bare SHA (builds before kinds)."""
    if isinstance(item, str):
        return bool(SHORT_SHA.fullmatch(item))
    return (isinstance(item, dict) and set(item) == {"sha", "kind", "lines"} and isinstance(item["sha"], str)
            and bool(SHORT_SHA.fullmatch(item["sha"])) and item["kind"] in RESOLUTIONS
            and isinstance(item["lines"], int) and not isinstance(item["lines"], bool) and item["lines"] >= 0)


def cluster_problems(pr: dict) -> tuple[list[str], list[str]]:
    """Errors and warnings about one PR's areas: its `clusters` list and its nodes' `cluster`."""
    errors: list[str] = []
    warnings: list[str] = []
    key, listed = pr.get("key"), pr.get("clusters")
    ids: dict[str, int] = {}
    if listed is not None:
        if not isinstance(listed, list):
            return [f'PR {key}: "clusters" must be a list of {{"id", "label", "order"}}'], []
        for item in listed:
            if not (isinstance(item, dict) and isinstance(item.get("id"), str) and manifest.CLUSTER.fullmatch(item["id"])
                    and isinstance(item.get("label"), str) and isinstance(item.get("order"), int) and not isinstance(item.get("order"), bool)):
                errors.append(f"PR {key}: cluster {item!r} needs an id (letters, digits, '_', '.', '-'), a label, and an integer order")
            elif item["id"] in ids:
                errors.append(f"PR {key}: cluster id {item['id']!r} is listed twice")
            else:
                ids[item["id"]] = 0
    nodes = [node for node in pr.get("nodes", []) if isinstance(node, dict)]
    core = [node for node in nodes if node.get("layer") != "test" and node.get("layer") not in LATE]
    for node in nodes:
        if "cluster" not in node:
            continue
        if not isinstance(node["cluster"], str) or node["cluster"] not in ids:
            errors.append(f"node {node.get('id')} in PR {key}: unknown cluster {node['cluster']!r}")
        elif node.get("layer") != "test" and not node.get("hub"):
            ids[node["cluster"]] += 1  # a docs/config/i18n node with an area is in it (it still reads last)
    if ids and not 4 <= len(ids) <= 15:
        warnings.append(f"PR {key}: {len(ids)} clusters; 4 to 15 (8 to 12 reads best) keep the map overview readable")
    empty = [cid for cid, n in ids.items() if not n]
    if empty:
        warnings.append(f"PR {key}: clusters with no file of their own (only tests or hubs): {empty}")
    if not ids and len(core) > OVERVIEW_CORE:
        warnings.append(f"PR {key}: {len(core)} core nodes and no clusters; the map overview groups them by folder")
    return errors, warnings


DATA_URI = re.compile(r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/]*={0,2})")
MIME_KIND = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}


def screens_problems(block, graph) -> tuple[list[str], list[str]]:
    """Errors and warnings about the `screens-data` block: its shape, each image's MIME type (png, jpeg, or webp only; an SVG
    can carry script) and magic bytes, the PR each pair names, and the pairs marked stale."""
    errors: list[str] = []
    warnings: list[str] = []
    items = block.get("screens") if isinstance(block, dict) else None
    if not isinstance(items, list) or not items:
        return ['screens-data must be {"screens": [one or more entries]}'], []
    keys = {pr.get("key") for pr in graph["prs"] if isinstance(pr, dict)} if isinstance(graph, dict) and isinstance(graph.get("prs"), list) else None
    ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"screens: entry #{index + 1} is not an object")
            continue
        name = item.get("id") if isinstance(item.get("id"), str) else f"#{index + 1}"
        if name in ids:
            errors.append(f"screens: id {name!r} is used twice")
        ids.add(name)
        if not (isinstance(item.get("title"), str) and item["title"].strip()):
            errors.append(f"screens: {name} has no title")
        if not isinstance(item.get("pr"), str) or (keys is not None and item["pr"] not in keys and not any(
                p.get("key") == item["pr"] for p in graph.get("parents") or [] if isinstance(p, dict))):
            errors.append(f"screens: {name} names PR {item.get('pr')!r}, which the map does not have")
        for side in ("before", "after"):
            value = item.get(side)
            if value is None:
                continue
            found = DATA_URI.fullmatch(value) if isinstance(value, str) else None
            if not found:
                errors.append(f"screens: {name}.{side} is not an image data URI (data:image/png, image/jpeg, or image/webp; base64)")
            elif found.group(1) not in MIME_KIND:
                errors.append(f"screens: {name}.{side} has MIME type {found.group(1)}; only image/png, image/jpeg, and image/webp are allowed")
            else:
                try:
                    kind = screens.sniff(base64.b64decode(found.group(2), validate=True))
                except (binascii.Error, ValueError):
                    kind = None
                if kind != MIME_KIND[found.group(1)]:
                    errors.append(f"screens: {name}.{side} claims {found.group(1)} but its bytes are not that format")
        if "before" in item and "after" in item and item["before"] is None and item["after"] is None:
            errors.append(f"screens: {name} has neither a before nor an after image")
        if item.get("stale") is True:
            tip = str(item.get("tip") or "")[:7]
            warnings.append(f"screens: {name} was taken at {tip or 'an earlier tip'}, but PR {item.get('pr')} has moved on; retake it (the page says its code changed since)")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page", type=Path)
    parser.add_argument("--skip-node", action="store_true", help="skip the node compile check (only if node is unavailable)")
    parser.add_argument("--allow-host", action="append", default=None)
    args = parser.parse_args()
    hosts = set(args.allow_host or ["cdnjs.cloudflare.com"])

    page = args.page.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    title = re.search(r"<title>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
    if not title or not title.group(1).strip():
        errors.append("missing or empty <title>")

    blocks = []
    data: dict[str, object] = {}
    for match in SCRIPT.finditer(page):
        attrs, code = match.group(1), match.group(2)
        src = re.search(r'\bsrc="([^"]+)"', attrs)
        ident = re.search(r'\bid="([^"]+)"', attrs)
        ident = ident.group(1) if ident else ""
        if src:
            host = urlparse(src.group(1)).hostname
            if host and host not in hosts:
                errors.append(f"script from a host outside the allowlist: {src.group(1)}")
            if code.strip():
                errors.append(f"script with src also has inline code: {src.group(1)}")
            continue
        if "<!--" in code or re.search(r"</script", code, re.IGNORECASE):
            errors.append(f"script {ident or '(inline)'} contains '<!--' or '</script'; escape it")
        kind = "json" if re.search(r'type="application/(ld\+)?json"', attrs) else "classic"
        if kind == "classic" and re.search(r'type="(?!text/javascript|application/javascript|module)[^"]+"', attrs):
            continue
        if kind == "classic" and 'type="module"' in attrs:
            warnings.append(f"module script {ident or '(inline)'} is not compile-checked")
            continue
        if kind == "json":
            try:
                data[ident] = json.loads(code, parse_constant=reject_constant)
            except ValueError as error:
                errors.append(f"JSON block #{ident or '?'} does not parse: {error}")
        blocks.append({"kind": kind, "id": ident, "code": code})

    for match in re.finditer(r'<link\b[^>]*\bhref="(https?://[^"]+)"', page, re.IGNORECASE):
        host = urlparse(match.group(1)).hostname
        if host and host not in hosts:
            errors.append(f"stylesheet or link from a host outside the allowlist: {match.group(1)}")

    if args.skip_node:
        warnings.append("node compile check skipped")
    elif not shutil.which("node"):
        errors.append("node is not on PATH; install it or pass --skip-node knowingly")
    else:
        with tempfile.TemporaryDirectory() as directory:
            blocks_file = Path(directory) / "blocks.json"
            check_file = Path(directory) / "check.js"
            blocks_file.write_text(json.dumps(blocks), encoding="utf-8")
            check_file.write_text(NODE_CHECK, encoding="utf-8")
            result = subprocess.run(["node", str(check_file), str(blocks_file)], capture_output=True, text=True)
            if result.returncode != 0:
                errors.append(f"node check failed to run: {result.stderr.strip()[:400]}")
            else:
                errors.extend(json.loads(result.stdout or "[]"))

    markup = re.sub(r"<!--.*?-->", "", page, flags=re.DOTALL)
    markup = SCRIPT.sub("", markup)
    markup = re.sub(r"<style\b.*?</style\s*>", "", markup, flags=re.IGNORECASE | re.DOTALL)
    for tag in BALANCED:
        opened = len(re.findall(rf"<{tag}(?=[\s>])", markup, re.IGNORECASE))
        closed = len(re.findall(rf"</{tag}\s*>", markup, re.IGNORECASE))
        if opened != closed:
            errors.append(f"unbalanced <{tag}>: {opened} opened, {closed} closed")
    leftover = sorted(set(re.findall(r"\{\{(?:S:[A-Za-z0-9_]+|[A-Z_]+)\}\}", markup)))
    if leftover:
        errors.append(f"unfilled template placeholders: {leftover}")

    if not re.search(r'<section\b[^>]*\bid="brief"', markup):
        warnings.append('no <section id="brief">: the page opens without what changes for users, the contracts, the ranked risks, '
                        "the untested gaps, and the decisions (references/narrative.md)")
    graph = data.get("graph-data")
    diffs = data.get("diff-data")
    if isinstance(graph, dict) and isinstance(graph.get("prs"), list):
        nodes = {}
        for pr in [*graph["prs"], *(graph.get("parents") or [])]:
            if "summary" in pr and not (isinstance(pr["summary"], str) and pr["summary"].strip()):
                errors.append(f"PR {pr.get('key')}: summary must be non-empty text (it is shown under the PR in the merge order)")
        for pr in graph["prs"]:
            for node in pr.get("nodes", []):
                if node.get("id") in nodes:
                    errors.append(f"duplicate node id {node.get('id')!r}")
                nodes[node.get("id")] = (pr.get("key"), node)
                if not isinstance(node.get("order"), int):
                    errors.append(f"node {node.get('id')} has no integer order")
                shas = node.get("conflict")
                if "conflict" in node and not (isinstance(shas, list) and shas and all(resolution_ok(item) for item in shas)):
                    errors.append(f"node {node.get('id')}: conflict must be a non-empty list of commit SHAs or of "
                                  '{"sha", "kind": "merged" or "picked", "lines": n >= 0} entries')
        for pr in graph["prs"]:
            for edge in pr.get("edges", []):
                if edge.get("from") not in nodes or edge.get("to") not in nodes:
                    errors.append(f"edge {edge} in PR {pr.get('key')} points to an unknown node")
                elif nodes[edge["from"]][0] != pr.get("key"):
                    errors.append(f"edge {edge} is listed under PR {pr.get('key')} but starts in another PR")
        if isinstance(diffs, dict):
            for key in diffs:
                if key not in nodes:
                    errors.append(f"diff entry for unknown node {key!r}")
                for entry in diffs[key] if isinstance(diffs[key], list) else []:
                    if "fp" in entry and not isinstance(entry["fp"], str):
                        errors.append(f"diff entry {key}:{entry.get('path')} has a non-string fingerprint")
                    if "whole" in entry and not (isinstance(entry["whole"], dict) and isinstance(entry["whole"].get("diff"), str)):
                        errors.append(f"diff entry {key}:{entry.get('path')} has a whole-PR diff without a string diff")
            without = [i for i, (_k, n) in nodes.items() if i not in diffs and not n.get("unchanged")]
            if without:
                warnings.append(f"nodes without a diff: {without[:20]}")
        errors.extend(f"parts: {problem}" for problem in chunks.graph_errors(graph))
        for pr in graph["prs"]:
            found, notes = cluster_problems(pr) if isinstance(pr, dict) else ([], [])
            errors.extend(found)
            warnings.extend(notes)
        found, notes = attention.problems(graph, diffs)
        errors.extend(found)
        warnings.extend(notes)
        found, notes = tours.problems(graph, diffs, re.findall(r'\bdata-tour="([^"]*)"', markup))
        errors.extend(f"tours: {problem}" for problem in found)
        warnings.extend(f"tours: {problem}" for problem in notes)
    else:
        warnings.append("no graph-data block found; graph checks skipped")

    if "screens-data" in data:
        found, notes = screens_problems(data["screens-data"], graph)
        errors.extend(found)
        warnings.extend(notes)

    config = data.get("review-config")
    previous = config.get("previous") if isinstance(config, dict) else None
    if previous is not None:
        files = previous.get("files") if isinstance(previous, dict) else None
        tips = previous.get("tips", {}) if isinstance(previous, dict) else None
        gen = previous.get("generation", 0) if isinstance(previous, dict) else None
        if not (isinstance(files, dict) and all(isinstance(v, dict) and all(isinstance(fp, str) for fp in v.values()) for v in files.values())
                and isinstance(tips, dict) and all(isinstance(v, str) for v in tips.values())
                and isinstance(gen, int) and not isinstance(gen, bool) and 0 <= gen <= 2**31):
            errors.append('review-config "previous" must be {"generation": n, "tips": {KEY: sha}, "files": {KEY: {path: fingerprint}}}')
    gen = config.get("generation", 0) if isinstance(config, dict) else 0
    if not isinstance(gen, int) or isinstance(gen, bool) or not 0 <= gen <= 2**31:
        errors.append('review-config "generation" must be an integer from 0 to 2**31')

    size = len(page.encode("utf-8"))
    print(f"{args.page}: {size // 1024} KB, {len(blocks)} inline scripts checked")
    images = sum(len(m.group(0)) for m in re.finditer(r'<script type="application/json" id="screens-data">.*?</script>', page, re.DOTALL))
    if size - images > 3 * 1024 * 1024:
        warnings.append("page is over 3 MB; consider --max-lines in gen_diffs.py or collapsing more files into groups")
    if size > 15 * 1024 * 1024:
        errors.append(f"page is {size // 1024 // 1024} MB; the artifact limit is 16 MB, so drop screenshots or save them smaller")
    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}")
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
