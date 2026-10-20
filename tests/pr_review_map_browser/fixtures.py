"""Build the synthetic review pages the pr-review-map browser checks open.

Every fixture comes from a small git repository written here with fixed authors and
dates, run through the skill's own scripts (build_graph.py, gen_diffs.py,
assemble.py, validate.py, refresh.py) exactly as the skill runs them, so the SHAs and
the pages are the same on every run and nothing outside the output directory is read
or written.

Usage:
  fixtures.py build OUT              all static fixtures, one directory each, under OUT
  fixtures.py demo-v1 DIR            the refresh demo at v1: DIR/repo and DIR/scratch/review.html
  fixtures.py demo-move DIR          move the demo branches the way a fix round does
  fixtures.py demo-rebuild DIR [OUT] rebuild the demo page by hand (no refresh.py) into OUT (default DIR/scratch)

`build` prints one JSON line naming each fixture page; the demo commands print the
tips they leave ({"A": sha, "B": sha}, short SHAs).
"""

from __future__ import annotations

import html
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "pr-review-map" / "scripts"
ENV = {
    **os.environ,
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2026-10-01T10:00:00Z",
    "GIT_COMMITTER_DATE": "2026-10-01T10:00:00Z",
}
NARRATIVE = (
    '<header><h1>{title}</h1><p class="sub">Sample.</p></header>\n<!-- review-map:graph -->\n'
    '<section id="pr-x"><h2>Per PR</h2><p><button type="button" class="tag" data-gopen="{key}"></button></p></section>\n'
)


def run(*args: object, cwd: Path | None = None, env: dict | None = None) -> str:
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env or ENV, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"{' '.join(map(str, args))} failed:\n{result.stdout}{result.stderr}")
    return result.stdout


def script(name: str, *args: object, cwd: Path | None = None, env: dict | None = None) -> str:
    return run(sys.executable, SCRIPTS / name, *args, cwd=cwd, env=env)


def git(repo: Path, *args: object, env: dict | None = None) -> str:
    return run("git", "-C", repo, *args, env=env)


def write(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def commit(repo: Path, files: dict[str, str], message: str) -> None:
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def new_repo(path: Path) -> Path:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    return path


def validate(page: Path, *, rejects: tuple[str, ...] = ()) -> None:
    """validate.py must pass `page`; with `rejects` it must instead fail with exactly those errors (a substring each, in order)."""
    result = subprocess.run([sys.executable, str(SCRIPTS / "validate.py"), str(page)], env=ENV, capture_output=True, text=True)
    out = result.stdout.strip().splitlines()
    if rejects:
        errors = [line for line in out if line.startswith("error:")]
        ok = result.returncode != 0 and len(errors) == len(rejects) and all(r in e for r, e in zip(rejects, errors))
    else:
        ok = result.returncode == 0 and bool(out) and "OK" in out[-1]
    if not ok:
        raise SystemExit(f"validate.py {page}:\n" + "\n".join(out) + result.stderr)


def page(
    d: Path, repo: Path, prs: list[tuple[str, str, str]], title: str, *, lang: str = "en", overlay: Path | None = None,
    extra: tuple = (), narrative: str | None = None,
) -> Path:
    """graphs.json, diffs.json, narrative.html, and review.html in `d` for `prs` [(key, range, name)]."""
    graph, diffs, narr, out = d / "graphs.json", d / "diffs.json", d / "narrative.html", d / "review.html"
    args: list[object] = ["--out", graph]
    for key, rng, name in prs:
        args += ["--pr", key, repo, rng, "--name", key, name]
    if overlay:
        args += ["--overlay", overlay]
    script("build_graph.py", *args, *extra, "--no-manifest")
    args = ["--graph", graph, "--out", diffs]
    for key, rng, _ in prs:
        args += ["--pr", key, repo, rng]
    script("gen_diffs.py", *args, "--strict", "--no-manifest")
    narr.write_text(narrative or NARRATIVE.format(title=title, key=prs[-1][0]), encoding="utf-8")
    assemble(graph, diffs, narr, title, out, lang=lang)
    return out


def assemble(graph: Path, diffs: Path, narr: Path, title: str, out: Path, *, lang: str = "en", previous: Path | None = None,
             rejects: tuple[str, ...] = ()) -> None:
    script("assemble.py", "--graph", graph, "--diffs", diffs, "--narrative", narr, "--title", title, "--lang", lang,
           "--target", "local", "--out", out, "--no-manifest", *(["--previous", previous] if previous else []))
    validate(out, rejects=rejects)


# ---------------------------------------------------------------------------------------------------------------------
# stack: three stacked PRs (A, B, C) with cross-PR links, overlay edges, tests, docs, config, and translations.


def stack(d: Path) -> dict:
    repo = new_repo(d / "repo")
    commit(repo, {"README.md": "# x\n", "src/legacy.ts": "export const legacy = 1;\n"}, "base")
    git(repo, "checkout", "-q", "-b", "feat/a")
    commit(repo, {
        "src/contracts/item.schema.ts": "export type Item = { id: number; name: string };\n",
        "src/domain/item.ts": "import type { Item } from '../contracts/item.schema';\nexport const make = (id: number): Item => ({ id, name: 'x' });\n",
        "src/logic/item.service.ts": "import { make } from '../domain/item';\nimport type { Item } from '../contracts/item.schema';\n"
                                     "export const list = (): Item[] => [make(1), make(2)];\n" + "".join(f"// line {i}\n" for i in range(30)),
        "src/logic/item.service.spec.ts": "import { list } from './item.service';\ntest('list', () => expect(list()).toHaveLength(2));\n",
        "docs/items.md": "# Items\n\nHow items work.\n",
    }, "A")
    git(repo, "checkout", "-q", "-b", "feat/b")
    commit(repo, {
        "src/rest/item.controller.ts": "import { list } from '../logic/item.service';\nimport type { Item } from '../contracts/item.schema';\n"
                                       "export const get = (): Item[] => list();\n",
        "src/rest/item.controller.spec.ts": "import { get } from './item.controller';\ntest('get', () => expect(get()).toBeTruthy());\n",
        "src/rest/routes.ts": "import { get } from './item.controller';\nexport const routes = { '/items': get };\n",
        "config/app.yaml": "items:\n  page: 20\n",
    }, "B")
    git(repo, "checkout", "-q", "-b", "feat/c")
    commit(repo, {
        "web/ui/ItemList.tsx": "import type { Item } from '../../src/contracts/item.schema';\nimport { useItems } from './useItems';\n"
                               "export const ItemList = () => useItems().map((i: Item) => i.name);\n",
        "web/ui/useItems.ts": "export const useItems = () => fetch('/items').then((r) => r.json());\n",
        "web/ui/ItemList.test.tsx": "import { ItemList } from './ItemList';\ntest('renders', () => expect(ItemList).toBeTruthy());\n",
        "web/locales/en.json": '{"items": "Items"}\n',
    }, "C")
    overlay = d / "overlay.json"
    overlay.write_text(json.dumps({
        "nodes": {"A:src/logic/item.service.ts": {"role": "Lists items", "note": "Builds two <code>Item</code>s."},
                  "B:src/rest/item.controller.ts": {"role": "GET /items"},
                  "C:web/ui/useItems.ts": {"role": "Fetches /items"}},
        "edges": [{"from": "C:web/ui/useItems.ts", "to": "B:src/rest/item.controller.ts", "kind": "http"},
                  {"from": "B:src/rest/item.controller.ts", "to": "B:config/app.yaml", "kind": "config"}],
    }), encoding="utf-8")
    prs = [("A", "main...feat/a", "A #101"), ("B", "feat/a...feat/b", "B #102"), ("C", "feat/b...feat/c", "C #103")]
    out = page(d, repo, prs, "Stack sample", overlay=overlay)
    # The same report rebuilt with PR A's node ids reversed (A1 <-> A5, A2 <-> A4): read marks must follow the files.
    graph = json.loads((d / "graphs.json").read_text(encoding="utf-8"))
    ids = [n["id"] for n in graph["prs"][0]["nodes"]]
    swap = dict(zip(ids, reversed(ids)))

    def rename(value: str) -> str:
        return swap.get(value, value)

    for pr in graph["prs"]:
        for node in pr["nodes"]:
            node["id"] = rename(node["id"])
        for edge in pr["edges"]:
            edge["from"], edge["to"] = rename(edge["from"]), rename(edge["to"])
    for edge in graph.get("crossEdges", []):
        edge["from"], edge["to"] = rename(edge["from"]), rename(edge["to"])
    diffs = json.loads((d / "diffs.json").read_text(encoding="utf-8"))
    (d / "graphs-renumbered.json").write_text(json.dumps(graph), encoding="utf-8")
    (d / "diffs-renumbered.json").write_text(json.dumps({rename(k): v for k, v in diffs.items()}), encoding="utf-8")
    renumbered = d / "review-renumbered.html"
    assemble(d / "graphs-renumbered.json", d / "diffs-renumbered.json", d / "narrative.html", "Stack sample", renumbered)
    return {"page": str(out), "renumbered": str(renumbered)}


# ---------------------------------------------------------------------------------------------------------------------
# big: one PR of 103 files across twelve features (lane thinning, grouping a long list).


def big(d: Path) -> dict:
    repo = new_repo(d / "repo")
    commit(repo, {"README.md": "# big\n"}, "base")
    git(repo, "checkout", "-q", "-b", "feat/big")
    rnd = random.Random(7)
    feats = ["billing", "booking", "catalog", "clinic", "doctor", "invoice", "patient", "payment", "price", "schedule", "slot", "visit"]
    files = {
        "src/shared/types.ts": "export type Id = string;\n",
        "src/shared/db.ts": "import type { Id } from './types';\nexport const db = { get: (id: Id) => id };\n",
        "src/shared/logger.ts": "export const log = (m: string) => m;\n",
        "src/shared/errors.ts": "import { log } from './logger';\nexport class AppError extends Error { constructor(m: string) { super(log(m)); } }\n",
    }
    ui = set(rnd.sample(feats, 8))
    for i, f in enumerate(feats):
        F = f.capitalize()
        files[f"src/contracts/{f}.schema.ts"] = f"import type {{ Id }} from '../shared/types';\nexport type {F} = {{ id: Id }};\n"
        files[f"src/domain/{f}.entity.ts"] = f"import type {{ {F} }} from '../contracts/{f}.schema';\nexport const {f}Entity = (x: {F}) => x;\n"
        files[f"src/infra/{f}.repository.ts"] = (f"import {{ db }} from '../shared/db';\nimport {{ {f}Entity }} from '../domain/{f}.entity';\n"
                                                 f"export const {f}Repo = {{ find: (id: string) => {f}Entity({{ id: db.get(id) }}) }};\n")
        extra = ""
        if i % 3 != 0:
            other = feats[rnd.randrange(len(feats))]
            if other != f:
                extra = f"import {{ {other}Service }} from './{other}.service';\n"
        if i % 4 == 1:
            extra += "import { AppError } from '../shared/errors';\n"
        files[f"src/logic/{f}.service.ts"] = (f"import {{ {f}Repo }} from '../infra/{f}.repository';\n{extra}"
                                              f"export const {f}Service = {{ get: (id: string) => {f}Repo.find(id) }};\n")
        files[f"src/rest/{f}.controller.ts"] = (f"import {{ {f}Service }} from '../logic/{f}.service';\n"
                                                f"import type {{ {F} }} from '../contracts/{f}.schema';\n"
                                                f"export const {f}Controller = (id: string): {F} => {f}Service.get(id);\n")
        files[f"src/logic/{f}.service.spec.ts"] = f"import {{ {f}Service }} from './{f}.service';\ntest('x', () => expect({f}Service).toBeTruthy());\n"
        files[f"src/rest/{f}.controller.spec.ts"] = (f"import {{ {f}Controller }} from './{f}.controller';\n"
                                                     f"test('x', () => expect({f}Controller).toBeTruthy());\n")
        if f in ui:
            files[f"web/{F}Panel.tsx"] = f"import type {{ {F} }} from '../src/contracts/{f}.schema';\nexport const {F}Panel = (x: {F}) => x.id;\n"
    files["src/app.ts"] = "".join(f"import {{ {f}Controller }} from './rest/{f}.controller';\n" for f in feats) + "export const app = 1;\n"
    files["src/routes.ts"] = "".join(f"import {{ {f}Controller }} from './rest/{f}.controller';\n" for f in feats[:6]) + "export const routes = 1;\n"
    files.update({
        "scripts/migrate.ts": "export const migrate = () => 1;\n", "tools/codegen.ts": "export const codegen = () => 1;\n",
        "docs/arch.md": "# arch\n", "docs/flows.md": "# flows\n", "package.json": '{"name": "big"}\n',
        "locales/en.json": '{"a": "b"}\n', "locales/pl.json": '{"a": "b"}\n',
    })
    commit(repo, files, "big")
    return {"page": str(page(d, repo, [("P", "main...feat/big", "P #900")], "Big sample", extra=("--alias", "@big/=src/")))}


# ---------------------------------------------------------------------------------------------------------------------
# hub: one Polish-language PR of about 45 files shaped around three shared dependencies (an i18n package's index, the
# app's error texts that wrap it, and a locale helper only those two use), with folders enough for "Group by folder",
# tests, config, docs, and three long translation catalogs in one node (the tallest diff, for the sticky list).

HUB_I18N = "@acme/i18n"


def _ts_module(imports: list[tuple[str, str]], body: list[str]) -> str:
    return "".join(f"import {{ {names} }} from '{source}';\n" for names, source in imports) + "\n" + "\n".join(body) + "\n"


def _catalog(lang: str) -> str:
    keys = [f"settings.{state}.{i}" for i in range(80) for state in ("on", "off")]
    return "{\n" + ",\n".join(f'  "{k}": "{lang}:{k}"' for k in keys) + "\n}\n"


def hub(d: Path) -> dict:
    repo = new_repo(d / "repo")
    commit(repo, {"README.md": "# acme\n", "package.json": '{"name": "acme", "private": true}\n',
                  "apps/mobile/src/app/App.tsx": "export const App = () => null;\n"}, "base")
    git(repo, "checkout", "-q", "-b", "feat/sign-in")
    i18n = HUB_I18N
    m = "apps/mobile/src"
    screens = ["Login", "Settings", "Profile", "Home", "Welcome"]
    files: dict[str, str] = {
        # The i18n package: the index (a hub) and its locale helper (only hubs use it, so it joins them).
        "packages/i18n/src/locale.ts": _ts_module([], [
            "export type Locale = 'pl' | 'en';", "export const FALLBACK: Locale = 'en';",
            "export function pickLocale(tags: readonly string[]): Locale {",
            "  for (const tag of tags) {", "    const base = tag.toLowerCase().split('-')[0];",
            "    if (base === 'pl' || base === 'en') return base;", "  }", "  return FALLBACK;", "}"]),
        "packages/i18n/src/index.ts": _ts_module([("pickLocale, type Locale", "./locale")], [
            "const catalogs: Record<Locale, Record<string, string>> = { pl: {}, en: {} };",
            "let current: Locale = pickLocale([]);",
            "export function setLocale(tags: readonly string[]): void {", "  current = pickLocale(tags);", "}",
            "export function t(key: string, params: Record<string, string> = {}): string {",
            "  const text = catalogs[current][key] ?? key;",
            "  return text.replace(/\\{(\\w+)\\}/g, (_, name: string) => params[name] ?? '');", "}"]),
        "packages/i18n/src/index.spec.ts": _ts_module([("t, setLocale", "./index")], [
            "test('falls back to the key', () => {", "  setLocale(['pl-PL']);", "  expect(t('missing')).toBe('missing');", "});"]),
        # Three catalogs, one node: the tallest diff of the PR (each file's diff scrolls inside 70vh), for the sticky list.
        **{f"packages/i18n/locales/{lang}.json": _catalog(lang) for lang in ("de", "en", "pl")},
        # The app's error texts (hub): wraps the i18n index for every screen and flow.
        f"{m}/i18n/error-text.ts": _ts_module([("t", i18n), ("pickLocale", "../../../../packages/i18n/src/locale")], [
            "export type Failure = 'network' | 'cancelled' | 'denied' | 'unknown';",
            "export function errorText(failure: Failure): string {",
            "  return t(`auth.${failure}`, { locale: pickLocale([]) });", "}"]),
        f"{m}/i18n/error-text.spec.ts": _ts_module([("errorText", "./error-text")], [
            "test('names the failure', () => {", "  expect(errorText('network')).toContain('network');", "});"]),
        # Sign-in flow.
        f"{m}/auth/token-store.ts": _ts_module([], [
            "const memory = new Map<string, string>();", "export function saveToken(token: string): void {",
            "  memory.set('token', token);", "}", "export function readToken(): string | undefined {", "  return memory.get('token');", "}"]),
        f"{m}/auth/token-store.spec.ts": _ts_module([("saveToken, readToken", "./token-store")], [
            "test('keeps the token', () => {", "  saveToken('x');", "  expect(readToken()).toBe('x');", "});"]),
        f"{m}/auth/oauth-session.ts": _ts_module([("t", i18n), ("errorText", "../i18n/error-text"), ("saveToken", "./token-store"),
                                                 ("request", "../../../../packages/api-client/src/http")], [
            "export type SessionResult = { ok: true } | { ok: false; message: string };",
            "export async function startSession(code: string): Promise<SessionResult> {",
            "  const res = await request('/oauth/token', { code });",
            "  if (!res.ok) return { ok: false, message: errorText('denied') };",
            "  saveToken(res.body.token);", "  return { ok: true };", "}",
            "export const sessionTitle = () => t('auth.title');"]),
        f"{m}/auth/oauth-session.spec.ts": _ts_module([("startSession", "./oauth-session")], [
            "test('rejects an empty code', async () => {", "  expect((await startSession('')).ok).toBe(false);", "});"]),
        f"{m}/auth/use-auth.spec.ts": _ts_module([("useAuth", "./use-auth")], [
            "test('starts signed out', () => {", "  expect(useAuth().signedIn).toBe(false);", "});"]),
        f"{m}/auth/use-auth.ts": _ts_module([("startSession", "./oauth-session"), ("readToken", "./token-store"),
                                            ("errorText", "../i18n/error-text"), ("t", i18n)], [
            "export function useAuth() {", "  return { signedIn: !!readToken(), signIn: startSession, retry: t('auth.retry'),",
            "    failed: errorText('unknown') };", "}"]),
        # Deep links back into the app.
        f"{m}/deep-links/parse-link.ts": _ts_module([("errorText", "../i18n/error-text"), ("t", i18n)], [
            "export type Link = { screen: string; code?: string } | { error: string };",
            "export function parseLink(url: string): Link {", "  const u = new URL(url);",
            "  if (u.pathname === '/oauth') return { screen: 'Login', code: u.searchParams.get('code') ?? undefined };",
            "  return { error: u.pathname ? errorText('unknown') : t('link.empty') };", "}"]),
        f"{m}/deep-links/parse-link.spec.ts": _ts_module([("parseLink", "./parse-link")], [
            "test('reads the code', () => {", "  expect(parseLink('acme://x/oauth?code=1')).toEqual({ screen: 'Login', code: '1' });", "});"]),
        f"{m}/deep-links/router.ts": _ts_module([("parseLink", "./parse-link"), ("startSession", "../auth/oauth-session"), ("t", i18n)], [
            "export async function route(url: string): Promise<string> {", "  const link = parseLink(url);",
            "  if ('error' in link) return link.error;", "  if (link.code) await startSession(link.code);",
            "  return t('link.opened', { screen: link.screen });", "}"]),
        f"{m}/deep-links/router.spec.ts": _ts_module([("route", "./router")], [
            "test('reports a broken link', async () => {", "  expect(await route('acme://x/')).toBeTruthy();", "});"]),
        # Shared components.
        f"{m}/components/Button.tsx": _ts_module([], [
            "export type ButtonProps = { label: string; onPress: () => void };",
            "export const Button = ({ label }: ButtonProps) => label;"]),
        f"{m}/components/Field.tsx": _ts_module([("t", i18n)], [
            "export const Field = ({ name }: { name: string }) => t(`field.${name}`);"]),
        f"{m}/components/Field.test.tsx": _ts_module([("Field", "./Field")], [
            "test('labels the field', () => {", "  expect(Field({ name: 'email' })).toBeTruthy();", "});"]),
        f"{m}/components/Toast.tsx": _ts_module([("errorText, type Failure", "../i18n/error-text")], [
            "export const Toast = ({ failure }: { failure: Failure }) => errorText(failure);"]),
        f"{m}/components/ErrorBanner.tsx": _ts_module([("errorText, type Failure", "../i18n/error-text"), ("Button", "./Button"), ("t", i18n)], [
            "export const ErrorBanner = ({ failure }: { failure: Failure }) => [errorText(failure), Button({ label: t('auth.retry'), onPress: () => {} })];"]),
        # Navigation and wiring.
        f"{m}/navigation/linking.ts": _ts_module([("route", "../deep-links/router")], [
            "export const linking = { prefixes: ['acme://'], subscribe: (url: string) => route(url) };"]),
        f"{m}/app/providers.tsx": _ts_module([("setLocale", i18n), ("linking", "../navigation/linking")], [
            "export const Providers = ({ children }: { children: unknown }) => {", "  setLocale(['pl-PL']);",
            "  return [linking, children];", "};"]),
        f"{m}/app/App.tsx": _ts_module([("Providers", "./providers"), ("Stack", "../navigation/stack")], [
            "export const App = () => Providers({ children: Stack() });"]),
        # Web bundle that shares the i18n package.
        "web/resources/js/flash.ts": _ts_module([("t", i18n), ("errorText", "../../../apps/mobile/src/i18n/error-text")], [
            "export function flash(kind: string): string {", "  return kind === 'error' ? errorText('unknown') : t(`flash.${kind}`);", "}"]),
        "web/resources/js/flash.spec.ts": _ts_module([("flash", "./flash")], [
            "test('error flash', () => {", "  expect(flash('error')).toBeTruthy();", "});"]),
        "web/resources/js/lang.ts": _ts_module([("setLocale", i18n), ("flash", "./flash")], [
            "export function boot(tags: readonly string[]): string {", "  setLocale(tags);", "  return flash('ready');", "}"]),
        # The API client the session uses.
        "packages/api-client/src/types.ts": _ts_module([], [
            "export type Response<T> = { ok: boolean; status: number; body: T };", "export type TokenBody = { token: string };"]),
        "packages/api-client/src/http.ts": _ts_module([("type Response", "./types"), ("t", "../../i18n/src/index")], [
            "export async function request(path: string, body: unknown): Promise<Response<any>> {",
            "  const res = await fetch(path, { method: 'POST', body: JSON.stringify(body) });",
            "  return { ok: res.ok, status: res.status, body: res.ok ? await res.json() : { message: t('http.failed') } };", "}"]),
        "packages/api-client/src/http.spec.ts": _ts_module([("request", "./http")], [
            "test('posts', async () => {", "  expect(request).toBeTruthy();", "});"]),
        # Config, lockfile, and docs.
        "apps/mobile/app.json": '{"expo": {"scheme": "acme", "name": "Acme"}}\n',
        "apps/mobile/eas.json": '{"build": {"preview": {"distribution": "internal"}}}\n',
        "apps/mobile/tsconfig.json": '{"compilerOptions": {"strict": true, "paths": {"@acme/i18n": ["../../packages/i18n/src/index.ts"]}}}\n',
        "apps/mobile/babel.config.js": "module.exports = { presets: ['babel-preset-expo'] };\n",
        "eslint.config.js": "export default [{ rules: { 'no-console': 'error' } }];\n",
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        "package.json": '{"name": "acme", "private": true, "workspaces": ["apps/*", "packages/*"]}\n',
        "docs/architecture/sign-in.md": "# Sign-in\n\nThe OAuth session, deep links, and error texts.\n",
    }
    # Screens: each uses both i18n hubs and two components; Settings is long.
    for name in screens:
        body = [f"export const {name}Screen = () => [", f"  t('{name.lower()}.title'),", "  errorText('network'),",
                "  Button({ label: t('ok'), onPress: () => {} }),", "  Field({ name: 'email' }),", "];"]
        if name == "Settings":
            body += [f"export const setting{i} = (on: boolean): string => (on ? t('settings.on.{i}') : t('settings.off.{i}'));"
                     for i in range(220)]
        imports = [("t", i18n), ("errorText", "../i18n/error-text"), ("Button", "../components/Button"), ("Field", "../components/Field")]
        if name == "Login":
            imports.append(("useAuth", "../auth/use-auth"))
            body.append("export const login = () => useAuth().signIn('code');")
        files[f"{m}/screens/{name}Screen.tsx"] = _ts_module(imports, body)
    files[f"{m}/screens/LoginScreen.test.tsx"] = _ts_module([("LoginScreen", "./LoginScreen")], [
        "test('renders', () => {", "  expect(LoginScreen()).toHaveLength(4);", "});"])
    files[f"{m}/navigation/stack.tsx"] = _ts_module([(f"{n}Screen", f"../screens/{n}Screen") for n in screens], [
        "export const Stack = () => [" + ", ".join(f"{n}Screen" for n in screens) + "];"])
    commit(repo, files, "feat: sign in with OAuth")
    overlay = d / "overlay.json"
    overlay.write_text(json.dumps({
        "nodes": {
            f"M:{m}/auth/oauth-session.ts": {"role": "Exchanges the OAuth code for a token"},
            "M:packages/i18n/src/index.ts": {"role": "Translation lookup shared by the app and the web bundle"},
            f"M:{m}/i18n/error-text.ts": {"role": "Failure texts for every sign-in error"},
            f"M:{m}/app/App.tsx": {"layer": "wiring"}, f"M:{m}/app/providers.tsx": {"layer": "wiring"},
            f"M:{m}/navigation/linking.ts": {"layer": "wiring"},
            "M:packages/api-client/src/types.ts": {"layer": "contract"},
        },
        "edges": [
            {"from": f"M:{m}/navigation/linking.ts", "to": "M:apps/mobile/app.json", "kind": "config"},
            {"from": "M:packages/i18n/src/index.ts", "to": "M:apps/mobile/tsconfig.json", "kind": "config"},
            {"from": f"M:{m}/app/App.tsx", "to": "M:apps/mobile/babel.config.js", "kind": "config"},
        ],
    }), encoding="utf-8")
    out = page(d, repo, [("M", "main...feat/sign-in", "M #47")], "Hub sample", lang="pl", overlay=overlay,
               extra=("--alias", f"{i18n}=packages/i18n/src/index.ts"))
    return {"page": str(out)}


# ---------------------------------------------------------------------------------------------------------------------
# sfc: Vue, Svelte, and Astro files with hunks in each block, plus files whose language highlight.js loads on demand.


def sfc(d: Path) -> dict:
    repo = new_repo(d / "repo")
    tpl = (["<template>", '  <article class="visit-card" :class="{ active }">']
           + [f'    <p class="row-{i}">{{{{ visit.field{i} }}}}</p>' for i in range(14)]
           + ["    <button type=\"button\" @click=\"emit('open', visit.id)\">Open</button>", "  </article>", "</template>", ""])
    scr = (['<script setup lang="ts">', "import { computed } from 'vue';", "import type { Visit } from '../types';", "",
            "const props = defineProps<{ visit: Visit; active: boolean }>();",
            "const emit = defineEmits<{ (e: 'open', id: number): void }>();"]
           + [f"const value{i} = computed(() => props.visit.field{i} ?? 0);" for i in range(12)]
           + ["export function label(v: Visit): string {", "  return `${v.id}: ${v.name}`;", "}", "</script>", ""])
    sty = (['<style lang="scss" scoped>', "$gap: 8px;", ".visit-card {"]
           + [f"  .row-{i} {{ margin: $gap * {i}; color: #333; }}" for i in range(12)]
           + ["  &.active { border-color: var(--accent); }", "}", "</style>", ""])
    vue = "\n".join(tpl + scr + sty)
    svelte = "\n".join(['<script lang="ts">', "  import { onMount } from 'svelte';", "  export let count: number = 0;"]
                       + [f'  let item{i}: string = "v{i}";' for i in range(12)]
                       + ["  onMount(() => { count += 1; });", "</script>", "", "<main>"]
                       + [f"  <p>{{item{i}}}</p>" for i in range(10)]
                       + ["  <button on:click={() => count++}>{count}</button>", "</main>", "", '<style lang="scss">',
                          "  main { padding: 1rem; }", "  p { color: red; }", "</style>", ""])
    astro = "\n".join(["---", "import Layout from '../layouts/Layout.astro';", "const title: string = 'Visits';", "---",
                       "<Layout title={title}>", "  <h1>{title}</h1>", "</Layout>", "<style>", "  h1 { color: navy; }", "</style>", ""])
    commit(repo, {
        "web/src/components/VisitCard.vue": vue, "web/src/routes/+page.svelte": svelte,
        "Dockerfile": "FROM node:20-alpine\nWORKDIR /app\nCOPY . .\nRUN npm ci\n", "app/build.gradle": "plugins {\n  id 'java'\n}\n",
        "api/visit.proto": 'syntax = "proto3";\nmessage Visit {\n  int64 id = 1;\n}\n', "web/.env.development": "API_URL=http://localhost\n",
        "db/schema.pgsql": "CREATE TABLE visit (id bigint PRIMARY KEY);\n", "infra/main.tf": 'resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}\n',
        "settings.gradle.kts": 'rootProject.name = "x"\n',
    }, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    vue2 = vue.replace('    <p class="row-7">{{ visit.field7 }}</p>', '    <p class="row-7" :title="label(visit)">{{ visit.field7 }}</p>')
    vue2 = vue2.replace("const value6 = computed(() => props.visit.field6 ?? 0);",
                        "const value6 = computed(() => (props.active ? props.visit.field6 : 0) ?? 0);")
    vue2 = vue2.replace("  .row-6 { margin: $gap * 6; color: #333; }", "  .row-6 { margin: $gap * 6; color: darken(#333, 10%); }")
    svelte2 = svelte.replace('  let item6: string = "v6";', "  let item6: string = `v${count}`;").replace("  <p>{item5}</p>", '  <p class="hot">{item5}</p>')
    commit(repo, {
        "web/src/components/VisitCard.vue": vue2, "web/src/routes/+page.svelte": svelte2, "web/src/pages/index.astro": astro,
        "Dockerfile": "FROM node:22-alpine\nWORKDIR /app\nCOPY . .\nRUN npm ci --omit=dev\n",
        "app/build.gradle": "plugins {\n  id 'java'\n  id 'application'\n}\n",
        "api/visit.proto": 'syntax = "proto3";\nmessage Visit {\n  int64 id = 1;\n  string name = 2;\n}\n',
        "web/.env.development": "API_URL=http://localhost:8080\nDEBUG=true\n",
        "db/schema.pgsql": "CREATE TABLE visit (id bigint PRIMARY KEY, name text NOT NULL);\n",
        "infra/main.tf": 'resource "aws_s3_bucket" "b" {\n  bucket = "y"\n}\n', "settings.gradle.kts": 'rootProject.name = "visits"\n',
    }, "feat")
    narrative = "<header><h1>Vue sample</h1></header>\n<!-- review-map:graph -->\n<footer>x</footer>\n"
    return {"page": str(page(d, repo, [("V", "main...feat", "V #7")], "Vue sample", narrative=narrative))}


# ---------------------------------------------------------------------------------------------------------------------
# addon: file names that are Object.prototype properties, a Vue script tag longer than git's funcname, and a node whose
# Dockerfile needs a language from cdnjs.


def _one_pr(repo: Path, base: dict[str, str], feat: dict[str, str]) -> Path:
    new_repo(repo)
    commit(repo, base, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    commit(repo, feat, "feat")
    return repo


def addon(d: Path) -> dict:
    narrative = "<header><h1>Add-on fixtures</h1></header>\n<!-- review-map:graph -->\n"
    out = {}
    odd = {"src/x.constructor": "a = 1\n", "constructor": "b = 2\n", "src/__proto__": "c = 3\n", "src/a.toString": "d = 4\n",
           "src/y.hasOwnProperty": "e = 5\n", "src/ok.ts": "export const ok: number = 1;\n"}
    repo = _one_pr(d / "odd-repo", {"README.md": "# x\n"}, odd)
    (d / "odd").mkdir(parents=True, exist_ok=True)
    out["odd"] = str(page(d / "odd", repo, [("X", "main...feat", "X")], "Odd names", narrative=narrative))
    tag = '<script setup generic="T extends Record<string, unknown>, U extends Array<T> = Array<T>" lang="ts">'
    vue = "\n".join(["<template>", "  <p>{{ n0 }}</p>", "</template>", "", tag] + [f"const n{i}: number = {i};" for i in range(12)] + ["</script>", ""])
    repo = _one_pr(d / "vue-repo", {"Long.vue": vue}, {"Long.vue": vue.replace("const n8: number = 8;", "const n8: number = 80;")})
    (d / "vue").mkdir(parents=True, exist_ok=True)
    out["vue"] = str(page(d / "vue", repo, [("X", "main...feat", "X")], "Long vue tag", narrative=narrative))
    docker = ["FROM node:20-alpine"] + [f"RUN echo step {i} && apk add --no-cache pkg{i}" for i in range(200)] + ['CMD ["node", "server.js"]', ""]
    repo = _one_pr(d / "redraw-repo", {"README.md": "# x\n"}, {
        "deploy/Dockerfile": "\n".join(docker), "deploy/a.ts": "\n".join(f"export const a{i}: number = {i};" for i in range(30)) + "\n",
        "deploy/b.ts": 'export const b: string = "b";\n'})
    groups = d / "groups.json"
    groups.write_text(json.dumps([{"id": "deploy", "label": "deploy", "layer": "config", "pattern": "^deploy/"}]), encoding="utf-8")
    (d / "redraw").mkdir(parents=True, exist_ok=True)
    out["redraw"] = str(page(d / "redraw", repo, [("X", "main...feat", "X")], "redraw", narrative=narrative, extra=("--groups", groups)))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# sec: markup in every field a report takes from data, and a page whose diffs.json predates fingerprints.

IMG = '<img src=x onerror="window.__pwn=(window.__pwn||[]).concat({})">'


def sec(d: Path) -> dict:
    repo = new_repo(d / "xss-repo")
    commit(repo, {"README.md": "# x\n"}, "base")
    git(repo, "checkout", "-q", "-b", "feat")
    bad = IMG.format("'path'") + ".ts"
    commit(repo, {f"src/{bad}": "export const x: number = 1;\n", "src/svc.ts": "import { x } from './" + bad[:-3] + "';\nexport const y = x;\n"}, "feat")
    overlay = d / "xss-overlay.json"
    overlay.write_text(json.dumps({"nodes": {"X:src/svc.ts": {
        "label": "svc " + IMG.format("'label'"), "role": "role " + IMG.format("'role'"),
        "note": "<code>kept</code> " + IMG.format("'note'") + ' <a href="javascript:window.__pwn=[\'js\']">js</a> <a href="https://example.com/x">ok</a>'
                '<script>window.__pwn=["script"]</script><svg><a href="#x">s</a></svg>'}}}), encoding="utf-8")
    graph, diffs = d / "xss-graphs.json", d / "xss-diffs.json"
    script("build_graph.py", "--out", graph, "--pr", "X", repo, "main...feat", "--name", "X", "X " + IMG.format("'name'"),
           "--title", "X", "T " + IMG.format("'title'"), "--repo", "X", "acme/" + IMG.format("'repo'"), "--overlay", overlay, "--no-manifest")
    script("gen_diffs.py", "--graph", graph, "--out", diffs, "--pr", "X", repo, "main...feat", "--no-manifest")
    data = json.loads(graph.read_text(encoding="utf-8"))
    data["prs"][0]["nodes"][0]["added"] = IMG.format("'added'")  # counts are data too
    # An area, a bucket, and merges carry text too: the area's label and why, a bucket that is no bucket, a "SHA" that
    # is markup (dropped, bare or in an entry) beside a real one (kept, in the older bare form).
    data["prs"][0]["clusters"] = [{"id": "c1", "label": "area " + IMG.format("'alabel'"), "order": 1, "depth": IMG.format("'depth'"),
                                   "why": "why " + IMG.format("'why'")}]
    for node in data["prs"][0]["nodes"]:
        node["cluster"] = "c1"
        node["bucket"] = IMG.format("'bucket'")
        node["conflict"] = ["abc1234", IMG.format("'conflict'"), {"sha": IMG.format("'csha'"), "kind": "picked", "lines": 3}]
    graph.write_text(json.dumps(data), encoding="utf-8")
    entries = json.loads(diffs.read_text(encoding="utf-8"))
    files = {e["path"]: e["fp"] for es in entries.values() for e in es}
    previous = d / "xss-previous.json"
    previous.write_text(json.dumps({"generation": 0, "tips": {"X": "1234567", "Y": "89abcde"},
                                    "files": {"X": {**{p: "0" * 12 for p in files}, "src/" + IMG.format("'removed'") + ".ts": "1" * 12},
                                              "Y": {IMG.format("'gonepr'"): "2" * 12}}}), encoding="utf-8")
    narr = d / "narrative.html"
    ref = html.escape("src/" + bad + ":1", quote=False)  # the markup-named file, referenced as text from a risk
    narr.write_text("<header><h1>Fixtures</h1></header>\n<!-- review-map:graph -->\n"
                    f'<section id="risks"><h2>Risks</h2><ul class="risk-list"><li class="sev-h">Odd name: <code>{ref}</code></li></ul></section>\n', encoding="utf-8")
    # validate.py refuses these values (a real report cannot carry them); the pages are built anyway so the viewer is
    # tested against them, and the fixture asserts that validate.py rejects exactly those fields, nothing else.
    bad_fields = ("node X1 has bucket", "node X1: conflict", "node X2 has bucket", "node X2: conflict", "cluster 'c1' depth")
    assemble(graph, diffs, narr, "xss", d / "xss.html", previous=previous, rejects=bad_fields)
    nofp = d / "nofp-diffs.json"
    nofp.write_text(json.dumps({k: [{kk: v for kk, v in e.items() if kk != "fp"} for e in es] for k, es in entries.items()}), encoding="utf-8")
    assemble(graph, nofp, narr, "nofp", d / "nofp.html", rejects=bad_fields)
    assemble(graph, nofp, narr, "nofp", d / "nofp-prev.html", previous=previous, rejects=bad_fields)
    return {"xss": str(d / "xss.html"), "nofp": str(d / "nofp.html"), "nofpPrev": str(d / "nofp-prev.html")}


# ---------------------------------------------------------------------------------------------------------------------
# plan: two stacked PRs for the review plan, conflicts, narrative references, and the workspace. P has three authored
# areas (read, skim, tool, each with a why), a generated file alone in its folder, docs and i18n, and two files resolved
# by hand in merges (and one resolved to one side); Q (on P) has no areas, buckets, or conflicts, like a report from before them, two unchanged
# reference files (one beside its changed file, one alone in an authored area), and a pure rename (no changed lines). The narrative's risks
# name lines inside and outside the diff, a bare file name, a continuation, and references that must stay plain.

PLAN_NARRATIVE = """<header><h1>Plan sample</h1><p class="sub">Areas, conflicts, and references.</p></header>
<!-- review-map:graph -->
<section id="risks"><h2>Risks</h2>
<ul class="risk-list">
<li class="sev-h"><span class="who tag c-P">P</span><strong>Token lifetime.</strong> The TTL moved: <code>src/auth/session.ts:40</code>.</li>
<li class="sev-m"><span class="who tag c-P">P</span><strong>Rounding.</strong> See <code>invoice.ts:3-4</code> and <code>:8</code>.</li>
<li class="sev-l"><span class="who tag c-P">P</span><strong>Header.</strong> <code>src/auth/session.ts:2</code> sits outside the diff.</li>
<li class="sev-l"><span class="who tag c-Q">Q</span><strong>No references.</strong> <code>nowhere.ts:5</code>, <code>index.ts:1</code>, and <code>12:30</code> stay plain.</li>
</ul>
<p>Elsewhere: <code>token.ts:10-12</code>, and in a block <code>web/app.ts:1</code> inside <a href="#risks"><code>web/app.ts:2</code></a>.</p>
<pre class="code"><code>src/auth/session.ts:40</code></pre>
</section>
"""
PLAN_AREAS = {"auth": ("read", "Token lifetime and storage"), "billing": ("skim", "Mechanical rounding change"), "util": ("tool", "Formatting only")}
# Merge resolutions as build_graph.py writes them: session.ts combined by hand in one merge and resolved to one side in
# another, invoice.ts combined by hand, token.ts only resolved to one side (no mark, no count; listed in its panel).
PLAN_CONFLICTS = {"src/auth/session.ts": [{"sha": "abc1234", "kind": "merged", "lines": 12}, {"sha": "def5678", "kind": "picked", "lines": 4}],
                  "src/billing/invoice.ts": [{"sha": "0badc0d1", "kind": "merged", "lines": 3}],
                  "src/auth/token.ts": [{"sha": "abc1234", "kind": "picked", "lines": 2}]}


def plan(d: Path) -> dict:
    repo = new_repo(d / "repo")
    session = [f"export const s{i} = {i};" for i in range(1, 61)]
    invoice = [f"export const i{k} = {k};" for k in range(1, 11)]
    commit(repo, {"README.md": "# plan\n", "src/auth/session.ts": "\n".join(session) + "\n", "src/billing/invoice.ts": "\n".join(invoice) + "\n",
                  "locales/en.json": '{"a": "b"}\n', "lib/consts.ts": "export const LIMIT = 10;\n", "web/theme.ts": "export const theme = 'dark';\n",
                  "styles/base.ts": "".join(f"export const c{i} = {i};\n" for i in range(12))}, "base")
    git(repo, "checkout", "-q", "-b", "feat/p")
    session[39] = "export const s40 = 4000;"
    for k in (3, 4, 8):
        invoice[k - 1] = f"export const i{k} = Math.round({k} * 100) / 100;"
    commit(repo, {
        "src/auth/session.ts": "\n".join(session) + "\n",
        "src/auth/token.ts": "import { s1 } from './session';\n" + "".join(f"export const t{i} = s1 + {i};\n" for i in range(2, 51)),
        "src/auth/index.ts": "export * from './session';\nexport * from './token';\n",
        "src/auth/session.spec.ts": "import { s40 } from './session';\ntest('ttl', () => expect(s40).toBe(4000));\n",
        "src/billing/invoice.ts": "\n".join(invoice) + "\n",
        "src/billing/index.ts": "export * from './invoice';\n",
        "src/billing/invoice.spec.ts": "import { i3 } from './invoice';\ntest('rounds', () => expect(i3).toBe(3));\n",
        "src/util/fmt.ts": "export const fmt = (n: number): string => n.toFixed(2);\n",
        "gen/api.ts": "".join(f"export const op{i} = '/api/{i}';\n" for i in range(30)),
        "locales/en.json": '{"a": "b", "ttl": "Session length"}\n',
        "docs/plan.md": "# Plan\n\nWhy the TTL changed.\n",
    }, "P")
    git(repo, "checkout", "-q", "-b", "feat/q")
    git(repo, "mv", "styles/base.ts", "styles/main.ts")  # a pure rename: a changed file with no changed lines
    commit(repo, {"web/app.ts": "import { s40 } from '../src/auth/index';\nexport const app = () => s40;\n",
                  "web/app.spec.ts": "import { app } from './app';\ntest('app', () => expect(app()).toBe(4000));\n"}, "Q")
    overlay = d / "overlay.json"
    overlay.write_text(json.dumps({
        "clusters": {"auth": {"label": "Sign-in", "order": 1}, "billing": {"label": "Billing", "order": 2}, "util": {"label": "Utilities", "order": 3},
                     "ref": {"label": "Reference", "order": 4}},
        "nodes": {"P:src/auth/session.ts": {"cluster": "auth"}, "P:src/auth/token.ts": {"cluster": "auth"}, "P:src/auth/index.ts": {"cluster": "auth"},
                  "P:src/billing/invoice.ts": {"cluster": "billing"}, "P:src/billing/index.ts": {"cluster": "billing"},
                  "P:src/util/fmt.ts": {"cluster": "util"}, "Q:lib/consts.ts": {"cluster": "ref"}},
        # Unchanged reference files in Q: one beside web/app.ts, one alone in the authored area "ref" (an area of nothing but references).
        "extraNodes": [{"pr": "Q", "path": "web/theme.ts"}, {"pr": "Q", "path": "lib/consts.ts"}],
    }), encoding="utf-8")
    graph, diffs, narr, out = d / "graphs.json", d / "diffs.json", d / "narrative.html", d / "review.html"
    prs = [("P", "main...feat/p", "P #11"), ("Q", "feat/p...feat/q", "Q #12")]
    args: list[object] = ["--out", graph, "--overlay", overlay]
    for key, rng, name in prs:
        args += ["--pr", key, repo, rng, "--name", key, name]
    script("build_graph.py", *args, "--no-manifest")
    # The data side's fields (build_graph.py writes them in newer versions): area depth and why, buckets, conflicts.
    data = json.loads(graph.read_text(encoding="utf-8"))
    for c in data["prs"][0].get("clusters", []):
        c["depth"], c["why"] = PLAN_AREAS[c["id"]]
    for n in data["prs"][0]["nodes"]:
        n["bucket"] = "generated" if n["path"] == "gen/api.ts" else {"test": "test", "i18n": "i18n", "docs": "docs", "config": "config"}.get(n["layer"], "logic")
        if n["path"] in PLAN_CONFLICTS:
            n["conflict"] = PLAN_CONFLICTS[n["path"]]
    graph.write_text(json.dumps(data), encoding="utf-8")
    args = ["--graph", graph, "--out", diffs]
    for key, rng, _ in prs:
        args += ["--pr", key, repo, rng]
    script("gen_diffs.py", *args, "--strict", "--no-manifest")
    narr.write_text(PLAN_NARRATIVE, encoding="utf-8")
    assemble(graph, diffs, narr, "Plan sample", out)
    pl = d / "review-pl.html"
    assemble(graph, diffs, narr, "Plan sample", pl, lang="pl")
    return {"page": str(out), "pl": str(pl)}


# ---------------------------------------------------------------------------------------------------------------------
# The refresh demo: two stacked PRs, A (feat/items on main) and B (feat/web on feat/items), built at v1, then moved the
# way a fix round moves them. Fixed commit dates keep the SHAs the same on every run.

DEMO_OVERLAY = {"nodes": {
    "A:src/service.ts": {"role": "Lists items a page at a time; prices through the legacy helper"},
    "A:src/controller.ts": {"role": "GET /items handler"},
    "A:src/types.ts": {"role": "Item and Page types"},
    "A:src/format.ts": {"role": "Item label for the list"},
    "A:src/legacy.ts": {"role": "Legacy label switched to a template string"},
    "A:src/service.spec.ts": {"role": "Paging test"},
    "B:web/app.tsx": {"role": "Renders the item list"},
    "B:web/app.spec.tsx": {"role": "Render test"},
}}
LEGACY = """// Legacy pricing helpers, kept for old callers.
export const TAX = 0.23;

export function gross(net: number): number {
  return Math.round(net * (1 + TAX) * 100) / 100;
}

export function legacyLabel(id: number): string {
  return 'item-' + id;
}
"""
SERVICE_V1 = """import type { Item, Page } from './types';
import { gross } from './legacy';

const ITEMS: Item[] = [
  { id: 1, name: 'Apple' },
  { id: 2, name: 'Pear' },
];

export function listItems(offset: number, limit: number): Page<Item> {
  const items = ITEMS.slice(offset, offset + limit);
  return { items, total: ITEMS.length };
}

export function priceOf(net: number): number {
  return gross(net);
}
"""
CONTROLLER_V1 = """import { listItems } from './service';
import { formatItem } from './format';

export function handleList(query: { offset?: string; limit?: string }) {
  const offset = Number(query.offset ?? 0);
  const limit = Number(query.limit ?? 20);
  const page = listItems(offset, limit);
  return { status: 200, body: page.items.map(formatItem) };
}
"""
SERVICE_V2 = """import type { Item, Page } from './types';
import { gross } from './legacy';
import { cached } from './cache';

const ITEMS: Item[] = [
  { id: 1, name: 'Apple', price: 2 },
  { id: 2, name: 'Pear', price: 3 },
];

/** Default page size when the caller gives none. */
export const PAGE = 20;

export function listItems(offset: number, limit: number): Page<Item> {
  const items = ITEMS.slice(offset, offset + limit);
  return { items, total: ITEMS.length };
}

export function priceOf(net: number): number {
  return cached(net, gross);
}
"""
CONTROLLER_V2 = """import { listItems, PAGE } from './service';

export function handleList(query: { offset?: string; limit?: string }) {
  const offset = Math.max(0, parseInt(query.offset ?? '0', 10) || 0);
  const limit = Math.min(100, parseInt(query.limit ?? String(PAGE), 10) || PAGE);
  const page = listItems(offset, limit);
  return { status: 200, body: page.items.map((item) => `#${item.id} ${item.name}`) };
}
"""
CACHE = """const memo = new Map<number, number>();

export function cached(key: number, compute: (key: number) => number): number {
  if (!memo.has(key)) memo.set(key, compute(key));
  return memo.get(key)!;
}
"""


def _demo_env(date: str) -> dict:
    return {**ENV, "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.com", "GIT_COMMITTER_NAME": "demo",
            "GIT_COMMITTER_EMAIL": "demo@example.com", "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}


def _demo_commit(repo: Path, message: str, date: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, env=_demo_env(date))


def _demo_tips(repo: Path) -> dict:
    return {"A": git(repo, "rev-parse", "--short", "feat/items").strip(), "B": git(repo, "rev-parse", "--short", "feat/web").strip()}


def _demo_build(demo: Path, out: Path) -> None:
    """build_graph -> gen_diffs -> assemble -> validate in `out`, with the inputs build-v1 uses (the manifest is written)."""
    repo = demo / "repo"
    script("build_graph.py", "--out", "graphs.json", "--pr", "A", repo, "main...feat/items", "--name", "A", "A #1",
           "--pr", "B", repo, "feat/items...feat/web", "--name", "B", "B #2", "--title", "A", "Items service", "--title", "B", "Web app",
           "--overlay", "overlay.json", cwd=out)
    script("gen_diffs.py", "--graph", "graphs.json", "--out", "diffs.json", "--pr", "A", repo, "main...feat/items",
           "--pr", "B", repo, "feat/items...feat/web", "--strict", cwd=out)
    script("assemble.py", "--graph", "graphs.json", "--diffs", "diffs.json", "--narrative", "narrative.html",
           "--title", "Refresh demo", "--lang", "en", "--target", "local", "--out", "review.html", cwd=out)
    validate(out / "review.html")


def demo_v1(demo: Path) -> dict:
    """(Re)create the demo repository and build report v1 into demo/scratch/review.html."""
    repo, scratch = demo / "repo", demo / "scratch"
    shutil.rmtree(repo, ignore_errors=True)
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    new_repo(repo)
    write(repo, {"README.md": "# Items demo\n", "src/legacy.ts": LEGACY})
    _demo_commit(repo, "base", "2026-10-01T10:00:00Z")
    git(repo, "checkout", "-q", "-b", "feat/items")
    write(repo, {
        "src/types.ts": "export type Item = { id: number; name: string };\nexport type Page<T> = { items: T[]; total: number };\n",
        "src/format.ts": "import type { Item } from './types';\n\nexport function formatItem(item: Item): string {\n  return `#${item.id} ${item.name}`;\n}\n",
        "src/service.ts": SERVICE_V1, "src/controller.ts": CONTROLLER_V1,
        "src/service.spec.ts": "import { listItems } from './service';\n\ntest('lists the first page', () => {\n"
                               "  expect(listItems(0, 1).items).toHaveLength(1);\n});\n",
        "src/legacy.ts": LEGACY.replace("'item-' + id", "`item-${id}`"),
    })
    _demo_commit(repo, "feat: items service and controller", "2026-10-02T10:00:00Z")
    git(repo, "checkout", "-q", "-b", "feat/web")
    write(repo, {
        "web/app.tsx": "import { handleList } from '../src/controller';\n\nexport function App() {\n"
                       "  const res = handleList({ limit: '10' });\n  return res.body.join('\\n');\n}\n",
        "web/app.spec.tsx": "import { App } from './app';\n\ntest('renders items', () => {\n  expect(App()).toContain('Apple');\n});\n",
    })
    _demo_commit(repo, "feat: web app", "2026-10-03T10:00:00Z")
    git(repo, "checkout", "-q", "main")
    tips = _demo_tips(repo)
    (scratch / "overlay.json").write_text(json.dumps(DEMO_OVERLAY, indent=1) + "\n", encoding="utf-8")
    (scratch / "narrative.html").write_text(
        '<header><h1>Items demo</h1><p class="sub">Two stacked PRs used to try refresh.py: the items service (A) and the web app on top of it (B).</p></header>\n'
        '<section id="stack" data-toc="PR stack"><h2>PR stack and merge order</h2>\n<div class="grid-4">\n'
        f'<div class="pr-card c-A"><span class="k">A · service</span><span class="t">A #1</span><span class="meta">base <code>main</code> · 6 files · tip <code>{tips["A"]}</code></span></div>\n'
        f'<div class="pr-card c-B"><span class="k">B · web</span><span class="t">B #2</span><span class="meta">base <code>feat/items</code> · 2 files · tip <code>{tips["B"]}</code></span></div>\n'
        "</div></section>\n<!-- review-map:graph -->\n"
        '<section id="verify" data-toc="Verification"><h2>Verification</h2><p>Demo only; nothing was run.</p></section>\n', encoding="utf-8")
    _demo_build(demo, scratch)
    return tips


def demo_move(demo: Path) -> dict:
    """Move the demo branches the way a fix round does (see the module docstring of the refresh checks)."""
    repo = demo / "repo"
    if git(repo, "tag", "-l", "demo-v2").strip():
        raise SystemExit("the demo branches already moved; run demo-v1 to start over")
    old_items = git(repo, "rev-parse", "feat/items").strip()
    git(repo, "checkout", "-q", "main")
    legacy = (repo / "src" / "legacy.ts").read_text(encoding="utf-8")
    write(repo, {"src/legacy.ts": "// Owned by the billing team.\n// Do not add new callers.\n\n" + legacy})
    _demo_commit(repo, "docs: legacy ownership", "2026-10-11T10:00:00Z")
    rebase_env = {**_demo_env("2026-10-15T10:00:00Z")}
    rebase_env.pop("GIT_AUTHOR_DATE")
    git(repo, "rebase", "-q", "main", "feat/items", env=rebase_env)
    write(repo, {
        "src/types.ts": "/** One sellable item. */\nexport type Item = { id: number; name: string; price: number };\n"
                        "export type Page<T> = { items: T[]; total: number };\n",
        "src/service.ts": SERVICE_V2, "src/cache.ts": CACHE, "src/controller.ts": CONTROLLER_V2,
    })
    git(repo, "rm", "-q", "src/format.ts")
    _demo_commit(repo, "fix: review round 1", "2026-10-12T10:00:00Z")
    git(repo, "rebase", "-q", "--onto", "feat/items", old_items, "feat/web", env=rebase_env)
    git(repo, "checkout", "-q", "main")
    git(repo, "tag", "demo-v2")
    return _demo_tips(repo)


def demo_rebuild(demo: Path, out: Path | None = None) -> dict:
    """Rebuild the demo page by hand into `out` (no refresh.py, no --previous); inputs come from demo/scratch."""
    out = out or demo / "scratch"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("overlay.json", "narrative.html"):
        if not (out / name).exists():
            shutil.copyfile(demo / "scratch" / name, out / name)
    _demo_build(demo, out)
    return _demo_tips(demo / "repo")


FIXTURES = {"stack": stack, "big": big, "hub": hub, "sfc": sfc, "addon": addon, "sec": sec, "plan": plan}


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[0] not in ("build", "demo-v1", "demo-move", "demo-rebuild"):
        raise SystemExit(__doc__)
    cmd, target = argv[0], Path(argv[1]).resolve()
    if cmd == "build":
        target.mkdir(parents=True, exist_ok=True)
        pages = {}
        for name in (argv[2:] or FIXTURES):
            d = target / name
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)
            pages[name] = FIXTURES[name](d)
        print(json.dumps(pages))
    elif cmd == "demo-v1":
        print(json.dumps(demo_v1(target)))
    elif cmd == "demo-move":
        print(json.dumps(demo_move(target)))
    else:
        print(json.dumps(demo_rebuild(target, Path(argv[2]).resolve() if len(argv) > 2 else None)))


if __name__ == "__main__":
    main(sys.argv[1:])
