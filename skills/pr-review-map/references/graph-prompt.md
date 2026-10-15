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
     [--alias SPEC=PATH for workspace packages / tsconfig paths] \
     [--groups <scratch dir>/groups.json] --overlay <scratch dir>/overlay.json
   Start with an empty overlay ({}). Resolve package aliases from package.json
   "exports"/"name" and tsconfig "paths" at the tip with `git show`, not by guessing.
2. Read the printed summary and the generated graphs.json. For each PR check:
   - Every changed file is in exactly one node (groups list theirs in `files`).
   - Layers are right; fix wrong guesses with overlay `nodes.<ref>.layer`.
   - Edges the script cannot see are added in the overlay:
     PHP/Java DI and service definitions (`di`), routing config → controller
     (`route`), code → env/config/translations it reads (`config`), catalog →
     translations (`config`), a client calling a handler in another service or an
     earlier PR (`http`), a base class or router a changed file depends on as an
     unchanged reference node (`extraNodes` + `import`).
   - Tests point at their subject with kind `test` (add the edge when the stems differ).
3. Fill `role` for every node (one line, at most ~60 characters, report language)
   and `note` for files a reviewer could misread (one or two sentences, report
   language, may use <code>). Take them from the change maps; verify against the code.
4. Re-run build_graph.py with the overlay until the summary shows no missing roles
   and no warnings you have not checked. If it reports a dependency cycle, confirm it
   is real or drop the wrong edge with `dropEdges`.
5. Generate diffs and confirm every node has one:
   python3 <skill dir>/scripts/gen_diffs.py --graph <scratch dir>/graphs.json \
     --out <scratch dir>/diffs.json --pr <KEY REPO RANGE> [...] --strict

Return only: node and edge counts per PR, cross-PR edge count, the overlay path,
and anything you could not resolve (unmatched files, edges you were unsure about).
```
