# Review-map data: graphs.json, overlay.json, diffs.json, review-map.json

`scripts/build_graph.py` writes `graphs.json` from git plus `overlay.json`;
`scripts/gen_diffs.py` writes `diffs.json` from `graphs.json`; `scripts/assemble.py`
embeds both. Hand-edit only the overlay, then re-run the scripts, so a branch
that moves never loses authored content: `scripts/refresh.py` replays all three
from `review-map.json` (below).

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
         "layer": "contract", "bucket": "logic", "role": "Zod schema of the response", "added": 79,
         "removed": 0, "order": 1, "note": "Optional <code>doctorName</code>, so older callers keep working.",
         "conflict": [{"sha": "4d5e6f7", "kind": "merged", "lines": 12}]},
        {"id": "S26", "label": "docs (4)", "path": "libs/x/docs/**", "layer": "docs", "bucket": "docs",
         "role": "", "added": 601, "removed": 0, "order": 26, "files": ["libs/x/docs/a.md", "…"]},
        {"id": "S27", "label": "ApiController.php (unchanged)", "path": "src/ApiController.php",
         "layer": "rest", "bucket": "logic", "role": "Base controller", "added": 0, "removed": 0,
         "order": 27, "unchanged": true}
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

- `key` — letters, digits, `_`, `-`, not starting with `-`; also the narrative class suffix (`c-S`).
- `name` — short tab label (`S #12680`). `title` is the tab tooltip.
- `repo` — repository label (`owner/name`) that copied review notes name with the
  PR. `build_graph.py` takes `--repo KEY owner/name`, else reads it from the
  `origin` remote URL path (never its host, credentials, query, or fragment), else
  uses the directory name.
- `base`, `tip` — short SHAs of the two versions the PR's diff compares (for
  `A...B` the base is the merge base), written by `build_graph.py` and left out
  when git cannot resolve them. Copied review notes name them per PR.
- `color` — optional: `var(--pal-1)` … `var(--pal-8)`, a hex colour, or a colour
  name (anything else is refused, since it lands in CSS); by default PR *n* gets
  palette slot `--pal-n` (8 slots, light and dark variants).
- List PRs in merge order. Edges may point only to the same or an earlier PR.
- `readFrom`, `readFromWhy` — the reading mode build_graph.py recommends for the PR,
  `"dependencies"` or `"entry"`, and the numbers behind it, `{"entries": 31, "light":
  25, "entryLines": 10, "baseLines": 60, "reason": "light"}` (see Reading order below;
  `reason` is `"few"` below 3 entry points, else `"light"` or `"heavy"`). The viewer
  opens the PR in that mode until the reader picks one for it, and its note says why.
- `clusters` — the areas the PR's nodes use, from the overlay (see Areas below):
  `[{"id": "auth", "label": "Sign-in", "order": 1, "depth": "read"}, {"id": "copy",
  "label": "Copy", "order": 2, "depth": "tool", "why": "i18n key parity test"}]`, by
  order; absent without them. `depth` and `why` appear only where the overlay sets them.
- `chunk` — only on a part of a PR split by its commits (`--chunks`,
  `references/chunks.md`): `{"of": "M", "index": 2, "count": 5, "from": "<sha>",
  "to": "<sha>", "commits": 4, "subjects": ["first five", "…"], "label": "web"}`, with
  full SHAs; the part's diff is `from..to`. The parts of one parent follow each other
  in the PR list, numbered 1..n, each starting where the one before ends, and their
  keys end in a letter (`Ma`, `Mb`), so node ids cannot collide. A part's default
  `name` is `#251 2/5 web`.

With parts, the top level also holds `"parents": [{"key": "M", "name": "#251",
"title": "…", "repo": "acme/web", "base": "1a2b3c4", "tip": "9f8e7d6", "parts": ["Ma",
"Mb", …]}]`: the whole PR, whose key is no PR of the graph (overlay references and
migrated notes use it), `base` the first part's start, `tip` the last part's end.
`assemble.py` and `validate.py` refuse a broken chain. A graph without `parents` and
`chunk` renders exactly as before.

With tours (see Tours below) the top level also holds `"tours": [{"id": "apple-web",
"name": "…", "steps": [{"node": "Mc4", "path": "app/…/AppleController.php", "side": "new",
"a": 12, "b": 30, "note": "…", "ref": "M:app/…/AppleController.php", "lines": "12-30",
"code": ["…"]}]}]`; a graph without them has no picker.

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
| `note` | Optional per-file reviewer note, report language. HTML limited to `code`, `b`/`strong`, `i`/`em`, `br`, `kbd`, `sub`, `sup`, and links to `https://`/`#` addresses; other tags keep only their text and lose their attributes, `script`/`style` are dropped. Shown in the detail panel. |
| `unchanged` | Reference node for a file the PR does not change (base class, router). No diff. |
| `hub` | `true` on a shared dependency (see below), written by `build_graph.py`; absent otherwise. The viewer reads it and does not detect hubs itself. |
| `trivial` | `true` on a file whose change is at most 2 lines, or only its import or re-export lines (JS/TS, Python, PHP; checked up to 60 changed lines and 1 MB, both versions with their imports and white space removed; `import.meta` and `import(` are code, and a PHP `use` counts only before the first class, interface, trait, enum, or function), written by `build_graph.py`. Such a hub reads after the other hubs; such an entry point is light (Reading order). |
| `cluster` | The id of the node's area from the overlay, one of its PR's `clusters` (see Areas below); absent otherwise. |
| `bucket` | The kind of change the review plan counts the node's lines under, on every node build_graph.py writes: `generated` when every file is a lockfile (the `#lockfiles` names), a test snapshot (`*.snap`, anything under `__snapshots__/`), or a minified file (`*.min.js`, `*.min.css`), or the overlay sets `generated: true`; else `test`, `i18n`, `docs`, or `config` for a node of that layer; else `logic` (every other layer). Overlay `generated: false` keeps a node in its layer's bucket. validate.py rejects any other value. |
| `conflict` | One entry per merge commit of the PR whose recorded result for one of the node's files differs from what git merges on its own (`git show --remerge-diff`): a conflict resolved by hand, or an edit made in the merge. `{"sha": "4d5e6f7", "kind": "merged", "lines": 12}`: the merge's short (7-character) SHA; `kind` `"picked"` when the merge's version of every such file is byte-identical to one parent's (one side taken), else `"merged"` (combined by hand); `lines` the lines the re-merge diff changes for the node's files. Oldest first; absent when there is none (see Merge resolutions below). An older build wrote bare SHAs; validate.py and the viewer still take them (as merged). |

Edge fields: `from` (a node of this PR), `to` (any node of this or an earlier PR),
`kind`, `external` (`true` when `to` is in another PR; listed in that PR's
colour in the header group of the step list and in the map's left band), and `via`
on an edge found only through barrels (below): the files it went through,
`"packages/core/src/index.ts > packages/core/src/nested/index.ts"`, shown in the
neighbourhood's tooltip. An edge
reads "`from` depends on `to`". The viewer derives the reverse direction ("used by
PR B") from every PR's edges, so a later PR's dependency needs no extra field.

### Layers

`contract` (schemas, DTOs, API types) · `domain` · `data` (migrations, DB schema) ·
`logic` (use cases, queries, pure functions) · `infra` (providers, repositories,
HTTP clients) · `rest` (controllers, handlers, routes) · `ui` · `wiring` (entry
points, DI, routing config, barrels) · `test` · `config` (package manifests,
lockfiles, deploy config) · `i18n` · `docs`.

The first guess matches whole path segments (a directory name) and file-name
suffixes, never a word inside a name, in this order: tests and test support (test
directories, and `fixtures`, `__fixtures__`, `testdata`, `mocks`, `stubs`, `fakes`,
`test-utils`/`test-helpers`/`test-support` directories), DI/routing YAML, config,
data (`migrations`, `db`, `prisma`, `seeds`, `.sql`), then `ui` for a component,
stylesheet, or template file (`.tsx`, `.jsx`, `.vue`, `.svelte`, `.astro`, `.css`,
`.html`, …) before any directory word can claim it, contract (`contracts`, `schemas`,
`dto` directories; `schema.ts`, `-contracts.ts`, `schemas.py`), domain, infra (`infra`,
`adapters`, `repositories`, `gateways`, `persistence`, `integrations` directories;
`-client.ts`, `.repository.ts`, `StripeClient.php`), rest (`controllers`, `handlers`,
`routes`, … directories; `.controller.ts`, `Controller.php`), wiring (`index`, `main`,
`app`, `bootstrap`, … files), else logic. So `resources/js/client/pages/x.tsx` is `ui`,
`client-error-text.ts` is `logic`, and `ui/fixtures/x.tsx` is `test`. A `client/` or
`providers/` directory names no layer: a front-end app and React providers live in them.

Tests are indented under their subject in the step list and drawn dashed on the
map. `docs`, `config`, and `i18n` always read last.

### Edge kinds

| Kind | When |
| --- | --- |
| `import` | Real import, `use`, `require`, or `from … import`, resolved to a changed file (through a barrel, changed or not, to the file that defines the name, with `via`). |
| `type` | A type-only import: `import type`, `import { type A, type B }` (every specifier a type), `export type … from`, or a barrel path with an `export type` on it. Orders like `import` unless it closes a cycle; drawn dotted and lighter. |
| `test` | Test → the file it tests. Decides where the test sits in the reading order. |
| `di` | DI binding or service definition (Symfony `services.yml`, Nest module, container registration). |
| `route` | Routing config → controller/handler. |
| `config` | Code → the config, env, or i18n it reads; catalog → translations. |
| `http` | A call across a service boundary (client → handler in another PR or repo). Drawn dashed. |

### Imports the script resolves

A relative specifier resolves against the importer (`.js` also finds `.ts`); any
other one tries, in order, and takes the first that names a file in the tree at the
tip: a scoped `--alias SPEC=PATH@DIR` whose DIR holds the importer (the longest DIR
first), the `compilerOptions.paths` of the `tsconfig.json` or `jsconfig.json` nearest
to the importer (JSON with a BOM, comments, and trailing commas; one that is not, or is
over 1 MB, is reported and not used; its in-repo `extends` followed; the longest
matching prefix first; targets relative to `baseUrl` when one is set, else to the file
that sets `paths`) and then its `baseUrl`, and last the unscoped `--alias SPEC=PATH`.
`SPEC` is an exact specifier or a prefix ending in `/`. A PATH that is itself in the
tree keeps an `@` in it (`src/@core/`); a trailing `@` also marks an alias unscoped. An
alias whose path or directory is in no PR's tree is reported. The summary line counts
the imports each tsconfig resolved.

An import of a file that re-exports (`export * from`, `export { X as Y } from`, `export
* as ns from`, `export type … from`) is followed whether or not the PR changes that
barrel: its re-export targets are resolved from it, at most 4 files deep and never one
file twice (re-export cycles end), to the files that define what the import takes; the
edge goes to each of them the PR changes (or an earlier PR, or an `extraNodes`
reference) with `via`, the barrels it went through. With named imports only the
re-exports of those names are followed: an `export { … }` that lists one, an `export *
as` with that name, and an `export *` whose target declares one of them (or whose
exports cannot be read: CommonJS, destructuring). `import * as`, side-effect imports,
`require`, and dynamic imports follow everything. The importer → barrel edge stays only
for names the barrel declares itself (or, for `import * as`, when it declares anything)
and names found nowhere, so a changed barrel no longer stands in for the files behind
it (and no longer becomes a shared dependency through them). A barrel's own `export … from`
of a changed file is its edge to that file. An edge found directly too carries no `via`.

### Shared dependencies

A file that most of a PR depends on (an i18n entry point, a failure-text helper, a
`common.py`) would put an arc from almost every row into its own and bind every file
to every other one in the reading order. `build_graph.py` flags such a file `hub`.
Counting only core nodes (not tests, not `docs`/`config`/`i18n`) and their non-`test`
edges within the PR, with `linked` the core nodes that share such an edge with another
core node: a node is a hub when at least `max(4, ceil(1.25 × sqrt(linked)))` other
core nodes depend on it (10 linked files: 4; 25: 7; 105: 13; 400: 25). The threshold
grows with the square root, not a share: a quarter asked for 27 of 105 linked files and
missed the error-text helpers fifteen screens use. Then a core node that only hubs
depend on joins them, repeated until nothing changes, so a hub's private helper is read
with it. The overlay's `"hub": true` or `false` on a node overrides the rule (`false`
also keeps the node out of the second step); on a test or late node it is ignored with a
warning. A file with fewer than 4 dependents is never a hub, so most small PRs have
none. A `trivial` change (above) can be a hub, since its many links would otherwise bind
its users together, but it reads after the hubs with something to read: a one-line
provider change that 28 files use is no first step.

The viewer pins the hubs, each with its tests indented under it, in a "Wspólne
zależności" / "Shared dependencies" group at the top of the step list, numbered as
the first steps in both reading modes. The arc lane draws an arc into a hub only
while that hub is the selected or hovered file; another selected file that uses hubs
gets a "◆" chip on its row and a blue ring on the hubs' dots instead, and its
neighbourhood lists them on one "+ shared:" line instead of as dependencies. The map
puts the hubs in a band on top, joined to each other by arcs above them, and shows an
edge into the band only for the selected file.

### Reading order

`order` is dependency-first ("Od zależności" / "From dependencies"). build_graph.py
reads the hubs first (those with something to read, then the `trivial` or unchanged
ones), then the other core nodes, and an edge between two of these parts counts in
neither: a node linked only to hubs reads with the isolated ones, and hubs do not pull
their users together. Within each part it splits
the nodes into connected ones, which share a non-`test` edge with another node of the
part, and isolated ones; edges to tests, to late nodes, and to other PRs do not
connect a node. It topologically sorts the connected nodes. A `type` edge orders its
files like an import unless it closes a cycle: type edges inside a strongly connected
component of all these edges are left out of the ordering (they still connect their
files), so a cycle closed only by a type-only import (transport ↔ refresh coordinator)
neither warns nor reorders anything. Each strongly connected component left, a real
import cycle, prints one warning naming only its files ("import cycle among 2 files
(…)"); when such a cycle blocks every file, the candidates are the files of a cycle that
waits on nothing outside itself, so breaking it never lets an unrelated or a waiting
file jump ahead. When several are ready to be read, the
flow rule picks the one that shares such an edge (either direction) with the most
recently placed node, so a run like types → service → controller stays together
instead of interleaving with unrelated files; remaining ties break by layer
(`contract < domain = data < logic < infra < rest < ui < wiring`), then path. It
appends the part's isolated nodes by layer and path, inserts each test right after the core
file it tests (its `test` edge first, else its other edges; the last such file
wins; a test with no core target goes after all core nodes), and puts `docs`,
`config`, `i18n` last. The viewer recomputes the order with the same rule, using
the stored `order` as its last tie-break (for build_graph.py output that encodes
the layer and path tie-break), so it reproduces the stored order exactly; on a
hand-written graph the stored order decides only between equally connected files.
The viewer opens each PR in the mode build_graph.py recommends (`readFrom`). Entry
points are the connected core nodes outside the hubs that no other such node depends
on, the files "from the entry point" opens with. One is light when it is `trivial` or
unchanged, or when its change (added + removed lines) is at most a third of the largest
change among the core files it depends on, directly or through others, hubs included.
`readFrom` is `"dependencies"` when there are at least 3 entry points and more than half
are light (a PR that adapts many callers to a change underneath reads best from that
change), else `"entry"`. A note under the order buttons says why and marks the
recommended button; a pick of the other mode is kept per PR (localStorage `omodes`,
`{prKey: "top"|"bottom"}`) and dropped when the reader picks the recommended one again,
so a rebuilt PR follows its new recommendation; a narrative button's `data-order` picks
one for the visit only. (An earlier report-wide `omode` key is not read.) "Od punktu
wejścia" / "From the entry point" reverses only the connected nodes of each part: the hubs still come first (read the shared
pieces before the files that use them), and isolated nodes, the placement of tests,
and the late layers stay as in the stored order, so an unrelated file (a collapsed
import change, say) never opens either mode. Reversing keeps every adjacent pair
adjacent, so the flow rule holds in both modes. The viewer numbers the steps on
the whole PR, tests included; the test filter hides tests without renumbering the
rest, and prev/next skip hidden steps. "Grupuj według folderów" / "Group by folder"
(off by default, kept in localStorage) splits the rows after the hub group into
collapsible sections by folder (a test goes with its subject's folder), keeps
reading order inside each, orders the sections by their first step, and leaves the
step numbers and prev/next as they are. "Grupuj według obszarów" / "Group by area"
(off by default, kept under `lgroup`; it and the folder grouping exclude each other)
does the same with one section per area (below). Do not author a second reading order
anywhere else.

A file is a test when its path is under a test directory (`__tests__`, `__mocks__`,
`test`, `tests`, `e2e`, `spec`) or its name carries its language's marker as its own
segment: `.test.`/`.spec.`/`.e2e.` anywhere; a `-test`/`_test`/`-spec`/`_spec`/`-e2e`/
`_e2e` suffix in JS/TS, Vue, and Svelte; Cypress `.cy.` in JS/TS; `_spec.rb`; `_test` in
Go, Python, Ruby, Elixir, and C/C++ (`.c`, `.cc`, `.cpp`, `.cxx`); `test_*` in Python,
Ruby, and C/C++; `*Test(s)` in PHP, Java, Kotlin, Scala, Groovy, C#, or Swift; `*Spec`
in Kotlin, Scala, and Groovy; failsafe `*IT`/`*ITCase` in Java and Kotlin; Django's
`tests.py`; or `conftest.py`. A `Spec` or `IT` suffix counts only after a lowercase
letter or digit (`OrderSpec.kt`, `UserRepositoryIT.java`). `test-utils.ts`,
`contest.ts`, `api-spec.yaml`, `pod_spec.go`, `openapi_spec.py`, `build_spec.rs`,
`Inspect.kt`, `SpecRunner.kt`, `Spec.kt`, `HotelSuite.kt`, `ITService.java`,
`Commit.java`, `latest.cc`, and `testing.c` are not tests; `*Suite` counts only under
a test directory, since domain names end in it too. The JS suffix also catches a
feature file such as `ab-test.tsx`, and the Kotlin one a data class such as
`PodSpec.kt`; set their `layer` in the overlay.
Its subject is the changed file whose name equals the test's name with those
markers removed (`mobile-state-panel-test.tsx` → `mobile-state-panel.tsx`,
`login.cy.ts` → `login.ts`, `PaymentITCase.java` → `Payment.java`), the nearest by
path when several match. Django's `tests.py` has no name match; its imports place it.
A file under a test directory named like its subject (`__tests__/utils.ts`, Django's
`tests/models.py`) matches it so too; test support (a file under `fixtures`, `mocks`,
`stubs`, `fakes`, `testdata`, or `test-utils` without a test marker in its name) tests
no file of its name and gets no subject. A test with no such match looks for one
subject near it, among the changed core
files under its root (the path above its last test directory, else its own directory):
first its name without leading area words (words of its directories, or `mobile`,
`web`, `test`, `spec`, `e2e`, `unit`, `integration`) matched exactly
(`apps/mobile/__tests__/mobile-transport-test.ts` → `…/runtime/transport.ts`),
then word overlap: a file all of whose name words are in the test's name (camelCase
split, digits dropped, a plural `s` removed), scored by the test's other non-area words
its name or its directories below the root share; the best score, at least 2, held by
exactly one file wins (`mobile-auth-bootstrap-test` → `auth/bootstrap.ts`,
`task-detail-mutations-test` → `details/task-detail.tsx`;
`routine-agenda-detail-mutations-test` with two such files gets none).

### Merge resolutions

A conflict resolved by hand in a merge commit is code no commit of its own shows, so it
is easy to miss. build_graph.py lists the PR's merge commits (`git rev-list --merges
--parents` over the range `A..B`, for `A...B` too; the newest 50, with a warning above
that), runs `git show --remerge-diff --format= --numstat -M -z` on each (one process per
merge), and adds an entry to `conflict` on the node of every listed file the PR changes,
found by its path at the tip or, for a file the PR moves, its path before the move. The
entry classifies the resolution: `"picked"` when the merge's blob of the file equals a
parent's (at the same path, or the path before a rename the re-merge shows), so the merge
took one side; else `"merged"`, a file combined by hand. Blob ids come from the
repository's long-running `git cat-file --batch-check`. `lines` is the file's added plus
removed lines in that re-merge diff (several files of one node in one merge add up; any
merged one makes the entry merged). A clean merge lists nothing. A file the merge touched
but the PR's diff does not is no node and is not reported. The summary prints a hint
naming the merged files with each merge's lines and counting the picked ones. It needs
git 2.36 or later; an older git, a shallow or partial (blobless) clone, or a failing call
skips the check with one warning and never stops the build. The viewer marks only merged
files (↯ on the row and the map box; the plan's conflicts column counts them). When the
merged files are more than 10 and more than a quarter of the PR's changed files (a long
branch merged from main often), the row and map marks hide by default, a line in the plan
says how many and that "Conflict marks" in the View menu shows them. The detail panel
always lists every resolution with its lines, picked ones dimmed.

### Areas (clusters)

A PR above 40 core files (not tests, not docs/config/i18n) opens its Map on an overview
of areas instead of every file; at 40 or fewer the Map is the flat map as before. Author
8–12 areas by feature or flow in the overlay:

```json
{"clusters": {"auth": {"label": "Sign-in", "order": 1, "depth": "read"},
              "billing": {"label": "Billing", "order": 2, "depth": "skim", "why": "renames only"}},
 "nodes": {"M:src/auth/service.ts": {"cluster": "auth"}, "M:src/auth/routes.ts": {"cluster": "auth"}}}
```

An id is up to 40 letters, digits, `_`, `.`, or `-`, starting with a letter or digit;
`label` (report language) defaults to the id and `order` to the area's place in the
overlay. A parent-key reference (`M:path`) puts the file in the area in every part, so
an area spans the parts and each part tab shows its own. build_graph.py writes the
node's `cluster` and each PR's `clusters` (the areas its nodes use); a shared
dependency keeps none, with a warning; a docs/config/i18n node keeps its area (for the
plan rows, "Group by area", and the overview) and still reads last; an unknown area,
a malformed id, or a non-integer order stops it. Its summary counts the files per area
(tests aside) and names the core files without one. validate.py rejects a node whose
area its PR does not list and warns about fewer than 4 or more than 15 areas, an area with
no file of its own (only tests or hubs), and a PR above 40 core nodes without areas.
An area of translation catalogs with `"depth": "tool"` and a `why` naming the parity
check keeps them out of the plan's time.

An area may also say how to review it, for the viewer's review plan: `depth` is
`"read"` (follow it line by line), `"skim"` (look it over), or `"tool"` (a check covers
it), and `why` a short phrase in the report language (for `"tool"` the check: `{"depth":
"tool", "why": "i18n key parity test"}`). Both reach the PR's `clusters` as given
(`prs[].clusters[].depth`, `.why`). build_graph.py stops on another depth or a `why`
that is not text; validate.py rejects them too and warns about a `"tool"` area without
a `why` and a `why` over 120 characters.

The review plan times each area from its files' changed lines per `bucket`, in changed
lines an hour when read closely: logic 400 added and 1500 removed, tests 1500, docs
2000, i18n 3000, config 1000, generated not counted; a `"skim"` area 4× faster, a
`"tool"` area 0; at least 1 minute, above 5 rounded up to the next 5, from 90 minutes
shown in hours (the viewer's `PLAN_RATE`, the minutes column's tooltip says the same).

The viewer completes the areas, so a graph without them still has some: the shared
dependencies form one area, docs/config/i18n without an area another (an authored area
of nothing but such files is listed and shelved with it), each test joins the file it
tests, core files without a known area are grouped by folder (at most 10 areas less the
authored ones, about 25 files each), and each earlier PR or part whose files the PR uses
is one area. The overview draws a box per area (name, files, read count, note-kind and
test chips) and one line per pair of linked areas with its link count, wider for more
(log scale), laid out with the flat map's layered layout (earlier PRs left, shared
dependencies in a band on top, docs/config/i18n below, their lines drawn only for the
selected file). A click or Enter expands an area in place: its linked files in the same
layout, the others in a grid, each test as a "T n" badge on the file it tests (the list
and the diff keep the tests). The selected file's links to other areas end at the files
of expanded areas and at the border of collapsed ones; selecting a file expands its area
and fades files more than 1 or 2 links away (1 / 2 / all, default 2, kept under `hops`).
It zooms and pans through an SVG transform: Ctrl+wheel or pinch, dragging, the −/+/Fit
buttons, keys `+` `-` `0`, Shift+arrows; the arrow keys move between the areas and the
files of expanded ones (one Tab stop), Enter or Space acts, and expanding is announced.
Expanded areas are kept per PR under `mapx`, zoom and pan under `mapz`.

### Tours (Trasy)

A tour walks one flow of the change (web sign-in, a token exchange, a deletion) step
by step across PRs and parts. Author one per distinct flow, at most 8, each of 3 to 15
steps, in the overlay:

```json
{"tours": [{"id": "apple-web", "name": "Web sign-in with Apple", "steps": [
  {"ref": "M:app/Http/Controllers/AppleAuthenticationController.php", "side": "new", "lines": "12-30",
   "note": "Redirects to Apple with state and nonce"},
  {"ref": "M:app/Services/AppleTokenVerifier.php", "lines": "40-58", "note": "Checks the id token's signature"}]}]}
```

`ref` names a file like any overlay reference (a parent-key reference reaches the parts:
the last part that changes the file on the new side, the first on the old side; not a
`#group`). `side` is `new` (default; lines at the PR's tip) or `old` (at its base, for
code the PR removes). `lines` is a line or a range on that side; without it the step
opens the whole file. `note` (report language) says what to look at in 80 characters or
fewer. The id takes an area id's form. build_graph.py reads each step's lines with `git
show` and writes graphs.json `tours` (above); an unknown key, a group, malformed lines or
side, and a tour list beyond the limits stop it. What a moved branch can cause degrades
with a warning instead, as other overlay references do: a step whose file the PR no
longer changes is left out (and a tour left with fewer than 3 steps with it), and a step
whose file is missing on its side or whose lines run past the file's end goes stale (it
opens the whole file; a file gone from its side keeps the previous build's lines and
code for when it comes back). validate.py checks each step's node and path against the diff data and
warns when a step's lines lie outside every hunk on their side (the viewer then opens the
whole file) and when a narrative `data-tour` button names no tour.

After a branch moves, `refresh.py` gives build_graph.py the graphs.json it replaces as
`--previous`: a step whose tour, ref, side, and lines are unchanged follows the code it was
resolved on with the viewer's note matcher (exact, white space ignored, or a close fuzzy
match, found once on the same side; scripts/tours.py ports it). Moved code moves the step
("moved 12-30 → 18-36"); code that changed leaves it stale, a warning, and the viewer opens
the whole file with "code changed". The overlay is never rewritten: change a step's
`lines` there to anchor it afresh. A step whose file left the PR, or whose file a new
commit deleted, degrades as above and never stops the refresh.

The viewer puts a tour picker beside the view toggle. A chosen tour shows a bar at the
foot of the graph, held at the bottom of the window: "Krok 3 z 8" / "Step 3 of 8", the
note, the step's file and lines (and "moved from :12-30" or "code changed"), Previous and
Next (keys `[` `]`), and Exit (Esc). Each step switches to its tab, selects its node,
opens its diff, and scrolls to and flashes its lines; the shown tab's rows carry the step
numbers of their files, the map draws the tour's path with numbered marks (the overview
of areas opens the areas on it), each step is announced in a live region, and the tour
and step persist under the `tour` localStorage key. A narrative button with
`data-tour="<id>"` starts a tour.

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
  "dropEdges": [{"from": "A:apps/api/src/app.ts", "to": "A:#docs"}],
  "tours": [{"id": "services", "name": "Services request", "steps": [{"ref": "S:libs/x/infra/monolith.client.ts", "lines": "10-24", "note": "…"}, "…"]}]
}
```

`nodes` may set `role`, `note`, `layer`, `label`, `hub` (`true` or `false`, see
Shared dependencies), `cluster` (an id from the overlay's `clusters`, see Areas), and
`generated` (`true` for generated code the patterns miss, such as an API client built
from a schema; `false` for a hand-kept file they catch; see `bucket`).
`tours` are described under Tours.
An `extraNodes` entry is an
unchanged reference file (`unchanged: true` is implied). For a PR split into parts,
the parent key (`M:path`) names the path in every part: `nodes` apply to each part's
node, an edge starts at the last part that changes its `from` and ends at the last
part up to that one with its `to` (skipped with a warning when none has it),
`dropEdges` drop it in every part, and `extraNodes` go to the first part. A part key
(`Mb:path`) names one part. Overlay edges replace a
weaker edge between the same nodes (`test > route > di > http > config > import > type`).
A reference to a path the PR does not change (a typo, or a file a moved branch
dropped) and an `extraNodes` file the PR now changes are skipped with a warning,
so a refresh never fails on them; fix or remove them when you see the warning.

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
  "S1": [{"path": "libs/x/contract/services.schema.ts", "diff": "--- /dev/null\n+++ b/…\n@@ -0,0 +1,79 @@\n+…", "fp": "3f9a0c1d2e4b"}],
  "B21": [{"path": "web/translations/pl-PL.json", "diff": "…", "fp": "…"}, {"path": "web/translations/en-US.json", "diff": "…", "fp": "…"}],
  "A27": [{"path": "pnpm-lock.yaml", "diff": "…", "fp": "…", "truncated": 5120}]
}
```

Keys are node ids; each value lists that node's files with a unified diff whose
`diff --git`, `index`, mode, and rename headers are stripped. For `.vue`, `.svelte`,
and `.astro` files each `@@` line ends with the last block tag before the hunk,
shortened to its name and lang (`<script lang="ts">`, `<template>`, `</script>`;
gen_diffs.py reads a tag that git cut at 80 bytes, that hides a `>` in an attribute,
or that spans lines from the file's old version), which the viewer uses to highlight
a hunk in the middle of a `<template>`, `<script>`, or `<style>` block in that block's
language (it falls back to the tags inside the hunks and a guess for diffs without it).
A text file moved without a change (similarity 100%, so git gives no hunk) carries
`"moved": "<old path>"` and, while it has at most 400 lines and the page's budget of 4000
such lines lasts (files in diff order), its whole content at the tip as one hunk of
context lines (`@@ -1,n +1,n @@`, after `--- a/` and `+++ b/` lines); the viewer says
"moved from … without changes" above it, and review notes and tour steps can anchor on
any line (validate.py finds them inside the hunk). Past the limits its `diff` is empty:
the viewer says it moved and that its lines are not in the page, and validate.py warns
that a tour step into it opens the file. Its `fp` stays the rename's (from, to,
similarity), so a refresh does not flag it changed. A path git C-quotes in a diff
header (a name with a double quote, a backslash, or a control character) is unquoted.
A file that two or more parts of a PR change has, on the entry of the last part that
changes it, `"whole": {"diff": "…", "truncated"?: n}`: its diff over the whole PR (first
part's start to last part's end), shown read-only by the viewer's whole-PR toggle.
`fp` fingerprints the file's change: 12 hex digits of SHA-256 over the full diff body
with every `@@` line reduced to `@@` (lines that only shift do not count), plus the
header lines for a mode change (and a new or deleted file's mode unless 100644), a
rename or copy (from, to, similarity), and the blob ids of a binary file. `truncated` is the
full line count of a diff cut at `--max-lines`; `binary: true` marks a binary
file. The viewer opens files lazily and collapses a file over 400 lines, and every
file after the first when a node has more than four.

## review-map.json and previous.json

`build_graph.py` (section `build_graph`, beside `--out`), `gen_diffs.py`
(`gen_diffs`, beside `--graph`), and `assemble.py` (`assemble`, beside `--graph`)
record the inputs of their last run in `review-map.json`: PR keys, repositories
(absolute), ranges, names, titles, labels, aliases, groups, overlay, context, line
cap, strictness, narrative, title, language, strings, target, template (when not the
default), output, the storage key as resolved, the previous-version file, and each
PR's full tip SHA. With `--chunks`, build_graph's section also has `"chunks": [{"path":
"chunks.json", "parent": "M", "tip": "<full sha of the branch tip>"}]` and gen_diffs's
`"chunks": ["chunks.json"]`. Paths inside the directory are relative to it.
`--no-manifest` skips the record.

`refresh.py DIR` replays the three runs (into side files, swapped in only when
both data steps succeed; build_graph.py gets the graphs.json it replaces as
`--previous`, so tour steps follow their code), then validates. For a PR split into parts it first fits `chunks.json`
to the branch (`chunks.advance`): commits after the last part become a new part, a
rewritten history is remapped by patch-id or subject, and a part it cannot map stops
it before anything is rebuilt; the new `chunks.json` replaces the old one with the
data. Before rebuilding it keeps the current
build's generation, tips, and file fingerprints in `previous.json`
(`{"generation": n, "tips": {KEY: short sha}, "files": {KEY: {path: fp}}}`), which
`assemble.py --previous` embeds in the page config. Every page also carries its own
generation, which `assemble.py` takes from the page it replaces (`--out`, else the
page the manifest last recorded): the same content (every file's PR, path, and
fingerprint) keeps its number, so rebuilding the same data is byte-identical; other
content counts one up, whether it came from `refresh.py` or the scripts by hand, and
then also above n when `--previous` is given. A page with no readable page before it
starts at 0 (one above n with `--previous`); a page whose data or generation is not
what assemble.py writes (a generation is an int from 0 to 2**31) counts as none, with a
warning. `refresh.py` writes the replaced page's own generation as n. A re-run that changes nothing keeps
the existing `previous.json`, so the page's comparison stays. `--assemble-only`
reassembles and validates with the recorded inputs, after a narrative edit. PR keys,
repositories, and ranges must not start with `-` or hold white space or control
characters (`--end-of-options` goes before every revision too), other values reach
the scripts as `--option=value`, and the outputs must lie in the directory unless
`--allow-outside` is given.

The viewer compares each file's `fp` with `previous.files`: a file the PR did not
change before is new, a different fingerprint is changed, a file only the previous
build had is removed; a file without `fp` is never flagged changed. A read mark
stores the fingerprint and generation it is known good on (`readfp` in
localStorage, `{f, g}`). On load it is cleared when the fingerprint differs and its
generation is not above the page's: lower means the page is newer; equal means the
mark comes from another history (a fresh directory with the same storage key; within
one history equal generations have equal content), which cannot be ordered, so the
different code counts as unread. A mark from a higher generation is from a newer page
and is never cleared, and a matching fingerprint moves the mark up to the page's
generation, so opening an older page never clears one. A cleared mark is remembered
under `wasread` (shown as ↻ while the page's code differs from what was read) until
the file is marked read again; a page built without `--previous` still lists the
cleared marks in its banner. A file without a fingerprint keeps its mark and stores
none.

Limit: generations are counted per directory. A page built in a fresh directory starts
at 0 again, so with the same storage key it never clears marks another directory's
history stamped with a higher generation, even where the code changed (those files
show as read). Keep one scratch directory per review, or give a new one its own
`--storage-key`.
