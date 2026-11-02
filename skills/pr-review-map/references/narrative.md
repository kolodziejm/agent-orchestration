# Narrative: what to write and the HTML for it

`narrative.html` is the content of `<main>` around the reading graph. It is split
by one line, `<!-- review-map:graph -->`: the title header above it, everything
else below. Write it in the report language. Each `<section id="…">` with an
`<h2>` becomes a TOC entry; add `data-toc="short label"` when the heading is long.

The page is read next to the graph, so it does not repeat the graph or the diff. The
graph owns the reading order, the file list, the per-file notes, and the sizes; the
narrative says only what neither shows: what changed in behaviour and structure, and
what to decide before merging.

Colour per PR: class `c-<KEY>` sets `--c` to that PR's palette colour (the same
colour as its graph tab). Use it on `.tag` and `ol.steps`.

Code references: write every one as `path:line` or `path:start-end`, relative to the
repository root, in `<code>` (`<code>apps/api/src/items/query.ts:26-95</code>`). The
viewer turns them into links that open the diff at those lines; it cannot place a
bare file name or a path from another root.

## 1. Header (above the marker) and merge order

```html
<header>
  <h1>Feature name in plain words</h1>
  <p class="sub">One sentence, only if the title does not say it.</p>
</header>

<!-- review-map:graph -->
```

Do not write the merge order. `assemble.py` appends it to the header: one line per
PR in merge order with key, name, title, tip SHA, file count, and +/−, taken from
`graphs.json` (a PR split into parts, `references/chunks.md`, is one line with its
parts under it). Nothing in it is typed by hand, so it is right after `refresh.py`.
The name links to the PR's section below (`id="pr-<KEY>"`, so name the sections that way),
and the whole row follows the link.

Under each line goes the PR's summary: one or two short sentences saying what the PR does
and what changes for users or the system. It is authored, in the overlay's `summaries`
(`{"A": "…"}`, `references/graph-schema.md`), not in the narrative; a PR without one has
a line without a sentence. Write it from the change map's Purpose, and do not repeat the
bullets below it.

## 2. Architecture (optional)

Include it only when the PRs change how layers connect (a new service call, a new
boundary, a moved responsibility). Skip it for a change inside one layer. A mermaid
flowchart and at most one line of text:

```html
<section id="arch">
  <h2>Architecture</h2>
  <p style="color:var(--muted)">One line: what the diagram shows that the graph does not.</p>
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
</section>
```

Mermaid source stays unindented inside `<pre class="mermaid">`. Quote labels that
contain punctuation, use `<br/>` for line breaks, and escape `<`/`&` in labels as
`&lt;`/`&amp;`. Do not set a theme in the diagram source. Keep node labels and notes short
(a few words, one line): a long note overflows its box and a diagram of many long labels is
unreadable even when zoomed. Every diagram has zoom in, zoom out, and fit buttons, Ctrl+wheel
and pinch zoom, drag to pan, and the keys `+`, `-`, `0`; the page still scrolls over it.

## 3. Request flow (optional)

Include it only when a request, event, or job crosses layers and the order matters.
A mermaid sequence diagram and at most one line of text. Failure paths (not found,
upstream 5xx, timeout, bad payload, missing config) go inside the diagram as `alt` /
`else` blocks with what the layer returns or logs; there is no error table.

```html
<section id="flow">
  <h2>Request flow</h2>
  <p style="color:var(--muted)">One line, only if the diagram needs it.</p>
  <div class="diagram">
<pre class="mermaid">
sequenceDiagram
  autonumber
  participant W as web loader
  participant A as api
  W->>A: GET /items/:id (timeout 3 s)
  alt found
    A-->>W: 200 render-ready model
  else unknown id
    A-->>W: 404, the section is hidden
  else upstream 5xx
    A-->>W: 502, logged, the section is hidden
  end
</pre>
  </div>
</section>
```

An optional button per tour of the PR (`tours` in the overlay) fits here:
`<button type="button" class="tag c-S" data-tour="apple-web"></button>`. Empty, it is
labelled "Take the tour: <name>" and starts that tour on the graph; one naming no tour
of the page is hidden (validate.py warns).

## 4. Changes per PR

One section per PR, in merge order, with `id="pr-<KEY>"` (the merge-order row links to it). It
holds the PR's graph button and nested bullets, then an optional "Look closely" element
(section 5): no lead, no intro, no summary, no file list.

```html
<section id="pr-S" data-toc="PR S · service">
  <h2><span class="tag c-S">S</span> Service layer · #123</h2>
  <p><button type="button" class="tag c-S" data-gopen="S"></button></p>
  <ul class="changes">
    <li>New route <code>GET /services</code> lists a facility's services
      <ul>
        <li>Sorted by name, then deduplicated by id (first one wins)</li>
        <li>An unknown facility returns 404 instead of an empty list; clients that relied on <code>[]</code> break</li>
      </ul>
    </li>
    <li><strong>Behaviour change:</strong> the default page size drops from 50 to 20
      <ul><li>The BFF asks for 20 as well, so no caller sees a difference</li></ul>
    </li>
    <li>Price per service is one price when all variants are equal (<code>200 zł</code>), else "from 180 zł" (<code>libs/x/query.ts:26-95</code>)</li>
  </ul>
</section>
```

Rules for the bullets:

- One bullet per change in behaviour or structure, never one per file.
- Two levels at most; the second level adds detail to the first, it does not start a
  new topic.
- No file lists, intros, or summaries. Give a reason only when it is not obvious from
  the change. A `<code>path:line</code>` marks the one place a reviewer should open,
  not every bullet.
- A behaviour change users or callers will notice (a new default, a removed option,
  another status code or message) starts with `<strong>Behaviour change:</strong>`. It
  is a fact of the PR, not a risk: it becomes a "Decisions for you" card only when the
  owner alone must decide whether to ship it.
- A business rule that changed is a bullet here, with concrete values (the input and
  the result), not a table.
- A file the graph marks as combined by hand in a merge (a `conflict` entry of kind
  `merged`, a ↯ badge) is a bullet only when its resolution matters; name the merge's
  SHA. A `picked` entry needs none.

The empty `data-gopen` button gets the "open on the reading graph" label and switches
the graph to that PR (`data-order="bottom"` opens it in dependency order).

## 5. Before merging

One section, four groups in this order. Leave out a group with nothing in it, except
"Decisions for you": if there are none, say so in one line. Show file links as written in
`<code>path:line</code>`; the viewer displays them as a short name with the line
(`session.php:182`) and puts the full path on hover, so do not shorten them yourself.

```html
<section id="before-merging" data-toc="Before merging">
  <h2>Before merging</h2>

  <h3>Decisions for you</h3>
  <ol class="decisions">
    <li><span class="who tag c-S">S</span>
      <p class="q">Ship the new 404 for an unknown facility now, or behind a flag?</p>
      <p class="rec"><strong>Recommended:</strong> now. Only the web loader calls it and it already hides the section on 404.</p>
      <ul class="alts">
        <li>Behind a flag: no change for callers, but the loader's 404 path stays untested in production.</li>
      </ul>
      <p class="refs"><code>libs/x/infra/monolith.client.ts:12</code></p></li>
    <li><span class="who tag c-A">A</span>
      <p class="q">Is a 3-second timeout acceptable for the item loader?</p>
      <p class="rec none"><strong>No recommendation:</strong> the change map has no latency data for the upstream; it is missing.</p>
      <ul class="alts"><li>3 s: a slow upstream hides the section.</li><li>6 s: the page waits longer.</li></ul></li>
  </ol>

  <h3>Verification</h3>
  <div class="tbl"><table class="verif">
    <thead><tr><th>PR</th><th>Tested SHA</th><th>Tests</th><th>Browser</th><th>Device</th><th>CI</th></tr></thead>
    <tbody>
      <tr><td><span class="tag c-S">S</span></td><td><code>c9e7133</code></td><td class="v-ran">ran</td><td class="v-na">n/a</td><td class="v-na">n/a</td><td class="v-not">not run</td></tr>
    </tbody>
  </table></div>
  <ul class="gaps"><li>CI did not run on any PR (drafts): only local checks cover them.</li></ul>
  <details><summary>Results and counts</summary><div class="body"><ul>
    <li><span class="tag c-S">S</span> Pest 412 passed; lint and types clean.</li>
  </ul></div></details>

  <h3>After merging</h3>
  <ul class="after">
    <li>Rebase B on develop once A has merged; its diff must not change.</li>
  </ul>
</section>
```

- **Decisions for you**: only what the owner alone can decide, a product, risk, or rollout
  trade-off. "Is this code correct?" is not a decision; it goes under "Look closely" (below)
  or becomes a verification gap. Ranked, most consequential first, no padding. Each card:
  - the question as one sentence (the tag is the PR it is about);
  - `Recommended:` with a one-line reason, in `p.rec`. Base it on evidence in the diff or
    the change maps. When the evidence does not support one, write `No recommendation:`
    in `p.rec.none` and name what is missing; never invent a recommendation;
  - the alternatives with their consequence, one line each (`ul.alts`);
  - small code links at the end (`p.refs`).
  The "Add as note" button appears on these cards only.
- **Verification**: one row per PR with the tested short SHA (the PR's tip, as the merge
  order shows it; if the tested commit was not recorded, say so in the details) and columns
  chosen for this report from what matters (Tests, Browser, Simulator, Real device,
  Independent check, CI, …). Every cell is `ran`, `not run`, or `n/a` in a `td` with class
  `v-ran`, `v-not`, or `v-na`: the word carries the meaning, the colour only helps. `n/a`
  means the PR does not touch that surface; a surface it touches that nobody ran is `not run`.
  Under the table list only the gaps that could actually cause harm, one line each. Test
  counts and the full detail go in a collapsed `details`. `refresh.py` warns when the
  narrative still shows an old tip, which is how a stale row shows up.
- **After merging**: a short checklist of required steps after the merge (a rebase, a flag
  or variable to set, a build order). Omit when empty.

State only what was actually run or read. A suite you did not run is `not run`.

### Look closely (inside a PR's section)

Review pointers that are not decisions (a spot where a bug could hide, a contract to check)
go under the owning PR's bullets, in a collapsed element, one line each, ranked, at most
three per PR. Drop the rest instead of padding, and do not repeat what a bullet or a
decision already says.

```html
  <details class="look"><summary>Look closely (1)</summary><ol>
    <li>Fingerprint, TTL, and cleanup decide whether a retry duplicates a command (<code>packages/client-core/src/unconfirmed-product-commands.ts:181</code>).</li>
  </ol></details>
```

```html
<footer>As of <date>. References point at the branch tips in the merge order; hover for the full path.</footer>
```

## Available classes

`panel`, `tag`, `callout warn|risk|ok`, `details > summary + .body`, `steps`,
`decisions` (`q`, `rec`, `rec none`, `alts`, `refs`), `verif` + `v-ran|v-not|v-na`, `gaps`, `after`,
`look`, `risk-list` + `sev-h|sev-m|sev-l` + `who` (older reports), `changes`, `diagram` + `pre.mermaid`,
`pre.code`, `pill ok|warn|risk`, `sub`.
Theme tokens: `--bg --surface --fg --muted --line --soft --accent --accent-ink`,
`--pal-1 … --pal-8`, `--warn-* --risk-* --ok-*`; they switch with the reader's theme
(View › Theme: Auto follows the host page or the system, or Light, or Dark). Write any
inline colour as one of them (`style="color:var(--muted)"`), never as hex or `rgb()`,
so the narrative reads in both themes. Mermaid diagrams are redrawn in mermaid's dark
or default theme when the page turns dark or light (on an Artifact only when the host
exposes its mermaid as `window.mermaid`).
