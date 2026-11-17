---
name: pr-review-map
description: >-
  Build an interactive HTML review map for a change of any size: one pull request, a
  branch, or a stack of dependent pull requests, possibly across repositories. A brief
  first (what changes for users, contract changes, ranked risks, what was never tested,
  decisions), then, as the change grows, a reading budget, a per-PR graph of the changed
  files and their real dependencies with a numbered reading order, a side-by-side diff
  viewer, the merge order, the changes per PR, and what to check before merging. Use it
  when the user wants to review, visualize, or understand a PR or a PR stack ("review
  map", "raport do review", "graf zależności diffu", "jak czytać te zmiany", "in what
  order should I read this diff", "where is the risk in this change"), and offer it after
  finishing a change that spans several PRs.
compatibility: Requires git and python3 (standard library only) to build the data, node to validate the page, and read access to every repository in the stack. Publishes through the Claude Code Artifact tool when available, otherwise writes a local HTML file. The page loads highlight.js (plus any language file its diffs need, such as dockerfile or protobuf) and, for a local file, mermaid from cdnjs.
---

# PR review map

A diff reads in GitHub's alphabetical file order and says nothing about where the risk
is. This skill produces one page that gets the reader to the important parts first: a
brief (what changes, which contracts move, the ranked risks, what was never tested, the
decisions), then, as the change grows, a reading budget and a graph of where to start,
what depends on what, and what to skip, with each file's diff one click away. It is a
comprehension aid for the reviewer, not a summary for its author: lead with the brief,
keep prose short (bullets that restate the graph or the diff do not belong), and never
state anything you did not verify.

## What the page contains

Keep this order. The viewer (`assets/viewer.html`) renders section 4, `assemble.py`
generates sections 2 and 3; you author the rest as `narrative.html` (building blocks
and rules: `references/narrative.md`).

1. **Header and brief** (authored): your title, then one section of one-liners across
   the whole change, never per PR: what changes for users (at most 3 bullets); one table
   of contract changes by kind (migration, route, API types, config/env, auth, events),
   each with PR chip and code link; the risks ranked across all PRs (irreversible, all
   users, security, data loss first), at most 7, each with severity, PR chip, and a link
   that opens the lines; what was never tested; one line per decision, linking to its
   card in Before merging. Code links here, in the budget, and on decision cards open a
   review overlay (that list as a queue, the diff banded; `j`/`k`, `x` reads, Esc closes).
2. **Reading budget** (generated, large changes): "Read N of M changed lines (x%)", a bar
   of the four attention classes (must read, read, skim, skip), then the files to read
   by PR, risky first with why, each opening at its focus lines.
3. **Merge order** (generated from `graphs.json`): one line per PR with key, name, title,
   tip SHA, file count, +/−, the authored `summary` (overlay `summaries`), and a link to
   its section; a PR split into parts is one line with its parts under it.
4. **Interactive reading graph** (the core). Per-PR tabs. Nodes are changed files;
   translations, catalogs, deploy config, docs, and lockfiles collapse into one node
   each. Edges are real dependencies: resolved imports (through barrels to the file that
   defines the name; type-only ones dotted), PHP `use`, DI and routing bindings, test →
   subject, code → config it reads, HTTP calls across services, and links to files of
   earlier PRs. Each changed file has an **attention** class (mechanical, pattern,
   novel, risky; `build_graph.py` guesses it, the overlay decides), shown as a chip and
   dimming mechanical rows; View › "Only what to read" keeps risky and novel files with
   their step numbers. The page opens on the map; a **Steps** toggle (closed by default,
   kept) opens the step list beside the detail panel and diff: one row per file in
   reading order (read checkbox, step number, layer colour, attention and note chips,
   "→A"/"←B" chips for other PRs), tests under their subject, a lane of arcs for the
   selected file's links. Files of earlier PRs head the list, shared dependencies (`hub`)
   come next, "Group by folder" or "by area" splits the rest. The order runs "from the
   entry point" or "from dependencies"; each PR opens in the one `build_graph.py`
   recommends (`readFrom`). Selecting a file shows its path, role, +/−, note, focus
   ranges, and neighbourhood, then its diff (side by side or unified). The map opens
   above 40 core files on an overview of areas (`clusters`, else folders). **Review
   notes** go on a line range, a file, or a PR (issue, question, suggestion, OK) and
   "Copy notes" puts them on the clipboard as Markdown with `path:start-end` references.
   **After a refresh** (step 7) a note follows moved code, goes "stale" or "file gone",
   and a banner counts files changed since the previous version and clears their read
   marks. **A PR split into parts** (step 1) shows tabs grouped under it. **Tours**
   (step 3): a picker walks one flow, opening each step's lines on its tab. Files combined
   by hand in a merge carry a ↯ mark and a copyable `git show --remerge-diff`. The
   **View** menu holds the list and map options and **Theme** (Auto, Light, Dark); ⤢,
   `f`, or `#ws` opens a full-window **workspace** (1100 px and wider). Read marks and
   the chosen view persist in localStorage.
5. **Architecture**: a mermaid flowchart, only when the PRs change how layers connect.
6. **Request flow**: a mermaid sequence diagram, only when relevant, failure paths inside
   it (`alt`/`else`). At most one line of text around either; both zoom and pan.
7. **Changes per PR**: nested bullets, one per change in behaviour or structure
   (never per file), with the button that opens the PR's graph. Behaviour changes
   start with "Behaviour change:"; business rules are bullets with concrete values.
   Review pointers that are not risks of the brief follow in a collapsed "Look closely
   (n)", at most three per PR.
8. **Before merging**: "Decisions for you" (only what the owner alone decides: question,
   "Recommended:" with evidence or "No recommendation:", alternatives, code links; "Add
   as note" only here), the **verification table** (per PR: tested SHA, ran / not run /
   n/a), and "After merging". File links show as a short name and line.

**Size** (`size` in `graphs.json`, computed by `build_graph.py`, the overlay may override):
`small` is one PR of at most 10 files and 400 lines; `large` is over 60 files, over 3000
lines, or over 3 PRs; else `medium`.

- small: the brief, Before merging, and the diffs; the step list opens by default, no
  map, budget, diagrams, or Changes per PR.
- medium: + reading order, map, attention chips, "Only what to read".
- large: + the reading budget.

Write the narrative in the user's language. UI strings exist for `pl` and `en`
(`assets/strings.json`); override keys or add a locale with `--strings`.

## Workflow

Keep your own context small: subagents read the diffs, scripts move the data,
you write the narrative from their summaries. Work in a scratch directory
(`$SCRATCH` below); `$SKILL` is this skill's directory. The size tier (step 3
prints it) decides how much runs: steps 1 and 3 to 7 always.

### 1. Pin the PRs and their ranges

For each PR record: key (short, e.g. `M`, `S`, `A`, `B`), display name
(`S #12680`), repository path, base, tip branch, tip SHA, and the diff range.

- A PR against its base branch: `base...tip` (three dots), the diff GitHub shows.
- A stacked PR: `previous-tip...tip`, so it shows only its own layer.
- The base moved and the PR was never rebased: `$(git merge-base origin/<base>
  <tip>)..<tip>`, and write that SHA down. Note merge commits: `git log --merges`.
- Fetch first. If a branch moves later, regenerate (step 7); never patch data by hand.

List the PRs in merge order; edges may only point to the same or an earlier PR.

**A very large PR** (over 100 files or 60 nodes; build_graph.py prints a hint) reads
better as a virtual stack of parts cut from its commits:

```bash
python3 $SKILL/scripts/chunks.py propose --repo /abs/repo --range develop...feat/x \
  --key M --name "#251" --out $SCRATCH/chunks.json
```

It groups consecutive commits by scope and prints a table. Let the user confirm or
adjust `chunks.json`; never rewrite their history. Then pass `--chunks
$SCRATCH/chunks.json` to build_graph.py and gen_diffs.py in place of that PR's `--pr`,
and fan out one change map per part. Details: `references/chunks.md`.

### 2. Fan out change maps (parallel, read-only)

Start one read-only subagent per PR with the prompt in
`references/change-map-prompt.md`. Each writes `$SCRATCH/pr-<key>.md` (purpose, changes
as the page's bullets, files by layer, flows as `path:start-end — note` steps, failure
paths, config, tests, contracts, risks with severity, untested gaps, a proposed
attention class and focus ranges per file, what it verified, per-file notes) and
returns only a short summary. Read the summaries; open a map only for the section you
are writing. A **small** change needs no fan-out: one change map, or read the diff
yourself; tours, areas, and roles are optional for it.

### 3. Build the graph data (one subagent)

Hand `references/graph-prompt.md` to one subagent. It runs
`scripts/build_graph.py`, which scaffolds `graphs.json` from git without a
checkout (numstat, grouping, a first-guess layer and attention class, JS/TS imports
with tsconfig paths and aliases, re-exports through barrels, type-only imports, Python
imports, PHP `use`, test → subject, dependency order, a recommended reading mode, the
`size` tier), then records what git cannot show in `overlay.json`: DI, routing, config
readers, HTTP edges, unchanged reference files, a `role` for every node, `note`s from
the change maps, a `hub` override where the shared-dependency rule misjudges a file,
`attention` (default: migrations risky; lockfiles, generated files, i18n, docs, trivial
changes, pure moves mechanical; tests and deploy config pattern; else novel) and `focus`
ranges where the guess is wrong, for a PR above 40 core files 8-12 areas (`clusters`),
and one tour per flow (`tours`, lines checked with `git show`). Schema and overlay
format: `references/graph-schema.md`.

### 4. Generate the diffs

```bash
python3 $SKILL/scripts/gen_diffs.py --graph $SCRATCH/graphs.json --out $SCRATCH/diffs.json \
  --pr S /abs/repo main...feat/s --pr A /abs/repo feat/s...feat/a --strict
```

One `--pr KEY REPO RANGE` per PR. Each diff is assigned to its node through
`path`/`files`, and `--max-lines` (default 2000) caps a huge file such as a lockfile.
Fix every "mapped to no node" file in the overlay rather than dropping `--strict`.

### 5. Write the narrative

Write `$SCRATCH/narrative.html` following `references/narrative.md`: the title
header, the brief, the single `<!-- review-map:graph -->` line, then the diagrams that are
relevant, the bullets per PR, and "Before merging" (a small change: header, brief, and
"Before merging" only). For the brief, merge the maps across all PRs: contracts into one
table, risks re-ranked by the rubric (at most 7; the rest stay under "Look closely"), the
harmful gaps, one line per decision. Do not write the budget, merge order, tips, file
counts, or +/−: assemble.py generates them from `graphs.json`. Check each claim against
the code at the tip (config semantics, defaults, status codes, flag behavior, deploy
order); if you cannot verify it, say so or leave it out. Use `file:line` references,
not code dumps.

### 6. Assemble and validate

```bash
python3 $SKILL/scripts/assemble.py --graph $SCRATCH/graphs.json --diffs $SCRATCH/diffs.json \
  --narrative $SCRATCH/narrative.html --title "<page title>" --lang pl \
  [--strings $SCRATCH/strings.json] --target artifact --out $SCRATCH/review.html
python3 $SKILL/scripts/validate.py $SCRATCH/review.html
```

Read marks (by PR and file path) and review notes live in localStorage under
`--storage-key` (default: derived from the title); keep it unchanged when you
regenerate so they survive. Keep `graphs.json` and `diffs.json` in `$SCRATCH`:
build_graph, gen_diffs, and assemble record their inputs (and the resolved
storage key) in `$SCRATCH/review-map.json` for step 7.
`assemble.py` fills the template, builds the table of contents, the budget, and
the merge order, colours each PR, and embeds the data as `<script
type="application/json">` blocks with `</` written as `<\/` and `<!--` as `<!--`
(both valid JSON). Never hand-insert JSON into the page and never emit an invalid
escape such as `<\!--`.

`validate.py` compiles every inline script in node, parses every data block, checks
markup balance, the CDN allowlist (cdnjs), leftover placeholders, and graph/diff
consistency (attention values, focus ranges). Do not publish until it prints `OK`;
a warning (no brief, a node without a diff, a focus outside its diff) is worth fixing.

### 7. Publish

- **Claude Code with the Artifact tool**: call its quickstart with intent `other`
  first and follow the page contract it returns. `--target artifact` output already
  starts with `<title>` and leaves `<pre class="mermaid">` to the host renderer.
  Publish `review.html` and give the user the link.
- **Anywhere else**: assemble with `--target local` (a full document that loads
  mermaid from cdnjs), validate it, and give the user the absolute file path.

When a branch moves, fetch, then run `python3 $SKILL/scripts/refresh.py $SCRATCH`.
It replays steps 3 (same overlay), 4, and 6 from `review-map.json`, resolves
branch names to their current tips (read-only, prints old → new per PR), and
builds the page against the previous version (`previous.json`): changed-file
banner and badges, read marks of changed files cleared, notes moved or flagged.
It never edits the narrative; the budget and merge order come from the new
`graphs.json`, and it warns where the narrative still shows an old tip. Tour steps
follow their code (moved, or stale: whole file); `focus` ranges do not, so a changed
file that has them is warned about. Parts survive: new commits become a new part, a
rebase is remapped by patch-id or subject, and it stops when that fails. Update the
narrative lines and claims the new commits change, run `refresh.py $SCRATCH
--assemble-only`, and republish. It trusts `review-map.json` as far as reading the
files it names: run it only on a manifest your own runs wrote; it refuses PR keys,
repositories, and ranges git could read as options and writes only inside `$SCRATCH`
unless given `--allow-outside`.

## Rules

- Read-only on the repositories: `git diff`, `git show`, `git log`, `git
  ls-tree`. No checkout, stash, commit, or push. Keys, ranges, and revisions
  never start with `-`; the scripts check that and pass `--end-of-options`.
- The graph owns reading order. Do not add numbered reading lists to the
  narrative; put per-file explanations in the graph `note` fields.
- Every edge must come from the code (resolved import, binding, call site), never
  from naming similarity alone, except test → subject.
- Keep diffs in the page (`diffs.json`), never link out; the page is self-contained
  apart from cdnjs.
- Report only what was verified. A suite that was not run is "not run"; a config
  value whose meaning you did not read is not described.
- Offer the map when you finish a change that spans several PRs; build it only
  when the user wants it.
