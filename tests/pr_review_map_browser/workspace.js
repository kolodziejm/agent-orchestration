'use strict';
// The workspace (the graph over the whole window): entering by the button, the key f, and #ws; its three columns and
// top bar; resizing by keyboard and pointer, kept across reloads; the right pane's neighbourhood, map, overview, and
// fold; the notes drawer; Esc's order; the scroll position given back; the tabs folding into a picker; and no workspace
// below 1100 pixels. On the plan sample (and the 103-file sample for the overview) in light and dark.
const { sleep } = require('./lib');

const STATE = `(function(){var g=document.getElementById('graph'),r=g.getBoundingClientRect(),q=function(s){var e=document.querySelector(s);if(!e)return null;var b=e.getBoundingClientRect();return {l:Math.round(b.left),r:Math.round(b.right),t:Math.round(b.top),b:Math.round(b.bottom),w:Math.round(b.width),shown:!!e.getClientRects().length&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'};};
  return {ws:g.classList.contains('ws'),pos:getComputedStyle(g).position,rect:[r.left,r.top,r.width,r.height],root:document.documentElement.classList.contains('g-wsroot'),hash:location.hash,
    inert:[].filter.call(document.querySelectorAll('[inert]'),function(e){return !e.contains(g);}).length,toc:document.querySelector('nav.toc').hasAttribute('inert'),
    side:q('.g-side'),dv:q('#dv'),det:q('#g-detail'),cv:q('#g-canvas'),rph:q('#g-rph'),top:q('#g-top'),plan:q('#g-plan'),lead:q('#graph>.lead'),btn:q('#g-wsb'),x:q('#g-wsx'),notesBtn:q('#g-wsnotes'),
    drawer:q('#nt-panel'),sep1:[document.getElementById('g-sep1').getAttribute('role'),+document.getElementById('g-sep1').getAttribute('aria-valuenow'),+document.getElementById('g-sep1').getAttribute('aria-valuemin'),+document.getElementById('g-sep1').getAttribute('aria-valuemax')],
    sep2:[document.getElementById('g-sep2').getAttribute('role'),+document.getElementById('g-sep2').getAttribute('aria-valuenow')],
    notesText:document.getElementById('g-wsnotes').textContent,notesExp:document.getElementById('g-wsnotes').getAttribute('aria-expanded'),
    fold:g.classList.contains('ws-fold'),active:document.activeElement&&(document.activeElement.id||document.activeElement.tagName),sy:Math.round(scrollY),vw:innerWidth,vh:innerHeight};})()`;

module.exports = {
  name: 'workspace',
  weight: 14, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const PLAN = t.url(t.fixtures, 'plan', 'review.html'), BIG = t.url(t.fixtures, 'big', 'review.html');
    const st = () => B.ev(STATE);
    const keyOn = async (id, key, mods = 0) => { await B.ev(`document.getElementById('${id}').focus()`); await B.key(key, mods); };

    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      /* ---------- Entering by the button: the overlay, three columns, the top bar ---------- */
      await t.fresh(PLAN, { dark });
      await B.ev(`T.pick(T.id('src/auth/session.ts'))`); await sleep(150);
      if (!dark) { await sleep(800); await B.ev(`document.querySelector('#graph>h2').scrollIntoView()`); await sleep(150); await t.shot('normal-1440-light'); }
      await B.ev(`window.scrollTo(0,700)`); await sleep(50);
      const y0 = await B.ev('Math.round(scrollY)');
      let s = await st();
      t.check(`ws ${th}: the ⤢ button shows at 1440 px, the workspace is off`, s.btn.shown && !s.ws && !s.x.shown && !s.notesBtn.shown, s);
      await B.ev(`document.getElementById('g-wsb').click()`); await sleep(250);
      s = await st();
      t.check(`ws ${th}: the button opens the graph over the whole window, the page behind inert, the address #ws`,
        s.ws && s.pos === 'fixed' && s.rect.join() === `0,0,${s.vw},${s.vh}` && s.root && s.toc && s.inert > 0 && s.hash === '#ws', s);
      t.check(`ws ${th}: list | diff | neighbourhood side by side under one top bar`, s.side.shown && s.dv.shown && s.det.shown && s.side.r <= s.dv.l && s.dv.r <= s.det.l && s.side.t >= s.top.b - 1
        && s.top.t === 0 && s.top.b - s.top.t < 64 && s.det.r <= s.vw && !s.plan.shown && !s.lead.shown && !s.btn.shown && s.x.shown && s.notesBtn.shown && !s.cv.shown, s);
      t.check(`ws ${th}: the selection carries over (file, diff, detail)`, await B.ev(`T.sel()===T.id('src/auth/session.ts')&&document.querySelector('#g-detail h4').textContent.indexOf('session.ts')>0&&!!T.df('src/auth/session.ts')`));
      t.check(`ws ${th}: the separators are focusable separators with their widths`, s.sep1[0] === 'separator' && s.sep1[1] === 340 && s.sep1[1] === s.side.w && s.sep2[0] === 'separator' && s.sep2[1] === 420
        && s.sep1[2] === 220 && s.sep1[3] > 340 && s.notesText === 'Notes 0' && s.notesExp === 'false', s);
      t.check(`ws ${th}: the focus lands on the step list and the change is announced`, await B.ev(`!!document.activeElement.closest('#g-order')`)
        && await B.ev(`new Promise(function(r){setTimeout(function(){r(document.getElementById('nt-live').textContent);},80);})`) === 'Workspace: list, diff, and right pane over the whole window. Esc closes it.');
      if (!dark) await t.shot('ws-1440-light');
      else await t.shot('ws-1440-dark');

      /* ---------- Resizing: keyboard and pointer, kept ---------- */
      await keyOn('g-sep1', 'ArrowRight');
      s = await st();
      t.check(`ws ${th}: → on the list separator widens the list by 16 px`, s.sep1[1] === 356 && s.side.w === 356, s.sep1);
      await keyOn('g-sep1', 'ArrowRight', 8);
      t.check(`ws ${th}: Shift+→ by 64 px`, (await st()).sep1[1] === 420);
      await keyOn('g-sep1', 'Home');
      t.check(`ws ${th}: Home: the narrowest list`, (await st()).sep1[1] === 220);
      await keyOn('g-sep1', 'End');
      s = await st();
      t.check(`ws ${th}: End: the widest list that leaves the diff room`, s.sep1[1] === s.sep1[3] && s.dv.w >= 360, s);
      await keyOn('g-sep1', 'Home'); await keyOn('g-sep1', 'ArrowRight', 8);
      const sep2 = await B.ev(`(function(){var b=document.getElementById('g-sep2').getBoundingClientRect();return {x:b.left+b.width/2,y:b.top+b.height/2};})()`);
      await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: sep2.x, y: sep2.y });
      await B.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: sep2.x, y: sep2.y, button: 'left', buttons: 1, clickCount: 1 });
      for (const dx of [30, 60, 100]) await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: sep2.x - dx, y: sep2.y, button: 'left', buttons: 1 });
      await B.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: sep2.x - 100, y: sep2.y, button: 'left', buttons: 0, clickCount: 1 });
      await sleep(80);
      s = await st();
      t.check(`ws ${th}: dragging the right separator 100 px left widens the right pane by 100 px`, s.sep2[1] === 520 && s.det.w >= 500, s);
      t.check(`ws ${th}: the widths are kept`, JSON.stringify(await B.ev(`T.stored('wscols')`)) === JSON.stringify({ l: 284, r: 520 }), await B.ev(`T.stored('wscols')`));

      /* ---------- The right pane: map, fold ---------- */
      await B.ev(`document.querySelector('[data-p=map]').click()`); await sleep(200);
      s = await st();
      const nodes = await B.ev(`document.querySelectorAll('#g-canvas .nd').length`);
      t.check(`ws ${th}: "Map" shows the map in the right pane instead of the neighbourhood`, s.cv.shown && !s.det.shown && s.cv.l >= s.dv.r && nodes === (await B.ev('T.rows()')).length
        && await B.ev(`document.querySelector('[data-p=map]').getAttribute('aria-pressed')`) === 'true', { s, nodes });
      t.check(`ws ${th}: the map's selection follows the list`, await B.ev(`(document.querySelector('#g-canvas .nd.on title')||{}).textContent`) === 'src/auth/session.ts\n\n↯ Resolved by hand in merge abc1234');  // def5678 took one side: no mark
      await B.ev(`T.pick(T.id('src/auth/token.ts'))`);
      t.check(`ws ${th}: picking another file moves the map's selection`, /^src\/auth\/token\.ts/.test(await B.ev(`(document.querySelector('#g-canvas .nd.on title')||{}).textContent`)));
      if (!dark) await t.shot('ws-1440-light-map');
      await B.ev(`document.getElementById('g-rpc').click()`); await sleep(100);
      s = await st();
      t.check(`ws ${th}: the fold button folds the right pane to a strip and the diff takes the room`, !s.cv.shown && !s.det.shown && s.rph.w < 60 && s.dv.w > s.vw - 284 - 120
        && await B.ev(`document.getElementById('g-rpc').getAttribute('aria-expanded')`) === 'false', s);
      await B.ev(`document.getElementById('g-rpc').click();document.querySelector('[data-p=nb]').click()`); await sleep(100);
      s = await st();
      t.check(`ws ${th}: unfolding brings the neighbourhood back`, s.det.shown && !s.cv.shown && s.sep2[1] === 520, s);

      /* ---------- Notes drawer, the View menu, and Esc's order ---------- */
      await B.ev(`document.getElementById('g-wsnotes').click()`); await sleep(80);
      s = await st();
      t.check(`ws ${th}: "Notes 0" opens the notes as a drawer from the right, focus in it`, s.drawer.shown && s.drawer.r === s.vw && s.drawer.t >= s.top.b - 1 && s.notesExp === 'true'
        && await B.ev(`!!document.activeElement.closest('#nt-panel')`), s);
      await B.key('Escape');
      s = await st();
      t.check(`ws ${th}: Esc closes the drawer first, the focus back on its button`, s.ws && !s.drawer.shown && s.notesExp === 'false' && s.active === 'g-wsnotes', s);
      await B.ev(`document.getElementById('g-mbtn').click();document.getElementById('g-tests').focus()`);
      t.check(`ws ${th}: the View menu opens in the top bar, inside the window`, await B.ev(`(function(){var r=document.getElementById('g-mpop').getBoundingClientRect();return !document.getElementById('g-mpop').hidden&&r.right<=innerWidth&&r.left>=0;})()`));
      await B.key('Escape');
      t.check(`ws ${th}: Esc closes the View menu and not the workspace`, (await st()).ws && await B.ev(`document.getElementById('g-mpop').hidden`));
      await B.ev(`document.getElementById('nt-pr-add').click()`); await sleep(50);
      await B.key('Escape');
      t.check(`ws ${th}: Esc in a note editor closes the editor, not the workspace`, (await st()).ws && await B.ev(`document.getElementById('nt-pred').hidden`));
      // A form field keeps its Esc (the tour picker during a tour is one): it lets go of the focus and the workspace stays.
      for (const [tag, id] of [['input', 'x-in'], ['select', 'x-sel'], ['textarea', 'x-ta']]) {
        await B.ev(`(function(){var e=document.createElement('${tag}');e.id='${id}';if('${tag}'==='input')e.type='text';document.getElementById('g-top').appendChild(e);e.focus();})()`);
        await B.key('Escape');
        t.check(`ws ${th}: Esc in a ${tag} does not close the workspace, it only lets go of the field`, (await st()).ws && await B.ev(`document.activeElement.id!=='${id}'`), await st());
        await B.ev(`document.getElementById('${id}').remove()`);
      }
      await B.ev(`document.activeElement.blur()`);
      await B.key('Escape');
      s = await st();
      t.check(`ws ${th}: then Esc closes the workspace: the page is back where it was, not inert, the address without #ws, focus on ⤢`,
        !s.ws && s.pos !== 'fixed' && !s.root && s.inert === 0 && !s.toc && s.hash === '' && s.sy === y0 && s.active === 'g-wsb' && s.plan.shown, { s, y0 });
      t.noErrors(`ws ${th}: no page errors`);
    }

    /* ---------- The key f, ✕, and #ws (the widths and the pane come back) ---------- */
    await B.ev(`document.querySelector('[data-p=map]').click()`);
    await B.ev(`document.activeElement.blur()`);
    await B.key('f'); await sleep(150);
    let s = await st();
    t.check('ws: f opens it, with the kept widths and pane', s.ws && s.sep1[1] === 284 && s.sep2[1] === 520 && s.cv.shown, s);
    await B.ev(`document.activeElement.blur()`);
    await B.key('f');
    t.check('ws: f again closes it', !(await st()).ws);
    await B.ev(`document.getElementById('nt-pr-add').click()`); await sleep(50);
    await B.key('f');
    t.check('ws: f while typing in a note does nothing', !(await st()).ws && await B.ev(`document.activeElement.tagName`) === 'TEXTAREA');
    await B.key('Escape');
    await B.ev(`document.getElementById('g-wsb').click()`);
    await B.ev(`document.getElementById('g-wsx').click()`);
    t.check('ws: ✕ closes it', !(await st()).ws);
    await B.open('about:blank');
    await t.reload(PLAN + '#ws');
    await sleep(200);
    s = await st();
    t.check('ws: #ws opens the page in the workspace with the kept widths and pane', s.ws && s.sep1[1] === 284 && s.sep2[1] === 520 && s.cv.shown && s.hash === '#ws', s);
    await B.ev(`document.querySelector('[data-p=nb]').click()`);
    // Tabs that do not fit give way to a picker.
    await B.ev(`[].forEach.call(document.querySelectorAll('#g-tabs [role=tab]'),function(b){b.textContent=b.textContent+' with a very long name for the tab bar '+'x'.repeat(40);});window.dispatchEvent(new Event('resize'))`);
    await sleep(80);
    s = await st();
    const pick = await B.ev(`({shown:!!document.getElementById('g-wspr').getClientRects().length,v:document.getElementById('g-wspr').value,opts:[].map.call(document.getElementById('g-wspr').options,function(o){return o.value;}),tabs:!!document.getElementById('g-tabs').getClientRects().length})`);
    t.check('ws: tabs that do not fit fold into a PR picker', s.fold && pick.shown && !pick.tabs && pick.v === 'P' && JSON.stringify(pick.opts) === '["P","Q"]' && s.top.b - s.top.t < 64, { s, pick });
    await B.ev(`(function(){var e=document.getElementById('g-wspr');e.value='Q';e.dispatchEvent(new Event('change'));})()`);
    t.check('ws: the picker switches the PR', await B.ev('T.tab()') === 'Q' && await B.ev(`document.getElementById('g-wspr').value`) === 'Q');
    t.check('ws: the hash link reloads into the workspace without page errors', B.errors.length === 0, B.errors.splice(0));
    // Leaving the width closes it.
    await B.ev(`T.pick(T.rows()[2].id)`);
    await B.viewport(1000, 900); await sleep(150);
    t.check('ws: a window narrower than 1100 px closes it', !(await st()).ws);
    const fo = await B.ev(`(function(){var a=document.activeElement,r=T.row(T.sel());return {tag:a&&a.tagName,inRow:!!a&&r.contains(a),shown:!!a&&!!a.getClientRects().length,btn:!document.getElementById('g-wsb').getClientRects().length};})()`);
    t.check('ws: closed that way (the ⤢ button is hidden), the focus goes to the selected step, not the page', fo.btn && fo.inRow && fo.shown, fo);
    await B.viewport(1440, 900, false);

    /* ---------- The address before #ws comes back on leaving, whichever way the workspace was entered ---------- */
    await t.fresh(PLAN);
    await B.ev(`location.hash='#risks'`); await sleep(60);
    await B.ev(`document.getElementById('g-wsb').click()`); await sleep(100);
    t.check('ws: the button puts #ws on the address', (await st()).ws && await B.ev('location.hash') === '#ws');
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(60);
    t.check('ws: leaving restores the address the button found (#risks)', !(await st()).ws && await B.ev('location.hash') === '#risks', await B.ev('location.hash'));
    await B.ev(`history.replaceState(null,'','#other');location.hash='#ws'`); await sleep(150);
    t.check('ws: #ws typed into the address opens it too', (await st()).ws);
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(60);
    t.check('ws: leaving restores the address from before that #ws (#other), not the one of the earlier session', await B.ev('location.hash') === '#other', await B.ev('location.hash'));
    await B.ev(`history.replaceState(null,'','#other')`);
    await B.open('about:blank');
    await t.reload(PLAN + '#ws'); await sleep(200);
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(60);
    t.check('ws: a page opened on #ws leaves it without an address hash', !(await st()).ws && await B.ev('location.hash') === '', await B.ev('location.hash'));
    t.noErrors('ws address: no page errors');

    /* ---------- The overview of a 103-file PR in the right pane ---------- */
    await t.fresh(BIG);
    await B.ev(`T.pick(T.rows()[10].id);document.getElementById('g-wsb').click()`); await sleep(100);
    await B.ev(`document.querySelector('[data-p=map]').click()`); await sleep(300);
    const ov = await B.ev(`(function(){var s=document.querySelector('#g-canvas .g-ovs'),c=document.getElementById('g-canvas').getBoundingClientRect(),r=s&&s.getBoundingClientRect();
      return {svg:!!s,h:r&&Math.round(r.height),ch:Math.round(c.height),w:r&&Math.round(r.width),cw:Math.round(c.width),boxes:document.querySelectorAll('#g-canvas .cl').length,t:s&&s.querySelector('.vp').getAttribute('transform')};})()`);
    t.check('ws: the overview of areas fills the right pane', ov.svg && ov.boxes > 3 && ov.h > ov.ch - 90 && Math.abs(ov.w - ov.cw) <= 4, ov);
    await B.ev(`document.querySelector('#g-canvas [data-z=in]').click()`); await sleep(50);
    t.check('ws: its zoom still works', await B.ev(`document.querySelector('#g-canvas .vp').getAttribute('transform')`) !== ov.t);
    await t.shot('ws-1440-light-overview');
    t.noErrors('ws overview: no page errors');

    /* ---------- At 1100 px: widths that follow the window, a top bar that fits ---------- */
    for (const url of [PLAN, t.url(t.fixtures, 'plan', 'review-pl.html')]) {
      await t.fresh(url, { width: 1100, height: 800 });
      await B.ev(`T.pick(T.rows()[1].id);document.getElementById('g-wsb').click()`); await sleep(150);
      s = await st();
      const bar = await B.ev(`(function(){var t=document.getElementById('g-top');return [t.scrollWidth,t.clientWidth];})()`);
      t.check(`ws 1100px ${url === PLAN ? 'en' : 'pl'}: the list and right pane follow the window, the diff keeps room, the top bar fits`, s.ws && s.sep1[1] === 264 && s.sep2[1] === 330 && s.dv.w >= 450 && bar[0] <= bar[1], { s, bar });
    }
    t.noErrors('ws 1100px: no page errors');

    /* ---------- Below 1100 px: no button, no key, no #ws ---------- */
    await t.fresh(PLAN, { width: 1000, height: 900 });
    s = await st();
    t.check('ws 1000px: the ⤢ button is hidden', !s.btn.shown && !s.ws, s);
    await B.ev(`document.activeElement.blur()`);
    await B.key('f');
    t.check('ws 1000px: f does nothing', !(await st()).ws);
    await B.open('about:blank');
    await t.reload(PLAN + '#ws');
    t.check('ws 1000px: #ws opens the page as usual', !(await st()).ws);
    t.noErrors('ws 1000px: no page errors');
  },
};
