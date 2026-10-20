# Narrative sections: structure and HTML building blocks

`narrative.html` is the content of `<main>` around the reading graph. It is split
by one line, `<!-- review-map:graph -->`: the header and stack cards go above it,
everything else below. Write it in the report language. Each `<section id="…">`
with an `<h2>` becomes a TOC entry; add `data-toc="short label"` when the heading
is long or carries tags.

Colour per PR: class `c-<KEY>` sets `--c` to that PR's palette colour (the same
colour as its graph tab). Use it on `.pr-card`, `.tag`, and `ol.steps`.

Code references: write every one as `path:line` or `path:start-end`, relative to the
repository root, in `<code>` (`<code>apps/api/src/items/query.ts:26-95</code>`), in
rules, PR sections, and risks alike. The viewer turns them into links that open the
diff at those lines; it cannot place a bare file name or a path from another root.

What to read and how long it takes is not prose: the viewer generates a "Plan review"
table (a row per area: files, lines, depth, estimated time from each kind's reading
rate, files combined by hand in a merge) and a bar
of changed lines by kind (logic, tests, i18n, docs, config, generated) from the graph.
Do not write a "what to read first" list, time estimates, or line counts by kind; steer
the plan through the areas' `depth` and `why` in the overlay (`references/graph-schema.md`,
Areas) instead.

## 1. Header and PR stack (above the marker)

```html
<header>
  <h1>Feature name in plain words</h1>
  <p class="sub">One or two sentences: what the stack delivers, where it is visible, flags, design link, tracking doc.</p>
</header>

<section id="stack" data-toc="PR stack">
  <h2>PR stack and merge order</h2>
  <p class="lead">Why the order matters (which PR must ship first and what breaks otherwise).</p>
  <div class="grid-4">
    <div class="pr-card c-S">
      <span class="k">S · short layer name</span>
      <span class="t"><a href="https://github.com/org/repo/pull/123">repo#123</a></span>
      <span class="meta">base <code>main</code> · 30 files · +1200/−40 · tip <code>c9e7133</code></span>
      <ul><li>Two or three bullets</li><li>of what this PR adds</li></ul>
    </div>
    <!-- one card per PR, in merge order -->
  </div>
  <div class="callout warn"><strong>Branch history:</strong> fixes flowed up the stack as merge commits (S → A → B); each PR's diff against its base is clean.</div>
</section>
```

Take files, +/−, and tip SHA from `git diff --shortstat <range>` and
`git rev-parse --short <tip>`; include the merge-commit callout only when
`git log --merges <range>` is non-empty. Write the tip as its short SHA in
`<code>`: when a branch moves, `refresh.py` finds the cards that still show an
old tip, prints the new tip and counts, and leaves the edit to you.

A PR split into parts (`references/chunks.md`) gets one card for the whole PR,
with class `c-<parent key>` (its first part's colour) and its parts in a nested
`ol.parts`, one row per part with its open button (`data-gopen` with the part key,
labelled with the part number), label, file count, and commit range:

```html
<div class="pr-card c-M">
  <span class="k">M · one PR in 5 parts</span>
  <span class="t"><a href="https://github.com/org/repo/pull/251">repo#251</a></span>
  <span class="meta">base <code>develop</code> · 219 files · +9100/−420 · tip <code>9f8e7d6</code></span>
  <ol class="parts">
    <li><button type="button" class="tag c-Ma" data-gopen="Ma">1/5</button><span>client-core</span><span class="meta">34 files · <code>1a2b3c4..5d6e7f8</code></span></li>
    <!-- one row per part, in order -->
  </ol>
</div>
<div class="callout warn"><strong>Parts:</strong> read them in order, since each builds on the ones before. They are commit ranges of one PR that merges as a whole, so there is no merge order to keep.</div>
```

Take each part's files from `chunks.py expand` and its range from the `from..to`
it prints. `refresh.py` names the rows that still show a part's old end after a
rebase and a new part the list does not have yet.

```html
<!-- review-map:graph -->
```

## 2. Architecture (below the marker)

```html
<section id="arch">
  <h2>Architecture</h2>
  <p class="lead">One paragraph: what each layer is responsible for.</p>
  <div class="diagram">
<pre class="mermaid">
flowchart LR
  subgraph B["PR B · web"]
    R["route"] --> SL["loader"]
  end
  subgraph A["PR A · api"]
    H["GET /items/:id"] --> Q["query"]
  end
  SL -- "x-tenant-id" --> H
</pre>
  </div>
  <div class="cols-2" style="margin-top:16px">
    <div class="panel"><h4>Boundaries</h4><ul><li>…</li></ul></div>
    <div class="panel"><h4>Who owns what</h4><ul><li>…</li></ul></div>
  </div>
</section>
```

Mermaid source stays unindented inside `<pre class="mermaid">`. Quote labels that
contain punctuation, use `<br/>` for line breaks, and escape `<`/`&` in labels as
`&lt;`/`&amp;`.

## 3. Request flow and error mapping

```html
<section id="flow">
  <h2>Request flow</h2>
  <p class="lead">What is awaited, what streams, what fails soft.</p>
  <div class="diagram">
<pre class="mermaid">
sequenceDiagram
  autonumber
  participant W as web loader
  participant A as api
  W->>A: GET /items/:id (timeout 3 s)
  A-->>W: 200 render-ready model
</pre>
  </div>
  <h3>Error mapping across layers</h3>
  <div class="tbl"><table>
    <thead><tr><th>Situation</th><th>Upstream</th><th>Service</th><th>BFF</th><th>Web</th></tr></thead>
    <tbody><tr><td>Unknown id</td><td>404</td><td>404</td><td>404</td><td>section hidden</td></tr></tbody>
  </table></div>
</section>
```

## 4. Data shape across layers

```html
<section id="shapes">
  <h2>Data shape across layers</h2>
  <p class="lead">The same field at each stage; "—" means the layer drops it.</p>
  <div class="tbl"><table>
    <thead><tr><th>Upstream (raw)</th><th>Service contract</th><th>BFF contract</th><th>Notes</th></tr></thead>
    <tbody><tr><td><code>items[].id</code></td><td><code>id</code></td><td><code>itemId</code></td><td>Repeats per category; deduplicated in the BFF</td></tr></tbody>
  </table></div>
</section>
```

## 5. Business rules with concrete examples

```html
<section id="rules">
  <h2>Business rules</h2>
  <div class="cols-2">
    <div class="panel">
      <h4>Order and deduplication (A)</h4>
      <ol class="steps c-A"><li><span><strong>Dedupe by id</strong>: first occurrence wins.</span></li></ol>
      <p style="font-size:14px;color:var(--muted)"><code>path/to/query.ts:26-95</code></p>
    </div>
  </div>
  <div class="tbl"><table>
    <thead><tr><th>Input</th><th>Result</th><th>Example</th></tr></thead>
    <tbody><tr><td>all prices equal</td><td>one price</td><td class="num">200 zł</td></tr></tbody>
  </table></div>
</section>
```

Every rule gets a concrete example row, and its source as `path:line` (or `path:start-end`).

## 6. One section per PR

```html
<section id="pr-S" data-toc="PR S · service">
  <h2><span class="tag c-S">S</span> Service layer · <a href="https://github.com/org/repo/pull/123">#123</a></h2>
  <p class="lead">Purpose in two or three sentences.</p>
  <p><button type="button" class="tag c-S" data-gopen="S"></button></p>
  <details><summary>Files (30)</summary><div class="body"><ul class="files">
    <li><span class="path">contract/schemas/items.schema.ts</span><span class="d">+79</span><span class="role">Zod schemas of the contract</span></li>
  </ul></div></details>
  <div class="callout warn"><strong>To check:</strong> one concrete thing a reviewer must verify, with the reason.</div>
</section>
```

- The empty `data-gopen` button gets the "open on the reading graph" label and
  switches the graph to that PR (`data-order="bottom"` opens it in dependency order).
- Optionally, a button per tour of the PR (`tours` in the overlay):
  `<button type="button" class="tag c-S" data-tour="apple-web"></button>`. Empty, it is
  labelled "Take the tour: <name>" (Polish "Przejdź trasę: …") and starts that tour on
  the graph; one naming no tour of the page is hidden (validate.py warns). It fits the
  request-flow section too.
- No numbered reading-order list here: the graph owns the reading order, and
  per-file explanations live in the graph's `note` fields.
- An intended change users will notice (a new default, a removed option, another
  status code or message) is a fact of the PR, not a risk: state it in the lead or a
  `<div class="callout warn"><strong>Behaviour change:</strong> …</div>`, never only as
  a risk bullet.
- A file the graph marks as combined by hand in a merge (a `conflict` entry of kind
  `merged`, a ↯ badge in the viewer) deserves a look: when its resolution matters, name
  it with the merge's SHA in a "To check" callout. A `picked` entry (the merge took one
  side's version) needs no callout.
- Collapse long file lists; group siblings on one line
  (`infra/providers/{client,url,mapper}.ts`, `+37 · +5 · +46`).
- Extra blocks that help: a component tree in `<pre class="code">`, an a11y list,
  a translation-key table inside `<details>`.

## 7. Risks ranked by severity, then out of scope

```html
<section id="risks">
  <h2>Risks and review questions</h2>
  <p class="lead">Most important first. The stripe colour is the severity.</p>
  <ul class="risk-list">
    <li class="sev-h"><span class="who tag c-S">S</span><strong>Deploy order.</strong> Why it matters and how to confirm (<code>libs/x/infra/monolith.client.ts:12-30</code>).</li>
    <li class="sev-m"><span class="who tag c-A">A</span><strong>…</strong> …</li>
    <li class="sev-l"><span class="who tag c-B">B</span><strong>…</strong> …</li>
  </ul>
  <h3>Deliberately out of scope</h3>
  <p>…</p>
</section>
```

Each risk names the code it is about as `path:line` or `path:start-end` (above), so a
click opens it in the diff. A risk is what could go wrong; a behaviour change the PR
intends belongs in its section (above).

## 8. Verification, then footer

```html
<section id="verify">
  <h2>Verification</h2>
  <div class="callout ok"><strong>Ran:</strong> exact commands or suites and their results per PR.</div>
  <div class="callout warn"><strong>Not run:</strong> what only CI or a live check will cover.</div>
</section>

<footer>As of <date>. <code>path:line</code> references point at the branch tips listed in the PR stack.</footer>
```

State only what was actually run. A suite you did not run goes under "Not run".

## Available classes

`panel`, `grid-4`, `pr-card` (`k`, `t`, `meta`, `ol.parts`), `tag`, `tbl` + `table`,
`td.num`, `callout warn|risk|ok`, `details > summary + .body`, `files`
(`path`, `d`, `role`), `steps`, `risk-list` + `sev-h|sev-m|sev-l` + `who`,
`diagram` + `pre.mermaid`, `pre.code`, `cols-2`, `pill ok|warn|risk`, `lead`, `sub`.
Theme tokens: `--bg --surface --fg --muted --line --soft --accent --accent-ink`,
`--pal-1 … --pal-8`, `--warn-* --risk-* --ok-*`; they switch for dark mode.
