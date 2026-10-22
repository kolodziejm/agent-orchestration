'use strict';
// The theme switch (View › Theme: Auto, Light, Dark): applied before the first paint, kept in localStorage, Auto
// following the emulated prefers-color-scheme and a host page's data-theme, a pick overriding both, the keyboard, the
// workspace; every colour from tokens (the map's boxes, layer bars, numbers, markers, and the lane's dots follow a
// switch without a redraw), dark text contrast at least 4.5:1, and the mermaid diagrams redrawn in the new theme (a
// stub mermaid for the local page and a stub host for the Artifact fragment; real mermaid too when cdnjs answers).
const { sleep } = require('./lib');

const KEY = 'review-map:theme';
// Page-side helpers: computed colours (rgb(), rgba(), or color(srgb …)), the background behind an element (its
// ancestors' backgrounds composited down to the body), and WCAG contrast.
const HELPERS = `window.TH={
  col:function(s){var m=/^rgba?\\(([^)]+)\\)$/.exec(s),p;if(m){p=m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1};}
    m=/^color\\(srgb ([^)]+)\\)$/.exec(s);if(m){p=m[1].split(/[\\s\\/]+/).filter(Boolean).map(Number);return {r:p[0]*255,g:p[1]*255,b:p[2]*255,a:p.length>3?p[3]:1};}return null;},
  lum:function(c){function f(v){v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);}return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b);},
  ratio:function(a,b){var x=TH.lum(a),y=TH.lum(b);return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05);},
  over:function(top,bot){var a=top.a;return {r:top.r*a+bot.r*(1-a),g:top.g*a+bot.g*(1-a),b:top.b*a+bot.b*(1-a),a:1};},
  bg:function(el){var ls=[];for(var e=el;e&&e.nodeType===1;e=e.parentElement){var c=TH.col(getComputedStyle(e).backgroundColor);if(c&&c.a>0){ls.push(c);if(c.a>=1)break;}}
    var b=ls.length&&ls[ls.length-1].a>=1?ls.pop():TH.col(getComputedStyle(document.body).backgroundColor);for(var i=ls.length-1;i>=0;i--)b=TH.over(ls[i],b);return b;},
  tok:function(n){var d=document.createElement('div');d.style.color=/^var\\(/.test(n)?n:'var('+n+')';document.body.appendChild(d);var c=getComputedStyle(d).color;d.remove();return c;},
  state:function(){var b=[].map.call(document.querySelectorAll('#g-thm [data-th]'),function(x){return x.dataset.th+':'+x.getAttribute('aria-pressed');}).join(' ');
    return {attr:document.documentElement.getAttribute('data-theme'),stored:localStorage.getItem('${KEY}'),pressed:b,bg:getComputedStyle(document.body).backgroundColor,
      dark:window.__reviewMapTheme.dark(),choice:window.__reviewMapTheme.choice(),scheme:getComputedStyle(document.documentElement).colorScheme};},
  pick:function(c){document.querySelector('#g-thm [data-th='+c+']').click();return TH.state();},
  /* Text that fails 4.5:1 against what is behind it: [selector, text, ratio] for the visible elements of each selector. */
  lowContrast:function(sels){var out=[];sels.forEach(function(s){[].slice.call(document.querySelectorAll(s),0,12).forEach(function(e){
    if(!e.getClientRects().length||!e.textContent.trim())return;var c=TH.col(getComputedStyle(e).color);if(!c)return;var b=TH.bg(e);if(c.a<1)c=TH.over(c,b);var r=TH.ratio(c,b);
    if(r<4.5)out.push([s,e.textContent.trim().slice(0,30),Math.round(r*100)/100]);});});return out;}
};true`;
const LIGHT_BG = 'rgb(246, 247, 249)', DARK_BG = 'rgb(18, 22, 29)';
const TEXT = ['body', 'header .sub', 'nav.toc a', '.pr-card .k', '.pr-card .meta', '.pr-card li', 'section>.lead', 'h4', '.tag', '.callout.warn', '.callout.risk', '.callout.ok',
  '.pill', '.risk-list li', 'th', 'td', 'footer', 'pre.code', 'code', '.files .role', '.g-row .nm', '.g-row .no', '.nmx .d', '.g-tabs button', '.g-tools button', '.g-tools label',
  '.g-detail .p', '.g-detail h4', '.g-nbi', '.k-dep', '.k-use', '.g-kleg', '.g-plsum', '.g-pt td', '.g-pt th', '.g-dp', '.g-pa', '.df>summary', 'table.dt td.cd', 'table.dt td.ln',
  'table.dt tr.hk td', '.nt-b', '.nt-hint', '.g-legend', '.g-morel li', '#g-mpop label', '#g-thm button', '#g-thl', '.hljs-keyword', '.hljs-string', '.hljs-comment', '.hljs-title'];
// A mermaid stand-in: records each initialize() and run() with the theme and the source it was given, draws an <svg>
// that names the theme, and rejects when window.__mmFail is set.
const STUB = `window.mermaid={calls:[],seen:[],initialize:function(c){this.cfg=c;this.calls.push('init:'+c.theme+':'+c.startOnLoad+':'+c.securityLevel);},
  run:function(o){var t=this.cfg.theme,self=this,ns=[].slice.call(o.nodes||[]);self.calls.push('run:'+t+':'+ns.length);
    if(window.__mmFail)return Promise.reject(new Error('stub failure'));
    ns.forEach(function(n){self.seen.push(n.innerHTML);n.setAttribute('data-processed','true');n.innerHTML='<svg class="mm" data-theme="'+t+'"></svg>';});return Promise.resolve();}};`;
// A host page: sets data-theme on <html> as soon as the parser makes it (before the fragment's scripts) when given,
// exposes the stub mermaid, and draws every diagram itself (with its own markup) once the document is parsed.
const host = (attr, withMermaid = true) => `${withMermaid ? STUB : ''}
  ${attr ? `(function(){function set(){document.documentElement.setAttribute('data-theme','${attr}');}
    if(document.documentElement)set();else new MutationObserver(function(r,o){if(document.documentElement){o.disconnect();set();}}).observe(document,{childList:true});})();` : ''}
  document.addEventListener('DOMContentLoaded',function(){[].forEach.call(document.querySelectorAll('pre.mermaid'),function(p){p.setAttribute('data-processed','true');p.innerHTML='<svg class="host"></svg>';});});`;

module.exports = {
  name: 'theme',
  weight: 9, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const PAGE = t.url(t.fixtures, 'theme', 'review.html'), ART = t.url(t.fixtures, 'theme', 'artifact.html');
    t.use(HELPERS);
    const st = () => B.ev('TH.state()');
    let scripts = [];
    const onNew = async (source) => { scripts.push((await B.send('Page.addScriptToEvaluateOnNewDocument', { source })).result.identifier); };
    const clearNew = async () => { for (const identifier of scripts) await B.send('Page.removeScriptToEvaluateOnNewDocument', { identifier }); scripts = []; };
    // The local page loads mermaid from cdnjs: serve the stub instead (also offline), or let the real one through.
    let stubMermaid = true;
    const onFetch = (m) => {
      if (m.method !== 'Fetch.requestPaused') return;
      const id = m.params.requestId;
      if (stubMermaid) B.send('Fetch.fulfillRequest', { requestId: id, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'application/javascript' }], body: Buffer.from(STUB).toString('base64') });
      else B.send('Fetch.continueRequest', { requestId: id });
    };
    B.on(onFetch);
    await B.send('Fetch.enable', { patterns: [{ urlPattern: '*mermaid.min.js*' }] });

    /* ---------- The switch: Auto by default, a pick applied and kept, Auto follows the system ---------- */
    await t.fresh(PAGE, { dark: false });
    let s = await st();
    const grp = await B.ev(`(function(){var g=document.getElementById('g-thm');return {role:g.getAttribute('role'),name:document.getElementById(g.getAttribute('aria-labelledby')).textContent,
      labels:[].map.call(g.querySelectorAll('button'),function(b){return b.textContent;}),inMenu:!!g.closest('#g-mpop'),title:g.querySelector('[data-th=auto]').title};})()`);
    t.check('switch: a labelled group of three buttons in the View menu', grp.role === 'group' && grp.name === 'Theme' && grp.labels.join() === 'Auto,Light,Dark' && grp.inMenu && /system/.test(grp.title), grp);
    t.check('switch: Auto is pressed, no data-theme, light system: the page is light', s.pressed === 'auto:true light:false dark:false' && s.attr === null && s.stored === null && s.bg === LIGHT_BG && !s.dark && s.scheme === 'light', s);
    await B.ev(`document.getElementById('g-mbtn').click()`);
    s = await B.ev(`TH.pick('dark')`);
    t.check('switch: Dark sets data-theme="dark", stores the pick, presses Dark, and the page turns dark', s.attr === 'dark' && s.stored === 'dark' && s.pressed === 'auto:false light:false dark:true' && s.bg === DARK_BG && s.dark && s.scheme === 'dark', s);
    t.check('switch: the menu stays open and the pick is announced', await B.ev(`!document.getElementById('g-mpop').hidden`)
      && await B.ev(`new Promise(function(r){setTimeout(function(){r(document.getElementById('nt-live').textContent);},80);})`) === 'Theme: Dark');
    await t.shot('dark-1440', '#graph', 1400);
    await t.noErrors('switch: no page errors');

    // Before the first paint: the first animation frame that has content already sees the stored pick.
    await onNew(`(function f(){if(document.body&&document.body.firstElementChild){window.__first=document.documentElement.getAttribute('data-theme')+'|'+getComputedStyle(document.body).backgroundColor;}else requestAnimationFrame(f);})();`);
    await t.reload(PAGE);
    const first = await B.ev('window.__first');
    s = await st();
    t.check('reload: the pick is applied before the first frame (no flash) and the switch shows it', first === `dark|${DARK_BG}` && s.attr === 'dark' && s.pressed === 'auto:false light:false dark:true', { first, s });
    await clearNew();

    await t.fresh(PAGE, { dark: true });
    s = await st();
    t.check('Auto, dark system: no data-theme and the page is dark', s.attr === null && s.bg === DARK_BG && s.pressed.startsWith('auto:true'), s);
    s = await B.ev(`TH.pick('light')`);
    t.check('Light on a dark system: data-theme="light", stored, the page light', s.attr === 'light' && s.stored === 'light' && s.bg === LIGHT_BG && !s.dark && s.scheme === 'light', s);
    await t.reload(PAGE);
    t.check('Light kept across a reload on a dark system', (await st()).bg === LIGHT_BG);
    s = await B.ev(`TH.pick('auto')`);
    t.check('Auto drops the stored pick and the attribute; the page follows the dark system', s.attr === null && s.stored === null && s.bg === DARK_BG && s.pressed.startsWith('auto:true'), s);
    await B.viewport(1440, 900, false); await sleep(100);
    s = await st();
    t.check('Auto follows the system turning light', s.bg === LIGHT_BG && !s.dark && s.pressed.startsWith('auto:true'), s);
    await B.viewport(1440, 900, true); await sleep(100);
    t.check('… and dark again', (await st()).bg === DARK_BG);

    /* ---------- Keyboard and the workspace ---------- */
    await t.fresh(PAGE, { dark: false });
    await B.ev(`document.getElementById('g-mbtn').focus()`); await B.key('Enter');
    await B.ev(`document.querySelector('#g-thm [data-th=dark]').focus()`); await B.key('Enter');
    s = await st();
    t.check('keyboard: Enter on Dark picks it', s.attr === 'dark' && s.stored === 'dark', s);
    await B.ev(`document.querySelector('#g-thm [data-th=light]').focus()`); await B.key(' ');
    s = await st();
    t.check('keyboard: Space on Light picks it', s.attr === 'light' && s.stored === 'light', s);
    await B.key('Escape');
    t.check('keyboard: Esc closes the menu and gives the focus back to View', await B.ev(`document.getElementById('g-mpop').hidden&&document.activeElement.id==='g-mbtn'`));
    await B.ev(`document.getElementById('g-wsb').click()`); await sleep(250);
    await B.ev(`document.getElementById('g-mbtn').click()`);
    const ws = await B.ev(`(function(){var b=document.querySelector('#g-thm [data-th=dark]'),r=b.getBoundingClientRect();return {ws:document.getElementById('graph').classList.contains('ws'),shown:!!b.getClientRects().length&&r.bottom<=innerHeight&&r.right<=innerWidth};})()`);
    s = await B.ev(`TH.pick('dark')`);
    t.check('workspace: the theme buttons show in its View menu and work', ws.ws && ws.shown && s.attr === 'dark' && s.bg === DARK_BG, { ws, s });
    await t.shot('ws-dark-1440');
    await B.key('Escape'); await B.key('Escape');
    await t.noErrors('keyboard and workspace: no page errors');

    /* ---------- A host page's data-theme: respected without a pick, overridden by one ---------- */
    await onNew(host('dark', false));
    await t.fresh(PAGE, { dark: false });
    s = await st();
    t.check('host dark, no pick, light system: the page stays dark and the switch shows Auto', s.attr === 'dark' && s.bg === DARK_BG && s.pressed.startsWith('auto:true') && s.stored === null, s);
    await B.ev(`document.documentElement.setAttribute('data-theme','light')`); await sleep(50);
    s = await st();
    t.check('host turns light later: Auto follows it', s.attr === 'light' && s.bg === LIGHT_BG && s.pressed.startsWith('auto:true'), s);
    await B.ev(`document.documentElement.setAttribute('data-theme','dark')`); await sleep(50);
    s = await B.ev(`TH.pick('light')`);
    t.check('a pick overrides the host', s.attr === 'light' && s.bg === LIGHT_BG && s.stored === 'light', s);
    await B.ev(`document.documentElement.setAttribute('data-theme','dark')`); await sleep(50);
    s = await st();
    t.check('the host changing data-theme again does not undo the pick', s.attr === 'light' && s.bg === LIGHT_BG, s);
    s = await B.ev(`TH.pick('auto')`);
    t.check('Auto gives the attribute back to the host (its last value)', s.attr === 'dark' && s.bg === DARK_BG && s.stored === null, s);
    await B.ev(`TH.pick('light')`);
    await t.reload(PAGE);
    s = await st();
    t.check('a stored pick wins over the host at load', s.attr === 'light' && s.bg === LIGHT_BG && s.pressed === 'auto:false light:true dark:false', s);
    await clearNew();
    await t.noErrors('host: no page errors');

    /* ---------- Colours follow the theme without a redraw: map, lane, legend; dark text contrast ---------- */
    await t.fresh(PAGE, { dark: false });
    await B.ev(`T.tabTo('B');T.pick(T.id('web/app.tsx'));document.querySelector('[data-v=map]').click()`); await sleep(200);
    const MAPC = `(function(){var g=document.querySelector('#g-canvas .nd:not(.ext):not(.on)'),x=document.querySelector('#g-canvas .nd.ext'),cs=function(e,p){return getComputedStyle(e)[p];};
      var lc=g.style.getPropertyValue('--lc').match(/--l-[a-z0-9]+/)[0],dot=document.querySelector('#g-lane circle.dot');
      return {same:g===window.__nd,box:cs(g.querySelector('rect.box'),'fill'),line:cs(g.querySelector('rect.box'),'stroke'),lb:cs(g.querySelector('rect.lb'),'fill'),num:cs(g.querySelector('.num'),'fill'),
        xnum:cs(x.querySelector('.num'),'fill'),xbox:cs(x.querySelector('rect.box'),'stroke'),mk:cs(document.querySelector('#g-canvas marker#ar path'),'fill'),
        dot:cs(dot,'fill'),dotTok:TH.tok(dot.style.getPropertyValue('--lc')),
        surface:TH.tok('--surface'),lineT:TH.tok('--line'),layer:TH.tok(lc),muted:TH.tok('--muted'),pal:TH.tok('--pal-1'),legend:getComputedStyle(document.querySelector('#g-legend i')).backgroundColor,
        legendTok:TH.tok(document.querySelector('#g-legend i').style.background.match(/--l-[a-z0-9]+/)[0])};})()`;
    await B.ev(`window.__nd=document.querySelector('#g-canvas .nd:not(.ext):not(.on)')`);
    const ml = await B.ev(MAPC);
    await B.ev(`document.getElementById('g-mbtn').click()`); await B.ev(`TH.pick('dark')`); await sleep(50);
    const md = await B.ev(MAPC);
    const follow = (m) => m.box === m.surface && m.line === m.lineT && m.lb === m.layer && m.num === m.layer && m.xnum === m.pal && m.xbox === m.pal && m.mk === m.muted
      && m.dot === m.dotTok && m.legend === m.legendTok;
    t.check('map: boxes, borders, layer bars, step numbers, earlier-PR colours, arrowheads, lane dots, and the legend come from tokens (light)', follow(ml), ml);
    t.check('map: after Dark the same drawing (no redraw) shows the dark tokens', md.same && follow(md) && md.box !== ml.box && md.lb !== ml.lb && md.mk !== ml.mk, md);
    const nums = await B.ev(`[].map.call(document.querySelectorAll('#g-canvas .nd .num'),function(n){return Math.round(TH.ratio(TH.col(getComputedStyle(n).fill),TH.col(TH.tok('--surface')))*100)/100;})`);
    t.check('map (dark): every step number reads at 4.5:1 or more on its box', nums.length >= 3 && nums.every((r) => r >= 4.5), nums);
    const layers = await B.ev(`['contract','domain','logic','infra','rest','wiring','ui','data','test','config','docs','i18n','other'].map(function(l){return [l,Math.round(TH.ratio(TH.col(TH.tok('--l-'+l)),TH.col(TH.tok('--surface')))*100)/100];})`);
    t.check('every layer colour reads at 4.5:1 or more on the dark surface', layers.every((x) => x[1] >= 4.5), layers);
    await t.shot('map-dark-1440', '#graph', 1400);
    await B.ev(`document.querySelector('[data-v=list]').click();document.getElementById('g-plan').open=true;document.querySelector('#dv-files td.ln[data-s=new][data-l="1"]').click();if(document.getElementById('g-mpop').hidden)document.getElementById('g-mbtn').click()`); await sleep(400);
    const low = await B.ev(`TH.lowContrast(${JSON.stringify(TEXT)})`);
    t.check('dark: the page\'s text reads at 4.5:1 or more against what is behind it', low.length === 0, low);
    await t.shot('list-dark-1440', 'main', 2400);
    await B.ev(`TH.pick('light')`);
    await t.shot('list-light-1440', 'main', 2400);
    await t.noErrors('colours: no page errors');

    /* ---------- Mermaid, local page: drawn in the page's theme, again after each switch, from the kept source ---------- */
    await t.fresh(PAGE, { dark: false });
    const src = await B.ev(`(function(){var d=document.createElement('div');d.innerHTML=${JSON.stringify('<pre class="mermaid">\nflowchart LR\n  S["service<br/>a &lt; b"] --> W["web"]\n</pre>')};return d.firstChild.innerHTML;})()`);
    const mm = () => B.ev(`({calls:window.mermaid.calls.slice(),seen:window.mermaid.seen.slice(),svgs:[].map.call(document.querySelectorAll('pre.mermaid'),function(p){var s=p.querySelector('svg');return s?s.getAttribute('class')+':'+s.getAttribute('data-theme'):p.textContent.trim().slice(0,20);})})`);
    let m = await mm();
    t.check('mermaid local: drawn once, light, strict, startOnLoad off, every diagram', m.calls.join() === 'init:default:false:strict,run:default:2' && m.svgs.join() === 'mm:default,mm:default', m);
    t.check('mermaid local: the source handed over keeps the <br/> and the escaped <', m.seen[0] === src && /sequenceDiagram/.test(m.seen[1]), { seen: m.seen[0], src });
    await B.ev(`TH.pick('dark')`); await sleep(100);
    m = await mm();
    t.check('mermaid local: Dark redraws every diagram in the dark theme from the original source', m.calls.slice(2).join() === 'init:dark:false:strict,run:dark:2' && m.svgs.join() === 'mm:dark,mm:dark' && m.seen[2] === src, m);
    await B.ev(`TH.pick('dark')`); await sleep(50);
    t.check('mermaid local: the same pick again draws nothing', (await mm()).calls.length === 4);
    await B.ev(`TH.pick('auto')`); await sleep(100);
    m = await mm();
    t.check('mermaid local: Auto on a light system redraws light', m.calls.slice(4).join() === 'init:default:false:strict,run:default:2' && m.svgs.join() === 'mm:default,mm:default', m);
    await B.viewport(1440, 900, true); await sleep(150);
    m = await mm();
    t.check('mermaid local: Auto follows the system turning dark', m.calls.slice(6).join() === 'init:dark:false:strict,run:dark:2' && m.svgs.join() === 'mm:dark,mm:dark', m);
    await B.viewport(1440, 900, false); await sleep(100);
    await t.noErrors('mermaid local: no page errors');

    /* ---------- Mermaid, Artifact fragment: the host draws; a theme change redraws through the host's mermaid ---------- */
    await onNew(host(null));
    await t.fresh(ART, { dark: false });
    m = await mm();
    t.check('mermaid artifact: the host draws, the page does not (no mermaid script, no calls)', m.calls.length === 0 && m.svgs.join() === 'host:null,host:null'
      && !(await B.ev(`!!document.querySelector('script[src*="mermaid"]')`)), m);
    await B.ev(`TH.pick('dark')`); await sleep(100);
    m = await mm();
    t.check('mermaid artifact: Dark redraws through window.mermaid from the source read before the host drew', m.calls.join() === 'init:dark:false:strict,run:dark:2' && m.svgs.join() === 'mm:dark,mm:dark' && m.seen[0] === src, m);
    await B.ev(`window.__mmFail=true;TH.pick('light')`); await sleep(100);
    m = await mm();
    t.check('mermaid artifact: a failed redraw puts the diagrams back as they were', m.svgs.join() === 'mm:dark,mm:dark' && await B.ev(`[].every.call(document.querySelectorAll('pre.mermaid'),function(p){return p.getAttribute('data-processed')==='true';})`), m);
    await clearNew();
    await t.noErrors('mermaid artifact: no page errors');

    await onNew(host('light'));
    await t.fresh(ART, { dark: false, seed: `localStorage.setItem('${KEY}','dark')` });
    await sleep(150);
    m = await mm();
    t.check('mermaid artifact: a pick that disagrees with the host redraws once the host has drawn', m.calls.join() === 'init:dark:false:strict,run:dark:2' && m.svgs.join() === 'mm:dark,mm:dark' && (await st()).attr === 'dark', m);
    await clearNew();
    await onNew(host('dark'));
    await t.fresh(ART, { dark: false, seed: `localStorage.setItem('${KEY}','dark')` });
    await sleep(150);
    m = await mm();
    t.check('mermaid artifact: a pick that agrees with the host leaves its drawing alone', m.calls.length === 0 && m.svgs.join() === 'host:null,host:null', m);
    await clearNew();

    await onNew(host('light', false));
    await t.fresh(ART, { dark: false });
    await B.ev(`TH.pick('dark')`); await sleep(100);
    const untouched = await B.ev(`[].map.call(document.querySelectorAll('pre.mermaid'),function(p){return p.innerHTML;}).join('|')`);
    t.check('mermaid artifact: without window.mermaid nothing is touched', untouched === '<svg class="host"></svg>|<svg class="host"></svg>', untouched);
    await clearNew();
    await t.noErrors('mermaid artifact (host): no page errors');

    /* ---------- Real mermaid from cdnjs (when it answers): light and dark drawings differ ---------- */
    if (!t.cdn) t.skip('real mermaid redraws in the other theme', 'cdnjs is unreachable');
    else {
      stubMermaid = false;
      await t.fresh(PAGE, { dark: false });
      const real = async () => { for (let i = 0; i < 50; i++) { const r = await B.ev(`(function(){var s=[].map.call(document.querySelectorAll('pre.mermaid svg'),function(v){var st=v.querySelector('style');return st?st.textContent:'';});return s.length===2&&s.every(Boolean)?s.join(''):null;})()`); if (r) return r; await sleep(100); } return null; };
      const lightCss = await real();
      await B.ev(`TH.pick('dark')`); await sleep(300);
      const darkCss = await real();
      t.check('real mermaid: both diagrams drawn light, then redrawn dark with other colours', !!lightCss && !!darkCss && /ececff/i.test(lightCss) && !/ececff/i.test(darkCss), { light: (lightCss || '').slice(0, 200), dark: (darkCss || '').slice(0, 200) });
      await t.shot('mermaid-dark-1440', '#arch', 600);
      await t.noErrors('real mermaid: no page errors');
      stubMermaid = true;
    }
    await B.send('Fetch.disable');
    B.off(onFetch);
  },
};
