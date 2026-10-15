# Review-map data: graphs.json, overlay.json, diffs.json

`scripts/build_graph.py` writes `graphs.json` from git plus `overlay.json`;
`scripts/gen_diffs.py` writes `diffs.json` from `graphs.json`; `scripts/assemble.py`
embeds both. Hand-edit only the overlay, then re-run the scripts, so a branch
that moves never loses authored content.

## graphs.json

```json
{
  "prs": [
    {
      "key": "S",
      "name": "S #12680",
      "title": "Service vertical: facility services route",
      "repo": "acme/web",
      "base": "1a2b3c4",
      "tip": "c9e7133",
      "color": "var(--pal-2)",
      "nodes": [
        {"id": "S1", "label": "services.schema.ts", "path": "libs/x/contract/services.schema.ts",
         "layer": "contract", "role": "Zod schema of the response", "added": 79, "removed": 0,
         "order": 1, "note": "Optional <code>doctorName</code>, so older callers keep working."},
        {"id": "S26", "label": "docs (4)", "path": "libs/x/docs/**", "layer": "docs", "role": "",
         "added": 601, "removed": 0, "order": 26, "files": ["libs/x/docs/a.md", "…"]},
        {"id": "S27", "label": "ApiController.php (unchanged)", "path": "src/ApiController.php",
         "layer": "rest", "role": "Base controller", "added": 0, "removed": 0, "order": 27,
         "unchanged": true}
      ],
      "edges": [
        {"from": "S3", "to": "S1", "kind": "import", "external": false},
        {"from": "S9", "to": "M4", "kind": "http", "external": true}
      ]
    }
  ],
  "crossEdges": [{"from": "S9", "to": "M4", "kind": "http"}]
}
```

PR fields:

- `key` — letters, digits, `_`, `-`; also the narrative class suffix (`c-S`).
- `name` — short tab label (`S #12680`). `title` is the tab tooltip.
- `repo` — repository label (`owner/name`) that copied review notes name with the
  PR. `build_graph.py` takes `--repo KEY owner/name`, else reads it from the
  `origin` remote URL path (never its host, credentials, query, or fragment), else
  uses the directory name.
- `base`, `tip` — short SHAs of the two versions the PR's diff compares (for
  `A...B` the base is the merge base), written by `build_graph.py` and left out
  when git cannot resolve them. Copied review notes name them per PR.
- `color` — optional CSS colour; by default PR *n* gets palette slot `--pal-n`
  (8 slots, light and dark variants).
- List PRs in merge order. Edges may point only to the same or an earlier PR.

Node fields:

| Field | Meaning |
| --- | --- |
| `id` | Unique across all PRs. Convention: `KEY` + dependency order (`S1`). Shown on cross-PR ghost nodes. |
| `label` | Short name on the node: basename, or the last two path segments when ambiguous (`api/index.ts`). |
| `path` | Repo path; for a group, a representative glob (`web/translations/*.json`). |
| `layer` | One of the layers below. Drives colour, legend, and reading order. |
| `role` | One line, at most ~60 characters, report language. Tooltip and detail panel. |
| `added`, `removed` | Line counts from `git diff --numstat`. |
| `order` | Integer, dependency-first: a node's dependencies have lower numbers. |
| `files` | Group nodes only: every path the node stands for. `gen_diffs.py` maps diffs with it. |
| `match` | Optional globs for hand-written graphs; `gen_diffs.py` also accepts a glob-like `path`. |
| `note` | Optional per-file reviewer note, trusted HTML, report language. Shown in the detail panel. |
| `unchanged` | Reference node for a file the PR does not change (base class, router). No diff. |

Edge fields: `from` (a node of this PR), `to` (any node of this or an earlier PR),
`kind`, and `external` (`true` when `to` is in another PR; listed in that PR's
colour in the header group of the step list and in the map's left band). An edge
reads "`from` depends on `to`". The viewer derives the reverse direction ("used by
PR B") from every PR's edges, so a later PR's dependency needs no extra field.

### Layers

`contract` (schemas, DTOs, API types) · `domain` · `data` (migrations, DB schema) ·
`logic` (use cases, queries, pure functions) · `infra` (providers, repositories,
HTTP clients) · `rest` (controllers, handlers, routes) · `ui` · `wiring` (entry
points, DI, routing config, barrels) · `test` · `config` (package manifests,
lockfiles, deploy config) · `i18n` · `docs`.

Tests are indented under their subject in the step list and drawn dashed on the
map. `docs`, `config`, and `i18n` always read last.

### Edge kinds

| Kind | When |
| --- | --- |
| `import` | Real import, `use`, `require`, or `from … import`, resolved to a changed file. |
| `test` | Test → the file it tests. Decides where the test sits in the reading order. |
| `di` | DI binding or service definition (Symfony `services.yml`, Nest module, container registration). |
| `route` | Routing config → controller/handler. |
| `config` | Code → the config, env, or i18n it reads; catalog → translations. |
| `http` | A call across a service boundary (client → handler in another PR or repo). Drawn dashed. |

### Reading order

`order` is dependency-first ("Od zależności" / "From dependencies"). build_graph.py
splits the core nodes (not tests, not `docs`/`config`/`i18n`) into connected ones,
which share a non-`test` edge with another core node of the same PR, and isolated
ones; edges to tests, to late nodes, and to other PRs do not connect a node. It
topologically sorts the connected nodes. When several are ready to be read, the
flow rule picks the one that shares such an edge (either direction) with the most
recently placed node, so a run like types → service → controller stays together
instead of interleaving with unrelated files; remaining ties break by layer
(`contract < domain = data < logic < infra < rest < ui < wiring`), then path. It
appends the isolated nodes by layer and path, inserts each test right after the core
file it tests (its `test` edge first, else its other edges; the last such file
wins; a test with no core target goes after all core nodes), and puts `docs`,
`config`, `i18n` last. The viewer recomputes the order with the same rule, using
the stored `order` as its last tie-break (for build_graph.py output that encodes
the layer and path tie-break), so it reproduces the stored order exactly; on a
hand-written graph the stored order decides only between equally connected files.
The viewer's default mode, "Od punktu wejścia" / "From the entry point", reverses
only the connected part: isolated nodes, the placement of tests, and the late
layers stay as in the stored order, so an unrelated file (a collapsed import
change, say) never opens either mode. Reversing keeps every adjacent pair
adjacent, so the flow rule holds in both modes. The viewer numbers the steps on
the whole PR, tests included; the test filter hides tests without renumbering the
rest, and prev/next skip hidden steps. Do not author a second reading order
anywhere else.

A file is a test when its path is under a test directory (`__tests__`, `__mocks__`,
`test`, `tests`, `e2e`, `spec`) or its name carries its language's marker as its own
segment: `.test.`/`.spec.`/`.e2e.` anywhere; a `-test`/`_test`/`-spec`/`_spec`/`-e2e`/
`_e2e` suffix in JS/TS, Vue, and Svelte; `_spec.rb`; `_test` in Go, Python, Ruby, and
Elixir; `test_*.py`/`test_*.rb`; `*Test(s)` in PHP, Java, Kotlin, C#, or Swift; or
`conftest.py`. `test-utils.ts`, `contest.ts`, `api-spec.yaml`, `pod_spec.go`,
`openapi_spec.py`, and `build_spec.rs` are not tests. The JS suffix also catches a
feature file such as `ab-test.tsx`; set its `layer` in the overlay.
Its subject is the changed file whose name equals the test's name with those
markers removed (`mobile-state-panel-test.tsx` → `mobile-state-panel.tsx`), the
nearest by path when several match.

## overlay.json

Everything git cannot tell the script. References are `KEY:path` (a changed file
or an individual node path) or `KEY:#group` (`#lockfiles`, `#catalogs`,
`#translations`, `#deploy`, `#docs`, or a custom group id).

```json
{
  "nodes": {
    "M:src/Api/Controller/GetServicesController.php": {
      "role": "GET endpoint; 404 for an unknown facility",
      "note": "Forces <code>should_check_require_prices_gate=false</code>."
    },
    "B:#translations": {"role": "16 keys × 14 locales"},
    "A:apps/api/src/app.ts": {"layer": "wiring"}
  },
  "extraNodes": [
    {"pr": "M", "path": "src/Api/Controller/ApiController.php", "label": "ApiController.php (unchanged)",
     "layer": "rest", "role": "Base API controller"}
  ],
  "edges": [
    {"from": "M:src/Api/Controller/GetServicesController.php", "to": "M:src/Module/Resources/config/services.yml", "kind": "di"},
    {"from": "M:src/Api/Resources/config/routing.yml", "to": "M:src/Api/Controller/GetServicesController.php", "kind": "route"},
    {"from": "S:libs/x/infra/monolith.client.ts", "to": "M:src/Api/Controller/GetServicesController.php", "kind": "http"},
    {"from": "M:src/Api/Controller/GetServicesController.php", "to": "M:src/Api/Controller/ApiController.php", "kind": "import"}
  ],
  "dropEdges": [{"from": "A:apps/api/src/app.ts", "to": "A:#docs"}]
}
```

`nodes` may set `role`, `note`, `layer`, `label`. An `extraNodes` entry is an
unchanged reference file (`unchanged: true` is implied). Overlay edges replace a
weaker edge between the same nodes (`test > route > di > http > config > import`).

## groups.json (optional)

Extra grouping rules, checked before the defaults (lockfiles, translation
catalogs, translations, deploy config, docs). The first matching rule wins.

```json
[
  {"id": "cycle", "label": "cycle docs", "layer": "docs", "pattern": "/cycles/"},
  {"pattern": "^skills/[^/]+/SKILL\\.md$", "group": false, "layer": "logic"}
]
```

`pattern` is a Python regex searched in the path. `"group": false` keeps each
matching file as its own node (with the given layer) instead of collapsing it.
`--no-default-groups` drops the defaults.

## diffs.json

```json
{
  "S1": [{"path": "libs/x/contract/services.schema.ts", "diff": "--- /dev/null\n+++ b/…\n@@ -0,0 +1,79 @@\n+…"}],
  "B21": [{"path": "web/translations/pl-PL.json", "diff": "…"}, {"path": "web/translations/en-US.json", "diff": "…"}],
  "A27": [{"path": "pnpm-lock.yaml", "diff": "…", "truncated": 5120}]
}
```

Keys are node ids; each value lists that node's files with a unified diff whose
`diff --git`, `index`, mode, and rename headers are stripped. `truncated` is the
full line count of a diff cut at `--max-lines`; `binary: true` marks a binary
file. The viewer opens files lazily and collapses a file over 400 lines, and every
file after the first when a node has more than four.
