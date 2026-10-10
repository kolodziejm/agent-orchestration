---
name: planned-change-report
description: >-
  Create a standalone visual HTML report that explains a planned change before it
  is implemented: what exists today, what will change, and how the pieces relate.
  Use it when the user asks to see or visualize a plan, and on your own initiative
  before a non-trivial change (several files, a structural or behavior change)
  where a picture makes the plan easier to understand than chat text.
compatibility: Any Agent Skills-compatible harness; no external assets or network required.
---

# Planned change report

The reader absorbs changes visually. This report exists so they can understand a
plan at a glance before work starts. It is a comprehension aid, not a process
step: skip it for trivial changes, and never make the reader wade through prose
to find the picture.

## What to show

Lead with the picture, then support it with short text.

1. **Change map** — one diagram of the affected area showing what stays, what
   changes, what is added, and what is removed, with the relationships between
   them. Pick the diagram type that fits the change (flow, sequence, state,
   component, or dependency) and scope it to the change, not the whole system.
2. **Today versus planned** — side by side where the comparison helps: behavior,
   structure, or data flow before and after.
3. **Steps** — the order of work, what each step delivers, and what depends on
   what. Draw it when there are more than a few steps.
4. **Decisions and alternatives** — the choices that shape the plan, the options
   that were considered, and why the chosen one won.
5. **Risks and open questions** — what could go wrong, what is still unknown, and
   which decisions the reader still has to make.
6. **Out of scope** — what deliberately does not change.

Keep text short. Use lists and tables for steps, files, and decisions. Leave large
diffs and source listings out.

## Honesty

Read the relevant code before drawing it; do not guess the current state. Mark
clearly what is observed in the repository, what is proposed, and what is an
estimate. Say plainly when something could not be checked. Never invent evidence,
measurements, or screenshots.

## HTML file

Write one self-contained HTML file:

- inline CSS, JavaScript, and SVG only; no external assets, fonts, imports, or
  network requests;
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

Save the file as `change-reports/<change-id>-plan.html` in the project root, where
`<change-id>` is a short filesystem-safe name for the change, unless the user names
another path. Creating the `change-reports/` directory is fine. Do not stage or
commit the report, do not edit `.gitignore` for it, and ask before overwriting a
file that belongs to a different change.

Finish by giving the path to the file and one or two sentences on what the plan
is and what the reader still needs to decide.
