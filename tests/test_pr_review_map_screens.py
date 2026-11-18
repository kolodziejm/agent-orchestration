"""Behavioral contracts for the pr-review-map screenshots: scripts/screens.py, assemble.py --screens, refresh.py, validate.py.

Screenshots are taken only on the user's request (references/screenshots.md); these tests cover what happens once there is a
screens.json: reading the images out of a PR's text, checking the file and its images, embedding them in the page, replaying
that from the manifest, marking a pair taken at an old tip, and validating the data block. The scripts run as the skill runs
them, as separate processes against a real git repository; the network is never used. Images are a few bytes generated here.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pr-review-map"
SCRIPTS = SKILL / "scripts"
ENV = {
    **os.environ,
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def png_bytes(width: int = 2, height: int = 2, colour: tuple[int, int, int] = (200, 40, 40)) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
WEBP = b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8 " + b"\x00" * 8
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
GIF = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"


def run_script(name: str, *args: object, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True, env=ENV)
    if check and result.returncode != 0:
        raise AssertionError(f"{name} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV, check=True).stdout


def commit_files(repo: Path, files: dict[str, str], message: str) -> None:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def screens_module():
    flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    sys.path.insert(0, str(SCRIPTS))
    try:
        return __import__("screens")
    finally:
        sys.path.remove(str(SCRIPTS))
        sys.dont_write_bytecode = flag


def data_block(page: str, ident: str):
    match = re.search(rf'<script type="application/json" id="{ident}">(.*?)</script>', page, re.DOTALL)
    return json.loads(match.group(1)) if match else None


def write_screens(folder: Path, pairs: list[dict], images: dict[str, bytes] | None = None) -> Path:
    (folder / "screens").mkdir(parents=True, exist_ok=True)
    for name, data in (images or {"welcome-before.png": png_bytes(colour=(200, 40, 40)), "welcome-after.png": png_bytes(colour=(40, 40, 200)),
                       "new-after.jpg": JPEG}).items():
        (folder / "screens" / name).write_bytes(data)
    path = folder / "screens.json"
    path.write_text(json.dumps({"screens": pairs}), encoding="utf-8")
    return path


class ImageUrlTests(unittest.TestCase):
    def test_image_urls_are_read_from_markdown_html_and_attachment_links(self):
        """This test will fail when image_urls stops finding markdown images (with or without a title), <img src> tags in either quote style, or bare GitHub user-attachments links, keeps a repeated URL, or lets a non-http address through."""
        screens = screens_module()
        body = (
            "Before and after:\n"
            '![Welcome before](https://github.com/user-attachments/assets/11111111-aaaa "the old one")\n'
            "<img width=\"600\" alt='Welcome after' src=\"https://github.com/user-attachments/assets/22222222-bbbb\">\n"
            "and https://github.com/user-attachments/assets/33333333-cccc on its own,\n"
            "an old one https://github.com/acme/app/assets/12345/44444444-dddd and <img src=https://user-images.githubusercontent.com/1/5.png>\n"
            "a repeat ![again](https://github.com/user-attachments/assets/11111111-aaaa)\n"
            "![inline](data:image/png;base64,AAAA) ![local](./shot.png) [a link](https://example.com/page)\n"
            '<img src="https://cdn.example.com/a.png?x=1&amp;y=2" alt="Ext">\n'
        )
        self.assertEqual(screens.image_urls(body), [
            ("https://github.com/user-attachments/assets/11111111-aaaa", "Welcome before"),
            ("https://github.com/user-attachments/assets/22222222-bbbb", "Welcome after"),
            ("https://github.com/user-attachments/assets/33333333-cccc", ""),
            ("https://github.com/acme/app/assets/12345/44444444-dddd", ""),
            ("https://user-images.githubusercontent.com/1/5.png", ""),
            ("https://cdn.example.com/a.png?x=1&y=2", "Ext"),
        ])
        self.assertEqual(screens.image_urls(""), [])
        self.assertEqual(screens.image_urls("no images, only [a link](https://example.com/x.png)"), [])

    def test_only_github_hosts_get_the_token_and_a_foreign_redirect_drops_it(self):
        """This test will fail when download accepts a non-GitHub or non-https address, or a redirect to another host keeps the Authorization header."""
        screens = screens_module()
        for url in ("https://cdn.example.com/a.png", "http://github.com/x", "https://github.com.evil.example/a.png"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    screens.download(url, "secret")
        handler = screens.DropAuthOnForeignRedirect()
        request = urllib.request.Request("https://github.com/user-attachments/assets/x", headers={"Authorization": "Bearer secret"})
        same = handler.redirect_request(request, None, 302, "Found", {}, "https://private-user-images.githubusercontent.com/x?jwt=1")
        self.assertEqual(same.get_header("Authorization"), "Bearer secret")
        other = handler.redirect_request(request, None, 302, "Found", {}, "https://bucket.s3.amazonaws.com/x?sig=1")
        self.assertIsNone(other.get_header("Authorization"))

    def test_collect_downloads_what_it_can_and_skips_the_rest_with_a_warning(self):
        """This test will fail when from-pr keeps an SVG or another non-image, stops at a download error instead of skipping it, writes a file under a name that is not its own hash and type, or leaves the draft screens.json out."""
        screens = screens_module()
        pages = {
            "https://github.com/user-attachments/assets/a": png_bytes(),
            "https://github.com/user-attachments/assets/b": SVG,
            "https://github.com/user-attachments/assets/c": OSError("HTTP 404"),
            "https://github.com/user-attachments/assets/d": JPEG,
            "https://cdn.example.com/e.png": ValueError("not a GitHub-hosted https address"),
        }

        def fetch(url):
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return value

        texts = [("the description", " ".join(f"![shot {i}]({u})" for i, u in enumerate(pages, 1))), ("comment 1", "![again](https://github.com/user-attachments/assets/a)")]
        with tempfile.TemporaryDirectory() as temp:
            out, warnings = Path(temp), []
            draft = screens.collect(texts, fetch, out, key="O", tip="abc1234", warn=warnings.append)
            self.assertEqual([e["id"] for e in draft], ["img-1", "img-2"])
            self.assertEqual([e["_from"] for e in draft], ["https://github.com/user-attachments/assets/a", "https://github.com/user-attachments/assets/d"])
            self.assertEqual([e["title"] for e in draft], ["shot 1", "shot 4"])
            self.assertTrue(all(e["pr"] == "O" and e["tip"] == "abc1234" and e["before"] is None and e["source"] == "pr-body" for e in draft))
            self.assertTrue(draft[0]["after"].endswith(".png") and draft[1]["after"].endswith(".jpg"))
            self.assertEqual(sorted(p.name for p in (out / "screens").iterdir()), sorted(Path(e["after"]).name for e in draft))
            self.assertEqual(json.loads((out / "screens.json").read_text(encoding="utf-8"))["screens"], draft)
            self.assertEqual(len(warnings), 3)
            self.assertTrue(any("not a PNG, JPEG, or WebP" in w and "/assets/b" in w for w in warnings))
            self.assertTrue(any("404" in w for w in warnings))
            self.assertTrue(any("not a GitHub-hosted" in w for w in warnings))
            self.assertTrue(all(w.startswith("warning:") for w in warnings))

    def test_from_pr_refuses_a_repository_or_key_that_could_be_an_option(self):
        """This test will fail when from-pr passes a --repo, --key, or --tip that is not plain OWNER/NAME, a key, and a SHA on to gh."""
        for args in (["--repo", "-x/y"], ["--repo", "acme"], ["--repo", "a/b c"], ["--repo", "acme/app", "--key", "-k"], ["--repo", "acme/app", "--tip", "main"]):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as temp:
                result = run_script("screens.py", "from-pr", *args, "--pr", "1", "--out", temp, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr.strip(), args)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def pair(self, **fields) -> dict:
        return {"id": "welcome", "title": "Welcome", "pr": "O", "before": "screens/b.png", "after": "screens/a.png", "tip": "abc1234", **fields}

    def check(self, pairs: list[dict], images: dict[str, bytes] | None = None) -> subprocess.CompletedProcess:
        write_screens(self.dir, pairs, {"b.png": png_bytes(), "a.png": png_bytes(colour=(1, 2, 3))} if images is None else images)
        return run_script("screens.py", "check", self.dir / "screens.json", check=False)

    def test_a_valid_file_passes_with_png_jpeg_and_webp(self):
        """This test will fail when check refuses a well-formed screens.json, or one of the three allowed image types."""
        result = self.check([self.pair(), self.pair(id="new", before=None, after="screens/n.jpg"), self.pair(id="gone", before="screens/g.webp", after=None, viewport="mobile", source="local", note="one line")],
                            {"b.png": png_bytes(), "a.png": png_bytes(), "n.jpg": JPEG, "g.webp": WEBP})
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "OK"), result.stdout)

    def test_an_svg_or_an_unknown_format_is_refused_whatever_its_name(self):
        """This test will fail when check lets an SVG, a GIF, or HTML through (an SVG can carry script), or trusts the file extension instead of the first bytes."""
        for name, data in (("SVG", SVG), ("GIF", GIF), ("HTML", b"<html></html>"), ("empty", b""), ("truncated PNG", b"\x89PNG")):
            with self.subTest(name=name):
                result = self.check([self.pair()], {"b.png": data, "a.png": png_bytes()})
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("is not a PNG, JPEG, or WebP image", result.stdout)
                self.assertIn("welcome.before", result.stdout)

    def test_a_missing_file_an_escaping_path_and_a_symlink_are_errors(self):
        """This test will fail when check accepts a path to a missing file, an absolute path, one that leaves the directory, or a symlink."""
        result = self.check([self.pair(before="screens/nope.png")])
        self.assertEqual(result.returncode, 1)
        self.assertIn("'screens/nope.png' is not a file", result.stdout)
        outside = self.dir.parent / "outside-screen.png"
        outside.write_bytes(png_bytes())
        self.addCleanup(outside.unlink)
        for path in (str(outside), "../outside-screen.png"):
            with self.subTest(path=path):
                result = self.check([self.pair(before=path)])
                self.assertEqual(result.returncode, 1)
                self.assertIn("must be a relative path inside", result.stdout)
        write_screens(self.dir, [self.pair(before="screens/link.png")])
        (self.dir / "screens" / "inside.png").write_bytes(png_bytes())
        for target, message in ((outside, "must be a relative path inside"), (self.dir / "screens" / "inside.png", "is not a file")):
            with self.subTest(link=message):
                (self.dir / "screens" / "link.png").unlink(missing_ok=True)
                (self.dir / "screens" / "link.png").symlink_to(target)
                result = run_script("screens.py", "check", self.dir / "screens.json", check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stdout)

    def test_the_schema_is_checked(self):
        """This test will fail when check accepts an entry without a title or PR key, with a bad id, a repeated id, both images null, a bad viewport or source, a multi-line note, or a malformed tip, or stops warning about a missing tip and unknown keys."""
        cases = {
            "title must be text": self.pair(title=" "),
            "pr must be the key": self.pair(pr="-x"),
            "id must be letters": self.pair(id="a b"),
            "both null": self.pair(before=None, after=None),
            "viewport must be one of": self.pair(viewport="tablet"),
            "source must be one of": self.pair(source="camera"),
            "note must be one line": self.pair(note="a\nb"),
            "tip must be a commit SHA": self.pair(tip="main"),
        }
        for message, item in cases.items():
            with self.subTest(message=message):
                result = self.check([item])
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(message, result.stdout)
        result = self.check([self.pair(), self.pair()])
        self.assertEqual(result.returncode, 1)
        self.assertIn("id is used twice", result.stdout)
        missing = self.pair()
        del missing["after"]
        result = self.check([missing])
        self.assertEqual(result.returncode, 1)
        self.assertIn('"after" is missing', result.stdout)
        notip = self.pair(colour="red")
        del notip["tip"]
        result = self.check([notip])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("no tip", result.stdout)
        self.assertIn("unknown keys ['colour']", result.stdout)
        (self.dir / "screens.json").write_text('{"screens": "x"}', encoding="utf-8")
        result = run_script("screens.py", "check", self.dir / "screens.json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected {"screens"', result.stderr)

    def test_a_large_image_warns_and_a_large_total_is_an_error(self):
        """This test will fail when an image over 600 KB stops being a warning (it still passes), or a total over 8 MB stops being an error (the page would pass the artifact's 16 MB)."""
        big = png_bytes() + b"\x00" * (650 * 1024)
        result = self.check([self.pair()], {"b.png": big, "a.png": png_bytes()})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r"warning: welcome\.before: 'screens/b\.png' is 650 KB; over 600 KB")
        self.assertNotIn("a.png' is", result.stdout)
        huge = {f"{i}.png": png_bytes() + b"\x00" * (1024 * 1024) for i in range(9)}
        result = self.check([self.pair(id=f"p{i}", before=f"screens/{i}.png", after=None) for i in range(9)], huge)
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stdout, r"error: the images total 9\.\d MB; over 8 MB")
        self.assertIn("9 pairs; keep to about 8", result.stdout)
        self.assertEqual(result.stdout.count("over 600 KB"), 9)


class PageTests(unittest.TestCase):
    """A one-PR map built with screens, replayed by refresh.py, moved, and validated."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.repo = repo = cls.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"README.md": "# x\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(repo, {"web/welcome.ts": "export const welcome = 'Hello';\n", "web/settings.ts": "export const tabs = ['a'];\n"}, "feat: welcome")
        cls.tip = git(repo, "rev-parse", "feat").strip()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def build(self, name: str, *, screens: bool = True, pairs: list[dict] | None = None) -> Path:
        d = self.root / name
        d.mkdir()
        (d / "narrative.html").write_text(
            '<header><h1>Welcome</h1></header>\n<section id="brief" data-toc="Brief"><h2>Brief</h2><ul class="brief-users"><li>Users see a welcome.</li></ul></section>\n'
            '<!-- review-map:graph -->\n<section id="before-merging"><h2>Before merging</h2><p>None.</p></section>\n', encoding="utf-8")
        run_script("build_graph.py", "--out", d / "graphs.json", "--pr", "O", self.repo, "main...feat", "--name", "O", "O #1")
        run_script("gen_diffs.py", "--graph", d / "graphs.json", "--out", d / "diffs.json", "--pr", "O", self.repo, "main...feat", "--strict")
        args = ["--graph", d / "graphs.json", "--diffs", d / "diffs.json", "--narrative", d / "narrative.html", "--title", "Welcome", "--lang", "en",
                "--target", "local", "--out", d / "review.html"]
        if pairs is None:
            pairs = [{"id": "welcome", "title": "First-run welcome", "pr": "O", "before": "screens/welcome-before.png", "after": "screens/welcome-after.png",
                      "viewport": "desktop", "source": "preview", "tip": self.tip},
                     {"id": "new", "title": "Billing tab", "pr": "O", "before": None, "after": "screens/new-after.jpg", "note": "A new tab.", "tip": self.tip[:7]}]
        write_screens(d, pairs)
        if screens:
            args += ["--screens", d / "screens.json"]
        run_script("assemble.py", *args)
        return d

    def page(self, d: Path) -> str:
        return (d / "review.html").read_text(encoding="utf-8")

    def test_assemble_embeds_every_image_as_a_data_uri_and_records_the_file(self):
        """This test will fail when assemble.py --screens stops embedding the images as data URIs in a screens-data block (with a null for a missing side), loses a title, note, or PR name, marks a current pair stale, or does not record the path in review-map.json."""
        d = self.build("embed")
        page = self.page(d)
        block = data_block(page, "screens-data")
        self.assertEqual([e["id"] for e in block["screens"]], ["welcome", "new"])
        welcome, new = block["screens"]
        self.assertEqual(welcome["before"], "data:image/png;base64," + base64.b64encode((d / "screens" / "welcome-before.png").read_bytes()).decode())
        self.assertEqual(welcome["after"], "data:image/png;base64," + base64.b64encode((d / "screens" / "welcome-after.png").read_bytes()).decode())
        self.assertNotEqual(welcome["before"], welcome["after"])
        self.assertIsNone(new["before"])
        self.assertEqual(new["after"], "data:image/jpeg;base64," + base64.b64encode(JPEG).decode())
        self.assertEqual((welcome["title"], welcome["pr"], welcome["prName"], welcome["viewport"], welcome["source"], welcome["tip"], welcome["stale"]),
                         ("First-run welcome", "O", "O #1", "desktop", "preview", self.tip, False))
        self.assertEqual((new["note"], new["stale"]), ("A new tab.", False))
        self.assertTrue(page.index('id="diff-data"') < page.index('id="screens-data"'))
        self.assertEqual(json.loads((d / "review-map.json").read_text(encoding="utf-8"))["assemble"]["screens"], "screens.json")
        self.assertEqual(run_script("validate.py", d / "review.html").stdout.strip().splitlines()[-1], "OK")

    def test_a_page_without_screens_has_no_block_and_records_none(self):
        """This test will fail when a build without --screens leaves a screens-data block or a placeholder in the page, or records a screens path."""
        d = self.build("none", screens=False)
        page = self.page(d)
        self.assertNotIn("screens-data", page.split("<script>")[0])
        self.assertIsNone(data_block(page, "screens-data"))
        self.assertNotIn("{{SCREENS_BLOCK}}", page)
        self.assertIsNone(json.loads((d / "review-map.json").read_text(encoding="utf-8"))["assemble"]["screens"])

    def test_assemble_stops_on_a_bad_screens_file(self):
        """This test will fail when assemble.py embeds an SVG, a pair of a PR the map does not have, or a screens.json with an error, instead of stopping before it writes the page."""
        d = self.build("bad")
        out = d / "bad.html"
        base = ["--graph", d / "graphs.json", "--diffs", d / "diffs.json", "--narrative", d / "narrative.html", "--title", "Welcome", "--target", "local", "--out", out,
                "--no-manifest"]
        write_screens(d, [{"id": "x", "title": "X", "pr": "O", "before": "screens/x.png", "after": None, "tip": self.tip}], {"x.png": SVG})
        result = run_script("assemble.py", *base, "--screens", d / "screens.json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a PNG, JPEG, or WebP image", result.stderr)
        self.assertFalse(out.exists())
        write_screens(d, [{"id": "x", "title": "X", "pr": "Z", "before": "screens/x.png", "after": None, "tip": self.tip}], {"x.png": png_bytes()})
        result = run_script("assemble.py", *base, "--screens", d / "screens.json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a PR of graphs.json", result.stderr)
        self.assertFalse(out.exists())

    def test_refresh_replays_the_recorded_screens_and_picks_up_one_added_later(self):
        """This test will fail when refresh.py --assemble-only stops re-embedding the screens the manifest names (so an edit to screens.json shows), or ignores a screens.json that was added beside review-map.json after the first build."""
        d = self.build("replay")
        pairs = json.loads((d / "screens.json").read_text(encoding="utf-8"))["screens"]
        pairs[1]["note"] = "Edited note."
        (d / "screens.json").write_text(json.dumps({"screens": pairs}), encoding="utf-8")
        result = run_script("refresh.py", d, "--assemble-only")
        self.assertIn("OK", result.stdout)
        self.assertEqual(data_block(self.page(d), "screens-data")["screens"][1]["note"], "Edited note.")
        later = self.build("later", screens=False)
        self.assertIsNone(data_block(self.page(later), "screens-data"))
        (later / "screens.json").write_text(json.dumps({"screens": pairs}), encoding="utf-8")
        run_script("refresh.py", later, "--assemble-only")
        self.assertEqual([e["id"] for e in data_block(self.page(later), "screens-data")["screens"]], ["welcome", "new"])
        self.assertEqual(json.loads((later / "review-map.json").read_text(encoding="utf-8"))["assemble"]["screens"], "screens.json")
        self.assertEqual(run_script("validate.py", later / "review.html").stdout.strip().splitlines()[-1], "OK")

    def test_a_pair_taken_at_an_old_tip_is_marked_and_refresh_warns_when_the_branch_moves(self):
        """This test will fail when a pair whose tip is not its PR's is not marked stale in the page, a short tip of the current commit counts as stale, validate.py stops warning, or refresh.py does not warn when the branch moves past the pairs' tip."""
        old = [{"id": "old", "title": "Old", "pr": "O", "before": None, "after": "screens/welcome-after.png", "tip": "1234567"},
               {"id": "cur", "title": "Current", "pr": "O", "before": None, "after": "screens/welcome-after.png", "tip": self.tip[:7]}]
        d = self.build("stale", pairs=old)
        self.assertEqual([e["stale"] for e in data_block(self.page(d), "screens-data")["screens"]], [True, False])
        validated = run_script("validate.py", d / "review.html").stdout
        self.assertIn("warning: screens: old was taken at 1234567, but PR O has moved on", validated)
        self.assertNotIn("screens: cur", validated)
        self.assertEqual(validated.strip().splitlines()[-1], "OK")
        # The branch moves: every pair predates the code now, and refresh.py says so.
        moving = self.root / "moving"
        shutil.copytree(self.repo, moving / "repo")
        d = self.root / "refresh"
        d.mkdir()
        mrepo = moving / "repo"
        (d / "narrative.html").write_text('<header><h1>W</h1></header>\n<!-- review-map:graph -->\n<section id="before-merging"><h2>Before merging</h2></section>\n', encoding="utf-8")
        run_script("build_graph.py", "--out", d / "graphs.json", "--pr", "O", mrepo, "main...feat", "--name", "O", "O #1")
        run_script("gen_diffs.py", "--graph", d / "graphs.json", "--out", d / "diffs.json", "--pr", "O", mrepo, "main...feat", "--strict")
        tip1 = git(mrepo, "rev-parse", "feat").strip()
        write_screens(d, [{"id": "cur", "title": "Current", "pr": "O", "before": None, "after": "screens/welcome-after.png", "tip": tip1}])
        run_script("assemble.py", "--graph", d / "graphs.json", "--diffs", d / "diffs.json", "--narrative", d / "narrative.html", "--title", "W", "--target", "local",
                   "--out", d / "review.html", "--screens", d / "screens.json")
        self.assertEqual([e["stale"] for e in data_block(self.page(d), "screens-data")["screens"]], [False])
        calm = run_script("refresh.py", d).stdout
        self.assertNotIn("screenshots", calm)
        commit_files(mrepo, {"web/welcome.ts": "export const welcome = 'Hello again';\n"}, "fix: round 1")
        out = run_script("refresh.py", d).stdout
        self.assertRegex(out, r"warning: PR O: tip is now [0-9a-f]{7}, so the screenshots cur \(" + tip1[:7] + r"\) predate the code")
        self.assertEqual([e["stale"] for e in data_block(self.page(d), "screens-data")["screens"]], [True])
        self.assertIn("screens: cur was taken at " + tip1[:7], out)

    def test_validate_checks_the_screens_block(self):
        """This test will fail when validate.py accepts an image data URI of another type (SVG, GIF), bytes that are not the type they claim, a plain URL in place of a data URI, both sides null, or an unknown PR, or stops reading the block at all."""
        d = self.build("validate")
        page = self.page(d)
        block = data_block(page, "screens-data")
        welcome = block["screens"][0]

        def mutated(change) -> tuple[int, str]:
            data = json.loads(json.dumps(block))
            change(data["screens"][0])
            text = json.dumps(data, separators=(",", ":"))
            path = d / "mutated.html"
            path.write_text(re.sub(r'(<script type="application/json" id="screens-data">).*?(</script>)', lambda m: m.group(1) + text + m.group(2), page, flags=re.DOTALL), encoding="utf-8")
            result = run_script("validate.py", path, check=False)
            return result.returncode, result.stdout

        svg = "data:image/svg+xml;base64," + base64.b64encode(SVG).decode()
        code, out = mutated(lambda e: e.update(before=svg))
        self.assertEqual(code, 1, out)
        self.assertIn("screens: welcome.before has MIME type image/svg+xml; only image/png, image/jpeg, and image/webp are allowed", out)
        code, out = mutated(lambda e: e.update(after="data:image/gif;base64," + base64.b64encode(GIF).decode()))
        self.assertEqual(code, 1, out)
        self.assertIn("welcome.after has MIME type image/gif", out)
        code, out = mutated(lambda e: e.update(before="data:image/jpeg;base64," + base64.b64encode(png_bytes()).decode()))
        self.assertEqual(code, 1, out)
        self.assertIn("welcome.before claims image/jpeg but its bytes are not that format", out)
        code, out = mutated(lambda e: e.update(before="https://example.com/a.png"))
        self.assertEqual(code, 1, out)
        self.assertIn("welcome.before is not an image data URI", out)
        code, out = mutated(lambda e: e.update(before=None, after=None))
        self.assertEqual(code, 1, out)
        self.assertIn("neither a before nor an after image", out)
        code, out = mutated(lambda e: e.update(pr="Z"))
        self.assertEqual(code, 1, out)
        self.assertIn("names PR 'Z', which the map does not have", out)
        code, out = mutated(lambda e: e.update(stale=True))
        self.assertEqual(code, 0, out)
        self.assertIn("warning: screens: welcome was taken at", out)
        self.assertEqual(run_script("validate.py", d / "review.html").stdout.strip().splitlines()[-1], "OK")


class SkillDocsTests(unittest.TestCase):
    def test_screenshots_are_documented_and_only_on_request(self):
        """This test will fail when SKILL.md stops pointing at references/screenshots.md or loses the rule that screenshots are taken only when the user asks, or when the reference loses its sources, capture settings, or the screens.json schema."""
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        reference = (SKILL / "references" / "screenshots.md").read_text(encoding="utf-8")
        self.assertIn("references/screenshots.md", skill)
        self.assertRegex(skill, r"(?i)only when the user (explicitly )?asks")
        self.assertRegex(reference, r"(?i)only when the user (explicitly )?asks")
        for needle in ("screens.py from-pr", "screens.py check", "refresh.py $SCRATCH --assemble-only", "--screens", "1280", "390", "600 KB", "8 MB", "SVG",
                       '"before"', '"after"', '"tip"', '"viewport"', '"source"', "pr-body", "preview", "local"):
            with self.subTest(needle=needle):
                self.assertIn(needle, reference)


if __name__ == "__main__":
    unittest.main()
