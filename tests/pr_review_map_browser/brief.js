'use strict';
// REQUIREMENT: a reader of a large change meets the brief first, then the generated reading budget, then the merge order and the
// graph. A budget entry opens its file at its focus lines (the old side for code the PR removes), as the brief's own code links
// do. Each file has an attention chip, mechanical rows are dimmed, and View › "Only what to read" keeps the risky and novel
// files with their step numbers. A small change has no budget and no map (not even the workspace's List | Map switch), and
// its step list is open by default, though a saved choice still wins. The brief's blocks read in both themes and at phone width.
const { sleep } = require('./lib');

module.exports = {
  name: 'brief',
  weight: 4,
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const LARGE = t.url(t.fixtures, 'brief', 'review.html');
    const SMALL = t.url(t.fixtures, 'brief', 'small', 'review.html');
    const STACK = t.url(t.fixtures, 'stack', 'review.html');
    const NF = (path, side, line) => `(function(){var c=T.cell(${JSON.stringify(path)},${JSON.stringify(side)},${line});return !!c&&c.classList.contains('nf');})()`;
    const ORDER = `(function(){var ids=['brief','budget','stack','graph'],pos=ids.map(function(i){var e=document.getElementById(i);return e?e.compareDocumentPosition(document.getElementById('graph'))&Node.DOCUMENT_POSITION_FOLLOWING:-1;});
      var tops=ids.map(function(i){var e=document.getElementById(i);return e?e.getBoundingClientRect().top+scrollY:-1;});
      return {tops:tops,toc:[].map.call(document.querySelectorAll('nav.toc a'),function(a){return a.getAttribute('href');})};})()`;

    // The page order and the budget.
    await t.fresh(LARGE, { steps: false });
    const order = await B.ev(ORDER);
    t.check('brief: the brief, the reading budget, the merge order, and the graph come in that order', order.tops.every((v) => v >= 0) && order.tops[0] < order.tops[1] && order.tops[1] < order.tops[2] && order.tops[2] < order.tops[3], order);
    t.check('brief: the table of contents lists them', ['#brief', '#budget', '#stack', '#graph'].every((h) => order.toc.includes(h)) && order.toc.indexOf('#budget') < order.toc.indexOf('#stack'), order.toc);
    const budget = await B.ev(`(function(){var s=document.getElementById('budget');return {sum:s.querySelector('.b-sum').textContent,segs:[].map.call(s.querySelectorAll('.b-seg'),function(e){return e.className+':'+Math.round(e.getBoundingClientRect().width);}),
      must:[].map.call(s.querySelectorAll('h3.b-risky~.b-group .b-list>li'),function(l){return l.querySelector('code').textContent;}),refs:s.querySelectorAll('button.g-ref').length,why:[].map.call(s.querySelectorAll('.b-why'),function(e){return e.textContent;})};})()`);
    t.check('brief: the budget says how much of the changed lines to read', /Read 34 of 96 changed lines \(35%\)/.test(budget.sum), budget.sum);
    t.check('brief: its bar has the four classes, wider for more lines', budget.segs.length === 4 && budget.segs.every((x) => +x.split(':')[1] > 0), budget.segs);
    t.check('brief: the files to read are links with their reasons, risky first', budget.refs >= 5 && budget.why.includes('Tenant check dropped') && budget.must.length === 3, budget);

    // A budget entry opens its file at its focus lines on that file's tab.
    await B.ev(`[].find.call(document.querySelectorAll('#budget button.g-ref'),function(b){return /session\\.ts:5-9/.test(b.textContent);}).click()`); await sleep(500);
    const sel = await B.ev(`({tab:T.tab(),path:document.querySelector('#dv-files details.df[open] .pth')&&document.querySelector('#dv-files details.df[open] .pth').textContent})`);
    t.check('brief: a budget entry opens its file on its PR\'s tab', sel.tab === 'A' && sel.path === 'src/auth/session.ts', sel);
    t.check('brief: and flashes its focus lines, nothing else', await B.ev(NF('src/auth/session.ts', 'new', 5)) && await B.ev(NF('src/auth/session.ts', 'new', 9)) && !(await B.ev(NF('src/auth/session.ts', 'new', 12))), sel);
    await sleep(1800);
    await B.ev(`[].find.call(document.querySelectorAll('#budget button.g-ref'),function(b){return /legacy\\.ts:2-4/.test(b.textContent);}).click()`); await sleep(500);
    const old = await B.ev(`({tab:T.tab(),path:document.querySelector('#dv-files details.df[open] .pth')&&document.querySelector('#dv-files details.df[open] .pth').textContent})`);
    t.check('brief: an entry for removed code opens the old side at its lines', old.tab === 'D' && old.path === 'src/auth/legacy.ts' && await B.ev(NF('src/auth/legacy.ts', 'old', 3)) && !(await B.ev(NF('src/auth/legacy.ts', 'old', 8))), old);
    await sleep(1800);

    // The brief's own code links open lines the same way, on the PR of their chip.
    await B.ev(`[].find.call(document.querySelectorAll('#brief .brief-risks button.g-ref'),function(b){return /items\\.ts:3-6/.test(b.textContent);}).click()`); await sleep(500);
    t.check('brief: a risk\'s code link opens its lines on the PR named by its chip', (await B.ev('T.tab()')) === 'B' && await B.ev(NF('src/api/items.ts', 'new', 4)), await B.ev('T.tab()'));
    await B.ev(`[].find.call(document.querySelectorAll('#brief table.contracts button.g-ref'),function(b){return /0042_slot\\.sql:1-8/.test(b.textContent);}).click()`); await sleep(500);
    t.check('brief: a contract\'s code link does too', (await B.ev('T.tab()')) === 'A' && await B.ev(NF('db/migrations/0042_slot.sql', 'new', 3)));
    await B.ev(`document.querySelector('#brief .brief-decisions a').click()`); await sleep(300);
    t.check('brief: a decision line jumps to its card in Before merging', await B.ev(`location.hash==='#dec-1'&&!!document.getElementById('dec-1')`));
    t.noErrors('brief: no page errors on the large page');

    // Attention chips, dimmed mechanical rows, and the "Only what to read" filter.
    await t.fresh(LARGE);
    await B.ev(`T.tabTo('B')`); await sleep(200);
    const rows = await B.ev(`(function(){var r={};T.rows().forEach(function(x){r[x.id]=x;});var d=T.data(),ids={};d.prs.forEach(function(p){p.nodes.forEach(function(n){ids[n.path]=n.id;});});
      function chip(id){var c=T.row(id).querySelector('.g-att');return c&&c.className+'|'+c.textContent;}
      function dim(id){return +getComputedStyle(T.row(id).querySelector('.nm')).opacity;}
      return {lock:chip(ids['package-lock.json']),items:chip(ids['src/api/items.ts']),test:chip(ids['src/api/items.test.ts']),dimLock:dim(ids['package-lock.json']),dimItems:dim(ids['src/api/items.ts']),nos:T.rows().map(function(x){return x.no;}),count:T.rows().length};})()`);
    t.check('brief: each step has an attention chip in words (skip, read, skim)', /a-mechanical\|Skip/.test(rows.lock) && /a-novel\|Read/.test(rows.items) && /a-pattern\|Skim/.test(rows.test), rows);
    t.check('brief: a mechanical row is dimmed, a novel one is not', rows.dimLock < 1 && rows.dimItems === 1, rows);
    await B.ev(`T.tabTo('A')`); await sleep(200);
    t.check('brief: a risky file\'s chip says it must be read', await B.ev(`/a-risky\\|Must read/.test((function(){var c=T.row(T.id('src/auth/session.ts')).querySelector('.g-att');return c.className+'|'+c.textContent;})())`));
    await B.ev(`T.pick(T.id('src/auth/session.ts'))`); await sleep(300);
    const det = await B.ev(`({chip:!!document.querySelector('#g-detail .g-attp .g-att.a-risky'),foc:[].map.call(document.querySelectorAll('#g-detail .g-foc button'),function(b){return b.textContent;}),why:[].map.call(document.querySelectorAll('#g-detail .g-foc .why'),function(b){return b.textContent;})})`);
    t.check('brief: the detail panel shows the chip and the focus ranges with their reasons', det.chip && det.foc.join() === '5-9' && det.why[0] === 'Tenant check dropped', det);
    await B.ev(`document.querySelector('#g-detail .g-foc button').click()`); await sleep(400);
    t.check('brief: a focus range in the detail panel opens its lines', await B.ev(NF('src/auth/session.ts', 'new', 7)));
    await sleep(1800);

    await B.ev(`T.tabTo('B')`); await sleep(200);
    const before = await B.ev(`T.rows().map(function(x){return x.id+':'+x.no;})`);
    t.check('brief: the filter is offered in the View menu', await B.ev(`(function(){var l=document.getElementById('g-onlyreadl');return !l.hidden&&/Only what to read/.test(l.textContent);})()`));
    await B.ev(`document.getElementById('g-mbtn').click()`); await sleep(100);
    await B.ev(`document.getElementById('g-onlyread').click()`); await sleep(300);
    const kept = await B.ev(`T.rows().map(function(x){return x.id+':'+x.no;})`);
    const ids = await B.ev(`(function(){var d=T.data(),o={};d.prs.forEach(function(p){p.nodes.forEach(function(n){o[n.id]=n.attention;});});return o;})()`);
    t.check('brief: "Only what to read" keeps the risky and novel files with their step numbers', kept.length > 0 && kept.length < before.length && kept.every((k) => ['risky', 'novel'].includes(ids[k.split(':')[0]]) && before.includes(k)), { before, kept });
    t.check('brief: and is kept for the next visit', (await B.ev(`localStorage.getItem(T.key()+'onlyread')`)) === '1');
    // A jump to a file the filter hides (a test, which is skim) turns the filter off and opens it.
    await B.ev(`[].find.call(document.querySelectorAll('#dec-1 .refs button.g-ref'),function(b){return /items\\.test\\.ts:1-2/.test(b.textContent);}).click()`); await sleep(500);
    t.check('brief: a jump to a file it hides switches the filter off and opens the file', (await B.ev(`document.getElementById('g-onlyread').checked`)) === false
      && (await B.ev(`T.sel()===T.id('src/api/items.test.ts','B')`)) && await B.ev(NF('src/api/items.test.ts', 'new', 1)) && (await B.ev(`localStorage.getItem(T.key()+'onlyread')`)) === '0');
    t.noErrors('brief: no page errors with the chips and the filter');

    // A medium change (three PRs) has the chips and the filter but no budget.
    await t.fresh(STACK, { steps: false });
    t.check('brief: a medium change has no budget section, but attention chips and the filter', await B.ev(`!document.getElementById('budget')&&!document.getElementById('g-onlyreadl').hidden`) && await B.ev(`(function(){document.getElementById('g-steps').click();return document.querySelectorAll('#g-order .g-att').length>3;})()`));

    // A small change: no budget, no map, the list open by default; a saved choice wins.
    await t.fresh(SMALL, { steps: false, width: 1440, height: 900 });
    const small = await B.ev(`(function(){var c=document.getElementById('g-canvas'),s=document.querySelector('.g-side');return {budget:!!document.getElementById('budget'),brief:!!document.getElementById('brief'),exp:document.getElementById('g-steps').getAttribute('aria-expanded'),
      side:getComputedStyle(s).display,map:!c.hidden||c.querySelectorAll('.nd').length>0,chips:document.querySelectorAll('#g-order .g-att').length,filter:document.getElementById('g-onlyreadl').hidden,stored:localStorage.getItem(T.key()+'steps'),
      link:document.querySelector('ol.merge-order a.mo-link').getAttribute('href'),cls:document.getElementById('graph').classList.contains('small')};})()`);
    t.check('brief: a small change has the brief and no budget', small.brief && !small.budget, small);
    t.check('brief: its step list opens by default, with no map', small.exp === 'true' && small.side !== 'none' && !small.map && small.cls && small.stored === null, small);
    t.check('brief: it has no attention chips or filter, and its merge-order link goes to the graph', small.chips === 0 && small.filter && small.link === '#graph', small);
    await B.ev(`document.getElementById('g-wsb').click()`); await sleep(300);
    const ws = await B.ev(`(function(){function shown(sel){var e=document.querySelector(sel);return !!e&&getComputedStyle(e).display!=='none';}return {ws:document.getElementById('graph').classList.contains('ws'),lmap:shown('.g-wsl'),pane:shown('.g-rpsw'),canvas:!document.getElementById('g-canvas').hidden,list:getComputedStyle(document.querySelector('.g-side')).display!=='none'};})()`);
    t.check('brief: the small workspace has no List | Map switch, no map, and shows the list', ws.ws && !ws.lmap && !ws.pane && !ws.canvas && ws.list, ws);
    await B.key('m'); await sleep(150);
    t.check('brief: the m key does not bring the map in', await B.ev(`document.getElementById('g-canvas').hidden`));
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(300);
    await t.fresh(SMALL, { steps: false, seed: `(function(){var c=JSON.parse(document.getElementById('review-config').textContent),k='review-map:'+(c.storageKey||c.title)+':';localStorage.setItem(k+'steps','0');})()` });
    t.check('brief: a saved choice (list closed) still wins over the small default', await B.ev(`document.getElementById('g-steps').getAttribute('aria-expanded')==='false'&&getComputedStyle(document.querySelector('.g-side')).display==='none'&&document.getElementById('g-canvas').hidden`));
    t.noErrors('brief: no page errors on the small page');

    // The brief's blocks in light and dark, and at phone width.
    const BLOCKS = `(function(){function st(sel,prop){var e=document.querySelector(sel);return e?getComputedStyle(e)[prop]:null;}
      return {risk:st('#brief .brief-risks>li','backgroundColor'),sev:st('#brief .brief-risks .sev','color'),border:st('#brief .brief-risks>li.sev-h','borderLeftColor'),borderM:st('#brief .brief-risks>li.sev-m','borderLeftColor'),
        th:st('#brief table.contracts th','backgroundColor'),kind:st('#brief td.kind','fontWeight'),text:st('#brief .brief-users li','color'),bg:st('body','backgroundColor'),
        bar:st('#budget .b-seg.b-risky','backgroundColor'),bar2:st('#budget .b-seg.b-novel','backgroundColor'),n:document.querySelectorAll('#brief .brief-risks>li').length,rows:document.querySelectorAll('#brief table.contracts tbody tr').length,
        h:document.documentElement.scrollWidth-document.documentElement.clientWidth};})()`;
    await t.fresh(LARGE, { dark: false, steps: false });
    const light = await B.ev(BLOCKS);
    await t.shot('brief-light', '#brief');
    await t.fresh(LARGE, { dark: true, steps: false });
    const dark = await B.ev(BLOCKS);
    await t.shot('brief-dark', '#brief');
    t.check('brief: the brief renders its risks, contracts, and users in light', light.n === 3 && light.rows === 2 && light.border !== light.borderM && light.sev === light.border, light);
    t.check('brief: and in dark, with every colour from a token (each differs from light)', dark.n === 3 && ['risk', 'sev', 'border', 'th', 'text', 'bg', 'bar', 'bar2'].every((k) => dark[k] !== light[k]), { light, dark });
    t.check('brief: the severity colours stay apart in dark', dark.border !== dark.borderM && dark.risk !== dark.text, dark);
    await t.fresh(LARGE, { dark: false, width: 390, height: 844, steps: false });
    const phone = await B.ev(BLOCKS);
    const fit = await B.ev(`(function(){var r=document.getElementById('brief').getBoundingClientRect(),t=document.querySelector('#brief .tbl').getBoundingClientRect(),b=document.getElementById('budget').getBoundingClientRect();return {brief:Math.round(r.right),tbl:Math.round(t.right),budget:Math.round(b.right),w:innerWidth};})()`);
    t.check('brief: at phone width the page does not scroll sideways and the blocks stay in the window', phone.h <= 0 && fit.brief <= fit.w && fit.tbl <= fit.w && fit.budget <= fit.w, { phone: phone.h, fit });
    await t.shot('brief-phone', '#brief');
    t.noErrors('brief: no page errors in either theme or at phone width');
  },
};
