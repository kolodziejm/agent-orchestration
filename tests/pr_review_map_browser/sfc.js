'use strict';
// Syntax highlighting: Vue, Svelte, and Astro hunks highlighted by the block they sit in (both diff sides, both diff
// modes), block comments over several lines (each side on its own lines, a hunk that starts inside one), languages
// outside the highlight.js bundle loaded from cdnjs on demand, the extension and file-name map, and the fence hint of a
// copied note on a .vue line. Needs network access to cdnjs, as the assembled page does.
const { sleep } = require('./lib');

const HELPERS = `window.V={
  open:function(p){[].find.call(document.querySelectorAll('#g-order .nm'),function(x){return x.title.split('\\n')[0]===p;}).click();},
  /* The highlight.js classes inside the first diff cell holding text (new: the added or context row; old: the removed one). */
  cls:function(text,side){var cells=[].filter.call(document.querySelectorAll('#dv-files td.cd'),function(td){return td.textContent.indexOf(text)>=0;});
    if(side==='new')cells=cells.filter(function(td){return td.classList.contains('add')||!td.classList.contains('del');}).slice(-1);
    if(side==='old')cells=cells.filter(function(td){return td.classList.contains('del');}).slice(0,1);
    var td=cells[0];if(!td)return null;var out={};[].forEach.call(td.querySelectorAll('[class^=hljs-],[class*=" hljs-"]'),function(s){s.className.split(' ').forEach(function(c){if(/^hljs-/.test(c))out[c]=1;});});return Object.keys(out).sort();},
  /* The code cell of the first line holding text on a side (old: the left cell, new: the right one; unified mode has
     one): its text outside highlight.js comments, and the words it marks as keywords. */
  code:function(text,side){
    var uni=!!document.querySelector('#dv-files table.dt.uni'),td=null;
    [].some.call(document.querySelectorAll('#dv-files table.dt tr'),function(tr){var c=tr.cells[uni?2:side==='old'?1:3];return !!(c&&c.textContent.indexOf(text)>=0&&(td=c));});
    if(!td)return null;var out='',w=document.createTreeWalker(td,NodeFilter.SHOW_TEXT),n;
    while((n=w.nextNode()))if(!n.parentNode.closest('.hljs-comment,.mk'))out+=n.data;
    return {code:out.replace(/\\s+/g,' ').trim(),kw:[].map.call(td.querySelectorAll('.hljs-keyword'),function(s){return s.textContent;})};}
};true`;
const LAZY = ['dockerfile', 'groovy', 'protobuf', 'pgsql'];

module.exports = {
  name: 'sfc',
  weight: 7, // seconds on a laptop, to start the longest suites first
  needs: ['chrome', 'cdn'],
  async run(t) {
    const B = t.B;
    const URL = t.url(t.fixtures, 'sfc', 'review.html');
    t.use(HELPERS);
    const has = (a, k) => !!a && a.indexOf(k) >= 0;
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(URL, { height: 1000, dark });
      await B.ev(`(function(){var t=Date.now();return new Promise(function(r){(function w(){if(${JSON.stringify(LAZY)}.every(function(l){return hljs.getLanguage(l);})||Date.now()-t>8000)r();else setTimeout(w,100);})();});})()`);
      t.check(`${th}: languages outside the bundle load from cdnjs when a diff needs them`, await B.ev(`${JSON.stringify(LAZY)}.every(function(l){return !!hljs.getLanguage(l);})&&!hljs.getLanguage('scala')&&[].every.call(document.querySelectorAll('script[src]'),function(s){return s.src.indexOf('https://cdnjs.cloudflare.com/')===0;})`));
      for (const m of ['sbs', 'uni']) {
        await B.ev(`document.querySelector('[data-m=${m}]').click()`);
        await B.ev(`V.open('web/src/components/VisitCard.vue')`); await sleep(150);
        const r = await B.ev(`({tpl:V.cls(':title="label(visit)"','new'),tplOld:V.cls('<p class="row-7">','old'),ts:V.cls('props.active ?','new'),tsOld:V.cls('const value6','old'),scss:V.cls('darken(#333','new'),scssOld:V.cls('color: #333; }','old')})`);
        t.check(`${th} vue ${m}: a template hunk in the middle of the file highlights as markup (both sides)`, has(r.tpl, 'hljs-tag') && has(r.tpl, 'hljs-attr') && has(r.tplOld, 'hljs-tag'), r);
        t.check(`${th} vue ${m}: a <script setup lang="ts"> hunk highlights as TypeScript (both sides)`, has(r.ts, 'hljs-keyword') && !has(r.ts, 'hljs-tag') && has(r.tsOld, 'hljs-keyword'), r);
        t.check(`${th} vue ${m}: a <style lang="scss"> hunk highlights as SCSS (both sides)`, (has(r.scss, 'hljs-selector-class') || has(r.scss, 'hljs-attribute')) && has(r.scss, 'hljs-variable') && !has(r.scss, 'hljs-tag') && has(r.scssOld, 'hljs-variable'), r);
        await B.ev(`V.open('web/src/routes/+page.svelte')`); await sleep(150);
        const sv = await B.ev(`({ts:V.cls('let item6','new'),mk:V.cls('class="hot"','new')})`);
        t.check(`${th} svelte ${m}: script lang="ts" as TypeScript, markup as xml`, has(sv.ts, 'hljs-keyword') && !has(sv.ts, 'hljs-tag') && has(sv.mk, 'hljs-tag'), sv);
        await B.ev(`V.open('web/src/pages/index.astro')`); await sleep(150);
        const as = await B.ev(`({fm:V.cls("const title",'new'),mk:V.cls('<h1>{title}','new'),css:V.cls('color: navy','new')})`);
        t.check(`${th} astro ${m}: frontmatter as TypeScript, markup as xml, <style> as CSS`, has(as.fm, 'hljs-keyword') && has(as.mk, 'hljs-tag') && has(as.css, 'hljs-attribute') && !has(as.css, 'hljs-tag'), as);
        await B.ev(`V.open('web/src/landing/platforms.ts')`); await sleep(150);
        const doc = await B.ev(`[' * The platforms',' * optional',' * declare only',' * (\`App',' * each status',' * platform follows',' * that change',' * "Platform launch',' * Linux is',' */'].map(function(s){return V.code(s,'new');})`);
        t.check(`${th} block comment ${m}: every line of a new file's doc comment reads as comment, through its closing line`, doc.every((c) => c && c.code === ''), doc);
        const pl = await B.ev(`({after:V.code('export const landingPlatforms','new'),glob:V.code("const glob = 'lib/*'",'new'),next:V.code('export const shown','new'),tail:V.code('and closes','new')})`);
        t.check(`${th} block comment ${m}: code after a comment, after a "/*" in a string, and after the closer on a line stays code`, pl.after.kw.includes('const') && pl.glob.kw.includes('const') && pl.next.code === 'export const shown: number = 3;' && pl.tail.code === 'export const tail = 2;' && pl.tail.kw.includes('const'), pl);
        await B.ev(`V.open('web/src/landing/legacy.ts')`); await sleep(150);
        const lg = await B.ev(`({bOld:V.code('export const b = 2','old'),bNew:V.code('export const b = 2','new'),dOld:V.code('export const d = 4','old'),dNew:V.code('export const d = 4','new'),two:V.code(' * Doc two','new'),twoOld:V.code(' * Doc two','old'),six:V.code('Doc six, after','new'),keep:V.code('export function keep','new')})`);
        if (m === 'sbs') t.check(`${th} block comment sbs: a comment removed on the old side or added on the new covers its lines on that side only`, lg.bOld.code === '' && lg.bNew.kw.includes('const') && lg.dOld.kw.includes('const') && lg.dNew.code === '', lg);
        else t.check(`${th} block comment uni: context lines follow the new side (inside the added comment, outside the removed one)`, lg.bNew.kw.includes('const') && lg.dNew.code === '', lg);
        t.check(`${th} block comment ${m}: a hunk that starts inside a doc comment reads as comment up to the closer, code after it`, lg.two.code === '' && lg.twoOld.code === '' && lg.six.code === '' && lg.keep.kw.includes('function'), lg);
        await B.ev(`V.open('web/public/landing.html')`); await sleep(150);
        const ht = await B.ev(`({inside:V.code('<section class="beta">','new'),after:V.cls('<p class="live">','new')})`);
        t.check(`${th} block comment ${m}: an HTML comment over several lines covers the markup inside it`, ht.inside.code === '' && has(ht.after, 'hljs-tag'), ht);
      }
      await B.ev(`document.querySelector('[data-m=sbs]').click()`);
      for (const [p, text, want] of [['Dockerfile', 'FROM node:22', 'hljs-keyword'], ['app/build.gradle', "id 'application'", 'hljs-string'], ['api/visit.proto', 'string name', 'hljs-type'],
        ['web/.env.development', 'DEBUG=true', 'hljs-attr'], ['db/schema.pgsql', 'NOT NULL', 'hljs-keyword'], ['settings.gradle.kts', 'rootProject', 'hljs-string']]) {
        await B.ev(`V.open(${JSON.stringify(p)})`); await sleep(120);
        const got = await B.ev(`V.cls(${JSON.stringify(text)},'new')`);
        t.check(`${th} extension map: ${p} is highlighted (${want})`, has(got, want), got);
      }
      await B.ev(`V.open('infra/main.tf')`); await sleep(120);
      t.check(`${th} extension map: Terraform (no highlight.js language) stays plain and readable`, JSON.stringify(await B.ev(`V.cls('bucket = "y"','new')`)) === '[]');
      // A copied note on a .vue line uses "vue" as its fence hint.
      await B.ev(`V.open('web/src/components/VisitCard.vue')`); await sleep(120);
      await B.ev(`[].find.call(document.querySelectorAll('#dv-files td.ln[data-s=new]'),function(t){return t.nextElementSibling&&t.nextElementSibling.textContent.indexOf('props.active ?')>=0;}).click();document.querySelector('[data-nt=add]').click()`);
      await B.ev(`T.save(document.querySelector('#dv-files .nt-ed'),null,'Why default to 0?')`);
      const md = await t.copy();
      t.check(`${th}: copied note on a .vue line uses the "vue" fence hint with the code`, /```vue\nconst value6 = computed\(\(\) => \(props\.active/.test(md || ''), md);
      await B.ev(`document.querySelector('#dv-files details.df').scrollIntoView()`); await sleep(150);
      await t.shot(`vue-1440-${th}`, '#dv', 1400);
      await B.ev(`document.querySelector('[data-m=uni]').click()`); await sleep(150);
      await t.shot(`vue-unified-1440-${th}`, '#dv', 1400);
      t.noErrors(`${th}: no page errors`);
    }
  },
};
