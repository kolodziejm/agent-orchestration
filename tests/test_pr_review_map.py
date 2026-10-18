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
# Runs the viewer's lang(), mdLang(), parse(), and sfcLangs(), cut out of assets/viewer.html, and prints the highlight.js
# language and the Markdown fence hint of every path in the input's "paths" and the language of every row of its
# "diffs" ({path: diff}) as [side, line, text, lang].
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
const code = cut('  function own(o,k)', 'function own(o,k)') + '\n' + cut('  var LANG={', 'function sfcLangs(path,hs){') + '\n'
  + cut('  function parse(diff){', 'function parse(diff){') + '\n' + cut('  function mdLang(p)', 'function mdLang(p)');
const api = new Function('DIFFS', 'esc', code + '\nreturn {lang: lang, parse: parse, sfcLangs: sfcLangs, mdLang: mdLang};')({}, String);
const input = JSON.parse(fs.readFileSync(inputFile, 'utf8'));
const out = {paths: {}, fences: {}, rows: {}};
input.paths.forEach((p) => { out.paths[p] = api.lang(p); out.fences[p] = api.mdLang(p); });
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
# Runs the viewer's note-state code (FILE lookup through stateOf()), cut out of assets/viewer.html, over a graph, diffs,
# and notes, and prints each note's state as {st, a?, b?, how?}.
NOTE_STATE = r"""
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
const code = [cut('  function own(o,k)', 'function own(o,k)'), cut('  function parse(diff){', 'function parse(diff){'),
  cut('  /* FILE[pr+', 'function stateOf(n){')].join('\n');
const input = JSON.parse(fs.readFileSync(inputFile, 'utf8'));
const stateOf = new Function('data', 'DIFFS', code + '\nreturn stateOf;')(input.graph, input.diffs);
process.stdout.write(JSON.stringify(input.notes.map((n) => { const s = stateOf(n); return Object.fromEntries(Object.entries(s).filter(([k]) => k !== 'k')); })));
"""

# Runs the viewer's note migration (chunkHome(), with the parent/part lookups and the note-state code it uses), cut out
# of assets/viewer.html, over a graph, diffs, and notes, and prints each note's new home with the graph's parents and
# without them.
CHUNK_HOME = r"""
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
function between(from, to) {
  const start = html.indexOf(from), end = html.indexOf(to, start);
  if (start < 0 || end < 0) throw new Error(from + ' not found in the viewer');
  return html.slice(start, end);
}
const code = [cut('  function own(o,k)', 'function own(o,k)'), between('  var PR=Object.create(null)', '  function layerOf(l)'),
  cut('  function parse(diff){', 'function parse(diff){'), cut('  /* FILE[pr+', 'function chunkHome(n){')].join('\n');
const input = JSON.parse(fs.readFileSync(inputFile, 'utf8'));
function homes(graph) {
  const cfg = {prs: graph.prs.map((p) => ({key: p.key, name: p.key}))};
  const chunkHome = new Function('CFG', 'data', 'DIFFS', 'S', code + '\nreturn chunkHome;')(cfg, graph, input.diffs, {});
  return input.notes.map((n) => chunkHome(JSON.parse(JSON.stringify(n))));
}
const plain = Object.assign({}, input.graph);
delete plain.parents;
process.stdout.write(JSON.stringify({parts: homes(input.graph), plain: homes(plain)}));
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
        """This test will fail when the viewer reads a removed "-- comment" or an added "++i" inside a hunk as a file header (and shifts the line numbers), when gen_diffs.py stops naming the block a Vue/Svelte hunk starts in on its @@ line as a short tag with its lang (also for a tag past git's 80-byte cut, with a ">" in an attribute, or spread over lines), the viewer highlights a hunk in the middle of a <template>, <script lang="ts">, or <style lang="scss"> block (or Svelte markup after </script>) in another block's language, a common file type loses its highlight.js language, or a file named after an Object.prototype property gets one."""
        repo = self.root / "sfc"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        vue = ["<template>", "  <ul>"] + [f'    <li class="r{i}">{{{{ n{i} }}}}</li>' for i in range(10)] + ["  </ul>", "</template>", "",
               '<script setup lang="ts">'] + [f"const n{i}: number = {i};" for i in range(10)] + ["</script>", "",
               '<style lang="scss" scoped>', "$gap: 4px;"] + [f".r{i} {{ margin: $gap * {i}; }}" for i in range(10)] + ["</style>", ""]
        svelte = ['<script lang="ts">'] + [f"  let v{i}: number = {i};" for i in range(10)] + ["</script>", "", "<main>"] + \
                 [f"  <p>{{v{i}}}</p>" for i in range(10)] + ["</main>", ""]
        # Long.vue's script tag runs past git's 80-byte funcname and hides a ">" in an attribute; Multi.vue's spans lines.
        # Their hunks end with </script>, so the viewer must take the block's lang from the @@ line.
        long_vue = ["<template>", "  <p>{{ m0 }}</p>", "</template>", "",
                    '<script setup generic="T extends Record<string, unknown>, U extends Array<T> = Array<T>" lang="ts">'] + \
                   [f"const m{i}: number = {i};" for i in range(12)] + ["</script>", ""]
        multi_vue = ["<template>", "  <p>{{ k0 }}</p>", "</template>", "", "<script", "  setup", '  lang="ts"', ">"] + \
                    [f"const k{i}: number = {i};" for i in range(12)] + ["</script>", ""]
        files = {"Card.vue": "\n".join(vue), "Page.svelte": "\n".join(svelte), "Long.vue": "\n".join(long_vue), "Multi.vue": "\n".join(multi_vue)}
        commit_files(repo, files, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        changed = {"    <li class=\"r5\">{{ n5 }}</li>": "    <li class=\"r5 on\">{{ n5 }}</li>",
                   "const n5: number = 5;": "const n5: number = 50;", ".r5 { margin: $gap * 5; }": ".r5 { margin: $gap * 6; }",
                   "  let v5: number = 5;": "  let v5: number = 55;", "  <p>{v5}</p>": "  <p class=\"on\">{v5}</p>",
                   "const m10: number = 10;": "const m10: number = 100;", "const k10: number = 10;": "const k10: number = 100;"}
        for old, new in changed.items():
            files = {path: text.replace(old, new) for path, text in files.items()}
        commit_files(repo, files, "feat")
        graph, diffs = self.root / "graphs-sfc.json", self.root / "diffs-sfc.json"
        run_script("build_graph.py", "--out", str(graph), "--pr", "V", str(repo), "main...feat")
        run_script("gen_diffs.py", "--graph", str(graph), "--out", str(diffs), "--pr", "V", str(repo), "main...feat", "--context", "2")
        by_path = {entry["path"]: entry["diff"] for entries in json.loads(diffs.read_text(encoding="utf-8")).values() for entry in entries}
        heads = [line.split("@@")[-1].strip() for diff in by_path.values() for line in diff.splitlines() if line.startswith("@@")]
        self.assertEqual(sorted(heads), sorted(['<template>', '<script lang="ts">', '<style lang="scss">', '<script lang="ts">', "</script>",
                                                '<script lang="ts">', '<script lang="ts">']))
        paths = {"Dockerfile": "dockerfile", "ops/Dockerfile.dev": "dockerfile", "app/build.gradle": "groovy", "settings.gradle.kts": "kotlin",
                 "api/visit.proto": "protobuf", "web/.env.local": "ini", ".env": "ini", "pyproject.toml": "ini", "a.mts": "typescript",
                 "a.cts": "typescript", "a.mjs": "javascript", "a.cjs": "javascript", "db/schema.pgsql": "pgsql", "q.sql": "sql",
                 "Makefile": "makefile", "schema.graphql": "graphql", "Card.vue": "xml", "infra/main.tf": None, "LICENSE": None, "c": None,
                 "src/x.constructor": None, "constructor": None, "src/__proto__": None, "a.toString": None, "b.hasOwnProperty": None,
                 "lib/valueOf": None}
        # A removed SQL comment and an added "++i" look like file headers ("--- ", "+++") but sit inside a hunk.
        by_path["q.sql"] = ("--- a/q.sql\n+++ b/q.sql\n@@ -1,4 +1,4 @@\n select 1;\n--- old comment\n+++i;\n select 2;\n select 3;\n"
                            "@@ -9 +9 @@\n--- x\n+-- y")
        cases = self.root / "langs.json"
        cases.write_text(json.dumps({"paths": list(paths), "diffs": by_path}), encoding="utf-8")
        script = self.root / "viewer-langs.js"
        script.write_text(VIEWER_LANGS, encoding="utf-8")
        result = subprocess.run(["node", str(script), str(SKILL / "assets" / "viewer.html"), str(cases)], capture_output=True, text=True, check=True)
        out = json.loads(result.stdout)
        self.assertEqual(out["paths"], paths)
        # A name that is an Object.prototype property is no language and no fence hint (it used to stop the page).
        self.assertEqual({p: out["fences"][p] for p in ("src/x.constructor", "constructor", "src/__proto__", "a.toString")},
                         {"src/x.constructor": "", "constructor": "", "src/__proto__": "", "a.toString": ""})
        self.assertEqual([(side, line, text) for side, line, text, _lang in out["rows"]["q.sql"]], [
            ("old", 1, "select 1;"), ("new", 1, "select 1;"), ("old", 2, "-- old comment"), ("new", 2, "++i;"),
            ("old", 3, "select 2;"), ("new", 3, "select 2;"), ("old", 4, "select 3;"), ("new", 4, "select 3;"),
            ("old", 9, "-- x"), ("new", 9, "-- y")])
        langs = {(path, side, text): lang for path, rows in out["rows"].items() for side, _line, text, lang in rows}
        for path, text, lang in (
            ("Card.vue", '<li class="r5">{{ n5 }}</li>', "xml"), ("Card.vue", '<li class="r5 on">{{ n5 }}</li>', "xml"),
            ("Card.vue", "const n5: number = 5;", "typescript"), ("Card.vue", "const n5: number = 50;", "typescript"),
            ("Card.vue", ".r5 { margin: $gap * 5; }", "scss"), ("Card.vue", ".r5 { margin: $gap * 6; }", "scss"),
            ("Page.svelte", "let v5: number = 55;", "typescript"), ("Page.svelte", '<p class="on">{v5}</p>', "xml"),
            ("Long.vue", "const m10: number = 100;", "typescript"), ("Multi.vue", "const k10: number = 100;", "typescript"),
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



def added(lines: list[str]) -> str:
    return f"--- /dev/null\n+++ b/f\n@@ -0,0 +1,{len(lines)} @@\n" + "\n".join("+" + line for line in lines)


class NoteStateTests(unittest.TestCase):
    """The viewer's note states, run in node on hand-written diffs."""

    @unittest.skipUnless(NODE, "node is required to run the viewer's note-state code")
    def test_notes_on_changed_code_move_go_stale_or_lose_their_file(self):
        """This test will fail when a note on code that moved (exactly, with white space changed, or slightly edited) is not moved to its code's new lines on the same side, when an in-place edit, an ambiguous match, a weak fuzzy match, or a snapshot with under 6 characters besides white space ("}", a blank line) does not leave it stale, when a note on a file the PR no longer changes is not "gone", or when file and PR notes stop being current."""
        svc = ["import { a } from './a';", "", "export function listItems(offset: number, limit: number) {",
               "  return ITEMS.slice(offset, offset + limit);", "}", "", "export const PAGE = 20;", "}", "}"]
        moved = ["import { a } from './a';", "// one", "// two", "", "export function listItems(offset: number, limit: number) {",
                 "  return ITEMS.slice(offset, offset + limit);", "}", "", "export const PAGE = 20;", "}", "}"]
        spaced = ["// x", "export  function listItems(offset: number,  limit: number) {", "    return ITEMS.slice(offset, offset + limit);", "}"]
        fuzzy = ["// x", "// y", "// z", "export function listItems(offset: number, limit: number, sort?: string) {", "  return ITEMS.slice(offset, offset + limit);"]
        inplace = ["import { a } from './a';", "", "export function listItems(page: Page) {", "  return ITEMS.slice(page.offset, page.end);", "}"]
        twice = ["const x = 1;", "export const PAGE = 20;", "const y = 2;", "export const PAGE = 20;"]
        weak = ["// a", "// b", "// c", "export function countItems(filter: Filter): number {", "  return ITEMS.filter(filter).length;", "}"]
        tuned = ["const x = 1;", "export const PAGE = 25;", "const y = 2;"]
        old_side = ("--- a/legacy.ts\n+++ b/legacy.ts\n@@ -10,4 +10,4 @@\n export function label(id: number) {\n"
                    "-  return 'item-' + id;\n+  return `item-${id}`;\n }\n ")
        diffs = {"P1": [{"path": "svc.ts", "diff": added(moved)}], "P2": [{"path": "sp.ts", "diff": added(spaced)}],
                 "P3": [{"path": "fz.ts", "diff": added(fuzzy)}], "P4": [{"path": "in.ts", "diff": added(inplace)}],
                 "P5": [{"path": "tw.ts", "diff": added(twice)}], "P6": [{"path": "legacy.ts", "diff": old_side}],
                 "P7": [{"path": "wk.ts", "diff": added(weak)}], "P8": [{"path": "tu.ts", "diff": added(tuned)}],
                 "P9": [{"path": "del.ts", "diff": "--- a/del.ts\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b"}]}
        graph = {"prs": [{"key": "P", "nodes": [{"id": i, "path": e[0]["path"]} for i, e in diffs.items()], "edges": []}]}

        def line(path, side, a, b, code, **extra):
            return {"id": f"{path}{a}{side}", "scope": "line", "pr": "P", "path": path, "side": side, "a": a, "b": b, "code": code, **extra}

        notes = [
            line("svc.ts", "new", 3, 5, svc[2:5]),        # three lines inserted above: exact move
            line("svc.ts", "new", 1, 1, svc[0:1]),        # unchanged
            line("sp.ts", "new", 3, 4, svc[2:4]),         # white space changed: moved, "ws"
            line("fz.ts", "new", 3, 4, svc[2:4]),         # a parameter added: moved, "fuzzy"
            line("in.ts", "new", 3, 4, svc[2:4]),         # rewritten in place: stale
            line("tw.ts", "new", 7, 7, svc[6:7]),         # the line now appears twice: stale (ambiguous)
            line("in.ts", "new", 8, 8, ["  return 42;"]),  # nowhere, and too short to match fuzzily: stale
            line("gone.ts", "new", 1, 2, ["a", "b"]),     # the PR no longer changes the file
            line("legacy.ts", "old", 2, 2, ["  return 'item-' + id;"]),  # the base moved by 9 lines: old side moved
            line("svc.ts", "new", 9, 8, svc[0:1]),        # malformed range: never matched in place
            {"id": "f1", "scope": "file", "pr": "P", "path": "in.ts"},
            {"id": "f2", "scope": "file", "pr": "P", "path": "gone.ts"},
            {"id": "p1", "scope": "pr", "pr": "P"},
            line("svc.ts", "new", 1, 1, None),            # no snapshot, its line still shown: current
            line("wk.ts", "new", 3, 4, svc[2:4]),         # only a loosely similar function elsewhere: stale
            line("tu.ts", "new", 2, 2, ["export const PAGE = 20;"]),  # edited in place, best fuzzy match is its own line: stale
            {"id": "f3", "scope": "file", "pr": "P", "path": "del.ts"},  # a file note on a file the PR deletes: current
            line("svc.ts", "new", 2, 2, ["}"]),           # "}" moved off its line: too little to relocate, stale
            line("svc.ts", "new", 3, 3, [""]),            # a blank line: stale, not moved to another blank line
            line("svc.ts", "new", 5, 6, ["}", "}"]),      # two "}" lines are still too little: stale
        ]
        script = Path(tempfile.mkdtemp()) / "note-state.js"
        script.write_text(NOTE_STATE, encoding="utf-8")
        inputs = script.with_name("in.json")
        inputs.write_text(json.dumps({"graph": graph, "diffs": diffs, "notes": notes}), encoding="utf-8")
        result = subprocess.run(["node", str(script), str(SKILL / "assets" / "viewer.html"), str(inputs)], capture_output=True, text=True, check=True)
        states = json.loads(result.stdout)
        shutil.rmtree(script.parent)
        self.assertEqual(states, [
            {"st": "moved", "a": 5, "b": 7, "how": "exact"}, {"st": "ok"}, {"st": "moved", "a": 2, "b": 3, "how": "ws"},
            {"st": "moved", "a": 4, "b": 5, "how": "fuzzy"}, {"st": "stale"}, {"st": "stale"}, {"st": "stale"}, {"st": "gone"},
            {"st": "moved", "a": 11, "b": 11, "how": "exact"}, {"st": "moved", "a": 1, "b": 1, "how": "exact"},
            {"st": "ok"}, {"st": "gone"}, {"st": "ok"}, {"st": "ok"}, {"st": "stale"}, {"st": "stale"}, {"st": "ok"},
            {"st": "stale"}, {"st": "stale"}, {"st": "stale"},
        ])


class ReviewMapRefreshTests(unittest.TestCase):
    """A report built once, then refreshed after its branch moved: manifest, refresh.py, fingerprints, previous build."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.repo = repo = cls.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        legacy = [f"export const v{i} = {i};" for i in range(12)]
        commit_files(repo, {"README.md": "# x\n", "src/legacy.ts": "\n".join(legacy) + "\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        cls.a_v1 = ["import { b } from './b';", "", "export function listItems(offset: number, limit: number) {",
                    "  return b(offset, limit);", "}"]
        commit_files(repo, {
            "src/a.ts": "\n".join(cls.a_v1) + "\n", "src/b.ts": "export const b = (o: number, l: number) => [o, l];\n",
            "src/c.ts": "export const c = 1;\n", "src/keep.ts": "export const keep = 1;\n",
            "src/legacy.ts": "\n".join(legacy).replace("v6 = 6", "v6 = 60") + "\n",
        }, "feat: items")
        cls.scratch = d = cls.root / "scratch"
        d.mkdir()
        cls.tip1 = git(repo, "rev-parse", "feat").strip()
        (d / "overlay.json").write_text(json.dumps({"nodes": {"A:src/c.ts": {"role": "Removed later"}, "A:src/a.ts": {"role": "Lists items"}}}), encoding="utf-8")
        (d / "groups.json").write_text(json.dumps([{"id": "imgs", "label": "images", "layer": "config", "pattern": "^img/"}]), encoding="utf-8")
        (d / "strings.json").write_text(json.dumps({"graphTitle": "Mapa"}), encoding="utf-8")
        (d / "narrative.html").write_text(
            f'<section id="stack"><h2>Stack</h2><div class="pr-card c-A">\n<span class="meta">tip <code>{cls.tip1[:7]}</code></span></div></section>\n'
            "<!-- review-map:graph -->\n<footer>x</footer>\n", encoding="utf-8")
        cls.build = ["--out", str(d / "graphs.json"), "--pr", "A", str(repo), "main...feat", "--name", "A", "A #1",
                     "--title", "A", "Items", "--repo", "A", "acme/items", "--alias", "@x/=src/", "--groups", str(d / "groups.json"),
                     "--overlay", str(d / "overlay.json")]
        run_script("build_graph.py", *cls.build)
        run_script("gen_diffs.py", "--graph", str(d / "graphs.json"), "--out", str(d / "diffs.json"), "--pr", "A", str(repo), "main...feat",
                   "--context", "3", "--max-lines", "500", "--strict")
        run_script("assemble.py", "--graph", str(d / "graphs.json"), "--diffs", str(d / "diffs.json"), "--narrative", str(d / "narrative.html"),
                   "--title", "Refresh Test", "--lang", "pl", "--strings", str(d / "strings.json"), "--storage-key", "items-review",
                   "--target", "local", "--out", str(d / "review.html"))
        cls.manifest_v1 = json.loads((d / "review-map.json").read_text(encoding="utf-8"))
        cls.diffs_v1 = json.loads((d / "diffs.json").read_text(encoding="utf-8"))
        cls.page_v1 = (d / "review.html").read_text(encoding="utf-8")
        # The branch moves: lines inserted above the code in a.ts, b.ts edited, c.ts removed, d.ts added; keep.ts and
        # legacy.ts stay as they were.
        git(repo, "rm", "-q", "src/c.ts")
        commit_files(repo, {"src/a.ts": "\n".join(cls.a_v1[:1] + ["// one", "// two"] + cls.a_v1[1:]) + "\n",
                            "src/b.ts": "export const b = (o: number, l: number) => [o, o + l];\n", "src/d.ts": "export const d = 4;\n"}, "fix: round 1")
        cls.tip2 = git(repo, "rev-parse", "feat").strip()
        cls.refs = git(repo, "for-each-ref"), git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")
        # A diffs.json written before fingerprints existed: refresh fingerprints its entries from their bodies (all text
        # here; a binary entry's body lacks the blob ids, so such a file shows as changed once).
        legacy_diffs = {k: [{key: v for key, v in e.items() if key != "fp"} for e in entries] for k, entries in cls.diffs_v1.items()}
        (d / "diffs.json").write_text(json.dumps(legacy_diffs), encoding="utf-8")
        cls.out = run_script("refresh.py", str(d)).stdout

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fps(self, diffs: dict) -> dict[str, str]:
        return {e["path"]: e["fp"] for entries in diffs.values() for e in entries}

    def test_the_manifest_records_every_input_relative_to_the_scratch_directory(self):
        """This test will fail when build_graph.py, gen_diffs.py, or assemble.py stop recording an input refresh.py needs, store a scratch file by an absolute path, a repository by a relative one, or leave the storage key unresolved."""
        m = self.manifest_v1
        self.assertEqual(m["version"], 1)
        self.assertEqual(m["build_graph"], {
            "out": "graphs.json", "prs": [{"key": "A", "repo": str(self.repo.resolve()), "range": "main...feat"}], "names": [["A", "A #1"]],
            "titles": [["A", "Items"]], "repos": [["A", "acme/items"]], "aliases": ["@x/=src/"], "groups": "groups.json",
            "noDefaultGroups": False, "overlay": "overlay.json", "tips": {"A": self.tip1}})
        self.assertEqual(m["gen_diffs"], {"graph": "graphs.json", "out": "diffs.json", "prs": [{"key": "A", "repo": str(self.repo.resolve()), "range": "main...feat"}],
                                          "context": 3, "maxLines": 500, "strict": True})
        self.assertEqual(m["assemble"], {"graph": "graphs.json", "diffs": "diffs.json", "narrative": "narrative.html", "title": "Refresh Test",
                                         "lang": "pl", "strings": "strings.json", "storageKey": "items-review", "target": "local",
                                         "template": None, "out": "review.html", "previous": None})
        other = self.root / "no-manifest"
        other.mkdir()
        run_script("build_graph.py", "--out", str(other / "g.json"), "--pr", "A", str(self.repo), "main...feat", "--no-manifest")
        self.assertFalse((other / "review-map.json").exists())
        result = run_script("refresh.py", str(other), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no review-map.json", result.stderr)

    def test_refresh_rebuilds_from_the_directory_and_reports_what_moved(self):
        """This test will fail when refresh.py does not resolve the branch to its new tip, print old -> new tips and the change counts, carry over the inputs (title, language, strings, storage key, target), warn about the narrative's old tip with its line, skip an overlay entry for a removed file instead of failing, update the manifest's tips, or writes to the repository."""
        out = self.out
        self.assertIn(f"PR A: {self.tip1[:7]} -> {self.tip2[:7]}", out)
        self.assertIn("changed since the previous version: 4 files (1 new, 2 changed, 1 removed)", out)
        self.assertIn(f"still shows its old tip {self.tip1[:7]} at narrative.html:2", out)
        self.assertIn("overlay reference 'A:src/c.ts': no node or changed file with that path in PR A; skipped", out)
        self.assertIn("OK", out)
        self.assertEqual((git(self.repo, "for-each-ref"), git(self.repo, "rev-parse", "HEAD"), git(self.repo, "status", "--porcelain")), self.refs)
        page = (self.scratch / "review.html").read_text(encoding="utf-8")
        config = embedded_json(page, "review-config")
        self.assertEqual((config["title"], config["lang"], config["storageKey"], config["strings"]["graphTitle"]), ("Refresh Test", "pl", "items-review", "Mapa"))
        self.assertTrue(page.startswith("<!doctype html>"))
        graph = embedded_json(page, "graph-data")
        self.assertEqual(graph["prs"][0]["tip"], self.tip2[:len(graph["prs"][0]["tip"])])
        self.assertEqual(json.loads((self.scratch / "review-map.json").read_text(encoding="utf-8"))["build_graph"]["tips"], {"A": self.tip2})
        self.assertFalse(list(self.scratch.glob("*.new")))

    def test_fingerprints_flag_new_changed_and_removed_files_only(self):
        """This test will fail when a file whose change is the same gets a new fingerprint (or one fingerprinted from an old diffs.json body differs), when an edited, shifted, or binary file keeps its old one, or when the page does not embed the previous build's tips and fingerprints."""
        new = self.fps(json.loads((self.scratch / "diffs.json").read_text(encoding="utf-8")))
        old = self.fps(self.diffs_v1)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{12}", fp) for fp in [*new.values(), *old.values()]))
        self.assertEqual({p for p in new if p in old and new[p] == old[p]}, {"src/keep.ts", "src/legacy.ts"})
        self.assertEqual({p for p in new if p in old and new[p] != old[p]}, {"src/a.ts", "src/b.ts"})
        self.assertEqual(set(new) - set(old), {"src/d.ts"})
        self.assertEqual(set(old) - set(new), {"src/c.ts"})
        previous = json.loads((self.scratch / "previous.json").read_text(encoding="utf-8"))
        self.assertEqual(previous, {"generation": 0, "tips": {"A": self.tip1[:len(previous["tips"]["A"])]}, "files": {"A": old}})
        config = embedded_json((self.scratch / "review.html").read_text(encoding="utf-8"), "review-config")
        self.assertEqual((config["previous"], config["generation"]), (previous, 1))
        self.assertEqual(embedded_json(self.page_v1, "review-config")["generation"], 0)
        # A binary file's fingerprint follows its blob, whose diff text is the same for every version.
        repo = self.root / "binary"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"x.bin": "a\0"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        prints = []
        for content in ("b\0", "c\0"):
            commit_files(repo, {"x.bin": content}, "edit")
            graph, diffs = repo.parent / "bg.json", repo.parent / "bd.json"
            run_script("build_graph.py", "--out", str(graph), "--pr", "B", str(repo), "main...feat", "--no-manifest")
            run_script("gen_diffs.py", "--graph", str(graph), "--out", str(diffs), "--pr", "B", str(repo), "main...feat", "--no-manifest")
            entry = next(e for entries in json.loads(diffs.read_text(encoding="utf-8")).values() for e in entries)
            self.assertTrue(entry.get("binary"))
            prints.append(entry["fp"])
        self.assertNotEqual(prints[0], prints[1])

    def test_a_base_that_moved_under_an_unchanged_change_keeps_its_fingerprint(self):
        """This test will fail when lines that only shift (the base gained lines above a hunk, the PR's change is the same) count as a change."""
        repo = self.root / "shift"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        body = [f"line {i}" for i in range(30)]
        commit_files(repo, {"f.txt": "\n".join(body) + "\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(repo, {"f.txt": "\n".join(body).replace("line 20", "line twenty") + "\n"}, "feat")
        results = []
        for step in ("v1", "v2"):
            if step == "v2":
                git(repo, "checkout", "-q", "main")
                commit_files(repo, {"f.txt": "\n".join(["new 1", "new 2", "new 3"] + body) + "\n"}, "main moves")
                git(repo, "rebase", "-q", "main", "feat")
            graph, diffs = repo.parent / f"s-{step}.json", repo.parent / f"sd-{step}.json"
            run_script("build_graph.py", "--out", str(graph), "--pr", "S", str(repo), "main...feat", "--no-manifest")
            run_script("gen_diffs.py", "--graph", str(graph), "--out", str(diffs), "--pr", "S", str(repo), "main...feat", "--no-manifest")
            results.append(next(e for entries in json.loads(diffs.read_text(encoding="utf-8")).values() for e in entries))
        self.assertNotEqual(results[0]["diff"], results[1]["diff"])
        self.assertEqual(results[0]["fp"], results[1]["fp"])

    @unittest.skipUnless(NODE, "node is required to validate the assembled page")
    def test_refresh_again_keeps_the_comparison_and_assemble_only_rebuilds_the_page(self):
        """This test will fail when a refresh that changes nothing alters the page (it must be byte-identical and keep the last comparison), when a failing step replaces the last good page or data, or when --assemble-only stops reassembling with the saved inputs and comparison."""
        page = (self.scratch / "review.html").read_bytes()
        previous = (self.scratch / "previous.json").read_bytes()
        again = run_script("refresh.py", str(self.scratch)).stdout
        self.assertIn("nothing changed since the last build; the page keeps its comparison", again)
        self.assertIn(f"PR A: {self.tip2[:7]} -> {self.tip2[:7]} (unchanged)", again)
        self.assertNotIn("warning: the branches moved", again)
        self.assertEqual((self.scratch / "review.html").read_bytes(), page)
        self.assertEqual((self.scratch / "previous.json").read_bytes(), previous)
        narrative = self.scratch / "narrative.html"
        good = narrative.read_text(encoding="utf-8")
        data = (self.scratch / "graphs.json").read_bytes(), (self.scratch / "diffs.json").read_bytes()
        try:
            narrative.write_text(good.replace("<!-- review-map:graph -->", ""), encoding="utf-8")
            failed = run_script("refresh.py", str(self.scratch), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual((self.scratch / "review.html").read_bytes(), page)
            self.assertEqual(((self.scratch / "graphs.json").read_bytes(), (self.scratch / "diffs.json").read_bytes()), data)
        finally:
            narrative.write_text(good.replace("<footer>x</footer>", "<footer>y</footer>"), encoding="utf-8")
        result = run_script("refresh.py", str(self.scratch), "--assemble-only").stdout
        self.assertIn("OK", result)
        rebuilt = (self.scratch / "review.html").read_text(encoding="utf-8")
        self.assertIn("<footer>y</footer>", rebuilt)
        self.assertEqual(embedded_json(rebuilt, "review-config")["previous"], json.loads(previous))
        narrative.write_text(good, encoding="utf-8")
        run_script("refresh.py", str(self.scratch), "--assemble-only")
        self.assertEqual((self.scratch / "review.html").read_bytes(), page)

    def test_a_manifest_or_command_line_cannot_smuggle_git_options_or_write_elsewhere(self):
        """This test will fail when a range, key, or name from review-map.json or the command line can reach git or argparse as an option (git diff --output= writes a file), when refresh.py writes an output outside its directory without --allow-outside, or when a title that starts with "-" no longer reaches assemble.py."""
        evil = self.root / "evil"
        pwned = self.root / "PWNED"
        shutil.copytree(self.scratch, evil)
        good = json.loads((evil / "review-map.json").read_text(encoding="utf-8"))

        def attempt(change, *extra):
            data = json.loads(json.dumps(good))
            change(data)
            (evil / "review-map.json").write_text(json.dumps(data), encoding="utf-8")
            return run_script("refresh.py", str(evil), *extra, check=False)

        def set_range(value):
            return lambda d: [pr.update(range=value) for name in ("build_graph", "gen_diffs") for pr in d[name]["prs"]]

        for name, change, message in (
            ("output option", set_range(f"--output={pwned} x..HEAD"), "must be base...tip or base..tip"),
            ("dash tip", set_range("main...--output=x"), "must be base...tip or base..tip"),
            ("dash key", lambda d: [pr.update(key="-A") for n in ("build_graph", "gen_diffs") for pr in d[n]["prs"]], "PR key"),
            ("dash repo", lambda d: [pr.update(repo="--upload-pack=x") for n in ("build_graph", "gen_diffs") for pr in d[n]["prs"]], "repository path"),
            ("dash name", lambda d: d["build_graph"].update(names=[["A", "--overlay=/etc/passwd"]]), "does not start with '-'"),
            ("graph outside", lambda d: d["build_graph"].update(out=str(self.root / "g.json")), "would write outside"),
            ("page outside", lambda d: d["assemble"].update(out=str(self.root / "page.html")), "would write outside"),
        ):
            with self.subTest(case=name):
                result = attempt(change)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stderr)
                self.assertFalse(pwned.exists())
        allowed = attempt(lambda d: d["assemble"].update(out=str(self.root / "page.html"), title="--draft"), "--assemble-only", "--allow-outside")
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertIn("<title>--draft</title>", (self.root / "page.html").read_text(encoding="utf-8"))
        for script, args in (("build_graph.py", ["--out", str(self.root / "x.json")]),
                             ("gen_diffs.py", ["--graph", str(self.scratch / "graphs.json"), "--out", str(self.root / "x.json")])):
            with self.subTest(script=script):
                result = run_script(script, *args, "--pr", "A", str(self.repo), f"--output={pwned} x..HEAD", "--no-manifest", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must be base...tip or base..tip", result.stderr)
                self.assertFalse(pwned.exists())

    def test_each_refresh_that_changes_something_counts_one_generation_up(self):
        """This test will fail when a later refresh does not record the replaced build's generation in previous.json or the page's own generation one above it, which the viewer needs to tell older pages from newer ones."""
        repo, scratch = self.root / "gen-repo", self.root / "gen-scratch"
        shutil.copytree(self.repo, repo)
        shutil.copytree(self.scratch, scratch)
        data = json.loads((scratch / "review-map.json").read_text(encoding="utf-8"))
        for name in ("build_graph", "gen_diffs"):
            for pr in data[name]["prs"]:
                pr["repo"] = str(repo.resolve())
        (scratch / "review-map.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(embedded_json((scratch / "review.html").read_text(encoding="utf-8"), "review-config")["generation"], 1)
        commit_files(repo, {"src/d.ts": "export const d = 5;\n"}, "fix: round 2")
        run_script("refresh.py", str(scratch))
        self.assertEqual(json.loads((scratch / "previous.json").read_text(encoding="utf-8"))["generation"], 1)
        self.assertEqual(embedded_json((scratch / "review.html").read_text(encoding="utf-8"), "review-config")["generation"], 2)

    def test_every_build_path_numbers_pages_by_what_they_show(self):
        """This test will fail when a build by hand (build_graph, gen_diffs, assemble without --previous) does not count the generation up after the content changed, when a rebuild of the same content changes the bytes or the number (also the first refresh after a hand build, which adds --previous), when refresh.py takes its numbers from anything but the page it replaces (a hand build after a refresh must not reset the count), or when a page written under a new name loses the history the manifest points to."""
        repo, d = self.root / "hand-repo", self.root / "hand"
        shutil.copytree(self.repo, repo)
        git(repo, "checkout", "-q", "-B", "feat", self.tip1)
        d.mkdir()
        for name in ("narrative.html", "overlay.json"):
            shutil.copy(self.scratch / name, d / name)

        def build(*extra, out="review.html"):
            run_script("build_graph.py", "--out", str(d / "graphs.json"), "--pr", "A", str(repo), "main...feat", "--overlay", str(d / "overlay.json"))
            run_script("gen_diffs.py", "--graph", str(d / "graphs.json"), "--out", str(d / "diffs.json"), "--pr", "A", str(repo), "main...feat")
            run_script("assemble.py", "--graph", str(d / "graphs.json"), "--diffs", str(d / "diffs.json"), "--narrative", str(d / "narrative.html"),
                       "--title", "Hand", "--target", "local", "--out", str(d / out), *extra)
            page = (d / out).read_text(encoding="utf-8")
            return embedded_json(page, "review-config").get("generation"), page

        gen, v1 = build()
        self.assertEqual(gen, 0)
        self.assertEqual(build(), (0, v1))
        commit_files(repo, {"src/a.ts": "export const a = 2;\n"}, "hand round 1")
        gen, v2 = build()
        self.assertEqual(gen, 1)
        self.assertNotIn('"previous"', v2)
        self.assertEqual(build(), (1, v2))
        # The first refresh after a hand build finds the same content: it adds the comparison but keeps generation 1.
        for _ in range(2):
            run_script("refresh.py", str(d))
            self.assertEqual(embedded_json((d / "review.html").read_text(encoding="utf-8"), "review-config")["generation"], 1)
        commit_files(repo, {"src/b.ts": "export const b = 3;\n"}, "hand round 2")
        run_script("refresh.py", str(d))
        self.assertEqual(json.loads((d / "previous.json").read_text(encoding="utf-8"))["generation"], 1)
        self.assertEqual(build()[0], 2)
        commit_files(repo, {"src/c.ts": "export const c = 4;\n"}, "hand round 3")
        self.assertEqual(build()[0], 3)
        self.assertEqual(build(out="renamed.html")[0], 3)
        commit_files(repo, {"src/c.ts": "export const c = 5;\n"}, "hand round 4")
        self.assertEqual(build(out="renamed-again.html")[0], 4)

    def test_a_page_assemble_cannot_read_gives_no_history_and_never_a_crash(self):
        """This test will fail when assemble.py crashes on, or takes a generation from, a page at --out whose review-map data has an unexpected shape (diff entries that are not lists of objects, PRs that are not a list, a node without an id, a non-string fingerprint) or whose generation is not an int from 0 to 2**31 (a bool, a string, a float, a negative or huge number), or when such a generation passes validate.py or --previous."""
        d = self.root / "odd-pages"
        d.mkdir()
        page = d / "review.html"
        args = ["--graph", str(self.scratch / "graphs.json"), "--diffs", str(self.scratch / "diffs.json"), "--narrative",
                str(self.scratch / "narrative.html"), "--title", "odd", "--target", "local", "--out", str(page), "--no-manifest"]
        run_script("assemble.py", *args)
        good = page.read_text(encoding="utf-8")
        config = embedded_json(good, "review-config")

        def block(text: str, ident: str, value) -> str:
            return re.sub(rf'(<script type="application/json" id="{ident}">).*?(</script>)',
                          lambda m: m.group(1) + json.dumps(value).replace("</", "<\\/") + m.group(2), text, flags=re.DOTALL)

        cases = {
            "diff entries not lists": block(good, "diff-data", {"x": [1]}),
            "prs not a list": block(good, "graph-data", {"prs": "zz"}),
            "node without id": block(good, "graph-data", {"prs": [{"key": "A", "nodes": [{"path": "a"}]}]}),
            "fingerprint not a string": block(good, "diff-data", {"A1": [{"path": "a", "fp": 5}]}),
            "unparsable data": good.replace('<script type="application/json" id="graph-data">{', '<script type="application/json" id="graph-data">{{', 1),
            **{f"generation {value!r}": block(good, "review-config", {**config, "generation": value})
               for value in (True, "7", 1.5, -1, 2**31 + 1)},
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                page.write_text(text, encoding="utf-8")
                result = run_script("assemble.py", *args, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("build history is ignored", result.stdout)
                self.assertEqual(embedded_json(page.read_text(encoding="utf-8"), "review-config")["generation"], 0)
        page.write_text(block(good, "review-config", {**config, "generation": 2**31}), encoding="utf-8")
        run_script("assemble.py", *args)
        self.assertEqual(embedded_json(page.read_text(encoding="utf-8"), "review-config")["generation"], 2**31)
        self.assertEqual(run_script("validate.py", str(page), check=False).returncode, 0)
        page.write_text(block(good, "review-config", {**config, "generation": 2**31 + 1}), encoding="utf-8")
        self.assertIn("integer from 0 to 2**31", run_script("validate.py", str(page), check=False).stdout)
        previous = d / "previous.json"
        previous.write_text(json.dumps({"generation": 2**31 + 1, "tips": {}, "files": {}}), encoding="utf-8")
        result = run_script("assemble.py", *args, "--previous", str(previous), check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_fingerprints_see_mode_changes_renames_and_copies(self):
        """This test will fail when a mode change or a pure rename leaves no trace in the fingerprint (every such file would hash to the same empty body), or when an ordinary new text file stops matching the fingerprint refresh.py computes from an old diffs.json body."""
        flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ in the skill
        sys.path.insert(0, str(SCRIPTS))
        try:
            import gen_diffs
        finally:
            sys.path.remove(str(SCRIPTS))
            sys.dont_write_bytecode = flag
        repo = self.root / "modes"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"a.sh": "echo a\n", "b.txt": "same content for a rename\n", "c.txt": "other content here\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        (repo / "a.sh").chmod(0o755)
        git(repo, "mv", "b.txt", "b2.txt")
        git(repo, "mv", "c.txt", "c2.txt")
        commit_files(repo, {"new.txt": "fresh\n"}, "modes and renames")
        diff = git(repo, "-c", "core.fileMode=true", "diff", "--full-index", "-M", "main...feat")
        files = {path: (body, fp) for path, body, _binary, fp in gen_diffs.split_files(diff)}
        self.assertEqual(set(files), {"a.sh", "b2.txt", "c2.txt", "new.txt"})
        self.assertEqual([files[p][0] for p in ("a.sh", "b2.txt", "c2.txt")], ["", "", ""])
        self.assertEqual(len({files[p][1] for p in ("a.sh", "b2.txt", "c2.txt")}), 3)
        self.assertNotEqual(files["a.sh"][1], gen_diffs.fingerprint(""))
        self.assertEqual(files["new.txt"][1], gen_diffs.fingerprint(files["new.txt"][0]))

    def test_assemble_refuses_a_pr_colour_that_is_not_a_colour(self):
        """This test will fail when a PR colour from graphs.json can carry CSS or markup into the page's <style>."""
        graph = json.loads((self.scratch / "graphs.json").read_text(encoding="utf-8"))
        for color, ok in (("red}</style><script>alert(1)</script>", False), ("url(https://x.test/a)", False), ("var(--pal-9)", False),
                          ("#1f7ae0", True), ("teal", True), ("var(--pal-3)", True)):
            with self.subTest(color=color):
                graph["prs"][0]["color"] = color
                path = self.root / "colour.json"
                path.write_text(json.dumps(graph), encoding="utf-8")
                result = run_script("assemble.py", "--graph", str(path), "--diffs", str(self.scratch / "diffs.json"), "--narrative",
                                    str(self.scratch / "narrative.html"), "--title", "c", "--out", str(self.root / "colour.html"),
                                    "--no-manifest", check=False)
                self.assertEqual(result.returncode == 0, ok, result.stderr)


def chunk_repo(repo: Path) -> list[str]:
    """A PR whose commits go core, core, web, web, core: src/core/service.ts changes in the first and the last part."""
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit_files(repo, {"README.md": "# x\n"}, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    steps = [
        ({"src/core/types.ts": "export type T = number;\n", "src/core/util.ts": "export const u = 1;\n"}, "feat(core): types"),
        ({"src/core/service.ts": "import type { T } from './types';\nexport const one = (): T => 1;\n",
          "src/core/types.ts": "export type T = number | string;\n"}, "feat(core): service"),
        ({"web/page.tsx": "import { one } from '../src/core/service';\nexport const Page = () => one();\n"}, "feat(web): page"),
        ({"web/page.spec.tsx": "import { Page } from './page';\ntest('page', () => Page());\n"}, "test(web): page spec"),
        ({"src/core/service.ts": "import type { T } from './types';\nexport const one = (): T => 2;\n"}, "fix(core): service edge"),
    ]
    shas = []
    for files, message in steps:
        commit_files(repo, files, message)
        shas.append(git(repo, "rev-parse", "HEAD").strip())
    return shas


# Feature folders of the large-PR fixture, each after the folders it uses (so a split by commits never imports forward).
AREAS = {"auth": [], "catalog": [], "billing": ["auth"], "profile": ["auth"], "search": ["catalog"],
         "checkout": ["billing", "catalog", "auth"], "notify": ["auth", "profile"], "reports": ["billing", "catalog", "search"],
         "admin": ["auth", "profile", "reports"]}


def area_files(name: str, uses: list[str]) -> dict[str, str]:
    """One feature folder of the large-PR fixture: 15 linked files (types, api, store, service, hooks, components,
    routes, index) and 3 tests; its service uses each used folder's service and its view their types."""
    a, base = name.capitalize(), f"src/{name}"
    up, up2 = "import { t } from '../shared/i18n';\n", "import { t } from '../../shared/i18n';\n"
    fail, fail2 = "import { fail } from '../shared/errors';\n", "import { fail } from '../../shared/errors';\n"
    return {
        f"{base}/types.ts": f"export type {a}Id = string;\n",
        f"{base}/api/client.ts": f"import type {{ {a}Id }} from '../types';\nexport const get = (id: {a}Id) => id;\n",
        f"{base}/api/endpoints.ts": f"import {{ get }} from './client';\nimport type {{ {a}Id }} from '../types';\nexport const one = (id: {a}Id) => get(id);\n",
        f"{base}/store/state.ts": f"import type {{ {a}Id }} from '../types';\nexport const state: {a}Id[] = [];\n",
        f"{base}/store/actions.ts": "import { state } from './state';\nimport { one } from '../api/endpoints';\n" + fail2
        + "export const load = () => state.map(one).concat(fail());\n",
        f"{base}/store/selectors.ts": "import { state } from './state';\nexport const all = () => state;\n",
        f"{base}/service.ts": "import { load } from './store/actions';\nimport { all } from './store/selectors';\n" + up + fail
        + "".join(f"import {{ run as {u}Run }} from '../{u}/service';\n" for u in uses) + f"export const run = () => [load(), all(), t('{name}'), fail()];\n",
        f"{base}/hooks/use{a}.ts": "import { run } from '../service';\n" + up2 + f"export const use{a} = () => [run(), t('x')];\n",
        f"{base}/hooks/use{a}List.ts": "import { run } from '../service';\nimport { all } from '../store/selectors';\n"
        + f"export const use{a}List = () => [run(), all()];\n",
        f"{base}/components/{a}View.tsx": f"import {{ use{a} }} from '../hooks/use{a}';\n" + up2 + fail2
        + "".join(f"import type {{ {u.capitalize()}Id }} from '../../{u}/types';\n" for u in uses) + f"export const {a}View = () => use{a}();\n",
        f"{base}/components/{a}List.tsx": f"import {{ use{a}List }} from '../hooks/use{a}List';\n" + up2
        + f"import {{ format }} from '../../shared/format';\nexport const {a}List = () => use{a}List();\n",
        f"{base}/components/{a}Item.tsx": f"import type {{ {a}Id }} from '../types';\nexport const {a}Item = (id: {a}Id) => id;\n",
        f"{base}/components/{a}Form.tsx": f"import {{ use{a} }} from '../hooks/use{a}';\n" + up2 + fail2 + f"export const {a}Form = () => use{a}();\n",
        f"{base}/routes.ts": "".join(f"import {{ {a}{c} }} from './components/{a}{c}';\n" for c in ("View", "List", "Item", "Form"))
        + f"export const routes = [{a}View, {a}List, {a}Item, {a}Form];\n",
        f"{base}/index.ts": "export { routes } from './routes';\nexport { run } from './service';\n",
        f"{base}/service.test.ts": "import { run } from './service';\ntest('run', () => run());\n",
        f"{base}/store/actions.test.ts": "import { load } from './actions';\ntest('load', () => load());\n",
        f"{base}/components/{a}View.test.tsx": f"import {{ {a}View }} from './{a}View';\ntest('view', () => {a}View());\n",
    }


def area_repo(repo: Path) -> None:
    """The large-PR fixture: one commit per feature folder (AREAS, scope = folder) after the shared files, then docs:
    168 nodes, 138 of them core, with src/shared/i18n.ts and src/shared/errors.ts used by most files (hubs)."""
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit_files(repo, {"README.md": "# x\n"}, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    commit_files(repo, {"src/shared/i18n.ts": "export const t = (k: string) => k;\n",
                        "src/shared/errors.ts": "import { t } from './i18n';\nexport const fail = () => t('failed');\n",
                        "src/shared/format.ts": "export const format = (v: string) => v.trim();\n"}, "feat(shared): i18n, errors, format")
    for name, uses in AREAS.items():
        commit_files(repo, area_files(name, uses), f"feat({name}): {name} feature")
    commit_files(repo, {"docs/areas.md": "# areas\n", "package.json": '{"name": "areas"}\n',
                        "locales/en.json": '{"x": "x"}\n', "locales/pl.json": '{"x": "x"}\n'}, "docs: areas")


def area_overlay(path: Path, key: str = "P") -> None:
    """Areas for six of the fixture's nine folders (the rest fall back to folders), plus a hub and the docs given an
    area they cannot keep."""
    authored = ["auth", "billing", "catalog", "checkout", "profile", "search"]
    nodes = {f"{key}:{f}": {"cluster": name} for name in authored for f in area_files(name, AREAS[name]) if ".test." not in f}
    nodes[f"{key}:src/shared/i18n.ts"] = {"cluster": "auth"}
    nodes[f"{key}:#docs"] = {"cluster": "auth"}
    path.write_text(json.dumps({"clusters": {name: {"label": name.capitalize(), "order": i} for i, name in enumerate(authored, 1)},
                                "nodes": nodes}), encoding="utf-8")


class AreaTests(unittest.TestCase):
    """Areas ("clusters") of a large PR: the overlay, build_graph.py and validate.py, and the viewer's areas and overview."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.repo = cls.root / "repo"
        area_repo(cls.repo)
        cls.overlay = cls.root / "overlay.json"
        area_overlay(cls.overlay)
        cls.out = {}
        for name, extra in (("areas", ["--overlay", str(cls.overlay)]), ("plain", [])):
            graph, diffs = cls.root / f"{name}.json", cls.root / f"{name}-diffs.json"
            cls.out[name] = run_script("build_graph.py", "--out", str(graph), "--pr", "P", str(cls.repo), "main...feat", "--no-manifest", *extra).stdout
            run_script("gen_diffs.py", "--graph", str(graph), "--out", str(diffs), "--pr", "P", str(cls.repo), "main...feat", "--no-manifest")
        cls.graph = json.loads((cls.root / "areas.json").read_text(encoding="utf-8"))
        cls.plain = json.loads((cls.root / "plain.json").read_text(encoding="utf-8"))
        cls.narrative = cls.root / "narrative.html"
        cls.narrative.write_text('<section id="s"><h2>S</h2></section>\n<!-- review-map:graph -->\n', encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def page(self, graph: dict, name: str) -> Path:
        path, out = self.root / f"{name}-graph.json", self.root / f"{name}.html"
        path.write_text(json.dumps(graph), encoding="utf-8")
        run_script("assemble.py", "--graph", str(path), "--diffs", str(self.root / "areas-diffs.json"), "--narrative", str(self.narrative),
                   "--title", "Areas", "--out", str(out), "--no-manifest")
        return out

    def test_overlay_areas_reach_their_nodes_and_each_pr_lists_the_ones_it_uses(self):
        """This test will fail when build_graph.py stops copying an overlay area onto its nodes and listing, per PR, the areas its nodes use in their order with their labels, keeps an area on a shared dependency or a docs/config/i18n node instead of warning, gives a test an area it was not given, stops naming the core files without an area or the large PR without areas, or accepts an unknown area, a malformed id, or a non-integer order."""
        pr = self.graph["prs"][0]
        self.assertEqual(pr["clusters"], [{"id": name, "label": name.capitalize(), "order": i}
                                          for i, name in enumerate(["auth", "billing", "catalog", "checkout", "profile", "search"], 1)])
        by_path = {node["path"]: node for node in pr["nodes"]}
        self.assertEqual(by_path["src/checkout/service.ts"]["cluster"], "checkout")
        self.assertEqual(by_path["src/auth/components/AuthView.tsx"]["cluster"], "auth")
        for path in ("src/checkout/service.test.ts", "src/admin/service.ts", "src/shared/format.ts", "src/shared/i18n.ts", "docs/areas.md"):
            with self.subTest(path=path):
                self.assertNotIn("cluster", by_path.get(path) or next(n for n in pr["nodes"] if path in n.get("files", [])))
        self.assertTrue(by_path["src/shared/i18n.ts"]["hub"])
        out = self.out["areas"]
        self.assertIn("overlay cluster 'auth' ignored for src/shared/i18n.ts: it is a shared dependency", out)
        self.assertIn("overlay cluster 'auth' ignored for docs/areas.md: it is docs", out)
        self.assertIn("areas: auth 15, billing 15, catalog 15, checkout 15, profile 15, search 15", out)
        self.assertIn("hint: PR P: 46 core files have no area, so the map groups them by folder", out)
        self.assertNotIn("clusters", self.plain["prs"][0])
        self.assertFalse([n for n in self.plain["prs"][0]["nodes"] if "cluster" in n])
        self.assertIn("hint: PR P has 138 core files; above 40 its map opens on an overview of areas", self.out["plain"])
        for name, overlay, message in (
            ("unknown", {"clusters": {"a": {}}, "nodes": {"P:src/auth/types.ts": {"cluster": "b"}}}, "unknown cluster 'b'"),
            ("bad id", {"clusters": {"a b": {}}}, "overlay cluster id 'a b'"),
            ("order", {"clusters": {"a": {"order": "1"}}}, "order must be an integer"),
            ("shape", {"clusters": ["a"]}, 'overlay "clusters" must be an object'),
        ):
            with self.subTest(case=name):
                path = self.root / "bad-overlay.json"
                path.write_text(json.dumps(overlay), encoding="utf-8")
                result = run_script("build_graph.py", "--out", str(self.root / "never.json"), "--pr", "P", str(self.repo), "main...feat",
                                    "--overlay", str(path), "--no-manifest", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    @unittest.skipUnless(NODE, "node is required to validate the assembled page")
    def test_validate_rejects_unknown_areas_and_warns_about_too_few_or_empty_ones(self):
        """This test will fail when validate.py passes a node whose area its PR does not list or a malformed area list, or stays silent about fewer than 4 areas, an area with no core node (only tests, hubs, or docs/config/i18n), or a PR above 40 core nodes without areas; or when it flags a well-formed page."""
        good = run_script("validate.py", str(self.page(self.graph, "good")), check=False)
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertNotIn("cluster", good.stdout)
        plain = run_script("validate.py", str(self.page(self.plain, "plain")), check=False)
        self.assertEqual(plain.returncode, 0, plain.stdout)
        self.assertIn("warning: PR P: 138 core nodes and no clusters; the map overview groups them by folder", plain.stdout)

        def broken(change):
            graph = json.loads(json.dumps(self.graph))
            change(graph["prs"][0])
            return run_script("validate.py", str(self.page(graph, "broken")), check=False)

        unknown = broken(lambda pr: pr["nodes"][0].update(cluster="nope"))
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("unknown cluster 'nope'", unknown.stdout)
        twice = broken(lambda pr: pr["clusters"].append(dict(pr["clusters"][0])))
        self.assertIn("cluster id 'auth' is listed twice", twice.stdout)
        self.assertEqual(broken(lambda pr: pr["clusters"][0].update(order="1")).returncode, 1)

        def few(pr):
            keep = {"auth", "billing", "catalog"}
            pr["clusters"] = [c for c in pr["clusters"] if c["id"] in keep] + [{"id": "tests", "label": "Tests", "order": 9}]
            for node in pr["nodes"]:
                if node.get("cluster") not in keep:
                    node.pop("cluster", None)
            next(n for n in pr["nodes"] if n["layer"] == "test")["cluster"] = "tests"

        warned = broken(few)
        self.assertEqual(warned.returncode, 0, warned.stdout)
        self.assertNotIn("4 clusters;", warned.stdout)
        self.assertIn("clusters with no core node (only tests, hubs, or docs/config/i18n): ['tests']", warned.stdout)

        def three(pr):
            pr["clusters"] = pr["clusters"][:3]
            for node in pr["nodes"]:
                if node.get("cluster") not in (None, "auth", "billing", "catalog"):
                    del node["cluster"]

        self.assertIn("warning: PR P: 3 clusters; 4 to 15", broken(three).stdout)


class ChunkTests(unittest.TestCase):
    """One PR split into parts cut from its commits: chunks.py propose and expand, build_graph.py and gen_diffs.py --chunks."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.repo = cls.root / "repo"
        cls.shas = chunk_repo(cls.repo)
        cls.scratch = d = cls.root / "scratch"
        d.mkdir()
        cls.refs = git(cls.repo, "for-each-ref"), git(cls.repo, "rev-parse", "HEAD"), git(cls.repo, "status", "--porcelain")
        cls.propose = run_script("chunks.py", "propose", "--repo", str(cls.repo), "--range", "main...feat", "--key", "M",
                                 "--name", "#9", "--out", str(d / "chunks.json"), "--min-files", "1").stdout
        cls.chunks = json.loads((d / "chunks.json").read_text(encoding="utf-8"))
        (d / "overlay.json").write_text(json.dumps({
            "nodes": {"M:src/core/service.ts": {"role": "Service"}, "Mb:web/page.tsx": {"note": "Only in part 2."}},
            "edges": [{"from": "M:web/page.tsx", "to": "M:src/core/types.ts", "kind": "config"},
                      {"from": "M:src/core/service.ts", "to": "M:web/page.spec.tsx", "kind": "config"},
                      {"from": "M:src/core/types.ts", "to": "M:web/page.tsx", "kind": "config"}],
        }), encoding="utf-8")
        cls.build = run_script("build_graph.py", "--out", str(d / "graphs.json"), "--chunks", str(d / "chunks.json"),
                               "--overlay", str(d / "overlay.json")).stdout
        cls.graph = json.loads((d / "graphs.json").read_text(encoding="utf-8"))
        run_script("gen_diffs.py", "--graph", str(d / "graphs.json"), "--out", str(d / "diffs.json"), "--chunks", str(d / "chunks.json"), "--strict")
        cls.diffs = json.loads((d / "diffs.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def pr(self, key: str) -> dict:
        return next(pr for pr in self.graph["prs"] if pr["key"] == key)

    def node(self, key: str, path: str) -> dict:
        return next(n for n in self.pr(key)["nodes"] if n["path"] == path)

    def test_propose_groups_consecutive_commits_by_scope_deterministically(self):
        """This test will fail when chunks.py propose stops grouping consecutive commits by their conventional-commit scope, cutting parts at the last commit of each group with keys that end in a letter, warning about a scope that comes back later (interleaved history), merging a group under --min-files into its neighbour, giving the same draft for the same history, refusing to overwrite a draft without --force, or when it writes to the repository."""
        self.assertEqual([(p["key"], p["to"], p["label"]) for p in self.chunks["parts"]],
                         [("Ma", self.shas[1], "core"), ("Mb", self.shas[3], "web"), ("Mc", self.shas[4], "core")])
        self.assertEqual(self.chunks["parent"], {"key": "M", "repo": str(self.repo.resolve()), "range": "main...feat", "name": "#9"})
        self.assertIn("1/3   Ma   2        3      core", self.propose)
        self.assertIn("warning: scope 'core' appears in parts 1, 3 with other scopes between them (interleaved history)", self.propose)
        again = self.root / "again.json"
        run_script("chunks.py", "propose", "--repo", str(self.repo), "--range", "main...feat", "--key", "M", "--name", "#9",
                   "--out", str(again), "--min-files", "1")
        self.assertEqual(again.read_bytes(), (self.scratch / "chunks.json").read_bytes())
        refused = run_script("chunks.py", "propose", "--repo", str(self.repo), "--range", "main...feat", "--key", "M", "--out", str(again), check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--force", refused.stderr)
        run_script("chunks.py", "propose", "--repo", str(self.repo), "--range", "main...feat", "--key", "M", "--out", str(again),
                   "--min-files", "3", "--force")
        merged = json.loads(again.read_text(encoding="utf-8"))["parts"]
        self.assertEqual([(p["key"], p["to"], p["label"]) for p in merged], [("Ma", self.shas[1], "core"), ("Mb", self.shas[4], "web + core")])
        self.assertEqual((git(self.repo, "for-each-ref"), git(self.repo, "rev-parse", "HEAD"), git(self.repo, "status", "--porcelain")), self.refs)

    def test_propose_gives_a_base_merge_a_part_of_its_own(self):
        """This test will fail when a merge of the base branch inside the PR lands in a part with the PR's own commits (that part's diff would show the base's changes) or goes without a warning."""
        repo = self.root / "merges"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit_files(repo, {"README.md": "# x\n"}, "base")
        git(repo, "checkout", "-q", "-b", "feat")
        commit_files(repo, {"a.ts": "export const a = 1;\n"}, "feat(api): a")
        git(repo, "checkout", "-q", "main")
        commit_files(repo, {"base.ts": "export const b = 1;\n"}, "chore: base moves")
        git(repo, "checkout", "-q", "feat")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "main")
        commit_files(repo, {"a2.ts": "export const a2 = 1;\n"}, "feat(api): a2")
        out = self.root / "merges.json"
        result = run_script("chunks.py", "propose", "--repo", str(repo), "--range", "main...feat", "--key", "P", "--out", str(out), "--min-files", "5")
        parts = json.loads(out.read_text(encoding="utf-8"))["parts"]
        merge = git(repo, "rev-parse", "feat^").strip()
        self.assertEqual([p["to"] for p in parts], [git(repo, "rev-parse", "feat~2").strip(), merge, git(repo, "rev-parse", "feat").strip()])
        self.assertIn(f"part 2 (Pb) holds only the base merge {merge[:7]}", result.stdout)

    def test_each_part_is_a_pr_with_its_chunk_and_the_parent_lists_them(self):
        """This test will fail when build_graph.py --chunks does not turn each part into a PR with its from..to range and chunk metadata (contiguous, numbered, commit count, subjects, label) and a default name, list the parent under parents, record the chunks file relative to the scratch directory, accept a --pr with the parent's key as the parts' place, or stays silent about a PR above 100 files."""
        self.assertEqual([pr["key"] for pr in self.graph["prs"]], ["Ma", "Mb", "Mc"])
        starts = [git(self.repo, "merge-base", "main", "feat").strip(), *self.shas[1:4:2]]
        for index, (key, start, end) in enumerate(zip(("Ma", "Mb", "Mc"), starts, (self.shas[1], self.shas[3], self.shas[4])), 1):
            with self.subTest(part=key):
                chunk = self.pr(key)["chunk"]
                self.assertEqual((chunk["of"], chunk["index"], chunk["count"], chunk["from"], chunk["to"]), ("M", index, 3, start, end))
                self.assertEqual(self.pr(key)["tip"], end[:len(self.pr(key)["tip"])])
        self.assertEqual((self.pr("Mb")["chunk"]["commits"], self.pr("Mb")["chunk"]["subjects"], self.pr("Mb")["chunk"]["label"]),
                         (2, ["feat(web): page", "test(web): page spec"], "web"))
        self.assertEqual([pr["name"] for pr in self.graph["prs"]], ["#9 1/3 core", "#9 2/3 web", "#9 3/3 core"])
        parent = self.graph["parents"][0]
        self.assertEqual({k: parent[k] for k in ("key", "name", "parts")}, {"key": "M", "name": "#9", "parts": ["Ma", "Mb", "Mc"]})
        self.assertEqual((parent["base"], parent["tip"]), (self.pr("Ma")["base"], self.pr("Mc")["tip"]))
        record = json.loads((self.scratch / "review-map.json").read_text(encoding="utf-8"))
        self.assertEqual(record["build_graph"]["chunks"], [{"path": "chunks.json", "parent": "M", "tip": self.shas[4]}])
        self.assertEqual(record["build_graph"]["prs"], [])
        self.assertEqual(record["gen_diffs"]["chunks"], ["chunks.json"])
        placed = self.root / "placed.json"
        run_script("build_graph.py", "--out", str(placed), "--pr", "M", str(self.repo), "main...feat", "--chunks", str(self.scratch / "chunks.json"),
                   "--overlay", str(self.scratch / "overlay.json"), "--no-manifest")
        self.assertEqual(json.loads(placed.read_text(encoding="utf-8")), self.graph)
        wrong = run_script("build_graph.py", "--out", str(placed), "--pr", "M", str(self.repo), "main..feat", "--chunks",
                           str(self.scratch / "chunks.json"), "--no-manifest", check=False)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("names another repository or range", wrong.stderr)
        big = self.root / "big"
        big.mkdir()
        git(big, "init", "-q", "-b", "main")
        commit_files(big, {"README.md": "# x\n"}, "base")
        git(big, "checkout", "-q", "-b", "feat")
        commit_files(big, {f"src/f{i:03}.ts": f"export const f{i} = {i};\n" for i in range(101)}, "feat: many")
        hint = run_script("build_graph.py", "--out", str(self.root / "big.json"), "--pr", "B", str(big), "main...feat", "--no-manifest").stdout
        self.assertIn("hint: PR B changes 101 files in 101 nodes", hint)
        self.assertNotIn("hint:", self.build)

    def test_a_file_in_two_parts_is_one_node_per_part_with_its_own_slice(self):
        """This test will fail when a file that two parts change is not one node in each part with that part's own diff and fingerprint, or when the last part's entry loses the file's diff over the whole PR (or a file in one part gets one)."""
        first, last = self.node("Ma", "src/core/service.ts"), self.node("Mc", "src/core/service.ts")
        (a,), (c,) = self.diffs[first["id"]], self.diffs[last["id"]]
        self.assertIn("+export const one = (): T => 1;", a["diff"])
        self.assertIn("-export const one = (): T => 1;\n+export const one = (): T => 2;", c["diff"])
        self.assertNotEqual(a["fp"], c["fp"])
        self.assertNotIn("whole", a)
        self.assertIn("+export const one = (): T => 2;", c["whole"]["diff"])
        self.assertNotIn("-export const one", c["whole"]["diff"])
        self.assertTrue(all("whole" not in e for entries in self.diffs.values() for e in entries if e["path"] != "src/core/service.ts"))

    def test_cross_part_edges_are_external_and_parent_overlay_references_reach_every_part(self):
        """This test will fail when an import into an earlier part is not an external cross-part edge, a parent-key overlay node does not reach every part's node of that path (or a part key reaches more than its part), a parent-key edge does not start at the last part changing its file and end at the latest part up to it, an edge with no such target is not skipped with a warning, or a parent-key dropEdges misses a part."""
        ids = {n["id"]: (pr["key"], n["path"]) for pr in self.graph["prs"] for n in pr["nodes"]}

        def edges(key):
            return {(ids[e["from"]][1], ids[e["to"]], e["kind"], e["external"]) for e in self.pr(key)["edges"]}

        self.assertIn(("web/page.tsx", ("Ma", "src/core/service.ts"), "import", True), edges("Mb"))
        self.assertIn(("web/page.tsx", ("Ma", "src/core/types.ts"), "config", True), edges("Mb"))
        self.assertIn(("src/core/service.ts", ("Mb", "web/page.spec.tsx"), "config", True), edges("Mc"))
        self.assertIn(("src/core/service.ts", ("Ma", "src/core/types.ts"), "import", True), edges("Mc"))
        self.assertEqual((self.node("Ma", "src/core/service.ts")["role"], self.node("Mc", "src/core/service.ts")["role"]), ("Service", "Service"))
        self.assertEqual(self.node("Mb", "web/page.tsx")["note"], "Only in part 2.")
        self.assertIn("is in no part up to the one M:src/core/types.ts is in; skipped", self.build)
        self.assertEqual(self.graph["crossEdges"], [{"from": e["from"], "to": e["to"], "kind": e["kind"]}
                                                    for pr in self.graph["prs"] for e in pr["edges"] if e["external"]])
        overlay = self.root / "drop.json"
        overlay.write_text(json.dumps({"dropEdges": [{"from": "M:src/core/service.ts", "to": "M:src/core/types.ts"}]}), encoding="utf-8")
        dropped = self.root / "dropped.json"
        run_script("build_graph.py", "--out", str(dropped), "--chunks", str(self.scratch / "chunks.json"), "--overlay", str(overlay), "--no-manifest")
        graph = json.loads(dropped.read_text(encoding="utf-8"))
        by_id = {n["id"]: n["path"] for pr in graph["prs"] for n in pr["nodes"]}
        self.assertFalse([e for pr in graph["prs"] for e in pr["edges"] if (by_id[e["from"]], by_id[e["to"]]) == ("src/core/service.ts", "src/core/types.ts")])

    def test_areas_given_with_the_parent_key_reach_every_part_and_each_part_lists_its_own(self):
        """This test will fail when an overlay area given with the PR's key (M:path) does not reach that file's node in every part that changes it, an area given with a part key reaches another part, or a part lists an area none of its nodes use."""
        overlay = self.root / "areas-overlay.json"
        overlay.write_text(json.dumps({"clusters": {"core": {"label": "Core"}, "web": {"label": "Web", "order": 0}},
                                       "nodes": {"M:src/core/service.ts": {"cluster": "core"}, "M:src/core/types.ts": {"cluster": "core"},
                                                 "Mb:web/page.tsx": {"cluster": "web"}}}), encoding="utf-8")
        out = self.root / "areas-graph.json"
        run_script("build_graph.py", "--out", str(out), "--chunks", str(self.scratch / "chunks.json"), "--overlay", str(overlay), "--no-manifest")
        parts = {pr["key"]: pr for pr in json.loads(out.read_text(encoding="utf-8"))["prs"]}

        def area(key, path):
            return next(n for n in parts[key]["nodes"] if n["path"] == path).get("cluster")

        self.assertEqual([area("Ma", "src/core/service.ts"), area("Mc", "src/core/service.ts"), area("Ma", "src/core/types.ts")], ["core"] * 3)
        self.assertEqual((area("Mb", "web/page.tsx"), area("Mb", "web/page.spec.tsx"), area("Ma", "src/core/util.ts")), ("web", None, None))
        self.assertEqual({key: pr.get("clusters") for key, pr in parts.items()},
                         {"Ma": [{"id": "core", "label": "Core", "order": 1}], "Mb": [{"id": "web", "label": "Web", "order": 0}],
                          "Mc": [{"id": "core", "label": "Core", "order": 1}]})

    def test_broken_chunks_and_part_chains_are_rejected(self):
        """This test will fail when a chunks file with parts out of order, a part key that ends in a digit or repeats, or a parent key that is also a PR key is accepted, or when assemble.py or validate.py accept graphs.json parts whose chain is broken (a part that does not start where the one before ends, a wrong index, a parent that lists other parts)."""
        good = self.chunks

        def chunks_with(change):
            data = json.loads(json.dumps(good))
            change(data)
            path = self.root / "bad-chunks.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return path

        for name, change, args, message in (
            ("out of order", lambda d: d["parts"].reverse(), [], "does not come after"),
            ("digit key", lambda d: d["parts"][0].update(key="M1"), [], "end in a letter"),
            ("repeated key", lambda d: d["parts"][1].update(key="Ma"), [], "used twice"),
            ("short sha", lambda d: d["parts"][0].update(to="abc"), [], "commit SHA"),
            ("parent is a pr", lambda d: None, ["--pr", "Mb", str(self.repo), "main...feat"], "unique"),
        ):
            with self.subTest(case=name):
                result = run_script("build_graph.py", "--out", str(self.root / "never.json"), "--chunks", str(chunks_with(change)), *args,
                                    "--no-manifest", check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stderr)
        narrative = self.root / "narrative.html"
        narrative.write_text('<section id="s"><h2>S</h2><div class="pr-card c-M">x</div></section>\n<!-- review-map:graph -->\n', encoding="utf-8")
        page = self.root / "chunked.html"
        run_script("assemble.py", "--graph", str(self.scratch / "graphs.json"), "--diffs", str(self.scratch / "diffs.json"), "--narrative", str(narrative),
                   "--title", "Parts", "--out", str(page), "--no-manifest")
        self.assertIn(".c-M{--c:var(--pal-1)}", page.read_text(encoding="utf-8"))
        if NODE:
            self.assertEqual(run_script("validate.py", str(page), check=False).returncode, 0)
        text = page.read_text(encoding="utf-8")
        for name, change, message in (
            ("chain", lambda g: g["prs"][2]["chunk"].update({"from": g["prs"][0]["chunk"]["to"]}), "not where part Mb ends"),
            ("index", lambda g: g["prs"][1]["chunk"].update(index=3), "index/count"),
            ("parent parts", lambda g: g["parents"][0].update(parts=["Ma", "Mc"]), "are not its part PRs"),
            ("orphan", lambda g: g["prs"][0]["chunk"].update(of="X"), "chunk names no parent"),
        ):
            with self.subTest(case=name):
                graph = json.loads(json.dumps(self.graph))
                change(graph)
                broken = self.root / "broken-graph.json"
                broken.write_text(json.dumps(graph), encoding="utf-8")
                result = run_script("assemble.py", "--graph", str(broken), "--diffs", str(self.scratch / "diffs.json"), "--narrative", str(narrative),
                                    "--title", "Parts", "--out", str(self.root / "never.html"), "--no-manifest", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                bad = self.root / "broken-page.html"
                bad.write_text(re.sub(r'(<script type="application/json" id="graph-data">).*?(</script>)',
                                      lambda m: m.group(1) + json.dumps(graph).replace("</", "<\\/") + m.group(2), text, flags=re.DOTALL), encoding="utf-8")
                checked = run_script("validate.py", str(bad), "--skip-node", check=False)
                self.assertEqual(checked.returncode, 1, checked.stdout)
                self.assertIn(message, checked.stdout)

    @unittest.skipUnless(NODE, "node is required to run the viewer's note migration")
    def test_notes_from_a_whole_pr_map_move_to_their_parts(self):
        """This test will fail when the viewer stops moving a note written on the whole PR's map (stored under the parent's key) to the part that holds its code: a new-side line note to the last part changing its file, or to the latest part that still shows its code at its lines, or at other lines (taking them); an old-side note likewise from the first part; a file note to the last part. Or when it moves a PR note, a note on a file no part changes, or a note already on a part, or moves anything on a page without parents."""
        lines = ["const a = 1;", "const b = 2;", "const c = 3;", "const d = 4;", "const e = 5;", "const f = 6;"]
        base_g = [f"export const g{i} = {i};" for i in range(1, 13)]
        diffs = {
            "Ma1": [{"path": "f.ts", "diff": added(lines).replace("+++ b/f", "+++ b/f.ts")}],
            "Mb1": [{"path": "g.ts", "diff": "--- a/g.ts\n+++ b/g.ts\n@@ -1,3 +1,3 @@\n export const g1 = 1;\n-export const g2 = 2;\n+export const g2 = 20;\n export const g3 = 3;"}],
            "Mc1": [{"path": "f.ts", "diff": "--- a/f.ts\n+++ b/f.ts\n@@ -1,0 +1,2 @@\n+// x\n+// y"}],
            "Mc2": [{"path": "g.ts", "diff": "--- a/g.ts\n+++ b/g.ts\n@@ -9,3 +9,2 @@\n export const g9 = 9;\n-export const g10 = 10;\n export const g11 = 11;"}],
        }
        graph = {"prs": [{"key": k, "chunk": {"of": "M", "index": i, "count": 3}, "nodes": [{"id": n, "path": diffs[n][0]["path"]} for n in diffs if n.startswith(k)], "edges": []}
                         for i, k in enumerate(("Ma", "Mb", "Mc"), 1)],
                 "parents": [{"key": "M", "name": "#9", "parts": ["Ma", "Mb", "Mc"]}]}

        def line(path, side, a, code, pr="M"):
            return {"id": f"{path}{side}{a}", "scope": "line", "pr": pr, "path": path, "side": side, "a": a, "b": a, "code": [code]}

        notes = [
            line("f.ts", "new", 1, "// x"),          # shown by the last part: it goes there
            line("f.ts", "new", 5, "const c = 3;"),   # the last part does not show it; part 1 has it at line 3
            line("g.ts", "old", 2, base_g[1]),        # old side, shown by the first part changing g.ts
            line("g.ts", "old", 10, base_g[9]),       # old side, only the last part shows it
            line("f.ts", "new", 2, "gone code"),      # nowhere: the last part changing the file
            {"id": "file", "scope": "file", "pr": "M", "path": "g.ts"},
            {"id": "pr", "scope": "pr", "pr": "M"},
            line("h.ts", "new", 1, "x"),              # no part changes h.ts
            line("f.ts", "new", 1, "// x", pr="Mb"),  # already on a part
        ]
        script = self.root / "chunk-home.js"
        script.write_text(CHUNK_HOME, encoding="utf-8")
        inputs = self.root / "chunk-home.json"
        inputs.write_text(json.dumps({"graph": graph, "diffs": diffs, "notes": notes}), encoding="utf-8")
        result = subprocess.run(["node", str(script), str(SKILL / "assets" / "viewer.html"), str(inputs)], capture_output=True, text=True, check=True)
        homes = json.loads(result.stdout)
        self.assertEqual(homes["parts"], [
            {"pr": "Mc", "node": "Mc1"}, {"pr": "Ma", "node": "Ma1", "a": 3, "b": 3}, {"pr": "Mb", "node": "Mb1"},
            {"pr": "Mc", "node": "Mc2"}, {"pr": "Mc", "node": "Mc1"}, {"pr": "Mc", "node": "Mc2"}, None, None, None,
        ])
        self.assertEqual(homes["plain"], [None] * len(notes))


class ChunkRefreshTests(unittest.TestCase):
    """A map split into parts, refreshed after its branch gained commits, was rebased, or was rewritten past mapping."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        repo, d = cls.root / "repo", cls.root / "scratch"
        cls.shas = chunk_repo(repo)
        d.mkdir()
        run_script("chunks.py", "propose", "--repo", str(repo), "--range", "main...feat", "--key", "M", "--name", "#9",
                   "--out", str(d / "chunks.json"), "--min-files", "1")
        (d / "overlay.json").write_text(json.dumps({"nodes": {"M:src/core/service.ts": {"role": "Service"}}}), encoding="utf-8")
        run_script("build_graph.py", "--out", str(d / "graphs.json"), "--chunks", str(d / "chunks.json"), "--overlay", str(d / "overlay.json"))
        run_script("gen_diffs.py", "--graph", str(d / "graphs.json"), "--out", str(d / "diffs.json"), "--chunks", str(d / "chunks.json"), "--strict")
        (d / "narrative.html").write_text(
            '<section id="stack"><h2>Stack</h2><div class="pr-card c-M"><span class="meta">tip <code>%s</code></span>\n'
            '<ol class="parts"><li><button type="button" class="tag c-Ma" data-gopen="Ma">1/3</button><code>%s..%s</code></li></ol></div></section>\n'
            "<!-- review-map:graph -->\n<footer>x</footer>\n" % (cls.shas[4][:7], cls.shas[0][:7], cls.shas[1][:7]), encoding="utf-8")
        run_script("assemble.py", "--graph", str(d / "graphs.json"), "--diffs", str(d / "diffs.json"), "--narrative", str(d / "narrative.html"),
                   "--title", "Parts", "--lang", "pl", "--target", "local", "--out", str(d / "review.html"))
        cls.repo, cls.scratch = repo, d

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def copy(self, name: str) -> tuple[Path, Path]:
        """A copy of the repository and the scratch directory whose manifest and chunks.json point at the copy."""
        repo, d = self.root / f"{name}-repo", self.root / f"{name}-scratch"
        shutil.copytree(self.repo, repo)
        shutil.copytree(self.scratch, d)
        chunks = json.loads((d / "chunks.json").read_text(encoding="utf-8"))
        chunks["parent"]["repo"] = str(repo.resolve())
        (d / "chunks.json").write_text(json.dumps(chunks, indent=1), encoding="utf-8")
        return repo, d

    def parts(self, d: Path) -> list[dict]:
        return json.loads((d / "chunks.json").read_text(encoding="utf-8"))["parts"]

    @unittest.skipUnless(NODE, "node is required to validate the refreshed page")
    def test_new_commits_become_a_new_part_and_earlier_parts_stay(self):
        """This test will fail when refresh.py does not turn commits after the last part into a new part labelled in the page's language, changes an earlier part's range or fingerprints (which would clear its read marks), forgets to record the new tip, misses the narrative's missing part, or writes to the repository."""
        repo, d = self.copy("append")
        before = self.parts(d)
        old = {e["path"] + "@" + k: e["fp"] for k, entries in json.loads((d / "diffs.json").read_text(encoding="utf-8")).items() for e in entries}
        commit_files(repo, {"web/extra.ts": "export const extra = 1;\n"}, "feat(web): extra")
        tip = git(repo, "rev-parse", "feat").strip()
        refs = git(repo, "for-each-ref"), git(repo, "status", "--porcelain")
        out = run_script("refresh.py", str(d)).stdout
        self.assertEqual(self.parts(d), before + [{"key": "Md", "to": tip, "label": "nowe od ostatniej wersji"}])
        self.assertIn(f"1 commit(s) after part Mc became the new part Md ({self.shas[4][:7]}..{tip[:7]})", out)
        self.assertIn(f"PR M: the new part Md (to {tip[:7]}) is not in the narrative; add it to the parts card", out)
        self.assertIn("changed since the previous version: 1 files (1 new, 0 changed, 0 removed)", out)
        graph = json.loads((d / "graphs.json").read_text(encoding="utf-8"))
        self.assertEqual([pr["key"] for pr in graph["prs"]], ["Ma", "Mb", "Mc", "Md"])
        new = {e["path"] + "@" + k: e["fp"] for k, entries in json.loads((d / "diffs.json").read_text(encoding="utf-8")).items() for e in entries}
        self.assertEqual({k: v for k, v in new.items() if not k.endswith("@Md1")}, old)
        self.assertEqual(json.loads((d / "previous.json").read_text(encoding="utf-8"))["files"].keys(), {"Ma", "Mb", "Mc"})
        self.assertEqual(json.loads((d / "review-map.json").read_text(encoding="utf-8"))["build_graph"]["chunks"],
                         [{"path": "chunks.json", "parent": "M", "tip": tip}])
        self.assertEqual((git(repo, "for-each-ref"), git(repo, "status", "--porcelain")), refs)
        self.assertFalse(list(d.glob("*.new")))

    @unittest.skipUnless(NODE, "node is required to validate the refreshed page")
    def test_a_rebase_remaps_every_part_by_patch_id_or_subject(self):
        """This test will fail when refresh.py, after the branch was rebased onto a moved base, does not map each part's end to the rewritten commit with the same patch-id (or subject), keeps a key or label from carrying over, adds a part nobody asked for, or does not name the narrative lines that still show a part's old end."""
        repo, d = self.copy("rebase")
        before = self.parts(d)
        git(repo, "checkout", "-q", "main")
        commit_files(repo, {"base.txt": "base moved\n"}, "chore: base moves")
        git(repo, "rebase", "-q", "main", "feat")
        out = run_script("refresh.py", str(d)).stdout
        after = self.parts(d)
        self.assertEqual([(p["key"], p["label"]) for p in after], [(p["key"], p["label"]) for p in before])
        subject = lambda sha: git(repo, "log", "-1", "--format=%s", sha).strip()  # noqa: E731
        self.assertEqual([subject(p["to"]) for p in after], [subject(p["to"]) for p in before])
        self.assertTrue(all(a["to"] != b["to"] for a, b in zip(after, before)))
        self.assertEqual(after[-1]["to"], git(repo, "rev-parse", "feat").strip())
        self.assertIn("the history was rewritten; 3 of 3 part ends remapped", out)
        self.assertIn(f"part Ma now ends at {after[0]['to'][:7]}, not {before[0]['to'][:7]}; the narrative still shows {before[0]['to'][:7]} at narrative.html:2", out)
        self.assertIn("changed since the previous version: 0 files", out)

    def test_a_history_it_cannot_map_stops_the_refresh_before_anything_changes(self):
        """This test will fail when refresh.py rebuilds a map whose part ends no longer exist on the rewritten branch (the commit was dropped or reworded and changed) instead of stopping with a request to propose the parts again, or when it touches chunks.json, the data, or the page on the way."""
        repo, d = self.copy("rewrite")
        git(repo, "reset", "-q", "--hard", self.shas[2])
        commit_files(repo, {"web/page.spec.tsx": "test('another', () => 1);\n"}, "test(web): rewritten spec")
        files = {name: (d / name).read_bytes() for name in ("chunks.json", "graphs.json", "diffs.json", "review.html", "review-map.json")}
        result = run_script("refresh.py", str(d), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("part Mb (ending at", result.stderr)
        self.assertIn("re-run chunks.py propose for main...feat", result.stderr)
        self.assertEqual({name: (d / name).read_bytes() for name in files}, files)
        self.assertFalse(list(d.glob("*.new")))


if __name__ == "__main__":
    unittest.main()
