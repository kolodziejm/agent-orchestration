'use strict';
// The reading graph: list order, selection, lane arcs, neighbourhood, cross-PR chips and header group, keyboard, map,
// read marks (and their migration), notes and copying them, narrow windows, a 103-row PR, and the sticky list.
const path = require('path');
const { sleep, viewerOrder } = require('./lib');

module.exports = {
  name: 'core',
  weight: 26, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const STACK = t.url(t.fixtures, 'stack', 'review.html'), HUB = t.url(t.fixtures, 'hub', 'review.html'), BIG = t.url(t.fixtures, 'big', 'review.html');
    const ORDER = (o) => Object.fromEntries(Object.entries(o).map(([m, prs]) => [m, Object.fromEntries(Object.entries(prs).map(([k, v]) => [k, v.on]))]));

    /* ---------- Stack sample: ordering, selection, arcs, neighbourhood, chips, ext group ---------- */
    const exp = viewerOrder(path.join(t.fixtures, 'stack', 'review.html'));
    const order = ORDER(exp.order);
    await t.fresh(STACK);
    t.noErrors('stack: no page errors on load');
    t.check('stack: default view is the list (map hidden)', await B.ev(`document.getElementById('g-canvas').hidden&&document.querySelector('[data-v=list]').getAttribute('aria-pressed')==='true'`));
    for (const mode of ['top', 'bottom']) {
      await B.ev(`document.querySelector('[data-o=${mode}]').click()`);
      for (const k of ['A', 'B', 'C']) {
        await B.ev(`T.tabTo('${k}')`);
        const rows = await B.ev('T.rows()');
        const on = order[mode][k];
        const want = Object.keys(on).sort((a, b) => on[a] - on[b]);
        t.check(`stack ${mode} ${k}: list order and numbers match computeOrder`, JSON.stringify(rows.map((r) => r.id)) === JSON.stringify(want) && rows.every((r) => r.no === on[r.id]), { rows, on });
      }
    }
    await B.ev(`document.querySelector('[data-o=top]').click()`);
    await B.ev(`T.tabTo('A')`);
    const testIndent = await B.ev(`T.rows().filter(function(r){return r.t;}).map(function(r){return r.id;})`);
    const aTests = exp.data.prs[0].nodes.filter((n) => n.layer === 'test').map((n) => n.id);
    t.check('stack A: tests are indented under their subject', JSON.stringify(testIndent) === JSON.stringify(aTests), { testIndent, aTests });
    const before = await B.ev('T.rows()');
    await B.ev(`document.getElementById('g-tests').click()`);
    const hidden = await B.ev('T.rows()');
    t.check('tests filter hides test rows and keeps the other step numbers', hidden.length === before.length - aTests.length && hidden.every((r) => before.find((x) => x.id === r.id).no === r.no), { before, hidden });
    await B.ev(`document.getElementById('g-tests').click()`);
    // Selection sync on tab B.
    await B.ev(`T.tabTo('B')`);
    const bNodes = Object.fromEntries(exp.data.prs[1].nodes.map((n) => [n.path, n]));
    const ctrl = bNodes['src/rest/item.controller.ts'].id, routes = bNodes['src/rest/routes.ts'].id, cfg = bNodes['config/app.yaml'].id;
    await B.ev(`T.pick('${ctrl}')`);
    await sleep(150);
    const s1 = await B.ev(`({sel:T.sel(),h4:document.querySelector('#g-detail h4').textContent,title:document.getElementById('dv-title').textContent,files:[].map.call(document.querySelectorAll('#dv-files .df .pth'),function(e){return e.textContent;}),no:+T.row('${ctrl}').querySelector('.no').textContent})`);
    t.check('selection syncs list, detail, and diff', s1.sel === ctrl && s1.h4 === `Step ${s1.no} · item.controller.ts` && s1.title === s1.h4 && s1.files[0] === 'src/rest/item.controller.ts', s1);
    // Arcs: controller -> config (dep, same PR); routes -> controller (use); the test arc to its subject is left out.
    const arcs = await B.ev(`({dep:document.querySelectorAll('#g-lane path.arc.dep').length,use:document.querySelectorAll('#g-lane path.arc.use').length,all:document.querySelectorAll('#g-lane path.arc').length,dots:document.querySelectorAll('#g-lane circle').length})`);
    t.check('lane highlights the selected file\'s arcs (1 blue dependency, 1 orange dependent)', arcs.dep === 1 && arcs.use === 1 && arcs.dots === 4, arcs);
    const rowsB = await B.ev('T.rows()');
    t.check('rows of dependencies and dependents are marked', rowsB.find((r) => r.id === cfg).dep && rowsB.find((r) => r.id === routes).use, rowsB);
    // Neighbourhood: deps include the two files of PR A plus config; dependents include routes and C's useItems (later PR).
    const nb = await B.ev(`({dep:[].map.call(document.querySelectorAll('.g-nbc.dep .g-nbi'),function(b){return b.dataset.go;}),use:[].map.call(document.querySelectorAll('.g-nbc.use .g-nbi'),function(b){return b.dataset.go;}),lines:document.querySelectorAll('.g-nbl > path').length,x:document.querySelectorAll('.g-nbi.x').length})`);
    const aSvc = exp.data.prs[0].nodes.find((n) => n.path === 'src/logic/item.service.ts').id;
    const cUse = exp.data.prs[2].nodes.find((n) => n.path === 'web/ui/useItems.ts').id;
    t.check('neighbourhood lists same-PR and cross-PR dependencies and dependents, with connectors', nb.dep.includes(cfg) && nb.dep.includes(aSvc) && nb.use.includes(routes) && nb.use.includes(cUse) && nb.lines === nb.dep.length + nb.use.length && nb.x === 3, nb);
    await B.ev(`document.querySelector('.g-nbi[data-go="${routes}"]').click()`);
    t.check('neighbourhood click selects that file', await B.ev(`T.sel()`) === routes);
    t.check('focus moves to the new detail heading after a neighbourhood click', await B.ev(`document.activeElement===document.querySelector('#g-detail h4')`));
    await B.ev(`document.querySelector('.g-nbi[data-go="${ctrl}"]').click()`);
    await B.ev(`document.querySelector('.g-nbi[data-go="${aSvc}"]').click()`);
    t.check('cross-PR neighbourhood item jumps to that PR\'s tab and file', await B.ev(`T.tab()==='A'&&T.sel()==='${aSvc}'`), await B.ev(`[T.tab(),T.sel()]`));
    // Row chips.
    await B.ev(`T.tabTo('A')`);
    const schema = exp.data.prs[0].nodes.find((n) => n.path === 'src/contracts/item.schema.ts').id;
    const chips = await B.ev(`[].map.call(T.row('${schema}').querySelectorAll('.g-xc'),function(c){return [c.textContent,c.title];})`);
    t.check('row chips show later PRs that use the file (←B, ←C) with paths in the title', chips.length === 2 && chips[0][0] === '←B' && chips[1][0] === '←C' && /used by B #102: src\/rest\/item.controller.ts/.test(chips[0][1]), chips);
    await B.ev(`T.row('${schema}').querySelectorAll('.g-xc')[1].click()`);
    const cList = exp.data.prs[2].nodes.find((n) => n.path === 'web/ui/ItemList.tsx').id;
    t.check('"used by" chip jumps to the later PR and selects the file', await B.ev(`T.tab()==='C'&&T.sel()==='${cList}'`), await B.ev(`[T.tab(),T.sel()]`));
    const uses = await B.ev(`[].map.call(T.row('${cList}').querySelectorAll('.g-xc'),function(c){return c.textContent;})`);
    t.check('"uses" chip on the later PR\'s row', JSON.stringify(uses) === '["→A"]', uses);
    // Ext header group on C: one sub-group per earlier PR.
    const ext = await B.ev(`({hidden:document.getElementById('g-xlist').hidden,groups:[].map.call(document.querySelectorAll('.g-xg .tag'),function(t){return t.textContent;}),rows:[].map.call(document.querySelectorAll('.g-xr .no'),function(t){return t.textContent;})})`);
    t.check('earlier-PR files sit in a header group, one sub-group per PR', !ext.hidden && JSON.stringify(ext.groups) === '["A #101","B #102"]' && ext.rows.length === 2, ext);
    await B.ev(`T.pick('${cList}')`);
    t.check('selected file\'s earlier-PR dependency is marked in the header group', await B.ev(`document.querySelector('.g-xg li.dep .g-xr .no').textContent==='${schema}'`));
    await B.ev(`document.getElementById('g-ext').click()`);
    t.check('"Files from earlier PRs" off hides the header group', await B.ev(`document.getElementById('g-xlist').hidden`));
    await B.ev(`document.getElementById('g-ext').click()`);
    await B.ev(`document.querySelectorAll('.g-xr')[1].click()`);
    t.check('header-group row jumps to its PR and file', await B.ev(`T.tab()==='B'&&T.sel()==='${ctrl}'`), await B.ev(`[T.tab(),T.sel()]`));
    // Tab memory.
    await B.ev(`T.tabTo('C')`);
    t.check('switching back to a tab restores its last selection', await B.ev(`T.sel()==='${cList}'`));
    // Keyboard.
    await B.ev(`T.tabTo('B')`);
    await B.ev(`T.row(T.sel()).querySelector('.nm').focus()`);
    const kStart = await B.ev(`T.rows().map(function(r){return r.id;})`);
    const i0 = kStart.indexOf(await B.ev('T.sel()'));
    await B.key('ArrowDown');
    const f1 = await B.ev(`document.activeElement.closest('li').dataset.id`);
    t.check('ArrowDown moves focus to the next row without selecting', f1 === kStart[i0 + 1] && await B.ev('T.sel()') === kStart[i0], { f1, kStart, i0 });
    await B.key('Enter');
    t.check('Enter opens the focused row', await B.ev('T.sel()') === kStart[i0 + 1]);
    await B.key('Home');
    t.check('Home moves to the first row', await B.ev(`document.activeElement.closest('li').dataset.id`) === kStart[0]);
    t.check('roving tabindex: one row button is tabbable', await B.ev(`document.querySelectorAll('#g-order .nm[tabindex="0"]').length`) === 1);
    // Prev/next.
    await B.ev(`T.pick('${kStart[0]}')`);
    await B.ev(`document.getElementById('g-next').click()`);
    t.check('Next moves to the next step', await B.ev('T.sel()') === kStart[1]);
    await B.ev(`document.querySelector('#g-detail [data-pn=prev]').click()`);
    t.check('detail "previous" goes back and keeps focus on the prev/next control', await B.ev('T.sel()') === kStart[0] && (await B.ev(`document.activeElement.tagName`) === 'H4' || await B.ev(`!!document.activeElement.dataset.pn`)));
    // Read marks.
    await B.ev(`T.row('${kStart[0]}').querySelector('input').click()`);
    const key = 'review-map:stack-sample:';
    const kPath = exp.data.prs[1].nodes.find((n) => n.id === kStart[0]).path;
    t.check('read checkbox marks the row and persists by PR and path', await B.ev(`T.row('${kStart[0]}').classList.contains('done')&&JSON.parse(localStorage.getItem('${key}read')).B[${JSON.stringify(kPath)}]===1`), await B.ev(`localStorage.getItem('${key}read')`));
    // Map toggle.
    await B.ev(`document.querySelector('[data-v=map]').click()`);
    await sleep(150);
    const m = await B.ev(`({hidden:document.getElementById('g-canvas').hidden,nodes:document.querySelectorAll('#g-canvas .nd').length,rows:T.rows().length,ext:document.querySelectorAll('.g-xr').length,stored:localStorage.getItem('${key}view'),path:!document.getElementById('g-pathl').hidden,font:Math.min.apply(null,[].map.call(document.querySelectorAll('#g-canvas text'),function(t){return t.getBoundingClientRect().height;}))})`);
    t.check('map toggle shows every row and earlier-PR file as a node and stores the view', !m.hidden && m.nodes === m.rows + m.ext && m.stored === 'map' && m.path, m);
    t.check('map labels are not scaled down (text boxes at least 11px tall)', m.font >= 11, m);
    await B.ev(`document.querySelectorAll('#g-canvas .nd')[3].dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
    const mapSel = await B.ev(`({sel:T.sel(),on:(document.querySelector('#g-canvas .nd.on title')||{}).textContent})`);
    t.check('clicking a map node selects it in the list and detail', !!mapSel.sel && mapSel.on && mapSel.on.startsWith(exp.data.prs[1].nodes.find((n) => n.id === mapSel.sel).path), mapSel);
    await t.reload(STACK);
    t.check('the chosen view survives a reload', await B.ev(`!document.getElementById('g-canvas').hidden&&document.querySelector('[data-v=map]').getAttribute('aria-pressed')==='true'`));
    await B.ev(`T.tabTo('B')`);
    t.check('read mark survives a reload', await B.ev(`T.row('${kStart[0]}').classList.contains('done')&&document.querySelector('#g-canvas .nd.done')!==null`));
    // Lane: only the selected file's arcs by default; hover hints; "All links" draws every arc and is remembered.
    await B.ev(`document.querySelector('[data-v=list]').click();T.tabTo('A')`);
    const aId = (p) => exp.data.prs[0].nodes.find((n) => n.path === p).id;
    const dom = aId('src/domain/item.ts'), svc = aId('src/logic/item.service.ts');
    const arcCount = `({all:document.querySelectorAll('#g-lane path.arc').length,dep:document.querySelectorAll('#g-lane path.arc.dep').length,use:document.querySelectorAll('#g-lane path.arc.use').length,pk:document.querySelectorAll('#g-lane path.arc.pk').length,dots:document.querySelectorAll('#g-lane circle').length,box:document.getElementById('g-all').checked})`;
    await B.ev(`T.tabTo('B');T.tabTo('A')`);
    const l0 = await B.ev(arcCount);
    t.check('lane: with nothing selected only the dots show (no arcs)', l0.all === 0 && l0.dots === 5 && !l0.box, l0);
    await B.ev(`T.row('${svc}').dispatchEvent(new MouseEvent('mouseenter'))`);
    const lh = await B.ev(arcCount);
    t.check('lane: hovering a row hints its arcs', lh.all === 2 && lh.pk === 2, lh);
    await B.ev(`T.row('${svc}').dispatchEvent(new MouseEvent('mouseleave'));T.pick('${dom}')`);
    const l1 = await B.ev(arcCount);
    t.check('lane: selecting draws only that file\'s arcs (1 blue, 1 orange)', l1.all === 2 && l1.dep === 1 && l1.use === 1, l1);
    await B.ev(`document.getElementById('g-all').click()`);
    const l2 = await B.ev(arcCount);
    t.check('lane: "All links" adds the other arcs and is stored under its own key', l2.all === 3 && l2.dep === 1 && l2.use === 1 && await B.ev(`localStorage.getItem('${key}arcs')`) === 'all', l2);
    await t.reload(STACK);
    const l3 = await B.ev(arcCount);
    t.check('lane: "All links" survives a reload and draws arcs with nothing selected', l3.box && l3.all === 3 && l3.dep === 0, l3);
    await B.ev(`document.getElementById('g-all').click()`);
    t.check('lane: turning "All links" off clears the arcs and is stored', await B.ev(`document.querySelectorAll('#g-lane path.arc').length===0&&localStorage.getItem('${key}arcs')==='sel'`));
    await B.ev(`document.querySelector('[data-v=map]').click();T.tabTo('B')`);
    // Map keyboard: one Tab stop, arrows move through the band then the steps, Enter opens.
    const mk0 = await B.ev(`(function(){var z=document.querySelectorAll('#g-canvas .nd[tabindex="0"]');return {zero:z.length,first:z[0]===document.querySelector('#g-canvas .nd')};})()`);
    t.check('with no selection the first map node is the only Tab stop', mk0.zero === 1 && mk0.first, mk0);
    await B.ev(`T.pick('${kStart[1]}')`);
    const mk = await B.ev(`(function(){var z=document.querySelectorAll('#g-canvas .nd[tabindex="0"]');return {zero:z.length,all:document.querySelectorAll('#g-canvas .nd').length,on:z[0]&&z[0].classList.contains('on')};})()`);
    t.check('after selecting, the selected map node is the only Tab stop', mk.zero === 1 && mk.all > 1 && mk.on, mk);
    await B.ev(`document.querySelector('#g-canvas .nd[tabindex="0"]').focus()`);
    const seq = await B.ev(`[].map.call(document.querySelectorAll('#g-canvas .nd'),function(g){return g.querySelector('title').textContent.split('\\n')[0];})`);
    const f0 = await B.ev(`document.activeElement.querySelector('title').textContent.split('\\n')[0]`);
    await B.key('ArrowRight');
    const f1m = await B.ev(`({p:document.activeElement.querySelector('title').textContent.split('\\n')[0],t:document.activeElement.getAttribute('tabindex'),z:document.querySelectorAll('#g-canvas .nd[tabindex="0"]').length})`);
    t.check('ArrowRight moves map focus to the next node and keeps one Tab stop', f1m.p === seq[seq.indexOf(f0) + 1] && f1m.t === '0' && f1m.z === 1, { seq, f0, f1m });
    await B.key('Home');
    t.check('Home moves map focus to the first node', await B.ev(`document.activeElement.querySelector('title').textContent.split('\\n')[0]`) === seq[0]);
    await B.key('End');
    await B.key('Enter');
    const lastPath = seq[seq.length - 1];
    t.check('Enter on a map node opens it', await B.ev(`(document.querySelector('#g-detail .p')||{}).textContent`) === lastPath, lastPath);
    await B.ev(`document.querySelector('[data-v=list]').click()`);
    t.check('switching back to the list hides the map', await B.ev(`document.getElementById('g-canvas').hidden&&localStorage.getItem('${key}view')==='list'`));
    t.noErrors('stack: no page errors after the interaction run');

    /* ---------- Read marks: keyed by PR and path, so a rebuild that renumbers ids keeps them on their files ---------- */
    await t.fresh(STACK);
    const aNodes = exp.data.prs[0].nodes, schemaA = aNodes.find((n) => n.path === 'src/contracts/item.schema.ts').id;
    await B.ev(`T.row('${schemaA}').querySelector('input').click()`);
    const ren = viewerOrder(path.join(t.fixtures, 'stack', 'review-renumbered.html')).data.prs[0].nodes;
    const schemaNew = ren.find((n) => n.path === 'src/contracts/item.schema.ts').id, holder = ren.find((n) => n.id === schemaA).path;
    await t.reload(t.url(t.fixtures, 'stack', 'review-renumbered.html'));
    const rn = await B.ev(`({done:T.rows().filter(function(r){return r.done;}).map(function(r){return r.id;})})`);
    t.check(`read mark follows its file after a rebuild renumbers ids (${schemaA} -> ${schemaNew}; ${schemaA} is now ${holder})`, schemaNew !== schemaA && JSON.stringify(rn.done) === JSON.stringify([schemaNew]), rn);
    // One-time migration of id-based marks from earlier versions; the old key stays for older pages.
    const svcA = aNodes.find((n) => n.path === 'src/logic/item.service.ts').id;
    await t.fresh(STACK, { seed: `localStorage.setItem('${key}done',JSON.stringify({'${svcA}':1,'Z99':1}))` });
    const mig = await B.ev(`({done:T.rows().filter(function(r){return r.done;}).map(function(r){return r.id;}),read:JSON.parse(localStorage.getItem('${key}read')),old:localStorage.getItem('${key}done')})`);
    t.check('id-based read marks migrate once to PR and path; unknown ids are dropped; the old key is kept', JSON.stringify(mig.done) === JSON.stringify([svcA]) && JSON.stringify(mig.read) === JSON.stringify({ A: { 'src/logic/item.service.ts': 1 } }) && mig.old === JSON.stringify({ [svcA]: 1, Z99: 1 }), mig);
    await B.ev(`T.row('${svcA}').querySelector('input').click()`);
    await t.reload(STACK);
    t.check('after migration, unchecking sticks (the old key is not migrated again)', await B.ev(`T.rows().every(function(r){return !r.done;})&&localStorage.getItem('${key}read')==='{}'`), await B.ev(`localStorage.getItem('${key}read')`));
    t.noErrors('read marks: no page errors');

    /* ---------- Themes: re-render in dark keeps the selection; C's map has the earlier-PR band ---------- */
    await t.fresh(STACK);
    await B.ev(`T.tabTo('B');T.pick('${ctrl}');document.getElementById('nt-panel').open=false;document.querySelector('.g-tabs-row').scrollIntoView()`);
    await sleep(250);
    await t.shot('stack-1440-light-list');
    await t.theme(true);
    await sleep(250);
    await t.shot('stack-1440-dark-list');
    t.check('dark theme re-render keeps the selection and has no errors', await B.ev('T.sel()') === ctrl && B.errors.length === 0, B.errors);
    await B.ev(`T.tabTo('C');document.querySelector('[data-v=map]').click();document.querySelector('.g-tabs-row').scrollIntoView()`);
    await sleep(250);
    await t.shot('stack-1440-dark-map');
    await t.theme(false);
    await sleep(200);
    await t.shot('stack-1440-light-map');
    const cMap = await B.ev(`({ext:document.querySelectorAll('#g-canvas .gl').length,shelf:!!document.querySelector('#g-canvas .shl')})`);
    t.check('stack C map: earlier-PR band with one label per PR, shelf present', cMap.ext === 2 && cMap.shelf, cMap);

    /* ---------- Notes: line, file, and PR notes; kinds, filter, copy, jump, and stored-data robustness ---------- */
    await t.fresh(STACK);
    await B.ev(`T.tabTo('B');T.pick('${ctrl}')`);
    await sleep(150);
    await B.ev(`document.querySelector('#dv-files td.ln[data-s=new][data-l="2"]').click()`);
    await B.ev(`document.querySelector('[data-nt=add]').click()`);
    await B.ev(`T.save(document.querySelector('#dv-files .nt-ed'),'issue',${JSON.stringify('Type the return.\n# Heading in a note\nTitle\n===\n<!-- unclosed\n```js\nconst open = true;')})`);
    const ln = await B.ev(`({count:document.getElementById('nt-count').textContent,marker:!!document.querySelector('#dv-files td.ln.nk.k-issue'),chip:(T.row('${ctrl}').querySelector('.g-nk.k-issue')||{}).textContent})`);
    t.check('line note: saved, marked in the diff, and shown as a kind chip on the row', ln.count === '1' && ln.marker && ln.chip === '!', ln);
    await B.ev(`document.querySelector('#dv-files .nt-fadd').click()`);
    await B.ev(`T.save(document.querySelector('#dv-files .nt-fed'),'ok','Whole file looks fine.')`);
    await B.ev(`document.getElementById('nt-pr-add').click()`);
    await B.ev(`T.save(document.getElementById('nt-pred'),'question','Why two PRs?')`);
    const n3 = await B.ev(`({count:document.getElementById('nt-count').textContent,chips:[].map.call(T.row('${ctrl}').querySelectorAll('.g-nk'),function(c){return c.textContent;}),file:(document.querySelector('#dv-files .nt-fk-slot .nt-k')||{}).textContent})`);
    t.check('file and PR notes: saved; row shows one chip per kind (PR notes excluded)', n3.count === '3' && JSON.stringify(n3.chips) === '["!","✓"]' && n3.file === '✓ 1', n3);
    await B.ev(`document.querySelector('#nt-filter .k-issue').click()`);
    const filt = await B.ev(`({items:document.querySelectorAll('#nt-list li').length,copy:document.getElementById('nt-copy').textContent})`);
    t.check('kind filter narrows the list and the copy label', filt.items === 1 && filt.copy === 'Copy shown notes (1)', filt);
    const copied = await t.copy();
    t.check('copy notes produces Markdown with the issue and its path:line', /## Issue \(1\)/.test(copied) && /src\/rest\/item.controller.ts:2/.test(copied), copied);
    await B.ev(`document.querySelector('#nt-filter .k-issue').click()`);
    await B.ev(`T.tabTo('A')`);
    await B.ev(`[].find.call(document.querySelectorAll('#nt-list .nt-loc'),function(b){return /:2 /.test(b.textContent);}).click()`);
    await sleep(300);
    t.check('note jump opens the PR tab, the file, and focuses the line', await B.ev(`T.tab()==='B'&&T.sel()==='${ctrl}'&&document.activeElement.matches('td.ln[data-l="2"]')`), await B.ev(`[T.tab(),T.sel(),document.activeElement.outerHTML.slice(0,80)]`));
    await B.key('ArrowUp');
    t.check('line-number keyboard navigation still works after a jump', await B.ev(`document.activeElement.matches('td.ln[data-l="1"]')`), await B.ev(`document.activeElement.outerHTML.slice(0,80)`));
    // A kind change while the filter shows only questions moves focus into the notes panel.
    await B.ev(`document.querySelector('#nt-filter .k-question').click()`);
    await B.ev(`document.querySelector('#nt-list [data-a=edit]').click()`);
    await B.ev(`(function(){var li=document.querySelector('#nt-list li');li.querySelector('input[value=issue]').click();[].find.call(li.querySelectorAll('button'),function(b){return b.classList.contains('pri');}).click();})()`);
    await sleep(100);
    const f3 = await B.ev(`({tag:document.activeElement.tagName,inPanel:!!document.activeElement.closest('#nt-panel'),status:document.getElementById('nt-status').textContent})`);
    t.check('a kind change the filter hides moves focus into the notes panel, not to body', f3.tag !== 'BODY' && f3.inPanel && f3.status === 'Saved. The kind filter now hides this note.', f3);
    await B.ev(`document.querySelector('#nt-filter .k-question').click()`);
    const allMd = await t.copy();
    const mdName = 'copied Markdown (CommonMark): a note\'s headings, setext line, open comment, and open fence do not break the structure';
    if (t.micromark) {
      const htmlMd = t.micromark(allMd, { allowDangerousHtml: true });
      const lv = (n) => (htmlMd.match(new RegExp('<h' + n + '>', 'g')) || []).length;
      const mdHeads = { h1: lv(1), h2: lv(2), h3: lv(3), h4: lv(4), h5: lv(5) };
      t.check(mdName, mdHeads.h1 === 1 && mdHeads.h2 === 2 && mdHeads.h3 === 2 && mdHeads.h4 === 3 && mdHeads.h5 === 1 && /<h5>Heading in a note<\/h5>/.test(htmlMd) && /<p>Whole file looks fine.<\/p>/.test(htmlMd) && /<h4>3\./.test(htmlMd), { mdHeads, allMd });
    } else t.skip(mdName, 'micromark is not installed');
    await B.ev(`document.getElementById('nt-panel').scrollIntoView()`);
    await t.shot('notes-1440-light', '#nt-panel');
    await B.ev(`T.pick('${ctrl}');document.querySelector('.g-work').scrollIntoView()`);
    await sleep(200);
    await t.shot('notes-row-chips-1440-light', '.g-side');
    t.noErrors('notes: no page errors');
    // Kinds named after Object.prototype properties load as questions; a stored last kind "constructor" falls back too.
    const bad = JSON.stringify([
      { scope: 'pr', kind: 'constructor', pr: 'A', text: 'a' }, { scope: 'pr', kind: '__proto__', pr: 'A', text: 'b' },
      { scope: 'pr', kind: 'toString', pr: 'A', text: 'c' }, { scope: 'pr', kind: 'issue', pr: 'A', text: 'd' }]);
    await t.fresh(STACK, { seed: `localStorage.setItem('${key}notes',${JSON.stringify(bad)});localStorage.setItem('${key}notekind','constructor')` });
    const fx1 = await B.ev(`({kinds:[].map.call(document.querySelectorAll('#nt-list li .nt-h .nt-k'),function(c){return c.className;}),q:document.querySelector('#nt-filter .k-question').textContent})`);
    await B.ev(`document.getElementById('nt-pr-add').click()`);
    const f1b = await B.ev(`document.querySelector('#nt-pred input:checked').value`);
    t.check('stored kinds "constructor", "__proto__", "toString" load as questions', fx1.kinds.filter((c) => /k-question/.test(c)).length === 3 && /3$/.test(fx1.q), fx1);
    t.check('a stored last kind "constructor" falls back to question in the editor', f1b === 'question', f1b);
    t.noErrors('prototype-named kinds: no page errors');
    // The clear-all confirmation counts unreadable stored entries too, and clearing removes them.
    const mixed = JSON.stringify([{ scope: 'pr', kind: 'issue', pr: 'A', text: 'x' }, { bogus: true }, 7]);
    await t.fresh(STACK, { seed: `localStorage.setItem('${key}notes',${JSON.stringify(mixed)})` });
    await B.ev(`document.getElementById('nt-clear').click()`);
    const f2 = await B.ev(`document.querySelector('#nt-confirm span').textContent`);
    t.check('clear-all confirmation names the unreadable entries', /\(1\)/.test(f2) && /\(2\)/.test(f2) && /cannot read/.test(f2), f2);
    await B.ev(`[].find.call(document.querySelectorAll('#nt-confirm button'),function(b){return b.classList.contains('dng');}).click()`);
    t.check('clearing removes the unreadable entries too', await B.ev(`localStorage.getItem('${key}notes')`) === '[]');
    await t.fresh(STACK, { seed: `localStorage.setItem('${key}notes',${JSON.stringify(JSON.stringify([{ bogus: true }]))})` });
    t.check('"Clear all" stays usable when only unreadable entries are stored', await B.ev(`!document.getElementById('nt-clear').disabled`));
    await B.ev(`document.getElementById('nt-clear').click()`);
    t.check('that confirmation also names them', /\(0\).*\(1\)/.test(await B.ev(`document.querySelector('#nt-confirm span').textContent`)));
    t.noErrors('unreadable notes: no page errors');

    /* ---------- Narrow window (800px) ---------- */
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      for (const [name, url] of [['stack', STACK], ['hub', HUB]]) {
        await t.fresh(url, { width: 800, height: 1000, dark });
        await B.ev(`T.pick(T.rows()[2].id)`);
        await sleep(300);
        const n = await B.ev(`({h:T.hscroll(),stack:document.querySelector('.g-side').getBoundingClientRect().bottom<=document.querySelector('#g-detail').getBoundingClientRect().top+1,lane:document.getElementById('g-lane').getBoundingClientRect().width})`);
        t.check(`${name} 800px ${th}: no horizontal page scroll, list above detail, lane narrowed`, n.h <= 0 && n.stack && n.lane <= 44, n);
        await B.ev(`document.querySelector('.g-tabs-row').scrollIntoView()`);
        await t.shot(`${name}-800-${th}`);
        await B.ev(`document.querySelector('[data-v=map]').click()`);
        await sleep(200);
        t.check(`${name} 800px ${th} map: still no horizontal page scroll`, await B.ev('T.hscroll()') <= 0);
        await B.ev(`document.querySelector('[data-v=list]').click()`);
        await B.ev(`document.querySelector('#g-detail').scrollIntoView()`);
        await t.shot(`${name}-800-${th}-detail`);
        t.noErrors(`${name} 800px ${th}: no page errors`);
      }
    }

    /* ---------- Large sample (103 rows): lane thinning ---------- */
    const expBig = viewerOrder(path.join(t.fixtures, 'big', 'review.html'));
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(BIG, { dark });
      const rows = await B.ev('T.rows()');
      const on = expBig.order.top.P.on;
      t.check(`big ${th}: 103 rows in computeOrder order`, rows.length === 103 && rows.every((r, i) => i === 0 || on[r.id] > on[rows[i - 1].id]) && rows.every((r) => r.no === on[r.id]), rows.length);
      const none = await B.ev(`document.querySelectorAll('#g-lane path.arc').length`);
      const sid = rows[40].id;
      await B.ev(`T.pick('${sid}')`);
      await sleep(200);
      const withSel = await B.ev(`({all:document.querySelectorAll('#g-lane path.arc').length,dep:document.querySelectorAll('#g-lane path.arc.dep').length,use:document.querySelectorAll('#g-lane path.arc.use').length})`);
      const p = expBig.data.prs[0], vis = new Set(rows.map((r) => r.id));
      const wantDep = p.edges.filter((e) => e.from === sid && vis.has(e.to) && e.kind !== 'test').length;
      const wantUse = p.edges.filter((e) => e.to === sid && vis.has(e.from) && e.kind !== 'test').length;
      t.check(`big ${th}: by default the lane is empty with no selection and draws only the selected file's arcs`, none === 0 && withSel.dep === wantDep && withSel.use >= wantUse && withSel.all === withSel.dep + withSel.use, { none, withSel, wantDep, wantUse });
      await B.ev(`document.getElementById('g-all').click()`);
      const allOn = await B.ev(`({all:document.querySelectorAll('#g-lane path.arc').length,dep:document.querySelectorAll('#g-lane path.arc.dep').length,use:document.querySelectorAll('#g-lane path.arc.use').length})`);
      t.check(`big ${th}: "All links" over 60 rows adds nearby arcs but not all ${p.edges.length}`, allOn.all > withSel.all && allOn.all < p.edges.length && allOn.dep === withSel.dep && allOn.use === withSel.use, { allOn, withSel });
      await B.ev(`document.getElementById('g-all').click()`);
      await B.ev(`document.getElementById('g-detail').scrollIntoView()`);
      await sleep(200);
      await t.shot(`big-1440-${th}-list-detail`);
      await B.ev(`document.querySelector('[data-v=map]').click();document.getElementById('g-canvas').scrollIntoView()`);
      await sleep(300);
      await t.shot(`big-1440-${th}-map`);
      t.noErrors(`big ${th}: no page errors`);
    }

    /* ---------- Hub sample (about 45 files): list and map in both themes, sticky list beside a long diff ---------- */
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(HUB, { dark });
      await B.ev(`T.pick(T.rows()[3].id);document.getElementById('nt-panel').open=false;document.querySelector('.g-tabs-row').scrollIntoView()`);
      await sleep(300);
      await t.shot(`hub-1440-${th}-list`);
      await B.ev(`document.querySelector('[data-v=map]').click();document.getElementById('g-canvas').scrollIntoView()`);
      await sleep(300);
      await t.shot(`hub-1440-${th}-map`);
      t.noErrors(`hub ${th}: no page errors`);
    }
    await t.fresh(HUB);
    const long = await B.ev(`(function(){var d=JSON.parse(document.getElementById('diff-data').textContent),best=null,n=0;T.rows().forEach(function(r){var l=(d[r.id]||[]).reduce(function(s,f){return s+f.diff.split('\\n').length;},0);if(l>n){n=l;best=r.id;}});return best;})()`);
    await B.ev(`T.pick('${long}')`);
    await sleep(300);
    await B.ev(`[].forEach.call(document.querySelectorAll('#dv-files details.df'),function(d){d.open=true;});window.scrollTo(0,document.getElementById('dv').getBoundingClientRect().top+scrollY+300)`);
    await sleep(200);
    const sticky = await B.ev(`(function(){var s=document.querySelector('.g-side').getBoundingClientRect(),d=document.getElementById('dv').getBoundingClientRect();return {sideTop:s.top,sideBottom:s.bottom,dvTop:d.top,dvBottom:d.bottom,vh:innerHeight};})()`);
    t.check('hub: list stays pinned beside a long diff while scrolling it', Math.abs(sticky.sideTop - 12) < 2 && sticky.dvTop < 0 && sticky.dvBottom > sticky.vh, sticky);
    await t.shot('hub-1440-light-list-beside-diff');
    const other = await B.ev(`T.rows()[8].id`);
    await B.ev(`T.pick('${other}')`);
    await sleep(700);
    t.check('hub: selecting from the pinned list scrolls the detail back into view', await B.ev(`(function(){var t=document.getElementById('g-detail').getBoundingClientRect().top;return t>=-2&&t<innerHeight;})()`));
    t.noErrors('hub sticky: no page errors');
  },
};
