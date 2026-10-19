# Parts: one large PR as a virtual stack cut from its commits

A pull request of 200 files reads like a stack of five once its commits are cut into
consecutive parts: each part gets its own tab, reading order (with its own shared
dependencies and recommended reading mode), map, and diffs, and the parts link to
each other like stacked PRs. The skill never rewrites history; a part
is only a commit range (`from..to`) of the branch as it is.

## When

Suggest parts when one PR changes more than 100 files or its graph has more than 60
nodes (`build_graph.py` prints a hint for such a PR). Below that, one map reads well.
The owner decides: show the proposal, never build parts they did not confirm.

## Propose and confirm

```bash
python3 $SKILL/scripts/chunks.py propose --repo /abs/repo --range develop...feat/x \
  --key M --name "#251" --title "Sign in with Apple" --out $SCRATCH/chunks.json
```

It reads `git log --first-parent --reverse` with numstat for the range (a merge
against its first parent) and groups consecutive commits by their conventional-commit
scope (`feat(web): …` → `web`; without a scope the type; else a `[prefix]` or a task
id such as `ABC-123`; a commit with none joins the commits before it). A group under
`--min-files` (15) files merges into the neighbour that gives the smaller result while
that stays at `--max-files` (60) files or fewer; a larger group splits at commit
boundaries. It prints one row per part (part, key, commits, files, scopes, first
subjects) and writes a draft. It refuses to overwrite an existing file without `--force`,
since the owner may have edited it.

Warnings to pass on to the owner:

- **Interleaved history**: a scope comes back after other scopes (`core` in parts 1 and
  3). Merge those parts in `chunks.json`, or let the owner regroup the commits with an
  interactive rebase outside the skill, then propose again.
- **Base merge**: a merge of the base branch gets a part of its own, because its diff
  is the base's changes. Keep it as context and skip it when reading; folding it into
  a neighbour puts those changes into that part's diff.
- **A single commit above `--max-files`** cannot be split further.

```json
{"parent": {"key": "M", "repo": "/abs/repo", "range": "develop...feat/x", "name": "#251", "title": "…"},
 "parts": [{"key": "Ma", "to": "<full sha>", "label": "client-core"},
           {"key": "Mb", "to": "<full sha>", "label": "web"}]}
```

Part *i* is `to(i-1)..to(i)`; part 1 starts at the merge base of the range's base and
`to(1)` (at the base itself for `base..tip`). To merge two parts, delete the earlier
one's entry; to split one, add an entry with the `to` of a commit inside it; relabel
freely (report language, short). Keys end in a letter (`Ma`, `Mb`, …, `Maa`), so node
ids (key + step number) of two parts cannot collide, and differ from the parent key.
`chunks.py expand chunks.json` checks the chain (each `to` comes after the one before
it on the branch) and prints each part's range, commits, files, and `--pr` arguments.

## Build

Pass the file instead of the PR's `--pr` to both data scripts:

```bash
python3 $SKILL/scripts/build_graph.py --out $SCRATCH/graphs.json --chunks $SCRATCH/chunks.json \
  --overlay $SCRATCH/overlay.json [--pr S /abs/api main...feat/s --pr M /abs/repo develop...feat/x]
python3 $SKILL/scripts/gen_diffs.py --graph $SCRATCH/graphs.json --out $SCRATCH/diffs.json \
  --chunks $SCRATCH/chunks.json --strict
```

In a stack, a `--pr` with the parent's key (same repository and range as the file)
marks where the parts go; without one they follow the `--pr` entries. Each part is a
PR in `graphs.json` with its own key, range, `chunk` metadata, and default name
(`#251 2/5 web`); `parents` lists the parent with its parts. Imports from a later part
resolve to the latest earlier part that changed the file, as cross-PR (`external`)
edges. A file that several parts change is one node per part, each with its own diff
slice and fingerprint; `gen_diffs.py` adds its diff over the whole PR to the last part's
entry (`whole`) for the viewer's toggle.

Overlay references may use the parent key: `M:path` sets `role`, `note`, `layer`,
`label`, and `cluster` (its area, so an area spans the parts and each part tab shows the
areas its nodes use) on every part's node of that path; an edge from `M:a` starts at the last part
that changes `a` and ends at the last part up to that one that has its target (skipped
with a warning when there is none); `dropEdges` drops the edge in every part;
`extraNodes` with `"pr": "M"` go to the first part, so every part can link to them. A
part key (`Mb:path`) names that part alone.

## Change maps

Fan out one change map per part (`references/change-map-prompt.md`): the part's range
from `chunks.py expand`, its label as the purpose hint, and the earlier parts listed
under "Earlier PRs in the stack". Per-part notes go into the overlay under the part's
key, notes true for the file in every part under the parent key.

## The page

- Part tabs sit in one group after the parent's name (`#251 ▸ 1/5 client-core · 34`);
  the tooltip has the part's commits and first subjects.
- Files of earlier parts the part uses head the step list in a group per part, which
  starts collapsed; "→1/5" chips link a file to the parts it uses or that use it.
- A file changed in other parts too carries an "⇄1,3" chip ("also in parts 1, 3"), and
  its detail panel links to its node in each of them. Its diff header has a "Whole-PR
  diff" toggle that shows the file's diff over the whole PR read-only.
- Read marks, notes, and the changes banner work per part (part key + path).
- Copied notes name the part (`#251 · part 2/5 (abc1234..def5678)`) and say that
  their line numbers are at that part's commits, not at the branch tip.
- **From a whole-PR map** (same storage key): notes move to the parts once. A new-side
  line note goes to the last part changing its file (its tip has the PR tip's version),
  or to the latest part whose diff shows its code at its lines; an old-side note to the
  first part changing the file (its start has the base version); a file note to the last
  part; a PR note stays on the parent. Read marks are not carried over, since part diffs
  differ: the banner lists them as "read on the whole PR" until the file is marked read
  in a part.

## Narrative

Write one stack card for the parent with an `ol.parts` list, and say that the parts are
read in order but have no merge order (`references/narrative.md`).

## Refresh

`refresh.py` keeps the parts when the branch moves:

- **New commits** after the last part become a new part labelled "new since last
  version" (in the page language); earlier parts, their read marks, and their notes stay
  as they were.
- **Rebase or force-push**: each part's end maps to the commit on the new branch with
  the same patch-id, else the same subject (the only one after the previous part's end);
  later commits become a new part. Keys and labels stay.
- **Unmappable** (a boundary commit dropped, squashed, or reworded and changed): it stops
  before rebuilding anything and asks for `chunks.py propose` again.

The updated `chunks.json` replaces the old one only when the data steps succeed. The
narrative warnings name lines that still show a part's old end and new parts missing
from the parts card. Relabel a new part in `chunks.json` if you like and run
`refresh.py` again.
