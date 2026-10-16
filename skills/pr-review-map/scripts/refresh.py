#!/usr/bin/env python3
"""Rebuild a review map after its branches moved: build_graph -> gen_diffs -> assemble -> validate.

Usage:
  python3 refresh.py SCRATCH_DIR [--assemble-only]

SCRATCH_DIR holds review-map.json, which build_graph.py, gen_diffs.py, and
assemble.py write beside graphs.json with the inputs of their last run (see
scripts/manifest.py). refresh.py replays those runs with the same inputs: PR keys,
repositories, ranges, names, titles, repository labels, aliases, groups, overlay,
diff context and line cap, narrative, title, language, strings, target, output, and
the storage key, so read marks and review notes carry over. Branch names in the
ranges resolve to their current tips: fetch first. The repositories are only read
(rev-parse, merge-base, diff, show, ls-tree). It prints each PR's old -> new tip.

Before rebuilding it keeps the current build's tips and file fingerprints in
previous.json and passes them to assemble.py --previous: the page then shows what
changed since that version (new, changed, removed files), and the viewer clears read
marks of files whose change differs from the one that was read. A re-run that
changes nothing keeps the comparison from the last time something did.

The narrative is never rewritten. When a tip moved, refresh.py warns that the
narrative's claims may be outdated, lists the lines of narrative.html that still show
a PR's old tip, and prints each PR's new file count and +/-. After editing the
narrative, `--assemble-only` assembles and validates again without rebuilding.

refresh.py trusts the manifest only so far: PR keys, repositories, and ranges must
pass manifest.check_pr (no leading "-", white space, or control characters), every
other value reaches the scripts as `--option=value` or is checked the same way, and
the files it writes (graphs.json, diffs.json, the page, previous.json) must lie in
SCRATCH_DIR unless --allow-outside is given. It still reads the inputs the manifest
names (overlay, narrative, strings, template) wherever they are, so run it only on a
manifest you or your own scripts wrote. Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing sibling scripts must not leave a __pycache__ in the skill
import manifest  # noqa: E402
from gen_diffs import fingerprint  # noqa: E402

HERE = Path(__file__).resolve().parent
PREVIOUS = "previous.json"
FIXED_BASE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def git(repo: str, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else None


def tip_of(rng: str) -> str:
    return (rng.split("...", 1)[1] if "..." in rng else rng.split("..", 1)[1]) or "HEAD"


def resolve_tip(repo: str, rng: str) -> str | None:
    return git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{tip_of(rng)}^{{commit}}")


def step(script: str, args: list[str], names: dict[str, str] | None = None) -> str:
    """Run one pipeline script, echo its output indented (side-file paths shown by their final `names`), and stop on failure."""
    print(f"$ {script}")
    result = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        for side, final in (names or {}).items():
            line = line.replace(side, final)
        print(f"  {line}")
    if result.returncode != 0:
        raise SystemExit(f"{script} failed (exit {result.returncode}); the previous page is left as it was" if script != "validate.py"
                         else "validate.py failed; fix the page before publishing it")
    return result.stdout


def file_fingerprints(graph: dict, diffs: dict) -> dict[str, dict[str, str]]:
    """{PR key: {path: fp}} for every changed file; an entry from before `fp` existed is fingerprinted from its body."""
    owner = {node["id"]: pr["key"] for pr in graph.get("prs", []) for node in pr.get("nodes", [])}
    out: dict[str, dict[str, str]] = {pr["key"]: {} for pr in graph.get("prs", [])}
    for node_id, entries in diffs.items():
        key = owner.get(node_id)
        if key is None:
            continue
        for entry in entries:
            out[key][entry["path"]] = entry.get("fp") or fingerprint(entry.get("diff", ""))
    return out


def load_json(path: Path | None):
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def counts(graph: dict) -> dict[str, tuple[int, int, int]]:
    """{PR key: (files, added, removed)} over the changed files, as a stack card shows them."""
    out = {}
    for pr in graph.get("prs", []):
        nodes = [n for n in pr.get("nodes", []) if not n.get("unchanged")]
        out[pr["key"]] = (sum(len(n.get("files") or [n["path"]]) for n in nodes),
                          sum(n.get("added", 0) for n in nodes), sum(n.get("removed", 0) for n in nodes))
    return out


def summary(before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]) -> tuple[int, int, int]:
    new = changed = removed = 0
    for key in sorted(set(before) | set(after)):
        old, cur = before.get(key, {}), after.get(key, {})
        new += sum(1 for p in cur if p not in old)
        changed += sum(1 for p in cur if p in old and old[p] != cur[p])
        removed += sum(1 for p in old if p not in cur)
    return new, changed, removed


def assemble_args(here: Path, section: dict, previous: Path | None) -> list[str]:
    """assemble.py's arguments, each as `--option=value` so no value can pass for an option."""
    values = {"graph": manifest.resolve(here, section["graph"]), "diffs": manifest.resolve(here, section["diffs"]),
              "narrative": manifest.resolve(here, section["narrative"]), "title": text(section, "title"),
              "lang": text(section, "lang", "en"), "target": text(section, "target", "artifact"),
              "storage-key": text(section, "storageKey"), "out": manifest.resolve(here, section["out"]),
              "strings": manifest.resolve(here, section.get("strings")), "template": manifest.resolve(here, section.get("template")),
              "previous": previous}
    return [f"--{name}={value}" for name, value in values.items() if value is not None]


def text(section: dict, name: str, default: str | None = None) -> str:
    """A manifest string, refused when it holds a control character (it goes on a command line)."""
    value = section.get(name, default)
    if not isinstance(value, str) or re.search(r"[\x00-\x1f\x7f]", value):
        raise SystemExit(f"{manifest.NAME}: {name} must be a string without control characters, not {value!r}")
    return value


def pair_args(flag: str, pairs) -> list[str]:
    """`flag KEY VALUE` for each manifest pair; a VALUE starting with "-" would be read as an option, so it is refused."""
    out = []
    for item in pairs or []:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(v, str) for v in item)) \
                or not manifest.KEY.fullmatch(item[0]) or item[1].startswith("-") or re.search(r"[\x00-\x1f\x7f]", item[1]):
            raise SystemExit(f"{manifest.NAME}: {flag} entry {item!r} must be [KEY, value] with a value that does not start with '-'")
        out += [flag, *item]
    return out


def generation(path: Path | None) -> int:
    """The generation of the page built with the previous-version file `path`: one after that file's, 0 without one."""
    data = load_json(path) if path is not None else None
    return int(data.get("generation", 0)) + 1 if isinstance(data, dict) else 0


def narrative_warnings(narrative: Path | None, moved: list[tuple[str, str, str]], before: dict, after: dict) -> list[str]:
    """Where narrative.html still shows a moved PR's old tip, and each moved PR's new counts."""
    text = narrative.read_text(encoding="utf-8") if narrative and narrative.is_file() else ""
    lines = text.splitlines()
    out = []
    for key, old, new in moved:
        hits = []
        if old:
            for number, line in enumerate(lines, 1):
                for match in re.finditer(r"\b[0-9a-f]{7,40}\b", line):
                    if old.startswith(match.group(0)):
                        hits.append(f"{narrative.name}:{number}")
        where = f"still shows its old tip {old[:7]} at {', '.join(hits)}" if hits else (
            f"does not show its new tip {new[:7]}" if new[:7] not in text else "")
        files, added, removed = after.get(key, (0, 0, 0))
        was = before.get(key)
        stats = f"now {files} files +{added}/−{removed}" + (f" (was {was[0]} files +{was[1]}/−{was[2]})" if was else "")
        out.append(f"PR {key}: tip {old[:7] or '?'} -> {new[:7]}; {stats}" + (f"; the narrative {where}" if where else ""))
    return out


def previous_file(here: Path, asm: dict) -> Path | None:
    """The comparison to embed: refresh.py's previous.json, else the one assemble.py was last given."""
    for path in (here / PREVIOUS, manifest.resolve(here, asm.get("previous"))):
        if path is not None and path.is_file():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="the scratch directory with review-map.json")
    parser.add_argument("--assemble-only", action="store_true", help="assemble and validate again without rebuilding the data")
    parser.add_argument("--allow-outside", action="store_true",
                        help="let the manifest's outputs (graph, diffs, page) lie outside the directory")
    args = parser.parse_args()
    here = args.directory.resolve()
    data = manifest.read(here)
    if not data:
        raise SystemExit(f"no {manifest.NAME} in {here}; build the map once with build_graph.py, gen_diffs.py, and assemble.py")
    sections = ("assemble",) if args.assemble_only else ("build_graph", "gen_diffs", "assemble")
    missing = [name for name in sections if not isinstance(data.get(name), dict)]
    if missing:
        raise SystemExit(f"{manifest.NAME} has no record of {', '.join(missing)}; run those scripts once with their outputs in {here}")
    build, gen, asm = data.get("build_graph", {}), data.get("gen_diffs", {}), data["assemble"]
    out = manifest.resolve(here, asm["out"])
    writes = [out] + ([] if args.assemble_only else [manifest.resolve(here, build["out"]), manifest.resolve(here, gen["out"])])
    outside = [str(path) for path in writes if not manifest.inside(here, path)]
    if outside and not args.allow_outside:
        raise SystemExit(f"{manifest.NAME} would write outside {here}: {', '.join(outside)}; "
                         "pass --allow-outside if you wrote that manifest yourself")
    for pr in ([] if args.assemble_only else build["prs"] + gen["prs"]):
        manifest.check_pr(pr["key"], pr["repo"], pr["range"])
    if args.assemble_only:
        step("assemble.py", assemble_args(here, asm, previous_file(here, asm)))
        step("validate.py", ["--", str(out)])
        return 0

    graph_path, diffs_path = manifest.resolve(here, build["out"]), manifest.resolve(here, gen["out"])
    if (manifest.resolve(here, gen["graph"]).resolve() != graph_path.resolve()
            or manifest.resolve(here, asm["graph"]).resolve() != graph_path.resolve()
            or manifest.resolve(here, asm["diffs"]).resolve() != diffs_path.resolve()):
        raise SystemExit(f"{manifest.NAME} records runs over different files (graph {build['out']}, gen_diffs {gen['graph']} -> "
                         f"{gen['out']}, assemble {asm['graph']} + {asm['diffs']}); run the three scripts once over the same files")
    if [p["key"] for p in gen["prs"]] != [p["key"] for p in build["prs"]]:
        raise SystemExit(f"{manifest.NAME}: build_graph and gen_diffs list different PRs; run both once with the same --pr list")

    old_graph, old_diffs = load_json(graph_path), load_json(diffs_path)
    old_files = file_fingerprints(old_graph, old_diffs) if old_graph and old_diffs else None
    old_tips = dict(build.get("tips", {}))
    new_tips, moved, warnings = {}, [], []
    for pr in build["prs"]:
        tip = resolve_tip(pr["repo"], pr["range"])
        if not tip:
            raise SystemExit(f"PR {pr['key']}: cannot resolve {tip_of(pr['range'])!r} in {pr['repo']}; fetch it or fix the range")
        new_tips[pr["key"]] = tip
        old = old_tips.get(pr["key"], "")
        print(f"PR {pr['key']}: {old[:7] or '?'} -> {tip[:7]}" + ("" if old != tip else " (unchanged)"))
        if old != tip:
            moved.append((pr["key"], old, tip))
        left = pr["range"].split("..", 1)[0]
        if ".." in pr["range"] and "..." not in pr["range"] and FIXED_BASE.match(left) \
                and git(pr["repo"], "merge-base", "--is-ancestor", "--end-of-options", left, tip) is None:
            warnings.append(f"PR {pr['key']}: its range starts at the fixed commit {left}, which is no longer an ancestor of "
                            f"the tip (rebased?); re-run build_graph.py and gen_diffs.py with a new range")

    # Build into side files and swap them in only when both steps succeed, so a failure leaves the last good data.
    new_graph_path, new_diffs_path = graph_path.with_name(graph_path.name + ".new"), diffs_path.with_name(diffs_path.name + ".new")
    build_args = [f"--out={new_graph_path}", "--no-manifest"]
    for pr in build["prs"]:
        build_args += ["--pr", pr["key"], pr["repo"], pr["range"]]
    for flag, name in (("--name", "names"), ("--title", "titles"), ("--repo", "repos")):
        build_args += pair_args(flag, build.get(name))
    for alias in build.get("aliases", []):
        build_args.append(f"--alias={text({'alias': alias}, 'alias')}")
    for flag, name in (("--groups", "groups"), ("--overlay", "overlay")):
        if build.get(name):
            build_args.append(f"{flag}={manifest.resolve(here, build[name])}")
    if build.get("noDefaultGroups") is True:
        build_args.append("--no-default-groups")
    context, max_lines = gen.get("context", 4), gen.get("maxLines", 2000)
    if not (isinstance(context, int) and isinstance(max_lines, int) and context >= 0 and max_lines > 0):
        raise SystemExit(f"{manifest.NAME}: gen_diffs context and maxLines must be non-negative integers")
    diff_args = [f"--graph={new_graph_path}", f"--out={new_diffs_path}", "--no-manifest", f"--context={context}", f"--max-lines={max_lines}"]
    for pr in gen["prs"]:
        diff_args += ["--pr", pr["key"], pr["repo"], pr["range"]]
    if gen.get("strict") is True:
        diff_args.append("--strict")
    try:
        names = {str(new_graph_path): str(graph_path), str(new_diffs_path): str(diffs_path)}
        step("build_graph.py", build_args, names)
        step("gen_diffs.py", diff_args, names)
    except SystemExit:
        new_graph_path.unlink(missing_ok=True)
        new_diffs_path.unlink(missing_ok=True)
        raise
    new_graph_path.replace(graph_path)
    new_diffs_path.replace(diffs_path)
    manifest.record(here, "build_graph", {**build, "tips": new_tips})

    new_graph, new_diffs = load_json(graph_path), load_json(diffs_path)
    new_files = file_fingerprints(new_graph, new_diffs)
    kept = previous_file(here, asm)
    if old_files is None:
        previous = kept
    elif old_files == new_files and not moved and kept is not None:
        previous = kept
        print("nothing changed since the last build; the page keeps its comparison with the version before")
    else:
        # The build being replaced becomes the comparison; its generation is one after the comparison it had, so the
        # viewer can tell an older page from a newer one and never clears a read mark on an older page.
        previous = here / PREVIOUS
        short = {pr["key"]: pr.get("tip", "") for pr in old_graph.get("prs", [])}
        current = generation(manifest.resolve(here, asm.get("previous")))
        previous.write_text(json.dumps({"generation": current, "tips": short, "files": old_files}, ensure_ascii=False, indent=1,
                                       sort_keys=True) + "\n", encoding="utf-8")
    step("assemble.py", assemble_args(here, asm, previous))
    step("validate.py", ["--", str(out)])

    if previous is not None:
        before = load_json(previous).get("files", {})
        new, changed, removed = summary(before, new_files)
        print(f"changed since the previous version: {new + changed + removed} files ({new} new, {changed} changed, {removed} removed)")
    if moved:
        narrative = manifest.resolve(here, asm["narrative"])
        print(f"warning: the branches moved, so claims in {narrative.name} (stack cards, counts, file:line references, "
              f"behaviour) may be outdated; update it, then run: python3 {Path(__file__).resolve()} {here} --assemble-only")
        for line in narrative_warnings(narrative, moved, counts(old_graph or {}), counts(new_graph)):
            print(f"warning: {line}")
    for line in warnings:
        print(f"warning: {line}")
    print(f"refreshed {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
