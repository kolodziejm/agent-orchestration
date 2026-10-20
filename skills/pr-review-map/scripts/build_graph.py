#!/usr/bin/env python3
"""Scaffold graphs.json for a review map straight from git: nodes, edges, reading order.

Usage:
  python3 build_graph.py --out graphs.json \\
      --pr M /path/monolith 1a2b3c4..feat/m  --name M "Monolith #59132" \\
      --pr S /path/repo main...feat/s        --name S "S #12680" \\
      --pr A /path/repo feat/s...feat/a      --name A "A #12681" \\
      [--title KEY "longer title"] [--repo KEY owner/name] \\
      [--alias '@scope/pkg=libs/pkg/src/index.ts'] [--alias '@/=apps/mobile/src/@apps/mobile'] \\
      [--groups groups.json] [--no-default-groups] [--overlay overlay.json] \\
      [--chunks chunks.json] [--previous graphs.json]

Give the PRs in merge order (earliest first); an edge from a later PR to a file an
earlier PR changed becomes a dashed cross-PR edge. Files are read at each range's tip
through one `git cat-file --batch` process per repository, so nothing is checked out.

What the script resolves on its own:
  * nodes from `git diff --numstat` with +/- counts; lockfiles, translations,
    translation catalogs, deploy config, and docs collapse into one group node each
  * a first-guess layer per file from path segments and name suffixes (refine it in the overlay)
  * JS/TS imports: relative, `.js`->`.ts`, `--alias SPEC=PATH` (an exact specifier, or a prefix ending
    in `/`), scoped `--alias SPEC=PATH@DIR` (only for importers under DIR), and the `paths`/`baseUrl` of
    the tsconfig.json or jsconfig.json nearest to the importer (its in-repo `extends` followed). For one
    import a scoped alias goes first, then the importer's tsconfig, then the unscoped aliases; the first
    that names a file in the tree wins. `import type`, `import { type A }` (every specifier a type), and
    `export type ... from` become `type` edges.
  * re-exports through unchanged barrels: an import that resolves to a file the PR does not change but
    that re-exports (`export * from`, `export { X } from`, `export * as ns from`) is followed, read at the
    tip, at most 4 files deep and never twice, to the changed files it re-exports; with named imports
    only the re-exports of those names (for `export *`, a changed file that declares one of them). Such
    an edge carries `via`, the unchanged files it went through.
  * Python imports, PHP `use`
  * test -> subject edges by file name with the test marker removed (`panel-test.tsx`, `panel.spec.ts`,
    `test_panel.py`, `panel_spec.rb` -> `panel`); a test without such a match falls back to its name
    without leading area words (`mobile-transport-test` -> `transport`), then to word overlap with a
    changed file near it (`mobile-auth-bootstrap-test` -> `auth/bootstrap.ts`), only when one file wins
  * `trivial`: a file that changes at most 2 lines, or only import/re-export lines
  * `hub`: shared dependencies, files that at least max(4, ceil(1.25 * sqrt(linked))) of the PR's linked
    files depend on, plus files only they use; the viewer pins them in a "Shared dependencies" group,
    trivial ones after the others, and leaves their incoming links out of the arcs
  * `order`: dependency-first reading order that keeps connected files adjacent, shared
    dependencies first (the viewer reverses the rest for the "from the entry point" mode); a type-only
    edge orders its files unless it closes a cycle; one warning per real import cycle names its files
  * each PR's `readFrom`: "dependencies" when most of its (at least 3) entry points are light, trivial or
    changing at most a third of the largest change underneath them, else "entry"; `readFromWhy` has the
    numbers. The viewer opens the PR in that mode unless the reader picked one for it
  * each PR's `repo` label: `--repo`, else `owner/name` from the `origin` remote
    URL path (never its host, credentials, query, or fragment), else the
    repository directory name
  * each PR's `base` and `tip`: short SHAs of the two versions its diff compares
    (the merge base for `A...B`), so copied review notes can name them
  * each node's `bucket` for the viewer's review plan: "generated" (lockfiles, test snapshots, minified files, or the
    overlay's `generated: true`), else test, i18n, docs, or config from its layer, else "logic"
  * each node's `conflict`: short SHAs of the PR's merge commits (the newest 50) whose recorded result for its files
    differs from git's automatic re-merge (`git show --remerge-diff`, git 2.36+); an older git, a shallow clone, or a
    failing call skips this with one warning

What it cannot see (DI wiring, routing, HTTP calls between services, config
readers, roles, per-file notes, unchanged reference files, areas) goes in the overlay,
so re-running after the branches move keeps it. See references/graph-schema.md.

Areas ("clusters"): the overlay's `clusters` ({id: {label, order, depth?, why?}}, depth one of
read, skim, tool, passed on as given) and each node's
`cluster` (a parent-key reference reaches every part) become each PR's `clusters`
list (the areas its nodes use, by order) and the node's `cluster`. A hub or a
docs/config/i18n node keeps none, with a warning (the viewer puts them in its
shared and late areas); the viewer groups core files without one by folder. A PR
above 40 core files without areas gets a hint: its map opens on an overview of areas.

--chunks FILE (chunks.py, references/chunks.md) splits one PR into parts cut from
its commits: each part becomes a PR of its own (key, range from..to, `chunk`
metadata) in the place of a --pr with the parent's key, else after the --pr
entries, and the output lists the parents under `parents`. An overlay reference
with the parent's key (`M:path`) sets role and note on every part's node of that
path; an edge from it starts at the last part that changes the file and ends at
the last part up to that one that has its target. A PR above 100 files or 60
nodes gets a hint to split it.
Tours ("Trasy", scripts/tours.py): the overlay's `tours` ([{id, name, steps: [{ref, side, lines, note}]}], at most 8
of 3 to 15 steps) become graphs.json `tours`, each step resolved to a node (for a parent's key the last part that
changes the file on the new side, the first on the old side) with its lines read by `git show` at the PR's tip (new
side) or base (old side); an unknown key or a group stops it. A step whose file the PR no longer changes is left out
(a tour left with fewer than 3 steps with it), and one whose file is missing on its side or whose lines run past the
file's end goes stale (it opens the whole file), each with a warning. --previous FILE (refresh.py passes the
graphs.json this build replaces) lets each step follow the code it was resolved on: it prints "moved 12-30 → 18-36" or
warns that a step went stale (it then opens the whole file). The overlay is never rewritten.
Its arguments and each PR's full tip SHA go in the `build_graph` section of
review-map.json beside --out (scripts/manifest.py), which refresh.py replays;
--no-manifest skips that. Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import posixpath
import re
import statistics
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True  # importing manifest.py must not leave a __pycache__ in the skill
import chunks  # noqa: E402
import manifest  # noqa: E402
import tours  # noqa: E402

LOCKFILES = (r"(^|/)(pnpm-lock\.yaml|package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|bun\.lockb?|composer\.lock|poetry\.lock"
             r"|uv\.lock|Pipfile\.lock|Cargo\.lock|go\.sum|Gemfile\.lock|Podfile\.lock|packages\.lock\.json)$")
DEFAULT_GROUPS = [
    {"id": "lockfiles", "label": "lockfiles", "layer": "config", "pattern": LOCKFILES},
    {"id": "catalogs", "label": "translation catalogs", "layer": "i18n",
     "pattern": r"(^|/)translations?-catalogs?/"},
    {"id": "translations", "label": "translations", "layer": "i18n",
     "pattern": r"(^|/)(translations?|locales?|i18n|lang|messages)/.*\.(json|ya?ml|po|pot|xliff|xlf|properties|strings|arb|ftl)$"},
    {"id": "deploy", "label": "deploy config", "layer": "config",
     "pattern": r"(^|/)(helm|charts|k8s|kubernetes|deploy|deployment|terraform|\.devcontainer|\.devplanner)/|(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml|\.?env\.example|\.env\.[a-z]+\.example)$|^\.github/workflows/|^\.gitlab-ci\.yml$"},
    {"id": "docs", "label": "docs", "layer": "docs",
     "pattern": r"\.(md|mdx|rst|adoc|txt)$|(^|/)docs?/"},
]

# First-guess layer for a single file, checked in order. Rules match whole path segments (a directory name between
# slashes) or a file-name suffix, never a word inside a name, and a component file (.tsx, .jsx, .vue, .svelte, .astro)
# or a stylesheet or template is `ui` before any directory word can claim it: `resources/js/client/components/x.tsx`
# is ui, `client-error-text.ts` is logic, `api-client.ts` is infra. Test support (fixtures, mocks, stubs, fakes,
# testdata, test-utils/helpers/support directories) reads as `test`.
# A test is a file under a test directory or
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
TEST_SUPPORT_DIRS = r"__fixtures__|fixtures?|testdata|test-?(?:support|utils|helpers)|mocks?|stubs?|fakes?"
TEST_SUPPORT = re.compile(r"(^|/)(" + TEST_SUPPORT_DIRS + r")/")
LAYER_RULES = [
    ("test", r"(^|/)(__tests__|__mocks__|tests?|e2e|spec|" + TEST_SUPPORT_DIRS + r")/|\.(spec|test|e2e)\.[^/]+$"
             r"|[-_](spec|test|e2e)\.([cm]?[jt]sx?|vue|svelte)$|\.cy\.[cm]?[jt]sx?$|_spec\.rb$"
             r"|_test\.(go|py|rb|exs|c|cc|cpp|cxx)$|(^|/)test_[^/]+\.(py|rb|c|cc|cpp|cxx)$"
             r"|Tests?\.(php|java|kt|scala|groovy|cs|swift)$|[a-z0-9]Spec\.(kt|scala|groovy)$"
             r"|[a-z0-9]IT(Case)?\.(java|kt)$|(^|/)(tests|conftest)\.py$"),
    ("wiring", r"(^|/)([\w-]*-)?(services|routing|routes|di|container|bundles)(\.[\w-]+)?\.(ya?ml|xml)$"),
    ("config", r"(^|/)(package\.json|tsconfig[^/]*\.json|jsconfig\.json|pyproject\.toml|setup\.(cfg|py)|composer\.json|go\.mod|Cargo\.toml|Gemfile|requirements[^/]*\.txt|project\.json|nx\.json|turbo\.json)$|(^|/)[^/]*\.config\.[cm]?[jt]s$|(^|/)\.[^/]*rc(\.[a-z]+)?$|\.(ya?ml|toml|ini|cfg|env)$"),
    ("data", r"(^|/)(migrations?|db|database|prisma|seeds?)/|\.(sql|prisma)$"),
    ("ui", r"\.(tsx|jsx|vue|svelte|astro|css|scss|sass|less|html|twig|erb|hbs)$"),
    ("contract", r"(^|/)(contracts?|schemas?|dto|dtos|openapi|proto|api-types)/|\.(proto|graphql|gql)$"
                 r"|(^|/|[._-])(schemas?|contracts?|dtos?)\.([cm]?[jt]s|py)$"),
    ("domain", r"(^|/)(domain|entities|entity|models?|value-?objects?)/"),
    ("infra", r"(^|/)(infra|infrastructure|adapters?|repositor(y|ies)|gateways?|persistence|integrations?)/"
              r"|[._-](client|repository|repo|gateway|adapter)\.([cm]?[jt]s|py|rb|go)$"
              r"|[a-z0-9](Client|Repository|Gateway|Adapter)\.(php|java|kt|scala|cs|swift|ts)$"),
    ("rest", r"(^|/)(rest|controllers?|handlers?|routes?|endpoints?|resolvers?)/|(Controller|Handler|Resolver|Endpoint)\.[^/]+$"
             r"|(^|/)(routes?|handlers?|router)\.[cm]?[jt]sx?$|[._-](controller|handler|resolver|endpoint|routes?)\.[cm]?[jt]s$"),
    ("wiring", r"(^|/)(index|main|app|server|context|container|module|bootstrap|di|setup|register)\.[^/]+$|\.module\.[cm]?[jt]s$|(^|/)__init__\.py$"),
    ("logic", r""),
]
PRIO = {"contract": 0, "domain": 1, "data": 1, "logic": 2, "infra": 3, "rest": 4, "ui": 5,
        "wiring": 6, "test": 7, "config": 8, "i18n": 8, "docs": 9}
LATE = {"docs", "config", "i18n"}
# A hub has at least max(HUB_MIN, ceil(HUB_SCALE * sqrt(linked))) dependents among the PR's `linked` core files: 4 up
# to 10 linked files, 7 at 25, 13 at 105, 25 at 400. A share (a quarter) asked for 27 of 105 and missed the error-text
# helpers fifteen screens use.
HUB_MIN, HUB_SCALE = 4, 1.25
TRIVIAL_LINES = 2       # a change of at most this many lines is trivial
IMPORT_ONLY_MAX = 60    # a larger change is never checked for being import lines only
BARREL_DEPTH = 4        # re-export hops followed from an unchanged barrel
BLOB_CAP = 1 << 20      # a tsconfig, a barrel, or a file checked for import-only changes above 1 MB is not read
# readFrom (see read_from()): "dependencies" when a PR has at least MODE_ENTRIES entry points and most of them are light:
# trivial, or changing at most 1/MODE_RATIO of the largest change underneath them.
MODE_ENTRIES, MODE_RATIO = 3, 3
OVERVIEW_CORE = 40  # above this many core files the viewer opens the map on its overview of areas
# A node's `bucket`, the kind of change the viewer's review plan counts its lines under: "generated" for lockfiles, test
# snapshots, and minified files (every file of a group) or the overlay's `generated: true`, else its layer's own bucket
# (test, i18n, docs, config), else "logic".
GENERATED = re.compile(LOCKFILES + r"|\.snap$|(^|/)__snapshots__/|\.min\.(?:[cm]?js|css)$")
BUCKETS = {"test": "test", "i18n": "i18n", "docs": "docs", "config": "config"}
DEPTHS = ("read", "skim", "tool")  # an area's `depth`: read closely, skim, or covered by a tool (`why` names the check)
REMERGE_GIT = (2, 36)  # first git with `show --remerge-diff`
MERGE_CAP = 50         # merge commits per PR checked for hand-resolved conflicts (the newest)
KIND_RANK = {"test": 6, "route": 5, "di": 4, "http": 3, "config": 2, "import": 1, "type": 0}
KINDS = set(KIND_RANK)
GENERIC_NAMES = re.compile(r"^(index|types?|context|handlers?|routes?|utils?|helpers?|constants?|config|main|app|mod|lib|__init__|package|README|readme|schema|models?)\.[^.]+$")
JS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")
JS_RESOLVE = (".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json")
JS_IMPORT = re.compile(
    r"""(?:^|[;\s])(?P<kw>import|export)\s(?P<clause>[^'"`;]*?)\bfrom\s*['"](?P<a>[^'"]+)['"]"""
    r"""|(?:^|[;\s])import\s*['"](?P<b>[^'"]+)['"]"""
    r"""|\b(?:require|import|(?:vi|jest)\.(?:mock|doMock|requireActual|importActual))\s*\(\s*['"](?P<c>[^'"]+)['"]""",
    re.MULTILINE,
)
# What an import or re-export clause names: `type`? then a default name, `* as ns` (or a bare `*`), and/or `{...}`.
CLAUSE = re.compile(r"(?P<type>type\s+(?=[{*\w$]))?(?:(?P<default>[A-Za-z_$][\w$]*)\s*(?:,\s*)?)?"
                    r"(?:(?P<star>\*)(?:\s*as\s+[\w$]+)?|\{(?P<list>[^}]*)\})?", re.DOTALL)
REEXPORT = re.compile(r"""(?:^|[;\s])export\s+(?P<type>type\s+)?(?:\*\s*(?:as\s+(?P<ns>[\w$]+)\s*)?|\{(?P<list>[^}]*)\}\s*)"""
                      r"""from\s*['"](?P<spec>[^'"]+)['"]""", re.MULTILINE)
EXPORT_DECL = re.compile(r"(?:^|[;\s])export\s+(?:declare\s+)?(?:default\s+)?(?:abstract\s+)?(?:async\s+)?"
                         r"(?:function\s*\*?|class|const|let|var|type|interface|enum|namespace)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
EXPORT_LIST = re.compile(r"(?:^|[;\s])export\s+(?:type\s+)?\{([^}]*)\}(?!\s*from\b)", re.MULTILINE)
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
PY_IMPORT = re.compile(r"^\s*(?:from\s+(\.+[\w.]*|[\w.]+)\s+import\s|import\s+([\w.]+(?:\s*,\s*[\w.]+)*))", re.MULTILINE)
PHP_USE = re.compile(r"^\s*use\s+(?:function\s+|const\s+)?\\?([A-Za-z_][\w\\]*)(?:\s+as\s+\w+)?\s*;", re.MULTILINE)
# Import statements, removed from both versions of a file to tell an import-only change (see trivial()).
IMPORT_LINES = {
    "js": re.compile(r"""^[ \t]*(?:import(?!\s*\()(?=[\s{*'"])[^'"`;]*?['"][^'"\n]*['"]|export\s+(?:type\s+)?(?:\*(?:\s*as\s+[\w$]+)?|\{[^}]*\})\s*"""
                     r"""from\s*['"][^'"\n]*['"]|(?:const|let|var)\s+[^=;\n]+=\s*require\(\s*['"][^'"\n]*['"]\s*\))[ \t]*;?""", re.MULTILINE),
    "py": re.compile(r"^[ \t]*(?:from\s+[\w.]+\s+import\s+(?:\([^)]*\)|[^\n]*)|import\s+[^\n]*)", re.MULTILINE),
    "php": re.compile(r"^[ \t]*use\s+[^;{]+;", re.MULTILINE),
}
PHP_BODY = re.compile(r"^[ \t]*(?:(?:abstract|final|readonly)\s+)*(?:class|interface|trait|enum|function)\b", re.MULTILINE)
# Stripped (repeatedly) from a test's stem to find its subject: `panel-test` -> `panel`,
# `app.e2e-spec` -> `app`, `test_service` -> `service`, `UserTest` -> `User`, `login.cy` -> `login`,
# `OrderSpec` -> `Order`, `UserRepositoryIT` -> `UserRepository`. Django's `tests` strips to nothing:
# such a file has no name-matched subject and is placed by its imports.
TEST_MARK = re.compile(r"([.\-_](spec|test|e2e)$|\.cy$|Tests?$|(?<=[a-z0-9])(Spec|IT(Case)?)$|^test_|^tests$)")
TEST_DIRS = {"__tests__", "__mocks__", "test", "tests", "spec", "specs", "e2e"}
# Words that name an area rather than a subject: dropped from the front of a test's name, and not counted as a match.
AREA_WORDS = {"mobile", "web", "test", "spec", "e2e", "unit", "integration"}
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


def base_of(repo: str, rng: str) -> str:
    """The version a range's diff starts from: the merge base for `A...B`, `A` for `A..B` ("" when git cannot tell)."""
    tip = tip_of(rng)
    base = rng.split("..." if "..." in rng else "..", 1)[0] or "HEAD"
    if "..." in rng:
        base = (git(repo, "merge-base", "--end-of-options", base, tip, check=False) or "").strip()
    return base


def range_commits(repo: str, rng: str) -> dict[str, str]:
    """Short SHAs of the two versions the diff compares: `base` (the merge base for
    `A...B`, `A` for `A..B`) and `tip`. A commit git cannot resolve is left out."""

    def short(rev: str) -> str:
        out = git(repo, "rev-parse", "--verify", "--quiet", "--short", "--end-of-options", f"{rev}^{{commit}}", check=False)
        return (out or "").strip()

    base = base_of(repo, rng)
    commits = {"base": short(base) if base else "", "tip": short(tip_of(rng))}
    return {name: sha for name, sha in commits.items() if sha}


def numstat(repo: str, rng: str) -> dict[str, tuple[int, int, bool, str | None]]:
    """path -> (added, removed, binary, path before a rename or None)."""
    out = git(repo, "diff", "--numstat", "-M", "-z", "--end-of-options", rng, "--") or ""
    tokens = out.split("\0")
    files: dict[str, tuple[int, int, bool, str | None]] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token:
            continue
        added, removed, path = token.split("\t", 2)
        old = None
        if path == "":
            old, path = tokens[i], tokens[i + 1]
            i += 2
        files[path] = (int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0,
                       added == "-" and removed == "-", old)
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


class Blobs:
    """Files at revisions read through long-running `git cat-file --batch-check` and `--batch` processes of one
    repository (one process each instead of a `git show` per file). A request is a `rev:path` line on stdin, so nothing
    in it can become an option; a path with a newline cannot be asked that way and falls back to `git show`."""

    def __init__(self, repo: str):
        self.repo = repo
        self.procs: dict[str, subprocess.Popen] = {}

    def _ask(self, mode: str, name: str) -> tuple[str, int] | None:
        proc = self.procs.get(mode)
        if proc is None:
            proc = self.procs[mode] = subprocess.Popen(["git", "-C", self.repo, "cat-file", f"--{mode}"],
                                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.stdin.write(name.encode("utf-8") + b"\n")
        proc.stdin.flush()
        head = proc.stdout.readline().decode("utf-8", errors="replace").rstrip("\n")
        parts = head.rsplit(" ", 2)
        if len(parts) != 3 or not parts[2].isdigit():
            return None  # "<name> missing" or "ambiguous"
        return parts[1], int(parts[2])

    def size(self, rev: str, path: str) -> int | None:
        """The size of a file at a revision, or None when it is not there."""
        if "\n" in path:
            text = self.read(rev, path)
            return None if text is None else len(text.encode("utf-8"))
        found = self._ask("batch-check", f"{rev}:{path}")
        return found[1] if found and found[0] == "blob" else None

    def read(self, rev: str, path: str) -> str | None:
        """A file at a revision as text, or None when it is not there."""
        if "\n" in path:
            return git(self.repo, "show", "--end-of-options", f"{rev}:{path}", check=False)
        found = self._ask("batch", f"{rev}:{path}")
        if found is None:
            return None
        proc = self.procs["batch"]
        data = proc.stdout.read(found[1])
        proc.stdout.read(1)  # the newline after the content
        return data.decode("utf-8", errors="replace") if found[0] == "blob" else None

    def close(self) -> None:
        for proc in self.procs.values():
            proc.stdin.close()
            proc.wait()
            proc.stdout.close()
        self.procs.clear()


def jsonc(text: str):
    """JSON with a leading BOM, comments, and trailing commas (tsconfig.json), or None. Comments and trailing commas are
    found outside strings only."""
    text = text[1:] if text.startswith("\ufeff") else text
    out, i, n = [], 0, len(text)

    def skip(j: int) -> int:
        """The index after white space and comments from j."""
        while j < n:
            if text[j] in " \t\r\n":
                j += 1
            elif text.startswith("//", j):
                k = text.find("\n", j)
                j = n if k < 0 else k
            elif text.startswith("/*", j):
                k = text.find("*/", j + 2)
                j = n if k < 0 else k + 2
            else:
                break
        return j

    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i) or text.startswith("/*", i):
            i = skip(i)
        elif text[i] == "," and skip(i + 1) < n and text[skip(i + 1)] in "}]":
            i += 1  # a trailing comma
        else:
            out.append(text[i])
            i += 1
    try:
        return json.loads("".join(out))
    except ValueError:
        return None


def specifiers(text: str) -> list[tuple[str, str, bool]]:
    """(name in the source module, name here, type-only) for each `a`, `a as b`, `type a` of a `{...}` list."""
    out = []
    for part in COMMENTS.sub("", text).split(","):
        part = part.strip()
        if not part:
            continue
        type_only = False
        if re.match(r"type\s+[\w$]", part) and not re.fullmatch(r"type\s+as\s+[\w$]+", part):
            type_only, part = True, part[4:].strip()
        names = re.split(r"\s+as\s+", part)
        out.append((names[0].strip(), names[-1].strip(), type_only))
    return out


def clause_names(clause: str) -> tuple[bool, set[str] | None]:
    """(type-only, names) of an `import <clause> from` or `export <clause> from`: the names it takes from the module
    (`default` for a default import), or None for all of them (`* as ns`, `*`, or a clause this cannot read)."""
    text = COMMENTS.sub("", clause).strip()
    match = CLAUSE.fullmatch(text)
    if not match or not text:
        return False, None
    specs = specifiers(match.group("list")) if match.group("list") is not None else []
    type_only = bool(match.group("type")) or (
        bool(specs) and not match.group("default") and not match.group("star") and all(t for _s, _l, t in specs))
    if match.group("star"):
        return type_only, None
    names = {source for source, _local, _t in specs}
    if match.group("default"):
        names.add("default")
    return type_only, names or None


class Resolver:
    """Resolve import specifiers of one PR against its tip tree."""

    def __init__(self, repo: str, tip: str, raw_aliases: list[str], blobs: Blobs):
        self.repo, self.tip, self.blobs = repo, tip, blobs
        listing = git(repo, "ls-tree", "-r", "--name-only", "-z", "--end-of-options", tip) or ""
        self.tree = {path for path in listing.split("\0") if path}
        self.dirs = {""}
        for path in self.tree:
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                self.dirs.add("/".join(parts[:i]))
        self.sources: dict[str, str] = {}
        self.skipped: dict[str, int] = {}  # files over BLOB_CAP left unread as a config or barrel: path -> size
        self.unreadable: set[str] = set()  # tsconfig/jsconfig files that are not JSON with comments
        self.nearest: dict[str, str | None] = {}
        self.ts_info: dict[str, tuple[list[tuple[str, list[str]]], str, str | None]] = {}
        self.exports: dict[str, list[tuple[str, str, bool, object]]] = {}
        self.ts_hits: dict[str, int] = {}
        self.scoped: list[tuple[str, str, str]] = []
        self.unscoped: list[tuple[str, str]] = []
        self.missing: set[str] = set()  # aliases whose path or directory this tree lacks
        for item in raw_aliases:
            spec, target, scope = self.parse_alias(item)
            if scope is None:
                self.unscoped.append((spec, target))
            else:
                self.scoped.append((spec, target, scope))
            if not self.exists(target) or (scope is not None and scope not in self.dirs):
                self.missing.add(item)
        self.unscoped.sort(key=lambda pair: -len(pair[0]))
        self.scoped.sort(key=lambda item: (-len(item[2]), -len(item[0])))

    def exists(self, path: str) -> bool:
        """Whether a path (a file, a directory, or a module path without its extension) is in the tree."""
        path = path.rstrip("/")
        if not path:
            return True
        return path in self.dirs or any(c in self.tree for c in self._js_candidates(path))

    def parse_alias(self, item: str) -> tuple[str, str, str | None]:
        """SPEC=PATH, or SPEC=PATH@DIR for importers under DIR. A PATH that is itself in the tree keeps its `@`
        (`src/@core/`); a trailing `@` (empty DIR) also says the alias is unscoped."""
        if "=" not in item:
            raise SystemExit(f"--alias {item!r}: expected SPEC=PATH or SPEC=PATH@DIR")
        spec, target = item.split("=", 1)
        scope = None
        if "@" in target and not self.exists(target):
            head, tail = target.rsplit("@", 1)
            if head:
                target, scope = head, tail.strip("/") or None
        if spec.endswith("/") and target and not target.endswith("/"):
            target += "/"
        return spec, target, scope

    def source(self, path: str, capped: bool = False) -> str:
        """A file at the tip ("" when it is not there). `capped`: read only up to BLOB_CAP bytes, else "" (noted in
        `skipped`); configs and barrels are read so, a changed file's own imports are not."""
        if path not in self.sources:
            if capped:
                size = self.blobs.size(self.tip, path)
                if size is not None and size > BLOB_CAP:
                    self.skipped[path] = size
                    return ""
            self.sources[path] = self.blobs.read(self.tip, path) or ""
        return self.sources[path]

    def _js_candidates(self, base: str) -> list[str]:
        base = posixpath.normpath(base)
        out = [base] + [base + ext for ext in JS_RESOLVE] + [f"{base}/index{ext}" for ext in JS_RESOLVE]
        root, ext = posixpath.splitext(base)
        if ext in (".js", ".jsx", ".mjs", ".cjs"):
            out += [root + alt for alt in (".ts", ".tsx", ".mts", ".cts")]
        return out

    def _first(self, base: str) -> str | None:
        return next((c for c in self._js_candidates(base) if c in self.tree), None)

    @staticmethod
    def _alias_bases(pairs, spec: str) -> list[str]:
        out = []
        for prefix, target in pairs:
            if prefix.endswith("/") and spec.startswith(prefix):
                out.append(target + spec[len(prefix):])
            elif spec == prefix:
                out.append(target)
        return out

    def js(self, frm: str, spec: str) -> str | None:
        if spec.startswith("."):
            return self._first(posixpath.join(posixpath.dirname(frm), spec))
        scoped = [(s, t) for s, t, scope in self.scoped if frm.startswith(scope + "/")]
        for base in self._alias_bases(scoped, spec):
            hit = self._first(base)
            if hit:
                return hit
        config = self._nearest(posixpath.dirname(frm))
        if config:
            for base in self._tsconfig_bases(config, spec):
                hit = self._first(base)
                if hit:
                    self.ts_hits[config] = self.ts_hits.get(config, 0) + 1
                    return hit
        for base in self._alias_bases(self.unscoped, spec):
            hit = self._first(base)
            if hit:
                return hit
        return None

    def _nearest(self, directory: str) -> str | None:
        """The tsconfig.json or jsconfig.json in `directory` or the closest directory above it."""
        if directory not in self.nearest:
            here = next((p for p in (posixpath.join(directory, n) for n in ("tsconfig.json", "jsconfig.json")) if p in self.tree), None)
            self.nearest[directory] = here if here or not directory else self._nearest(posixpath.dirname(directory))
        return self.nearest[directory]

    def _extends(self, config: str, value) -> list[str]:
        """The in-repo configs `extends` names, last first (a later one overrides an earlier one); packages are skipped."""
        out = []
        for item in reversed(value if isinstance(value, list) else [value]):
            if not isinstance(item, str) or not item.startswith((".", "/")) or item.startswith("/"):
                continue
            path = posixpath.normpath(posixpath.join(posixpath.dirname(config), item))
            for candidate in (path, path + ".json", posixpath.join(path, "tsconfig.json")):
                if candidate in self.tree:
                    out.append(candidate)
                    break
        return out

    def _tsconfig_bases(self, config: str, spec: str) -> list[str]:
        if config not in self.ts_info:
            paths = base_url = paths_dir = None
            order, seen = [config], set()
            while order:
                current = order.pop(0)
                if current in seen or len(seen) > 16:
                    continue
                seen.add(current)
                text = self.source(current, capped=True)
                data = jsonc(text)
                if not isinstance(data, dict):
                    if text.strip():
                        self.unreadable.add(current)
                    continue
                options = data.get("compilerOptions") if isinstance(data.get("compilerOptions"), dict) else {}
                if paths is None and isinstance(options.get("paths"), dict):
                    paths, paths_dir = options["paths"], posixpath.dirname(current)
                if base_url is None and isinstance(options.get("baseUrl"), str):
                    base_url = posixpath.normpath(posixpath.join(posixpath.dirname(current), options["baseUrl"]))
                order[:0] = self._extends(current, data.get("extends"))
            if base_url == ".":
                base_url = ""
            patterns = [(pattern, [t for t in targets if isinstance(t, str)]) for pattern, targets in (paths or {}).items()
                        if isinstance(pattern, str) and isinstance(targets, list)]
            self.ts_info[config] = (patterns, base_url if base_url is not None else paths_dir or "", base_url)
        patterns, root, base_url = self.ts_info[config]
        out = []
        exact = [targets for pattern, targets in patterns if "*" not in pattern and pattern == spec]
        wild = []
        for pattern, targets in patterns:
            if "*" in pattern:
                prefix, suffix = pattern.split("*", 1)
                if spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix):
                    wild.append((len(prefix), pattern, targets, spec[len(prefix):len(spec) - len(suffix)]))
        for targets in exact:
            out += [posixpath.join(root, t) for t in targets]
        for _length, _pattern, targets, star in sorted(wild, key=lambda w: (-w[0], w[1])):
            out += [posixpath.join(root, t.replace("*", star, 1)) for t in targets]
        if base_url is not None:
            out.append(posixpath.join(base_url, spec))
        return [posixpath.normpath(b) for b in out]

    def reexports(self, path: str) -> list[tuple[str, str, bool, object]]:
        """(specifier, form, type-only, detail) per `export ... from` of a file: form "named" with its specifiers,
        "ns" with the namespace name, or "star"."""
        if path not in self.exports:
            out = []
            for m in REEXPORT.finditer(self.source(path, capped=True)):
                type_only = bool(m.group("type"))
                if m.group("list") is not None:
                    out.append((m.group("spec"), "named", type_only, specifiers(m.group("list"))))
                elif m.group("ns"):
                    out.append((m.group("spec"), "ns", type_only, m.group("ns")))
                else:
                    out.append((m.group("spec"), "star", type_only, None))
            self.exports[path] = out
        return self.exports[path]

    def declares(self, path: str) -> set[str] | None:
        """The names a module exports, or None when this cannot tell (an `export *`, CommonJS, destructuring, a file
        too large to read)."""
        src = self.source(path, capped=True)
        if (re.search(r"(?:^|[;\s])export\s+(?:type\s+)?\*\s*from", src) or "module.exports" in src
                or re.search(r"\bexports\.\w", src) or re.search(r"(?:^|[;\s])export\s+(?:const|let|var)\s*[{\[]", src)):
            return None
        names = set(EXPORT_DECL.findall(src))
        if re.search(r"(?:^|[;\s])export\s+default\b", src):
            names.add("default")
        for m in EXPORT_LIST.finditer(src):
            names.update(local for _s, local, _t in specifiers(m.group(1)))
        for _spec, form, _t, detail in self.reexports(path):
            if form == "named":
                names.update(local for _s, local, _t2 in detail)
            elif form == "ns":
                names.add(detail)
        return names or None

    def through(self, path: str, names: set[str] | None, changed, depth: int = 0, seen: set[str] | None = None):
        """[(changed file, type-only, chain)]: the changed files `path`, an unchanged module, re-exports `names` from
        (None: any), directly or through other unchanged modules, at most BARREL_DEPTH hops, each file once."""
        seen = set() if seen is None else seen
        if depth >= BARREL_DEPTH or path in seen or not path.endswith(JS_EXT):
            return []
        seen.add(path)
        out = []
        for spec, form, type_only, detail in self.reexports(path):
            if form == "named":
                picked = [(s, local, t) for s, local, t in detail if names is None or local in names]
                if not picked:
                    continue
                child = {s for s, _local, _t in picked}
                type_only = type_only or all(t for _s, _l, t in picked)
            elif form == "ns":
                if names is not None and detail not in names:
                    continue
                child = None
            else:
                child = None if names is None else names - {"default"}
                if child is not None and not child:
                    continue
            target = self.js(path, spec)
            if target is None:
                continue
            if changed(target):
                if form == "star" and child is not None:
                    declared = self.declares(target)
                    if declared is not None and not declared & child:
                        continue
                out.append((target, type_only, (path,)))
            else:
                for hit, deeper_type, chain in self.through(target, child, changed, depth + 1, seen):
                    out.append((hit, type_only or deeper_type, (path,) + chain))
        return out

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


def import_free(path: str, text: str) -> str | None:
    """A code file's text without its import statements and white space; None for other files. In PHP only a `use`
    before the first class, interface, trait, enum, or function counts: one inside a class takes in a trait."""
    lang = "js" if path.endswith(JS_EXT) else "py" if path.endswith(".py") else "php" if path.endswith(".php") else None
    if lang is None:
        return None
    if lang == "php":
        body = PHP_BODY.search(text)
        head, tail = (text[:body.start()], text[body.start():]) if body else (text, "")
        return re.sub(r"\s+", "", IMPORT_LINES[lang].sub("", head) + tail)
    return re.sub(r"\s+", "", IMPORT_LINES[lang].sub("", text))


def is_core(node: dict) -> bool:
    return node["layer"] != "test" and node["layer"] not in LATE


def bucket(node: dict) -> str:
    """The node's `bucket`: "generated" when the overlay says so or every file is a lockfile, a test snapshot, or a
    minified file (overlay `generated: false` keeps such a node in its layer's bucket), else test, i18n, docs, or
    config from its layer, else logic."""
    generated = node.get("generated")
    if generated is None:
        generated = all(GENERATED.search(path) for path in node["files"] or [node["path"]])
    return "generated" if generated else BUCKETS.get(node["layer"], "logic")


class Conflicts:
    """Files whose recorded merge result differs from git's automatic re-merge: per merge commit of a PR (`git rev-list
    --merges`, the newest MERGE_CAP), the paths `git show --remerge-diff --name-only` lists (git 2.36+). Hand-resolved
    conflicts show up there, and so does anything else the merge commit changed by hand. An older git, a shallow
    repository (its re-merges may lack their merge base), or a failing call turns the check off with one warning; it
    never stops the build."""

    def __init__(self, warnings: list[str]) -> None:
        self.warnings = warnings
        self.version: tuple[int, int] | None = None
        self.off = False
        self.shallow: dict[str, bool] = {}  # repo -> is a shallow clone
        self.rank: dict[str, int] = {}  # short SHA -> place among the merges checked, oldest first

    def stop(self, why: str) -> None:
        self.off = True
        self.warnings.append(f"{why}; files with hand-resolved merge conflicts are not marked")

    def supported(self, repo: str) -> bool:
        if self.version is None and not self.off:
            found = re.search(r"(\d+)\.(\d+)", git(repo, "version", check=False) or "")
            self.version = (int(found.group(1)), int(found.group(2))) if found else REMERGE_GIT
            if self.version < REMERGE_GIT:
                self.stop(f"git {self.version[0]}.{self.version[1]} has no --remerge-diff (2.36+)")
        if self.off:
            return False
        if repo not in self.shallow:
            self.shallow[repo] = (git(repo, "rev-parse", "--is-shallow-repository", check=False) or "").strip() == "true"
            if self.shallow[repo]:
                self.warnings.append(f"{repo} is a shallow clone; files with hand-resolved merge conflicts are not marked in it")
        return not self.shallow[repo]

    def of(self, key: str, repo: str, rng: str) -> dict[str, list[str]]:
        """path at the merge -> short SHAs of the merges that changed it by hand, oldest first."""
        if not self.supported(repo):
            return {}
        listed = git(repo, "rev-list", "--merges", "--end-of-options", rng.replace("...", "..", 1), check=False)
        if listed is None:
            self.stop(f"PR {key}: git rev-list --merges failed")
            return {}
        merges = listed.split()
        if len(merges) > MERGE_CAP:
            self.warnings.append(f"PR {key}: {len(merges)} merge commits; only the newest {MERGE_CAP} are checked for hand-resolved conflicts")
        found: dict[str, list[str]] = {}
        for sha in reversed(merges[:MERGE_CAP]):
            self.rank.setdefault(sha[:7], len(self.rank))
            out = git(repo, "show", "--remerge-diff", "--format=", "--name-only", "-z", "--end-of-options", sha, check=False)
            if out is None:
                self.stop(f"PR {key}: git show --remerge-diff {sha[:7]} failed")
                return {}
            for path in filter(None, out.split("\0")):
                found.setdefault(path, []).append(sha[:7])
        return found


def is_light(node: dict) -> bool:
    """A trivial change or an unchanged reference file: nothing to read first."""
    return bool(node.get("trivial") or node.get("unchanged"))


def find_hubs(nodes: dict[str, dict], edges: list[tuple[str, str, str]], forced: dict[str, bool]) -> set[str]:
    """Shared dependencies ("hubs") of one PR; `edges` are its same-PR (from, to, kind).

    Only core files (not tests, not docs/config/i18n) and their non-test edges to each other
    count. A file is a hub when at least max(HUB_MIN, ceil(HUB_SCALE * sqrt(linked))) other core
    files depend on it, `linked` being the core files that share such an edge with another one (10
    linked files: 4; 25: 7; 105: 13). Then a file that only hubs depend on joins them (repeated
    until nothing changes), so a hub's private helpers are read with it. `forced` is the overlay's
    per-node `hub: true/false`; `false` also keeps a file out of the second step. A trivial change
    can be a hub (its links would otherwise bind every user together); the order reads it after
    the other hubs.
    """
    core = {nk for nk in nodes if is_core(nodes[nk])}
    users: dict[str, set[str]] = {nk: set() for nk in core}
    linked: set[str] = set()
    for frm, to, kind in edges:
        if frm in core and to in core and kind != "test" and frm != to:
            users[to].add(frm)
            linked.update((frm, to))
    need = max(HUB_MIN, math.ceil(HUB_SCALE * math.sqrt(len(linked))))
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


def read_clusters(overlay: dict) -> dict[str, dict]:
    """The overlay's areas, {id: {"id", "label", "order", "depth"?, "why"?}}; `order` defaults to the area's place in the
    overlay, `depth` (read, skim, tool) and `why` (what covers a "tool" area) are optional and passed on as given."""
    raw = overlay.get("clusters", {})
    if not isinstance(raw, dict):
        raise SystemExit('overlay "clusters" must be an object: {"auth": {"label": "Sign-in", "order": 1}}')
    out = {}
    for position, (cid, fields) in enumerate(raw.items(), 1):
        if not manifest.CLUSTER.fullmatch(cid):
            raise SystemExit(f"overlay cluster id {cid!r}: up to 40 letters, digits, '_', '.', or '-', starting with a letter or digit")
        if not isinstance(fields, dict):
            raise SystemExit(f"overlay cluster {cid!r} must be an object with an optional label and order")
        label, order = fields.get("label", cid), fields.get("order", position)
        if not isinstance(label, str) or not label.strip() or chunks.CONTROL.search(label):
            raise SystemExit(f"overlay cluster {cid!r}: label must be non-empty text")
        if not isinstance(order, int) or isinstance(order, bool):
            raise SystemExit(f"overlay cluster {cid!r}: order must be an integer")
        out[cid] = {"id": cid, "label": label.strip(), "order": order}
        if "depth" in fields:
            if fields["depth"] not in DEPTHS:
                raise SystemExit(f"overlay cluster {cid!r}: depth must be one of {', '.join(DEPTHS)}")
            out[cid]["depth"] = fields["depth"]
        if "why" in fields:
            why = fields["why"]
            if not isinstance(why, str) or not why.strip() or chunks.CONTROL.search(why):
                raise SystemExit(f"overlay cluster {cid!r}: why must be non-empty text")
            out[cid]["why"] = why
    return out


def components(members: list[str], deps: dict[str, set[str]]) -> dict[str, int]:
    """Strongly connected components (Tarjan, iterative): node -> component number; `members` sets the visit order."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    comp: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    count = 0
    for root in members:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(sorted(deps[root])))]
        while work:
            node, rest = work[-1]
            for nxt in rest:
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(deps[nxt]))))
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        comp[member] = count
                        if member == node:
                            break
                    count += 1
    return comp


def reading_order(nodes: dict[str, dict], edges: list[tuple[str, str, str]], on_cycle=None) -> list[str]:
    """Dependency-first reading order of one PR's nodes; `edges` are its same-PR (from, to, kind).

    Core files (not tests, not docs/config/i18n) are read in three parts: the shared dependencies
    (nodes with `hub` set, see find_hubs) with something to read, then the trivial or unchanged
    ones, then the other files; an edge between two parts counts in neither, so hubs neither pull
    files towards the top nor bind files that share nothing else. Edges are non-test edges between
    core files. A `type` edge (a type-only import) orders its files like an import unless it closes
    a cycle: type edges inside a strongly connected component of all edges are dropped from the
    ordering (they still link the files), so a type-only cycle orders nothing and warns nothing.
    Each strongly connected component left (a real import cycle) is reported once through
    `on_cycle(paths)`. In each part the files that share an edge with another file of that part
    come first, topologically sorted; when a cycle blocks every file, the files of a cycle that
    waits on nothing outside itself are the candidates. The part's files with no such edge (edges
    to tests, late files, and other PRs do not count) follow, so an unrelated file never opens
    either reading mode. Among the candidates, the one connected (by such an edge, either
    direction) to the most recently placed file wins, so a chain such as types -> service ->
    controller reads as a run instead of interleaving with unrelated files; then (PRIO, path).
    Each test goes right after the core file it tests (its `test` edge first, else its other
    edges; the last such file wins), a test with no core target after all core files, then
    docs/config/i18n. The viewer's computeOrder() applies the same rule (its final tie-break is
    this stored order) and reverses only the connected files of each part for "from the entry
    point", so the shared dependencies open both modes.
    """

    def rank(nk: str, default: int = 5) -> tuple[int, str, str]:
        return (PRIO.get(nodes[nk]["layer"], default), nodes[nk]["path"], nk)

    core = {nk for nk in nodes if is_core(nodes[nk])}
    hubs = {nk for nk in core if nodes[nk].get("hub")}
    light = {nk for nk in hubs if is_light(nodes[nk])}
    rel = sorted({(frm, to, kind) for frm, to, kind in edges if frm in core and to in core and kind != "test" and frm != to})
    members = sorted(core, key=rank)
    every: dict[str, set[str]] = {nk: set() for nk in core}
    for frm, to, _kind in rel:
        every[frm].add(to)
    loose = components(members, every)
    hard = {(frm, to) for frm, to, kind in rel if kind != "type" or loose[frm] != loose[to]}
    strict: dict[str, set[str]] = {nk: set() for nk in core}
    for frm, to in hard:
        strict[frm].add(to)
    comp = components(members, strict)
    cycles: dict[int, list[str]] = {}
    for nk in members:
        cycles.setdefault(comp[nk], []).append(nodes[nk]["path"])
    if on_cycle:
        for paths in sorted((sorted(p) for p in cycles.values() if len(p) > 1)):
            on_cycle(paths)

    def part(members: set[str]) -> list[str]:
        deps: dict[str, set[str]] = {nk: set() for nk in members}
        near: dict[str, set[str]] = {nk: set() for nk in members}
        for frm, to, _kind in rel:
            if frm in members and to in members:
                near[frm].add(to)
                near[to].add(frm)
                if (frm, to) in hard:
                    deps[frm].add(to)
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
                blocked = {comp[nk] for nk in remaining if any(comp[d] != comp[nk] for d in deps[nk] & remaining)}
                ready = [nk for nk in remaining if comp[nk] not in blocked]
            pick = min(ready, key=flow)
            placed[pick] = len(seq)
            seq.append(pick)
            remaining.discard(pick)
        return seq + sorted(members - linked, key=rank)

    order = part(hubs - light) + part(light) + part(core - hubs)
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


def resolve_tours(specs: list[dict], prs: list[dict], ids: dict, index_of: dict[str, int], parent_parts: dict[str, list[int]],
                  previous, warnings: list[str]) -> tuple[list[dict], list[str]]:
    """graphs.json `tours` from the overlay's (tours.read()) and the lines to print about steps that moved.

    A step's ref names a file of a PR (a changed file, one inside a group, or an extraNodes reference); for a parent's
    key the last part that has the file on the new side, the first on the old side. Its lines are read with `git show`
    at the PR's tip (new side) or base (old side: the merge base for A...B) and placed by tours.place(), from the
    previous build's step with the same tour, ref, side, and lines when `previous` has one. A stale step's message goes
    to `warnings`. An unknown PR key or a group stops the build (the overlay is wrong); what a moved branch can cause
    degrades with a warning, as other overlay references do: a step whose file the PR no longer changes is left out
    (and a tour left with fewer than tours.MIN_STEPS steps with it), a step whose file is missing on its side opens
    the whole file (stale, keeping the previous build's lines and code for when the file comes back)."""
    if not specs:
        return [], []
    revs: dict[tuple[int, str], str | None] = {}

    def side_rev(index: int, side: str) -> str | None:
        if (index, side) not in revs:
            repo, rng = prs[index]["repo"], prs[index]["range"]
            three = "..." in rng
            left, right = rng.split("..." if three else "..", 1)
            right = right or "HEAD"
            if side == "new":
                rev = right
            elif three:
                rev = (git(repo, "merge-base", "--end-of-options", left or "HEAD", right, check=False) or "").strip()
            else:
                rev = left or "HEAD"
            found = git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}", check=False) if rev else None
            revs[(index, side)] = (found or "").strip() or None
        return revs[(index, side)]

    before, seen, out, moves = tours.previous_steps(previous), {}, [], []
    for tour in specs:
        steps = []
        for number, spec in enumerate(tour["steps"], 1):
            where = f"tour {tour['id']} step {number} ({spec['ref']})"
            key, path = spec["ref"].split(":", 1)
            if key not in index_of and key not in parent_parts:
                raise SystemExit(f"{where}: unknown PR key {key!r}")
            if not path or path.startswith("#"):
                raise SystemExit(f"{where}: a step names a file (KEY:path), not a group")
            found = [i for i in parent_parts.get(key, [index_of.get(key)]) if path in prs[i]["owner"]]
            if not found:
                warnings.append(f"{where}: PR {key} has no node with the file {path!r} (a changed file or an extraNodes reference) "
                                "any more; the step is left out until the overlay is updated")
                continue
            index = found[-1] if spec["side"] == "new" else found[0]
            placed, message = {}, None
            if spec["a"] is not None:
                match = (tour["id"], spec["ref"], spec["side"], spec["lines"])
                earlier = before.get(match, [])
                previous_step = earlier[seen.get(match, 0)] if seen.get(match, 0) < len(earlier) else None
                seen[match] = seen.get(match, 0) + 1
                rev = side_rev(index, spec["side"])
                text = git(prs[index]["repo"], "show", "--end-of-options", f"{rev}:{path}", check=False) if rev else None
                if text is None:
                    placed = tours.gone(previous_step)
                    message = (f"{where}: {path} does not exist on the {spec['side']} side of PR {prs[index]['key']} "
                               f"({'tip' if spec['side'] == 'new' else 'base'} {(rev or '?')[:7]}); the step opens the whole file "
                               "until its side or lines in the overlay are updated")
                else:
                    placed, message = tours.place(spec, tours.file_lines(text), previous_step, where)
            if message:
                (warnings if placed.get("stale") else moves).append(message)
            step = {"node": ids[(index, prs[index]["owner"][path])], "path": path, "side": spec["side"]}
            step.update({field: placed[field] for field in ("a", "b", "stale") if field in placed})
            step.update({"note": spec["note"], "ref": spec["ref"]})
            if spec["lines"] is not None:
                step["lines"] = spec["lines"]
            if "code" in placed:
                step["code"] = placed["code"]
            steps.append(step)
        if len(steps) < tours.MIN_STEPS:
            warnings.append(f"tour {tour['id']}: {len(steps)} of its {len(tour['steps'])} steps are left; a tour has {tours.MIN_STEPS} to "
                            f"{tours.MAX_STEPS}, so it is left out until the overlay is updated")
            continue
        out.append({"id": tour["id"], "name": tour["name"], "steps": steps})
    return out, moves


def read_from(nodes: dict[str, dict], edges: list[tuple[str, str, str]]) -> tuple[str, dict[str, int]]:
    """The reading mode to open a PR in, and the numbers behind it.

    Entry points are the linked core files outside the hubs that no other such file depends on (the
    files "from the entry point" opens with). An entry point is light when it is trivial (at most 2
    changed lines, or only import lines) or unchanged, or when its change (added + removed lines) is at
    most 1/MODE_RATIO of the largest change among the core files it depends on, directly or through
    others, hubs included. "dependencies" when there are at least MODE_ENTRIES entry points and more
    than half of them are light: a PR that adapts many callers to a change underneath reads best from
    that change. Otherwise "entry". `why` holds the counts, the median change of the entry points and
    of the largest change under each, and `reason`: "few" (fewer than MODE_ENTRIES entry points), "light", or "heavy".
    """
    core = {nk for nk in nodes if is_core(nodes[nk])}
    hubs = {nk for nk in core if nodes[nk].get("hub")}
    rest = core - hubs
    below: dict[str, set[str]] = {nk: set() for nk in core}
    linked: set[str] = set()
    used: set[str] = set()
    for frm, to, kind in edges:
        if frm in core and to in core and kind != "test" and frm != to:
            below[frm].add(to)
            if frm in rest and to in rest:
                linked.update((frm, to))
                used.add(to)
    entries = sorted(linked - used)

    def lines(nk: str) -> int:
        return nodes[nk]["added"] + nodes[nk]["removed"]

    def base(nk: str) -> int:
        seen, stack, top = {nk}, [nk], 0
        while stack:
            for dep in below[stack.pop()]:
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
                    top = max(top, lines(dep))
        return top

    bases = {nk: base(nk) for nk in entries}
    light = [nk for nk in entries if is_light(nodes[nk]) or MODE_RATIO * lines(nk) <= bases[nk]]
    why = {"entries": len(entries), "light": len(light),
           "entryLines": statistics.median_low([lines(nk) for nk in entries]) if entries else 0,
           "baseLines": statistics.median_low(list(bases.values())) if entries else 0}
    deps_first = len(entries) >= MODE_ENTRIES and 2 * len(light) > len(entries)
    why["reason"] = "few" if len(entries) < MODE_ENTRIES else "light" if deps_first else "heavy"
    return ("dependencies" if deps_first else "entry"), why


def words(text: str) -> list[str]:
    """Lower-case words of a name or path (camelCase split, digits dropped, a plural `s` removed)."""
    out = []
    for word in re.split(r"[^A-Za-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).lower()):
        if not word or word.isdigit():
            continue
        out.append(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word)
    return out


def test_root(test: str) -> str:
    """Where a test's subjects live: the path above its last test directory (`apps/mobile` for
    `apps/mobile/__tests__/x-test.ts`), else its own directory."""
    dirs = test.split("/")[:-1]
    cut = max((i for i, d in enumerate(dirs) if d in TEST_DIRS), default=None)
    return "/".join(dirs[:cut] if cut is not None else dirs)


def guess_subject(test: str, subjects: dict[str, list[str]], candidates: list[str]) -> str | None:
    """A subject for a test its name does not match exactly; None unless exactly one file wins.

    Only changed core files under test_root() count. First the test's name without leading area words (words of its
    own directories, or mobile/web/test/spec/e2e/unit/integration): `mobile-transport-test` -> `transport`. Then word
    overlap: a file all of whose name words are in the test's name, scored by the test's other words (area words do not
    count) that its name or its directories below the root share; the best score, at least 2, held by one file wins:
    `mobile-auth-bootstrap-test` -> `auth/bootstrap.ts`, `task-detail-mutations-test` -> `details/task-detail.tsx`.
    """
    root = test_root(test)
    near = [c for c in candidates if not root or c.startswith(root + "/")]
    area = AREA_WORDS | set(words(posixpath.dirname(test)))
    name = test_stem(test)
    match = re.match(r"([A-Za-z0-9]+)[-_.](.+)$", name)
    while match and set(words(match.group(1))) <= area:
        name = match.group(2)
        found = [c for c in subjects.get(name, []) if c in near]
        if len(found) == 1:
            return found[0]
        if found:
            return None
        match = re.match(r"([A-Za-z0-9]+)[-_.](.+)$", name)
    mine = set(words(test_stem(test)))
    wanted = mine - area
    best, best_score, tied = None, 0, False
    for candidate in near:
        own = set(words(stem(candidate)))
        if not own or not own <= mine:
            continue
        below = candidate[len(root) + 1:] if root else candidate
        score = len((own | set(words(posixpath.dirname(below)))) & wanted)
        if score > best_score:
            best, best_score, tied = candidate, score, False
        elif score == best_score and score:
            tied = True
    return best if best is not None and best_score >= 2 and not tied else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr", action="append", nargs=3, metavar=("KEY", "REPO", "RANGE"), default=[])
    parser.add_argument("--name", action="append", nargs=2, metavar=("KEY", "NAME"), default=[])
    parser.add_argument("--title", action="append", nargs=2, metavar=("KEY", "TITLE"), default=[])
    parser.add_argument("--repo", action="append", nargs=2, metavar=("KEY", "REPO"), default=[],
                        help="repository label for copied review notes (default: owner/name from origin)")
    parser.add_argument("--alias", action="append", default=[], metavar="SPEC=PATH[@DIR]",
                        help="map an import specifier (exact) or prefix (ending in /) to a repo path; "
                             "@DIR limits it to importers under DIR")
    parser.add_argument("--groups", type=Path, help="JSON list of extra group rules, checked before the defaults")
    parser.add_argument("--no-default-groups", action="store_true")
    parser.add_argument("--overlay", type=Path, help="authored roles, notes, layers, extra nodes and edges")
    parser.add_argument("--chunks", action="append", type=Path, default=[], metavar="FILE",
                        help="split one PR into parts cut from its commits (chunks.json from chunks.py propose)")
    parser.add_argument("--previous", type=Path, metavar="FILE",
                        help="the graphs.json this build replaces (refresh.py): tour steps follow the code they were resolved on")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-manifest", action="store_true", help="do not record this run in review-map.json")
    args = parser.parse_args()
    if not args.pr and not args.chunks:
        parser.error("give at least one --pr or --chunks")

    names = dict(args.name)
    titles = dict(args.title)
    repos = dict(args.repo)
    for item in args.alias:
        if "=" not in item:
            raise SystemExit(f"--alias {item!r}: expected SPEC=PATH or SPEC=PATH@DIR")
    rules = json.loads(args.groups.read_text(encoding="utf-8")) if args.groups else []
    if not args.no_default_groups:
        rules = rules + DEFAULT_GROUPS
    overlay = json.loads(args.overlay.read_text(encoding="utf-8")) if args.overlay else {}
    clusters = read_clusters(overlay)
    tour_specs, tour_warnings = tours.read(overlay)

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
    warnings: list[str] = list(tour_warnings)
    previous_graph = None
    if args.previous and tour_specs:
        try:
            previous_graph = json.loads(args.previous.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            warnings.append(f"--previous {args.previous}: cannot read it ({error}); tour steps take the overlay's lines as they are")
    labels: dict[str, str] = {}
    blobs: dict[str, Blobs] = {}
    merges = Conflicts(warnings)
    for entry in entries:
        key, repo, rng = entry["key"], entry["repo"], entry["range"]
        files = numstat(repo, rng)
        resolved = merges.of(key, repo, rng)
        reader = blobs.setdefault(repo, Blobs(repo))
        resolver = Resolver(repo, tip_of(rng), args.alias, reader)
        base = base_of(repo, rng)
        nodes: dict[str, dict] = {}
        owner: dict[str, str] = {}
        for path in sorted(files):
            added, removed, binary, old = files[path]
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
                lines = added + removed
                if not binary and lines <= TRIVIAL_LINES:
                    node["trivial"] = True
                elif not binary and lines <= IMPORT_ONLY_MAX and base and path.endswith((*JS_EXT, ".py", ".php")):
                    size = reader.size(base, old or path) or 0
                    if size <= BLOB_CAP and len(resolver.source(path).encode("utf-8")) <= BLOB_CAP:
                        before = reader.read(base, old or path) or ""
                        if import_free(path, resolver.source(path)) == import_free(path, before):
                            node["trivial"] = True
            node["added"] += added
            node["removed"] += removed
            owner[path] = nk
            # A merge names the file as it was then: its path at the tip, or before a rename the PR makes.
            shas = set(resolved.get(path, [])) | set(resolved.get(old, []) if old else [])
            if shas:
                node["conflict"] = sorted(shas | set(node.get("conflict", [])), key=merges.rank.__getitem__)
        for nk, node in nodes.items():
            if nk.startswith("#"):
                node["path"] = group_path(node["files"])
                if len(node["files"]) > 1:
                    node["label"] = f"{node['label']} ({len(node['files'])})"
        if repo not in labels:
            labels[repo] = repo_label(repo)
        prs.append({"key": key, "repo": repo, "label": repos.get(key) or repos.get(entry.get("parent", "")) or labels[repo],
                    "range": rng, "tip": tip_of(rng), "nodes": nodes, "owner": owner, "edges": {},
                    "chunk": entry.get("chunk"), "parent": entry.get("parent"),
                    "via": {}, "direct": set(), "resolver": resolver, "counts": {"barrel": 0, "tests": 0}})
    for item in args.alias:
        if all(item in pr["resolver"].missing for pr in prs):
            warnings.append(f"--alias {item!r}: its path (or its @directory) is in no PR's tree at the tip; it resolves nothing")

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

    def add_edge(index: int, frm: str, target: tuple[int, str], kind: str, via: str | None = None) -> None:
        """Record frm -> target; a stronger kind replaces a weaker one. `via` names the unchanged barrels an edge went
        through; an edge found any other way too (a direct import, the overlay) carries none."""
        if (index, frm) == target:
            return
        edges = prs[index]["edges"]
        key = (frm, target)
        if key not in edges or KIND_RANK[kind] > KIND_RANK[edges[key]]:
            edges[key] = kind
            if via is not None:
                prs[index]["via"][key] = via
        if via is None:
            prs[index]["direct"].add(key)
        else:
            prs[index]["via"].setdefault(key, via)

    for index, pr in enumerate(prs):
        resolver = pr["resolver"]
        changed_so_far = set().union(*(set(p["owner"]) for p in prs[: index + 1]))

        def changed(path: str, index: int = index) -> bool:
            return locate(path, index) is not None

        for path, nk in pr["owner"].items():
            if nk.startswith("#") or pr["nodes"][nk].get("unchanged"):
                continue
            if path.endswith(JS_EXT):
                src = resolver.source(path)
                for match in JS_IMPORT.finditer(src):
                    spec = match.group("a") or match.group("b") or match.group("c")
                    type_only, wanted = clause_names(match.group("clause")) if match.group("a") else (False, None)
                    target = resolver.js(path, spec)
                    if not target:
                        continue
                    found = locate(target, index)
                    if found is not None:
                        add_edge(index, nk, found, "type" if type_only else "import")
                        continue
                    for hit, through_type, chain in resolver.through(target, wanted, changed):
                        add_edge(index, nk, locate(hit, index), "type" if type_only or through_type else "import",
                                 via=" > ".join(chain))
            elif path.endswith(".py"):
                src = resolver.source(path)
                for match in PY_IMPORT.finditer(src):
                    modules = [match.group(1)] if match.group(1) else [m.strip() for m in match.group(2).split(",")]
                    for module in modules:
                        for target in resolver.python(path, module):
                            found = locate(target, index)
                            if found is not None:
                                add_edge(index, nk, found, "import")
            elif path.endswith(".php"):
                src = resolver.source(path)
                for match in PHP_USE.finditer(src):
                    for target in php_targets(match.group(1), changed_so_far):
                        found = locate(target, index)
                        if found is not None:
                            add_edge(index, nk, found, "import")

        own = pr["nodes"]
        subjects: dict[str, list[str]] = {}
        for nk, node in own.items():
            if not nk.startswith("#") and node["layer"] != "test":
                subjects.setdefault(stem(nk), []).append(nk)
        candidates = sorted(nk for nk, node in own.items()
                            if not nk.startswith("#") and is_core(node) and not node.get("unchanged"))
        for nk in sorted(own):
            node = own[nk]
            if nk.startswith("#") or node["layer"] != "test":
                continue
            name = test_stem(nk)
            if name == stem(nk) and TEST_SUPPORT.search(nk):
                continue  # test support (fixtures/index.ts) without a test marker tests no file of its name
            found = subjects.get(name, []) if name else []
            if found:
                best = max(found, key=lambda c: len(posixpath.commonpath([c, nk])))
                add_edge(index, nk, (index, best), "test")
            elif name:
                guess = guess_subject(nk, subjects, candidates)
                if guess is not None:
                    add_edge(index, nk, (index, guess), "test")
                    pr["counts"]["tests"] += 1

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
            if "generated" in fields:
                if not isinstance(fields["generated"], bool):
                    raise SystemExit(f"overlay nodes {text!r}: generated must be true or false")
                node["generated"] = fields["generated"]
            if "cluster" in fields:
                if not isinstance(fields["cluster"], str) or fields["cluster"] not in clusters:
                    raise SystemExit(f"overlay nodes {text!r}: unknown cluster {fields['cluster']!r}; define it under clusters")
                node["cluster"] = fields["cluster"]
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
        for nk in sorted(nk for nk, node in nodes.items() if "cluster" in node and (node.get("hub") or node["layer"] in LATE)):
            node = nodes[nk]
            where = "a shared dependency (the viewer's shared area; set hub false to keep it in an area)" if node.get("hub") \
                else f"{node['layer']} (the viewer's docs, config, and i18n area)"
            warnings.append(f"{pr['key']}: overlay cluster {node.pop('cluster')!r} ignored for {node['path']}: it is {where}")

        def on_cycle(paths: list[str], key: str = pr["key"]) -> None:
            shown = ", ".join(paths[:6]) + (f" and {len(paths) - 6} more" if len(paths) > 6 else "")
            warnings.append(f"{key}: import cycle among {len(paths)} files ({shown}); read in flow order. "
                            "Confirm it, or drop a wrong edge with dropEdges")

        order = reading_order(nodes, same_pr, on_cycle)
        for position, nk in enumerate(order, 1):
            ids[(index, nk)] = f"{pr['key']}{position}"
            nodes[nk]["order"] = position
        pr["order"] = order
        pr["readFrom"] = read_from(nodes, same_pr)

    for pr in prs:
        for path in sorted(pr["resolver"].unreadable):
            warnings.append(f"{pr['key']}: {path} is not JSON (comments and trailing commas allowed); its paths and baseUrl are not used")
        for path, size in sorted(pr["resolver"].skipped.items()):
            warnings.append(f"{pr['key']}: {path} is {size / (1 << 20):.1f} MB, over the 1 MB read for configs and re-exports; skipped")
    for reader in blobs.values():
        reader.close()
    tour_out, tour_moves = resolve_tours(tour_specs, prs, ids, index_of, parent_parts, previous_graph, warnings)

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
        entry["readFrom"], entry["readFromWhy"] = pr["readFrom"]
        used = {node["cluster"] for node in nodes.values() if "cluster" in node}
        if used:
            entry["clusters"] = sorted((clusters[cid] for cid in used), key=lambda c: (c["order"], c["id"]))
        entry.update({"nodes": [], "edges": []})
        for nk in pr["order"]:
            node = nodes[nk]
            label = node["label"]
            if not nk.startswith("#") and (counts[label] > 1 or GENERIC_NAMES.match(label)) and "/" in node["path"]:
                label = "/".join(node["path"].split("/")[-2:])
            item = {"id": ids[(index, nk)], "label": label, "path": node["path"], "layer": node["layer"], "bucket": bucket(node),
                    "role": node["role"], "added": node["added"], "removed": node["removed"], "order": node["order"]}
            if nk.startswith("#"):
                item["files"] = node["files"]
            if node.get("note"):
                item["note"] = node["note"]
            if node.get("unchanged"):
                item["unchanged"] = True
            if node.get("trivial"):
                item["trivial"] = True
            if node.get("hub"):
                item["hub"] = True
            if "cluster" in node:
                item["cluster"] = node["cluster"]
            if node.get("conflict"):
                item["conflict"] = node["conflict"]
            if not item["role"]:
                missing_roles += 1
            entry["nodes"].append(item)
        for (frm, target), kind in sorted(pr["edges"].items(), key=lambda kv: (ids[(index, kv[0][0])], ids[kv[0][1]])):
            edge = {"from": ids[(index, frm)], "to": ids[target], "kind": kind, "external": target[0] != index}
            if (frm, target) in pr["via"] and (frm, target) not in pr["direct"]:
                edge["via"] = pr["via"][(frm, target)]
                pr["counts"]["barrel"] += 1
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
    if tour_out:
        out["tours"] = tour_out

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
        core = [node for node in entry["nodes"] if node["layer"] != "test" and node["layer"] not in LATE]
        areas = {c["id"]: sum(1 for node in core if node.get("cluster") == c["id"]) for c in entry.get("clusters", [])}
        pr = prs[index]
        found = [f"{pr['counts']['barrel']} through barrels" if pr["counts"]["barrel"] else "",
                 f"{pr['counts']['tests']} tests matched by nearby names" if pr["counts"]["tests"] else ""]
        hits = pr["resolver"].ts_hits
        if hits:
            found.append("tsconfig paths: " + ", ".join(f"{path} {n}" for path, n in sorted(hits.items())))
        why = entry["readFromWhy"]
        print(f"{entry['key']}: {len(entry['nodes'])} nodes, {len(entry['edges'])} edges"
              + (f" ({'; '.join(x for x in found if x)})" if any(found) else "")
              + (f"; shared dependencies: {', '.join(hubs)}" if hubs else "")
              + (f"; areas: {', '.join(f'{cid} {n}' for cid, n in areas.items())}" if areas else "")
              + f"; reads from {'dependencies' if entry['readFrom'] == 'dependencies' else 'the entry point'}"
              + (f" (too few entry points, {why['entries']}, to recommend another order)" if why["reason"] == "few" else
                 f" ({why['light']} of {why['entries']} entry points light: median {why['entryLines']} changed lines"
                 f" over {why['baseLines']} underneath)"))
        resolved = [f"{node['path']} ({', '.join(node['conflict'])})" for node in entry["nodes"] if node.get("conflict")]
        if resolved:
            print(f"hint: PR {entry['key']}: {len(resolved)} files changed by hand in merge commits (conflict resolutions; "
                  "check each and say in its note what it kept): " + ", ".join(resolved[:5]) + (", …" if len(resolved) > 5 else ""))
        loose = [node["path"] for node in core if not node.get("hub") and "cluster" not in node]
        if areas and loose:
            print(f"hint: PR {entry['key']}: {len(loose)} core files have no area, so the map groups them by folder: "
                  + ", ".join(loose[:5]) + (", …" if len(loose) > 5 else ""))
        elif not areas and len(core) > OVERVIEW_CORE:
            print(f"hint: PR {entry['key']} has {len(core)} core files; above {OVERVIEW_CORE} its map opens on an overview of areas: "
                  "give 8-12 of them by feature or flow in the overlay (clusters, nodes.<ref>.cluster), else it groups by folder")
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
    if tour_out:
        print("tours: " + ", ".join(f"{tour['id']} {len(tour['steps'])} steps" for tour in tour_out))
    for line in tour_moves:
        print(line)
    for warning in warnings:
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
