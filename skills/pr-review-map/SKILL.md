---
name: pr-review-map
description: >-
  Build an interactive HTML review map for one large pull request or a stack of
  dependent pull requests, possibly across repositories: a per-PR graph of the
  changed files and their real dependencies with a numbered reading order, a
  side-by-side diff viewer for the selected file, and the architecture, data
  flow, business rules, risks, and verification around it. Use it when the user
  wants to review, visualize, or understand a big PR or PR stack ("review map",
  "raport do review", "graf zależności diffu", "jak czytać te zmiany", "in what
  order should I read this diff"), and offer it after finishing a change that
  spans several PRs.
compatibility: Requires git and python3 (standard library only) to build the data, node to validate the page, and read access to every repository in the stack. Publishes through the Claude Code Artifact tool when available, otherwise writes a local HTML file. The page loads highlight.js (plus any language file its diffs need, such as dockerfile or protobuf) and, for a local file, mermaid from cdnjs.
---

# PR review map

Large diffs are unreadable in GitHub's alphabetical file order. This skill
produces one page that tells a reviewer where to start, what depends on what,
and what to check, with the diff of each file one click away. It is a
comprehension aid for the reviewer, not a summary for its author: lead with the
reading graph, keep prose short, and never state anything you did not verify.

## What the page contains

Keep this order. The viewer (`assets/viewer.html`) renders section 2; you author
the rest as `narrative.html` (building blocks: `references/narrative.md`).

1. **Header and PR stack cards**: one card per PR in merge order with link,
   base, file count, +/−, tip SHA, and two or three bullets. Explain the merge
   order. Add a callout when the branches carry merge commits.
2. **Interactive reading graph** (the core). Per-PR tabs. Nodes are changed
   files; translations, catalogs, deploy config, docs, and lockfiles collapse into
   one node each. Edges are real dependencies: resolved imports, PHP `use`, DI and
   routing bindings, test → subject, code → config it reads, HTTP calls across
   services, and links to files of earlier PRs. The default view is a step list
   pinned beside the detail panel and diff: one row per file in reading order
   (read checkbox, step number, layer colour, note-kind chips, and "→A"/"←B"
   chips for files of PR A it uses or PR B files that use it, which open that
   file on its tab), each test indented under its subject, and a lane drawing the
   selected file's dependencies and dependents as arcs between rows ("All links"
   draws every dependency; above 60 rows only nearby arcs and the selected
   file's). Files of earlier PRs the PR uses head the list, grouped
   by PR. Shared dependencies (files at least a quarter of the PR's linked files
   use, flagged `hub`) come next as the first steps in both modes, in their own
   group; arcs into them show only while one is selected, and the neighbourhood
   lists them on one "+ shared:" line. "Group by folder" splits the rest into
   collapsible sections that keep the step numbers. The order runs "from the entry point" (default, reverse dependency
   order) or "from dependencies"; in both, a file connected to the one just read
   comes next when the dependencies allow, tests follow their subject, files with
   no edge to another file of the PR come after the connected ones, docs/config/
   i18n last, and step numbers stay fixed when the test filter hides tests.
   Selecting a file (click, ↑/↓ and Enter, prev/next) shows its path, role, +/−,
   per-file note, and neighbourhood (dependencies in blue | file | dependents in
   orange, other PRs' files in their colour, previous and next step), then its
   diff (side by side or unified, big files collapsed, rendered lazily). A Map
   toggle adds the whole graph: entry points right, tests under their subject,
   earlier-PR files in a left band, shared dependencies in a top band, unlinked files and docs/config/i18n on a
   shelf, full-size labels that scroll. Read marks and the chosen view persist in
   localStorage. **Review notes**: on a line range (click a line number;
   Shift+click or the keyboard for a range on the same side), a
   whole file ("Note on file" in its diff header), or a whole PR (the button by
   the tabs), each an issue, question, suggestion, or OK. Notes show as coloured
   markers and in a notes panel (kind filter, edit, delete, jump), persist in
   localStorage, and "Copy notes" puts the shown ones on the clipboard as Markdown
   for an agent: what each kind asks for (fix, answer, consider, nothing), the
   PRs with repo and base/tip commits, then the notes by kind, PR, file, and line,
   each with a `path:start-end` (or bare `path`) reference, side, code, and text;
   headings in a note move below the note's own level and an open fence is closed.
   **After a refresh** (step 7) a line note whose code moved follows it ("moved
   from :12-14"; exact, white space ignored, or a close fuzzy match, found once on
   the same side), one whose code changed is "stale" (no marker), one on a file
   the PR no longer changes is "file gone"; a "Code changed" filter and actions
   (accept the new location, re-anchor to the selected lines, dismiss, restore)
   handle them, and the copy names each state. A banner counts the files new,
   changed, and removed since the previous version (tips old → new, "Only changed
   files"), rows carry new/changed badges, and read marks of changed files are
   cleared and marked ↻.
3. **Architecture** as a mermaid flowchart, then the **request flow** as a
   mermaid sequence diagram plus an error-mapping table across layers.
4. **Data shape across layers**: one table, a row per field, a column per layer.
5. **Business rules**: tables with concrete example values and `path:line`.
6. **One section per PR**: purpose, an "open on the reading graph" button,
   a collapsible file list, and "to check" callouts. No numbered reading-order
   list here: the graph owns the order and per-file notes live in its detail panel.
7. **Risks** ranked by severity (coloured stripe), then what is out of scope.
8. **Verification**: what was actually run and its result, and what was not.

Write the narrative and the UI strings in the user's language. Built-in UI
strings exist for `pl` and `en` (`assets/strings.json`); override any key, or
supply a whole other locale, with a small JSON file passed as `--strings`.

## Workflow

Keep your own context small: subagents read the diffs, scripts move the data,
you write the narrative from their summaries. Work in a scratch directory
(`$SCRATCH` below); `$SKILL` is this skill's directory.

### 1. Pin the PRs and their ranges

For each PR record: key (short, e.g. `M`, `S`, `A`, `B`), display name
(`S #12680`), repository path, base, tip branch, tip SHA, and the diff range.

- A PR against its base branch: `base...tip` (three dots), the diff GitHub shows.
- A stacked PR: `previous-tip...tip`, so it shows only its own layer.
- The base moved and the PR was never rebased (long-lived branches, monoliths):
  `$(git merge-base origin/<base> <tip>)..<tip>`, and write that SHA down.
- Note merge commits: `git log --merges --oneline <range>`.
- Fetch first. If a branch moves later, regenerate (step 7); do not patch data by hand.

List the PRs in merge order; edges may only point to the same or an earlier PR.

### 2. Fan out change maps (parallel, read-only)

Start one read-only subagent per PR with the prompt in
`references/change-map-prompt.md`. Each writes `$SCRATCH/pr-<key>.md` (purpose,
files by layer with +/−, flow in reading order with `file:line`, wire shapes,
error mapping, config, tests, ranked risks, per-file notes) and returns only a
short summary. Read the summaries; open a map only for the section you are
writing.

### 3. Build the graph data (one subagent)

Hand `references/graph-prompt.md` to one subagent. It runs
`scripts/build_graph.py`, which scaffolds `graphs.json` from git without a
checkout (numstat, grouping, a first-guess layer, JS/TS imports with aliases,
Python imports, PHP `use`, test → subject, dependency order), then records what
git cannot show in `overlay.json`: DI, routing, config readers, HTTP edges,
unchanged reference files, a `role` for every node, `note`s from the change
maps, and a `hub` override where the shared-dependency rule misjudges a file. The schema and overlay format are in `references/graph-schema.md`.

### 4. Generate the diffs

```bash
python3 $SKILL/scripts/gen_diffs.py --graph $SCRATCH/graphs.json --out $SCRATCH/diffs.json \
  --pr S /abs/repo main...feat/s --pr A /abs/repo feat/s...feat/a --strict
```

One `--pr KEY REPO RANGE` per PR. Git headers are stripped, each diff is
assigned to its node through `path`/`files`, `--max-lines` (default 2000)
caps a huge file such as a lockfile, and Vue/Svelte/Astro hunks name their block
on the `@@` line so the viewer highlights template, script, and style apart. Fix every "mapped to no node" file in the
overlay rather than dropping `--strict`.

### 5. Write the narrative

Write `$SCRATCH/narrative.html` following `references/narrative.md`, with the
single `<!-- review-map:graph -->` line between the stack section and the
architecture section. Before writing a claim, check it against the code at the
tip: config semantics, defaults, status codes, flag behavior, deploy order. If
you cannot verify something, say so in the page or leave it out. Use `file:line`
references, not code dumps; the diff viewer shows the code.

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
`assemble.py` fills the template, builds the table of contents, colours each PR,
and embeds the data as `<script type="application/json">` blocks with `</`
written as `<\/` and `<!--` as `<!--` (both valid JSON). Never hand-insert
JSON into the page and never emit an invalid escape such as `<\!--`.

`validate.py` compiles every inline script in node (`new Function`), parses
every data block with `JSON.parse`, checks div/section/details balance, the CDN
allowlist (cdnjs), leftover placeholders, and graph/diff consistency. Do not
publish until it prints `OK`. Warnings about nodes without a diff are worth
fixing too.

### 7. Publish

- **Claude Code with the Artifact tool**: call its quickstart with intent
  `other` first and follow the page contract it returns (`<title>` first, theme
  tokens for light and dark, mobile layout, CDN allowlist). `--target artifact`
  output already starts with `<title>` and leaves `<pre class="mermaid">` to the
  host renderer. Publish `review.html` and give the user the link.
- **Anywhere else**: assemble with `--target local` (a full document that loads
  mermaid from cdnjs), validate it, and give the user the absolute file path.

When a branch moves, fetch, then run `python3 $SKILL/scripts/refresh.py $SCRATCH`.
It replays steps 3 (same overlay), 4, and 6 from `review-map.json`, resolves
branch names to their current tips (read-only, prints old → new per PR), and
builds the page against the previous version (`previous.json`): changed-file
banner and badges, read marks of changed files cleared, notes moved or flagged.
It never edits the narrative; it warns which stack cards still show an old tip
and prints new counts. Update those cards and every claim the new commits
change, run `refresh.py $SCRATCH --assemble-only`, and republish.

## Rules

- Read-only on the repositories: `git diff`, `git show`, `git log`, `git
  ls-tree`. No checkout, stash, commit, or push.
- The graph owns reading order. Do not add numbered reading lists to the
  narrative; put per-file explanations in the graph `note` fields.
- Every edge must come from the code (resolved import, binding, call site). Do
  not draw edges from naming similarity alone, except test → subject.
- Keep diffs in the page: embed them through `diffs.json`, never link out
  instead. Keep the page self-contained apart from cdnjs.
- Report only what was verified. A suite that was not run goes under "not run";
  a config value whose meaning you did not read is not described.
- Offer the map when you finish a change that spans several PRs; build it only
  when the user wants it.
