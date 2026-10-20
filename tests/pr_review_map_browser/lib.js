'use strict';
// Shared harness for the pr-review-map browser checks: finding and driving headless Chrome over the DevTools protocol
// (Node's built-in WebSocket, no npm package), loading a page with fresh or seeded localStorage, viewport and theme
// emulation, clipboard capture, page-side helpers, screenshots, and check bookkeeping.
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isExecutable = (p) => { try { return fs.statSync(p).isFile() && (fs.accessSync(p, fs.constants.X_OK), true); } catch (e) { return false; } };

// Chrome or Chromium: $CHROME when set (an empty or missing path means "none"), else the first of the usual names on
// PATH, else the usual install locations of the platform.
function findChrome() {
  if (process.env.CHROME !== undefined) {
    const p = process.env.CHROME;
    return p && isExecutable(p) ? { path: p } : { why: p ? `CHROME=${p} is not an executable file` : 'CHROME is empty' };
  }
  const names = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome'];
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    for (const n of names) { const p = path.join(dir, n); if (dir && isExecutable(p)) return { path: p }; }
  }
  const home = os.homedir();
  const known = {
    darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium',
      path.join(home, 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome'), path.join(home, 'Applications/Chromium.app/Contents/MacOS/Chromium')],
    linux: ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium'],
    win32: [path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Google/Chrome/Application/chrome.exe'),
      path.join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Google/Chrome/Application/chrome.exe')],
  }[process.platform] || [];
  const found = known.find(isExecutable);
  return found ? { path: found } : { why: 'no Chrome or Chromium found (set CHROME to its binary)' };
}

// The viewer loads highlight.js (and mermaid, and languages outside the bundle) from here.
const CDN = 'https://cdnjs.cloudflare.com/';
const HLJS = CDN + 'ajax/libs/highlight.js/11.9.0/highlight.min.js';

// Whether cdnjs answers within a few seconds (Node's fetch; a proxy only Chrome knows about reads as unreachable).
async function cdnReachable() {
  try { return (await fetch(HLJS, { method: 'HEAD', signal: AbortSignal.timeout(5000) })).ok; } catch (e) { return false; }
}

// Every Chrome still running is killed when this process ends, however it ends.
const live = new Set();
process.on('exit', () => { for (const proc of live) proc.kill('SIGKILL'); });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => process.exit(130));

const KEYS = { ArrowDown: 40, ArrowUp: 38, ArrowLeft: 37, ArrowRight: 39, Enter: 13, Home: 36, End: 35, Tab: 9, Escape: 27, ' ': 32 };

// One headless Chrome with one page. B.errors collects uncaught exceptions, console.error calls, and error log entries.
// offline: no host name resolves, and cdnjs load failures are not page errors (the viewer works without highlighting).
async function launch(chrome, workDir, { offline = false } = {}) {
  const profile = fs.mkdtempSync(path.join(workDir, 'chrome-'));
  const args = ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--hide-scrollbars',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--window-size=1440,900', 'about:blank'];
  if (process.platform === 'linux' && process.getuid && process.getuid() === 0) args.unshift('--no-sandbox');
  if (offline) args.unshift('--host-resolver-rules=MAP * ~NOTFOUND'); // no host name resolves, so cdnjs fails at once
  const proc = spawn(chrome, args, { stdio: 'ignore' });
  live.add(proc);
  proc.once('exit', () => live.delete(proc));
  let port = null;
  for (let i = 0; i < 150 && !port; i++) {
    try { port = +fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0] || null; } catch (e) { /* not yet */ }
    if (!port) await sleep(100);
  }
  if (!port) { proc.kill('SIGKILL'); throw new Error('Chrome did not open a DevTools port'); }
  let page = null;
  for (let i = 0; i < 50 && !page; i++) {
    try { page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page'); } catch (e) { /* not yet */ }
    if (!page) await sleep(100);
  }
  if (!page) { proc.kill('SIGKILL'); throw new Error('Chrome opened no page target'); }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.addEventListener('open', resolve); ws.addEventListener('error', reject); });
  let id = 0;
  const pending = {}, errors = [], listeners = [];
  ws.addEventListener('message', (m) => {
    const msg = JSON.parse(m.data);
    if (msg.method) listeners.forEach((f) => f(msg));
    if (msg.id && pending[msg.id]) { pending[msg.id](msg); delete pending[msg.id]; }
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') errors.push('console.error ' + JSON.stringify(msg.params.args.map((a) => a.value || a.description)));
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error' && !/favicon/.test(msg.params.entry.url || '')
      && !(offline && (msg.params.entry.url || '').startsWith(CDN))) errors.push('log ' + msg.params.entry.text);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const i = ++id;
    const timer = setTimeout(() => { delete pending[i]; reject(new Error(`${method} timed out`)); }, 60000);
    pending[i] = (msg) => { clearTimeout(timer); resolve(msg); };
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  await send('Runtime.enable'); await send('Page.enable'); await send('Log.enable');
  await send('Browser.grantPermissions', { permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'] });
  const B = {
    errors, send,
    on(f) { listeners.push(f); },
    off(f) { const i = listeners.indexOf(f); if (i >= 0) listeners.splice(i, 1); },
    async ev(expression) {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, userGesture: true });
      if (r.error) throw new Error(expression.slice(0, 120) + ' -> ' + r.error.message);
      if (r.result.exceptionDetails) throw new Error(expression.slice(0, 120) + ' -> ' + JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
      return r.result.result.value;
    },
    // Window size and the prefers-color-scheme the page sees (the viewer follows it unless data-theme is set); without `dark`
    // the colour scheme is left alone (setting it again, even to the same value, makes the viewer draw its list afresh).
    async viewport(width, height, dark) {
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      if (dark !== undefined) await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }] });
    },
    // Navigate and wait for the load event (or only for the DOM with interactive, when a held request delays load).
    async open(url, { interactive = false } = {}) {
      await send('Page.navigate', { url });
      const ready = interactive ? ['interactive', 'complete'] : ['complete'];
      for (let i = 0; i < 100; i++) { await sleep(100); try { if (ready.includes(await B.ev('document.readyState'))) break; } catch (e) { /* navigating */ } }
      await sleep(300);
    },
    async key(key, modifiers = 0) {
      const text = key === 'Enter' ? '\r' : key === ' ' ? ' ' : undefined;
      const code = key === ' ' ? 'Space' : key;
      await send('Input.dispatchKeyEvent', { type: text ? 'keyDown' : 'rawKeyDown', key, code, windowsVirtualKeyCode: KEYS[key], modifiers, text });
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode: KEYS[key], modifiers });
      await sleep(60);
    },
    async screenshot(file, selector, maxH = 2400) {
      let clip;
      if (selector) {
        const r = await B.ev(`(function(){var r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,w:r.width,h:r.height};})()`);
        clip = { x: Math.max(0, r.x - 4), y: Math.max(0, r.y - 4), width: r.w + 8, height: Math.min(r.h + 8, maxH), scale: 1 };
      }
      const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: !!selector, ...(clip ? { clip } : {}) });
      fs.writeFileSync(file, Buffer.from(r.result.data, 'base64'));
    },
    async close() {
      try { ws.close(); } catch (e) { /* closed */ }
      const exited = proc.exitCode !== null || proc.signalCode !== null ? Promise.resolve() : new Promise((r) => proc.once('exit', r));
      proc.kill('SIGKILL');
      await Promise.race([exited, sleep(5000)]);
      try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); } catch (e) { /* left for the run's cleanup */ }
    },
  };
  return B;
}

// Page-side helpers every suite gets as window.T after each load. Rows and sections read the list as the reader sees it.
const PAGE_HELPERS = `window.T={
  rows:function(){return [].map.call(document.querySelectorAll('#g-order li.g-row'),function(li){var s=li.closest('.g-sec'),ix=li.querySelector('.ix'),cb=li.querySelector('.g-cb');
    return {id:li.dataset.id,no:+li.querySelector('.no').textContent,t:li.classList.contains('t'),sel:li.classList.contains('sel'),dep:li.classList.contains('dep'),
      use:li.classList.contains('use'),done:li.classList.contains('done'),was:li.classList.contains('was'),badge:cb?cb.textContent:'',ix:ix?ix.textContent:'',sec:s?s.dataset.sec:'',vis:!!li.offsetParent};});},
  secs:function(){return [].map.call(document.querySelectorAll('#g-order .g-sec'),function(s){var h=s.querySelector('.g-sh');return {key:s.dataset.sec,hub:s.classList.contains('hub'),shut:s.classList.contains('shut'),exp:h.getAttribute('aria-expanded'),label:h.getAttribute('aria-label'),sc:h.querySelector('.sc').textContent,chips:h.querySelectorAll('.g-nk').length,cls:h.className,ids:[].map.call(s.querySelectorAll('li.g-row'),function(li){return li.dataset.id;})};});},
  sel:function(){var l=document.querySelector('#g-order li.sel');return l?l.dataset.id:null;},
  tab:function(){var b=document.querySelector('#g-tabs [aria-selected=true]');return b?b.dataset.k:null;},
  tabTo:function(k){document.querySelector('#g-tabs [data-k="'+k+'"]').click();},
  row:function(id){return document.querySelector('#g-order li.g-row[data-id="'+id+'"]');},
  pick:function(id){T.row(id).querySelector('.nm').click();},
  head:function(key){return document.querySelector('#g-order .g-sec[data-sec="'+key+'"]>.g-sh');},
  arcs:function(){return [].map.call(document.querySelectorAll('#g-lane path.arc'),function(p){return {f:p.dataset.f,t:p.dataset.t,c:p.getAttribute('class'),d:p.getAttribute('d')};});},
  data:function(){return JSON.parse(document.getElementById('graph-data').textContent);},
  id:function(p,pr){var d=T.data();for(var i=0;i<d.prs.length;i++){if(pr&&d.prs[i].key!==pr)continue;for(var j=0;j<d.prs[i].nodes.length;j++)if(d.prs[i].nodes[j].path===p)return d.prs[i].nodes[j].id;}return null;},
  hubs:function(){var o={};T.data().prs.forEach(function(p){p.nodes.forEach(function(n){if(n.hub)o[n.id]=1;});});return o;},
  hscroll:function(){return document.documentElement.scrollWidth-document.documentElement.clientWidth;},
  key:function(){var c=JSON.parse(document.getElementById('review-config').textContent);return 'review-map:'+(c.storageKey||c.title)+':';},
  stored:function(k){return JSON.parse(localStorage.getItem(T.key()+k)||'null');},
  df:function(p){return [].find.call(document.querySelectorAll('#dv-files details.df'),function(d){return d.querySelector('.pth').textContent===p;});},
  cell:function(p,side,l){var d=T.df(p);return d&&d.querySelector('td.ln[data-s="'+side+'"][data-l="'+l+'"]');},
  /* Fill a note editor inside box (kind optional) and press its primary button. */
  save:function(box,kind,text){var e=box.querySelector('.nt-ed')||box;if(kind)e.querySelector('input[value='+kind+']').click();var t=e.querySelector('textarea');t.value=text;t.dispatchEvent(new Event('input',{bubbles:true}));[].find.call(e.querySelectorAll('button'),function(b){return b.classList.contains('pri');}).click();},
  /* Click "Copy" with navigator.clipboard.writeText captured; resolves with the copied text (or the manual-copy box's). */
  copy:function(){window.__copied=null;navigator.clipboard.writeText=function(t){window.__copied=t;return Promise.resolve();};document.getElementById('nt-copy').click();
    return new Promise(function(r){var n=0;(function w(){if(window.__copied!==null||++n>20){var m=document.getElementById('nt-manual-text');r(window.__copied!==null?window.__copied:m?m.value:null);}else setTimeout(w,50);})();});}
};true`;

// The viewer's own computeOrder(), cut out of an assembled page and run on its embedded graph:
// {order: {top|bottom: {prKey: {on: {id: step}, subj: {testId: subjectId}}}}, data}.
function viewerOrder(file) {
  const html = fs.readFileSync(file, 'utf8');
  const late = html.match(/var LATE=(\{[^}]*\});/)[1];
  const start = html.indexOf('function computeOrder(p){');
  if (start < 0) throw new Error('computeOrder not found in ' + file);
  let depth = 0, end = -1;
  for (let i = html.indexOf('{', start); i < html.length; i++) { if (html[i] === '{') depth++; else if (html[i] === '}' && --depth === 0) { end = i + 1; break; } }
  const data = JSON.parse(html.match(/<script type="application\/json" id="graph-data">([\s\S]*?)<\/script>/)[1]);
  const run = new Function('data', 'var ON={},SUBJ={},LINKED={},HUB={},omode,all={},LATE=' + late + ';\n' + html.slice(start, end) + `
    data.prs.forEach(function(p){p.nodes.forEach(function(n){all[n.id]=Object.assign({pr:p.key},n);});});
    var out={};['bottom','top'].forEach(function(m){omode=m;out[m]={};data.prs.forEach(function(p){computeOrder(p);out[m][p.key]={on:ON,subj:SUBJ};});});return out;`);
  return { order: run(data), data };
}

// The context one suite runs with: the browser, fixture paths, checks, and page loading.
class Suite {
  constructor(name, opts) {
    Object.assign(this, opts); // fixtures, work, python, root, shots, verbose, micromark; the runner sets B
    this.name = name; this.passed = 0; this.failures = []; this.skips = []; this.helpers = [];
  }
  check(name, cond, extra) {
    if (cond) { this.passed++; if (this.verbose) console.log(`  PASS ${this.name}: ${name}`); return true; }
    const detail = extra === undefined ? '' : ' :: ' + JSON.stringify(extra).slice(0, 900);
    this.failures.push(name + detail);
    console.log(`  FAIL ${this.name}: ${name}${detail}`);
    return false;
  }
  skip(name, why) { this.skips.push(`${name} (${why})`); if (this.verbose) console.log(`  SKIP ${this.name}: ${name} (${why})`); }
  // Report and clear the page errors collected since the last call.
  noErrors(name) { return this.check(name, this.B.errors.length === 0, this.B.errors.splice(0)); }
  url(...parts) { return 'file://' + path.join(...parts); }
  // Register extra page-side helpers (a script string ending in `true`) injected after every load, beside window.T.
  use(script) { this.helpers.push(script); }
  async inject() { await this.B.ev(PAGE_HELPERS); for (const h of this.helpers) await this.B.ev(h); }
  // Load url at a size and colour scheme with empty localStorage (then `seed`, a script run before the real load).
  async fresh(url, { width = 1440, height = 900, dark = false, seed } = {}) {
    await this.B.viewport(width, height, dark);
    await this.B.open(url);
    await this.B.ev('localStorage.clear()');
    if (seed) await this.B.ev(seed);
    await this.B.open(url);
    await this.inject();
  }
  // Load url keeping localStorage (a reload, or another page of the same report).
  async reload(url) { await this.B.open(url); await this.inject(); }
  // Switch the page's own theme attribute (light when dark is false).
  async theme(dark) { await this.B.ev(dark ? `document.documentElement.setAttribute('data-theme','dark')` : `document.documentElement.removeAttribute('data-theme')`); }
  async copy() { return this.B.ev('T.copy()'); }
  // A screenshot for eyeballing, written only with --shots DIR.
  async shot(name, selector, maxH) { if (this.shots) await this.B.screenshot(path.join(this.shots, `${this.name}-${name}.png`), selector, maxH); }
  // Run a fixture or skill script with the configured Python; returns stdout.
  // (Asynchronous, so suites running side by side keep going.)
  py(args) {
    return new Promise((resolve, reject) => execFile(this.python, args, { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' }, maxBuffer: 1 << 26 },
      (err, stdout, stderr) => (err ? reject(new Error(`${path.basename(args[0])} ${args.slice(1).join(' ')} failed:\n${stdout}${stderr}`)) : resolve(stdout))));
  }
  async fixture(cmd, ...args) { return JSON.parse(await this.py([path.join(__dirname, 'fixtures.py'), cmd, ...args])); }
  skill(script, ...args) { return this.py([path.join(this.root, 'skills', 'pr-review-map', 'scripts', script), ...args]); }
}

module.exports = { findChrome, cdnReachable, launch, sleep, Suite, viewerOrder };
