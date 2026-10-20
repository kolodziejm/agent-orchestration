# Prompt: build graphs.json (one subagent, after the change maps exist)

```text
Task: build the reading graph data for a review map. Do not edit, commit, check out,
stash, or push anything in the repositories; write only inside <scratch dir>.

Inputs:
- PRs in merge order, each KEY REPO RANGE NAME:
  <M /abs/monolith 1a2b3c4..feat/m "Monolith #123">
  <S /abs/repo main...feat/s "S #456">
- Change maps: <scratch dir>/pr-<key>.md (purpose, files by layer, flow, config,
  per-file notes).
- Schema and overlay format: <skill dir>/references/graph-schema.md
- Report language: <language>

Steps:
1. Run the scaffold:
   python3 <skill dir>/scripts/build_graph.py --out <scratch dir>/graphs.json \
     --pr <KEY REPO RANGE> --name <KEY NAME> [... one pair per PR] \
     [--title <KEY "PR title">] [--repo <KEY owner/name> when origin does not name it] \
     [--alias SPEC=PATH for workspace packages, SPEC=PATH@DIR for importers under DIR only] \
     [--groups <scratch dir>/groups.json] --overlay <scratch dir>/overlay.json \
     [--chunks <scratch dir>/chunks.json for a PR split into parts, in place of its --pr]
   Start with an empty overlay ({}). The script reads tsconfig/jsconfig "paths" and
   "baseUrl" nearest to each importer and follows re-exports through unchanged barrels
   itself; give --alias only for what those miss (workspace packages, resolved from
   package.json "exports"/"name" at the tip with `git show`, not by guessing), scoped
   with @DIR when two parts of the repo use the same prefix differently.
2. Read the printed summary and the generated graphs.json. For each PR check:
   - Every changed file is in exactly one node (groups list theirs in `files`).
   - Layers are right; fix wrong guesses with overlay `nodes.<ref>.layer`.
   - Edges the script cannot see are added in the overlay:
     PHP/Java DI and service definitions (`di`), routing config → controller
     (`route`), code → env/config/translations it reads (`config`), catalog →
     translations (`config`), a client calling a handler in another service or an
     earlier PR (`http`), a base class or router a changed file depends on as an
     unchanged reference node (`extraNodes` + `import`).
   - Tests point at their subject with kind `test` (the script also matches a test to one
     nearby file by its name's words; add the edge when it finds none or the wrong one).
   - For a PR split into parts, each part is a PR (`Ma`, `Mb`, …). Put what holds for a
     file in every part under the parent key (`M:path`), what holds in one part under
     the part key (`Mb:path`); see <skill dir>/references/chunks.md.
   - The summary names each PR's shared dependencies (`hub`). Keep a file there only
     when most of the PR uses it as a utility (i18n, error text, shared types); set
     `nodes.<ref>.hub` to false for a central file whose links carry the flow, or to
     true for a missed utility.
   - The summary says which mode each PR reads from (`readFrom`) and why; it follows
     from the graph, so fix wrong edges or layers rather than the mode.
3. Fill `role` for every node (one line, at most ~60 characters, report language)
   and `note` for files a reviewer could misread (one or two sentences, report
   language, may use <code>). Take them from the change maps; verify against the code.
   For a PR (or part) above 40 core files (the summary prints a hint), group the core
   files into 8-12 areas by feature or flow, taken from the change maps' layers and
   flow: overlay `clusters` ({"auth": {"label": "...", "order": 1}}, labels in the
   report language, order as the flow reads) and `nodes.<ref>.cluster` on each core
   file. Shared dependencies, tests, and docs/config/i18n need none. For parts use the
   parent key, so an area spans the parts. A smaller PR may have areas too, when its
   files split into parts a reviewer takes differently. Give every area a `depth` for
   the viewer's review plan: `"read"` for logic to follow line by line, `"skim"` for
   mechanical changes (renames, wiring, styles), `"tool"` when a check covers it; and a
   `why` of a few words (report language) for skim and tool, for tool naming the check
   ("i18n key parity test", "regenerated from openapi.yaml, CI diff check").
   Mark generated files the defaults miss (lockfiles, snapshots, and minified files are
   caught) with `nodes.<ref>.generated: true`, so the plan counts them apart.
   The summary's hint names the files a merge commit changed by hand (node `conflict`):
   look at each resolution (`git show --remerge-diff <sha> -- <path>`) against both
   sides and say in its `note` what it kept.
   Author one tour per distinct flow in the change maps' "Flows" section (at most 8, each
   of 3 to 15 steps): overlay `tours` ([{"id": "apple-web", "name": "...", "steps":
   [{"ref": "M:path", "side": "new", "lines": "12-30", "note": "..."}]}], name and notes
   in the report language, a note at most 80 characters, a parent key for parts). Check
   every step's lines with `git show <tip>:<path>` (`side: "old"` and the base for code
   the PR removes): they must show the code the note names. Leave `lines` out only when
   the whole file is the step.
4. Re-run build_graph.py with the overlay until the summary shows no missing roles,
   no core files without an area where you authored areas, every tour with its step
   count, and no warnings you have not checked. If it reports an import cycle (type-only
   imports never make one), confirm it is real or drop the wrong edge with `dropEdges`.
5. Generate diffs and confirm every node has one:
   python3 <skill dir>/scripts/gen_diffs.py --graph <scratch dir>/graphs.json \
     --out <scratch dir>/diffs.json --pr <KEY REPO RANGE> [...] [--chunks <same file>] --strict
   Keep both outputs in <scratch dir>: the scripts record their arguments in
   <scratch dir>/review-map.json, which refresh.py replays when a branch moves.
   An overlay reference to a file the PR does not change is skipped with a
   warning; fix it rather than leave it. Then assemble a page and run validate.py: a tour
   step whose lines lie outside every hunk of its diff is a warning (the viewer opens the
   whole file); move it onto changed lines unless the unchanged code is the point.

Return only: node and edge counts per PR, cross-PR edge count, the areas per PR with
their file counts and depth, the tours with their step counts, the files resolved by
hand in merges with what each kept, the overlay path, and anything you could not
resolve (unmatched files, edges you were unsure about).
```
