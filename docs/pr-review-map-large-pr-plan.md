# pr-review-map for large PRs — approved goal: a 200-file pull request reads as clearly as a 30-file one.

**Trigger:** kolodziejm/personal-os#251 (one PR, 219 files → 178 nodes, 403 edges). The Map view became a mesh of crossing edges and the step list was too long to scan. A zoomable canvas alone does not fix density; aggregation does.

**Non-goals:** no history rewrite (the skill stays read-only on repositories); no new runtime dependency in the page (elkjs not adopted now); no change to existing localStorage keys; pages and `graphs.json` without the new fields render exactly as today.

**Building blocks:** commit chunks (virtual stack) · clusters (semantic zoom) · tours (guided flows) · existing multi-PR machinery · `refresh.py` replay.

**Decisions (owner, 2026-10-18):**
- Commits that arrive after a chunked map was built become a new part ("new since last version"); earlier parts, their read marks and notes stay untouched.
- Read marks from a whole-PR map are not carried into parts (part diffs differ); the banner lists them as "read on the whole PR". Notes migrate exactly.
- Files changed in two or more parts get a "whole-PR diff" toggle; the full diff is embedded only for those files.
- Polish name for tours: **Trasy** (`tours`).
- Defaults until data says otherwise: suggest parts above 100 files or 60 nodes; open the Map on the cluster overview above 40 core nodes; keep the in-house layered layout (elkjs only behind a flag later, if expanded clusters stay messy).
- Interleaved history: `chunks.py propose` only proposes consecutive ranges and warns when scopes interleave or a base merge sits inside a part; regrouping history stays a manual step outside the skill.

## Units (status; dependencies)

**P1a — Commit chunks: propose and render:** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS; 269 tests); deps: none. **P1b — Chunks on refresh, note migration, narrative card:** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS; 273 tests); deps: P1a. **P2a — Cluster schema and "Group by area" list:** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS; 279 tests); deps: none. **P2b — Cluster overview map, test badges, hop fade:** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS; 279 tests); deps: P2a. **P2c — Pan/zoom and accessibility polish:** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS; 279 tests); deps: P2b. **P3a — Tours schema, resolution, validation, viewer stepper:** planned; deps: none (P2b for the map path). **P3b — Tour relocation on refresh, map path, prompt changes:** planned; deps: P3a.

Each unit ends with `uv run --locked ./scripts/check` (fallback `PYTHON=.venv/bin/python ./scripts/check`), one `CHANGELOG.md` "## Unreleased" bullet, the pr-review-map paragraph in `README.md` updated, and `./scripts/install-claude-code --dry-run` then `./scripts/install-claude-code`.

## P1 — Virtual stack from commits

- **`scripts/chunks.py`** (new, stdlib, read-only git). `propose` reads `git log --first-parent --reverse` with per-commit numstat for `base...tip`, groups consecutive commits by conventional-commit `type(scope)`, then message prefix or task id, merges neighbours under ~15 files, splits above ~60, prints a table (part, commits, files, scopes, first subjects) and writes a draft `chunks.json` for the owner to confirm. `expand()` turns it into per-part `--pr` entries.
- **`chunks.json`:** `{"parent":{"key":"M","repo":abs,"range":"develop...feat/x","name":"#251","title":…},"parts":[{"key":"Ma","to":"<full sha>","label":"client-core"}]}`. Part *i* is `to(i-1)..to(i)`; part 1 starts at the merge base. Part keys end in a letter (`Ma`, `Mb`) so node ids (key + order) cannot collide.
- **`build_graph.py` / `gen_diffs.py`:** `--chunks FILE`. Each part gets `chunk:{of,index,count,from,to,commits,subjects≤5}`; top level gets `parents[]`. Overlay refs keep the parent key (`M:path`): role and note apply to every part node of that path; edges resolve to the latest part where the file exists (existing `locate()` already marks cross-part edges `external`).
- **File in several parts:** one node per part with its own diff slice and fingerprint, an "also in parts 1, 3" chip, and the whole-PR diff toggle (decision above).
- **`review-map.json` / `refresh.py`:** record the `chunks` section (path + parent tip). Refresh keeps boundaries that are still ancestors, appends new commits as a new part, remaps after a rebase by subject + `git patch-id`, and stops with "re-run chunks.py propose" when that fails. `narrative_warnings` also checks part boundary SHAs.
- **Viewer:** part tabs grouped under the parent (`#251 ▸ 1/5 client-core · 34`) with the range and subjects in a tooltip; the earlier-parts group in the step list starts collapsed. Copied notes name the part (`M · part 2/5 (abc..def)`) and say line numbers are at that part's tip.
- **Note migration (one-time):** new-side line notes go to the last part changing the file (its tip equals the PR tip for that file), old-side notes to the first part changing it, PR-scope notes to the parent.
- **Narrative / prompts:** `references/narrative.md` gains one parent `pr-card` with a nested `ol.parts` and a callout that review order matters but merge order does not apply. Change maps fan out per part (`change-map-prompt.md`, earlier parts read as earlier PRs); `graph-prompt.md` gains the `--chunks` command; `SKILL.md` step 1 gets ~12 lines (threshold, propose, owner confirms) with details in new `references/chunks.md`.
- **Validation:** `validate.py` and `assemble.check_graph` check contiguous parts with indices 1..n, `from(i) == to(i-1)`, and valid keys.
- **Tests (`tests/test_pr_review_map.py`):** deterministic propose grouped by scope; file in two parts → two nodes with their own slices; cross-part edge is external; parent overlay refs resolve; refresh appends a part, remaps after rebase, refuses when unmappable; manifest stores relative paths; broken chain rejected; note migration (cut-out function); `SKILL.md` stays under 250 lines.

## P2 — Cluster overview with expand

- **Schema (`references/graph-schema.md`):** overlay `"clusters":{"auth":{"label":"…","order":1}}` and `nodes.<ref>.cluster` (parent-key refs work across parts); output per PR `clusters:[{id,label,order}]` and node `cluster`. Unauthored clusters fall back to folder prefix; hubs form a "shared" cluster; tests take their subject's cluster; docs/config/i18n go to a "late" cluster.
- **Prompt / validation:** `graph-prompt.md` assigns 8–12 clusters by feature or flow from the change maps. `validate.py`: unknown cluster id is an error; fewer than 4 or more than 15 clusters, or a cluster with no core node, is a warning.
- **Viewer:** above 40 core nodes the Map opens on the overview: cluster boxes (label, files, +/−, read x/y, note chips) and aggregated inter-cluster edges with a count and log-scaled width. Click/Enter expands a cluster in place; edges to collapsed clusters end on the border; node-to-node edges between expanded clusters draw only for the selected file. Tests become a "T n" badge on their subject (still in the list and diff). Selection auto-expands the file's cluster and fades nodes beyond N hops to 0.25 (toggle 1 / 2 / all, default 2). The step list gains "Group by area" (reuses folder grouping, keeps step numbers).
- **Layout:** keep the in-house layered layout and run it twice: on the cluster DAG (8–12 nodes, cycles broken) and inside each expanded cluster (5–25 nodes). Reason: density, not the layouter, causes the mesh; elkjs would add ~1.5 MB CDN JS per view (unverified), async layout, possible worker limits in the Artifact sandbox, and no node-testable cut-out functions.
- **Pan/zoom (P2c):** SVG transform; Ctrl+wheel or pinch, drag, buttons +/−/fit, keys `+` `-` `0`; arrows keep moving the selection, Shift+arrow pans.
- **Accessibility:** one Tab stop with roving tabindex; clusters are `role="button"` with `aria-expanded` and labels like "Auth, 14 files, 3 read, 5 links to Data"; expansions announced in a live region; `prefers-reduced-motion` disables transitions.
- **localStorage (new keys):** `mapx` (expanded clusters per PR), `hops`, `mapz` (zoom per PR), `lgroup`.
- **Tests:** overlay clusters and folder fallback; unknown cluster rejected; cut-out `clusterGraph()` (aggregated counts, tests folded into badges, hubs); cut-out `hops()`; at most 12 boxes on the overview and fewer crossings than the flat map on the fixture.

## P3 — Tours (Trasy)

- **Schema:** overlay `"tours":[{"id":"apple-web","name":"…","steps":[{"ref":"M:app/…/AppleAuthenticationController.php","side":"new","lines":"12-30","note":"≤80 chars"}]}]`. `build_graph` resolves each ref to a node (across PRs and parts), reads the step's code from `git show tip:path` (old side: base) and writes `tours[]` with `{node,path,side,a,b,code,note}`; unknown ref or path outside the node is an error.
- **Validation:** `validate.py` re-checks node/path against the diff data; a range outside every hunk on that side is a warning and the step falls back to the file; at most 8 tours, 3–15 steps each.
- **Refresh (P3b):** `refresh.py` passes `--previous graphs.json`; `build_graph` relocates steps from the previous `code` with a Python port of the viewer's 3-tier note matcher (exact → whitespace-insensitive → bigram ≥ 0.8, unique match), printing "moved 12-30 → 18-36" or "stale" (falls back to the file). The overlay is never rewritten. Python and JS matchers share test vectors with `NOTE_STATE`.
- **Prompts:** `change-map-prompt.md` §4 becomes named flows with steps `path:start-end — note` (new-side lines at the tip); `graph-prompt.md` authors one tour per distinct flow and checks lines with `git show`; `narrative.md` gains an optional `data-tour` button.
- **Viewer:** tour picker beside the view toggle; a tour bar "Krok 3 z 8 · note" with Prev/Next, keys `[` `]`, Esc to exit; each step switches tab, selects the node, opens the diff and scrolls to and flashes the range (reuses `jump()`); list rows get tour-step badges; the map draws the tour path (reuses the reading-path overlay); current step announced in a live region; state persists under the new `tour` key.

## i18n (`assets/strings.json`, identical pl/en key sets)

Parts: `chunkOf` ("część {i}/{n}"), `chunkRange`, `chunkAlso`, `chunkWholeRead`, `chunkWholeDiff`. Clusters: `mapAreas`, `clusterExpand`, `clusterCollapse`, `expandAll`, `collapseAll`, `edgeCount`, `testsBadge`, `hops1`, `hops2`, `hopsAll`, `zoomIn`, `zoomOut`, `zoomFit`, `groupByArea`. Tours: `tours` ("Trasy" / "Tours"), `tourPick`, `tourStep`, `tourPrev`, `tourNext`, `tourExit`, `tourMoved`, `tourStale`.

## Risks

- A base merge inside a part puts base changes into that part's diff: `propose` sets a boundary there or warns.
- Copied notes on a part that is not the last to change a file cite lines at that part's tip, not the branch tip (the copy says so).
- Interleaved commits produce many tiny parts (merge threshold and warning).
- Node id collisions if the part-key rule is not enforced (validated).
- Python and JS relocation matchers drifting apart (shared test vectors).
- `assets/viewer.html` (~2000 lines) keeps growing; `SKILL.md` has ~30 lines of budget left.

## First use after P1–P2

Rebuild the review map of kolodziejm/personal-os#251 as a chunked map (parts by plan section: backend core, backend flows, web, iOS, docs, review fixes) with clusters, then add tours for web sign-in, iOS exchange, deletion with revocation, and server notifications.

## Canonical references: [skill](../skills/pr-review-map/SKILL.md) · [viewer](../skills/pr-review-map/assets/viewer.html) · [graph schema](../skills/pr-review-map/references/graph-schema.md) · [build_graph](../skills/pr-review-map/scripts/build_graph.py) · [refresh](../skills/pr-review-map/scripts/refresh.py) · [tests](../tests/test_pr_review_map.py) · [installer](../harnesses/claude-code/install.py) · [README](../README.md)
