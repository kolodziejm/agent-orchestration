#!/usr/bin/env python3
"""Before/after screenshots for a review map: collect them from a PR, and check a screens.json.

Screenshots are taken only when the user asks for them (references/screenshots.md); this script never captures anything.

Usage:
  python3 screens.py from-pr --repo OWNER/NAME --pr N --out DIR [--key KEY] [--tip SHA]
  python3 screens.py check FILE

from-pr lists the image URLs in the PR's description and in its comments (markdown images, <img src>, and GitHub
user-attachments links), downloads each GitHub-hosted one with the `gh` login, and writes DIR/screens/<n>.<ext> plus a draft
DIR/screens.json with one entry per image (its URL in `_from`, the alt text in `_alt`). The draft has no title, PR key, or
pairing yet: the agent pairs the images into before/after entries and labels them, then runs `check`. It only reads
(`gh api` GET calls and downloads), never posts. An image it cannot download (another host, an error, not a PNG, JPEG, or
WebP, over 10 MB) is skipped with a warning. The `gh` token goes only to GitHub hosts and is dropped on a redirect to another.

check validates a screens.json (assemble.py --screens runs the same checks):
  {"screens": [{"id", "title", "pr", "before": path|null, "after": path|null, "note"?, "viewport"?: desktop|mobile,
                "source"?: pr-body|preview|local, "tip"?: sha}]}
Paths are relative to the file and stay inside its directory. `before: null` is a new screen, `after: null` a removed one;
not both. Every image must start with the PNG, JPEG, or WebP magic bytes: SVG (it can carry script) and anything else is
refused, and a downloaded image is treated as untrusted data. An image over 600 KB is a warning, a total over 8 MB an error
(the page must stay under the artifact's 16 MB), more than 8 pairs a warning. Exit 0 when there is no error.
Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # importing manifest.py must not leave a __pycache__ in the skill
import manifest  # noqa: E402

WARN_BYTES = 600 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_PAIRS = 8
MAX_DOWNLOAD = 10 * 1024 * 1024
MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
EXT = {"png": "png", "jpeg": "jpg", "webp": "webp"}
VIEWPORTS = ("desktop", "mobile")
SOURCES = ("pr-body", "preview", "local")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,59}")
SHA = re.compile(r"[0-9a-f]{7,40}")
KNOWN = {"id", "title", "pr", "before", "after", "note", "viewport", "source", "tip"}
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
GITHUB_HOSTS = ("github.com", "githubusercontent.com")


def sniff(data: bytes) -> str | None:
    """The image kind (png, jpeg, webp) the leading bytes say, else None (SVG, GIF, HTML, and the rest are not images here)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def data_uri(kind: str, data: bytes) -> str:
    return f"data:{MIME[kind]};base64," + base64.b64encode(data).decode("ascii")


def text_ok(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not re.search(r"[\x00-\x1f\x7f]", value)


def load(path: Path) -> list:
    """The `screens` list of a screens.json; SystemExit names a file that is not one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"{path}: cannot read as JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("screens"), list):
        raise SystemExit(f'{path}: expected {{"screens": [...]}}')
    return data["screens"]


def images_of(path: Path, screens: list, errors: list[str], warnings: list[str]) -> dict[str, tuple[str, bytes]]:
    """{path as written: (kind, bytes)} of every image the entries name; a bad one is an error and absent. Warns about sizes."""
    base = path.resolve().parent
    found: dict[str, tuple[str, bytes]] = {}
    total = 0
    for item in screens:
        if not isinstance(item, dict):
            continue
        for side in ("before", "after"):
            rel = item.get(side)
            if not isinstance(rel, str) or rel in found:
                continue
            where = f"{item.get('id', '?')}.{side}"
            target = (base / rel)
            if Path(rel).is_absolute() or not manifest.inside(base, target):
                errors.append(f"{where}: {rel!r} must be a relative path inside {base}")
                continue
            if target.is_symlink() or not target.is_file():
                errors.append(f"{where}: {rel!r} is not a file")
                continue
            try:
                data = target.read_bytes()
            except OSError as error:
                errors.append(f"{where}: cannot read {rel!r}: {error}")
                continue
            kind = sniff(data)
            if kind is None:
                errors.append(f"{where}: {rel!r} is not a PNG, JPEG, or WebP image (an SVG or any other format is refused)")
                continue
            if len(data) > WARN_BYTES:
                warnings.append(f"{where}: {rel!r} is {len(data) // 1024} KB; over {WARN_BYTES // 1024} KB, save it as JPEG (quality ~80) or WebP")
            total += len(data)
            found[rel] = (kind, data)
    if total > MAX_TOTAL:
        errors.append(f"the images total {total / 1024 / 1024:.1f} MB; over {MAX_TOTAL // 1024 // 1024} MB the page would pass the artifact's 16 MB limit")
    return found


def problems(path: Path, screens: list) -> tuple[list[str], list[str], list[dict]]:
    """(errors, warnings, entries) of a screens list read from `path`. Each entry has `before` and `after` as data URIs
    (None for no image); only a list without an error should be embedded."""
    errors: list[str] = []
    warnings: list[str] = []
    entries: list[dict] = []
    seen: set[str] = set()
    if not screens:
        errors.append("screens is empty")
    if len(screens) > MAX_PAIRS:
        warnings.append(f"{len(screens)} pairs; keep to about {MAX_PAIRS}, the screens the change affects")
    images = images_of(path, screens, errors, warnings)
    for index, item in enumerate(screens):
        if not isinstance(item, dict):
            errors.append(f"screen #{index + 1} must be an object")
            continue
        ident = item.get("id")
        name = ident if isinstance(ident, str) else f"#{index + 1}"
        if not (isinstance(ident, str) and ID.fullmatch(ident)):
            errors.append(f"screen {name}: id must be letters, digits, '_', '.', '-' (at most 60)")
        elif ident in seen:
            errors.append(f"screen {name}: id is used twice")
        else:
            seen.add(ident)
        if not text_ok(item.get("title"), 200):
            errors.append(f"screen {name}: title must be text of at most 200 characters")
        if not (isinstance(item.get("pr"), str) and manifest.KEY.fullmatch(item["pr"])):
            errors.append(f"screen {name}: pr must be the key of a PR of the map (letters, digits, '_' or '-')")
        for side in ("before", "after"):
            if side not in item:
                errors.append(f'screen {name}: "{side}" is missing (a path, or null for {"a new" if side == "before" else "a removed"} screen)')
            elif item[side] is not None and not isinstance(item[side], str):
                errors.append(f'screen {name}: "{side}" must be a path or null')
        if item.get("before") is None and item.get("after") is None and "before" in item and "after" in item:
            errors.append(f"screen {name}: before and after are both null")
        if "note" in item and not text_ok(item["note"], 300):
            errors.append(f"screen {name}: note must be one line of text of at most 300 characters")
        if "viewport" in item and item["viewport"] not in VIEWPORTS:
            errors.append(f"screen {name}: viewport must be one of {', '.join(VIEWPORTS)}")
        if "source" in item and item["source"] not in SOURCES:
            errors.append(f"screen {name}: source must be one of {', '.join(SOURCES)}")
        if "tip" in item and not (isinstance(item["tip"], str) and SHA.fullmatch(item["tip"])):
            errors.append(f"screen {name}: tip must be a commit SHA (7 to 40 lowercase hex digits)")
        elif "tip" not in item:
            warnings.append(f"screen {name}: no tip; record the SHA the pair was taken at, so a later change can be flagged")
        extra = sorted(k for k in item if k not in KNOWN and not str(k).startswith("_"))
        if extra:
            warnings.append(f"screen {name}: unknown keys {extra}")
        entry = {k: item[k] for k in ("id", "title", "pr", "note", "viewport", "source", "tip") if isinstance(item.get(k), str)}
        for side in ("before", "after"):
            image = images.get(item.get(side)) if isinstance(item.get(side), str) else None
            entry[side] = data_uri(*image) if image else None
        entries.append(entry)
    return errors, warnings, entries


def embed(path: Path) -> tuple[list[dict], list[str]]:
    """The entries of a screens.json ready to embed (data URIs) and the warnings; SystemExit lists the errors."""
    errors, warnings, entries = problems(path, load(path))
    if errors:
        raise SystemExit(f"{path}: " + "; ".join(errors[:8]) + (f" (and {len(errors) - 8} more)" if len(errors) > 8 else ""))
    return entries, warnings


def tips_of(graph: dict) -> dict[str, str]:
    """{PR key: tip} of a graphs.json, a split PR's parent too."""
    return {item["key"]: str(item.get("tip") or "") for item in [*graph.get("prs", []), *(graph.get("parents") or [])]
            if isinstance(item, dict) and isinstance(item.get("key"), str)}


def same_tip(a: str, b: str) -> bool:
    """Whether two SHAs (either may be abbreviated, at least 7 digits) name the same commit."""
    a, b = a.lower(), b.lower()
    return len(a) >= 7 and len(b) >= 7 and (a.startswith(b) or b.startswith(a))


def stale_ids(screens: list, tips: dict[str, str]) -> list[str]:
    """The ids of the screens whose recorded `tip` is no longer the tip of their PR."""
    out = []
    for item in screens:
        if isinstance(item, dict) and isinstance(item.get("tip"), str) and isinstance(item.get("pr"), str):
            now = tips.get(item["pr"], "")
            if now and not same_tip(item["tip"], now):
                out.append(str(item.get("id")))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# from-pr

MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(\s*<?([^\s)>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
IMG_ALT = re.compile(r"""\balt\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
ATTACHMENT = re.compile(
    r"https://(?:github\.com/user-attachments/assets/[0-9A-Za-z._-]+"
    r"|github\.com/[\w.-]+/[\w.-]+/assets/\d+/[0-9A-Za-z._-]+"
    r"|(?:private-)?user-images\.githubusercontent\.com/[^\s)\"'<>\]]+)")


def image_urls(text: str) -> list[tuple[str, str]]:
    """[(url, alt text)] of the images in a PR body or comment, in order of appearance, without repeats: markdown images,
    <img src> tags, and bare GitHub user-attachment links. Only http(s) addresses count. Pure: no network."""
    found: list[tuple[int, str, str]] = []
    for match in MD_IMAGE.finditer(text):
        found.append((match.start(), match.group(2), match.group(1)))
    for match in IMG_TAG.finditer(text):
        src = IMG_SRC.search(match.group(0))
        alt = IMG_ALT.search(match.group(0))
        if src:
            found.append((match.start(), next(g for g in src.groups() if g is not None), next((g for g in (alt.groups() if alt else ()) if g is not None), "")))
    for match in ATTACHMENT.finditer(text):
        found.append((match.start(), match.group(0), ""))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _at, url, alt in sorted(found, key=lambda f: f[0]):
        url = url.replace("&amp;", "&").strip()
        if not re.match(r"https?://", url, re.IGNORECASE) or url in seen:
            continue
        seen.add(url)
        out.append((url, alt.strip()))
    return out


def github_host(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in GITHUB_HOSTS)


def gh_json_lines(args: list[str]) -> list[str]:
    """The strings a read-only `gh api GET` prints with `--jq`, one JSON string per line."""
    result = subprocess.run(["gh", "api", "--method", "GET", "--paginate", *args], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"gh api {args[-1] if args else ''} failed: {result.stderr.strip()[:300]}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def pr_texts(repo: str, number: int) -> list[tuple[str, str]]:
    """[(where, text)]: the PR description, then its conversation comments, review comments, and review summaries."""
    texts = [("the description", t or "") for t in gh_json_lines([f"repos/{repo}/pulls/{number}", "--jq", ".body | tojson"])]
    for label, path in (("comment", f"repos/{repo}/issues/{number}/comments"), ("review comment", f"repos/{repo}/pulls/{number}/comments"),
                        ("review", f"repos/{repo}/pulls/{number}/reviews")):
        texts += [(f"{label} {i}", t or "") for i, t in enumerate(gh_json_lines([path, "--jq", ".[] | .body | tojson"]), 1)]
    return texts


class DropAuthOnForeignRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect but sends the token only to GitHub hosts (an attachment redirects to a signed storage URL)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (not github_host(newurl) or not newurl.startswith("https://")):
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def download(url: str, token: str | None) -> bytes:
    """The bytes at an https GitHub URL (at most MAX_DOWNLOAD), authenticated with the `gh` token for GitHub hosts."""
    if not url.startswith("https://") or not github_host(url):
        raise ValueError("not a GitHub-hosted https address; download it yourself and list it in screens.json")
    request = urllib.request.Request(url, headers={"User-Agent": "pr-review-map-screens"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(DropAuthOnForeignRedirect)
    with opener.open(request, timeout=30) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError(f"over {MAX_DOWNLOAD // 1024 // 1024} MB")
    return data


def gh_token() -> str | None:
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() or None if result.returncode == 0 else None


def collect(texts: list[tuple[str, str]], fetch, out: Path, key: str = "", tip: str = "", warn=print) -> list[dict]:
    """Download the images in `texts` ([(where, text)]) with `fetch(url) -> bytes`, write them under out/screens/, and return the
    draft entries (also written to out/screens.json). An image that cannot be fetched or is not PNG/JPEG/WebP is skipped
    with a warning."""
    folder = out / "screens"
    folder.mkdir(parents=True, exist_ok=True)
    draft: list[dict] = []
    seen: set[str] = set()
    for where, text in texts:
        for url, alt in image_urls(text):
            if url in seen:
                continue
            seen.add(url)
            try:
                data = fetch(url)
            except (OSError, ValueError, urllib.error.URLError) as error:
                warn(f"warning: skipped {url} ({where}): {error}")
                continue
            kind = sniff(data)
            if kind is None:
                warn(f"warning: skipped {url} ({where}): not a PNG, JPEG, or WebP image")
                continue
            number = len(draft) + 1
            name = f"{number:02d}-{hashlib.sha256(data).hexdigest()[:8]}.{EXT[kind]}"
            (folder / name).write_bytes(data)
            draft.append({"id": f"img-{number}", "title": alt or f"Image {number}", "pr": key, "before": None, "after": f"screens/{name}",
                          "source": "pr-body", **({"tip": tip} if tip else {}), "_from": url, "_alt": alt, "_where": where})
    (out / "screens.json").write_text(json.dumps({"screens": draft}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return draft


def cmd_from_pr(args: argparse.Namespace) -> int:
    if not REPO.fullmatch(args.repo) or args.repo.startswith("-"):
        raise SystemExit(f"--repo {args.repo!r} must be OWNER/NAME")
    if args.key and not manifest.KEY.fullmatch(args.key):
        raise SystemExit(f"--key {args.key!r} must be letters, digits, '_' or '-'")
    if args.tip and not SHA.fullmatch(args.tip):
        raise SystemExit(f"--tip {args.tip!r} must be a commit SHA (7 to 40 lowercase hex digits)")
    texts = pr_texts(args.repo, args.pr)
    token = gh_token()
    if not token:
        print("warning: no `gh auth token`; private attachments will fail to download")
    draft = collect(texts, lambda url: download(url, token), args.out, args.key or "", args.tip or "")
    found = sum(len(image_urls(t)) for _w, t in texts)
    print(f"wrote {args.out / 'screens.json'}: {len(draft)} of {found} image(s) downloaded into {args.out / 'screens'}")
    print("next: pair the images into before/after entries, give each a title, pr, viewport, and tip, then run: "
          f"python3 {Path(__file__).resolve()} check {args.out / 'screens.json'}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    errors, warnings, _entries = problems(args.file, load(args.file))
    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}")
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print(f"OK ({len(warnings)} warning(s))" if warnings else "OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("from-pr", help="download the images of a PR's description and comments into a draft screens.json")
    one.add_argument("--repo", required=True, metavar="OWNER/NAME")
    one.add_argument("--pr", required=True, type=int)
    one.add_argument("--out", required=True, type=Path)
    one.add_argument("--key", help="the PR's key in the map, written into each draft entry")
    one.add_argument("--tip", help="the tip SHA the images describe, written into each draft entry")
    one.set_defaults(run=cmd_from_pr)
    two = sub.add_parser("check", help="validate a screens.json and its images")
    two.add_argument("file", type=Path)
    two.set_defaults(run=cmd_check)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
