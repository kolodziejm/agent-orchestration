'use strict';
// After a refresh: notes on code that moved, changed, or went away (moved, stale, file gone, and their actions), the
// "changed since the last version" banner and row badges, read marks cleared only for files that changed, copying notes
// with their states, a second refresh with nothing moved, and the Polish strings. The demo repository is built in this
// suite's own directory: v1, notes and read marks, then the branches move the way a fix round moves them and
// refresh.py rebuilds the page the open tab reloads.
const fs = require('fs');
const path = require('path');
const { sleep } = require('./lib');

const HELPERS = `window.R={
  open:function(pr,p){T.tabTo(pr);var id=T.id(p,pr);T.pick(id);return id;},
  sel:function(p,side,a,b){T.cell(p,side,a).click();if(b!==a)T.cell(p,side,b).dispatchEvent(new MouseEvent('click',{bubbles:true,shiftKey:true}));},
  lineNote:function(pr,p,side,a,b,kind,text){R.open(pr,p);R.sel(p,side,a,b);document.querySelector('#dv-files [data-nt=add]').click();T.save(document.querySelector('#dv-files tr.nt-bar'),kind,text);},
  fileNote:function(pr,p,kind,text){R.open(pr,p);T.df(p).querySelector('.nt-fadd').click();T.save(T.df(p).querySelector('.nt-fed'),kind,text);},
  prNote:function(pr,kind,text){T.tabTo(pr);document.getElementById('nt-pr-add').click();T.save(document.getElementById('nt-pred'),kind,text);},
  read:function(pr,p){R.open(pr,p);T.row(T.id(p,pr)).querySelector('input').click();},
  marks:function(p){var d=T.df(p);return d?[].map.call(d.querySelectorAll('td.ln.nk'),function(td){return td.dataset.s+':'+td.dataset.l;}):null;},
  notes:function(){return [].map.call(document.querySelectorAll('#nt-list li'),function(li){return {st:li.dataset.st,loc:li.querySelector('.nt-loc').textContent,badge:[].map.call(li.querySelectorAll('.nt-st'),function(b){return b.textContent;}).join('|'),text:(li.querySelector('.nt-tx')||{}).textContent,acts:[].map.call(li.querySelectorAll('.nt-acts button'),function(b){return b.textContent;})};});},
  li:function(text){return [].find.call(document.querySelectorAll('#nt-list li'),function(li){var t=li.querySelector('.nt-tx');return t&&t.textContent===text;});},
  act:function(text,label){[].find.call(R.li(text).querySelectorAll('.nt-acts button'),function(b){return b.textContent===label;}).click();}
};true`;
const N = { svc: 'N1 listItems pages from the static list', types: 'N2 Item needs a price', ctrl: 'N3 validate the limit', fmt: 'N4 escape the name',
  legacy: 'N5 old label format', file: 'N6 controller file is fine', pr: 'N7 why two PRs?', web: 'N8 web render' };
const q = JSON.stringify;

module.exports = {
  name: 'refresh',
  weight: 12, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    t.use(HELPERS);
    const demo = t.work, scratch = path.join(demo, 'scratch');
    const URL = t.url(scratch, 'review.html');
    const v1 = await t.fixture('demo-v1', demo);

    /* ---------- v1: notes and read marks on the first version ---------- */
    await t.fresh(URL);
    t.check('v1: no change banner without a previous version', await B.ev(`document.getElementById('g-chg').hidden`));
    await B.ev(`R.lineNote('A','src/service.ts','new',9,12,'issue',${q(N.svc)})`);
    await B.ev(`R.lineNote('A','src/types.ts','new',1,1,'suggestion',${q(N.types)})`);
    await B.ev(`R.lineNote('A','src/controller.ts','new',5,6,'issue',${q(N.ctrl)})`);
    await B.ev(`R.lineNote('A','src/format.ts','new',4,4,'question',${q(N.fmt)})`);
    await B.ev(`R.lineNote('A','src/legacy.ts','old',9,9,'question',${q(N.legacy)})`);
    await B.ev(`R.fileNote('A','src/controller.ts','ok',${q(N.file)})`);
    await B.ev(`R.prNote('A','question',${q(N.pr)})`);
    await B.ev(`R.lineNote('B','web/app.tsx','new',4,4,'suggestion',${q(N.web)})`);
    for (const [pr, p] of [['A', 'src/service.ts'], ['A', 'src/service.spec.ts'], ['A', 'src/legacy.ts'], ['A', 'src/format.ts'], ['B', 'web/app.tsx']]) await B.ev(`R.read('${pr}','${p}')`);
    const s1 = await B.ev(`({n:R.notes(),read:T.stored('read'),rfp:T.stored('readfp')})`);
    t.check('v1: 8 notes saved, all current (no status badge)', s1.n.length === 8 && s1.n.every((x) => x.st === 'ok' && !x.badge), s1.n);
    t.check('v1: read marks stored by PR and path with their fingerprints', Object.keys(s1.read.A).length === 4 && Object.keys(s1.read.B).length === 1 && Object.keys(s1.rfp.A).length === 4 && /^src\/service\.ts=[0-9a-f]{12}$/.test(s1.rfp.A['src/service.ts'].f) && s1.rfp.A['src/service.ts'].g === 0, s1);
    t.noErrors('v1: no page errors');
    await B.ev(`document.getElementById('nt-panel').scrollIntoView()`);
    await t.shot('v1-notes-1440-light', '#nt-panel');

    /* ---------- move the branches, refresh, reload the same tab ---------- */
    const v2 = await t.fixture('demo-move', demo);
    const out = await t.skill('refresh.py', scratch);
    t.check('refresh: prints old -> new tips, the change counts, and the narrative lines with old tips', out.includes(`PR A: ${v1.A} -> ${v2.A}`) && /changed since the previous version: 5 files \(1 new, 3 changed, 1 removed\)/.test(out) && out.includes(`still shows its old tip ${v1.A} at narrative.html:4`) && /OK/.test(out), out);
    await t.reload(URL);
    const n2 = await B.ev(`R.notes()`);
    const by = Object.fromEntries(n2.map((x) => [x.text, x]));
    t.check('v2: every note kept (8)', n2.length === 8, n2);
    t.check('v2: line note whose lines shifted is "moved" to the new lines (exact)', by[N.svc].st === 'moved' && /service\.ts:13-16/.test(by[N.svc].loc) && by[N.svc].badge === 'moved from :9–12', by[N.svc]);
    t.check('v2: a shifted line with a small edit is "moved, code changed slightly"', by[N.types].st === 'moved' && /types\.ts:2 /.test(by[N.types].loc) && /changed slightly/.test(by[N.types].badge), by[N.types]);
    t.check('v2: lines edited in place are "stale"', by[N.ctrl].st === 'stale' && /controller\.ts:5-6/.test(by[N.ctrl].loc) && /stale/.test(by[N.ctrl].badge), by[N.ctrl]);
    t.check('v2: a note on a removed file is "file gone"', by[N.fmt].st === 'gone' && /gone/.test(by[N.fmt].badge), by[N.fmt]);
    t.check('v2: an old-side note relocates on the old side (base moved by 3 lines)', by[N.legacy].st === 'moved' && /legacy\.ts:12 · old/.test(by[N.legacy].loc), by[N.legacy]);
    t.check('v2: file, PR, and unchanged-file notes stay current', [N.file, N.pr, N.web].every((x) => by[x].st === 'ok' && !by[x].badge), [N.file, N.pr, N.web].map((x) => by[x]));
    t.check('v2: actions: moved = accept/re-anchor/dismiss, stale = re-anchor/dismiss, gone = re-anchor/dismiss, ok = edit/delete only',
      q(by[N.svc].acts) === '["Accept new location","Re-anchor to selection","Dismiss","Edit","Delete"]' && q(by[N.ctrl].acts) === '["Re-anchor to selection","Dismiss","Edit","Delete"]'
      && q(by[N.fmt].acts) === '["Re-anchor to selection","Dismiss","Edit","Delete"]' && q(by[N.file].acts) === '["Edit","Delete"]', n2.map((x) => x.acts));
    const panel = await B.ev(`({chip:document.querySelector('#nt-filter .st-changed').textContent,dis:document.querySelector('#nt-filter .st-dismissed').hidden,callout:document.getElementById('nt-chg').textContent,count:document.getElementById('nt-count').textContent})`);
    t.check('v2: "Code changed" filter chip counts 5, a callout explains the states, no Dismissed chip yet', panel.chip === '⚠ Code changed 5' && panel.dis && /5 \(moved 3, stale 1, file gone 1\)/.test(panel.callout) && panel.count === '8', panel);
    await B.ev(`R.open('A','src/service.ts')`);
    const mk = await B.ev(`R.marks('src/service.ts')`);
    t.check('v2: the moved note marks its new lines (13-16), not the old ones', q(mk) === q(['new:13', 'new:14', 'new:15', 'new:16']), mk);
    await B.ev(`R.open('A','src/types.ts')`);
    t.check('v2: the fuzzy-moved note marks new line 2', q(await B.ev(`R.marks('src/types.ts')`)) === '["new:2"]', await B.ev(`R.marks('src/types.ts')`));
    await B.ev(`R.open('A','src/legacy.ts')`);
    t.check('v2: the old-side note marks old line 12', q(await B.ev(`R.marks('src/legacy.ts')`)) === '["old:12"]', await B.ev(`R.marks('src/legacy.ts')`));
    await B.ev(`R.open('A','src/controller.ts')`);
    const ct = await B.ev(`({m:R.marks('src/controller.ts'),file:(T.df('src/controller.ts').querySelector('.nt-fk-slot .nt-k')||{}).textContent})`);
    t.check('v2: the stale note has no line marker; the file note still shows in the header', ct.m.length === 0 && ct.file === '✓ 1', ct);
    // Jump: moved goes to new lines, stale opens the file, gone says so.
    await B.ev(`R.li(${q(N.svc)}).querySelector('.nt-loc').click()`); await sleep(250);
    t.check('jump: a moved note focuses its new first line', await B.ev(`document.activeElement.matches('td.ln[data-s=new][data-l="13"]')&&T.df('src/service.ts')!==undefined`));
    await B.ev(`R.li(${q(N.ctrl)}).querySelector('.nt-loc').click()`); await sleep(250);
    t.check('jump: a stale note opens its file and says the code changed', await B.ev(`document.activeElement.matches('#dv-files summary')&&/changed/.test(document.getElementById('nt-status').textContent)`), await B.ev(`[document.activeElement.outerHTML.slice(0,60),document.getElementById('nt-status').textContent]`));
    await B.ev(`R.li(${q(N.fmt)}).querySelector('.nt-loc').click()`); await sleep(100);
    t.check('jump: a gone note says the PR no longer changes its file', /no longer changes/.test(await B.ev(`document.getElementById('nt-status').textContent`)));
    // Copy with statuses.
    const md = await t.copy();
    t.check('copy: moved note heading names its new place and "moved from :9-12"', md.includes('`src/service.ts:13-16` · new (PR) · moved from :9-12\n'), md);
    t.check('copy: fuzzy move says the code changed slightly', md.includes('`src/types.ts:2` · new (PR) · moved from :1; the code changed slightly since the note'), md);
    t.check('copy: stale note says so and labels its code block as the code when written', /`src\/controller\.ts:5-6` · new \(PR\) · stale: code changed since the note\n\nCode when the note was written:\n\n```typescript\n  const offset = Number/.test(md), md);
    t.check('copy: gone note says the file is gone; the old-side move names the old side', md.includes('`src/format.ts:4` · new (PR) · file gone: the PR no longer changes this file') && md.includes('`src/legacy.ts:12` · old (base) · moved from :9'), md);
    t.check('copy: a paragraph explains the states for the agent; current notes have no suffix', md.includes('Some notes were written on an earlier version of the PR.') && md.includes('`src/controller.ts` · whole file\n') && md.includes('`web/app.tsx:4` · new (PR)\n'), md);

    /* ---------- banner, badges, read marks ---------- */
    await B.ev(`T.tabTo('A')`);
    const bn = await B.ev(`({text:document.getElementById('g-chg').innerText,cls:document.getElementById('g-chg').className,removed:[].map.call(document.querySelectorAll('#g-chg details li'),function(l){return l.textContent;})})`);
    t.check('banner: "5 files (1 new, 3 changed, 1 removed)", tips old -> new for both PRs', /Changed since the last version: 5 files \(1 new, 3 changed, 1 removed\)/.test(bn.text) && bn.text.includes(`A #1 ${v1.A} → ${v2.A}`) && bn.text.includes(`B #2 ${v1.B} → ${v2.B}`) && /warn/.test(bn.cls), bn.text);
    t.check('banner: removed file listed; read-before-changed list present', bn.removed.includes('A #1 · src/format.ts') && bn.removed.some((x) => /src\/service\.ts/.test(x)), bn.removed);
    const rowBy = Object.fromEntries((await B.ev(`T.rows().map(function(r){r.path=T.data().prs[0].nodes.find(function(n){return n.id===r.id;}).path;return r;})`)).map((r) => [r.path, r]));
    t.check('badges: new on cache.ts, changed on controller/service/types, none on legacy/spec', rowBy['src/cache.ts'].badge === 'new' && ['src/controller.ts', 'src/service.ts', 'src/types.ts'].every((p) => rowBy[p].badge === 'changed') && !rowBy['src/legacy.ts'].badge && !rowBy['src/service.spec.ts'].badge, rowBy);
    t.check('read marks: cleared only for the changed file (service.ts, marked ↻), kept for legacy.ts (base moved, same change) and service.spec.ts', !rowBy['src/service.ts'].done && rowBy['src/service.ts'].was && /↻/.test(rowBy['src/service.ts'].ix) && rowBy['src/legacy.ts'].done && rowBy['src/service.spec.ts'].done && !rowBy['src/legacy.ts'].was, rowBy);
    await B.ev(`R.open('A','src/controller.ts');[].forEach.call(document.querySelectorAll('#g-chg details'),function(d){d.open=true;});document.querySelector('.g-work').scrollIntoView()`); await sleep(200);
    await t.shot('v2-1440-light-badges-wasread', '.g-work', 700);
    await t.theme(true); await sleep(200);
    await t.shot('v2-1440-dark-badges-wasread', '.g-work', 700);
    await t.theme(false); await sleep(100);
    const stB = await B.ev(`(T.tabTo('B'),T.rows())`);
    t.check('read marks: PR B (new tip, same diff) keeps its mark and has no badges', stB.find((r) => r.done) && stB.every((r) => !r.badge), stB);
    const st = await B.ev(`({read:T.stored('read'),was:T.stored('wasread')})`);
    t.check('read marks: storage keeps the removed file\'s mark and remembers the cleared one under "wasread"', st.read.A['src/format.ts'] === 1 && !st.read.A['src/service.ts'] && /^src\/service\.ts=/.test(st.was.A['src/service.ts']), st);
    await B.ev(`T.tabTo('A');T.row(T.id('src/service.ts','A')).querySelector('input').click()`);
    const re = await B.ev(`({row:T.rows().find(function(r){return r.id===T.id('src/service.ts','A');}),was:T.stored('wasread'),banner:document.getElementById('g-chg').innerText})`);
    t.check('read marks: marking it read again drops the ↻ and the "read before" entry', re.row.done && !re.row.was && !(re.was.A && re.was.A['src/service.ts']) && !/Read before/.test(re.banner), re);
    await t.reload(URL);
    t.check('read marks: a reload does not clear the new mark (fingerprint matches)', await B.ev(`(T.tabTo('A'),T.rows().find(function(r){return r.id===T.id('src/service.ts','A');}).done)`));
    // Only changed files.
    await B.ev(`document.getElementById('g-changed').click()`);
    const oc = await B.ev(`T.rows().map(function(r){return r.no+':'+r.badge;})`);
    t.check('"Only changed files" leaves the 4 new/changed rows and keeps their step numbers', oc.length === 4 && oc.every((x) => /:(new|changed)$/.test(x)) && oc.map((x) => +x.split(':')[0]).some((n) => n > 4), oc);
    await B.ev(`R.li(${q(N.legacy)}).querySelector('.nt-loc').click()`); await sleep(200);
    t.check('a note jump to an unchanged file turns "Only changed files" off', await B.ev(`!document.getElementById('g-changed').checked&&T.rows().length===6`));
    t.noErrors('banner, badges, marks: no page errors');

    /* ---------- layout: 1440 and 800, light and dark ---------- */
    for (const [w, h] of [[1440, 900], [800, 1000]]) {
      for (const dark of [false, true]) {
        const th = dark ? 'dark' : 'light';
        await B.viewport(w, h, dark);
        await t.reload(URL);
        await B.ev(`T.tabTo('A');R.open('A','src/service.ts');[].forEach.call(document.querySelectorAll('#g-chg details'),function(d){d.open=true;});document.getElementById('graph').scrollIntoView()`);
        await sleep(250);
        t.check(`${w} ${th}: no horizontal page scroll`, await B.ev('T.hscroll()') <= 0, await B.ev('T.hscroll()'));
        await t.shot(`v2-${w}-${th}-banner-list`);
        await B.ev(`document.getElementById('nt-panel').scrollIntoView()`); await sleep(150);
        await t.shot(`v2-${w}-${th}-notes`, '#nt-panel', 1400);
        await B.ev(`T.df('src/service.ts').scrollIntoView({block:'start'})`); await sleep(150);
        await t.shot(`v2-${w}-${th}-moved-marker`, '#dv', 900);
        t.noErrors(`${w} ${th}: no page errors`);
      }
    }
    await B.viewport(1440, 900, false);
    await t.reload(URL);

    /* ---------- actions ---------- */
    await B.ev(`R.act(${q(N.svc)},'Accept new location')`);
    const ac = await B.ev(`({n:R.notes().find(function(x){return x.text===${q(N.svc)};}),s:T.stored('notes').find(function(x){return x.text===${q(N.svc)};}),focus:document.activeElement.className})`);
    t.check('accept: the note now anchors at 13-16 with the code there, no badge, stored', ac.n.st === 'ok' && !ac.n.badge && ac.s.a === 13 && ac.s.b === 16 && ac.s.code[0].startsWith('export function listItems') && ac.focus === 'nt-loc', ac);
    await B.ev(`R.act(${q(N.ctrl)},'Re-anchor to selection')`);
    t.check('re-anchor without a selection explains how', /Select lines in a diff first/.test(await B.ev(`document.getElementById('nt-status').textContent`)));
    await B.ev(`R.open('A','src/controller.ts');R.sel('src/controller.ts','new',4,5)`);
    t.check('re-anchor tooltip names the selected lines', /Move this note to src\/controller\.ts · new \(PR\), lines 4–5/.test(await B.ev(`[].find.call(R.li(${q(N.ctrl)}).querySelectorAll('button'),function(b){return b.dataset.a==='reanchor';}).title`)));
    await B.ev(`R.act(${q(N.ctrl)},'Re-anchor to selection')`);
    const ra = await B.ev(`({n:R.notes().find(function(x){return x.text===${q(N.ctrl)};}),m:R.marks('src/controller.ts'),sel:!!document.querySelector('#dv-files td.ls')})`);
    t.check('re-anchor: the stale note moves to the selection (4-5), is current, marks the lines; the selection clears', ra.n.st === 'ok' && /controller\.ts:4-5/.test(ra.n.loc) && q(ra.m) === '["new:4","new:5"]' && !ra.sel, ra);
    await B.ev(`R.act(${q(N.fmt)},'Dismiss')`);
    const ds = await B.ev(`({n:R.notes().length,has:!!R.li(${q(N.fmt)}),chip:document.querySelector('#nt-filter .st-dismissed').textContent,hidden:document.querySelector('#nt-filter .st-dismissed').hidden,count:document.getElementById('nt-count').textContent,stored:T.stored('notes').find(function(x){return x.text===${q(N.fmt)};})})`);
    t.check('dismiss: the note leaves the list but stays stored; a Dismissed chip appears; the count drops', ds.n === 7 && !ds.has && !ds.hidden && ds.chip === 'Dismissed 1' && ds.count === '7' && ds.stored && ds.stored.dismissed > 0, ds);
    const md2 = await t.copy();
    t.check('copy leaves dismissed notes out by default', !md2.includes('src/format.ts') && md2.includes('Notes: 7'), md2.slice(0, 300));
    await B.ev(`document.querySelector('#nt-filter .st-dismissed').click()`);
    const dl = await B.ev(`R.notes()`);
    t.check('Dismissed filter shows just the dismissed note with Restore', dl.length === 1 && dl[0].st === 'dismissed' && dl[0].badge === 'dismissed|file gone from the PR' && dl[0].acts[0] === 'Restore', dl);
    const md3 = await t.copy();
    t.check('copying the dismissed view says so and marks the note', md3.includes('Only dismissed notes were copied.') && md3.includes('file gone: the PR no longer changes this file · dismissed by the reviewer'), md3);
    await B.ev(`R.act(${q(N.fmt)},'Restore')`);
    t.check('restore brings it back', await B.ev(`(document.querySelector('#nt-filter .st-dismissed').hidden&&R.notes().length===8)`) || await B.ev(`(document.querySelector('#nt-filter .st-dismissed').click(),R.notes().length===8)`));
    await B.ev(`document.querySelector('#nt-filter .st-changed').click()`);
    const cf = await B.ev(`({n:R.notes().map(function(x){return x.st;}),copy:document.getElementById('nt-copy').textContent})`);
    t.check('"Code changed" filter shows only the remaining changed notes (types moved, legacy moved, format gone)', q(cf.n.sort()) === '["gone","moved","moved"]' && cf.copy === 'Copy shown notes (3)', cf);
    await t.reload(URL);
    const rl = await B.ev(`R.notes().map(function(x){return x.st;})`);
    t.check('after a reload: accepted and re-anchored notes stay current, the rest keep their states', rl.filter((s) => s === 'ok').length === 5 && rl.filter((s) => s === 'moved').length === 2 && rl.includes('gone'), rl);
    t.noErrors('actions: no page errors');

    /* ---------- a second refresh with nothing moved keeps the comparison ---------- */
    const before = fs.readFileSync(path.join(scratch, 'review.html'), 'utf8');
    const out2 = await t.skill('refresh.py', scratch);
    t.check('refresh again with nothing moved: same page bytes, comparison kept', /nothing changed since the last build/.test(out2) && fs.readFileSync(path.join(scratch, 'review.html'), 'utf8') === before, out2);

    /* ---------- Polish page: same storage key, same notes ---------- */
    const s = scratch;
    await t.skill('assemble.py', '--graph', path.join(s, 'graphs.json'), '--diffs', path.join(s, 'diffs.json'), '--narrative', path.join(s, 'narrative.html'),
      '--title', 'Refresh demo', '--lang', 'pl', '--target', 'local', '--previous', path.join(s, 'previous.json'), '--out', path.join(s, 'review-pl.html'), '--no-manifest');
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await B.viewport(1440, 900, dark);
      await t.reload(t.url(s, 'review-pl.html'));
      await B.ev(`[].forEach.call(document.querySelectorAll('#g-chg details'),function(d){d.open=true;});document.getElementById('graph').scrollIntoView()`); await sleep(200);
      const pl = await B.ev(`({b:document.getElementById('g-chg').innerText,chip:document.querySelector('#nt-filter .st-changed').textContent,badges:[].map.call(document.querySelectorAll('#nt-list .nt-st'),function(x){return x.textContent;})})`);
      t.check(`pl ${th}: banner, chip, and badges in Polish`, /Zmiany od poprzedniej wersji: 5 plików \(nowe: 1, zmienione: 3, usunięte z PR-a: 1\)/.test(pl.b) && pl.chip === '⚠ Zmieniony kod 3' && pl.badges.includes('pliku nie ma już w PR-ze'), pl);
      await t.shot(`v2-pl-1440-${th}`);
      t.noErrors(`pl ${th}: no page errors`);
    }
  },
};
