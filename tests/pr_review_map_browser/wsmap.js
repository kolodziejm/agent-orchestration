'use strict';
// The workspace's left column as the map ("List | Map", the key m): its layout and width, the map following every
// selection (centred, gliding unless reduced motion is asked for, far files faded, a big PR's overview opening the
// selected file's area and closing the one it opened before), the file's header above the diff (path, role, note clamped to 3 lines, tour step, dependency and dependent chips, merges folded);
// the diff drawn unified while its column is narrow; the arc lane's cap in the workspace; and the conflict marks hidden
// on a PR where most files were combined by hand. On the plan, big, hub, and stack samples and their noise variants.
const fs = require('fs');
const path = require('path');
const { sleep, viewerOrder } = require('./lib');

const LAYOUT = `(function(){function q(s){var e=document.querySelector(s);if(!e||!e.getClientRects().length||getComputedStyle(e).display==='none')return null;var b=e.getBoundingClientRect();return {l:Math.round(b.left),r:Math.round(b.right),t:Math.round(b.top),b:Math.round(b.bottom),w:Math.round(b.width)};}
  var s1=document.getElementById('g-sep1');
  return {lmap:document.getElementById('graph').classList.contains('ws-lmap'),side:q('.g-side'),cv:q('#g-canvas'),dv:q('#dv'),det:q('#g-detail'),rph:q('#g-rph'),sep2:q('#g-sep2'),dinfo:q('#g-dinfo'),sw:q('.g-wsl'),
    pressed:[].map.call(document.querySelectorAll('[data-wl]'),function(b){return b.dataset.wl+':'+b.getAttribute('aria-pressed');}).join(),sep1:[s1.getAttribute('aria-label'),+s1.getAttribute('aria-valuenow'),+s1.getAttribute('aria-valuemin')],
    vw:innerWidth,stored:localStorage.getItem(T.key()+'wsleft'),active:document.activeElement&&(document.activeElement.closest('#g-canvas')?'map':document.activeElement.closest('#g-order')?'list':document.activeElement.id||document.activeElement.tagName)};})()`;
// The selected node on the map against the middle of the map's view: offsets, the flat map's scroll and its limits, the overview's transform.
const AT = `(function(){var cv=document.getElementById('g-canvas'),s=cv.querySelector('.g-ovs'),n=cv.querySelector('.nd.on');if(!n)return null;var r=n.getBoundingClientRect(),c=(s||cv).getBoundingClientRect(),num=n.querySelector('.num');
  return {path:n.querySelector('title').textContent.split('\\n')[0],dx:Math.round(r.left+r.width/2-(c.left+c.width/2)),dy:Math.round(r.top+r.height/2-(c.top+c.height/2)),
    sl:Math.round(cv.scrollLeft),st:Math.round(cv.scrollTop),ml:cv.scrollWidth-cv.clientWidth,mt:cv.scrollHeight-cv.clientHeight,t:s?s.querySelector('.vp').getAttribute('transform'):null,num:num?num.textContent.trim():null,
    ov:s?(function(){var v=s.querySelector('.vp'),m=/translate\\(([-\\d.]+),([-\\d.]+)\\) scale\\(([\\d.]+)\\)/.exec(v.getAttribute('transform')),b=v.getBBox();return {tx:+m[1],z:+m[3],right:Math.round(+m[1]+(b.x+b.width)*+m[3]),w:Math.round(c.width)};})():null,
    inView:r.left>=c.left-1&&r.right<=c.right+1&&r.top>=c.top-1&&r.bottom<=c.bottom+1};})()`;
// Centred on the flat map: in the middle on each axis, or the scroll at its limit on that side.
// Centred on the overview (across): in the middle, or the view stopped at the drawing's left or right edge.
const ovCentred = (a) => !!a && !!a.ov && (Math.abs(a.dx) <= 2 || (a.dx < 0 && a.ov.tx >= 15) || (a.dx > 0 && a.ov.right <= a.ov.w - 15));
const centred = (a) => !!a && (Math.abs(a.dx) <= 2 || (a.dx < 0 && a.sl === 0) || (a.dx > 0 && a.sl >= a.ml - 1)) && (Math.abs(a.dy) <= 2 || (a.dy < 0 && a.st === 0) || (a.dy > 0 && a.st >= a.mt - 1));
const DIFF = `({tbl:[].map.call(document.querySelectorAll('#dv-files table.dt'),function(t){return t.classList.contains('sbs')?'sbs':'uni';}).join(),
  pressed:(document.querySelector('[data-m][aria-pressed=true]')||{dataset:{}}).dataset.m,auto:[].filter.call(document.querySelectorAll('.dv-am'),function(a){return !a.hidden&&!!a.getClientRects().length;}).length,
  title:(document.querySelector('[data-m][aria-pressed=true]')||{}).title||'',stored:localStorage.getItem(T.key()+'diffmode'),dv:document.getElementById('dv').offsetWidth,
  cols:(function(){var t=document.querySelector('#dv-files table.dt'),r=t&&t.querySelector('tr:not(.hk)');return r?r.children.length:0;})(),
  code:(function(){var c=document.querySelector('#dv-files table.dt td.cd');var t=c&&c.closest('table');return c?Math.round(c.getBoundingClientRect().width/t.getBoundingClientRect().width*100):0;})()})`;
const CONF = `({chips:document.querySelectorAll('#g-order .g-cfb').length,marks:document.querySelectorAll('#g-canvas .cfm').length,note:(document.querySelector('#g-planb .g-cfn')||{}).textContent||null,
  box:document.getElementById('g-cfmarks').checked,label:document.getElementById('g-cfl').hidden?null:document.getElementById('g-cfl').textContent.trim(),stored:localStorage.getItem(T.key()+'cfmarks'),
  detail:document.querySelectorAll('#g-detail .g-cf').length})`;

module.exports = {
  name: 'wsmap',
  weight: 16, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const fx = (...p) => t.url(t.fixtures, ...p);
    const PLAN = fx('plan', 'review.html'), BIG = fx('big', 'review.html'), HUB = fx('hub', 'review.html'), STACK = fx('stack', 'review.html');
    const lay = () => B.ev(LAYOUT), at = () => B.ev(AT), diff = () => B.ev(DIFF);
    const motion = async (reduce, dark = false) => B.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }, { name: 'prefers-reduced-motion', value: reduce ? 'reduce' : 'no-preference' }] });
    let strings = null;

    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      /* ---------- The switch, the layout, the width, the key m, focus ---------- */
      await t.fresh(PLAN, { dark });
      if (!strings) strings = JSON.parse(await B.ev(`document.getElementById('review-config').textContent`)).strings;
      await B.ev(`T.pick(T.id('src/auth/session.ts'))`); await sleep(100);
      let s = await lay();
      t.check(`wsmap ${th}: "List | Map" is no part of the page outside the workspace`, !s.sw, s);
      await B.ev(`document.activeElement.blur()`);
      await B.key('m');
      t.check(`wsmap ${th}: m outside the workspace does nothing`, (await lay()).stored === null && !(await B.ev(`document.getElementById('graph').classList.contains('ws')`)));
      await B.ev(`document.getElementById('g-wsb').click()`); await sleep(200);
      s = await lay();
      t.check(`wsmap ${th}: in the workspace the top bar has "List | Map", the list picked`, !!s.sw && s.sw.b < 50 && s.pressed === 'list:true,map:false' && !!s.side && !s.lmap
        && await B.ev(`document.querySelector('.g-wsl').getAttribute('aria-label')`) === strings.wsLeft, s);
      await B.ev(`document.querySelector('[data-wl=map]').click()`); await sleep(250);
      s = await lay();
      t.check(`wsmap ${th}: "Map" puts the map in the left column (45% of the window), folds the right pane away, and gives the diff the rest`,
        s.lmap && !s.side && !!s.cv && s.cv.l <= 12 && Math.abs(s.cv.r - Math.round(s.vw * 0.45)) <= 2 && !s.det && !s.rph && !s.sep2 && s.dv.l >= s.cv.r && s.dv.l - s.cv.r <= 12 && s.dv.r === s.vw
        && s.pressed === 'list:false,map:true' && s.stored === 'map', s);
      t.check(`wsmap ${th}: the separator now sizes the map`, s.sep1[0] === strings.wsSepM && s.sep1[1] === Math.round(s.vw * 0.45) && s.sep1[2] === 300, s.sep1);
      t.check(`wsmap ${th}: the map shows the selection`, (await at()).path === 'src/auth/session.ts' && await B.ev(`document.querySelectorAll('#g-canvas .nd').length`) === (await B.ev('T.rows()')).length);
      t.check(`wsmap ${th}: the switch is announced`, await B.ev(`new Promise(function(r){setTimeout(function(){r(document.getElementById('nt-live').textContent);},80);})`) === `${strings.wsLeft}: ${strings.wsLeftMap}`);
      if (!dark) await t.shot('ws-1440-map-light'); else await t.shot('ws-1440-map-dark');
      await B.ev(`document.getElementById('g-sep1').focus()`); await B.key('ArrowRight');
      s = await lay();
      t.check(`wsmap ${th}: → on the separator widens the map by 16 px and keeps it apart from the list's width`, s.sep1[1] === Math.round(s.vw * 0.45) + 16 && s.cv.r === s.sep1[1]
        && JSON.stringify(await B.ev(`T.stored('wscols')`)) === JSON.stringify({ l: 340, r: 420, m: s.sep1[1] }), { s, stored: await B.ev(`T.stored('wscols')`) });
      await B.ev(`T.row(T.sel()).querySelector('.nm').focus();document.querySelector('[data-wl=list]').click()`); await sleep(150);
      await B.ev(`T.row(T.sel()).querySelector('.nm').focus()`);
      await B.key('m'); await sleep(200);
      s = await lay();
      t.check(`wsmap ${th}: m switches to the map, and the focus moves from the list to the selected file's box`, s.lmap && s.active === 'map' && await B.ev(`document.activeElement.classList.contains('on')`), s);
      await B.key('m'); await sleep(200);
      s = await lay();
      t.check(`wsmap ${th}: m again brings the list back, the focus on the selected step, the list's width as it was`, !s.lmap && !!s.side && s.side.w === 340 && s.active === 'list' && s.stored === 'list' && !!s.det, s);
      await B.ev(`document.getElementById('nt-pr-add').click()`); await sleep(50);
      await B.key('m');
      t.check(`wsmap ${th}: m while typing a note does nothing`, !(await lay()).lmap && await B.ev(`document.activeElement.tagName`) === 'TEXTAREA');
      await B.key('Escape');
      await B.ev(`document.activeElement.blur()`); await B.key('m'); await sleep(150);
      await B.open('about:blank'); await t.reload(PLAN + '#ws'); await sleep(250);
      s = await lay();
      t.check(`wsmap ${th}: a reload keeps the map column and its width`, s.lmap && s.cv.r === Math.round(s.vw * 0.45) + 16 && s.active === 'map', s);
      t.noErrors(`wsmap ${th}: no page errors`);
    }

    /* ---------- The flat map follows the selection: centred, gliding, far files faded ---------- */
    await t.fresh(PLAN);
    const order = viewerOrder(PLAN.replace(/^file:\/\//, ''));
    await B.ev(`T.pick(T.id('src/auth/session.ts'));document.getElementById('g-wsb').click()`); await sleep(150);
    await B.ev(`document.querySelector('[data-wl=map]').click()`); await sleep(250);
    // Far files: more than 2 links from the selected one (a test counts as the file it tests), not the previous or next step.
    const fade = async () => {
      const mode = await B.ev(`document.querySelector('[data-o][aria-pressed=true]').dataset.o`), subj = order.order[mode].P.subj, P = order.data.prs[0];
      const rows = (await B.ev('T.rows()')).sort((a, b) => a.no - b.no).map((r) => r.id), sel = await B.ev('T.sel()'), i = rows.indexOf(sel), rp = (x) => subj[x] || x, adj = {};
      for (const e of P.edges) { const a = rp(e.from), b = rp(e.to); if (a !== b) { (adj[a] = adj[a] || []).push(b); (adj[b] = adj[b] || []).push(a); } }
      const dist = { [rp(sel)]: 0 }, q = [rp(sel)];
      while (q.length) { const k = q.shift(); if (dist[k] >= 2) continue; for (const m of adj[k] || []) if (dist[m] == null) { dist[m] = dist[k] + 1; q.push(m); } }
      const near = (id) => id === rows[i - 1] || id === rows[i + 1] || dist[id] != null || (subj[id] && dist[subj[id]] != null);
      const want = rows.filter((id) => !near(id)).sort();
      const got = await B.ev(`[].filter.call(document.querySelectorAll('#g-canvas .nd'),function(g){return g.classList.contains('far');}).map(function(g){return T.id(g.querySelector('title').textContent.split('\\n')[0]);}).sort()`);
      const op = await B.ev(`[].map.call(document.querySelectorAll('#g-canvas .nd.far'),function(g){return +getComputedStyle(g).opacity;})`);
      return { want, got, op };
    };
    let f = await fade();
    t.check('wsmap follow: files more than 2 links away fade (the selected one, its links, and the previous and next steps do not)', f.want.length > 0 && JSON.stringify(f.got) === JSON.stringify(f.want) && f.op.every((o) => o < 0.3), f);
    let a = await at();
    t.check('wsmap follow: the map opens centred on the selected file', centred(a), a);
    const stepTo = async (js) => { const before = await B.ev(`(function(){${js};var c=document.getElementById('g-canvas');return [Math.round(c.scrollLeft),Math.round(c.scrollTop)];})()`); await sleep(700); return { before, after: await at() }; };
    let r = await stepTo(`document.getElementById('g-next').click()`);
    t.check('wsmap follow: Next selects the next step and the map centres it', r.after.path === await B.ev(`T.data().prs[0].nodes.find(function(n){return n.id===T.sel();}).path`) && centred(r.after), r);
    r = await stepTo(`document.getElementById('g-prev').click()`);
    t.check('wsmap follow: Previous too', r.after.path === 'src/auth/session.ts' && centred(r.after), r);
    const far = await B.ev(`(function(){var g=[].find.call(document.querySelectorAll('#g-canvas .nd'),function(x){return /fmt\\.ts|api\\.ts|translations|docs/.test(x.querySelector('title').textContent);});return g.querySelector('title').textContent.split('\\n')[0];})()`);
    r = await stepTo(`[].find.call(document.querySelectorAll('#g-canvas .nd'),function(x){return x.querySelector('title').textContent.split('\\n')[0]===${JSON.stringify(far)};}).dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
    t.check('wsmap follow: a click on a box selects it and centres it', r.after.path === far && await B.ev(`T.sel()`) === await B.ev(`T.id(${JSON.stringify(far)})`) && centred(r.after), r);
    await B.ev(`document.querySelector('#g-canvas .nd.on').focus()`); await B.key('ArrowUp'); await B.key('Enter'); await sleep(700);
    a = await at();
    t.check('wsmap follow: the keyboard (arrows, Enter) selects and centres', a.path !== far && centred(a) && await B.ev(`document.activeElement.classList.contains('on')`), a);
    r = await stepTo(`window.__gsel(T.id('src/auth/token.ts'))`);
    t.check('wsmap follow: a jump (a note, a tour step, a reference) centres too', r.after.path === 'src/auth/token.ts' && centred(r.after), r);
    await motion(true);
    const now = await B.ev(`(function(){document.getElementById('g-next').click();var c=document.getElementById('g-canvas');return [Math.round(c.scrollLeft),Math.round(c.scrollTop)];})()`);
    await sleep(300); a = await at();
    t.check('wsmap follow: with reduced motion the map jumps there at once', now[0] === a.sl && now[1] === a.st && centred(a), { now, a });
    await motion(false);
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(100);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(150);
    t.check('wsmap follow: the page\'s own map view keeps its plain dimming (no faded files outside the workspace)', await B.ev(`document.querySelectorAll('#g-canvas .nd').length>5&&!document.querySelector('#g-canvas .far')&&!!document.querySelector('#g-canvas .nd.on')`));
    await B.ev(`document.querySelector('[data-v=list]').click();document.getElementById('g-wsb').click()`); await sleep(250);
    t.check('wsmap follow: back in the workspace the map column is still picked', (await lay()).lmap);
    t.noErrors('wsmap follow: no page errors');

    /* ---------- The file's header above the diff: path, lines, role, note (clamped), tour step, merges folded ---------- */
    await B.ev(`T.pick(T.id('src/auth/session.ts'))`); await sleep(150);
    const DI = `(function(){var d=document.getElementById('g-dinfo'),f=document.querySelector('#dv-files details.df'),h=document.querySelector('#dv .dv-head'),q=function(s){var e=d.querySelector(s);return e?e.textContent:null;},n=d.querySelector('.dn'),m=d.querySelector('.dnm'),c=d.querySelector('details.dcf');
      return {shown:!!d.getClientRects().length,path:q('.dm .p'),lt:q('.dm .lt'),role:q('.dr'),note:n?n.innerHTML:null,noteH:n?Math.round(n.getBoundingClientRect().height):0,lh:n?parseFloat(getComputedStyle(n).lineHeight):0,
        more:m&&!m.hidden?m.textContent:null,tour:q('.dt'),cfSum:c?c.querySelector('summary').textContent:null,open:!!(c&&c.open),
        cf:[].map.call(d.querySelectorAll('.g-cf'),function(x){return x.querySelector('code').textContent;}),cfShown:[].filter.call(d.querySelectorAll('.g-cf'),function(x){return x.checkVisibility();}).length,
        h:Math.round(d.getBoundingClientRect().height),top:f?Math.round(f.getBoundingClientRect().top):null,above:!!f&&d.getBoundingClientRect().bottom<=f.getBoundingClientRect().top&&d.getBoundingClientRect().top>=h.getBoundingClientRect().bottom,
        title:document.getElementById('dv-title').textContent,panel:!!document.getElementById('g-detail').getClientRects().length,
        rows:[].map.call(d.querySelectorAll('.dnb'),function(r){var ch=[].slice.call(r.querySelectorAll('.dch')),mo=r.querySelector('.dmo'),sh=ch.filter(function(c){return !c.hidden;});
          return {side:r.classList.contains('dep')?'dep':'use',k:r.querySelector('.k').textContent,ids:ch.map(function(c){return c.dataset.go;}),text:ch.map(function(c){return c.textContent;}),shown:sh.length,
            x:ch.map(function(c){return c.classList.contains('x');}),ty:ch.map(function(c){return c.classList.contains('ty');}),aria:ch.map(function(c){return c.getAttribute('aria-label');}),
            none:(r.querySelector('.no0')||{}).textContent||null,mo:mo&&!mo.hidden?mo.textContent:null,exp:mo?mo.getAttribute('aria-expanded'):null,h:Math.round(r.getBoundingClientRect().height),
            colour:getComputedStyle(r.querySelector('.k')).color,end:sh.length?Math.round(sh[sh.length-1].getBoundingClientRect().right):0,moL:mo&&!mo.hidden?Math.round(mo.getBoundingClientRect().left):0};})};})()`;
    // The neighbourhood pane's lists (rendered, though hidden, in the map column): [data-go, text] per item, side by side.
    const PANE = `(function(){function l(s){return [].map.call(document.querySelectorAll('#g-detail .g-nbc.'+s+' .g-nbi'),function(b){return [b.dataset.go,b.textContent];});}
      var sh=[].map.call(document.querySelectorAll('#g-detail .g-nbs [data-go]'),function(b){return b.dataset.go;});return {dep:l('dep'),use:l('use'),sh:sh};})()`;
    const HL = `(function(){var e=document.querySelector('#g-canvas .hl');return e?((e.querySelector('title')||{}).textContent||'').split('\\n')[0]:null;})()`;
    let di = await B.ev(DI);
    t.check('header: in the map column the file\'s header sits between the diff\'s "Step n · file" and its files: path, layer and lines; its merges folded under one line', di.shown && di.above && !di.panel
      && /^Step \d+ · session\.ts$/.test(di.title) && di.path === 'src/auth/session.ts' && di.lt === 'Logic · +1 / −1' && di.role === null && di.note === null
      && di.cfSum === '↯ ' + strings.dinfoMerges.replace('{n}', '2') && !di.open && di.cfShown === 0 && di.h < 115, di);
    let pane = await B.ev(PANE);
    t.check('header: two rows of chips, "Depends on:" in blue and "Used by:" in orange, the same files in the same order as the neighbourhood pane (a later PR\'s file with its PR, dashed); "none" when empty',
      JSON.stringify(di.rows.map((r) => [r.side, r.k])) === JSON.stringify([['dep', strings.dependsOn + ':'], ['use', strings.usedBy + ':']]) && di.rows[0].none === strings.none && di.rows[0].ids.length === 0
      && JSON.stringify(di.rows[1].ids.map((x, i) => [x, di.rows[1].text[i]])) === JSON.stringify(pane.use) && pane.use.length === 4 && di.rows[1].x.join() === 'false,false,false,true' && /^Q #12web\/app\.ts$/.test(di.rows[1].text[3])
      && di.rows.every((r) => r.h <= 24 && r.mo === null) && di.rows[0].colour !== di.rows[1].colour, { rows: di.rows, pane });
    // A chip under the pointer marks its box on the map; a click selects it and the map follows.
    await B.ev(`document.querySelector('#g-dinfo .dnb.use .dch').dispatchEvent(new MouseEvent('mouseenter'))`);
    const hl1 = await B.ev(HL);
    await B.ev(`document.querySelector('#g-dinfo .dnb.use .dch').dispatchEvent(new MouseEvent('mouseleave'))`);
    t.check('header: hovering a chip marks its file on the map, leaving clears it', hl1 === 'src/auth/index.ts' && await B.ev(HL) === null, hl1);
    await B.ev(`document.querySelector('#g-dinfo .dnb.use .dch').click()`); await sleep(700);
    a = await at();
    t.check('header: a chip\'s click selects its file and the map follows', await B.ev('T.sel()') === await B.ev(`T.id('src/auth/index.ts')`) && a.path === 'src/auth/index.ts' && centred(a), a);
    await B.ev(`window.__gsel(T.id('src/auth/session.ts'))`); await sleep(80);
    await B.ev(`document.querySelector('#g-dinfo details.dcf summary').click()`); await sleep(60);
    di = await B.ev(DI);
    t.check('header: the merges unfold to each one with its command', di.open && di.cfShown === 2 && JSON.stringify(di.cf) === JSON.stringify(['git show --remerge-diff abc1234 -- src/auth/session.ts', 'git show --remerge-diff def5678 -- src/auth/session.ts']), di);
    const copied = await B.ev(`new Promise(function(r){window.__c=null;navigator.clipboard.writeText=function(x){window.__c=x;return Promise.resolve();};document.querySelector('#g-dinfo .g-cf button').click();setTimeout(function(){r(window.__c);},100);})`);
    t.check('header: "Copy" copies the command', copied === 'git show --remerge-diff abc1234 -- src/auth/session.ts', copied);
    await B.ev(`window.__gsel(T.id('src/auth/token.ts'))`); await sleep(80);
    di = await B.ev(DI);
    t.check('header: the merges stay unfolded from file to file; one that took a side reads ⇢', di.open && di.cfSum === '⇢ ' + strings.dinfoMerges.replace('{n}', '1') && di.cf.length === 1, di);
    await B.ev(`window.__gsel(T.id('src/util/fmt.ts'))`); await sleep(80);
    di = await B.ev(DI);
    t.check('header: a file with no role, note, merges, or links is its path line and two "none" rows', di.shown && di.cfSum === null && di.path === 'src/util/fmt.ts' && di.lt === 'Logic · +1 / −0' && di.h < 95
      && di.rows.every((r) => r.none === strings.none), di);
    await B.key('m'); await sleep(150);
    t.check('header: with the list (and its neighbourhood pane) the header is gone', !(await B.ev(DI)).shown && (await B.ev(DI)).panel);
    t.noErrors('header: no page errors');
    await t.fresh(STACK);
    await B.ev(`T.pick(T.id('src/logic/item.service.ts'));document.getElementById('g-wsb').click()`); await sleep(150);
    await B.key('m'); await sleep(200);
    di = await B.ev(DI);
    t.check('header: the role and the whole note show without a click (a short note has no "more")', di.role === 'Lists items' && di.note === 'Builds two <code>Item</code>s.' && di.more === null && di.noteH > 0, di);
    const tyAt = di.rows[0].ids.indexOf(await B.ev(`T.id('src/contracts/item.schema.ts')`));
    t.check('header: a type-only dependency\'s chip is dashed and says so', tyAt >= 0 && di.rows[0].ty[tyAt] && di.rows[0].aria[tyAt].endsWith(' · ' + strings.nbType) && di.rows[0].ty.filter(Boolean).length === 1, di.rows[0]);
    await t.fresh(HUB);
    await B.ev(`T.pick(T.id('apps/mobile/src/auth/oauth-session.ts'));document.getElementById('g-wsb').click()`); await sleep(150);
    await B.key('m'); await sleep(250);
    di = await B.ev(DI);
    t.check('header: the role shows', di.role === 'Exchanges the OAuth code for a token' && di.note === null, di);
    const hubStr = JSON.parse(await B.ev(`document.getElementById('review-config').textContent`)).strings;
    pane = await B.ev(PANE);
    t.check('header: the shared dependencies close the "Depends on" row, marked ◆ (as the pane\'s "+ shared:" line)', pane.sh.length >= 2
      && JSON.stringify(di.rows[0].ids) === JSON.stringify(pane.dep.map((x) => x[0]).concat(pane.sh)) && di.rows[0].text.slice(-pane.sh.length).every((x) => x[0] === '◆')
      && di.rows[0].aria.slice(-pane.sh.length).every((x) => x.startsWith(hubStr.usesShared.split('{')[0])), { rows: di.rows[0], pane });
    // A shared dependency used by 17 files: one line of chips, the rest folded into "+n", which unfolds them in place.
    await B.ev(`window.__gsel(T.id('packages/i18n/src/index.ts'))`); await sleep(150);
    await B.ev(`document.querySelector('#g-detail [data-more=use]').click()`); await sleep(80); // the pane's whole list, to compare
    pane = await B.ev(PANE); di = await B.ev(DI);
    let u = di.rows[1];
    t.check('header: a row longer than its line shows what fits and "+n" for the rest, right after the last chip', u.ids.length === pane.use.length && pane.use.length > 12 && JSON.stringify(u.ids) === JSON.stringify(pane.use.map((x) => x[0]))
      && u.shown >= 2 && u.shown < u.ids.length && u.mo === `+${u.ids.length - u.shown}` && u.exp === 'false' && u.h <= 24 && u.moL - u.end >= 0 && u.moL - u.end <= 12, u);
    const hdr = di.h;
    await B.ev(`document.querySelector('#g-dinfo .dnb.use .dmo').click()`); await sleep(60);
    u = (await B.ev(DI)).rows[1];
    t.check('header: "+n" unfolds the row (all chips, wrapping) and then folds it back', u.shown === u.ids.length && u.mo === hubStr.dinfoLess && u.exp === 'true' && u.h > 30, u);
    await B.ev(`document.querySelector('#g-dinfo .dnb.use .dmo').click()`); await sleep(60);
    di = await B.ev(DI); u = di.rows[1];
    t.check('header: folded again it is one line', u.shown < u.ids.length && u.mo === `+${u.ids.length - u.shown}` && u.exp === 'false' && di.h === hdr, u);
    // Keyboard: the chips and "+n" are buttons; Shift+Tab from "+n" reaches the last shown chip, which marks its file (here
    // on the overview of a 45-file PR: its box, or its area's box when that is closed).
    await B.ev(`document.querySelector('#g-dinfo .dnb.use .dmo').focus()`);
    await B.key('Tab', 8);
    const kf = await B.ev(`({id:document.activeElement.dataset.go,cls:document.activeElement.className})`);
    const kh = await B.ev(`(function(){var e=document.querySelector('#g-canvas .hl');return e?e.getAttribute('class'):null;})()`);
    t.check('header: the keyboard reaches the chips, and a focused chip marks its file on the map', kf.cls === 'dch' && kf.id === u.ids[u.shown - 1] && /\b(nd|cl)\b/.test(kh || ''), { kf, kh });
    await B.key('Enter'); await sleep(300);
    t.check('header: Enter on a chip selects its file', await B.ev('T.sel()') === kf.id);
    await t.shot('ws-1440-map-header-hub');
    // The stack sample with a long note and a tour of three steps (two on one file), written beside the suite's files.
    const src = fs.readFileSync(STACK.replace(/^file:\/\//, ''), 'utf8'), a0 = src.indexOf('id="graph-data">'), e0 = src.indexOf('</script>', a0);
    const gd = JSON.parse(src.slice(src.indexOf('>', a0) + 1, e0)), A = gd.prs[0], svc = A.nodes.find((x) => x.path === 'src/logic/item.service.ts'), dom = A.nodes.find((x) => x.path === 'src/domain/item.ts');
    svc.note = 'Builds the list. ' + 'It reads every item through the domain factory, keeps their order, and returns them as one page. '.repeat(6);
    gd.tours = [{ id: 'flow', name: 'Items flow', steps: [{ node: svc.id, path: svc.path, side: 'new', a: 1, b: 1, note: 'Imports the factory' },
      { node: svc.id, path: svc.path, side: 'new', a: 3, b: 3, note: 'Lists two items' }, { node: dom.id, path: dom.path, side: 'new', a: 2, b: 2, note: 'Makes an item' }] }];
    const LONG = path.join(t.work, 'long.html');
    fs.writeFileSync(LONG, src.slice(0, src.indexOf('>', a0) + 1) + JSON.stringify(gd).replace(/</g, '\\u003c') + src.slice(e0));
    await t.fresh(t.url(LONG));
    await B.ev(`T.pick(T.id('src/logic/item.service.ts'));document.getElementById('g-wsb').click()`); await sleep(150);
    await B.key('m'); await sleep(250);
    di = await B.ev(DI);
    t.check('header: a long note shows its first 3 lines and "more", the diff still starting high', di.note.startsWith('Builds the list.') && Math.abs(di.noteH - 3 * di.lh) <= 2 && di.more === strings.dinfoMore && di.h < 200 && di.top < 345, di);
    await t.shot('ws-1440-map-header');
    await B.ev(`document.querySelector('#g-dinfo .dnm').click()`);
    di = await B.ev(DI);
    t.check('header: "more" shows the whole note, then reads "less"', di.noteH > 4 * di.lh && di.more === strings.dinfoLess && await B.ev(`document.querySelector('#g-dinfo .dnm').getAttribute('aria-expanded')`) === 'true', di);
    await B.ev(`(function(){var s=document.getElementById('g-tour');s.value='flow';s.dispatchEvent(new Event('change'));})()`); await sleep(300);
    di = await B.ev(DI);
    t.check('header: during a tour it shows the step\'s note', di.tour === 'Tour “Items flow” · step 1 of 3: Imports the factory' && di.path === 'src/logic/item.service.ts', di);
    await B.ev(`document.getElementById('g-tnext').click()`); await sleep(200);
    t.check('header: the next step on the same file updates it', (await B.ev(DI)).tour === 'Tour “Items flow” · step 2 of 3: Lists two items');
    await B.ev(`document.getElementById('g-tnext').click()`); await sleep(300);
    di = await B.ev(DI);
    t.check('header: and a step on another file', di.tour === 'Tour “Items flow” · step 3 of 3: Makes an item' && di.path === 'src/domain/item.ts', di);
    await B.ev(`document.getElementById('g-texit').click()`); await sleep(200);
    t.check('header: no tour, no step line', (await B.ev(DI)).tour === null && (await lay()).lmap);
    t.noErrors('header pages: no page errors');

    /* ---------- The overview of a big PR in the map column ---------- */
    await t.fresh(BIG);
    const rows = await B.ev('T.rows()');
    await B.ev(`T.pick(T.rows()[30].id);document.getElementById('g-wsb').click()`); await sleep(150);
    await B.key('m'); await sleep(400);
    const OV = `(function(){var c=document.getElementById('g-canvas');return {ov:!!c.querySelector('.g-ovs'),open:[].map.call(c.querySelectorAll('.cl.open'),function(g){return g.querySelector('.cll').textContent;}),
      mapx:localStorage.getItem(T.key()+'mapx'),mapz:localStorage.getItem(T.key()+'mapz')};})()`;
    let ov = await B.ev(OV); a = await at();
    const areaOf = async () => B.ev(`(function(){var n=document.querySelector('#g-canvas .nd.on'),g=n&&n.parentNode;var b=[].find.call(document.querySelectorAll('#g-canvas .cl.open'),function(c){var r=c.getBoundingClientRect(),q=n.getBoundingClientRect();return q.left>=r.left&&q.right<=r.right&&q.top>=r.top&&q.bottom<=r.bottom;});return b?b.querySelector('.cll').textContent:null;})()`);
    t.check('wsmap overview: above 40 core files the map column shows the overview, only the selected file\'s area open, centred on its box', ov.ov && ov.open.length === 1 && ov.open[0] === await areaOf() && ovCentred(a) && a.inView, { ov, a });
    t.check('wsmap overview: the box keeps its step number', a.num === String(rows[30].no), a);
    t.check('wsmap overview: the area opened for the selection is not kept, nor the view', ov.mapx === null && ov.mapz === null, ov);
    const first = ov.open[0];
    let n = 0;
    while (n < 40 && (await B.ev(OV)).open[0] === first) { await B.ev(`document.getElementById('g-next').click()`); n++; }
    await sleep(500);
    ov = await B.ev(OV); a = await at();
    t.check('wsmap overview: stepping into another area opens it and closes the one opened before', n < 40 && ov.open.length === 1 && ov.open[0] !== first && ov.open[0] === await areaOf() && a.inView && ovCentred(a), { ov, n, a });
    // An area the reader opens stays open as the selection moves on.
    const closed = await B.ev(`[].find.call(document.querySelectorAll('#g-canvas .cl:not(.open)'),function(g){return !/shared|←/.test(g.querySelector('.cll').textContent);}).querySelector('.cll').textContent`);
    await B.ev(`[].find.call(document.querySelectorAll('#g-canvas .cl'),function(g){return g.querySelector('.cll').textContent===${JSON.stringify(closed)};}).dispatchEvent(new MouseEvent('click',{bubbles:true}))`); await sleep(100);
    await B.ev(`document.getElementById('g-prev').click()`); await sleep(100);
    ov = await B.ev(OV);
    t.check('wsmap overview: an area the reader opened stays open (and is kept) as the selection moves', ov.open.includes(closed) && /\S/.test(ov.mapx || '') && JSON.parse(ov.mapx).P.length === 1, ov);
    // Gliding: the view moves after the selection, over a few frames; with reduced motion it is there at once. Between
    // two files far apart (steps 31 and 61), so the view has to move.
    const glide = async (i) => { const t0 = await B.ev(`(function(){window.__gsel(T.rows()[${i}].id);return document.querySelector('#g-canvas .vp').getAttribute('transform');})()`); await sleep(500); const a1 = await at(); return { t0, t1: a1.t, a: a1 }; };
    await glide(30);
    let gl = await glide(60);
    t.check('wsmap overview: the view glides to the selected file', gl.t0 !== gl.t1 && ovCentred(gl.a) && gl.a.inView, gl);
    await motion(true);
    gl = await glide(30);
    t.check('wsmap overview: with reduced motion it jumps there at once', gl.t0 === gl.t1 && ovCentred(gl.a) && gl.a.inView, gl);
    await motion(false);
    // The zoom is kept for the page's session: back from the list it is as it was; not stored.
    await B.ev(`document.querySelector('#g-canvas [data-z=in]').click()`); await sleep(50);
    const z1 = (/scale\(([\d.]+)\)/.exec((await at()).t) || [])[1];
    await B.key('m'); await sleep(100); await B.key('m'); await sleep(300);
    const z2 = (/scale\(([\d.]+)\)/.exec((await at()).t) || [])[1];
    t.check('wsmap overview: the zoom is kept while the page is open, not stored', z1 && z1 === z2 && z1 !== '0.700' && (await B.ev(OV)).mapz === null, { z1, z2 });
    await t.shot('ws-1440-map-overview');
    t.noErrors('wsmap overview: no page errors');

    /* ---------- The diff draws unified while its column is narrow ---------- */
    await t.fresh(PLAN);
    await B.ev(`T.pick(T.id('src/auth/session.ts'))`); await sleep(100);
    let d = await diff();
    t.check('diff: on the page (not the workspace) the diff keeps the reader\'s mode, whatever its width', d.tbl === 'sbs' && d.pressed === 'sbs' && d.auto === 0 && d.dv < 900, d);
    await B.ev(`document.getElementById('g-wsb').click()`); await sleep(200);
    d = await diff();
    t.check('diff: in the workspace a column under 900 px draws unified, "auto" on its button, the stored pick untouched', d.dv < 900 && d.tbl === 'uni' && d.pressed === 'uni' && d.auto === 1 && d.stored === null
      && d.title === strings.diffAutoTitle.replace('{w}', '900'), d);
    t.check('diff: a unified table has three columns, the code taking most of its width', d.cols === 3 && d.code > 80, d);
    await B.ev(`document.getElementById('g-rpc').click()`); await sleep(200);
    d = await diff();
    t.check('diff: folding the right pane widens the column past 900 px and side by side comes back', d.dv >= 900 && d.tbl === 'sbs' && d.pressed === 'sbs' && d.auto === 0, d);
    await B.ev(`document.getElementById('g-rpc').click()`); await sleep(200);
    t.check('diff: narrow again, unified again', (await diff()).tbl === 'uni');
    await B.ev(`document.querySelector('[data-m=sbs]').click()`); await sleep(100);
    d = await diff();
    t.check('diff: picking side by side while narrow holds (and is stored)', d.tbl === 'sbs' && d.pressed === 'sbs' && d.auto === 0 && d.stored === 'sbs', d);
    await B.ev(`document.getElementById('g-rpc').click()`); await sleep(150); await B.ev(`document.getElementById('g-rpc').click()`); await sleep(200);
    t.check('diff: after the width crosses the line and back, the switch works again', (await diff()).tbl === 'uni');
    await B.ev(`document.getElementById('g-wsx').click()`); await sleep(200);
    d = await diff();
    t.check('diff: leaving the workspace brings the pick back', d.tbl === 'sbs' && d.pressed === 'sbs' && d.auto === 0, d);
    await t.fresh(PLAN, { width: 2000, height: 1250 });
    await B.ev(`T.pick(T.id('src/auth/session.ts'));document.getElementById('g-wsb').click()`); await sleep(150);
    await B.key('m'); await sleep(250);
    d = await diff();
    t.check('diff: at 2000 px the map column leaves the diff wide: side by side', d.dv >= 900 && d.tbl === 'sbs' && d.auto === 0, d);
    await t.shot('ws-2000-map');
    await B.viewport(1440, 900); await sleep(300);
    d = await diff();
    t.check('diff: narrowing the window to 1440 px makes it unified', d.dv < 900 && d.tbl === 'uni' && d.auto === 1, d);
    t.noErrors('diff: no page errors');

    /* ---------- The arc lane's cap in the workspace's list ---------- */
    await t.fresh(HUB);
    const idx = await B.ev(`T.id('packages/i18n/src/index.ts')`);
    await B.ev(`T.pick('${idx}')`); await sleep(100);
    const page = await B.ev(`({more:(document.querySelector('#g-lane text.more')||{}).textContent||null,n:document.querySelectorAll('#g-lane path.arc').length})`);
    await B.ev(`document.getElementById('g-wsb').click()`); await sleep(250);
    const ws = await B.ev(`({more:(document.querySelector('#g-lane text.more')||{}).textContent||null,n:document.querySelectorAll('#g-lane path.arc').length})`);
    t.check('lane cap: the workspace\'s list caps the selected shared dependency\'s arcs like the page does', !!page.more && page.more === ws.more && page.n === ws.n, { page, ws });
    await t.shot('ws-1440-lane-cap');
    t.noErrors('lane cap: no page errors');

    /* ---------- Conflict marks: hidden when most files were combined by hand ---------- */
    const conf = async () => B.ev(CONF);
    const noteText = (lang, n) => { const c = lang === 'pl' ? (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? 'few' : 'many') : 'other'; return strings.cfNoise[c].replace('{n}', n); };
    await t.fresh(fx('plan', 'noise11.html'));
    let c = await conf();
    t.check('conflicts: all 11 files of a PR combined by hand (more than 10, more than a quarter): no chips, the plan says why in one line, the View toggle off', c.chips === 0 && c.note === noteText('en', 11)
      && c.box === false && c.label === strings.cfMarks && c.stored === null, c);
    await B.ev(`T.pick(T.rows()[0].id)`); await sleep(60);
    t.check('conflicts: the detail panel still lists the file\'s merge', (await conf()).detail === 1);
    await B.ev(`document.querySelector('[data-v=map]').click()`); await sleep(150);
    t.check('conflicts: no marks on the map either', (await conf()).marks === 0);
    await B.ev(`document.getElementById('g-mbtn').click();document.getElementById('g-cfmarks').click()`); await sleep(150);
    c = await conf();
    t.check('conflicts: "Conflict marks" in View turns the chips and the map marks on, the plan\'s line goes, and it is stored', c.chips === 11 && c.marks === 11 && c.note === null && c.box === true && c.stored === '1', c);
    await t.reload(fx('plan', 'noise11.html'));
    t.check('conflicts: the choice is kept', (await conf()).chips === 11);
    await B.ev(`T.tabTo('Q')`);
    t.check('conflicts: on a PR with no merges the toggle hides', (await conf()).label === null);
    await B.ev(`localStorage.removeItem(T.key()+'cfmarks')`);
    await t.fresh(fx('plan', 'noise10.html'));
    c = await conf();
    t.check('conflicts: 10 files combined by hand (not more than 10) keep their chips, the toggle on, no line', c.chips === 10 && c.box === true && c.note === null, c);
    await t.fresh(fx('big', 'noise26.html'));
    c = await conf();
    t.check('conflicts: 26 of 103 files (above a quarter) hide them', c.chips === 0 && c.note === noteText('en', 26) && c.box === false, c);
    await B.ev(`T.pick(T.rows()[0].id);document.getElementById('g-wsb').click()`); await sleep(150);
    await B.key('m'); await sleep(300);
    await B.ev(`document.querySelector('#g-canvas [data-x=all]').click()`); await sleep(150);
    t.check('conflicts: and the overview has no marks', (await conf()).marks === 0 && await B.ev(`document.querySelectorAll('#g-canvas .nd').length`) > 50);
    await B.ev(`document.getElementById('g-mbtn').click();document.getElementById('g-cfmarks').click()`); await sleep(300);
    await B.key('m'); await sleep(100); await B.key('m'); await sleep(300);
    await B.ev(`document.querySelector('#g-canvas [data-x=all]').click()`); await sleep(150);
    const boxed = await B.ev(`[].filter.call(document.querySelectorAll('#g-canvas .nd'),function(g){var p=g.querySelector('title').textContent.split('\\n')[0],n=T.data().prs[0].nodes.find(function(x){return x.path===p;});return !!n&&!!n.conflict;}).length`);
    t.check('conflicts: turned on, the overview marks every box of those files', boxed > 10 && (await conf()).marks === boxed, { boxed, c: await conf() });
    await t.fresh(fx('big', 'noise25.html'));
    c = await conf();
    t.check('conflicts: 25 of 103 (not above a quarter) keep them', c.chips === 25 && c.box === true && c.note === null, c);
    await t.fresh(fx('big', 'noise26-pl.html'));
    const plStrings = JSON.parse(await B.ev(`document.getElementById('review-config').textContent`)).strings;
    c = await conf();
    t.check('conflicts pl: the plan\'s line and the toggle in Polish', c.note === '26 plików rozwiązanych ręcznie przy merge’ach — znaczniki ukryte, włącz w Widok' && c.label === 'Znaczniki konfliktów'
      && plStrings.cfNoise.few.startsWith('{n} pliki rozwiązane'), c);
    await B.ev(`document.querySelector('.g-tabs-row').scrollIntoView()`); await sleep(100);
    await t.shot('plan-pl-noise');
    t.noErrors('conflicts: no page errors');
  },
};
