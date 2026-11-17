'use strict';
// REQUIREMENT: a code link in the brief (a risk, a contract), the reading budget, or a decision card opens a review overlay
// over the page instead of scrolling the reader away: the page behind keeps its scroll position and is inert, a queue of the
// list the link came from stands in for the step list (the budget: Must read, then Read under its divider), the file's diff
// opens on its PR's tab at the entry's lines with the range banded, the neighbours stay on the right, and a footer steps.
// j/k and [ ] move, x marks read and goes on, Esc closes (not while a note editor has the focus) and gives back the scroll
// position and the focus on the link, whose row then shows it is read (the step list's read mark). Back closes it, one
// history entry per open. Notes work as in the workspace. At 800 px it is one sheet with the queue behind a button. Long file
// names show shortened, and the budget's line count follows the reason. In light and dark.
const { sleep } = require('./lib');

module.exports = {
  name: 'overlay',
  weight: 6,
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const LARGE = t.url(t.fixtures, 'brief', 'review.html');
    const SESSION = 'session.ts5–9', PHP = 'add_link_to_tas…items_tables.php1';
    const QUEUE = ['0042_slot.sql1', SESSION, PHP, 'legacy.ts2–4 (old side)', '--Read (2)', 'items.ts1', 'ItemList.tsx1'];
    const click = (sel, re) => B.ev(`[].find.call(document.querySelectorAll(${JSON.stringify(sel)}),function(b){return ${re}.test(b.textContent);}).click()`);
    const ST = `(function(){var g=document.getElementById('graph'),cur=document.querySelector('#ov-ol .ov-row.cur'),a=document.activeElement;
      return {open:g.classList.contains('ovl'),ws:g.classList.contains('ws'),role:g.getAttribute('role'),modal:g.getAttribute('aria-modal'),label:g.getAttribute('aria-label'),sy:Math.round(scrollY),hash:location.hash,state:history.state,
        title:document.getElementById('ov-t').textContent,cur:cur?cur.textContent:null,curI:cur?+cur.dataset.i:-1,
        rows:[].map.call(document.querySelectorAll('#ov-ol>li'),function(l){return (l.classList.contains('ov-div')?'--':'')+l.textContent+(l.classList.contains('done')?' ✓':'');}),
        qlabel:document.getElementById('ov-ol').getAttribute('aria-label'),tab:T.tab(),head:document.getElementById('ov-head').textContent,
        inQ:!!a&&!!a.closest&&!!a.closest('#graph'),active:a?(a.tagName+'.'+a.className+':'+(a.textContent||'').trim().slice(0,24)):'',
        toc:document.querySelector('nav.toc').hasAttribute('inert'),order:getComputedStyle(document.getElementById('g-orderbox')).display,det:getComputedStyle(document.getElementById('g-detail')).display,
        side:getComputedStyle(document.querySelector('.g-side')).display,foot:getComputedStyle(document.getElementById('ov-foot')).display};})()`;
    const BAND = (path, side) => `(function(){var d=T.df(${JSON.stringify(path)});return d?[].map.call(d.querySelectorAll('td.ln.ovr[data-s="${side}"]'),function(c){return +c.dataset.l;}):null;})()`;
    const READ = () => B.ev(`JSON.stringify(T.stored('read'))`);
    const OPEN = async (sel, re, y = 150, opts = {}) => {
      await t.fresh(LARGE, { steps: false, ...opts });
      await B.ev(`window.scrollTo(0,${y})`); await sleep(150);
      await click(sel, re); await sleep(900);
    };
    let s;

    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';

      // A budget entry opens the overlay at its lines; the page does not move.
      await OPEN('#budget button.g-ref', /session\.ts:5-9/, 150, { dark });
      s = await B.ev(ST);
      t.check(`overlay ${th}: a budget link opens the overlay, a dialog, and the page keeps its scroll position`, s.open && s.ws && s.role === 'dialog' && s.modal === 'true' && s.sy === 150 && /Reading budget/.test(s.label), s);
      t.check(`overlay ${th}: the page behind is inert, the address is as it was, and the history holds one entry for the overlay`, s.toc && s.hash === '' && s.state && s.state.prmOv === 1, s);
      t.check(`overlay ${th}: the queue replaces the step list, with the neighbours and a footer`, s.order === 'none' && s.side !== 'none' && s.det !== 'none' && s.foot !== 'none', s);
      t.check(`overlay ${th}: the queue holds the Must read files, then Read under its divider, the current one marked and the queue named`,
        s.rows.join('|') === QUEUE.join('|') && s.cur === SESSION && /Reading queue/.test(s.qlabel) && /Reading budget/.test(s.title), s);
      t.check(`overlay ${th}: the diff of that file opens on its PR's tab with its range banded, the header names PR, path, lines, and why`,
        s.tab === 'A' && JSON.stringify(await B.ev(BAND('src/auth/session.ts', 'new'))) === '[5,6,7,8,9]' && /A #1/.test(s.head) && /src\/auth\/session\.ts/.test(s.head) && /lines 5–9/.test(s.head) && /Tenant check dropped/.test(s.head), s);
      await sleep(1800); // the flash fades; the band stays and is not the note colour
      const band = await B.ev(`(function(){var c=T.cell('src/auth/session.ts','new',6),o=T.cell('src/auth/session.ts','new',12),root=getComputedStyle(document.documentElement);
        return {band:c.classList.contains('ovr'),flash:c.classList.contains('nf'),sel:c.classList.contains('ls'),img:getComputedStyle(c).backgroundImage,other:getComputedStyle(o).backgroundImage,ls:root.getPropertyValue('--d-sel').trim(),rng:root.getPropertyValue('--d-rng').trim()};})()`);
      t.check(`overlay ${th}: the band stays after the flash, in its own colour (not the note selection's), and only on the range`, band.band && !band.flash && !band.sel && band.img !== 'none' && band.other === 'none' && band.rng && band.rng !== band.ls, band);
      await t.shot(`overlay-${th}`);
      s = await B.ev(ST);
      t.check(`overlay ${th}: the focus is on the current queue row`, /^BUTTON\.nm:session\.ts/.test(s.active), s.active);

      // Tab stays inside the dialog.
      let outside = 0;
      for (let i = 0; i < 25; i++) { await B.key('Tab'); if (!(await B.ev(ST)).inQ) outside++; }
      for (let i = 0; i < 25; i++) { await B.key('Tab', 8); if (!(await B.ev(ST)).inQ) outside++; } // Shift+Tab
      t.check(`overlay ${th}: Tab and Shift+Tab never leave the dialog`, outside === 0, outside);
      await B.ev(`document.querySelector('#ov-ol .ov-row.cur .nm').focus()`);

      // x marks read and advances; j k [ ] move without marking.
      await B.key('x'); await sleep(700);
      s = await B.ev(ST);
      t.check(`overlay ${th}: x marks the file read and opens the next entry, on its own PR's tab`, s.cur === PHP && s.rows[1] === 'session.ts5–9 ✓' && s.tab === 'B' && /database\/migrations\/2026_11_16_193657_add_link/.test(s.head), s);
      t.check(`overlay ${th}: the read mark is the page's own (the step list reads it, see below)`, (await READ()) === '{"A":{"src/auth/session.ts":1}}', await READ());
      await B.key('j'); await sleep(500); s = await B.ev(ST);
      t.check(`overlay ${th}: an entry for removed code opens the old side of its file on that PR's tab`, s.cur === 'legacy.ts2–4 (old side)' && s.tab === 'D' && JSON.stringify(await B.ev(BAND('src/auth/legacy.ts', 'old'))) === '[2,3,4]', s);
      await B.key('j'); await sleep(250); const j1 = (await B.ev(ST)).curI;
      await B.key('k'); await sleep(250); const k1 = (await B.ev(ST)).curI;
      await B.key(']'); await sleep(250); const j2 = (await B.ev(ST)).curI;
      await B.key('['); await sleep(250); const k2 = (await B.ev(ST)).curI;
      t.check(`overlay ${th}: j and k, [ and ] move through the queue without marking anything`, [j1, k1, j2, k2].join() === '4,3,4,3' && (await READ()) === '{"A":{"src/auth/session.ts":1}}', { j1, k1, j2, k2 });
      for (let i = 0; i < 5; i++) await B.key('k');
      await sleep(250);
      t.check(`overlay ${th}: the queue stops at its first entry, and Prev is disabled there`, (await B.ev(ST)).curI === 0 && (await B.ev(`document.getElementById('ov-prev').getAttribute('aria-disabled')`)) === 'true');
      for (let i = 0; i < 9; i++) await B.key('j');
      await sleep(250);
      t.check(`overlay ${th}: and at its last, where "Read, next" marks it read and stays`, (await B.ev(ST)).curI === 5 && await (async () => { await B.key('x'); await sleep(250); const r = await B.ev(ST); return r.curI === 5 && r.rows[6] === 'ItemList.tsx1 ✓'; })());
      // The step list, the map, and the rows of the page all read the same marks: undo that one from the queue.
      await B.ev(`(function(){var cb=document.querySelector('#ov-ol .ov-row.done:last-of-type input');cb.click();})()`); await sleep(100);
      t.check(`overlay ${th}: a queue row's check unmarks it again`, (await READ()) === '{"A":{"src/auth/session.ts":1}}', await READ());

      // Keys leave a note editor alone, and notes work as in the workspace.
      await click('#ov-ol .nm', /session\.ts/); await sleep(600);
      await B.ev(`T.cell('src/auth/session.ts','new',7).click()`); await sleep(100);
      await B.ev(`document.querySelector('#dv-files [data-nt=add]').click()`); await sleep(100);
      const ta = await B.ev(`(function(){var e=document.querySelector('#dv-files .nt-ed textarea');if(e)e.focus();return !!e&&document.activeElement===e;})()`);
      await B.key('j'); await B.key('x'); await B.key(']'); await sleep(200);
      s = await B.ev(ST);
      t.check(`overlay ${th}: j, x, and ] do nothing while a note editor has the focus`, ta && s.cur === SESSION && s.open && (await READ()) === '{"A":{"src/auth/session.ts":1}}', { ta, s });
      await B.ev(`T.save(document.querySelector('#dv-files .nt-ed'),'issue','Check the tenant.')`); await sleep(150);
      const copied = await t.copy();
      t.check(`overlay ${th}: a line note saves from the overlay, and the notes drawer opens and copies it`, (await B.ev(`document.getElementById('nt-count').textContent`)) === '1'
        && await B.ev(`(function(){document.getElementById('g-wsnotes').click();return document.getElementById('graph').classList.contains('ws-notes');})()`)
        && /Check the tenant\./.test(copied) && /src\/auth\/session\.ts/.test(copied), copied);
      await B.ev(`document.getElementById('g-wsnotes').focus()`); await B.key('Escape'); await sleep(200);
      t.check(`overlay ${th}: Esc closes the notes drawer first, then the overlay`, (await B.ev(ST)).open && !(await B.ev(`document.getElementById('graph').classList.contains('ws-notes')`)));
      await B.ev(`document.querySelector('#ov-ol .ov-row.cur .nm').focus()`);

      // Esc: the scroll position, the focus, and the read state of the row.
      await B.key('Escape'); await sleep(500);
      s = await B.ev(ST);
      const rm = await B.ev(`(function(){var b=[].find.call(document.querySelectorAll('#budget button.g-ref'),function(b){return /session\\.ts:5-9/.test(b.textContent);});var m=b.previousElementSibling;
        return {focus:document.activeElement===b,mark:!!m&&m.classList.contains('g-rm')&&!m.hidden,markText:m&&m.textContent,li:b.closest('li').classList.contains('r-read'),shown:[].filter.call(document.querySelectorAll('#budget .g-rm'),function(e){return !e.hidden;}).length,
          inert:document.querySelectorAll('[inert]').length,role:document.getElementById('graph').getAttribute('role'),hist:history.state};})()`);
      t.check(`overlay ${th}: Esc closes it, restores the scroll position and the page, and the focus returns to the link`, !s.open && !s.ws && s.sy === 150 && rm.focus && rm.inert === 0 && rm.role === null, { s, rm });
      t.check(`overlay ${th}: the budget row of the file just read shows a read mark, and no other does`, rm.mark && rm.li && rm.markText === '✓' && rm.shown === 1, rm);
      t.check(`overlay ${th}: closing leaves no history entry of its own behind`, rm.hist === null, rm.hist);
      await B.ev(`T.tabTo('A')`); await sleep(200);
      t.check(`overlay ${th}: the step list shows the same file as read (the page's own mark)`, await B.ev(`T.row(T.id('src/auth/session.ts','A')).classList.contains('done')`));
      t.noErrors(`overlay ${th}: no page errors`);
    }

    // The queue scrolls itself to keep the current row in view (a window too short for all of it).
    await OPEN('#budget button.g-ref', /session\.ts:5-9/, 150, { height: 330 });
    for (let i = 0; i < 6; i++) await B.key('j');
    await sleep(300);
    const vis = await B.ev(`(function(){var q=document.getElementById('ov-q'),r=document.querySelector('#ov-ol .ov-row.cur').getBoundingClientRect(),b=q.getBoundingClientRect();return {scrolls:q.scrollHeight>q.clientHeight,top:q.scrollTop,inView:r.top>=b.top&&r.bottom<=b.bottom};})()`);
    t.check('overlay: the queue scrolls itself to keep the current row in view', vis.scrolls && vis.top > 0 && vis.inView, vis);
    await B.key('Escape'); await sleep(300);

    // Long names show shortened, with the full path on hover, and the line count follows the reason.
    await t.fresh(LARGE, { steps: false });
    const bud = await B.ev(`(function(){var b=[].find.call(document.querySelectorAll('#budget button.g-ref'),function(b){return /add_link/.test(b.textContent);}),li=b.closest('li'),n=li.querySelector('.b-n'),prev=n.previousElementSibling.getBoundingClientRect(),nr=n.getBoundingClientRect(),lr=li.getBoundingClientRect();
      var s=[].find.call(document.querySelectorAll('#budget button.g-ref'),function(b){return /session\\.ts/.test(b.textContent);}).closest('li');
      return {text:b.textContent,title:b.querySelector('code').title,n:n.textContent,gap:Math.round(nr.left-prev.right),fromEdge:Math.round(lr.right-nr.right),why:s.querySelector('.b-why').textContent,sn:s.querySelector('.b-n').textContent,mono:getComputedStyle(n).fontFamily,color:getComputedStyle(n).color,muted:getComputedStyle(document.querySelector('.b-why')).color,full:b.querySelector('code').getAttribute('data-full')};})()`);
    t.check('overlay: a long migration name shows without its timestamp and shortened in the middle, its full path on hover', bud.text === 'add_link_to_tas…items_tables.php:1' && bud.title === 'database/migrations/2026_11_16_193657_add_link_to_tasks_routines_and_agenda_items_tables.php'
      && bud.full === 'database/migrations/2026_11_16_193657_add_link_to_tasks_routines_and_agenda_items_tables.php:1', bud);
    t.check('overlay: the line count follows the reason as a muted "· 2 lines", not at the far edge', bud.n === '· 2 lines' && bud.sn === '· 5 lines' && bud.gap < 24 && bud.fromEdge > 100 && bud.color === bud.muted, bud);
    const names = await B.ev(`['2026_11_16_193657_add_link_to_tasks_routines_and_agenda_items_tables.php','20261116193657_create_users.rb','2026-11-16-notes.md','0042_slot.sql','session.ts','a'.repeat(40)+'.ts','2026_11_16_193657_x','2026_11_16_193657_'].map(window.__shortName)`);
    t.check('overlay: a name drops a leading timestamp, shortens in the middle to 32 characters keeping its ending, and short names and plain numbers stay',
      names[0] === 'add_link_to_tas…items_tables.php' && names[0].length === 32 && names[1] === 'create_users.rb' && names[2] === 'notes.md' && names[3] === '0042_slot.sql'
      && names[4] === 'session.ts' && names[5].length === 32 && names[5].endsWith('.ts') && names[6] === 'x' && names[7] === '2026_11_16_193657_', names);

    // A risk link opens a queue of the risks, in rank order; a contract link one of the contracts; a decision link its own.
    await OPEN('#brief .brief-risks button.g-ref', /items\.ts:3-6/);
    s = await B.ev(ST);
    t.check('overlay: a risk link opens a queue of the risks in rank order, on the PR named by its chip, with the risk as the reason',
      s.cur === 'items.ts3–6' && s.rows.join('|') === 'session.ts5–9|items.ts3–6|ItemList.tsx2–3' && s.tab === 'B' && /Medium · A retry after the timeout/.test(s.head) && /Risks/.test(s.title), s);
    await B.key('Escape'); await sleep(400);
    await click('#brief table.contracts button.g-ref', /0042_slot\.sql:1-8/); await sleep(800);
    s = await B.ev(ST);
    t.check('overlay: a contract link opens a queue of the contracts', s.rows.join('|') === '0042_slot.sql1–8|items.ts3–6' && s.cur === '0042_slot.sql1–8' && s.tab === 'A' && /Migration · Adds visits\.slot_id/.test(s.head), s);
    await B.key('Escape'); await sleep(400);
    await click('#dec-1 .refs button.g-ref', /items\.ts:3-6/); await sleep(800);
    s = await B.ev(ST);
    t.check('overlay: a decision card\'s link opens that decision\'s links', s.rows.join('|') === 'items.ts3–6|items.test.ts1–2' && s.cur === 'items.ts3–6' && /Ship the 404/.test(s.head), s);
    await B.key('x'); await sleep(500);
    await B.key('Escape'); await sleep(400);
    await B.ev(`document.querySelector('#dec-1 .g-radd').click()`); await sleep(200);
    const dn = await B.ev(`document.getElementById('nt-list').textContent`);
    t.check('overlay: the read mark in a decision card stays out of the text of its "Add as note"', /Ship the 404/.test(dn) && !/✓/.test(dn), dn);
    const marks = await B.ev(`(function(){function m(sel,re){var b=[].find.call(document.querySelectorAll(sel),function(b){return re.test(b.textContent);});return b&&b.previousElementSibling.classList.contains('g-rm');}
      return {risk:m('#brief .brief-risks button.g-ref',/session/),contract:m('#brief table.contracts button.g-ref',/0042/),dec:m('#dec-1 .refs button.g-ref',/items\\.ts/)};})()`);
    t.check('overlay: risk, contract, and decision links each carry a read mark (hidden until their file is read)', marks.risk && marks.contract && marks.dec, marks);
    t.check('overlay: a link elsewhere (the graph\'s detail panel) keeps scrolling to its lines and opens no overlay', await (async () => {
      await t.fresh(LARGE);
      await B.ev(`T.pick(T.id('src/auth/session.ts'))`); await sleep(300);
      await B.ev(`document.querySelector('#g-detail .g-foc button').click()`); await sleep(500);
      return !(await B.ev(ST)).open && await B.ev(`T.cell('src/auth/session.ts','new',7).classList.contains('nf')`);
    })());

    // Back closes it, one entry for the whole visit; no stale entry after Esc.
    await OPEN('#budget button.g-ref', /session\.ts:5-9/);
    const len0 = await B.ev('history.length');
    await B.key('j'); await B.key('j'); await sleep(300);
    t.check('overlay: stepping through the queue adds no history entry', (await B.ev('history.length')) === len0, [len0, await B.ev('history.length')]);
    await B.ev('history.back()'); await sleep(500);
    s = await B.ev(ST);
    t.check('overlay: Back closes it, with the page where it was and the focus on the link', !s.open && !s.ws && s.sy === 150 && s.state === null && /g-ref/.test(s.active), s);
    const at0 = await B.ev('navigation.currentEntry.index');
    await click('#budget button.g-ref', /session\.ts:5-9/); await sleep(700);
    const at1 = await B.ev('navigation.currentEntry.index');
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(500);
    t.check('overlay: ✕ closes it and takes its history entry off again (one entry for the visit, none left behind)', !(await B.ev(ST)).open && at1 === at0 + 1 && (await B.ev('navigation.currentEntry.index')) === at0, [at0, at1, await B.ev('navigation.currentEntry.index')]);
    t.check('overlay: the workspace still opens by ⤢ with the step list, and #ws still works', await (async () => {
      await t.fresh(LARGE, { steps: false });
      await B.ev(`document.getElementById('g-wsb').click()`); await sleep(300);
      const ws = await B.ev(`(function(){var g=document.getElementById('graph');return {ws:g.classList.contains('ws'),ovl:g.classList.contains('ovl'),order:getComputedStyle(document.getElementById('g-orderbox')).display,q:getComputedStyle(document.getElementById('ov-q')).display,hash:location.hash};})()`);
      await B.key('Escape'); await sleep(200);
      await B.open(LARGE + '#ws');
      const ws2 = await B.ev(`document.getElementById('graph').classList.contains('ws')&&!document.getElementById('graph').classList.contains('ovl')`);
      return ws.ws && !ws.ovl && ws.order !== 'none' && ws.q === 'none' && ws.hash === '#ws' && ws2;
    })());
    t.noErrors('overlay: no page errors on the wide overlay');

    // Narrow: one sheet, the diff unified, the queue behind "List (i/n)".
    for (const dark of [false, true]) {
      const th = `${dark ? 'dark' : 'light'} narrow`;
      await OPEN('#budget button.g-ref', /session\.ts:5-9/, 150, { width: 800, height: 900, dark });
      s = await B.ev(ST);
      const sheet = await B.ev(`(function(){function r(s){var e=document.querySelector(s);if(!e)return null;var b=e.getBoundingClientRect();return {w:Math.round(b.width),shown:!!e.getClientRects().length};}
        return {g:r('#graph'),side:r('.g-side'),det:r('#g-detail'),lb:r('#ov-lb'),lbText:document.getElementById('ov-lb').textContent,uni:!!document.querySelector('#dv-files table.dt.uni'),foot:r('#ov-foot'),prev:r('#ov-prev'),next:r('#ov-next'),vw:innerWidth,hs:document.documentElement.scrollWidth-document.documentElement.clientWidth,
          band:(function(){var c=T.cell('src/auth/session.ts','new',6);return !!c&&c.classList.contains('ovr');})()};})()`);
      t.check(`overlay ${th}: at 800 px it is one sheet with the header, the unified diff, and Prev / Read-next; the queue and the neighbours are hidden`,
        s.open && sheet.g.w === sheet.vw && sheet.uni && sheet.band && !sheet.side.shown && !sheet.det.shown && sheet.lb.shown && sheet.foot.shown && sheet.prev.shown && sheet.next.shown && /Tenant check dropped/.test(s.head), { s, sheet });
      t.check(`overlay ${th}: the list button says where the reader is, the sheet does not scroll sideways, and the focus is inside it`, sheet.lbText === 'List (2/6)' && sheet.hs <= 0 && s.inQ, { sheet, active: s.active });
      await B.ev(`document.getElementById('ov-lb').click()`); await sleep(250);
      const dr = await B.ev(`(function(){var q=document.getElementById('ov-q').getBoundingClientRect();return {shown:!!document.querySelector('.g-side').getClientRects().length,w:Math.round(q.width),exp:document.getElementById('ov-lb').getAttribute('aria-expanded'),rows:document.querySelectorAll('#ov-ol .ov-row').length};})()`);
      t.check(`overlay ${th}: the button opens the queue as a drawer`, dr.shown && dr.exp === 'true' && dr.rows === 6 && dr.w < 400, dr);
      await t.shot(`overlay-drawer-${dark ? 'dark' : 'light'}`);
      await B.ev(`document.querySelectorAll('#ov-ol .nm')[4].click()`); await sleep(700);
      s = await B.ev(ST);
      t.check(`overlay ${th}: a row in it opens its file and closes the drawer`, s.cur === 'items.ts1' && s.tab === 'B' && !(await B.ev(`document.querySelector('.g-side').getClientRects().length`)) && (await B.ev(`document.getElementById('ov-lb').textContent`)) === 'List (5/6)', s);
      await B.ev(`document.getElementById('ov-next').click()`); await sleep(600);
      t.check(`overlay ${th}: "Read, next" marks the file read and steps on`, (await B.ev(ST)).cur === 'ItemList.tsx1' && (await READ()) === '{"B":{"src/api/items.ts":1}}', await READ());
      await B.ev(`document.getElementById('ov-lb').click()`); await sleep(150);
      await B.key('Escape'); await sleep(200);
      t.check(`overlay ${th}: Esc closes the drawer first, then the sheet, and the scroll position comes back`, (await B.ev(ST)).open && !(await B.ev(`document.getElementById('graph').classList.contains('ov-qopen')`)) && await (async () => { await B.key('Escape'); await sleep(500); const r = await B.ev(ST); return !r.open && r.sy === 150; })());
    }
    t.noErrors('overlay: no page errors on the narrow sheet');

    // Resizing from wide to narrow while it is open keeps it open and lays it out again.
    await OPEN('#budget button.g-ref', /session\.ts:5-9/);
    await B.viewport(800, 900); await sleep(500);
    s = await B.ev(ST);
    t.check('overlay: narrowing the window with it open turns it into the sheet instead of closing it', s.open && await B.ev(`document.getElementById('graph').classList.contains('ov-n')`), s);
    await B.viewport(1440, 900); await sleep(500);
    t.check('overlay: and widening it brings the three columns back', (await B.ev(ST)).open && !(await B.ev(`document.getElementById('graph').classList.contains('ov-n')`)) && (await B.ev(ST)).side !== 'none');
    await B.key('Escape'); await sleep(300);
    t.noErrors('overlay: no page errors after resizing');
  },
};
