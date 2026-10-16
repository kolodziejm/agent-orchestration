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
# Runs the viewer's own computeOrder(), cut out of assets/viewer.html, over a graphs.json in both modes and
# prints {mode: {prKey: {nodeId: step}}}.
VIEWER_ORDER = r"""
const fs = require('fs');
const [template, graphFile] = process.argv.slice(2);
const html = fs.readFileSync(template, 'utf8');
const late = html.match(/var LATE=(\{[^}]*\});/)[1];
const start = html.indexOf('function computeOrder(p){');
if (start < 0) throw new Error('computeOrder not found in the viewer');
let depth = 0, end = -1;
for (let i = html.indexOf('{', start); i < html.length; i++) {
  if (html[i] === '{') depth++;
  else if (html[i] === '}' && --depth === 0) { end = i + 1; break; }
}
const run = new Function('data', 'var ON={},SUBJ={},LINKED={},HUB={},omode,all={},LATE=' + late + ';\n' + html.slice(start, end) + `
  data.prs.forEach(function(p){p.nodes.forEach(function(n){all[n.id]=Object.assign({pr:p.key},n);});});
  var out={};
  ['bottom','top'].forEach(function(m){omode=m;out[m]={};data.prs.forEach(function(p){computeOrder(p);out[m][p.key]=ON;});});
  return out;`);
process.stdout.write(JSON.stringify(run(JSON.parse(fs.readFileSync(graphFile, 'utf8')))));
"""
# Runs the viewer's mdNote(), cut out of assets/viewer.html, over a JSON list of note texts and prints the results.
MD_NOTE = r"""
const fs = require('fs');
const [template, casesFile] = process.argv.slice(2);
const html = fs.readFileSync(template, 'utf8');
const start = html.indexOf('  var MD_Q=');
const fn = html.indexOf('function mdNote(text){');
if (start < 0 || fn < 0) throw new Error('mdNote not found in the viewer');
let depth = 0, end = -1;
for (let i = html.indexOf('{', fn); i < html.length; i++) {
  if (html[i] === '{') depth++;
  else if (html[i] === '}' && --depth === 0) { end = i + 1; break; }
}
const mdNote = new Function(html.slice(start, end) + '\nreturn mdNote;')();
process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(casesFile, 'utf8')).map(mdNote)));
"""
# Runs the viewer's lang(), parse(), and sfcLangs(), cut out of assets/viewer.html, and prints the highlight.js language
# of every path in the input's "paths" and of every row of its "diffs" ({path: diff}) as [side, line, text, lang].
VIEWER_LANGS = r"""
const fs = require('fs');
const [template, inputFile] = process.argv.slice(2);
const html = fs.readFileSync(template, 'utf8');
function cut(from, to) {
  const start = html.indexOf(from), fn = html.indexOf(to, start);
  if (start < 0 || fn < 0) throw new Error(from + ' not found in the viewer');
  let depth = 0;
  for (let i = html.indexOf('{', fn); i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
  }
}
const code = cut('  var LANG={', 'function sfcLangs(path,hs){') + '\n' + cut('  function parse(diff){', 'function parse(diff){');
const api = new Function('DIFFS', 'esc', code + '\nreturn {lang: lang, parse: parse, sfcLangs: sfcLangs};')({}, String);
const input = JSON.parse(fs.readFileSync(inputFile, 'utf8'));
const out = {paths: {}, rows: {}};
input.paths.forEach((p) => { out.paths[p] = api.lang(p); });
Object.entries(input.diffs).forEach(([path, diff]) => {
  const hs = api.parse(diff), rows = [];
  api.sfcLangs(path, hs);
  hs.forEach((h) => h.rows.forEach((r) => {
    if (r.t !== 'add') rows.push(['old', r.o, r.s.trim(), r.lo]);
    if (r.t !== 'del') rows.push(['new', r.n, r.s.trim(), r.ln]);
  }));
  out.rows[path] = rows;
});
process.stdout.write(JSON.stringify(out));
"""


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
        repo = cls.root / "ordering"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"README.md": "# x\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(
            repo,
            {
                "src/types.ts": "export type T = number;\n",
                "src/service.ts": "import type { T } from './types';\nexport const one = (): T => 1;\n",
                "src/index.ts": "export { one } from './service';\n",
                "src/mobile-state-panel.tsx": "import { one } from './service';\nexport const Panel = () => one();\n",
                "src/mobile-state-panel-test.tsx": "import { types } from './types';\nimport { Panel } from './mobile-state-panel';\n",
                "src/zeta.rb": "module Zeta; end\n",
                "spec_support/zeta_spec.rb": "describe Zeta do; end\n",
                "src/test-utils.ts": "export const helper = 1;\n",
                "src/contest.ts": "export const contest = 1;\n",
                "cluster/pod_spec.go": "package cluster\n",
                "src/openapi_spec.py": "SPEC = {}\n",
                "src/build_spec.rs": "pub struct BuildSpec;\n",
                "app/main.ts": "console.log('boot');\n",
                "api/openapi-spec.yaml": "openapi: 3.0.0\n",
                "docs/guide.md": "# guide\n",
            },
            "feat",
        )
        cls.ordering_path = cls.root / "graphs-ordering.json"
        run_script("build_graph.py", "--out", str(cls.ordering_path), "--pr", "O", str(repo), "main...feat")
        cls.ordering = json.loads(cls.ordering_path.read_text(encoding="utf-8"))
        # Two service -> controller chains whose layer/path tie-break alone would read both services, then both
        # controllers; the flow tie-break keeps each controller next to its service.
        repo = cls.root / "flow"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"README.md": "# x\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(
            repo,
            {
                "src/logic/billing.service.ts": "export const bill = 1;\n",
                "src/logic/visit.service.ts": "export const visit = 1;\n",
                "src/rest/billing.controller.ts": "import { bill } from '../logic/billing.service';\nexport const b = bill;\n",
                "src/rest/billing.controller.spec.ts": "import { b } from './billing.controller';\n",
                "src/rest/visit.controller.ts": "import { visit } from '../logic/visit.service';\nexport const v = visit;\n",
            },
            "feat",
        )
        cls.flow_path = cls.root / "graphs-flow.json"
        run_script("build_graph.py", "--out", str(cls.flow_path), "--pr", "F", str(repo), "main...feat")
        cls.flow = json.loads(cls.flow_path.read_text(encoding="utf-8"))
        # Shared dependencies: i18n/index.ts (6 dependents) and failure-text.ts (4) of 10 linked core files are hubs,
        # catalog.ts joins them because only index.ts uses it, c/util.ts is linked to hubs only, lonely.ts to nothing.
        cls.hub_repo = repo = cls.root / "hubs"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"README.md": "# x\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        i18n, failure = "import { t } from '../../i18n';\n", "import { failureText } from '../../errors/failure-text';\n"
        commit_files(
            repo,
            {
                "src/i18n/catalog.ts": "export const catalog: Record<string, string> = {};\n",
                "src/i18n/index.ts": "import { catalog } from './catalog';\nexport const t = (k: string) => catalog[k];\n",
                "src/errors/failure-text.ts": "import { t } from '../i18n';\nexport const failureText = () => t('failed');\n",
                "src/errors/failure-text.test.ts": "import { failureText } from './failure-text';\n",
                "src/feature/a/state.ts": i18n + "export const a = t('a');\n",
                "src/feature/a/state.spec.ts": "import { a } from './state';\n",
                "src/feature/a/screen.tsx": "import { a } from './state';\n" + i18n + failure + "export const A = () => a;\n",
                "src/feature/b/state.ts": i18n + "export const b = t('b');\n",
                "src/feature/b/screen.tsx": "import { b } from './state';\n" + i18n + failure + "export const B = () => b;\n",
                "src/feature/c/state.ts": "export const c = 1;\n",
                "src/feature/c/screen.tsx": "import { c } from './state';\n" + failure + "export const C = () => c;\n",
                "src/feature/c/util.ts": i18n + failure + "export const u = 1;\n",
                "src/lonely.ts": "export const lonely = 1;\n",
                "docs/notes.md": "# notes\n",
            },
            "feat",
        )
        cls.hubs_path = cls.root / "graphs-hubs.json"
        run_script("build_graph.py", "--out", str(cls.hubs_path), "--pr", "H", str(repo), "main...feat")
        cls.hubs = json.loads(cls.hubs_path.read_text(encoding="utf-8"))

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

    def test_build_graph_records_the_commits_each_diff_compares(self):
        """This test will fail when a PR loses the base or tip SHA its review-note line numbers refer to, or a three-dot range stops using the merge base."""
        short = {ref: git(self.repo, "rev-parse", "--short", ref).strip() for ref in ("main", "feat/a", "feat/b")}
        self.assertEqual(
            [(pr["key"], pr["base"], pr["tip"]) for pr in self.graph["prs"]],
            [("A", short["main"], short["feat/a"]), ("B", short["feat/a"], short["feat/b"])],
        )
        repo = self.root / "moved"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"a.txt": "a\n"}, "base")
        fork = git(repo, "rev-parse", "--short", "HEAD").strip()
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(repo, {"b.txt": "b\n"}, "feat")
        git(repo, "checkout", "-q", "main")
        commit_files(repo, {"c.txt": "c\n"}, "main moves on")
        moved_main = git(repo, "rev-parse", "--short", "main").strip()
        out = self.root / "graphs-moved.json"
        run_script("build_graph.py", "--out", str(out), "--pr", "A", str(repo), "main...feat", "--pr", "X", str(repo), "main..feat")
        moved = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([pr["base"] for pr in moved["prs"]], [fork, moved_main])

    def test_isolated_files_follow_connected_ones_and_tests_are_found_by_name(self):
        """This test will fail when a file with no same-PR edge opens the reading order, a language's test marker is missed or applied to another language (pod_spec.go, openapi_spec.py, build_spec.rs), a test-like name such as test-utils.ts or contest.ts becomes a test, or a test is not placed after its name-matched subject."""
        pr = self.ordering["prs"][0]
        nodes = {node["path"]: node for node in pr["nodes"]}
        by_id = {node["id"]: node["path"] for node in pr["nodes"]}
        layers = {path: node["layer"] for path, node in nodes.items()}
        self.assertEqual(layers["src/mobile-state-panel-test.tsx"], "test")
        self.assertEqual(layers["spec_support/zeta_spec.rb"], "test")
        for path in ("src/test-utils.ts", "src/contest.ts", "api/openapi-spec.yaml", "cluster/pod_spec.go",
                     "src/openapi_spec.py", "src/build_spec.rs"):
            self.assertNotEqual(layers[path], "test", path)
        edges = {(by_id[e["from"]], by_id[e["to"]]): e["kind"] for e in pr["edges"]}
        self.assertEqual(edges[("src/mobile-state-panel-test.tsx", "src/mobile-state-panel.tsx")], "test")
        self.assertEqual(edges[("spec_support/zeta_spec.rb", "src/zeta.rb")], "test")
        order = [node["path"] for node in sorted(pr["nodes"], key=lambda node: node["order"])]
        self.assertEqual(
            order,
            [
                "src/types.ts", "src/service.ts", "src/mobile-state-panel.tsx", "src/mobile-state-panel-test.tsx",
                "src/index.ts",
                "cluster/pod_spec.go", "src/build_spec.rs", "src/contest.ts", "src/openapi_spec.py", "src/test-utils.ts",
                "src/zeta.rb", "spec_support/zeta_spec.rb", "app/main.ts",
                "api/openapi-spec.yaml", "docs/guide.md",
            ],
        )

    def test_more_languages_test_conventions_are_found_and_matched_to_subjects(self):
        """This test will fail when a C/C++, Kotlin/Scala/Groovy, Java failsafe, Cypress, or Django test convention is missed, a look-alike name (Inspect.kt, SpecRunner.kt, HotelSuite.kt, ITService.java, Commit.java, latest.cc, testing.c) becomes a test, a test loses its name-matched subject, or Django's tests.py gets a name match instead of being placed by its imports."""
        repo = self.root / "conventions"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"README.md": "# x\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        tests = {
            "cpp/widget_test.cc": "cpp/widget.cc", "cpp/test_parser.cpp": "cpp/parser.cpp", "cpp/engine_test.c": "cpp/engine.c",
            "kt/OrderServiceSpec.kt": "kt/OrderService.kt", "kt/CartTests.kt": "kt/Cart.kt",
            "scala/LedgerSpec.scala": "scala/Ledger.scala", "groovy/PriceSpec.groovy": "groovy/Price.groovy",
            "java/UserRepositoryIT.java": "java/UserRepository.java", "java/PaymentITCase.java": "java/Payment.java",
            "web/login.cy.ts": "web/login.ts", "shop/tests.py": None,
        }
        others = ["cpp/widget.h", "kt/Inspect.kt", "kt/SpecRunner.kt", "kt/Spec.kt", "kt/HotelSuite.kt", "scala/HotelSuite.scala",
                  "java/ITService.java", "java/Commit.java", "cpp/latest.cc", "cpp/testing.c", "web/policy.ts", "misc/tests.ts",
                  ".editorconfig", "shop/models.py", "shop/views.py"]
        files = {path: "x\n" for path in [*tests, *(subject for subject in tests.values() if subject), *others]}
        files["shop/tests.py"] = "from .models import Item\n"
        files["shop/views.py"] = "from .models import Item\n"
        files["shop/models.py"] = "class Item: pass\n"
        commit_files(repo, files, "feat")
        out = self.root / "graphs-conventions.json"
        run_script("build_graph.py", "--out", str(out), "--pr", "T", str(repo), "main...feat")
        pr = json.loads(out.read_text(encoding="utf-8"))["prs"][0]
        nodes = {node["path"]: node for node in pr["nodes"]}
        by_id = {node["id"]: node["path"] for node in pr["nodes"]}
        for path in tests:
            self.assertEqual(nodes[path]["layer"], "test", path)
        for path in others:
            self.assertNotEqual(nodes[path]["layer"], "test", path)
        test_edges = {by_id[e["from"]]: by_id[e["to"]] for e in pr["edges"] if e["kind"] == "test"}
        self.assertEqual(test_edges, {path: subject for path, subject in tests.items() if subject})
        edges = {(by_id[e["from"]], by_id[e["to"]], e["kind"]) for e in pr["edges"]}
        self.assertIn(("shop/tests.py", "shop/models.py", "import"), edges)
        order = [node["path"] for node in sorted(pr["nodes"], key=lambda node: node["order"])]
        self.assertEqual(order[order.index("shop/models.py") + 1], "shop/tests.py")

    @unittest.skipUnless(NODE, "node is required to run the viewer's Markdown code")
    def test_copied_note_text_cannot_break_the_markdown_structure(self):
        """This test will fail when a note's text can make a heading at or above its own "####" level (ATX, also in a quote or list item, or a setext underline), leave a code fence or an HTML comment/<pre> block open over the notes after it, when a fence or HTML block inside a list item or quote has its code changed or gets a stray closing fence, when a "---" thematic break is escaped as if it were an underline, when CR line endings slip through, or when ordinary text, closed fences, and closed HTML stop being copied as written."""
        cases = {
            "# Top\n## Sub\n###### Six": "##### Top\n###### Sub\n###### Six",
            "   # Indented\n> # Quoted\n- # Listed\n1. ## Numbered": "   ##### Indented\n> ##### Quoted\n- ##### Listed\n1. ###### Numbered",
            "Title\n===\nLine\n  ---  ": "Title\n\\===\nLine\n  \\---  ",
            "para\n\n---\n\nnext": "para\n\n---\n\nnext",
            "```js\nconst a = 1;\n# not a heading": "```js\nconst a = 1;\n# not a heading\n```",
            "~~~~\ncode\n~~~": "~~~~\ncode\n~~~\n~~~~",
            "```\n# in code\n```\n# outside": "```\n# in code\n```\n##### outside",
            "<!-- todo\nstill open": "\\<!-- todo\nstill open",
            "<pre>\nraw": "\\<pre>\nraw",
            "<!-- closed -->\n<pre>x</pre>": "<!-- closed -->\n<pre>x</pre>",
            "#hashtag, ####### seven, plain `code`": "#hashtag, ####### seven, plain `code`",
            # A fence opened in a list item or a quote: its code is copied as written, its closing fence is not taken for
            # an opener, and no fence is appended (the blank line and heading after the note end it with its container).
            "1. Run:\n- ```sh\n  # install\n  ```\n# after": "1. Run:\n- ```sh\n  # install\n  ```\n##### after",
            "> ```py\n> # comment\n> x = 1": "> ```py\n> # comment\n> x = 1",
            "- item\n  ```\n  # code": "- item\n  ```\n  # code",
            "- item\n  ```\n# out": "- item\n  ```\n##### out",
            # Lines inside an HTML block are not fences or headings; the block ends at its end marker or blank line.
            "<!--\n```\n-->\n# heading": "<!--\n```\n-->\n##### heading",
            "<div>\n```\n</div>\n\n# h": "<div>\n```\n</div>\n\n##### h",
            "- <!-- open\n  # x": "- <!-- open\n  # x",
            # "---" is a thematic break after a heading, a fence, a list item it is not part of, or a blank line.
            "# H\n---": "##### H\n---",
            "```\nx\n```\n---": "```\nx\n```\n---",
            "- a\n---": "- a\n---",
            "- a\n  ===\n> b\n> ---": "- a\n  \\===\n> b\n> \\---",
            "> a\nlazy\n===": "> a\nlazy\n===",
            "a\r\nb\r\n===\r\n# c\rd": "a\nb\n\\===\n##### c\nd",
        }
        script = self.root / "md-note.js"
        script.write_text(MD_NOTE, encoding="utf-8")
        inputs = self.root / "md-note-cases.json"
        inputs.write_text(json.dumps(list(cases)), encoding="utf-8")
        result = subprocess.run(
            ["node", str(script), str(SKILL / "assets" / "viewer.html"), str(inputs)], capture_output=True, text=True, check=True,
        )
        self.assertEqual(dict(zip(cases, json.loads(result.stdout))), cases)

    def test_reading_order_keeps_connected_files_adjacent(self):
        """This test will fail when the reading order stops preferring, among the files ready to read, the one connected to the file placed last, and falls back to layer and path alone (both services, then both controllers)."""
        pr = self.flow["prs"][0]
        order = [node["path"] for node in sorted(pr["nodes"], key=lambda node: node["order"])]
        self.assertEqual(
            order,
            [
                "src/logic/billing.service.ts", "src/rest/billing.controller.ts", "src/rest/billing.controller.spec.ts",
                "src/logic/visit.service.ts", "src/rest/visit.controller.ts",
            ],
        )

    def test_shared_dependencies_are_flagged_and_read_first(self):
        """This test will fail when a file most of the PR depends on is not flagged as a shared dependency, a file only hubs use stays out of their group, a file below the threshold (or a test, or a small PR's file) gets flagged, hubs stop opening the order, edges into hubs still bind or pull the other files, or the overlay's hub: true/false is ignored or accepts a non-boolean."""
        pr = self.hubs["prs"][0]
        order = [node["path"] for node in sorted(pr["nodes"], key=lambda node: node["order"])]
        self.assertEqual(
            {node["path"] for node in pr["nodes"] if node.get("hub")},
            {"src/i18n/catalog.ts", "src/i18n/index.ts", "src/errors/failure-text.ts"},
        )
        self.assertTrue(all(node["hub"] is True for node in pr["nodes"] if "hub" in node))
        self.assertEqual(
            order,
            [
                "src/i18n/catalog.ts", "src/i18n/index.ts", "src/errors/failure-text.ts", "src/errors/failure-text.test.ts",
                "src/feature/a/state.ts", "src/feature/a/state.spec.ts", "src/feature/a/screen.tsx",
                "src/feature/b/state.ts", "src/feature/b/screen.tsx", "src/feature/c/state.ts", "src/feature/c/screen.tsx",
                "src/feature/c/util.ts", "src/lonely.ts", "docs/notes.md",
            ],
        )
        for graph in (self.graph, self.ordering, self.flow):
            self.assertFalse([node["path"] for pr in graph["prs"] for node in pr["nodes"] if "hub" in node])
        overlay = self.root / "overlay-hubs.json"
        overlay.write_text(json.dumps({"nodes": {
            "H:src/errors/failure-text.ts": {"hub": False}, "H:src/feature/a/state.ts": {"hub": True}, "H:#docs": {"hub": True},
        }}), encoding="utf-8")
        out = self.root / "graphs-hubs-overlay.json"
        result = run_script("build_graph.py", "--out", str(out), "--pr", "H", str(self.hub_repo), "main...feat", "--overlay", str(overlay))
        self.assertIn("overlay hub ignored for docs/notes.md", result.stdout)
        self.assertIn("shared dependencies:", result.stdout)
        forced = json.loads(out.read_text(encoding="utf-8"))["prs"][0]["nodes"]
        self.assertEqual(
            [node["path"] for node in sorted(forced, key=lambda node: node["order"]) if node.get("hub")],
            ["src/i18n/catalog.ts", "src/i18n/index.ts", "src/feature/a/state.ts"],
        )
        overlay.write_text(json.dumps({"nodes": {"H:src/lonely.ts": {"hub": "yes"}}}), encoding="utf-8")
        result = run_script("build_graph.py", "--out", str(out), "--pr", "H", str(self.hub_repo), "main...feat",
                            "--overlay", str(overlay), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hub must be true or false", result.stderr)

    @unittest.skipUnless(NODE, "node is required to run the viewer's ordering code")
    def test_viewer_order_matches_the_stored_order_and_numbers_every_step(self):
        """This test will fail when the viewer's "from dependencies" order drifts from build_graph.py's stored order, the viewer stops applying the flow tie-break itself (a stored order without it must come out the same), "from the entry point" skips, repeats, or misplaces a step, or stops reading the shared dependencies first."""
        script = self.root / "viewer-order.js"
        script.write_text(VIEWER_ORDER, encoding="utf-8")
        orders = {}
        # The same flow graph with its stored order rewritten to the layer/path-only order: the viewer must apply the
        # flow rule itself and arrive at build_graph.py's order, not just copy the stored numbers.
        stale = json.loads(json.dumps(self.flow))
        by_path = {node["path"]: node for node in stale["prs"][0]["nodes"]}
        for position, path in enumerate(("src/logic/billing.service.ts", "src/logic/visit.service.ts", "src/rest/billing.controller.ts",
                                          "src/rest/billing.controller.spec.ts", "src/rest/visit.controller.ts"), 1):
            by_path[path]["order"] = position
        stale_path = self.root / "graphs-flow-stale.json"
        stale_path.write_text(json.dumps(stale), encoding="utf-8")
        for name, path, graph in (("fixture", self.graph_path, self.graph), ("ordering", self.ordering_path, self.ordering),
                                  ("flow", self.flow_path, self.flow), ("hubs", self.hubs_path, self.hubs)):
            result = subprocess.run(
                ["node", str(script), str(SKILL / "assets" / "viewer.html"), str(path)],
                capture_output=True, text=True, check=True,
            )
            orders[name] = json.loads(result.stdout)
            for pr in graph["prs"]:
                with self.subTest(graph=name, pr=pr["key"]):
                    stored = {node["id"]: node["order"] for node in pr["nodes"]}
                    self.assertEqual(orders[name]["bottom"][pr["key"]], stored)
                    top = orders[name]["top"][pr["key"]]
                    self.assertEqual(set(top), set(stored))
                    self.assertEqual(sorted(top.values()), list(range(1, len(stored) + 1)))
        result = subprocess.run(
            ["node", str(script), str(SKILL / "assets" / "viewer.html"), str(stale_path)], capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["bottom"]["F"], {node["id"]: node["order"] for node in self.flow["prs"][0]["nodes"]})
        flow_ids = {node["id"]: node["path"] for node in self.flow["prs"][0]["nodes"]}
        flow_top = orders["flow"]["top"]["F"]
        self.assertEqual(
            [flow_ids[i] for i in sorted(flow_top, key=flow_top.get)],
            [
                "src/rest/visit.controller.ts", "src/logic/visit.service.ts", "src/rest/billing.controller.ts",
                "src/rest/billing.controller.spec.ts", "src/logic/billing.service.ts",
            ],
        )
        # Shared dependencies open "from the entry point" too, their own links reversed like the rest's; edges into them
        # neither bind c/util.ts (it reads with the unlinked files) nor pull the files that use them.
        hub_ids = {node["id"]: node["path"] for node in self.hubs["prs"][0]["nodes"]}
        hub_top = orders["hubs"]["top"]["H"]
        self.assertEqual(
            [hub_ids[i] for i in sorted(hub_top, key=hub_top.get)],
            [
                "src/errors/failure-text.ts", "src/errors/failure-text.test.ts", "src/i18n/index.ts", "src/i18n/catalog.ts",
                "src/feature/c/screen.tsx", "src/feature/c/state.ts", "src/feature/b/screen.tsx", "src/feature/b/state.ts",
                "src/feature/a/screen.tsx", "src/feature/a/state.ts", "src/feature/a/state.spec.ts",
                "src/feature/c/util.ts", "src/lonely.ts", "docs/notes.md",
            ],
        )
        top = orders["ordering"]["top"]["O"]
        by_id = {node["id"]: node["path"] for node in self.ordering["prs"][0]["nodes"]}
        self.assertEqual(
            [by_id[i] for i in sorted(top, key=top.get)],
            [
                "src/index.ts", "src/mobile-state-panel.tsx", "src/mobile-state-panel-test.tsx", "src/service.ts",
                "src/types.ts",
                "cluster/pod_spec.go", "src/build_spec.rs", "src/contest.ts", "src/openapi_spec.py", "src/test-utils.ts",
                "src/zeta.rb", "spec_support/zeta_spec.rb", "app/main.ts",
                "api/openapi-spec.yaml", "docs/guide.md",
            ],
        )

    @unittest.skipUnless(NODE, "node is required to run the viewer's highlighting code")
    def test_single_file_components_are_highlighted_per_block_and_common_files_are_mapped(self):
        """This test will fail when gen_diffs.py stops naming the block a Vue/Svelte hunk starts in on its @@ line, the viewer highlights a hunk in the middle of a <template>, <script lang="ts">, or <style lang="scss"> block (or Svelte markup after </script>) in another block's language, or a common file type loses its highlight.js language."""
        repo = self.root / "sfc"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        vue = ["<template>", "  <ul>"] + [f'    <li class="r{i}">{{{{ n{i} }}}}</li>' for i in range(10)] + ["  </ul>", "</template>", "",
               '<script setup lang="ts">'] + [f"const n{i}: number = {i};" for i in range(10)] + ["</script>", "",
               '<style lang="scss" scoped>', "$gap: 4px;"] + [f".r{i} {{ margin: $gap * {i}; }}" for i in range(10)] + ["</style>", ""]
        svelte = ['<script lang="ts">'] + [f"  let v{i}: number = {i};" for i in range(10)] + ["</script>", "", "<main>"] + \
                 [f"  <p>{{v{i}}}</p>" for i in range(10)] + ["</main>", ""]
        commit_files(repo, {"Card.vue": "\n".join(vue), "Page.svelte": "\n".join(svelte)}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        changed = {"    <li class=\"r5\">{{ n5 }}</li>": "    <li class=\"r5 on\">{{ n5 }}</li>",
                   "const n5: number = 5;": "const n5: number = 50;", ".r5 { margin: $gap * 5; }": ".r5 { margin: $gap * 6; }",
                   "  let v5: number = 5;": "  let v5: number = 55;", "  <p>{v5}</p>": "  <p class=\"on\">{v5}</p>"}
        files = {"Card.vue": "\n".join(vue), "Page.svelte": "\n".join(svelte)}
        for old, new in changed.items():
            files = {path: text.replace(old, new) for path, text in files.items()}
        commit_files(repo, files, "feat")
        graph, diffs = self.root / "graphs-sfc.json", self.root / "diffs-sfc.json"
        run_script("build_graph.py", "--out", str(graph), "--pr", "V", str(repo), "main...feat")
        run_script("gen_diffs.py", "--graph", str(graph), "--out", str(diffs), "--pr", "V", str(repo), "main...feat", "--context", "2")
        by_path = {entry["path"]: entry["diff"] for entries in json.loads(diffs.read_text(encoding="utf-8")).values() for entry in entries}
        heads = [line.split("@@")[-1].strip() for diff in by_path.values() for line in diff.splitlines() if line.startswith("@@")]
        self.assertEqual(sorted(heads), sorted(['<template>', '<script setup lang="ts">', '<style lang="scss" scoped>', '<script lang="ts">', "</script>"]))
        paths = {"Dockerfile": "dockerfile", "ops/Dockerfile.dev": "dockerfile", "app/build.gradle": "groovy", "settings.gradle.kts": "kotlin",
                 "api/visit.proto": "protobuf", "web/.env.local": "ini", ".env": "ini", "pyproject.toml": "ini", "a.mts": "typescript",
                 "a.cts": "typescript", "a.mjs": "javascript", "a.cjs": "javascript", "db/schema.pgsql": "pgsql", "q.sql": "sql",
                 "Makefile": "makefile", "schema.graphql": "graphql", "Card.vue": "xml", "infra/main.tf": None, "LICENSE": None, "c": None}
        cases = self.root / "langs.json"
        cases.write_text(json.dumps({"paths": list(paths), "diffs": by_path}), encoding="utf-8")
        script = self.root / "viewer-langs.js"
        script.write_text(VIEWER_LANGS, encoding="utf-8")
        result = subprocess.run(["node", str(script), str(SKILL / "assets" / "viewer.html"), str(cases)], capture_output=True, text=True, check=True)
        out = json.loads(result.stdout)
        self.assertEqual(out["paths"], paths)
        langs = {(path, side, text): lang for path, rows in out["rows"].items() for side, _line, text, lang in rows}
        for path, text, lang in (
            ("Card.vue", '<li class="r5">{{ n5 }}</li>', "xml"), ("Card.vue", '<li class="r5 on">{{ n5 }}</li>', "xml"),
            ("Card.vue", "const n5: number = 5;", "typescript"), ("Card.vue", "const n5: number = 50;", "typescript"),
            ("Card.vue", ".r5 { margin: $gap * 5; }", "scss"), ("Card.vue", ".r5 { margin: $gap * 6; }", "scss"),
            ("Page.svelte", "let v5: number = 55;", "typescript"), ("Page.svelte", '<p class="on">{v5}</p>', "xml"),
        ):
            with self.subTest(path=path, text=text):
                side = "old" if (path, "old", text) in langs and (path, "new", text) not in langs else "new"
                self.assertEqual(langs[(path, side, text)], lang)

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
                self.assertEqual([(p["base"], p["tip"]) for p in config["prs"]], [(p["base"], p["tip"]) for p in self.graph["prs"]])
                for element in ('id="nt-panel"', 'id="nt-copy"', 'id="nt-clear"', 'id="nt-list"', 'id="nt-manual-text"',
                                'id="nt-filter"', 'id="nt-pr-add"', 'id="nt-pred"'):
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
