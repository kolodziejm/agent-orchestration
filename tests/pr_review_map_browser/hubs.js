'use strict';
// Shared dependencies (hubs) and "Group by folder", on the Polish hub sample (one PR of about 45 files around three
// hubs): the pinned hub group and its order, arcs and the neighbourhood around hubs, the hub band on the map, folder
// sections (collapse, keyboard, jumps into collapsed sections, header counts), and layout at 1440 and 800 in both themes.
const path = require('path');
const { sleep, viewerOrder } = require('./lib');

module.exports = {
  name: 'hubs',
  weight: 15, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const HUB = t.url(t.fixtures, 'hub', 'review.html'), STACK = t.url(t.fixtures, 'stack', 'review.html'), BIG = t.url(t.fixtures, 'big', 'review.html');
    const exp = viewerOrder(path.join(t.fixtures, 'hub', 'review.html'));
    const g = exp.data.prs[0], byId = {};
    g.nodes.forEach((n) => { byId[n.id] = n; });
    const HUBS = g.nodes.filter((n) => n.hub).map((n) => n.id);
    const P = (p) => g.nodes.find((n) => n.path === p).id;
    // The OAuth session (uses two hubs and other files), the i18n index (the most used hub), and the app's error texts
    // (a hub that itself uses the index).
    const gas = P('apps/mobile/src/auth/oauth-session.ts'), idx = P('packages/i18n/src/index.ts'), ft = P('apps/mobile/src/i18n/error-text.ts');
    const LATE = { docs: 1, config: 1, i18n: 1 };
    t.check('fixture: three hubs, among them the i18n index and the error texts', HUBS.length === 3 && HUBS.includes(idx) && HUBS.includes(ft), HUBS.map((h) => byId[h].path));

    /* ---------- Hub group and order ---------- */
    await t.fresh(HUB);
    t.noErrors('hub: no page errors on load');
    t.check('hub: "Group by folder" is off by default', await B.ev(`!document.getElementById('g-group').checked`));
    for (const mode of ['top', 'bottom']) {
      await B.ev(`document.querySelector('[data-o=${mode}]').click()`);
      const rows = await B.ev('T.rows()'), secs = await B.ev('T.secs()');
      const on = exp.order[mode].M.on, subj = exp.order[mode].M.subj;
      const want = Object.keys(on).sort((a, b) => on[a] - on[b]);
      t.check(`hub ${mode}: list order and numbers match computeOrder`, JSON.stringify(rows.map((r) => r.id)) === JSON.stringify(want) && rows.every((r) => r.no === on[r.id]), { rows: rows.map((r) => r.id + ':' + r.no) });
      const hubRows = want.filter((id) => HUBS.includes(id) || HUBS.includes(subj[id]));
      t.check(`hub ${mode}: the shared-dependency group is pinned first and holds the hubs and their tests as steps 1..${hubRows.length}`,
        secs.length === 1 && secs[0].hub && JSON.stringify(secs[0].ids) === JSON.stringify(hubRows) && hubRows.every((id) => on[id] <= hubRows.length) && HUBS.every((h) => hubRows.includes(h)), { secs, hubRows });
      t.check(`hub ${mode}: the group header names it and counts read/files`, /Wspólne zależności/.test(secs[0].label) && secs[0].sc === `0/${hubRows.length}` && secs[0].exp === 'true', secs[0]);
    }
    const topOn = exp.order.top.M.on;
    t.check('hub: hubs open "from the entry point" too, the error texts (which use the index) before the index', topOn[ft] < topOn[idx] && HUBS.every((h) => topOn[h] <= HUBS.length + 2), { ft: topOn[ft], idx: topOn[idx] });
    await B.ev(`document.querySelector('[data-o=top]').click()`);

    /* ---------- Arcs ---------- */
    await B.ev(`T.pick('${gas}')`); await sleep(100);
    const usesHubs = g.edges.filter((e) => e.from === gas && HUBS.includes(e.to)).map((e) => e.to);
    let arcs = await B.ev('T.arcs()');
    const nonHubLinks = g.edges.filter((e) => (e.from === gas || e.to === gas) && !(HUBS.includes(e.to) && e.from === gas) && e.kind !== 'test').length;
    t.check('arcs: a selected file draws its own links but no arc into a shared dependency', usesHubs.length > 0 && arcs.every((a) => !HUBS.includes(a.t) || HUBS.includes(a.f)) && arcs.length === nonHubLinks, { arcs, usesHubs, nonHubLinks });
    const chip = await B.ev(`(function(){var c=T.row('${gas}').querySelector('.g-hc');return c?{text:c.textContent,title:c.title,aria:c.getAttribute('aria-label')}:null;})()`);
    t.check('arcs: the selected row gets a "◆" chip naming the shared dependencies it uses', !!chip && chip.text.startsWith('◆') && usesHubs.every((h) => chip.title.includes(byId[h].label)), chip);
    t.check('arcs: only the selected row has that chip', await B.ev(`document.querySelectorAll('#g-order .g-hc').length`) === 1);
    t.check('arcs: the used hubs\' rows are marked as dependencies and their dots ringed', await B.ev(`[${usesHubs.map((h) => `'${h}'`).join(',')}].every(function(h){return T.row(h).classList.contains('dep');})`) && await B.ev(`document.querySelectorAll('#g-lane circle.dot.hu').length`) === usesHubs.length);
    await B.ev(`T.pick('${idx}')`); await sleep(100);
    arcs = await B.ev('T.arcs()');
    const idxUsers = g.edges.filter((e) => e.to === idx && e.kind !== 'test').length;
    t.check('arcs: selecting a shared dependency draws its incoming arcs (orange)', arcs.filter((a) => a.t === idx).length === idxUsers && arcs.filter((a) => a.t === idx).every((a) => /\buse\b/.test(a.c)) && await B.ev(`!document.querySelector('#g-order .g-hc')`), { n: arcs.filter((a) => a.t === idx).length, idxUsers });
    await B.ev(`T.row('${gas}').dispatchEvent(new MouseEvent('mouseenter'))`); await sleep(50);
    await B.ev(`T.row('${gas}').dispatchEvent(new MouseEvent('mouseleave'));T.row('${ft}').dispatchEvent(new MouseEvent('mouseenter'))`); await sleep(50);
    arcs = await B.ev('T.arcs()');
    t.check('arcs: hovering a shared dependency hints its incoming arcs', arcs.filter((a) => a.t === ft && !HUBS.includes(a.f)).length === g.edges.filter((e) => e.to === ft && !HUBS.includes(e.from) && !(e.kind === 'test' && exp.order.top.M.subj[e.from] === e.to)).length, arcs.filter((a) => a.t === ft).length);
    await B.ev(`T.row('${ft}').dispatchEvent(new MouseEvent('mouseleave'))`);
    await B.ev(`document.getElementById('g-all').click()`); await sleep(80);
    await B.ev(`T.pick('${gas}')`); await sleep(80);
    arcs = await B.ev('T.arcs()');
    t.check('arcs: "All links" leaves out every arc into a shared dependency (unless that hub is selected)', arcs.length > 20 && arcs.every((a) => !HUBS.includes(a.t) || HUBS.includes(a.f)), arcs.length);
    await B.ev(`document.getElementById('g-all').click()`);

    /* ---------- Neighbourhood ---------- */
    await B.ev(`T.pick('${gas}')`); await sleep(80);
    const nb = await B.ev(`({line:(document.querySelector('#g-detail .g-nbs')||{}).textContent,links:[].map.call(document.querySelectorAll('#g-detail .g-nbs [data-go]'),function(b){return b.dataset.go;}),deps:[].map.call(document.querySelectorAll('#g-detail .g-nbc.dep .g-nbi'),function(b){return b.dataset.go;})})`);
    t.check('neighbourhood: shared dependencies collapse into one "+ wspólne:" line, not dependency items', !!nb.line && nb.line.startsWith('+ wspólne:') && JSON.stringify([...nb.links].sort()) === JSON.stringify([...usesHubs].sort()) && nb.deps.every((d) => !HUBS.includes(d)) && nb.deps.length > 0, nb);
    await B.ev(`document.querySelector('#g-detail .g-nbs [data-go]').click()`); await sleep(80);
    t.check('neighbourhood: a "+ shared" link selects that hub', HUBS.includes(await B.ev('T.sel()')));
    await B.ev(`T.pick('${idx}')`); await sleep(80);
    const nbh = await B.ev(`({line:!!document.querySelector('#g-detail .g-nbs'),uses:document.querySelectorAll('#g-detail .g-nbc.use .g-nbi').length,more:(document.querySelector('#g-detail [data-more=use]')||{}).textContent})`);
    t.check('neighbourhood: a hub itself lists its dependents (with "+n więcej") and no shared line', !nbh.line && nbh.uses === 7 && /\+\d+ więcej/.test(nbh.more || ''), nbh);
    t.noErrors('hub interactions: no page errors');

    /* ---------- Map ---------- */
    await B.ev(`T.pick('${gas}')`);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(300);
    const mp = await B.ev(`(function(){
      var hubs=T.hubs(),nd=[].slice.call(document.querySelectorAll('#g-canvas g.nd')),band=document.querySelector('#g-canvas rect.hbb');
      function y(g){return +g.getAttribute('transform').match(/,([\\d.]+)\\)/)[1];}
      function row(g){var t=g.querySelector('tspan.num').textContent.trim();return [].find.call(document.querySelectorAll('#g-order li.g-row'),function(li){return li.querySelector('.no').textContent===t;});}
      var hy=[],oy=[],ht={};[].forEach.call(document.querySelectorAll('#g-order .g-sec.hub li.g-row'),function(li){if(!hubs[li.dataset.id])ht[li.dataset.id]=1;});
      nd.forEach(function(g){var r=row(g);if(!r)return;var i=r.dataset.id;if(ht[i])return;(hubs[i]?hy:oy).push(y(g));});
      var ed=[].map.call(document.querySelectorAll('#g-canvas path.ed'),function(p){return {f:p.dataset.f,t:p.dataset.t,c:p.getAttribute('class'),shown:getComputedStyle(p).display!=='none'};});
      var into=ed.filter(function(e){return hubs[e.t]&&!hubs[e.f]&&!ht[e.f];});
      return {band:!!band,bandBottom:band?+band.getAttribute('y')+ +band.getAttribute('height'):0,hubMaxY:Math.max.apply(null,hy),otherMinY:Math.min.apply(null,oy),hubs:hy.length,
        into:into.length,intoShown:into.filter(function(e){return e.shown;}).map(function(e){return e.f+'>'+e.t+' '+e.c;}),hubHub:ed.filter(function(e){return hubs[e.t]&&hubs[e.f];}).map(function(e){return e.shown;})};
    })()`);
    t.check('map: shared dependencies sit in their own band above the graph', mp.band && mp.hubs === HUBS.length && mp.hubMaxY < mp.otherMinY && mp.bandBottom <= mp.otherMinY, mp);
    t.check('map: edges into the band are hidden except the selected file\'s (blue)', mp.into > 10 && mp.intoShown.length === usesHubs.length && mp.intoShown.every((s) => s.startsWith(gas + '>') && /\bdep\b/.test(s)), mp);
    t.check('map: links between shared dependencies stay drawn', mp.hubHub.length >= 2 && mp.hubHub.every(Boolean), mp.hubHub);
    await B.ev(`document.querySelector('[data-v=list]').click()`);
    t.noErrors('map: no page errors');

    /* ---------- Group by folder ---------- */
    const flat = await B.ev('T.rows()');
    await B.ev(`document.getElementById('g-group').click()`); await sleep(100);
    let rows = await B.ev('T.rows()'), secs = await B.ev('T.secs()');
    const key = await B.ev('T.key()');
    t.check('grouping: on splits the list into 3-10 folder sections after the hub group, stored under its own key', secs.length >= 4 && secs.length <= 11 && secs[0].hub && await B.ev(`localStorage.getItem('${key}folders')`) === '1', secs.map((s) => s.key + ':' + s.ids.length));
    const noOf = {};
    flat.forEach((r) => { noOf[r.id] = r.no; });
    t.check('grouping: every step keeps its number', rows.length === flat.length && rows.every((r) => noOf[r.id] === r.no));
    t.check('grouping: reading order inside each section, sections ordered by their first step', secs.every((s) => s.ids.every((id, i) => i === 0 || noOf[s.ids[i - 1]] < noOf[id])) && secs.every((s, i) => i === 0 || noOf[secs[i - 1].ids[0]] < noOf[s.ids[0]]), secs.map((s) => s.ids.map((id) => noOf[id])));
    const subjTop = exp.order.top.M.subj;
    t.check('grouping: each test stays right under its subject (or its subject\'s other tests)', rows.every((r, i) => !subjTop[r.id] || (i > 0 && rows[i - 1].sec === r.sec && (rows[i - 1].id === subjTop[r.id] || subjTop[rows[i - 1].id] === subjTop[r.id]))), rows.filter((r) => subjTop[r.id]).map((r) => r.id));
    t.check('grouping: headers name the folder and count files, read, and notes', secs.slice(1).every((s) => /\/: \d+ (plik|pliki|plików), przeczytane: 0, uwagi: 0$|^\(katalog główny\): /.test(s.label)), secs.map((s) => s.label));
    await t.reload(HUB);
    t.check('grouping: survives a reload', await B.ev(`document.getElementById('g-group').checked`) && (await B.ev('T.secs()')).length === secs.length);
    // Collapse, persistence, header counts.
    secs = await B.ev('T.secs()');
    const biggest = secs.slice(1).reduce((a, s) => (s.ids.length > a.ids.length ? s : a));
    await B.ev(`T.head(${JSON.stringify(biggest.key)}).click()`); await sleep(50);
    const s2 = (await B.ev('T.secs()')).find((s) => s.key === biggest.key), r2 = await B.ev('T.rows()');
    t.check('collapse: a header click hides its rows and sets aria-expanded=false', s2.shut && s2.exp === 'false' && r2.filter((r) => r.sec === biggest.key).every((r) => !r.vis), s2);
    t.check('collapse: the state is stored per PR under "fold"', JSON.parse(await B.ev(`localStorage.getItem('${key}fold')`)).M[biggest.key] === 1);
    await t.reload(HUB);
    t.check('collapse: survives a reload', (await B.ev('T.secs()')).find((s) => s.key === biggest.key).shut);
    await B.ev(`T.head(${JSON.stringify(biggest.key)}).click()`);
    const sm = secs.slice(1).find((s) => s.ids.length >= 3 && s.key !== biggest.key);
    await B.ev(`T.row('${sm.ids[0]}').querySelector('input').click()`);
    t.check('header counts: marking a row read updates "read/files"', (await B.ev('T.secs()')).find((s) => s.key === sm.key).sc === `1/${sm.ids.length}`);
    // Keyboard: skip a collapsed section.
    secs = await B.ev('T.secs()');
    const si = secs.findIndex((s, i) => i > 1 && i < secs.length - 1);
    const prevSec = secs[si - 1], shut = secs[si], nextSec = secs[si + 1];
    await B.ev(`T.head(${JSON.stringify(shut.key)}).click()`);
    await B.ev(`T.row('${prevSec.ids[prevSec.ids.length - 1]}').querySelector('.nm').focus()`);
    await B.key('ArrowDown');
    const k1 = await B.ev(`({head:!!document.activeElement.closest('.g-sh'),sec:document.activeElement.closest('.g-sec')&&document.activeElement.closest('.g-sec').dataset.sec})`);
    await B.key('ArrowDown');
    const k2 = await B.ev(`(document.activeElement.closest('.g-sec')||{dataset:{}}).dataset.sec`);
    await B.key('ArrowDown');
    const k3 = await B.ev(`(document.activeElement.closest('li.g-row')||{dataset:{}}).dataset.id`);
    t.check('keyboard: ArrowDown moves onto a collapsed header, then past its hidden rows to the next header and its first row', k1.head && k1.sec === shut.key && k2 === nextSec.key && k3 === nextSec.ids[0], { k1, k2, k3, want: nextSec.ids[0] });
    await B.key('ArrowUp');
    t.check('keyboard: one Tab stop in the list after moving', await B.ev(`document.querySelectorAll('#g-order .nm[tabindex="0"],#g-order .g-sh[tabindex="0"]').length`) === 1);
    await B.key('ArrowUp');
    await B.key('ArrowRight');
    const expanded = !(await B.ev('T.secs()')).find((s) => s.key === shut.key).shut;
    await B.key('ArrowLeft');
    t.check('keyboard: ArrowRight on a header expands it, ArrowLeft collapses it', expanded && (await B.ev('T.secs()')).find((s) => s.key === shut.key).shut);
    await B.key('Enter');
    t.check('keyboard: Enter on a header toggles it', !(await B.ev('T.secs()')).find((s) => s.key === shut.key).shut);
    // Next into a collapsed section.
    rows = await B.ev('T.rows()');
    const byNo = {};
    rows.forEach((r) => { byNo[r.no] = r; });
    let k = 6;
    while (byNo[k + 1] && byNo[k + 1].sec === byNo[k].sec) k++;
    const target = byNo[k + 1];
    await B.ev(`T.pick('${byNo[k].id}')`);
    await B.ev(`T.head(${JSON.stringify(target.sec)}).click()`);
    await B.ev(`document.getElementById('g-next').click()`); await sleep(80);
    t.check('jump: "Next" into a collapsed section selects the step and expands the section (stored)', await B.ev('T.sel()') === target.id && !(await B.ev('T.secs()')).find((s) => s.key === target.sec).shut && !(JSON.parse(await B.ev(`localStorage.getItem('${key}fold')`) || '{}').M || {})[target.sec], target);
    // Neighbourhood click into a collapsed section, and the lane end at its header.
    const secOf = {};
    (await B.ev('T.rows()')).forEach((r) => { secOf[r.id] = r.sec; });
    const gasSec = secOf[gas];
    const dep = g.edges.find((e) => !HUBS.includes(e.to) && !HUBS.includes(e.from) && e.kind !== 'test' && secOf[e.from] && secOf[e.to] && secOf[e.from] !== secOf[e.to] && byId[e.to].layer !== 'test');
    if (dep) {
      const depSec = secOf[dep.to];
      await B.ev(`T.pick('${dep.from}')`);
      await B.ev(`T.head(${JSON.stringify(depSec)}).click()`); await sleep(50);
      const lane = await B.ev(`(function(){var a=[].find.call(document.querySelectorAll('#g-lane path.arc'),function(p){return p.dataset.t==='${dep.to}';});var h=T.head(${JSON.stringify(depSec)});var m=a&&a.getAttribute('d').match(/([\\d.]+)$/);return {end:m?+m[1]:null,hy:h.offsetTop+h.offsetHeight/2,cls:h.className};})()`);
      t.check('lane: an arc to a row in a collapsed section ends at its header, which takes the blue mark', lane.end !== null && Math.abs(lane.end - lane.hy) < 1 && /\bdep\b/.test(lane.cls), lane);
      await B.ev(`document.querySelector('#g-detail .g-nbc.dep [data-go="${dep.to}"]').click()`); await sleep(80);
      t.check('jump: a neighbourhood click into a collapsed section expands it', await B.ev('T.sel()') === dep.to && !(await B.ev('T.secs()')).find((s) => s.key === depSec).shut);
    } else {
      t.check('fixture: a link between two folder sections exists', false, secOf);
    }
    // Note jump into a collapsed section; header note chip.
    await B.ev(`T.pick('${gas}')`); await sleep(80);
    await B.ev(`document.querySelector('#dv-files td.ln[data-s=new][data-l="5"]').click()`);
    await B.ev(`document.querySelector('[data-nt=add]').click()`);
    await B.ev(`T.save(document.querySelector('#dv-files .nt-ed'),'issue','Check this import.')`);
    const gasHead = (await B.ev('T.secs()')).find((s) => s.key === gasSec);
    t.check('header counts: a note on a row shows as a kind chip on its section header', gasHead.chips === 1 && /uwagi: 1$/.test(gasHead.label), gasHead);
    await B.ev(`T.pick('${idx}')`);
    await B.ev(`T.head(${JSON.stringify(gasSec)}).click()`);
    await B.ev(`document.querySelector('#nt-list .nt-loc').click()`); await sleep(300);
    t.check('jump: a note jump into a collapsed section expands it and focuses the line', await B.ev('T.sel()') === gas && !(await B.ev('T.secs()')).find((s) => s.key === gasSec).shut && await B.ev(`document.activeElement.matches('td.ln[data-l="5"]')`), await B.ev(`document.activeElement.outerHTML.slice(0,80)`));
    // Tests filter and order modes while grouped.
    await B.ev(`document.getElementById('g-tests').click()`); await sleep(80);
    rows = await B.ev('T.rows()'); secs = await B.ev('T.secs()');
    t.check('grouping + tests filter: tests hidden, numbers kept, no empty section', rows.every((r) => !r.t && noOf[r.id] === r.no) && secs.every((s) => s.ids.length > 0), secs.map((s) => s.ids.length));
    await B.ev(`document.getElementById('g-tests').click()`);
    await B.ev(`document.querySelector('[data-o=bottom]').click()`); await sleep(80);
    secs = await B.ev('T.secs()'); rows = await B.ev('T.rows()');
    const nb2 = {};
    rows.forEach((r) => { nb2[r.id] = r.no; });
    t.check('grouping + "from dependencies": hub group first, sections by first step', secs[0].hub && secs.every((s, i) => i === 0 || nb2[secs[i - 1].ids[0]] < nb2[s.ids[0]]) && secs.every((s) => s.ids.every((id, i) => i === 0 || nb2[s.ids[i - 1]] < nb2[id])));
    await B.ev(`document.querySelector('[data-o=top]').click()`);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(200);
    await B.ev(`document.querySelector('[data-v=list]').click()`);
    t.noErrors('grouping: no page errors');

    /* ---------- Stack: a cross-PR chip into a collapsed section ---------- */
    await t.fresh(STACK);
    await B.ev(`document.getElementById('g-group').click()`);
    const chipRow = await B.ev(`(function(){var c=document.querySelector('#g-order .g-xc');return c?{row:c.closest('li.g-row').dataset.id,text:c.textContent,title:c.title.split('\\n')[0]}:null;})()`);
    if (chipRow) {
      await B.ev(`T.tabTo('${chipRow.text.slice(1)}')`);
      const tid = await B.ev(`T.id(${JSON.stringify(chipRow.title.replace(/^[^:]*: /, ''))})`);
      const tsec = (await B.ev('T.rows()')).find((r) => r.id === tid).sec;
      await B.ev(`T.head(${JSON.stringify(tsec)}).click()`);
      await B.ev(`T.tabTo('A')`);
      await B.ev(`T.row('${chipRow.row}').querySelector('.g-xc').click()`); await sleep(100);
      t.check('jump: a cross-PR chip opens the file on its tab and expands its collapsed section', await B.ev('T.sel()') === tid && !(await B.ev('T.secs()')).find((s) => s.key === tsec).shut && await B.ev(`document.activeElement===T.row('${tid}').querySelector('.nm')`), { tid, tsec });
    } else t.check('stack has a cross-PR chip', false);
    t.noErrors('stack grouped: no page errors');

    /* ---------- Big: grouping a 103-row PR ---------- */
    await t.fresh(BIG);
    await B.ev(`document.getElementById('g-group').click()`); await sleep(100);
    secs = await B.ev('T.secs()'); rows = await B.ev('T.rows()');
    t.check('big: 103 rows in 3-10 sections, none a single row of a deeper folder', rows.length === 103 && secs.length >= 3 && secs.length <= 10 && secs.every((s) => s.ids.length > 1), secs.map((s) => s.key + ':' + s.ids.length));
    t.noErrors('big: no page errors');

    /* ---------- Every core file: selecting it draws no arc into a shared dependency ---------- */
    const core = g.nodes.filter((n) => n.layer !== 'test' && !LATE[n.layer] && !n.hub).map((n) => n.id);
    await t.fresh(HUB);
    const intoHub = {};
    for (const id of core) {
      await B.ev(`T.pick('${id}')`);
      const n = (await B.ev(`[].map.call(document.querySelectorAll('#g-lane path.arc'),function(p){return p.dataset.t||'';})`)).filter((x) => HUBS.includes(x)).length;
      if (n) intoHub[byId[id].path] = n;
    }
    t.check(`selecting each of the ${core.length} core files draws no arc into a shared dependency`, core.length > 15 && Object.keys(intoHub).length === 0, intoHub);
    t.noErrors('every core file: no page errors');

    /* ---------- Layout in both themes, 1440 and 800 ---------- */
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      for (const w of [1440, 800]) {
        await t.fresh(HUB, { width: w, height: w === 800 ? 1000 : 900, dark });
        await B.ev(`T.pick('${gas}')`); await sleep(150);
        t.check(`hub ${w}px ${th}: no horizontal page scroll`, await B.ev('T.hscroll()') <= 0, await B.ev('T.hscroll()'));
        if (w === 800) t.check(`hub 800px ${th}: the list stacks above the detail panel`, await B.ev(`document.querySelector('.g-side').getBoundingClientRect().bottom<=document.getElementById('g-detail').getBoundingClientRect().top+1`));
        await B.ev(`document.getElementById('graph').scrollIntoView()`); await sleep(100);
        await t.shot(`${w}-${th}-list`, '.g-work', 1500);
        await t.shot(`${w}-${th}-neighbourhood`, '#g-detail', 600);
        await B.ev(`document.getElementById('g-group').click()`); await sleep(100);
        const s = await B.ev('T.secs()');
        const fold = s.slice(1).find((x) => !x.ids.includes(gas) && x.ids.length > 2);
        await B.ev(`T.head(${JSON.stringify(fold.key)}).click()`); await sleep(100);
        await t.shot(`${w}-${th}-grouped`, '.g-side', 1500);
        t.check(`hub ${w}px ${th} grouped: no horizontal page scroll`, await B.ev('T.hscroll()') <= 0);
        await B.ev(`document.getElementById('g-group').click()`);
        await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(300);
        await t.shot(`${w}-${th}-map`, '#g-canvas', 900);
        t.check(`hub ${w}px ${th} map: no horizontal page scroll`, await B.ev('T.hscroll()') <= 0);
        t.noErrors(`hub ${w}px ${th}: no page errors`);
      }
      if (t.shots) {
        await t.fresh(HUB, { dark });
        await B.ev(`document.getElementById('g-all').click()`); await B.ev(`T.pick('${gas}')`); await sleep(100);
        await t.shot(`1440-${th}-alllinks`, '.g-side', 1500);
      }
    }
  },
};
