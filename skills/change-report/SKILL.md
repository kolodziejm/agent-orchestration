---
name: change-report
description: >-
  Create one standalone, harness-agnostic HTML change report for an initiative in
  PRE or POST mode when the current user explicitly requests it. The skill may
  suggest a report, but suggestion or model visibility never authorizes a report
  file to be created or updated.
compatibility: Any Agent Skills-compatible harness; no external assets or network required.
---

# Change report

This is a prompt-only Agent Skills package. It has exactly two requested modes:
`PRE` and `POST`. One HTML document may contain both tabs for one initiative.
There is no required renderer, schema, helper script, CLI, digest, approval state
machine, or skill-specific persistence contract.

## Permission and timing

The model may remain visible and may suggest this skill:

- before material, multi-file, or architectural implementation work, for `PRE`;
- after implementation and validation, before the user's personal review or merge
  decision, for `POST`.

A suggestion is not a request. Loading, mentioning, or suggesting this skill MUST
NOT create, overwrite, or update any report file. Act only after an explicit
current-user request for a PRE report, a POST report, or an update to the report.
Do not infer that request from a plan, approval, review authorization, or a prior
conversation. Never create a report merely to inspect the repository.

The report is evidence and communication. It never creates a PR, commits, pushes,
merges, or authorizes a merge. Agent review never equals human review.

## Modes

### PRE

Use PRE before implementation. Build an evidence-backed baseline and proposal:

- current repository state, relevant constraints, and evidence sources;
- problem, user impact, and success conditions;
- proposed target architecture, likely modules/contracts, and relationships;
- explicitly unchanged scope and non-goals;
- proposed PR or review-unit decomposition with dependencies;
- expected intermediate states and handoff points;
- considered alternatives and why they were not selected;
- risks, mitigations, planned validation, and open or confirmed human decisions.

PRE must label facts separately from proposals and estimates. If the document is
not yet implemented, the POST tab must visibly say `NOT IMPLEMENTED YET`.

### POST

Use POST after implementation and validation, before human review or merge. Preserve
and show the PRE baseline when a genuine PRE exists, then record:

- plan-versus-actual differences and the actual architecture;
- the actual stack organized per PR or fallback review unit, with dependencies and
  intermediate states;
- before/after behavior, affected paths, and diff accounting split into
  human-authored, generated-artifact, and lockfile lines/files;
- tests and CI with `NOT REQUESTED`, `NOT RUN`, `UNKNOWN`, or observed results
  distinguished precisely;
- agent review and human review as separate activities;
- decisions, findings, residual work, risks, and readiness for human review/merge.

If no genuine PRE report exists, say that the PRE baseline is unavailable. Never
backfill or fabricate a PRE from POST facts. A POST report may still describe the
actual work and clearly mark unavailable comparisons.

## Evidence, provenance, and status

Use available harness tools for the smallest useful read-only evidence set. Do not
assume Git, a shell, a browser, a particular Agent Skills command, or a particular
report location. Do not mutate project source to create a report. Do not include
secrets, credentials, tokens, personal data, private URLs, or large source dumps.
Escape all untrusted text before inserting it into HTML.

Use these provenance labels when applicable, visibly and consistently:

- `REPOSITORY EVIDENCE` — observed from the repository or an available runtime;
- `PROPOSAL` — intended future design or behavior;
- `ESTIMATE` — forecast such as effort, size, or likely impact;
- `HUMAN DECISION` — explicitly supplied or confirmed by a person;
- `ACTUAL` — implemented and observed in the requested scope;
- `AGENT REVIEW` — review performed by an agent;
- `HUMAN REVIEW` — review performed by a person;
- `UNVERIFIED` — claimed or expected but not independently established.

Keep `NOT REQUESTED`, `NOT RUN`, and `UNKNOWN` distinct: the first means no check
was requested, the second means it was requested but not executed, and the third
means its state cannot be established. Do not call agent observations human review,
and do not call readiness merge authorization.

## Report language

Write headings, explanations, decisions, risks, and summaries in the language of
the user's current conversation unless the user explicitly requests another
language. If the conversation is multilingual, follow the language of the latest
explicit report request; ask only when that is genuinely unclear. Preserve code,
commands, paths, identifiers, API names, quoted evidence, and canonical status
values exactly rather than translating them.

## HTML deliverable

Create one standalone HTML file for the initiative. It must:

- use inline CSS, JavaScript, and SVG only; have no external assets, imports,
  fonts, analytics, network requests, or runtime dependencies;
- use a light, responsive theme and be visually rich only where it improves
  comprehension; keep semantic colors restrained and pair them with text and
  provenance/status badges;
- provide accessible PRE/POST tabs with semantic headings, keyboard operation,
  visible focus, appropriate ARIA roles/state, and a useful reading order;
- show both modes with JavaScript disabled and in print output; make the POST
  `NOT IMPLEMENTED YET` state available without scripting;
- use diagrams only when they clarify relationships, include an equivalent
  textual fallback, and keep diagrams compact;
- use semantic lists/tables for units, paths, counts, decisions, validation, and
  residual work; keep large diffs and source listings out of the report;
- escape untrusted content and avoid secrets, personal data, and unnecessary
  absolute paths.

The compact header may take visual inspiration from a supplied status strip, but
must remain readable, semantic, and provenance-aware rather than decorative.

## Workflow and output

When the user explicitly requests a mode, gather read-only evidence with the
available harness tools, write the report content, and render the standalone HTML
according to these instructions. By default, place it in the active project's
`change-reports/<change-id>.html`, using the current working directory or nearest
repository root as the project root and a short filesystem-safe change ID. This
keeps the report visible in editors such as VS Code. If the user explicitly
supplies another output path, honor it after confirming it is writable and safe.

Creating the requested HTML and its `change-reports/` parent is allowed, but do not
modify project source, add or edit `.gitignore`, stage or commit the report, or
create supporting state, cache, schema, script, or test files. Before overwriting
an unrelated existing file, stop and ask. For POST, update the same initiative
report when available so the PRE tab remains intact; otherwise create a document
that states the PRE baseline is unavailable.

Stop after producing or updating the requested HTML. Show its project-relative
and absolute paths, note that it may appear as an untracked or modified file, and
report its mode, evidence limitations, and any `NOT RUN` or `UNVERIFIED` status.
Do not treat a report as authority for implementation, review, release, or merge.
