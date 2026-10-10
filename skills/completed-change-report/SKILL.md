---
name: completed-change-report
description: >-
  Create a standalone visual HTML report that explains a change after it was
  made: what changed, how it works now, and what was verified. Use it when the
  user asks to see or visualize what was done, and on your own initiative after
  finishing a non-trivial change (several files, a structural or behavior change)
  where a picture makes the result easier to understand than chat text.
compatibility: Any Agent Skills-compatible harness; no external assets or network required.
---

# Completed change report

The reader absorbs changes visually. This report exists so they can understand
finished work at a glance before reading the diff. It is a comprehension aid, not
a process step: skip it for trivial changes, and never make the reader wade
through prose to find the picture.

## What to show

Lead with the picture, then support it with short text.

1. **Change map** — one diagram of the affected area showing what stayed, what
   changed, what was added, and what was removed, with the relationships between
   them. Pick the diagram type that fits the change (flow, sequence, state,
   component, or dependency) and scope it to the change, not the whole system.
2. **Before versus after** — side by side where the comparison helps: behavior,
   structure, or data flow. For visible UI changes, include real before and after
   screenshots when they exist.
3. **How it works now** — the new path through the code, drawn when it has more
   than a few steps.
4. **What was verified** — the checks that ran and their results, and separately
   what was not run or could not be verified.
5. **Differences from the plan** — if a planned change report exists for this
   change (`change-reports/<change-id>-plan.html`), link to it and show where the
   result differs and why. If there is none, say so and move on.
6. **Where to look** — the few places in the diff that deserve the reader's own
   attention, with the reason for each, plus remaining work and open questions.

Keep text short. Use lists and tables for files, checks, and decisions. Give the
size of the change (files and lines, with generated files counted separately) but
leave large diffs and source listings out.

## Honesty

Describe what the code actually does now, read from the repository at the revision
you are reporting on, and name that revision. Report checks exactly: passed,
failed, or not run. Do not call work verified when it was not. Never invent
evidence, measurements, or screenshots; if a before state was not captured, say it
is unavailable.

## HTML file

Write one self-contained HTML file:

- inline CSS, JavaScript, and SVG only; screenshots embedded as data URIs; no
  external assets, fonts, imports, or network requests;
- a light, responsive layout that also reads well printed and with JavaScript
  disabled;
- diagrams as inline SVG with readable labels and a short text summary beside
  each one;
- semantic headings and tables, keyboard-usable controls, and visible focus;
- restrained colors that carry meaning (added, changed, removed, unchanged), always
  paired with a text label;
- all inserted text escaped; no secrets, credentials, personal data, or private
  URLs.

Write the headings and explanations in the language of the current conversation.
Keep code, commands, paths, and identifiers exactly as they are.

## Output

Save the file as `change-reports/<change-id>-done.html` in the project root, using
the same `<change-id>` as the planned change report when one exists, unless the
user names another path. Creating the `change-reports/` directory is fine. Do not
stage or commit the report, do not edit `.gitignore` for it, and ask before
overwriting a file that belongs to a different change.

Finish by giving the path to the file and one or two sentences on what changed
and what remains unverified.
