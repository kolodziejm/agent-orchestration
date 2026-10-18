"""Tours ("Trasy"): named walks through a review map, authored in the overlay and resolved by build_graph.py.

overlay.json:
  "tours": [{"id": "apple-web", "name": "Web sign-in with Apple", "steps": [
      {"ref": "M:app/Http/AppleController.php", "side": "new", "lines": "12-30", "note": "Starts the redirect"}, …]}]

A step's `ref` names a file as any overlay reference does (`KEY:path`; a parent's key for a PR split into parts), not a
`#group`; `side` is "new" (the default: the file at the PR's tip) or "old" (at its base); `lines` is one line or a
range on that side ("12", "12-30"), and without it the step opens the whole file; `note` (report language) says what
to look at, in 80 characters or fewer. At most 8 tours of 3 to 15 steps each; a tour id takes the form of an area's.

build_graph.py resolves each step to a node: the PR's node of that file, for a parent's key the last part that changes
the file on the new side (its tip has the PR tip's version) and the first one on the old side (its start has the
base's), and reads the step's lines with `git show` (new side: the PR's tip; old side: its base). It writes
graphs.json "tours": [{"id", "name", "steps": [{"node", "path", "side", "a", "b", "note", "ref", "lines", "code"}]}],
where `ref` and `lines` are the step as authored and `code` the lines a..b held when the step was resolved. An unknown
PR key, a path no node of the PR has, a file missing on the step's side, and lines outside the file stop it.

Relocation: with `--previous` (refresh.py passes the graphs.json the build replaces) a step whose tour, ref, side, and
lines are unchanged follows its previous code with assess() and locate(), a port of the viewer's note matcher (exact,
then white space ignored, then the window most like it by character-bigram Dice of at least 0.8, clearly ahead of every
other; tests/test_pr_review_map.py runs both on the same vectors): code still at its lines keeps them, code found once
elsewhere moves the step there ("moved 12-30 -> 18-36"), anything else leaves it stale (`stale: true`: the viewer opens
the file) with its previous code and lines kept for the next refresh. The overlay is never rewritten.

validate.py and assemble.py check the result with problems(). Python 3 standard library only.
"""

from __future__ import annotations

import re

import manifest

MAX_TOURS, MIN_STEPS, MAX_STEPS, NOTE_MAX = 8, 3, 15, 80
LINES = re.compile(r"([1-9][0-9]{0,6})(?:-([1-9][0-9]{0,6}))?")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SIDES = ("new", "old")
# The viewer's matcher, kept in step with assets/viewer.html (locate(), assess()): JavaScript's \s, and lengths and
# character bigrams counted in UTF-16 code units, as JavaScript strings count them.
WS = re.compile("[\t\n\v\f\r    -     　﻿]+")
FUZZ, FUZZ_GAP, MIN_SIG, MIN_FUZZY = 0.8, 0.05, 6, 12
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def bare(text: str) -> str:
    return WS.sub("", text)


def units(text: str) -> list[bytes]:
    data = text.encode("utf-16-le", "surrogatepass")
    return [data[i:i + 2] for i in range(0, len(data), 2)]


def grams(text: str) -> tuple[dict[bytes, int], int]:
    found: dict[bytes, int] = {}
    u = units(text)
    for i in range(len(u) - 1):
        key = u[i] + u[i + 1]
        found[key] = found.get(key, 0) + 1
    return found, max(0, len(u) - 1)


def dice(a: tuple[dict, int], b: tuple[dict, int]) -> float:
    shared = sum(min(count, b[0][key]) for key, count in a[0].items() if key in b[0])
    return 2 * shared / (a[1] + b[1]) if a[1] + b[1] else 1


def locate(rows: list[tuple[int, str]], snap: list[str]) -> dict | None:
    """Where the lines `snap` sit among `rows` ([(line, text)]): {i, how} for a unique match (how: exact, ws, fuzzy),
    {amb: True} when the first tier that matches matches more than once, None for none (the viewer's locate())."""
    size, windows = len(snap), len(rows) - len(snap) + 1
    if not size or windows < 1 or len(units(bare("".join(snap)))) < MIN_SIG:
        return None
    for how, form in (("exact", str), ("ws", bare)):
        want = [form(s) for s in snap]
        hits = [i for i in range(windows) if all(form(rows[i + k][1]) == want[k] for k in range(size))]
        if len(hits) == 1:
            return {"i": hits[0], "how": how}
        if hits:
            return {"amb": True}
    target = bare("".join(snap))
    if len(units(target)) < MIN_FUZZY:
        return None
    goal, scores, best = grams(target), [], 0
    for i in range(windows):
        scores.append(dice(grams(bare("".join(text for _line, text in rows[i:i + size]))), goal))
        if scores[i] > scores[best]:
            best = i
    if scores[best] < FUZZ:
        return None
    if any(abs(i - best) >= size and scores[i] >= scores[best] - FUZZ_GAP for i in range(windows)):
        return {"amb": True}
    return {"i": best, "how": "fuzzy"}


def code_at(rows: list[tuple[int, str]], a: int, b: int) -> list[str]:
    out, previous = [], None
    for line, text in rows:
        if a <= line <= b:
            if previous is not None and line != previous + 1:
                out.append("…")
            out.append(text)
            previous = line
    return out


def assess(rows: list[tuple[int, str]], a: int, b: int, code: list[str] | None) -> dict:
    """The state of lines a..b written on `code` among `rows` now (the viewer's assess() for a line note): {st: ok},
    {st: moved, a, b, how}, or {st: stale}."""
    code = [str(x) for x in code] if isinstance(code, list) else []
    now, snap = code_at(rows, a, b), [x for x in code if x != "…"]
    if not snap:
        return {"st": "ok" if now else "stale"}
    if "\n".join(now) == "\n".join(code) and len(now) == len(code):
        return {"st": "ok"}
    match = locate(rows, snap)
    if match and not match.get("amb"):
        first, last = rows[match["i"]][0], rows[match["i"] + len(snap) - 1][0]
        if (first, last) != (a, b):
            return {"st": "moved", "a": first, "b": last, "how": match["how"]}
    return {"st": "stale"}


def span(a, b) -> str:
    return str(a) if a == b else f"{a}-{b}"


def text_ok(value) -> bool:
    return isinstance(value, str) and not CONTROL.search(value)


def read(overlay: dict) -> tuple[list[dict], list[str]]:
    """The overlay's tours, checked for shape: ([{id, name, steps: [{ref, side, lines, a, b, note}]}], warnings).
    SystemExit names the first problem."""
    raw = overlay.get("tours", [])
    if not isinstance(raw, list):
        raise SystemExit('overlay "tours" must be a list: [{"id": "flow", "name": "…", "steps": [{"ref": "KEY:path", …}]}]')
    if len(raw) > MAX_TOURS:
        raise SystemExit(f"overlay tours: {len(raw)} tours; give at most {MAX_TOURS}, one per distinct flow")
    out, warnings, seen = [], [], set()
    for number, tour in enumerate(raw, 1):
        if not isinstance(tour, dict):
            raise SystemExit(f"overlay tour {number} must be an object with an id, a name, and steps")
        tid, name, steps = tour.get("id"), tour.get("name", tour.get("id")), tour.get("steps")
        if not isinstance(tid, str) or not manifest.CLUSTER.fullmatch(tid):
            raise SystemExit(f"overlay tour {number}: id {tid!r} must be up to 40 letters, digits, '_', '.', or '-', starting with a letter or digit")
        if tid in seen:
            raise SystemExit(f"overlay tour {tid!r} is defined twice")
        seen.add(tid)
        if not text_ok(name) or not name.strip():
            raise SystemExit(f"overlay tour {tid!r}: name must be non-empty text")
        if not isinstance(steps, list) or not MIN_STEPS <= len(steps) <= MAX_STEPS:
            count = len(steps) if isinstance(steps, list) else "no list of"
            raise SystemExit(f"overlay tour {tid!r}: {count} steps; a tour has {MIN_STEPS} to {MAX_STEPS}")
        parsed = []
        for index, step in enumerate(steps, 1):
            where = f"overlay tour {tid!r} step {index}"
            if not isinstance(step, dict) or not isinstance(step.get("ref"), str) or ":" not in step["ref"]:
                raise SystemExit(f"{where}: needs a ref (KEY:path)")
            side, lines, note = step.get("side", "new"), step.get("lines"), step.get("note", "")
            if side not in SIDES:
                raise SystemExit(f"{where}: side {side!r} must be \"new\" or \"old\"")
            a = b = None
            if lines is not None:
                match = LINES.fullmatch(lines) if isinstance(lines, str) else None
                a, b = (int(match.group(1)), int(match.group(2) or match.group(1))) if match else (0, -1)
                if not match or b < a:
                    raise SystemExit(f"{where}: lines {lines!r} must be a line or a range on the step's side (\"12\" or \"12-30\")")
            if not text_ok(note):
                raise SystemExit(f"{where}: note must be text without control characters")
            if len(note) > NOTE_MAX:
                warnings.append(f"{where}: note has {len(note)} characters; keep it to {NOTE_MAX} so the tour bar shows it whole")
            parsed.append({"ref": step["ref"], "side": side, "lines": lines, "a": a, "b": b, "note": note.strip()})
        out.append({"id": tid, "name": name.strip(), "steps": parsed})
    return out, warnings


def previous_steps(graph) -> dict[tuple, list[dict]]:
    """The steps of a previous graphs.json by (tour id, ref, side, lines as authored), in order; malformed data gives none."""
    found: dict[tuple, list[dict]] = {}
    tours = graph.get("tours") if isinstance(graph, dict) else None
    for tour in tours if isinstance(tours, list) else []:
        if not isinstance(tour, dict) or not isinstance(tour.get("steps"), list):
            continue
        for step in tour["steps"]:
            if isinstance(step, dict) and isinstance(step.get("ref"), str):
                found.setdefault((tour.get("id"), step["ref"], step.get("side", "new"), step.get("lines")), []).append(step)
    return found


def place(spec: dict, rows: list[str], previous: dict | None, where: str) -> tuple[dict, str | None]:
    """A step's lines now ({a, b, code}, {stale, code}, or {} for a whole-file step) and what to print about them.

    `rows` are the file's lines on the step's side, `previous` the step as the build before resolved it. A previous
    step with code is followed (assess()); without one the authored lines are taken as they are, and lines past the end
    of the file stop the build."""
    if spec["a"] is None:
        return {}, None
    numbered = list(enumerate(rows, 1))
    code = previous.get("code") if isinstance(previous, dict) else None
    if isinstance(code, list) and code and all(isinstance(x, str) for x in code):
        pa, pb = previous.get("a"), previous.get("b")
        known = isinstance(pa, int) and isinstance(pb, int) and not isinstance(pa, bool) and not isinstance(pb, bool) and 1 <= pa <= pb
        state = assess(numbered, pa if known else 0, pb if known else -1, code)
        was = span(pa, pb) if known else spec["lines"]
        if state["st"] == "ok" and known:
            return {"a": pa, "b": pb, "code": code}, None
        if state["st"] == "moved":
            a, b = state["a"], state["b"]
            return {"a": a, "b": b, "code": rows[a - 1:b]}, f"{where}: moved {was} → {span(a, b)} ({state['how']})"
        # A stale step keeps where its code was last seen, so the next refresh compares with that place as the viewer does.
        return {**({"a": pa, "b": pb} if known else {}), "stale": True, "code": code}, (
            f"{where}: stale, the code it was written on (at {was}) is gone; the step opens the whole file until its lines in the "
            "overlay are updated")
    if spec["b"] > len(rows):
        raise SystemExit(f"{where}: lines {spec['lines']} are outside the file ({len(rows)} lines on the {spec['side']} side)")
    return {"a": spec["a"], "b": spec["b"], "code": rows[spec["a"] - 1:spec["b"]]}, None


def file_lines(text: str) -> list[str]:
    """A file's lines as git numbers them (split on newlines only; a final newline ends the last line)."""
    lines = text.split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def hunk_spans(diff: str, side: str) -> list[tuple[int, int]]:
    """The line ranges the hunks of a diff cover on one side."""
    out = []
    for line in str(diff).split("\n"):
        match = HUNK.match(line)
        if match:
            start, count = (match.group(1), match.group(2)) if side == "old" else (match.group(3), match.group(4))
            count = 1 if count is None else int(count)
            if count:
                out.append((int(start), int(start) + count - 1))
    return out


def problems(graph, diffs, tour_ids_used: list[str] = ()) -> tuple[list[str], list[str]]:
    """Errors and warnings about graphs.json "tours" (validate.py, assemble.py): the shape, at most 8 tours of 3 to 15
    steps, each step's node known and its path a file of that node in the diff data, and (warning) lines outside every
    hunk on their side. `tour_ids_used` are the ids the narrative's data-tour buttons name (warning when unknown)."""
    errors: list[str] = []
    warnings: list[str] = []
    tours = graph.get("tours") if isinstance(graph, dict) else None
    known_ids: set[str] = set()
    if tours is not None:
        if not isinstance(tours, list):
            return ['graphs.json "tours" must be a list of {"id", "name", "steps"}'], []
        if len(tours) > MAX_TOURS:
            errors.append(f"{len(tours)} tours; at most {MAX_TOURS}")
        prs = graph.get("prs") if isinstance(graph.get("prs"), list) else []
        nodes = {node["id"]: node for pr in prs if isinstance(pr, dict) and isinstance(pr.get("nodes"), list)
                 for node in pr["nodes"] if isinstance(node, dict) and isinstance(node.get("id"), str)}
        for number, tour in enumerate(tours, 1):
            tid = tour.get("id") if isinstance(tour, dict) else None
            if not isinstance(tid, str) or not manifest.CLUSTER.fullmatch(tid) or tid in known_ids:
                errors.append(f"tour {number}: id {tid!r} is missing, malformed, or used twice")
                continue
            known_ids.add(tid)
            steps = tour.get("steps")
            if not isinstance(tour.get("name"), str) or not tour["name"].strip():
                errors.append(f"tour {tid}: needs a name")
            if not isinstance(steps, list) or not MIN_STEPS <= len(steps) <= MAX_STEPS:
                errors.append(f"tour {tid}: needs {MIN_STEPS} to {MAX_STEPS} steps")
                continue
            for index, step in enumerate(steps, 1):
                errors_before = len(errors)
                where = f"tour {tid} step {index}"
                if not isinstance(step, dict):
                    errors.append(f"{where}: must be an object")
                    continue
                node = nodes.get(step["node"]) if isinstance(step.get("node"), str) else None
                path, side = step.get("path"), step.get("side", "new")
                a, b = step.get("a"), step.get("b")
                if node is None:
                    errors.append(f"{where}: unknown node {step.get('node')!r}")
                    continue
                if side not in SIDES:
                    errors.append(f"{where}: side must be \"new\" or \"old\"")
                if (a is None) != (b is None) or (a is not None and not (isinstance(a, int) and isinstance(b, int)
                                                                           and not isinstance(a, bool) and not isinstance(b, bool) and 1 <= a <= b)):
                    errors.append(f"{where}: a and b must be line numbers with 1 <= a <= b, or both absent")
                if not isinstance(step.get("note", ""), str) or ("code" in step and not (
                        isinstance(step["code"], list) and all(isinstance(x, str) for x in step["code"]))):
                    errors.append(f"{where}: note must be text and code a list of lines")
                entries = diffs.get(node.get("id")) if isinstance(diffs, dict) else None
                diffed = {e["path"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("path"), str)} if isinstance(entries, list) else {}
                if not isinstance(path, str):
                    owned = False
                elif isinstance(diffs, dict) and not node.get("unchanged"):
                    owned = path in diffed
                else:
                    owned = path in (node.get("files") or [node.get("path")])
                if not owned:
                    errors.append(f"{where}: {path!r} is not a file of node {node.get('id')} in the diff data")
                    continue
                if len(errors) == errors_before and isinstance(a, int) and side in SIDES and not step.get("stale"):
                    covered = hunk_spans(diffed[path].get("diff", ""), side) if path in diffed else []
                    if not any(start <= b and a <= end for start, end in covered):
                        warnings.append(f"{where} ({path}:{span(a, b)}, {side} side): outside every hunk of its diff; the viewer opens the whole file")
    for tid in sorted(set(tour_ids_used) - known_ids):
        warnings.append(f"the narrative's data-tour button {tid!r} names no tour; the viewer hides it")
    return errors, warnings
