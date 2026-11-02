'use strict';
// REQUIREMENT: every chart zooms and pans: the narrative's mermaid diagrams (flowchart and a long sequence diagram) and the
// flat map (40 files or fewer) have zoom in, zoom out, and fit buttons, Ctrl+wheel and pinch zoom, drag to pan, and the keys
// + - 0, and the page still scrolls with a plain wheel over them. The area overview keeps its own behaviour (core.js, wsmap.js).
// On the plan sample (a flat map) with diagrams added to its page: drawn by real mermaid when cdnjs answers, else a drawn
// svg put into the <pre> the way the Artifact host does after the page has loaded.
const fs = require('fs');
const path = require('path');
const { sleep } = require('./lib');

const SEQ = `sequenceDiagram
  autonumber
  participant UI as ekran
  participant GW as gateway
  participant API as serwer
  Note over UI,API: D · komenda bez odpowiedzi
${Array.from({ length: 12 }, (_, i) => `  UI->>GW: komenda ${i + 1}\n  GW->>API: operationId ${i + 1}\n  API-->>GW: odpowiedź ${i + 1}`).join('\n')}`;
const FLOW = `flowchart LR
  A["web"] --> B["api"]
  B --> C[("baza")]`;
// What the host draws when the page does not: tall (a long sequence diagram) and wide (a flowchart).
const TALL = '<svg viewBox="0 0 600 1800" xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="600" height="1800" fill="none" stroke="currentColor"/><text x="10" y="1790">end</text></svg>';
const WIDE = '<svg viewBox="0 0 1600 200" xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="1600" height="200" fill="none" stroke="currentColor"/></svg>';

// The pre's transform {z, x, y} (or the flat map svg's), the box's size, and the page's scroll.
const STATE = (sel, box) => `(function(){var e=document.querySelector(${JSON.stringify(sel)}),b=document.querySelector(${JSON.stringify(box)}),m=new DOMMatrix(getComputedStyle(e).transform),r=b.getBoundingClientRect(),q=e.getBoundingClientRect();
  return {z:+m.a.toFixed(3),x:+m.e.toFixed(1),y:+m.f.toFixed(1),w:r.width,h:r.height,sy:window.scrollY,inside:q.left>=r.left-1&&q.top>=r.top-1&&q.right<=r.right+1&&q.bottom<=r.bottom+1};})()`;

module.exports = {
  name: 'zoom',
  weight: 10,
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const src = t.url(t.fixtures, 'plan', 'review.html').replace(/^file:\/\//, '');
    let html = fs.readFileSync(src, 'utf8');
    const section = `<section id="zoomfx"><h2>Diagrams</h2><div class="diagram" id="dg-seq"><pre class="mermaid" id="pre-seq">\n${SEQ}\n</pre></div>\n<div class="diagram" id="dg-flow"><pre class="mermaid" id="pre-flow">\n${FLOW}\n</pre></div>\n<div style="height:1600px"></div></section>`;
    html = html.replace('</main>', section + '</main>');
    if (t.cdn) html = html.replace('</html>', '<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.15.0/mermaid.min.js"></script>\n</html>');
    const FILE = path.join(t.work, 'zoom.html');
    fs.writeFileSync(FILE, html);

    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(t.url(FILE), { dark });
      // A diagram the page did not draw is drawn now, as the Artifact host does.
      if (t.cdn) { for (let i = 0; i < 40 && !(await B.ev(`!!document.querySelector('#pre-seq svg')&&!!document.querySelector('#pre-flow svg')`)); i++) await sleep(250); }
      else await B.ev(`document.getElementById('pre-seq').innerHTML=${JSON.stringify(TALL)};document.getElementById('pre-flow').innerHTML=${JSON.stringify(WIDE)};`);
      await sleep(250);

      for (const [id, name] of [['seq', 'sequence diagram'], ['flow', 'flowchart']]) {
        const box = `#dg-${id}`, pre = `#pre-${id}`;
        await B.ev(`document.querySelector('${box}').scrollIntoView({block:'center'})`); await sleep(100);
        const info = await B.ev(`(function(){var d=document.querySelector('${box}'),b=d.querySelectorAll('.pz-bar button');return {pz:d.classList.contains('pz'),btns:[].map.call(b,function(x){return x.dataset.z;}),tab:d.tabIndex,role:d.getAttribute('role'),h:d.getBoundingClientRect().height,vh:window.innerHeight,hint:d.querySelector('.pz-bar').title};})()`);
        t.check(`zoom ${th} ${name}: a drawn diagram gets a box with zoom out, zoom in, and fit buttons, a tab stop, and a hint`, info.pz && JSON.stringify(info.btns) === '["out","in","fit"]' && info.tab === 0 && info.role === 'group' && /Ctrl\+wheel/.test(info.hint), info);
        t.check(`zoom ${th} ${name}: the box is no taller than three quarters of the window`, info.h <= info.vh * 0.75 + 1 && info.h >= 160, info);
        const s0 = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: it opens fitted to the width (never above 1:1)`, s0.z <= 1 && s0.z > 0 && (await B.ev(`document.querySelector('${pre}').getBoundingClientRect().width`)) <= s0.w + 1, s0);

        await B.ev(`document.querySelector('${box} [data-z=in]').click()`);
        const s1 = await B.ev(STATE(pre, box));
        await B.ev(`document.querySelector('${box} [data-z=out]').click();document.querySelector('${box} [data-z=out]').click()`);
        const s2 = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: the buttons zoom in and out`, s1.z > s0.z && s2.z < s1.z, [s0.z, s1.z, s2.z]);
        await B.ev(`document.querySelector('${box} [data-z=fit]').click()`);
        const s3 = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: Fit shows the whole diagram inside the box`, s3.inside, s3);

        // Ctrl+wheel zooms about the pointer and leaves the page where it is; a plain wheel scrolls the page and not the diagram.
        const r = await B.ev(`(function(){var b=document.querySelector('${box}').getBoundingClientRect();return {x:Math.round(b.left+b.width/2),y:Math.round(b.top+b.height/2)};})()`);
        const before = await B.ev(STATE(pre, box));
        await B.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: r.x, y: r.y, deltaX: 0, deltaY: -120, modifiers: 2 }); await sleep(120);
        const afterCtrl = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: Ctrl+wheel zooms in and the page does not scroll`, afterCtrl.z > before.z && afterCtrl.sy === before.sy, [before, afterCtrl]);
        await B.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: r.x, y: r.y, deltaX: 0, deltaY: 300, modifiers: 0 }); await sleep(250);
        const afterPlain = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: a plain wheel over the diagram scrolls the page and leaves the zoom alone`, afterPlain.sy > afterCtrl.sy && afterPlain.z === afterCtrl.z, [afterCtrl, afterPlain]);

        // Drag pans.
        await B.ev(`document.querySelector('${box}').scrollIntoView({block:'center'})`); await sleep(100);
        const r2 = await B.ev(`(function(){var b=document.querySelector('${box}').getBoundingClientRect();return {x:Math.round(b.left+b.width/2),y:Math.round(b.top+b.height/2)};})()`);
        const p0 = await B.ev(STATE(pre, box));
        await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: r2.x, y: r2.y });
        await B.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: r2.x, y: r2.y, button: 'left', buttons: 1, clickCount: 1 });
        for (const d of [20, 50, 80]) await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: r2.x - d, y: r2.y - d / 2, button: 'left', buttons: 1 });
        await B.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: r2.x - 80, y: r2.y - 40, button: 'left', buttons: 0, clickCount: 1 });
        const p1 = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: dragging pans the diagram without changing the zoom`, p1.x < p0.x - 40 && p1.y < p0.y - 20 && p1.z === p0.z, [p0, p1]);

        // Keys on the focused box: + - 0.
        await B.ev(`document.querySelector('${box}').focus()`);
        await B.key('0'); const k0 = await B.ev(STATE(pre, box));
        await B.key('+'); const k1 = await B.ev(STATE(pre, box));
        await B.key('-'); await B.key('-'); const k2 = await B.ev(STATE(pre, box));
        t.check(`zoom ${th} ${name}: the keys 0, +, and - fit, zoom in, and zoom out`, k0.inside && k1.z > k0.z && k2.z < k1.z, [k0.z, k1.z, k2.z]);

        // Pinch: two touches moving apart zoom (synthetic touch events, as the page sees them).
        const pinch = await B.ev(`(function(){var d=document.querySelector('${box}'),b=d.getBoundingClientRect(),cx=b.left+b.width/2,cy=b.top+b.height/2;
          function tc(id,x,y){return new Touch({identifier:id,target:d,clientX:x,clientY:y});}
          function fire(type,a,b2){var l=[tc(1,a,cy),tc(2,b2,cy)];d.dispatchEvent(new TouchEvent(type,{touches:type==='touchend'?[]:l,changedTouches:l,cancelable:true,bubbles:true}));}
          var z0=new DOMMatrix(getComputedStyle(document.querySelector('${pre}')).transform).a;
          fire('touchstart',cx-30,cx+30);fire('touchmove',cx-60,cx+60);fire('touchmove',cx-90,cx+90);fire('touchend',cx-90,cx+90);
          return {z0:z0,z1:new DOMMatrix(getComputedStyle(document.querySelector('${pre}')).transform).a};})()`);
        t.check(`zoom ${th} ${name}: a two-finger pinch zooms`, pinch.z1 > pinch.z0 * 1.5, pinch);
      }
      t.noErrors(`zoom ${th} diagrams: no page errors`);

      // The flat map.
      await t.fresh(t.url(FILE), { dark });
      await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(250);
      await B.ev(`document.getElementById('g-canvas').scrollIntoView({block:'start'})`); await sleep(100);
      const flat = await B.ev(`(function(){var c=document.getElementById('g-canvas');return {flat:c.classList.contains('flat'),ov:c.classList.contains('ov'),btns:[].map.call(c.querySelectorAll('.g-ovt [data-z]'),function(x){return x.dataset.z;}),pzv:!!c.querySelector('.g-pzv'),n:document.querySelectorAll('#g-canvas .nd').length};})()`);
      t.check(`zoom ${th} flat map: the map of 40 files or fewer has zoom out, zoom in, and fit buttons`, flat.flat && !flat.ov && flat.pzv && JSON.stringify(flat.btns) === '["out","in","fit"]' && flat.n > 3, flat);
      const SV = '#g-canvas .g-pzv>svg', BX = '#g-canvas .g-pzv';
      const f0 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: it opens at 1:1 from the top left, as the scrolled map did`, f0.z === 1 && f0.x === 0 && f0.y === 0, f0);
      await B.ev(`document.querySelector('#g-canvas [data-z=out]').click();document.querySelector('#g-canvas [data-z=out]').click()`);
      const f1 = await B.ev(STATE(SV, BX));
      await B.ev(`document.querySelector('#g-canvas [data-z=in]').click()`);
      const f2 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: the buttons zoom out and in`, f1.z < f0.z && f2.z > f1.z, [f0.z, f1.z, f2.z]);
      await B.ev(`document.querySelector('#g-canvas [data-z=fit]').click()`);
      const f3 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: Fit shows the whole map inside the box`, f3.inside, f3);
      const c = await B.ev(`(function(){var b=document.querySelector('${BX}').getBoundingClientRect();return {x:Math.round(b.left+b.width-8),y:Math.round(b.top+b.height-8)};})()`);
      const g0 = await B.ev(STATE(SV, BX));
      await B.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: c.x, y: c.y, deltaX: 0, deltaY: -120, modifiers: 2 }); await sleep(120);
      const g1 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: Ctrl+wheel zooms and the page does not scroll`, g1.z > g0.z && g1.sy === g0.sy, [g0, g1]);
      await B.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: c.x, y: c.y, deltaX: 0, deltaY: 200, modifiers: 0 }); await sleep(250);
      const g2 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: a plain wheel scrolls the page and leaves the zoom alone`, g2.sy > g1.sy && g2.z === g1.z, [g1, g2]);
      await B.ev(`document.getElementById('g-canvas').scrollIntoView({block:'start'})`); await sleep(100);
      const c2 = await B.ev(`(function(){var b=document.querySelector('${BX}').getBoundingClientRect();return {x:Math.round(b.left+b.width-6),y:Math.round(b.top+b.height-6)};})()`);
      const h0 = await B.ev(STATE(SV, BX));
      await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: c2.x, y: c2.y });
      await B.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: c2.x, y: c2.y, button: 'left', buttons: 1, clickCount: 1 });
      for (const d of [20, 50, 80]) await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: c2.x - d, y: c2.y - d / 2, button: 'left', buttons: 1 });
      await B.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: c2.x - 80, y: c2.y - 40, button: 'left', buttons: 0, clickCount: 1 });
      const h1 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: dragging pans the map without changing the zoom`, h1.x < h0.x - 40 && h1.z === h0.z, [h0, h1]);
      await B.ev(`document.querySelector('${BX}').focus()`);
      await B.key('0'); const m0 = await B.ev(STATE(SV, BX));
      await B.key('+'); const m1 = await B.ev(STATE(SV, BX));
      await B.key('-'); await B.key('-'); const m2 = await B.ev(STATE(SV, BX));
      t.check(`zoom ${th} flat map: the keys 0, +, and - fit, zoom in, and zoom out`, m0.inside && m1.z > m0.z && m2.z < m1.z, [m0.z, m1.z, m2.z]);
      const pinch = await B.ev(`(function(){var d=document.querySelector('${BX}'),b=d.getBoundingClientRect(),cx=b.left+b.width/2,cy=b.top+b.height/2;
        function tc(id,x,y){return new Touch({identifier:id,target:d,clientX:x,clientY:y});}
        function fire(type,a,b2){var l=[tc(1,a,cy),tc(2,b2,cy)];d.dispatchEvent(new TouchEvent(type,{touches:type==='touchend'?[]:l,changedTouches:l,cancelable:true,bubbles:true}));}
        var z0=new DOMMatrix(getComputedStyle(document.querySelector('${SV}')).transform).a;
        fire('touchstart',cx-30,cx+30);fire('touchmove',cx-60,cx+60);fire('touchmove',cx-90,cx+90);fire('touchend',cx-90,cx+90);
        return {z0:z0,z1:new DOMMatrix(getComputedStyle(document.querySelector('${SV}')).transform).a};})()`);
      t.check(`zoom ${th} flat map: a two-finger pinch zooms`, pinch.z1 > pinch.z0 * 1.5, pinch);
      // A click that is not a drag still selects a file; one that ends a drag does not.
      await B.ev(`document.querySelector('[data-z=fit]')&&document.querySelector('#g-canvas [data-z=fit]').click()`); await sleep(80);
      const node = await B.ev(`(function(){var g=document.querySelector('#g-canvas .nd:not(.ext)'),r=g.getBoundingClientRect();return {id:g.dataset.id||null,x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()`);
      const sel0 = await B.ev('T.sel()');
      await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: node.x, y: node.y });
      await B.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: node.x, y: node.y, button: 'left', buttons: 1, clickCount: 1 });
      for (const d of [10, 30]) await B.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: node.x + d, y: node.y, button: 'left', buttons: 1 });
      await B.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: node.x + 30, y: node.y, button: 'left', buttons: 0, clickCount: 1 }); await sleep(100);
      const sel1 = await B.ev('T.sel()');
      t.check(`zoom ${th} flat map: a drag that starts on a file pans and does not select it`, sel1 === sel0, [sel0, sel1]);
      const node2 = await B.ev(`(function(){var g=document.querySelector('#g-canvas .nd:not(.ext)'),r=g.getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()`);
      await B.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: node2.x, y: node2.y, button: 'left', buttons: 1, clickCount: 1 });
      await B.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: node2.x, y: node2.y, button: 'left', buttons: 0, clickCount: 1 }); await sleep(120);
      t.check(`zoom ${th} flat map: a plain click on a file still selects it`, (await B.ev('T.sel()')) !== null, await B.ev('T.sel()'));
      t.noErrors(`zoom ${th} flat map: no page errors`);
    }
  },
};
