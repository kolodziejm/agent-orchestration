'use strict';
// The review plan (one row per area: files, lines, depth with its why, minutes, conflicts; the changed lines by kind),
// the marks of files resolved by hand in a merge (row chip, detail line with its command, map mark), the lead's folded
// legend, the View menu, and the narrative's code references and "Add as note" on risks: on the two-PR plan sample in
// light and dark, its Polish page, a report without the new fields (stack), and markup in the new fields (sec).
const fs = require('fs');
const path = require('path');
const { sleep } = require('./lib');

// The documented reading rates (changed lines an hour read closely, per bucket; logic's added and removed lines apart),
// skimming 4 times faster, tools 0; hours from 90 minutes on.
const RATE = { logic: 400, logicDel: 1500, test: 1500, docs: 2000, i18n: 3000, config: 1000, generated: 0 };
const bucketOf = (n) => (['logic', 'test', 'i18n', 'docs', 'config', 'generated'].includes(n.bucket) ? n.bucket : ['test', 'i18n', 'docs', 'config'].includes(n.layer) ? n.layer : 'logic');
function minutesBy(depth, nodes) {
  const by = {};
  if (depth === 'tool') return by;
  for (const n of nodes) {
    const b = bucketOf(n), a = n.added || 0, d = n.removed || 0;
    const h = b === 'logic' ? a / RATE.logic + d / RATE.logicDel : RATE[b] ? (a + d) / RATE[b] : 0;
    if (h > 0) by[b] = (by[b] || 0) + h * 60 / (depth === 'skim' ? 4 : 1);
  }
  return by;
}
function minutesOf(by) { let m = Object.values(by).reduce((s, x) => s + x, 0); if (!(m > 0)) return 0; m = Math.ceil(m - 1e-9); if (m < 1) m = 1; return m > 5 ? Math.ceil(m / 5) * 5 : m; }
function timeText(m, sep = '.') { if (m < 90) return `${m} min`; let h = m / 60; h = h < 10 ? Math.round(h * 2) / 2 : Math.round(h); return `${String(h).replace('.', sep)} h`; }
const merged = (n) => (n.conflict || []).some((c) => typeof c === 'string' || c.kind !== 'picked');

// What the plan should say for one PR, from the graph alone: areas by path (the sample's), lines and conflicts (files
// with a merged resolution) from the nodes (unchanged reference files do not count), depth from the area or the default
// rule, time from the documented rates per bucket (none for no changed lines), order as the sections of "Group by
// area": authored areas (g 2) by their order, folder areas (g 3) by first step, late ones (g 4).
function expectPlan(pr, areaOf, steps) {
  const LIGHT = { test: 1, i18n: 1, docs: 1, config: 1, generated: 1 };
  const by = {}, firstAny = {}; // an unchanged file still sets where its area's section starts
  for (const n of pr.nodes) {
    const a = areaOf(n);
    if (n.unchanged) { firstAny[a.name] = Math.min(firstAny[a.name] ?? Infinity, steps[n.id]); continue; }
    const r = by[a.name] || (by[a.name] = { name: a.name, g: a.g, order: a.order || 0, files: 0, a: 0, d: 0, cf: 0, light: true, depth: a.depth || null, why: a.why || '', first: Infinity, nodes: [] });
    r.files++; r.a += n.added || 0; r.d += n.removed || 0; if (merged(n)) r.cf++; if (!LIGHT[bucketOf(n)]) r.light = false;
    r.first = Math.min(r.first, steps[n.id]); r.nodes.push(n);
  }
  const rows = Object.values(by).map((r) => {
    r.first = Math.min(r.first, firstAny[r.name] ?? Infinity);
    const depth = r.depth || (r.light ? 'skim' : 'read'), mb = minutesBy(depth, r.nodes), top = Object.keys(mb).sort((x, y) => mb[y] - mb[x])[0] || null;
    return { ...r, auto: !r.depth, depthOut: depth, min: minutesOf(mb), top };
  });
  rows.sort((x, y) => x.g - y.g || (x.g === 2 ? x.order - y.order : 0) || x.first - y.first);
  const kinds = {};
  for (const n of pr.nodes) kinds[bucketOf(n)] = (kinds[bucketOf(n)] || 0) + (n.added || 0) + (n.removed || 0);
  return { rows, kinds };
}
const READ_PLAN = `({sum:document.getElementById('g-plsum').textContent,open:document.getElementById('g-plan').open,
  rows:[].map.call(document.querySelectorAll('#g-planb tbody tr'),function(tr){var c=tr.children,dp=c[3].querySelector('.g-dp');return {name:c[0].textContent,files:+c[1].textContent,lines:c[2].textContent,
    depth:dp.textContent,cls:dp.className,why:(c[3].querySelector('.g-pwhy')||{}).textContent||'',min:c[4].textContent,top:(c[4].querySelector('i')||{className:null}).className,tip:c[4].title,cf:+c[5].textContent};}),
  foot:[].map.call(document.querySelectorAll('#g-planb tfoot td'),function(td){return td.textContent;}),
  bar:[].map.call(document.querySelectorAll('#g-planb .g-kbar span'),function(s){return [s.dataset.b,+s.style.flexGrow,getComputedStyle(s).backgroundColor];}),
  legend:[].map.call(document.querySelectorAll('#g-planb .g-kleg li'),function(li){return [li.dataset.b,+li.querySelector('b').textContent,li.textContent];}),
  group:(document.querySelector('#g-planb .g-kinds')||{getAttribute:function(){return null;}}).getAttribute('aria-label'),
  barHidden:(document.querySelector('#g-planb .g-kbar')||{getAttribute:function(){return null;}}).getAttribute('aria-hidden')})`;

module.exports = {
  name: 'plan',
  weight: 14, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const PLAN = t.url(t.fixtures, 'plan', 'review.html'), PL = t.url(t.fixtures, 'plan', 'review-pl.html'), STACK = t.url(t.fixtures, 'stack', 'review.html');
    const AUTH = { name: 'Sign-in', depth: 'read', why: 'Token lifetime and storage', g: 2, order: 1 }, BILL = { name: 'Billing', depth: 'skim', why: 'Mechanical rounding change', g: 2, order: 2 };
    const AREA = {
      'src/auth/session.ts': AUTH, 'src/auth/session.spec.ts': AUTH, 'src/auth/token.ts': AUTH, 'src/auth/index.ts': AUTH,
      'src/billing/invoice.ts': BILL, 'src/billing/invoice.spec.ts': BILL, 'src/billing/index.ts': BILL,
      'src/util/fmt.ts': { name: 'Utilities', depth: 'tool', why: 'Formatting only', g: 2, order: 3 }, 'gen/api.ts': { name: 'gen/', g: 3 },
      'locales/en.json': { name: 'Docs, config, i18n', g: 4 }, 'docs/plan.md': { name: 'Docs, config, i18n', g: 4 }, 'web/app.ts': { name: 'web/', g: 3 }, 'web/app.spec.ts': { name: 'web/', g: 3 }, 'styles/main.ts': { name: 'styles/', g: 3 },
      'web/theme.ts': { name: 'web/', g: 3 }, 'lib/consts.ts': { name: 'Reference', g: 2, order: 4 }, // unchanged reference files
    };
    const DEPTH = { read: 'read', skim: 'skim', tool: 'tools' };
    let strings = null, data = null, lightColors = null;

    /* ---------- The plan table and the lines-by-kind bar, both themes and both tabs ---------- */
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(PLAN, { dark });
      t.noErrors(`plan ${th}: no page errors on load`);
      if (!strings) { strings = JSON.parse(await B.ev(`document.getElementById('review-config').textContent`)).strings; data = await B.ev('T.data()'); }
      for (const k of ['P', 'Q']) {
        await B.ev(`T.tabTo('${k}')`);
        const pr = data.prs.find((p) => p.key === k), steps = Object.fromEntries((await B.ev('T.rows()')).map((r) => [r.id, r.no]));
        const exp = expectPlan(pr, (n) => AREA[n.path], steps), got = await B.ev(READ_PLAN);
        const want = exp.rows.map((r) => ({ name: r.name, files: r.files, lines: `+${r.a} −${r.d}`, depth: DEPTH[r.depthOut], auto: r.auto, why: r.why, min: timeText(r.min), top: r.min ? `b-${r.top}` : null, cf: r.cf }));
        const have = got.rows.map((r) => ({ name: r.name, files: r.files, lines: r.lines, depth: r.depth, auto: / auto/.test(r.cls), why: r.why, min: r.min, top: r.top, cf: r.cf }));
        t.check(`plan ${th} ${k}: one row per area in the order of the "Group by area" sections, with files, lines, depth, why, time by bucket (marked with the bucket that takes most of it), and merged conflicts`, JSON.stringify(have) === JSON.stringify(want), { have, want });
        t.check(`plan ${th} ${k}: a timed row's title gives the time and its split by bucket`, got.rows.every((r, i) => !exp.rows[i].min ? !r.tip : r.tip.startsWith(`≈ ${timeText(exp.rows[i].min)}: ${strings.buckets[exp.rows[i].top]} `)), got.rows.map((r) => r.tip));
        const tot = exp.rows.reduce((s, r) => ({ n: s.n + r.files, a: s.a + r.a, d: s.d + r.d, min: s.min + r.min, cf: s.cf + r.cf }), { n: 0, a: 0, d: 0, min: 0, cf: 0 });
        t.check(`plan ${th} ${k}: the total row and the summary add the rows up`, JSON.stringify(got.foot) === JSON.stringify([String(tot.n), `+${tot.a} −${tot.d}`, '', timeText(tot.min), String(tot.cf)])
          && got.sum === `≈ ${timeText(tot.min)} · ${tot.n} ${tot.n === 1 ? 'file' : 'files'} · +${tot.a} −${tot.d}`, { foot: got.foot, sum: got.sum, tot });
        const kinds = ['logic', 'test', 'i18n', 'docs', 'config', 'generated'];
        t.check(`plan ${th} ${k}: the bar has one segment per kind with lines, sized by them, and the legend gives every kind's number`,
          JSON.stringify(got.bar.map((b) => [b[0], b[1]])) === JSON.stringify(kinds.filter((b) => exp.kinds[b]).map((b) => [b, exp.kinds[b]]))
          && JSON.stringify(got.legend.map((l) => [l[0], l[1]])) === JSON.stringify(kinds.map((b) => [b, exp.kinds[b] || 0]))
          && got.legend.every((l) => l[2].startsWith(strings.buckets[l[0]])), { got: [got.bar, got.legend], kinds: exp.kinds });
        t.check(`plan ${th} ${k}: the bar is decoration (aria-hidden) inside a named group whose legend is the text`, got.barHidden === 'true' && got.group === strings.kindsTitle, got);
        t.check(`plan ${th} ${k}: the table's lines equal the bar's`, Object.values(exp.kinds).reduce((s, x) => s + x, 0) === tot.a + tot.d);
        if (k === 'Q') {
          const refs = pr.nodes.filter((n) => n.unchanged).map((n) => n.path).sort();
          t.check(`plan ${th} Q: (setup) Q has two unchanged reference files, one beside a changed file and one alone in its area`, JSON.stringify(refs) === '["lib/consts.ts","web/theme.ts"]', refs);
          t.check(`plan ${th} Q: unchanged files are not counted (web/ has its two changed files), an area of nothing but them has no row, and a changed file with no changed lines takes no time`,
            have.every((r) => r.name !== 'Reference') && have.find((r) => r.name === 'web/').files === 2 && JSON.stringify(have.find((r) => r.name === 'styles/')) === JSON.stringify({ name: 'styles/', files: 1, lines: '+0 −0', depth: 'read', auto: true, why: '', min: '0 min', top: null, cf: 0 })
            && got.sum.startsWith('≈ 1 min · 3 files'), { have, sum: got.sum });
        }
        if (k === 'P') {
          if (!dark) lightColors = got.bar.map((b) => b[2]);
          else t.check('plan: the bar\'s colours follow the theme', got.bar.length > 2 && got.bar.every((b, i) => b[2] !== lightColors[i]) && new Set(got.bar.map((b) => b[2])).size === got.bar.length, { dark: got.bar, light: lightColors });
          const rates = strings.planMinTitle.replace(/\{(\w+)\}/g, (m, x) => String({ ...RATE, skim: 4, hours: 90 }[x] ?? m));
          t.check(`plan ${th}: the time column's title gives the rates it uses`, await B.ev(`document.querySelectorAll('#g-planb thead th')[4].title`) === rates && /400.*1500.*1500.*2000.*3000.*1000.*4/.test(rates), rates);
          await B.ev(`document.querySelector('.g-tabs-row').scrollIntoView()`); await sleep(150);
          await t.shot(`plan-1440-${th}`);
        }
      }
      t.noErrors(`plan ${th}: no page errors`);
    }

    /* ---------- A row's click selects the area's first step; with "Group by area" it opens and lifts its section ---------- */
    await t.fresh(PLAN);
    const steps = Object.fromEntries((await B.ev('T.rows()')).map((r) => [r.id, r.no]));
    const P = data.prs[0], pid = (p) => P.nodes.find((n) => n.path === p).id;
    const firstOf = (name) => P.nodes.filter((n) => AREA[n.path].name === name).sort((a, b) => steps[a.id] - steps[b.id])[0].id;
    await B.ev(`[].find.call(document.querySelectorAll('#g-planb .g-pa'),function(b){return b.textContent==='Billing';}).click()`);
    t.check('plan: a row\'s click selects its area\'s first step', await B.ev('T.sel()') === firstOf('Billing'), [await B.ev('T.sel()'), firstOf('Billing')]);
    await B.ev(`document.getElementById('g-area').click()`); await sleep(80);
    await B.ev(`T.head('a:auth').click()`);
    t.check('plan: (setup) the Sign-in section is collapsed', (await B.ev('T.secs()')).find((s) => s.key === 'a:auth').shut);
    await B.ev(`[].find.call(document.querySelectorAll('#g-planb tbody tr'),function(tr){return tr.querySelector('th').textContent==='Sign-in';}).querySelector('td').click()`);
    const lift = await B.ev(`(function(){var b=document.getElementById('g-orderbox'),li=document.querySelector('#g-order .g-sec[data-sec="a:auth"]');return {top:b.scrollTop,want:Math.min(b.scrollHeight-b.clientHeight,Math.max(0,li.offsetTop-6)),shut:li.classList.contains('shut')};})()`);
    t.check('plan: a click anywhere on the row selects the first step and opens its section in the list', await B.ev('T.sel()') === firstOf('Sign-in') && !lift.shut && Math.abs(lift.top - lift.want) <= 1, { lift, sel: await B.ev('T.sel()') });
    await B.ev(`document.getElementById('g-area').click()`);
    // Folding is kept per report.
    await B.ev(`document.querySelector('#g-plan>summary').click()`);
    t.check('plan: folding stores the state', !(await B.ev(`document.getElementById('g-plan').open`)) && await B.ev(`localStorage.getItem(T.key()+'plan')`) === '0');
    await t.reload(PLAN);
    t.check('plan: a folded plan stays folded after a reload, its summary still showing', !(await B.ev(`document.getElementById('g-plan').open`)) && /≈ \d+ min/.test(await B.ev(`document.getElementById('g-plsum').textContent`)));
    await B.ev(`document.querySelector('#g-plan>summary').click()`);
    t.noErrors('plan clicks: no page errors');

    /* ---------- The plan keeps the sections' order of "Group by area" in both reading orders ---------- */
    await t.fresh(PLAN);
    for (const o of ['top', 'bottom', 'top']) {
      await B.ev(`document.querySelector('[data-o=${o}]').click()`); await sleep(60);
      const names = await B.ev(`[].map.call(document.querySelectorAll('#g-planb tbody th button'),function(b){return b.textContent.replace(/^◆ /,'');})`);
      await B.ev(`document.getElementById('g-area').click()`); await sleep(80);
      const secs = await B.ev(`[].filter.call(document.querySelectorAll('#g-order .g-sec'),function(s){return /^a:/.test(s.dataset.sec);}).map(function(s){return s.querySelector('.g-sh').title;})`);
      t.check(`plan order ${o}: the rows follow the sections of "Group by area" (and do not move when the reading order changes)`, JSON.stringify(names) === JSON.stringify(secs) && names.length === 5
        && JSON.stringify(names.slice(0, 3)) === '["Sign-in","Billing","Utilities"]', { names, secs });
      await B.ev(`document.getElementById('g-area').click()`);
    }
    t.noErrors('plan order: no page errors');

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

    /* ---------- From 90 minutes on the time reads in hours, in the page's number format ---------- */
    for (const [src, lang, sep] of [[PLAN, 'en', '.'], [PL, 'pl', ',']]) {
      const page = fs.readFileSync(src.replace(/^file:\/\//, ''), 'utf8'), a0 = page.indexOf('id="graph-data">'), e0 = page.indexOf('</script>', a0);
      const big = JSON.parse(page.slice(page.indexOf('>', a0) + 1, e0)), BP = big.prs[0];
      BP.nodes.find((n) => n.path === 'src/auth/session.ts').added = 1000; // a read area: about 2.5 h
      BP.nodes.find((n) => n.path === 'src/billing/invoice.ts').added = 24000; // a skimmed one: about 15 h
      const HOURS = path.join(t.work, `hours-${lang}.html`);
      fs.writeFileSync(HOURS, page.slice(0, page.indexOf('>', a0) + 1) + JSON.stringify(big).replace(/</g, '\\u003c') + page.slice(e0));
      await t.fresh(t.url(HOURS));
      const st = Object.fromEntries((await B.ev('T.rows()')).map((r) => [r.id, r.no])), exp = expectPlan(BP, (n) => AREA[n.path], st), got = await B.ev(READ_PLAN);
      const tot = exp.rows.reduce((x, r) => x + r.min, 0), want = exp.rows.map((r) => timeText(r.min, sep));
      t.check(`plan hours ${lang}: rows and total from 90 minutes on read in hours (halves below 10), with the page's decimal mark`,
        JSON.stringify(got.rows.map((r) => r.min)) === JSON.stringify(want) && want[0] === `2${sep}5 h` && want[1] === '15 h' && got.foot[3] === timeText(tot, sep)
        && got.sum.startsWith(`≈ ${timeText(tot, sep)} · `) && got.rows[1].top === 'b-logic', { got: got.rows.map((r) => r.min), want, foot: got.foot, sum: got.sum });
      t.noErrors(`plan hours ${lang}: no page errors`);
    }
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
    t.check('lead: the folded legend keeps the facts (orders, shared dependencies, map, overview, keys)', lead.items.length === 8 && ['graphMoreList', 'graphMoreOrder', 'graphMoreShared', 'graphMoreView', 'graphMoreMap', 'graphMoreAreas', 'graphMorePlan', 'graphMoreKeys'].every((k, i) => lead.items[i] === strings[k])
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
    const refs = await B.ev(`[].map.call(document.querySelectorAll('#risks code'),function(c){return [c.textContent,!!c.closest('button.g-ref'),(c.closest('button.g-ref')||{}).title||''];})`);
    const want = { 'src/auth/session.ts:40': 1, 'invoice.ts:3-4': 1, ':8': 1, 'src/auth/session.ts:2': 1, 'nowhere.ts:5': 0, 'index.ts:1': 0, '12:30': 0, 'token.ts:10-12': 1, 'web/app.ts:1': 1, 'web/app.ts:2': 0 };
    t.check('refs: path:line, path:start-end, a unique file name, and a continuation become buttons; unknown, ambiguous, linked, and pre code stays plain',
      refs.length === 11 && refs.every(([c, b], i) => (i === 10 ? !b : b === !!want[c])) && refs[1][2] === 'Show src/billing/invoice.ts:3-4 in the diff' && refs[2][2] === 'Show src/billing/invoice.ts:8 in the diff', refs);
    const refAt = (text) => `[].find.call(document.querySelectorAll('#risks button.g-ref'),function(b){return b.textContent===${JSON.stringify(text)};})`;
    const after1 = async (text) => { await B.ev(`${refAt(text)}.click()`); await sleep(250); return B.ev(`({tab:T.tab(),sel:T.sel(),act:document.activeElement.outerHTML.slice(0,90),nf:document.activeElement.classList.contains('nf'),miss:(document.querySelector('#dv-files .g-refmiss')||{}).textContent||null,top:document.activeElement.getBoundingClientRect().top,vh:innerHeight})`); };
    let r = await after1('src/auth/session.ts:40');
    t.check('refs: a click opens the file on its tab, focuses the line, and flashes it in view', r.tab === 'P' && r.sel === pid('src/auth/session.ts') && /data-s="new" data-l="40"/.test(r.act) && r.nf && !r.miss && r.top > 0 && r.top < r.vh, r);
    await B.ev(`T.tabTo('Q')`);
    r = await after1('invoice.ts:3-4');
    t.check('refs: a file name alone opens its file (from another tab) at the first line of the range', r.tab === 'P' && r.sel === pid('src/billing/invoice.ts') && /data-l="3"/.test(r.act) && r.nf, r);
    r = await after1(':8');
    t.check('refs: a continuation opens the same file at its line', r.sel === pid('src/billing/invoice.ts') && /data-l="8"/.test(r.act), r);
    r = await after1('src/auth/session.ts:2');
    t.check('refs: a line outside the diff opens the file and says so', r.sel === pid('src/auth/session.ts') && /<summary/.test(r.act) && r.miss === 'Line 2 is outside the shown hunks of src/auth/session.ts; the file is open.'
      && await B.ev(`document.getElementById('nt-live').textContent`) === r.miss, r);
    r = await after1('web/app.ts:1');
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
    const pl = await B.ev(`({plan:document.querySelector('#g-plan>summary span').textContent,depth:document.querySelector('#g-planb .g-dp').textContent,more:document.querySelector('#g-more>summary').textContent,
      menu:document.getElementById('g-mbtn').textContent,add:document.querySelector('#risks .g-radd').textContent,ws:document.getElementById('g-wsb').title,kinds:document.querySelector('#g-planb .g-kleg li').textContent})`);
    t.check('pl: the plan, depth, legend, menu, risk button, workspace button, and kinds are in Polish', pl.plan === 'Plan review' && ['czytaj', 'przejrzyj', 'narzędzia'].includes(pl.depth) && pl.more === 'Legenda i skróty'
      && /^Widok/.test(pl.menu) && pl.add === 'Dodaj jako uwagę' && /^Tryb roboczy/.test(pl.ws) && /^Logika/.test(pl.kinds), pl);
    await B.ev(`T.pick(T.id('src/auth/session.ts'))`);
    t.check('pl: the conflict line', /^↯ Rozwiązany ręcznie przy merge abc1234$/.test(await B.ev(`document.querySelector('#g-detail .g-cf>span').textContent`)));
    t.noErrors('pl: no page errors');

    /* ---------- A report without areas, buckets, or conflicts ---------- */
    await t.fresh(STACK);
    const old = await B.ev(READ_PLAN);
    t.check('older report: the plan still has areas (folders, docs/config/i18n), default depths, and lines by kind from the layers',
      old.rows.length >= 2 && old.rows.every((x) => / auto/.test(x.cls) && !x.why && x.cf === 0) && old.legend.find((l) => l[0] === 'generated')[1] === 0 && old.legend.find((l) => l[0] === 'docs')[1] > 0, old);
    t.check('older report: no conflict marks', await B.ev(`document.querySelectorAll('.g-cfb,.g-cf').length`) === 0);
    t.noErrors('older report: no page errors');

    /* ---------- Markup in the new fields stays text ---------- */
    await t.fresh(t.url(t.fixtures, 'sec', 'xss.html'));
    await B.ev(`T.pick(T.rows()[0].id)`);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(100);
    await B.ev(`document.querySelector('[data-v=list]').click()`);
    const x = await B.ev(`({pwn:window.__pwn||null,imgs:document.querySelectorAll('img').length,area:document.querySelector('#g-planb tbody th').textContent,why:document.querySelector('#g-planb .g-pwhy').textContent,
      depth:document.querySelector('#g-planb .g-dp').className,cf:[].map.call(document.querySelectorAll('#g-detail .g-cf code'),function(c){return c.textContent;}),
      chips:[].map.call(document.querySelectorAll('.g-cfb'),function(c){return c.title;}),legend:[].map.call(document.querySelectorAll('#g-planb .g-kleg li'),function(li){return li.dataset.b+':'+li.querySelector('b').textContent;}),
      ref:(document.querySelector('#risks button.g-ref')||{}).title||null})`);
    t.check('markup: an area\'s label and why show as text, a bogus depth falls back, a bogus bucket counts by layer, a bogus merge is dropped',
      x.pwn === null && x.imgs === 0 && /^area <img src=x/.test(x.area) && /^why <img src=x/.test(x.why) && /d-read auto/.test(x.depth) && x.cf.length === 1 && x.cf[0].startsWith('git show --remerge-diff abc1234 -- ')
      && x.chips.every((c) => c === 'Resolved by hand in merge abc1234') && x.legend.some((l) => /^logic:\d+$/.test(l)) && x.legend.includes('generated:0'), x);
    await B.ev(`document.querySelector('#risks button.g-ref').click()`); await sleep(150);
    await B.ev(`document.querySelector('#risks .g-radd').click()`); await sleep(60);
    const y = await B.ev(`({pwn:window.__pwn||null,imgs:document.querySelectorAll('img').length,note:(T.stored('notes')||[]).slice(-1)[0]})`);
    t.check('markup: a reference to a markup-named file opens it and its risk becomes a note as text', x.ref && y.pwn === null && y.imgs === 0 && y.note && y.note.scope === 'line' && /^Odd name: src\/<img src=x/.test(y.note.text), { x: x.ref, y });
    t.noErrors('markup: no page errors');
  },
};
