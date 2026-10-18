# Prompt: per-PR change map (one read-only subagent per PR)

Send one copy per PR, in parallel. Fill every `<…>`. The subagent only reads; it
writes one markdown file and returns a short result, so the orchestrator never
loads the diff itself.

For a PR split into parts (`references/chunks.md`), send one copy per part instead:
the part's range from `chunks.py expand` (`from..to`), the part's tip as Tip SHA,
`<pr name> part <i>/<n>: <label>` as the PR line, the earlier parts under "Earlier PRs
in the stack", and `pr-<part key>.md` as the output. Each part reads like a PR of a
stack.

```text
Read-only task. Do not edit, commit, check out, stash, or push anything in the repository.

Produce a change map for one pull request so a reviewer can understand it without
reading files in alphabetical order.

PR: <owner/repo#number> — <title>
Repository path: <absolute path>
Diff range: <base...tip | merge-base..tip>   (read it with `git diff <range>`, `git show <tip>:<path>`; never check out)
Tip SHA: <sha>
Earlier PRs in the stack (do not describe their files; mention where this PR calls into them): <keys and one-line purpose, or "none">
Report language: <language of the final report, e.g. Polish>

Write the map to <scratch dir>/pr-<key>.md with exactly these sections:

1. Header line: diff basis (the range, what the base SHA is, files and +/- from
   `git diff --shortstat`), and whether the branch contains merge commits
   (`git log --merges --oneline <range>`).
2. Purpose: 3-5 sentences. What the PR adds or changes and why, in behavioral terms.
3. Files by layer: every changed file with +/- from `git diff --numstat`, grouped
   by layer (contract, domain, data, logic, infra, rest, ui, wiring, tests, config,
   i18n, docs). One line each: what changed in it. Group translations, catalogs,
   lockfiles, deploy config, and docs into one line per group with a file count.
   For a lockfile, list intended entries and every unrelated side effect.
4. Flow in reading order: the path of a request or event through the changed
   code, entry point first, as a numbered list with `path:line` for each step.
5. Wire shapes: request and response (or event) fields at this PR's boundary,
   with renames, defaults, and dropped fields. Cite the schema file:line.
6. Error mapping: each failure (not found, upstream 5xx, timeout, bad payload,
   missing config) and what this layer returns or logs. Cite file:line.
7. Config and wiring: env vars, DI, routes, feature flags this PR adds or reads,
   with the file that defines and the file that reads each.
8. Tests: each test file, what it covers, notable gaps.
9. Reviewer risks: concrete, ranked high / medium / low, each with file:line and
   the reason. Include unrelated changes (lockfile churn, drive-by refactors).
10. Per-file notes: for files a reviewer could misread, one sentence each in the
    report language, formatted `path: note`. These become the graph's detail-panel
    notes, so state facts the diff alone does not make obvious.

Rules:
- Every claim must come from the code at the tip. Do not infer config semantics,
  defaults, or behavior you did not read; write "not verified" instead.
- Use file:line references, not code dumps. Quote at most a few lines when a
  specific expression is the point.
- Return to me only: the output path, files and +/- totals, the top 3 risks, and
  anything you could not determine.
```

## What the orchestrator does with the maps

- Header and stack cards: purpose, base, file counts, tip SHA, merge commits.
- Narrative sections: architecture, request flow, error table, data shape, rules,
  per-PR sections, risks. Re-check any claim you put in the report against the
  code before writing it.
- Graph overlay: `role` per file from "Files by layer", `note` from "Per-file
  notes", HTTP/DI/route/config edges from "Flow" and "Config and wiring".
