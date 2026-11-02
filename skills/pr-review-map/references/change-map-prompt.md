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
2. Purpose: 2-4 sentences. What the PR adds or changes and why, in behavioral terms.
3. Changes: the working input for the page's bullets, nested two levels at most. One
   item per change in behaviour or structure (a new route, a moved responsibility, a
   changed default, a new column), never one per file. Under it, the details a
   reviewer needs and the code does not make obvious. Give a reason only when it is
   not obvious from the change. Start an item that users or callers will notice (a
   new default, a removed option, another status code or message) with "Behaviour
   change:" and say before and after. A business rule gets its concrete values (input
   and result, units, limits). Cite `path:start-end` (relative to the repository root,
   lines at the tip) on the items worth opening. Mention a wire shape (request,
   response, or event fields at this PR's boundary, with renames, defaults, and
   dropped fields) as part of the change that alters it.
4. Files by layer: every changed file with +/- from `git diff --numstat`, grouped
   by layer (contract, domain, data, logic, infra, rest, ui, wiring, tests, config,
   i18n, docs). One line each: what changed in it. Group translations, catalogs,
   lockfiles, deploy config, and docs into one line per group with a file count.
   For a lockfile, list intended entries and every unrelated side effect. This is the
   input for the graph's `role` fields, not for the page.
5. Flows: each distinct flow the PR adds or changes (a request, an event, a job,
   a sign-in), named in a heading, entry point first, as a numbered list of steps
   `path:start-end — note` (lines at the tip from `git show <tip>:<path>`; `old:path:
   start-end` with lines at the base for code the PR removes; the note at most 80
   characters, report language). These become the graph's tours.
6. Failure paths: each failure (not found, upstream 5xx, timeout, bad payload,
   missing config) and what this layer returns or logs, per flow. Cite file:line. They
   become `alt`/`else` branches of the request-flow diagram.
7. Config and wiring: env vars, DI, routes, feature flags this PR adds or reads,
   with the file that defines and the file that reads each.
8. Tests: each test file, what it covers, notable gaps.
9. Decisions and look-closely pointers. Two lists:
   - Decisions only the owner can make: a product, risk, or rollout trade-off (a default
     that changes, a behaviour users will notice that is arguably wrong, a step after the
     merge that costs something). "Is this code correct?" is not a decision. For each: the
     question in one sentence; a recommendation only if the diff or the code you read
     supports it, with that evidence (`path:start-end` or the fact), else "no
     recommendation: <what is missing>"; the alternatives with their consequence, one line
     each; the code links. Do not invent a recommendation.
   - Look closely: where a bug could hide or a contract must be checked, ranked high /
     medium / low, at most three, each one line with `path:start-end` (relative to the
     repository root). Include unrelated changes (lockfile churn, drive-by refactors) and
     files a merge commit changed by hand (`git show --remerge-diff <merge>` lists them).
   Intended behaviour changes go under Changes, not here.
10. Not verified and surfaces: what you could not read or determine (a config value whose
    meaning you did not read, behaviour that only a run shows), and which surfaces the PR
    touches (backend tests, browser, iOS simulator or device, CI) so the verification table
    can say `n/a` for a surface it does not touch and `not run` for one it does. You are
    read-only, so you ran nothing; do not report a check as verified.
11. Per-file notes: for files a reviewer could misread, one sentence each in the
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

- Narrative bullets: the "Changes" section, rewritten per the rules in
  `references/narrative.md` (one bullet per change, two levels, "Behaviour change:",
  concrete values). The header (tip SHA, file counts, +/-) is generated from
  `graphs.json`; do not copy it from the maps. The per-PR `summaries` (overlay) come from
  Purpose.
- Diagrams, only when relevant: the architecture from "Changes" and "Config and
  wiring", the request flow from "Flows" with "Failure paths" as `alt`/`else`.
- "Before merging": "Decisions for you" from the decision lists (keep only what the owner
  alone decides, and only recommendations the evidence supports), "Look closely" under the
  owning PR's bullets from the pointer lists (at most three per PR, drop the rest), the
  verification table and its gaps from the surfaces and from what you ran or read
  yourself, with the SHA. Re-check any claim you put in the report against the code
  before writing it.
- Graph overlay: `role` per file from "Files by layer", `note` from "Per-file
  notes", HTTP/DI/route/config edges from "Flows" and "Config and wiring", and one
  tour per flow from "Flows".
