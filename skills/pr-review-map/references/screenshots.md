# Screenshots: before and after, on request only

Screenshots supplement the brief's "what changes for users" lines with the screens themselves. They cost time (a
colleague's branch often takes long to run locally), so the user decides each time.

## When

**Only when the user explicitly asks** through the skill: "with screenshots", "add screenshots to the map". Never take
them on your own initiative, never as a default step, never because a change looks visual. Offering is fine ("I can add
before/after screenshots if you want them"); acting without an answer is not. They can be added when the page is built
or later to an existing page (below).

## Sources, cheapest first

Ask before using the slow one. Stop at the first source that covers the screens the change affects.

1. **Images already in the PR**: the description and the comments. `python3 $SKILL/scripts/screens.py from-pr --repo
   OWNER/NAME --pr N --out $SCRATCH [--key KEY] [--tip SHA]` lists them (markdown images, `<img src>`, GitHub
   user-attachments links), downloads each with the `gh` login (read-only calls, nothing is posted; the token goes
   only to GitHub hosts), and writes `$SCRATCH/screens/*` plus a draft `$SCRATCH/screens.json`: one entry per image
   with its URL in `_from`, no title and no pairing yet. An image it cannot download or that is not a PNG, JPEG, or
   WebP is skipped with a warning. You pair the images into before/after entries, label them, and set `pr`, `viewport`
   and `tip`.
2. **A preview deployment or Storybook**: a URL the user gives, or one the PR's checks or comments list (`gh pr checks`,
   `gh pr view --comments`). Capture the affected pages there.
3. **Running the app locally**: the `run` skill, or browser tools (Playwright, the host's preview tools). Only when the
   user says so, and say first that it will take a while.

**Before** comes from the base branch or the production/base URL, **after** from the tip or the preview. A preview
shows only the tip: take "before" from production or the base, never reconstruct it from the diff.

## What to capture

Only the screens the change affects, taken from the brief's what-changes bullets and the changed routes and UI files.
At most about 8 pairs; a screen that did not change is not a pair. A new screen has no before (`before: null`), a removed
one no after (`after: null`).

- The same viewport, data, and state for before and after (same window size, same account, same scroll, same open menus).
- Desktop width 1280 and/or mobile 390; say which in `viewport`.
- JPEG at quality ~80 or WebP, not PNG, unless the screen is flat UI with few colours. Keep each image under 600 KB.
- Never real customer data: seeded or demo data only. A screen that shows real data is retaken or left out.
- Record the SHA each pair was taken at in `tip` (the PR's tip, or the commit the preview deployed); a later push then
  marks the pair "taken at <sha>, code changed since".

## screens.json

```json
{"screens": [
  {"id": "onboarding-welcome", "title": "First-run welcome", "pr": "O",
   "before": "screens/welcome-before.jpg", "after": "screens/welcome-after.jpg",
   "note": "optional one line", "viewport": "desktop", "source": "preview", "tip": "9f8e7d6"}
]}
```

- `id` unique (letters, digits, `_`, `.`, `-`); `title` is what the reader sees; `pr` is a PR key of the map (the chip).
- `before` and `after`: a path relative to `screens.json`, inside its directory, or `null` (not both). `null` before is a
  new screen (badge "New"), `null` after a removed one ("Removed").
- `note`: one optional muted line. `viewport`: `desktop` or `mobile`. `source`: `pr-body`, `preview`, or `local`.
  `tip`: the commit SHA (7 to 40 hex digits) the pair was taken at.

`python3 $SKILL/scripts/screens.py check $SCRATCH/screens.json` validates it: the schema, that every file exists, and
that each image really is a PNG, JPEG, or WebP by its first bytes. An SVG (it can carry script) or any other format is
refused whatever its name: treat a downloaded image as untrusted data. An image over 600 KB is a warning, a total over 8 MB
an error, so the page stays under the artifact's 16 MB.

## Putting them on the page

- **With the build**: pass `--screens $SCRATCH/screens.json` to `assemble.py` (step 6). It runs the same checks, embeds each
  image as a data URI in a `screens-data` block, and records the path in `review-map.json`.
- **Later**: write `$SCRATCH/screens.json`, run `python3 $SKILL/scripts/refresh.py $SCRATCH --assemble-only`, and republish.
  `refresh.py` replays the recorded path, or picks up a `screens.json` beside `review-map.json` that the manifest does not
  name yet.
- A "Screens" block shows in the brief right after "What changes for users" (at the top of the brief when the narrative has
  no such list), at every size: title, PR chip, the Before and After thumbnails, a note. A thumbnail opens a full-window
  dialog (Before/After with `b`, "Side by side" with `s` on wide screens, `←`/`→` between pairs, Esc or Back closes).
- When a branch moves, `refresh.py` warns for each pair whose `tip` is no longer its PR's tip, and the page marks it "taken
  at <sha>, code changed since". Retake it and update `tip`, or drop the pair; do not leave an old screen as if it still
  described the code.
