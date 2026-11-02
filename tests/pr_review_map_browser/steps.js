'use strict';
// REQUIREMENT: the report opens on the map with the step list closed behind one "Steps" toggle, so the detail panel and
// diff get the freed width. The toggle opens and closes the list and is remembered under its own key; an older saved
// view (view=list, wsleft=list) does not bring the list-first default back. Closed, Previous/Next, selecting on the map,
// and the step numbers in the detail panel still work, and nothing scrolls or focuses a hidden row; opening the list shows
// the current step. The workspace's left column is the same switch. (The other suites open the list in their shared setup.)
const { sleep } = require('./lib');

module.exports = {
  name: 'steps',
  weight: 6,
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const STACK = t.url(t.fixtures, 'stack', 'review.html');
    const STATE = `(function(){var b=document.getElementById('g-steps'),s=document.querySelector('.g-side'),w=document.getElementById('g-work').getBoundingClientRect(),m=document.querySelector('.g-main').getBoundingClientRect(),
      c=document.getElementById('g-canvas');var k=T.key();
      return {exp:b.getAttribute('aria-expanded'),btn:b.textContent.trim(),side:getComputedStyle(s).display,sideW:Math.round(s.getBoundingClientRect().width),mainW:Math.round(m.width),workW:Math.round(w.width),
        map:!c.hidden&&c.querySelectorAll('.nd').length,stored:localStorage.getItem(k+'steps'),sel:T.sel(),title:document.getElementById('dv-title').textContent,
        oldBtns:document.querySelectorAll('[data-v]').length,scroll:document.getElementById('g-orderbox').scrollTop,active:document.activeElement&&document.activeElement.id};})()`;

    // First visit: the map, the list closed, the diff panel as wide as the graph.
    await t.fresh(STACK, { steps: false });
    let s = await B.ev(STATE);
    t.check('steps: the page opens on the map with the step list closed behind one "Steps" toggle', s.exp === 'false' && s.map > 3 && s.side === 'none' && s.oldBtns === 0 && s.btn.length > 0 && s.stored === null, s);
    t.check('steps: closed, the detail panel and diff take the whole graph width', s.mainW === s.workW, s);
    await B.ev(`T.pick(T.rows()[0].id)`);
    const first = await B.ev(STATE);
    t.check('steps: selecting a file keeps its step number in the detail panel', /\b1 ·/.test(first.title) && first.sel !== null, first);

    // Previous/Next with the list closed.
    await B.ev(`document.getElementById('g-next').click()`); await sleep(120);
    const next = await B.ev(STATE);
    await B.ev(`document.getElementById('g-next').click()`); await sleep(120);
    const next2 = await B.ev(STATE);
    await B.ev(`document.getElementById('g-prev').click()`); await sleep(120);
    const back = await B.ev(STATE);
    t.check('steps: Previous and Next move through the steps with the list closed', next.sel !== first.sel && /\b2 ·/.test(next.title) && /\b3 ·/.test(next2.title) && back.sel === next.sel && back.side === 'none', [first.title, next.title, next2.title, back.title]);
    t.check('steps: with the list closed nothing scrolls or takes the focus in it', next2.scroll === 0 && back.active !== 'g-order' && !(await B.ev(`!!document.activeElement.closest('#g-order')`)), [next2.scroll, back.active]);

    // Selecting on the map works too.
    await B.ev(`document.querySelectorAll('#g-canvas .nd')[4].dispatchEvent(new MouseEvent('click',{bubbles:true}))`); await sleep(120);
    const onMap = await B.ev(STATE);
    t.check('steps: clicking a map node selects it with the list closed', onMap.sel !== null && onMap.sel !== back.sel && onMap.side === 'none', onMap);

    // The toggle opens the list at the current step and closes it again; the state is kept.
    await B.ev(`document.getElementById('g-steps').click()`); await sleep(200);
    const open = await B.ev(STATE);
    const vis = await B.ev(`(function(){var r=T.row(T.sel()),o=document.getElementById('g-orderbox').getBoundingClientRect(),q=r.getBoundingClientRect();return q.top>=o.top-1&&q.bottom<=o.bottom+1&&q.height>0;})()`);
    t.check('steps: the toggle opens the list beside the detail panel, with the current step showing', open.exp === 'true' && open.side !== 'none' && open.sideW > 200 && open.mainW < open.workW && open.stored === '1' && vis && open.map > 3, { open, vis });
    await B.ev(`document.getElementById('g-steps').click()`); await sleep(100);
    const closed = await B.ev(STATE);
    t.check('steps: the toggle closes it again and the choice is kept as closed', closed.exp === 'false' && closed.side === 'none' && closed.stored === '0' && closed.mainW === closed.workW, closed);
    await B.ev(`document.getElementById('g-steps').click()`); await sleep(100);
    await t.reload(STACK, { steps: false });
    t.check('steps: an open list is open after a reload', (await B.ev(STATE)).exp === 'true');
    t.noErrors('steps: no page errors');

    // An older saved view does not bring the list-first default back.
    await t.fresh(STACK, { steps: false, seed: `(function(){var c=JSON.parse(document.getElementById('review-config').textContent),k='review-map:'+(c.storageKey||c.title)+':';localStorage.setItem(k+'view','list');localStorage.setItem(k+'wsleft','list');})()` });
    s = await B.ev(STATE);
    t.check('steps: a saved view=list (and wsleft=list) does not override the default: map shown, list closed', s.exp === 'false' && s.side === 'none' && s.map > 3, s);

    // The workspace: the left column is the same switch (closed list = the map there).
    await t.fresh(STACK, { steps: false, width: 1440, height: 900 });
    await B.ev(`document.getElementById('g-wsb').click()`); await sleep(300);
    const ws = await B.ev(`({lmap:document.getElementById('graph').classList.contains('ws-lmap'),pressed:[].map.call(document.querySelectorAll('[data-wl]'),function(b){return b.dataset.wl+':'+b.getAttribute('aria-pressed');}).join()})`);
    t.check('steps: the workspace opens with the map in its left column while the list is closed', ws.lmap && ws.pressed === 'list:false,map:true', ws);
    await B.ev(`document.querySelector('[data-wl=list]').click()`); await sleep(200);
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(300);
    s = await B.ev(STATE);
    t.check('steps: picking List in the workspace is "Steps" open, and it stays so on leaving', s.exp === 'true' && s.side !== 'none' && s.stored === '1', s);
    t.noErrors('steps: no page errors in the workspace');
  },
};
