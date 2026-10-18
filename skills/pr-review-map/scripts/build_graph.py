#!/usr/bin/env python3
"""Scaffold graphs.json for a review map straight from git: nodes, edges, reading order.

Usage:
  python3 build_graph.py --out graphs.json \\
      --pr M /path/monolith 1a2b3c4..feat/m  --name M "Monolith #59132" \\
      --pr S /path/repo main...feat/s        --name S "S #12680" \\
      --pr A /path/repo feat/s...feat/a      --name A "A #12681" \\
      [--title KEY "longer title"] [--repo KEY owner/name] \\
      [--alias '@scope/pkg=libs/pkg/src/index.ts'] [--alias '@/=src/'] \\
      [--groups groups.json] [--no-default-groups] [--overlay overlay.json] \\
      [--chunks chunks.json]

Give the PRs in merge order (earliest first); an edge from a later PR to a file an
earlier PR changed becomes a dashed cross-PR edge. Files are read with `git show`
at each range's tip, so nothing is checked out.

What the script resolves on its own:
  * nodes from `git diff --numstat` with +/- counts; lockfiles, translations,
    translation catalogs, deploy config, and docs collapse into one group node each
  * a first-guess layer per file (refine it in the overlay)
  * JS/TS imports (relative, `.js`→`.ts`, `--alias`), Python imports, PHP `use`
  * test → subject edges by file name with the test marker removed
    (`panel-test.tsx`, `panel.spec.ts`, `test_panel.py`, `panel_spec.rb` → `panel`)
  * `hub`: shared dependencies, files that at least a quarter of the PR's linked files
    (and at least 4) depend on, plus files only they use; the viewer pins them in a
    "Shared dependencies" group and leaves their incoming links out of the arcs
  * `order`: dependency-first reading order that keeps connected files adjacent, shared
    dependencies first (the viewer reverses the rest for the "from the entry point" mode)
  * each PR's `repo` label: `--repo`, else `owner/name` from the `origin` remote
    URL path (never its host, credentials, query, or fragment), else the
    repository directory name
  * each PR's `base` and `tip`: short SHAs of the two versions its diff compares
    (the merge base for `A...B`), so copied review notes can name them

What it cannot see (DI wiring, routing, HTTP calls between services, config
readers, roles, per-file notes, unchanged reference files) goes in the overlay,
so re-running after the branches move keeps it. See references/graph-schema.md.

--chunks FILE (chunks.py, references/chunks.md) splits one PR into parts cut from
its commits: each part becomes a PR of its own (key, range from..to, `chunk`
metadata) in the place of a --pr with the parent's key, else after the --pr
entries, and the output lists the parents under `parents`. An overlay reference
with the parent's key (`M:path`) sets role and note on every part's node of that
path; an edge from it starts at the last part that changes the file and ends at
the last part up to that one that has its target. A PR above 100 files or 60
nodes gets a hint to split it.
Its arguments and each PR's full tip SHA go in the `build_graph` section of
review-map.json beside --out (scripts/manifest.py), which refresh.py replays;
--no-manifest skips that. Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True  # importing manifest.py must not leave a __pycache__ in the skill
import chunks  # noqa: E402
import manifest  # noqa: E402

DEFAULT_GROUPS = [
    {"id": "lockfiles", "label": "lockfiles", "layer": "config",
     "pattern": r"(^|/)(pnpm-lock\.yaml|package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|bun\.lockb?|composer\.lock|poetry\.lock|uv\.lock|Pipfile\.lock|Cargo\.lock|go\.sum|Gemfile\.lock|Podfile\.lock|packages\.lock\.json)$"},
    {"id": "catalogs", "label": "translation catalogs", "layer": "i18n",
     "pattern": r"(^|/)translations?-catalogs?/"},
    {"id": "translations", "label": "translations", "layer": "i18n",
     "pattern": r"(^|/)(translations?|locales?|i18n|lang|messages)/.*\.(json|ya?ml|po|pot|xliff|xlf|properties|strings|arb|ftl)$"},
    {"id": "deploy", "label": "deploy config", "layer": "config",
     "pattern": r"(^|/)(helm|charts|k8s|kubernetes|deploy|deployment|terraform|\.devcontainer|\.devplanner)/|(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml|\.?env\.example|\.env\.[a-z]+\.example)$|^\.github/workflows/|^\.gitlab-ci\.yml$"},
    {"id": "docs", "label": "docs", "layer": "docs",
     "pattern": r"\.(md|mdx|rst|adoc|txt)$|(^|/)docs?/"},
]

# First-guess layer for a single file, checked in order. A test is a file under a test directory or
# one whose name carries its language's marker as its own name segment: `.test.`/`.spec.`/`.e2e.`
# anywhere; a `-test`/`_test`/`-spec`/`_spec`/`-e2e`/`_e2e` suffix in JS/TS, Vue, and Svelte
# (`mobile-state-panel-test.tsx`); Cypress `.cy.` in JS/TS; `_spec.rb`; `_test` in Go, Python, Ruby,
# Elixir, and C/C++ (`.c`, `.cc`, `.cpp`, `.cxx`); `test_*` in Python, Ruby, and C/C++; `*Test(s)` in
# PHP/JVM/.NET/Swift; `*Spec` in Kotlin, Scala, and Groovy; failsafe `*IT`/`*ITCase` in Java and
# Kotlin; Django's `tests.py`; `conftest.py`. A `Spec` or `IT` suffix counts only after a lowercase
# letter or digit that ends a name (`OrderSpec.kt`, `UserRepositoryIT.java`). So `test-utils.ts`,
# `contest.ts`, `api-spec.yaml`, `pod_spec.go`, `openapi_spec.py`, `build_spec.rs`, `Inspect.kt`,
# `SpecRunner.kt`, `Spec.kt`, `HotelSuite.kt`, `ITService.java`, `Commit.java`, `latest.cc`, and
# `testing.c` are not tests. `*Suite` is left to test directories: domain names end in it too. The JS
# suffix also tags a feature file such as `ab-test.tsx`, and the Kotlin suffix a data class such as
# `PodSpec.kt`; fix those with an overlay `layer`.
LAYER_RULES = [
    ("test", r"(^|/)(__tests__|__mocks__|tests?|e2e|spec)/|\.(spec|test|e2e)\.[^/]+$"
             r"|[-_](spec|test|e2e)\.([cm]?[jt]sx?|vue|svelte)$|\.cy\.[cm]?[jt]sx?$|_spec\.rb$"
             r"|_test\.(go|py|rb|exs|c|cc|cpp|cxx)$|(^|/)test_[^/]+\.(py|rb|c|cc|cpp|cxx)$"
             r"|Tests?\.(php|java|kt|scala|groovy|cs|swift)$|[a-z0-9]Spec\.(kt|scala|groovy)$"
             r"|[a-z0-9]IT(Case)?\.(java|kt)$|(^|/)(tests|conftest)\.py$"),
    ("wiring", r"(^|/)([\w-]*-)?(services|routing|routes|di|container|bundles)(\.[\w-]+)?\.(ya?ml|xml)$"),
    ("config", r"(^|/)(package\.json|tsconfig[^/]*\.json|jsconfig\.json|pyproject\.toml|setup\.(cfg|py)|composer\.json|go\.mod|Cargo\.toml|Gemfile|requirements[^/]*\.txt|project\.json|nx\.json|turbo\.json)$|(^|/)[^/]*\.config\.[cm]?[jt]s$|(^|/)\.[^/]*rc(\.[a-z]+)?$|\.(ya?ml|toml|ini|cfg|env)$"),
    ("data", r"(^|/)(migrations?|db|database|prisma|seeds?|fixtures)/|\.(sql|prisma)$"),
    ("contract", r"(^|/)(contracts?|schemas?|dto|dtos|openapi|proto|api-types)/|\.(proto|graphql|gql)$|\.(schema|contract|dto)\.[cm]?[jt]sx?$"),
    ("domain", r"(^|/)(domain|entities|entity|models?|value-?objects?)/"),
    ("infra", r"(^|/)(infra|infrastructure|adapters?|providers?|repositor(y|ies)|clients?|gateways?|persistence|integrations?)/"),
    ("rest", r"(^|/)(rest|controllers?|handlers?|routes?|endpoints?|resolvers?)/|(Controller|Handler|Resolver|Endpoint)\.[^/]+$|(^|/)(routes?|handlers?|router)\.[cm]?[jt]sx?$"),
    ("ui", r"\.(tsx|jsx|vue|svelte|css|scss|sass|less|html|twig|erb|hbs)$"),
    ("wiring", r"(^|/)(index|main|app|server|context|container|module|bootstrap|di|setup|register)\.[^/]+$|\.module\.[cm]?[jt]s$|(^|/)__init__\.py$"),
    ("logic", r""),
]
PRIO = {"contract": 0, "domain": 1, "data": 1, "logic": 2, "infra": 3, "rest": 4, "ui": 5,
        "wiring": 6, "test": 7, "config": 8, "i18n": 8, "docs": 9}
LATE = {"docs", "config", "i18n"}
HUB_MIN, HUB_SHARE = 4, 4  # a hub: at least 4 dependents and at least a quarter of the linked core files
KIND_RANK = {"test": 6, "route": 5, "di": 4, "http": 3, "config": 2, "import": 1}
KINDS = set(KIND_RANK)
GENERIC_NAMES = re.compile(r"^(index|types?|context|handlers?|routes?|utils?|helpers?|constants?|config|main|app|mod|lib|__init__|package|README|readme|schema|models?)\.[^.]+$")
JS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")
JS_RESOLVE = (".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json")
JS_IMPORT = re.compile(
    r"""(?:^|[;\s])(?:import|export)\s[^'"`;]*?\bfrom\s*['"]([^'"]+)['"]"""
    r"""|(?:^|[;\s])import\s*['"]([^'"]+)['"]"""
    r"""|\b(?:require|import|(?:vi|jest)\.(?:mock|doMock|requireActual|importActual))\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
PY_IMPORT = re.compile(r"^\s*(?:from\s+(\.+[\w.]*|[\w.]+)\s+import\s|import\s+([\w.]+(?:\s*,\s*[\w.]+)*))", re.MULTILINE)
PHP_USE = re.compile(r"^\s*use\s+(?:function\s+|const\s+)?\\?([A-Za-z_][\w\\]*)(?:\s+as\s+\w+)?\s*;", re.MULTILINE)
# Stripped (repeatedly) from a test's stem to find its subject: `panel-test` -> `panel`,
# `app.e2e-spec` -> `app`, `test_service` -> `service`, `UserTest` -> `User`, `login.cy` -> `login`,
# `OrderSpec` -> `Order`, `UserRepositoryIT` -> `UserRepository`. Django's `tests` strips to nothing:
# such a file has no name-matched subject and is placed by its imports.
TEST_MARK = re.compile(r"([.\-_](spec|test|e2e)$|\.cy$|Tests?$|(?<=[a-z0-9])(Spec|IT(Case)?)$|^test_|^tests$)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
SCP = re.compile(r"(?P<host>[^/:]{2,}):(?P<path>.*)")
SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def git(repo: str, *args: str, check: bool = True) -> str | None:
    result = subprocess.run(
        ["git", "-C", repo, "-c", "core.quotePath=false", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        if check:
            raise SystemExit(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
        return None
    return result.stdout


def repo_label(repo: str) -> str:
    """`owner/name` from the origin URL's path, else the directory name.

    Nothing from the host, userinfo, query, or fragment can reach the label: everything up
    to the last `@` before the path is dropped (even a password with an unescaped `/`), and
    a label part that is not a plain name falls back to the directory name.
    """
    url = (git(repo, "remote", "get-url", "origin", check=False) or "").strip()
    path = ""
    if SCHEME.match(url):
        split = urlsplit(url)
        rest = (split.netloc + split.path).rsplit("@", 1)[-1]
        if split.scheme.lower() != "file" and "/" in rest:
            path = rest.split("/", 1)[1]
    else:
        match = SCP.fullmatch(re.split(r"[?#]", url, maxsplit=1)[0].rsplit("@", 1)[-1])
        if match:
            path = match.group("path")
    parts = [part for part in path.split("/") if part]
    if parts and parts[-1].endswith(".git"):
        parts[-1] = parts[-1][: -len(".git")]
    parts = [part for part in parts if part][-2:]
    if parts and all(SAFE_PART.fullmatch(part) for part in parts):
        return "/".join(parts)
    return Path(repo).resolve().name


def tip_of(rng: str) -> str:
    if "..." in rng:
        return rng.split("...", 1)[1] or "HEAD"
    if ".." in rng:
        return rng.split("..", 1)[1] or "HEAD"
    raise SystemExit(f"range {rng!r} must be base...tip or base..tip")


def range_commits(repo: str, rng: str) -> dict[str, str]:
    """Short SHAs of the two versions the diff compares: `base` (the merge base for
    `A...B`, `A` for `A..B`) and `tip`. A commit git cannot resolve is left out."""

    def short(rev: str) -> str:
        out = git(repo, "rev-parse", "--verify", "--quiet", "--short", "--end-of-options", f"{rev}^{{commit}}", check=False)
        return (out or "").strip()

    tip = tip_of(rng)
    base = rng.split("..." if "..." in rng else "..", 1)[0] or "HEAD"
    if "..." in rng:
        base = (git(repo, "merge-base", "--end-of-options", base, tip, check=False) or "").strip()
    commits = {"base": short(base) if base else "", "tip": short(tip)}
    return {name: sha for name, sha in commits.items() if sha}


def numstat(repo: str, rng: str) -> dict[str, tuple[int, int]]:
    out = git(repo, "diff", "--numstat", "-M", "-z", "--end-of-options", rng, "--") or ""
    tokens = out.split("\0")
    files: dict[str, tuple[int, int]] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token:
            continue
        added, removed, path = token.split("\t", 2)
        if path == "":
            path = tokens[i + 1]
            i += 2
        files[path] = (int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0)
    return files


def stem(path: str) -> str:
    base = posixpath.basename(path)
    for ext in (".d.ts",):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base.rsplit(".", 1)[0] if "." in base else base


def test_stem(path: str) -> str:
    name = stem(path)
    previous = None
    while previous != name:
        previous = name
        name = TEST_MARK.sub("", name)
    return name


def guess_layer(path: str) -> str:
    for layer, pattern in LAYER_RULES:
        if re.search(pattern, path):
            return layer
    return "logic"


def group_path(files: list[str]) -> str:
    if len(files) == 1:
        return files[0]
    dirs = {posixpath.dirname(f) for f in files}
    exts = {posixpath.splitext(f)[1] for f in files}
    if len(dirs) == 1:
        directory = dirs.pop()
        leaf = f"*{exts.pop()}" if len(exts) == 1 else "*"
        return f"{directory}/{leaf}" if directory else leaf
    common = posixpath.commonpath(files)
    return f"{common}/**" if common else ", ".join(sorted(files)[:3]) + (", …" if len(files) > 3 else "")


class Resolver:
    """Resolve import specifiers of one PR against its tip tree."""

    def __init__(self, repo: str, tip: str, aliases: list[tuple[str, str]]):
        self.repo, self.tip, self.aliases = repo, tip, aliases
        listing = git(repo, "ls-tree", "-r", "--name-only", "-z", "--end-of-options", tip) or ""
        self.tree = {path for path in listing.split("\0") if path}

    def source(self, path: str) -> str:
        return git(self.repo, "show", "--end-of-options", f"{self.tip}:{path}", check=False) or ""

    def _js_candidates(self, base: str) -> list[str]:
        base = posixpath.normpath(base)
        out = [base] + [base + ext for ext in JS_RESOLVE] + [f"{base}/index{ext}" for ext in JS_RESOLVE]
        root, ext = posixpath.splitext(base)
        if ext in (".js", ".jsx", ".mjs", ".cjs"):
            out += [root + alt for alt in (".ts", ".tsx", ".mts", ".cts")]
        return out

    def js(self, frm: str, spec: str) -> str | None:
        if spec.startswith("."):
            base = posixpath.join(posixpath.dirname(frm), spec)
        else:
            base = None
            for prefix, target in self.aliases:
                if prefix.endswith("/") and spec.startswith(prefix):
                    base = target + spec[len(prefix):]
                    break
                if spec == prefix:
                    base = target
                    break
            if base is None:
                return None
        for candidate in self._js_candidates(base):
            if candidate in self.tree:
                return candidate
        return None

    def python(self, frm: str, module: str) -> list[str]:
        if module.startswith("."):
            dots = len(module) - len(module.lstrip("."))
            package = posixpath.dirname(frm)
            for _ in range(dots - 1):
                package = posixpath.dirname(package)
            rest = module.lstrip(".").replace(".", "/")
            base = posixpath.join(package, rest) if rest else package
            return [c for c in (base + ".py", base + "/__init__.py") if c in self.tree]
        rel = module.replace(".", "/")
        suffixes = ("/" + rel + ".py", "/" + rel + "/__init__.py")
        exact = [c for c in (rel + ".py", rel + "/__init__.py") if c in self.tree]
        return exact or [p for p in self.tree if p.endswith(suffixes)][:1]


def php_targets(namespace: str, candidates: set[str]) -> list[str]:
    """Map a PHP `use` to the changed file whose path ends with the most namespace parts."""
    parts = [p for p in namespace.split("\\") if p]
    best, best_len = None, 0
    for path in sorted(candidates):
        if not path.endswith(".php"):
            continue
        segments = path[:-4].split("/")
        n = 0
        while n < min(len(parts), len(segments)) and parts[-1 - n] == segments[-1 - n]:
            n += 1
        if n > best_len:
            best, best_len = path, n
    return [best] if best is not None and best_len >= min(2, len(parts)) else []


def is_core(node: dict) -> bool:
    return node["layer"] != "test" and node["layer"] not in LATE


def find_hubs(nodes: dict[str, dict], edges: list[tuple[str, str, str]], forced: dict[str, bool]) -> set[str]:
    """Shared dependencies ("hubs") of one PR; `edges` are its same-PR (from, to, kind).

    Only core files (not tests, not docs/config/i18n) and their non-test edges to each other
    count. A file is a hub when at least max(HUB_MIN, ceil(linked / HUB_SHARE)) other core files
    depend on it, `linked` being the core files that share such an edge with another one (in a
    47-file PR with 25 linked files: 7). Then a file that only hubs depend on joins them
    (repeated until nothing changes), so a hub's private helpers are read with it. `forced` is
    the overlay's per-node `hub: true/false`; `false` also keeps a file out of the second step.
    """
    core = {nk for nk in nodes if is_core(nodes[nk])}
    users: dict[str, set[str]] = {nk: set() for nk in core}
    linked: set[str] = set()
    for frm, to, kind in edges:
        if frm in core and to in core and kind != "test" and frm != to:
            users[to].add(frm)
            linked.update((frm, to))
    need = max(HUB_MIN, -(-len(linked) // HUB_SHARE))
    hubs = {nk for nk in core if len(users[nk]) >= need or forced.get(nk) is True}
    hubs -= {nk for nk, value in forced.items() if value is False}
    grown = True
    while grown:
        grown = False
        for nk in sorted(core - hubs):
            if users[nk] and users[nk] <= hubs and forced.get(nk) is not False:
                hubs.add(nk)
                grown = True
    return hubs


def reading_order(nodes: dict[str, dict], edges: list[tuple[str, str, str]], on_cycle=None) -> list[str]:
    """Dependency-first reading order of one PR's nodes; `edges` are its same-PR (from, to, kind).

    Core files (not tests, not docs/config/i18n) are read in two parts: the shared dependencies
    (nodes with `hub` set, see find_hubs) first, then the others; an edge between a hub and a
    non-hub file counts in neither part, so hubs neither pull files towards the top nor bind
    files that share nothing else. In each part the files that share a non-test edge with
    another file of that part come first, topologically sorted; the part's files with no such
    edge (edges to tests, late files, and other PRs do not count) follow, so an unrelated file
    never opens either reading mode. Among the files ready to be read next, the one connected
    (by such an edge, either direction) to the most recently placed file wins, so a chain such
    as types -> service -> controller reads as a run instead of interleaving with unrelated
    files; then (PRIO, path). Each test goes right after the core file it tests (its `test`
    edge first, else its other edges; the last such file wins), a test with no core target
    after all core files, then docs/config/i18n. The viewer's computeOrder() applies the same
    rule (its final tie-break is this stored order) and reverses only the connected files of
    each part for "from the entry point", so the shared dependencies open both modes.
    """

    def rank(nk: str, default: int = 5) -> tuple[int, str, str]:
        return (PRIO.get(nodes[nk]["layer"], default), nodes[nk]["path"], nk)

    core = {nk for nk in nodes if is_core(nodes[nk])}
    hubs = {nk for nk in core if nodes[nk].get("hub")}

    def part(members: set[str]) -> list[str]:
        deps: dict[str, set[str]] = {nk: set() for nk in members}
        near: dict[str, set[str]] = {nk: set() for nk in members}
        for frm, to, kind in edges:
            if frm in members and to in members and kind != "test" and frm != to:
                deps[frm].add(to)
                near[frm].add(to)
                near[to].add(frm)
        linked = {nk for nk in members if near[nk]}
        seq: list[str] = []
        placed: dict[str, int] = {}
        remaining = set(linked)

        def flow(nk: str) -> tuple:
            last = max((placed[m] for m in near[nk] if m in placed), default=-1)
            return (-last, *rank(nk))

        while remaining:
            ready = [nk for nk in remaining if not deps[nk] & remaining]
            if not ready:
                ready = list(remaining)
                if on_cycle:
                    on_cycle(sorted(remaining)[:3])
            pick = min(ready, key=flow)
            placed[pick] = len(seq)
            seq.append(pick)
            remaining.discard(pick)
        return seq + sorted(members - linked, key=rank)

    order = part(hubs) + part(core - hubs)
    tests = sorted((nk for nk in nodes if nodes[nk]["layer"] == "test"), key=lambda nk: (nodes[nk]["path"], nk))
    attached = []
    for test in tests:
        targets = [(to, kind) for frm, to, kind in edges if frm == test and to in core]
        attached.append((test, [to for to, kind in targets if kind == "test"] or [to for to, _kind in targets]))
    for test, subjects in [p for p in attached if p[1]] + [p for p in attached if not p[1]]:
        anchor = max((order.index(t) for t in subjects), default=len(order) - 1)
        while anchor + 1 < len(order) and nodes[order[anchor + 1]]["layer"] == "test":
            anchor += 1
        order.insert(anchor + 1, test)
    order += sorted((nk for nk in nodes if nodes[nk]["layer"] in LATE), key=lambda nk: rank(nk, 9))
    return order


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr", action="append", nargs=3, metavar=("KEY", "REPO", "RANGE"), default=[])
    parser.add_argument("--name", action="append", nargs=2, metavar=("KEY", "NAME"), default=[])
    parser.add_argument("--title", action="append", nargs=2, metavar=("KEY", "TITLE"), default=[])
    parser.add_argument("--repo", action="append", nargs=2, metavar=("KEY", "REPO"), default=[],
                        help="repository label for copied review notes (default: owner/name from origin)")
    parser.add_argument("--alias", action="append", default=[], metavar="SPEC=PATH",
                        help="map an import specifier (exact) or prefix (ending in /) to a repo path")
    parser.add_argument("--groups", type=Path, help="JSON list of extra group rules, checked before the defaults")
    parser.add_argument("--no-default-groups", action="store_true")
    parser.add_argument("--overlay", type=Path, help="authored roles, notes, layers, extra nodes and edges")
    parser.add_argument("--chunks", action="append", type=Path, default=[], metavar="FILE",
                        help="split one PR into parts cut from its commits (chunks.json from chunks.py propose)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-manifest", action="store_true", help="do not record this run in review-map.json")
    args = parser.parse_args()
    if not args.pr and not args.chunks:
        parser.error("give at least one --pr or --chunks")

    names = dict(args.name)
    titles = dict(args.title)
    repos = dict(args.repo)
    aliases = []
    for item in args.alias:
        if "=" not in item:
            raise SystemExit(f"--alias {item!r}: expected SPEC=PATH")
        spec, target = item.split("=", 1)
        aliases.append((spec, target))
    aliases.sort(key=lambda pair: -len(pair[0]))
    rules = json.loads(args.groups.read_text(encoding="utf-8")) if args.groups else []
    if not args.no_default_groups:
        rules = rules + DEFAULT_GROUPS
    overlay = json.loads(args.overlay.read_text(encoding="utf-8")) if args.overlay else {}

    keys = [key for key, _repo, _rng in args.pr]
    for key, repo, rng in args.pr:
        manifest.check_pr(key, repo, rng)
    if len(set(keys)) != len(keys):
        raise SystemExit(f"PR keys must be unique: {keys}")
    entries, parents = chunks.stack(args.pr, args.chunks)
    for entry in entries:
        manifest.check_pr(entry["key"], entry["repo"], entry["range"])
    parent_parts: dict[str, list[int]] = {}  # parent key -> indices of its parts in prs
    for index, entry in enumerate(entries):
        if "parent" in entry:
            parent_parts.setdefault(entry["parent"], []).append(index)
    parent_of = {p["parent"]["key"]: p["parent"] for p in parents}

    prs = []          # per PR: key, nodes {nk: node}, owner {path: nk}
    warnings: list[str] = []
    labels: dict[str, str] = {}
    for entry in entries:
        key, repo, rng = entry["key"], entry["repo"], entry["range"]
        files = numstat(repo, rng)
        nodes: dict[str, dict] = {}
        owner: dict[str, str] = {}
        for path in sorted(files):
            added, removed = files[path]
            rule = next((r for r in rules if re.search(r["pattern"], path)), None)
            if rule is not None and rule.get("group", True):
                nk = "#" + rule["id"]
                node = nodes.setdefault(nk, {"label": rule.get("label", rule["id"]), "layer": rule.get("layer", "docs"),
                                             "role": rule.get("role", ""), "added": 0, "removed": 0, "files": []})
                node["files"].append(path)
            else:
                nk = path
                layer = rule.get("layer") if rule else None
                node = nodes.setdefault(nk, {"label": posixpath.basename(path), "layer": layer or guess_layer(path),
                                             "role": "", "added": 0, "removed": 0, "files": [path], "path": path})
            node["added"] += added
            node["removed"] += removed
            owner[path] = nk
        for nk, node in nodes.items():
            if nk.startswith("#"):
                node["path"] = group_path(node["files"])
                if len(node["files"]) > 1:
                    node["label"] = f"{node['label']} ({len(node['files'])})"
        if repo not in labels:
            labels[repo] = repo_label(repo)
        prs.append({"key": key, "repo": repo, "label": repos.get(key) or repos.get(entry.get("parent", "")) or labels[repo],
                    "range": rng, "tip": tip_of(rng), "nodes": nodes, "owner": owner, "edges": {},
                    "chunk": entry.get("chunk"), "parent": entry.get("parent")})

    # Unchanged reference files first, so imports and `use` statements resolve to them.
    # One with a parent's key goes to its first part, so every part can link to it.
    for extra in overlay.get("extraNodes", []):
        pk = extra.get("pr")
        i = parent_parts[pk][0] if pk in parent_parts else next((n for n, pr in enumerate(prs) if pr["key"] == pk), None)
        if i is None or not extra.get("path"):
            raise SystemExit(f"overlay extraNodes entry needs a known pr and a path: {extra}")
        path = extra["path"]
        if any(path in prs[n]["owner"] for n in parent_parts.get(pk, [i])):
            warnings.append(f"overlay extraNodes {path!r} is changed in PR {extra['pr']} now; skipped (set its fields under nodes)")
            continue
        prs[i]["nodes"][path] = {
            "label": extra.get("label", posixpath.basename(path)), "layer": extra.get("layer", guess_layer(path)),
            "role": extra.get("role", ""), "added": 0, "removed": 0, "files": [], "path": path,
            "unchanged": True, **({"note": extra["note"]} if extra.get("note") else {}),
        }
        prs[i]["owner"][path] = path

    def locate(path: str, upto: int) -> tuple[int, str] | None:
        """Find the PR (this one or an earlier one) and node that changed `path`."""
        for index in range(upto, -1, -1):
            nk = prs[index]["owner"].get(path)
            if nk is not None:
                return index, nk
        return None

    def add_edge(index: int, frm: str, target: tuple[int, str], kind: str) -> None:
        if (index, frm) == target:
            return
        edges = prs[index]["edges"]
        key = (frm, target)
        if key not in edges or KIND_RANK[kind] > KIND_RANK[edges[key]]:
            edges[key] = kind

    for index, pr in enumerate(prs):
        resolver = Resolver(pr["repo"], pr["tip"], aliases)
        changed_so_far = set().union(*(set(p["owner"]) for p in prs[: index + 1]))
        for path, nk in pr["owner"].items():
            if nk.startswith("#") or pr["nodes"][nk].get("unchanged"):
                continue
            targets: list[str] = []
            if path.endswith(JS_EXT):
                src = resolver.source(path)
                for match in JS_IMPORT.finditer(src):
                    spec = match.group(1) or match.group(2) or match.group(3)
                    target = resolver.js(path, spec)
                    if target:
                        targets.append(target)
            elif path.endswith(".py"):
                src = resolver.source(path)
                for match in PY_IMPORT.finditer(src):
                    modules = [match.group(1)] if match.group(1) else [m.strip() for m in match.group(2).split(",")]
                    for module in modules:
                        targets.extend(resolver.python(path, module))
            elif path.endswith(".php"):
                src = resolver.source(path)
                for match in PHP_USE.finditer(src):
                    targets.extend(php_targets(match.group(1), changed_so_far))
            for target in targets:
                found = locate(target, index)
                if found is not None:
                    add_edge(index, nk, found, "import")

        own = pr["nodes"]
        subjects: dict[str, list[str]] = {}
        for nk, node in own.items():
            if not nk.startswith("#") and node["layer"] != "test":
                subjects.setdefault(stem(nk), []).append(nk)
        for nk, node in own.items():
            if nk.startswith("#") or node["layer"] != "test":
                continue
            name = test_stem(nk)
            candidates = subjects.get(name, []) if name else []
            if candidates:
                best = max(candidates, key=lambda c: len(posixpath.commonpath([c, nk])))
                add_edge(index, nk, (index, best), "test")

    index_of = {pr["key"]: i for i, pr in enumerate(prs)}

    def refs(text: str) -> list[tuple[int, str]]:
        """The (PR index, node key) pairs an overlay reference names: one for a PR key, one per part that has the
        path for a parent's key, in part order. A path no PR (part) changes gives none, with a warning (re-running
        after a branch moved must not fail on a file that left the PR)."""
        if ":" not in text:
            raise SystemExit(f"overlay reference {text!r}: expected KEY:path or KEY:#group")
        key, path = text.split(":", 1)
        if key not in index_of and key not in parent_parts:
            raise SystemExit(f"overlay reference {text!r}: unknown PR key {key!r}")
        found = []
        for i in parent_parts.get(key, [index_of.get(key)]):
            nk = path if path in prs[i]["nodes"] else prs[i]["owner"].get(path)
            if nk is not None:
                found.append((i, nk))
        if not found:
            warnings.append(f"overlay reference {text!r}: no node or changed file with that path in PR {key}; skipped")
        return found

    for text, fields in overlay.get("nodes", {}).items():
        for i, nk in refs(text):
            node = prs[i]["nodes"][nk]
            for field in ("role", "note", "layer", "label"):
                if field in fields:
                    node[field] = fields[field]
            if "hub" in fields:
                if not isinstance(fields["hub"], bool):
                    raise SystemExit(f"overlay nodes {text!r}: hub must be true or false")
                node["forced_hub"] = fields["hub"]
    for edge in overlay.get("edges", []):
        kind = edge.get("kind", "import")
        if kind not in KINDS:
            raise SystemExit(f"overlay edge kind {kind!r} not in {sorted(KINDS)}")
        sources, targets = refs(edge["from"]), refs(edge["to"])
        if not sources or not targets:
            continue
        i, frm = sources[-1]
        eligible = [target for target in targets if target[0] <= i]
        if not eligible:
            if any(str(edge[end]).split(":", 1)[0] in parent_parts for end in ("from", "to")):
                warnings.append(f"overlay edge {edge}: {edge['to']} is in no part up to the one {edge['from']} is in; skipped")
                continue
            raise SystemExit(f"overlay edge {edge}: an edge may only point to the same or an earlier PR")
        add_edge(i, frm, eligible[-1], kind)
    for edge in overlay.get("dropEdges", []):
        targets = refs(edge["to"])
        for si, frm in refs(edge["from"]):
            for target in targets:
                prs[si]["edges"].pop((frm, target), None)

    ids: dict[tuple[int, str], str] = {}
    for index, pr in enumerate(prs):
        nodes = pr["nodes"]
        same_pr = [(frm, to, kind) for (frm, (ti, to)), kind in pr["edges"].items() if ti == index]
        forced = {nk: node["forced_hub"] for nk, node in nodes.items() if "forced_hub" in node}
        for nk in sorted(forced):
            if forced[nk] and not is_core(nodes[nk]):
                warnings.append(f"{pr['key']}: overlay hub ignored for {nodes[nk]['path']} ({nodes[nk]['layer']} is not a core layer)")
        for nk in find_hubs(nodes, same_pr, forced):
            nodes[nk]["hub"] = True
        order = reading_order(nodes, same_pr, lambda near: warnings.append(
            f"{pr['key']}: dependency cycle broken near {near}"))
        for position, nk in enumerate(order, 1):
            ids[(index, nk)] = f"{pr['key']}{position}"
            nodes[nk]["order"] = position
        pr["order"] = order

    out = {"prs": [], "crossEdges": []}
    missing_roles = 0
    for index, pr in enumerate(prs):
        nodes = pr["nodes"]
        counts: dict[str, int] = {}
        for nk in pr["order"]:
            counts[nodes[nk]["label"]] = counts.get(nodes[nk]["label"], 0) + 1
        default_name = default_title = pr["key"]
        if pr["chunk"]:
            parent = parent_of[pr["parent"]]
            parent_name = names.get(parent["key"]) or parent.get("name") or parent["key"]
            default_name = chunks.part_name(parent_name, pr["chunk"])
            default_title = titles.get(parent["key"]) or parent.get("title") or default_name
        name = names.get(pr["key"], default_name)
        entry = {"key": pr["key"], "name": name, "title": titles.get(pr["key"], name if not pr["chunk"] else default_title),
                 "repo": pr["label"], **range_commits(pr["repo"], pr["range"])}
        if pr["chunk"]:
            entry["chunk"] = pr["chunk"]
        entry.update({"nodes": [], "edges": []})
        for nk in pr["order"]:
            node = nodes[nk]
            label = node["label"]
            if not nk.startswith("#") and (counts[label] > 1 or GENERIC_NAMES.match(label)) and "/" in node["path"]:
                label = "/".join(node["path"].split("/")[-2:])
            item = {"id": ids[(index, nk)], "label": label, "path": node["path"], "layer": node["layer"],
                    "role": node["role"], "added": node["added"], "removed": node["removed"], "order": node["order"]}
            if nk.startswith("#"):
                item["files"] = node["files"]
            if node.get("note"):
                item["note"] = node["note"]
            if node.get("unchanged"):
                item["unchanged"] = True
            if node.get("hub"):
                item["hub"] = True
            if not item["role"]:
                missing_roles += 1
            entry["nodes"].append(item)
        for (frm, target), kind in sorted(pr["edges"].items(), key=lambda kv: (ids[(index, kv[0][0])], ids[kv[0][1]])):
            edge = {"from": ids[(index, frm)], "to": ids[target], "kind": kind, "external": target[0] != index}
            entry["edges"].append(edge)
            if edge["external"]:
                out["crossEdges"].append({"from": edge["from"], "to": edge["to"], "kind": kind})
        out["prs"].append(entry)
    if parents:
        by_key = {entry["key"]: entry for entry in out["prs"]}
        out["parents"] = []
        for expanded in parents:
            parent = expanded["parent"]
            keys = [part["key"] for part in expanded["parts"]]
            item = {"key": parent["key"], "name": names.get(parent["key"]) or parent.get("name") or parent["key"],
                    "title": titles.get(parent["key"]) or parent.get("title") or "", "repo": by_key[keys[0]]["repo"]}
            item.update({k: v for k, v in (("base", by_key[keys[0]].get("base")), ("tip", by_key[keys[-1]].get("tip"))) if v})
            item["parts"] = keys
            out["parents"].append(item)

    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not args.no_manifest:
        here = args.out.resolve().parent
        section = {
            "out": manifest.stored(here, args.out),
            "prs": [{"key": key, "repo": str(Path(repo).resolve()), "range": rng} for key, repo, rng in args.pr],
            "names": [list(pair) for pair in args.name], "titles": [list(pair) for pair in args.title],
            "repos": [list(pair) for pair in args.repo], "aliases": list(args.alias),
            "groups": manifest.stored(here, args.groups), "noDefaultGroups": args.no_default_groups,
            "overlay": manifest.stored(here, args.overlay),
            "tips": {key: (git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{tip_of(rng)}^{{commit}}", check=False) or "").strip()
                     for key, repo, rng in args.pr},
        }
        if args.chunks:
            section["chunks"] = [{"path": manifest.stored(here, path), "parent": expanded["parent"]["key"], "tip": expanded["parent"]["tip"]}
                                 for path, expanded in zip(args.chunks, parents)]
        manifest.record(here, "build_graph", section)
    for index, entry in enumerate(out["prs"]):
        hubs = [node["label"] for node in entry["nodes"] if node.get("hub")]
        print(f"{entry['key']}: {len(entry['nodes'])} nodes, {len(entry['edges'])} edges"
              + (f"; shared dependencies: {', '.join(hubs)}" if hubs else ""))
        changed = len([path for path, nk in prs[index]["owner"].items() if not prs[index]["nodes"][nk].get("unchanged")])
        if "chunk" not in entry and (changed > chunks.SUGGEST_FILES or len(entry["nodes"]) > chunks.SUGGEST_NODES):
            print(f"hint: PR {entry['key']} changes {changed} files in {len(entry['nodes'])} nodes; above {chunks.SUGGEST_FILES} files "
                  f"or {chunks.SUGGEST_NODES} nodes it reads better in parts cut from its commits (chunks.py propose, references/chunks.md)")
    for expanded in parents:
        parent = expanded["parent"]
        if parent["tip"] and parent["tip"] != parent["end"]:
            warnings.append(f"PR {parent['key']}: the branch tip is {parent['tip'][:7]} but the last part ends at {parent['end'][:7]}; "
                            "refresh.py adds the commits after it as a new part")
    print(f"cross-PR edges: {len(out['crossEdges'])}; nodes without a role: {missing_roles} -> {args.out}")
    for warning in warnings:
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
