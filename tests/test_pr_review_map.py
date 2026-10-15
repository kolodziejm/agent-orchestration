"""Behavioral contracts for the pr-review-map skill package and its scripts.

The scripts run as the skill runs them: as separate processes against a real git
repository, never imported, so no bytecode cache lands in the skill directory.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pr-review-map"
SCRIPTS = SKILL / "scripts"
NODE = shutil.which("node")
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
TRICKY = "const html = '</script><!-- not a comment -->';\n"


def run_script(name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, env=ENV
    )
    if check and result.returncode != 0:
        raise AssertionError(f"{name} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV, check=True
    ).stdout


def commit_files(repo: Path, files: dict[str, str], message: str) -> None:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def embedded_json(page: str, ident: str):
    match = re.search(rf'<script type="application/json" id="{ident}">(.*?)</script>', page, re.DOTALL)
    return json.loads(match.group(1))


class SkillPackageTests(unittest.TestCase):
    def test_skill_md_is_focused_and_every_referenced_file_exists(self):
        """This test will fail when SKILL.md loses its trigger phrases, grows past its budget, or points at a missing package file."""
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        front = text.split("---\n")[1]
        self.assertIn("name: pr-review-map\n", front)
        self.assertIn("compatibility:", front)
        description = " ".join(front.split("compatibility:")[0].split())
        for phrase in ("raport do review", "graf zależności diffu", "jak czytać te zmiany", "stack", "offer it"):
            self.assertIn(phrase, description)
        self.assertLess(len(text.splitlines()), 250)
        referenced = set(re.findall(r"`((?:scripts|references|assets)/[\w./-]+)`", text))
        referenced |= set(re.findall(r"\$SKILL/((?:scripts|references|assets)/[\w./-]+)", text))
        self.assertTrue(referenced)
        for relative in sorted(referenced):
            with self.subTest(file=relative):
                self.assertTrue((SKILL / relative).is_file())

    def test_every_template_string_exists_in_every_built_in_locale(self):
        """This test will fail when the viewer asks for a UI string a built-in locale lacks."""
        strings = json.loads((SKILL / "assets" / "strings.json").read_text(encoding="utf-8"))
        template = (SKILL / "assets" / "viewer.html").read_text(encoding="utf-8")
        used = set(re.findall(r"\{\{S:([A-Za-z0-9_]+)\}\}", template))
        used |= set(re.findall(r"\bS\.([A-Za-z]+)", template)) - {"layers", "files"}
        self.assertTrue(used)
        self.assertEqual(set(strings), {"pl", "en"})
        for lang, catalog in strings.items():
            with self.subTest(lang=lang):
                self.assertEqual(sorted(used - set(catalog)), [])
                self.assertEqual(set(catalog), set(strings["en"]))
                self.assertEqual(set(catalog["layers"]), set(strings["en"]["layers"]))
                self.assertIn("other", catalog["files"])


class ReviewMapPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.repo = cls.root / "repo"
        cls.repo.mkdir()
        git(cls.repo, "init", "-q", "-b", "main")
        git(cls.repo, "remote", "add", "origin", "https://reviewer:s3cret-token@git.example.com/acme/demo.git")
        commit_files(cls.repo, {"README.md": "# demo\n", "src/legacy.ts": "export const legacy = 1;\n"}, "base")
        git(cls.repo, "checkout", "-q", "-b", "feat/a")
        commit_files(
            cls.repo,
            {
                "src/types.ts": "export type Item = { id: number };\n",
                "src/service.ts": "import type { Item } from './types';\nimport { legacy } from './legacy';\n"
                "export const load = (): Item[] => [{ id: legacy }];\n",
                "src/service.spec.ts": "import { load } from './service';\n" + TRICKY
                + "test('load', () => expect(load()).toHaveLength(1));\n",
                "src/index.ts": "export { load } from './service.js';\n",
                "locales/en.json": '{"title": "Items"}\n',
                "locales/pl.json": '{"title": "Pozycje"}\n',
                "README.md": "# demo\n\nItems service.\n",
                "package-lock.json": "".join(f'{{"line": {i}}}\n' for i in range(60)),
            },
            "feat: items service",
        )
        git(cls.repo, "checkout", "-q", "-b", "feat/b")
        commit_files(
            cls.repo,
            {
                "web/app.tsx": "import { load } from '@demo/items';\nexport const App = () => load().length;\n",
                "web/app.spec.tsx": "import { App } from './app';\ntest('app', () => expect(App()).toBe(1));\n",
            },
            "feat: web app",
        )
        cls.overlay = cls.root / "overlay.json"
        cls.overlay.write_text(
            json.dumps(
                {
                    "nodes": {
                        "A:src/service.ts": {"role": "Loads items", "note": "Reads <code>legacy</code>."},
                        "A:#translations": {"role": "Two locales"},
                    },
                    "extraNodes": [{"pr": "A", "path": "src/legacy.ts", "layer": "infra", "role": "Unchanged source"}],
                    "edges": [{"from": "B:web/app.tsx", "to": "A:src/index.ts", "kind": "http"}],
                }
            ),
            encoding="utf-8",
        )
        cls.graph_path = cls.root / "graphs.json"
        cls.build_args = [
            "--out", str(cls.graph_path),
            "--pr", "A", str(cls.repo), "main...feat/a", "--name", "A", "A #1",
            "--pr", "B", str(cls.repo), "feat/a...feat/b", "--name", "B", "B #2",
            "--title", "A", "Items service", "--repo", "B", "acme/web",
            "--alias", "@demo/items=src/service.ts",
            "--overlay", str(cls.overlay),
        ]
        run_script("build_graph.py", *cls.build_args)
        cls.graph = json.loads(cls.graph_path.read_text(encoding="utf-8"))
        cls.diffs_path = cls.root / "diffs.json"
        run_script(
            "gen_diffs.py", "--graph", str(cls.graph_path), "--out", str(cls.diffs_path),
            "--pr", "A", str(cls.repo), "main...feat/a", "--pr", "B", str(cls.repo), "feat/a...feat/b",
            "--max-lines", "40", "--strict",
        )
        cls.diffs = json.loads(cls.diffs_path.read_text(encoding="utf-8"))
        cls.narrative = cls.root / "narrative.html"
        cls.narrative.write_text(
            '<header><h1>Demo</h1><p class="sub">Two PRs.</p></header>\n'
            '<section id="stack"><h2>Stack <span class="tag c-A">A</span></h2>'
            '<div class="grid-4"><div class="pr-card c-A"><span class="t">A #1</span></div></div></section>\n'
            "<!-- review-map:graph -->\n"
            '<section id="arch" data-toc="Architecture"><h2>How {{count}} items flow</h2>'
            '<div class="diagram"><pre class="mermaid">\nflowchart LR\n  A --> B\n</pre></div></section>\n'
            '<section id="pr-A"><h2>PR A</h2><p><button type="button" class="tag c-A" data-gopen="A"></button></p></section>\n'
            "<footer>As of today.</footer>\n",
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def nodes(self, key: str) -> dict[str, dict]:
        pr = next(pr for pr in self.graph["prs"] if pr["key"] == key)
        return {node["path"]: node for node in pr["nodes"]}

    def edges(self, key: str) -> set[tuple[str, str, str, bool]]:
        pr = next(pr for pr in self.graph["prs"] if pr["key"] == key)
        by_id = {node["id"]: node["path"] for p in self.graph["prs"] for node in p["nodes"]}
        return {(by_id[e["from"]], by_id[e["to"]], e["kind"], e["external"]) for e in pr["edges"]}

    def test_build_graph_resolves_nodes_groups_edges_and_the_overlay(self):
        """This test will fail when the scaffold misses a resolved import, a group, a cross-PR edge, or an overlay entry."""
        a = self.nodes("A")
        self.assertEqual(a["locales/*.json"]["files"], ["locales/en.json", "locales/pl.json"])
        self.assertEqual(a["locales/*.json"]["layer"], "i18n")
        self.assertEqual(a["locales/*.json"]["role"], "Two locales")
        self.assertEqual(a["package-lock.json"]["layer"], "config")
        self.assertEqual(a["README.md"]["layer"], "docs")
        self.assertEqual(a["src/service.spec.ts"]["layer"], "test")
        self.assertEqual(a["src/service.ts"]["note"], "Reads <code>legacy</code>.")
        self.assertTrue(a["src/legacy.ts"]["unchanged"])
        self.assertEqual(a["src/service.ts"]["added"], 3)
        self.assertEqual(
            self.edges("A"),
            {
                ("src/service.ts", "src/types.ts", "import", False),
                ("src/service.ts", "src/legacy.ts", "import", False),
                ("src/service.spec.ts", "src/service.ts", "test", False),
                ("src/index.ts", "src/service.ts", "import", False),
            },
        )
        self.assertEqual(
            self.edges("B"),
            {
                ("web/app.tsx", "src/service.ts", "import", True),
                ("web/app.tsx", "src/index.ts", "http", True),
                ("web/app.spec.tsx", "web/app.tsx", "test", False),
            },
        )
        self.assertEqual(len(self.graph["crossEdges"]), 2)
        self.assertEqual([pr["name"] for pr in self.graph["prs"]], ["A #1", "B #2"])

    def test_reading_order_puts_dependencies_first_tests_after_subjects_and_late_layers_last(self):
        """This test will fail when the dependency order, test placement, or late-layer rule breaks."""
        a = self.nodes("A")
        order = [node["path"] for node in sorted(a.values(), key=lambda node: node["order"])]
        self.assertLess(order.index("src/types.ts"), order.index("src/service.ts"))
        self.assertEqual(order[order.index("src/service.ts") + 1], "src/service.spec.ts")
        self.assertLess(order.index("src/service.ts"), order.index("src/index.ts"))
        self.assertEqual(
            {a[path]["layer"] for path in order[-3:]}, {"config", "i18n", "docs"}
        )
        ids = [node["id"] for pr in self.graph["prs"] for node in pr["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(node["order"] for node in a.values()), list(range(1, len(a) + 1)))

    def test_build_graph_labels_each_pr_with_its_repository_and_no_credentials(self):
        """This test will fail when a PR loses the repository label review notes cite, --repo stops overriding it, or the remote's host or credentials leak into the graph."""
        self.assertEqual([(pr["repo"], pr["title"]) for pr in self.graph["prs"]], [("acme/demo", "Items service"), ("acme/web", "B #2")])
        text = self.graph_path.read_text(encoding="utf-8")
        for secret in ("s3cret-token", "reviewer", "git.example.com"):
            self.assertNotIn(secret, text)
        repo = self.root / "folder-name"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"a.txt": "a\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(repo, {"b.txt": "b\n"}, "feat")
        git(repo, "remote", "add", "origin", "https://example.invalid/x.git")
        out = self.root / "graphs-remote.json"
        cases = {
            "https://TOKEN1secret@git.example.com": "folder-name",
            "https://git.example.com/acme/demo.git?private_token=TOKEN2secret#TOKEN3secret": "acme/demo",
            "https://user:pass/TOKEN4secret@git.example.com/demo.git": "demo",
            "deploy:TOKEN5secret@git.example.com:acme/demo.git": "acme/demo",
            "git@git.example.com:acme/demo.git": "acme/demo",
            "ssh://git@git.example.com:2222/group/acme/demo.git": "acme/demo",
            "/srv/git/demo.git": "folder-name",
        }
        for url, label in cases.items():
            with self.subTest(url=url):
                git(repo, "remote", "set-url", "origin", url)
                run_script("build_graph.py", "--out", str(out), "--pr", "R", str(repo), "main...feat")
                text = out.read_text(encoding="utf-8")
                self.assertEqual(json.loads(text)["prs"][0]["repo"], label)
                for leak in ("secret", "git.example.com", "user", "deploy", "private_token"):
                    self.assertNotIn(leak, text)

    def test_build_graph_is_deterministic(self):
        """This test will fail when two runs over the same branches produce different graphs."""
        again = self.root / "graphs-again.json"
        args = list(self.build_args)
        args[1] = str(again)
        run_script("build_graph.py", *args)
        self.assertEqual(again.read_bytes(), self.graph_path.read_bytes())

    def test_gen_diffs_assigns_every_file_strips_headers_and_truncates(self):
        """This test will fail when a changed file loses its diff, git headers leak into it, or a huge diff is not capped."""
        a = self.nodes("A")
        for pr in self.graph["prs"]:
            for node in pr["nodes"]:
                if not node.get("unchanged"):
                    self.assertIn(node["id"], self.diffs)
        self.assertNotIn(a["src/legacy.ts"]["id"], self.diffs)
        group = self.diffs[a["locales/*.json"]["id"]]
        self.assertEqual([entry["path"] for entry in group], ["locales/en.json", "locales/pl.json"])
        for entries in self.diffs.values():
            for entry in entries:
                self.assertNotIn("diff --git", entry["diff"])
                self.assertFalse(any(line.startswith("index ") for line in entry["diff"].splitlines()))
        lock = self.diffs[a["package-lock.json"]["id"]][0]
        self.assertEqual(len(lock["diff"].splitlines()), 40)
        self.assertGreater(lock["truncated"], 40)
        self.assertIn(TRICKY.strip(), self.diffs[a["src/service.spec.ts"]["id"]][0]["diff"])

    def test_gen_diffs_strict_fails_on_a_file_no_node_claims(self):
        """This test will fail when --strict lets a changed file silently disappear from the page."""
        graph = json.loads(self.graph_path.read_text(encoding="utf-8"))
        graph["prs"][0]["nodes"] = [n for n in graph["prs"][0]["nodes"] if n["path"] != "src/types.ts"]
        partial = self.root / "graphs-partial.json"
        partial.write_text(json.dumps(graph), encoding="utf-8")
        result = run_script(
            "gen_diffs.py", "--graph", str(partial), "--out", str(self.root / "partial-diffs.json"),
            "--pr", "A", str(self.repo), "main...feat/a", "--pr", "B", str(self.repo), "feat/a...feat/b",
            "--strict", check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("A:src/types.ts", result.stdout)

    def assemble(self, target: str, *extra: str) -> Path:
        out = self.root / f"review-{target}.html"
        run_script(
            "assemble.py", "--graph", str(self.graph_path), "--diffs", str(self.diffs_path),
            "--narrative", str(self.narrative), "--title", "Demo <review>", "--lang", "pl",
            "--target", target, "--out", str(out), *extra,
        )
        return out

    @unittest.skipUnless(NODE, "node is required to validate the assembled page")
    def test_assembled_pages_validate_and_embed_data_losslessly(self):
        """This test will fail when assembly emits a page the validator rejects, breaks the script boundary, or alters embedded data."""
        for target in ("artifact", "local"):
            with self.subTest(target=target):
                page_path = self.assemble(target)
                result = run_script("validate.py", str(page_path), check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                page = page_path.read_text(encoding="utf-8")
                self.assertEqual(embedded_json(page, "diff-data"), self.diffs)
                self.assertEqual(embedded_json(page, "graph-data"), self.graph)
                self.assertIn("<title>Demo &lt;review&gt;</title>", page)
                self.assertIn("How {{count}} items flow", page)
                self.assertIn('<li><a href="#graph">Graf czytania</a></li>', page)
                self.assertIn('<li><a href="#arch">Architecture</a></li>', page)
                self.assertIn(".c-A{--c:var(--pal-1)}", page)
                config = embedded_json(page, "review-config")
                self.assertEqual(config["title"], "Demo <review>")
                self.assertEqual(config["storageKey"], "demo-review")
                self.assertEqual([(p["key"], p["repo"]) for p in config["prs"]], [("A", "acme/demo"), ("B", "acme/web")])
                for element in ('id="nt-panel"', 'id="nt-copy"', 'id="nt-clear"', 'id="nt-list"', 'id="nt-manual-text"'):
                    self.assertIn(element, page)
                if target == "artifact":
                    self.assertTrue(page.startswith("<title>"))
                    self.assertNotIn("mermaid.min.js", page)
                else:
                    self.assertTrue(page.startswith("<!doctype html>"))
                    self.assertIn("mermaid.min.js", page)

    def test_string_overrides_replace_single_keys(self):
        """This test will fail when a --strings override is ignored or wipes the other strings."""
        overrides = self.root / "strings.json"
        overrides.write_text(json.dumps({"graphTitle": "Mapa", "layers": {"ui": "Widok"}}), encoding="utf-8")
        page = self.assemble("artifact", "--strings", str(overrides)).read_text(encoding="utf-8")
        config = embedded_json(page, "review-config")
        self.assertEqual(config["strings"]["graphTitle"], "Mapa")
        self.assertEqual(config["strings"]["layers"]["ui"], "Widok")
        self.assertEqual(config["strings"]["layers"]["logic"], "Logika")
        self.assertIn("<h2>Mapa</h2>", page)

    def test_assemble_refuses_a_narrative_without_exactly_one_graph_marker(self):
        """This test will fail when the graph can be placed twice or nowhere."""
        broken = self.root / "broken-narrative.html"
        broken.write_text("<section id='x'><h2>No marker</h2></section>\n", encoding="utf-8")
        result = run_script(
            "assemble.py", "--graph", str(self.graph_path), "--diffs", str(self.diffs_path),
            "--narrative", str(broken), "--title", "t", "--out", str(self.root / "never.html"), check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "never.html").exists())

    @unittest.skipUnless(NODE, "node is required to validate the assembled page")
    def test_validator_rejects_broken_pages(self):
        """This test will fail when the validator passes an invalid JSON escape, a script-ending sequence, broken JS, unbalanced markup, or a foreign CDN."""
        good = self.assemble("artifact").read_text(encoding="utf-8")
        start = good.index('<script type="application/json" id="diff-data">')
        cases = {
            "invalid-json-escape": good.replace(
                '<script type="application/json" id="diff-data">{',
                '<script type="application/json" id="diff-data">{"x":"<\\!--",', 1,
            ),
            "comment-opener-in-script": good[:start] + "<script>var a='<!--';</script>\n" + good[start:],
            "syntax-error": good[:start] + "<script>function (</script>\n" + good[start:],
            "unbalanced-div": good.replace("<main>", "<main><div>", 1),
            "foreign-cdn": good[:start] + '<script src="https://unpkg.com/x.js"></script>\n' + good[start:],
            "leftover-placeholder": good.replace("<main>", "<main>{{TOC}}", 1),
        }
        for name, page in cases.items():
            with self.subTest(case=name):
                path = self.root / f"bad-{name}.html"
                path.write_text(page, encoding="utf-8")
                result = run_script("validate.py", str(path), check=False)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("error:", result.stdout)


if __name__ == "__main__":
    unittest.main()
