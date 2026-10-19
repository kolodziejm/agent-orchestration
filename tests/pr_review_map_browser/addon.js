'use strict';
// Robustness add-ons: file names that are Object.prototype properties do not break the page, a Vue script tag longer
// than git's 80-byte funcname keeps its lang, and a language that arrives from cdnjs redraws the open diff in place
// without resetting which files are open, their scroll, the line selection, or focus. Needs network access to cdnjs.
const { sleep } = require('./lib');

module.exports = {
  name: 'addon',
  weight: 7, // seconds on a laptop, to start the longest suites first
  needs: ['chrome', 'cdn'],
  async run(t) {
    const B = t.B;
    const u = (name) => t.url(t.fixtures, 'addon', name, 'review.html');
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      /* 1. Files named after Object.prototype properties. */
      await t.fresh(u('odd'), { dark });
      const rows = await B.ev(`T.rows().map(function(r){return r.id;})`);
      t.check(`${th} odd names: the page renders every file (6 rows)`, rows.length === 6, rows);
      const shown = [];
      for (const id of rows) {
        await B.ev(`T.pick('${id}')`);
        shown.push(await B.ev(`({p:(document.querySelector('#dv-files .pth')||{}).textContent,lines:document.querySelectorAll('#dv-files td.cd').length,hl:document.querySelectorAll('#dv-files .hljs-keyword,#dv-files .hljs-built_in').length})`));
      }
      t.check(`${th} odd names: each diff draws (plain text), ok.ts is highlighted`, shown.every((s) => s.lines > 0) && shown.find((s) => s.p === 'src/ok.ts').hl > 0 && shown.filter((s) => s.p !== 'src/ok.ts').every((s) => s.hl === 0), shown);
      const ctor = rows.find((id, i) => shown[i].p === 'src/x.constructor');
      await B.ev(`T.pick('${ctor}');document.querySelector('#dv-files td.ln[data-s=new][data-l="1"]').click();document.querySelector('#dv-files [data-nt=add]').click()`);
      await B.ev(`T.save(document.querySelector('#dv-files .nt-ed'),null,'odd')`);
      const md = await t.copy();
      t.check(`${th} odd names: a copied note's fence has no "function Object" hint`, /\n```\na = 1\n```\n/.test(md) && !/function/.test(md), md);
      t.noErrors(`${th} odd names: no page errors`);

      /* 2. Long <script setup generic="…" lang="ts">: the hunk in the middle of the script is TypeScript. */
      await t.reload(u('vue'));
      await B.ev(`document.querySelector('#g-order li.g-row .nm').click()`);
      await sleep(300);
      const r = await B.ev(`(function(){var td=[].find.call(document.querySelectorAll('#dv-files td.cd'),function(c){return /n8: number = 80/.test(c.textContent);});return {head:document.querySelector('#dv-files tr.hk td').textContent,ts:!!(td&&[].some.call(td.querySelectorAll('.hljs-built_in'),function(s){return s.textContent==='number';}))};})()`);
      t.check(`${th} long Vue tag: the hunk header names <script lang="ts"> and the hunk is highlighted as TypeScript`, r.ts && /<script lang="ts">$/.test(r.head), r);
      await t.shot(`long-vue-tag-1440-${th}`, '#dv', 700);
      t.noErrors(`${th} long Vue tag: no page errors`);

      /* 3. Hold the dockerfile language at the network, change the view, then let it arrive. */
      let paused = null;
      const onPause = (m) => { if (m.method === 'Fetch.requestPaused') paused = m.params.requestId; };
      B.on(onPause);
      await B.send('Fetch.enable', { patterns: [{ urlPattern: '*languages/dockerfile.min.js*' }] });
      await B.open(u('redraw'), { interactive: true }); // the held language keeps the load event from firing
      await t.inject();
      for (let i = 0; i < 50 && !paused; i++) await sleep(100);
      await B.ev(`document.querySelector('#g-order li.g-row .nm').click()`);
      await sleep(200);
      const prep = await B.ev(`(function(){
        var a=T.df('deploy/a.ts'),k=T.df('deploy/Dockerfile'),b=T.df('deploy/b.ts');a.open=false;
        var body=k.querySelector('.df-body');body.scrollTop=300;
        k.querySelector('td.ln[data-s=new][data-l="60"]').click();
        return {a:a.open,k:k.open,b:b.open,top:body.scrollTop,hl:k.querySelectorAll('.hljs-keyword').length,focus:document.activeElement.dataset.l};})()`);
      const before = await B.ev(`document.querySelectorAll('#dv-files td.ls').length`);
      if (paused) await B.send('Fetch.continueRequest', { requestId: paused });
      await B.send('Fetch.disable');
      B.off(onPause);
      await sleep(800);
      const after = await B.ev(`(function(){
        var a=T.df('deploy/a.ts'),k=T.df('deploy/Dockerfile'),b=T.df('deploy/b.ts'),body=k.querySelector('.df-body');
        return {a:a.open,k:k.open,b:b.open,top:body.scrollTop,hl:k.querySelectorAll('.hljs-keyword').length,focus:document.activeElement.dataset&&document.activeElement.dataset.l,sel:document.querySelectorAll('#dv-files td.ls').length};})()`);
      t.check(`${th} redraw: the request was held, nothing highlighted yet; a.ts collapsed, Dockerfile scrolled, line 60 selected`, !!paused && prep.hl === 0 && !prep.a && prep.top === 300 && prep.focus === '60' && before > 0, { paused, prep, before });
      t.check(`${th} redraw: dockerfile arrives and highlights; a.ts stays collapsed, scroll, selection, and focus stay`, after.hl > 0 && !after.a && after.k && after.b && after.top === 300 && after.focus === '60' && after.sel === before, after);
      t.noErrors(`${th} redraw: no page errors`);
    }
  },
};
