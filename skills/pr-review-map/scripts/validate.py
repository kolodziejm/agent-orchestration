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
    diff entries only for known nodes, string fingerprints, a whole-PR diff (`whole`)
    with a string diff; a node without a diff is a warning
  * parts of a PR split by its commits (`parents`, `chunk`): contiguous, numbered
    1..n, each starting where the one before ends, keys ending in a letter
  * the previous version's data (review-config "previous", from refresh.py), when
    present: {"generation": n, "tips": {KEY: sha}, "files": {KEY: {path: fingerprint}}};
    review-config "generation", when present, an integer from 0 to 2**31
Python 3 standard library plus node on PATH (skip node only where it is missing).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True  # importing chunks.py must not leave a __pycache__ in the skill
import chunks  # noqa: E402

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

    graph = data.get("graph-data")
    diffs = data.get("diff-data")
    if isinstance(graph, dict) and isinstance(graph.get("prs"), list):
        nodes = {}
        for pr in graph["prs"]:
            for node in pr.get("nodes", []):
                if node.get("id") in nodes:
                    errors.append(f"duplicate node id {node.get('id')!r}")
                nodes[node.get("id")] = (pr.get("key"), node)
                if not isinstance(node.get("order"), int):
                    errors.append(f"node {node.get('id')} has no integer order")
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
    else:
        warnings.append("no graph-data block found; graph checks skipped")

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
    if size > 3 * 1024 * 1024:
        warnings.append("page is over 3 MB; consider --max-lines in gen_diffs.py or collapsing more files into groups")
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
