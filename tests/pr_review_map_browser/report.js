'use strict';
// The marks of files resolved by hand in a merge (row chip, detail line with its command, map mark), the lead's folded
// legend, the View menu, and the narrative's code references and "Add as note" on risks: on the two-PR sample in
// light and dark, its Polish page, a report without conflicts (stack), and markup in the conflict fields (sec).
const fs = require('fs');
const path = require('path');
const { sleep } = require('./lib');

module.exports = {
  name: 'report',
  weight: 8, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const PLAN = t.url(t.fixtures, 'plan', 'review.html'), PL = t.url(t.fixtures, 'plan', 'review-pl.html'), STACK = t.url(t.fixtures, 'stack', 'review.html');
    let strings = null, data = null;

    /* ---------- The sample loads without errors in both themes; its strings and data are read once ---------- */
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(PLAN, { dark });
      t.noErrors(`report ${th}: no page errors on load`);
      if (!strings) { strings = JSON.parse(await B.ev(`document.getElementById('review-config').textContent`)).strings; data = await B.ev('T.data()'); }
    }
    await t.fresh(PLAN);
    const steps = Object.fromEntries((await B.ev('T.rows()')).map((r) => [r.id, r.no]));
    const P = data.prs[0], pid = (p) => P.nodes.find((n) => n.path === p).id;

    /* ---------- Conflicts: row chip, detail line and command, map mark ---------- */
    const chips = await B.ev(`[].map.call(document.querySelectorAll('#g-order .g-cfb'),function(c){return [c.closest('li').dataset.id,c.title,c.getAttribute('aria-label')];})`);
    t.check('conflict: a chip on exactly the rows of files combined by hand (not one where a merge took one side), its title naming those merges', JSON.stringify(chips) === JSON.stringify([
      [pid('src/billing/invoice.ts'), 'Resolved by hand in merge 0badc0d1', 'Resolved by hand in merge 0badc0d1'],
      [pid('src/auth/session.ts'), 'Resolved by hand in merge abc1234', 'Resolved by hand in merge abc1234']].sort((a, b) => steps[a[0]] - steps[b[0]])), chips);
    await B.ev(`T.pick('${pid('src/auth/session.ts')}')`); await sleep(100);
    const det = await B.ev(`[].map.call(document.querySelectorAll('#g-detail .g-cf'),function(d){return [d.firstChild.textContent,d.querySelector('code').textContent,d.querySelector('button').getAttribute('aria-label'),(d.querySelector('.cl')||{}).textContent,d.classList.contains('pk'),getComputedStyle(d).backgroundColor,d.title];})`);
    t.check('conflict: the detail panel lists every resolution with its lines and remerge-diff command, the one that took a side dimmed', JSON.stringify(det.map((d) => d.slice(0, 2).concat(d.slice(3, 5)))) === JSON.stringify([
      ['↯ Resolved by hand in merge abc1234', 'git show --remerge-diff abc1234 -- src/auth/session.ts', '12 lines in the resolution', false],
      ['⇢ Took one side in merge def5678', 'git show --remerge-diff def5678 -- src/auth/session.ts', '4 lines in the resolution', true]])
      && det[0][2] === 'Copy the command git show --remerge-diff abc1234 -- src/auth/session.ts' && det[0][5] !== det[1][5]
      && det[0][6] === strings.conflictMergedTitle && det[1][6] === strings.conflictPickedTitle, det);
    await B.ev(`T.pick('${pid('src/auth/token.ts')}')`); await sleep(60);
    const tok = await B.ev(`({cf:[].map.call(document.querySelectorAll('#g-detail .g-cf'),function(d){return d.firstChild.textContent+'|'+d.classList.contains('pk');}),chip:!!T.row('${pid('src/auth/token.ts')}').querySelector('.g-cfb')})`);
    t.check('conflict: a file a merge only took one side of has no chip but its panel lists the merge, dimmed', JSON.stringify(tok) === JSON.stringify({ cf: ['⇢ Took one side in merge abc1234|true'], chip: false }), tok);
    await B.ev(`T.pick('${pid('src/auth/session.ts')}')`); await sleep(60);
    const copied = await B.ev(`new Promise(function(r){window.__c=null;navigator.clipboard.writeText=function(x){window.__c=x;return Promise.resolve();};document.querySelector('#g-detail .g-cf button').click();setTimeout(function(){r({c:window.__c,st:document.getElementById('nt-status').textContent});},100);})`);
    t.check('conflict: "Copy" puts the command on the clipboard and says so', copied.c === 'git show --remerge-diff abc1234 -- src/auth/session.ts' && copied.st === strings.conflictCopied, copied);
    // The command quotes a glob (a shell would expand it) and names no pathspec for a list of files: the same page with two nodes' paths replaced.
    const html = fs.readFileSync(PLAN.replace(/^file:\/\//, ''), 'utf8'), at = html.indexOf('id="graph-data">'), end = html.indexOf('</script>', at);
    const gd = JSON.parse(html.slice(html.indexOf('>', at) + 1, end)), P0 = gd.prs[0];
    const tweak = (path, to) => { const n = P0.nodes.find((x) => x.path === path); n.path = to; n.conflict = ['abc1234']; return n.id; };
    const gid = tweak('src/auth/token.ts', 'locales/*.json'), lid = tweak('src/auth/index.ts', 'a.json, b.json, c.json, …'), qid = tweak('src/billing/index.ts', "docs/it's [a] $x.md");
    const GLOB = path.join(t.work, 'glob.html');
    fs.writeFileSync(GLOB, html.slice(0, html.indexOf('>', at) + 1) + JSON.stringify(gd).replace(/</g, '\\u003c') + html.slice(end));
    await t.fresh(t.url(GLOB));
    const cmdOf = async (id) => { await B.ev(`T.pick('${id}')`); await sleep(60); return B.ev(`(document.querySelector('#g-detail .g-cf code')||{}).textContent`); };
    const cmds = [await cmdOf(gid), await cmdOf(lid), await cmdOf(qid)];
    t.check('conflict: a glob path is single-quoted in the command, a list of files gets no pathspec, odd characters are quoted', JSON.stringify(cmds) === JSON.stringify([
      "git show --remerge-diff abc1234 -- 'locales/*.json'", 'git show --remerge-diff abc1234', "git show --remerge-diff abc1234 -- 'docs/it'\\''s [a] $x.md'"]), cmds);
    t.noErrors('conflict commands: no page errors');

    await t.fresh(PLAN);
    await B.ev(`T.pick('${pid('src/util/fmt.ts')}')`);
    t.check('conflict: a file without conflicts has no conflict line', await B.ev(`document.querySelectorAll('#g-detail .g-cf').length`) === 0);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(200);
    const mk = await B.ev(`[].map.call(document.querySelectorAll('#g-canvas .nd'),function(g){return {p:g.querySelector('title').textContent.split('\\n')[0],m:!!g.querySelector('.cfm'),a:g.getAttribute('aria-label')};}).filter(function(x){return x.m;})`);
    t.check('conflict: the map marks the same two files, and their names say why', JSON.stringify(mk.map((x) => x.p).sort()) === '["src/auth/session.ts","src/billing/invoice.ts"]' && mk.every((x) => /Resolved by hand in merge/.test(x.a)), mk);
    await B.ev(`document.getElementById('g-canvas').scrollIntoView()`); await sleep(100);
    await t.shot('plan-1440-light-map-conflicts', '#g-canvas');
    await B.ev(`document.querySelector('[data-v=list]').click()`);
    t.noErrors('conflicts: no page errors');

    /* ---------- The lead: one sentence, the rest folded under "Legend and shortcuts"; the colour hint in the legend ---------- */
    const lead = await B.ev(`({lead:document.querySelector('#graph>.lead').textContent,open:document.getElementById('g-more').open,sum:document.querySelector('#g-more>summary').textContent,
      items:[].map.call(document.querySelectorAll('#g-more li'),function(li){return li.textContent;}),hint:(document.querySelector('#g-legend .g-hint')||{}).textContent,tools:document.querySelector('.g-tools').textContent})`);
    t.check('lead: one sentence, with the legend folded under it', lead.lead === strings.graphLead && lead.lead.split(/[.!?]\s/).length === 1 && !lead.open && lead.sum === strings.graphMore, lead);
    t.check('lead: the folded legend keeps the facts (orders, shared dependencies, map, overview, keys)', lead.items.length === 8 && ['graphMoreList', 'graphMoreOrder', 'graphMoreShared', 'graphMoreView', 'graphMoreMap', 'graphMoreAreas', 'graphMoreRefs', 'graphMoreKeys'].every((k, i) => lead.items[i] === strings[k])
      && /1\.25/.test(lead.items[2]) && /HTTP/.test(lead.items[4]) && /40 core files/.test(lead.items[5]) && /Ctrl\+wheel/.test(lead.items[5]), lead.items);
    t.check('lead: the colour hint sits in the legend, not the toolbar', /blue are its dependencies/.test(lead.hint) && !/blue are its/.test(lead.tools), lead);

    /* ---------- The View menu: a disclosure that holds the toggles, closed by Esc, a click outside, or leaving it ---------- */
    const menu = `({exp:document.getElementById('g-mbtn').getAttribute('aria-expanded'),hidden:document.getElementById('g-mpop').hidden,shown:!!document.getElementById('g-mpop').offsetParent,
      inMenu:['g-path','g-all','g-group','g-area','g-tests','g-ext'].every(function(i){return !!document.getElementById(i).closest('#g-mpop');}),active:document.activeElement&&document.activeElement.id})`;
    let m = await B.ev(menu);
    t.check('menu: closed at first, the six toggles inside it', m.exp === 'false' && m.hidden && !m.shown && m.inMenu, m);
    await B.ev(`document.getElementById('g-mbtn').focus();document.getElementById('g-mbtn').click()`);
    m = await B.ev(menu);
    t.check('menu: the button opens it and says so', m.exp === 'true' && !m.hidden && m.shown, m);
    await B.key('Tab');
    t.check('menu: Tab from the button walks into it ("Reading path" is hidden in the list view)', await B.ev(`document.activeElement.id`) === 'g-all' && await B.ev(`document.getElementById('g-pathl').hidden`));
    const before = (await B.ev('T.rows()')).length;
    await B.ev(`document.getElementById('g-tests').click()`);
    const after = (await B.ev('T.rows()')).length;
    t.check('menu: a toggle inside it still works (tests hidden) and leaves it open', after < before && !(await B.ev(menu)).hidden, { before, after });
    await B.ev(`document.getElementById('g-tests').click()`);
    await B.ev(`document.getElementById('g-tests').focus()`);
    await B.key('Escape');
    m = await B.ev(menu);
    t.check('menu: Esc closes it and gives the focus back to its button', m.hidden && m.exp === 'false' && m.active === 'g-mbtn', m);
    await B.ev(`document.getElementById('g-mbtn').click()`);
    await B.ev(`document.querySelector('header h1').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))`);
    t.check('menu: a click outside closes it', (await B.ev(menu)).hidden);
    await B.ev(`document.getElementById('g-mbtn').click();document.getElementById('g-ext').focus();document.getElementById('g-prev').focus()`);
    t.check('menu: the focus leaving it closes it', (await B.ev(menu)).hidden);
    await B.ev(`document.querySelector('[data-v=map]').click();document.getElementById('g-mbtn').click()`);
    t.check('menu: "Reading path" shows with the map', !(await B.ev(`document.getElementById('g-pathl').hidden`)) && await B.ev(`!!document.getElementById('g-pathl').offsetParent`));
    await B.ev(`document.getElementById('g-path').click()`); await sleep(100);
    t.check('menu: "Reading path" still draws the path', await B.ev(`!!document.querySelector('#g-canvas path.rp')`));
    await B.ev(`document.getElementById('g-path').click();document.querySelector('[data-v=list]').click();document.getElementById('g-mbtn').click()`);
    t.noErrors('menu: no page errors');

    /* ---------- Code references in the narrative ---------- */
    await t.fresh(PLAN);
    const refs = await B.ev(`[].map.call(document.querySelectorAll('#risks code'),function(c){return [c.textContent,!!c.closest('button.g-ref'),(c.closest('button.g-ref')||{}).title||'',c.title];})`);
    const want = { 'session.ts:40': 1, 'invoice.ts:3-4': 1, ':8': 1, 'session.ts:2': 1, 'nowhere.ts:5': 0, 'index.ts:1': 0, '12:30': 0, 'token.ts:10-12': 1, 'app.ts:1': 1, 'web/app.ts:2': 0 };
    t.check('refs: path:line, path:start-end, a unique file name, and a continuation become buttons; unknown, ambiguous, linked, and pre code stays plain',
      refs.length === 11 && refs.every(([c, b], i) => (i === 10 ? !b : b === !!want[c])) && refs[1][2] === 'Show src/billing/invoice.ts:3-4 in the diff' && refs[2][2] === 'Show src/billing/invoice.ts:8 in the diff', refs);
    // Requirement: a reference shows as its short name and line, and the full path is on hover (the code's title).
    t.check('refs: a path shows as its file name and line, with the full path on hover', refs[0][0] === 'session.ts:40' && refs[0][3] === 'src/auth/session.ts' && refs[1][3] === 'src/billing/invoice.ts', refs.slice(0, 3));
    const refAt = (text) => `[].find.call(document.querySelectorAll('#risks button.g-ref'),function(b){return b.textContent===${JSON.stringify(text)};})`;
    const after1 = async (text) => { await B.ev(`${refAt(text)}.click()`); await sleep(250); return B.ev(`({tab:T.tab(),sel:T.sel(),act:document.activeElement.outerHTML.slice(0,90),nf:document.activeElement.classList.contains('nf'),miss:(document.querySelector('#dv-files .g-refmiss')||{}).textContent||null,top:document.activeElement.getBoundingClientRect().top,vh:innerHeight})`); };
    let r = await after1('session.ts:40');
    t.check('refs: a click opens the file on its tab, focuses the line, and flashes it in view', r.tab === 'P' && r.sel === pid('src/auth/session.ts') && /data-s="new" data-l="40"/.test(r.act) && r.nf && !r.miss && r.top > 0 && r.top < r.vh, r);
    await B.ev(`T.tabTo('Q')`);
    r = await after1('invoice.ts:3-4');
    t.check('refs: a file name alone opens its file (from another tab) at the first line of the range', r.tab === 'P' && r.sel === pid('src/billing/invoice.ts') && /data-l="3"/.test(r.act) && r.nf, r);
    r = await after1(':8');
    t.check('refs: a continuation opens the same file at its line', r.sel === pid('src/billing/invoice.ts') && /data-l="8"/.test(r.act), r);
    r = await after1('session.ts:2');
    t.check('refs: a line outside the diff opens the file and says so', r.sel === pid('src/auth/session.ts') && /<summary/.test(r.act) && r.miss === 'Line 2 is outside the shown hunks of src/auth/session.ts; the file is open.'
      && await B.ev(`document.getElementById('nt-live').textContent`) === r.miss, r);
    r = await after1('app.ts:1');
    t.check('refs: a file of the later PR opens on its tab, and the outside-the-diff note is gone', r.tab === 'Q' && r.sel === data.prs[1].nodes.find((n) => n.path === 'web/app.ts').id && /data-l="1"/.test(r.act) && !r.miss, r);
    t.noErrors('refs: no page errors');

    /* ---------- "Add as note" on each risk ---------- */
    const add = async (i) => { await B.ev(`document.querySelectorAll('#risks .risk-list>li')[${i}].querySelector('.g-radd').click()`); await sleep(60);
      return B.ev(`({notes:T.stored('notes'),status:document.getElementById('nt-status').textContent,count:document.getElementById('nt-count').textContent,btn:document.querySelectorAll('#risks .g-radd')[${i}].textContent})`); };
    t.check('risk notes: one button per risk, named with the item', JSON.stringify(await B.ev(`[].map.call(document.querySelectorAll('#risks .g-radd'),function(b){return b.textContent;})`)) === JSON.stringify(Array(4).fill('Add as note'))
      && /^Add as note: Token lifetime\. The TTL moved: src\/auth\/session\.ts:40\.$/.test(await B.ev(`document.querySelector('#risks .g-radd').getAttribute('aria-label')`)));
    let s = await add(0);
    let n = s.notes[s.notes.length - 1];
    t.check('risk notes: one reference inside the diff makes an issue on its lines, with the item\'s text', s.notes.length === 1 && n.scope === 'line' && n.kind === 'issue' && n.pr === 'P' && n.path === 'src/auth/session.ts'
      && n.side === 'new' && n.a === 40 && n.b === 40 && JSON.stringify(n.code) === '["export const s40 = 4000;"]' && n.text === 'Token lifetime. The TTL moved: src/auth/session.ts:40.', n);
    t.check('risk notes: it confirms in the status and the live region, and on the button', s.status === 'Note added (Issue): src/auth/session.ts:40 · new (PR).' && s.count === '1' && s.btn === 'Added ✓'
      && await B.ev(`new Promise(function(r){setTimeout(function(){r(document.getElementById('nt-live').textContent);},80);})`) === s.status, s);
    s = await add(0);
    t.check('risk notes: the same item twice is not added again', s.notes.length === 1 && s.status === 'This item is already a note: src/auth/session.ts:40 · new (PR).', s);
    s = await add(1); n = s.notes[s.notes.length - 1];
    t.check('risk notes: two references make a note on the PR', s.notes.length === 2 && n.scope === 'pr' && n.pr === 'P' && n.kind === 'issue' && n.text === 'Rounding. See invoice.ts:3-4 and :8.' && s.status === 'Note added (Issue): P #11 · whole PR.', n);
    s = await add(2); n = s.notes[s.notes.length - 1];
    t.check('risk notes: one reference outside the diff makes a note on its file', n.scope === 'file' && n.pr === 'P' && n.path === 'src/auth/session.ts' && n.kind === 'issue', n);
    s = await add(3); n = s.notes[s.notes.length - 1];
    t.check('risk notes: no reference makes a note on the item\'s PR (its tag)', n.scope === 'pr' && n.pr === 'Q' && /^No references\./.test(n.text) && s.count === '4', n);
    await B.ev(`T.tabTo('P');T.pick('${pid('src/auth/session.ts')}')`); await sleep(150);
    t.check('risk notes: the line note marks its line and the row', await B.ev(`!!document.querySelector('#dv-files td.ln.nk.k-issue[data-l="40"]')&&!!T.row('${pid('src/auth/session.ts')}').querySelector('.g-nk.k-issue')`));
    const md = await t.copy();
    t.check('risk notes: they copy like any note', /src\/auth\/session\.ts:40/.test(md) && /## Issue \(4\)/.test(md), md);
    t.noErrors('risk notes: no page errors');

    /* ---------- Polish page ---------- */
    await t.fresh(PL);
    const pl = await B.ev(`({more:document.querySelector('#g-more>summary').textContent,menu:document.getElementById('g-mbtn').textContent,add:document.querySelector('#risks .g-radd').textContent,ws:document.getElementById('g-wsb').title,
      order:document.querySelector('#stack h2').textContent})`);
    t.check('pl: the legend, menu, risk button, workspace button, and merge-order heading are in Polish', pl.more === 'Legenda i skróty'
      && /^Widok/.test(pl.menu) && pl.add === 'Dodaj jako uwagę' && /^Tryb roboczy/.test(pl.ws) && pl.order === 'Kolejność merge', pl);
    await B.ev(`T.pick(T.id('src/auth/session.ts'))`);
    t.check('pl: the conflict line', /^↯ Rozwiązany ręcznie przy merge abc1234$/.test(await B.ev(`document.querySelector('#g-detail .g-cf>span').textContent`)));
    t.noErrors('pl: no page errors');

    /* ---------- A report without conflicts ---------- */
    await t.fresh(STACK);
    t.check('older report: no conflict marks', await B.ev(`document.querySelectorAll('.g-cfb,.g-cf').length`) === 0);
    t.noErrors('older report: no page errors');

    /* ---------- Markup in the new fields stays text ---------- */
    await t.fresh(t.url(t.fixtures, 'sec', 'xss.html'));
    await B.ev(`T.pick(T.rows()[0].id)`);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(100);
    await B.ev(`document.querySelector('[data-v=list]').click()`);
    const x = await B.ev(`({pwn:window.__pwn||null,imgs:document.querySelectorAll('img').length,cf:[].map.call(document.querySelectorAll('#g-detail .g-cf code'),function(c){return c.textContent;}),
      chips:[].map.call(document.querySelectorAll('.g-cfb'),function(c){return c.title;}),ref:(document.querySelector('#risks button.g-ref')||{}).title||null})`);
    t.check('markup: a bogus merge is dropped and the valid one shows as text',
      x.pwn === null && x.imgs === 0 && x.cf.length === 1 && x.cf[0].startsWith('git show --remerge-diff abc1234 -- ')
      && x.chips.every((c) => c === 'Resolved by hand in merge abc1234'), x);
    await B.ev(`document.querySelector('#risks button.g-ref').click()`); await sleep(150);
    await B.ev(`document.querySelector('#risks .g-radd').click()`); await sleep(60);
    const y = await B.ev(`({pwn:window.__pwn||null,imgs:document.querySelectorAll('img').length,note:(T.stored('notes')||[]).slice(-1)[0]})`);
    t.check('markup: a reference to a markup-named file opens it and its risk becomes a note as text', x.ref && y.pwn === null && y.imgs === 0 && y.note && y.note.scope === 'line' && /^Odd name: src\/<img src=x/.test(y.note.text), { x: x.ref, y });
    t.noErrors('markup: no page errors');
  },
};
