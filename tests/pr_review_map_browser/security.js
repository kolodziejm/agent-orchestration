'use strict';
// Data never becomes markup, and read marks survive page history: markup in every field a report takes from data stays
// text (an allow-list keeps <code> and https links in notes); a page whose diffs.json predates fingerprints stores and
// clears nothing by them; an older page of the same report never clears marks made on a newer one; a page rebuilt by
// hand (no refresh.py) counts its generation up and clears only marks on changed files; another history with the same
// storage key keeps marks it cannot order.
const fs = require('fs');
const path = require('path');
const { sleep } = require('./lib');

// Touch every view that renders data: each row and its detail, the map, the banner's lists, a note on every file.
const EXERCISE = `(async function(){
  var sleep=function(ms){return new Promise(function(r){setTimeout(r,ms);});};
  [].forEach.call(document.querySelectorAll('#g-chg details'),function(d){d.open=true;});
  var rows=[].slice.call(document.querySelectorAll('#g-order li.g-row'));
  for(var i=0;i<rows.length;i++){rows[i].querySelector('.nm').click();await sleep(30);
    var c=document.querySelector('#dv-files td.ln[data-l]');if(c){c.click();var a=document.querySelector('#dv-files [data-nt=add]');if(a){a.click();T.save(document.querySelector('#dv-files .nt-ed'),null,'n'+i);}}}
  document.querySelector('[data-v=map]').click();await sleep(100);
  document.querySelector('[data-v=list]').click();await sleep(50);
  return {pwn:window.__pwn||null,imgs:document.querySelectorAll('img').length,rows:rows.length};
})()`;
// Rows by path on the open tab, read marks, and the page's generation.
const HELPERS = `window.R={id:function(p){return [].find.call(document.querySelectorAll('#g-order li.g-row'),function(li){return li.querySelector('.nm').title.split('\\n')[0]===p;});},
  done:function(p){var li=R.id(p);return !!li&&li.classList.contains('done');},mark:function(p){var li=R.id(p);if(!li.classList.contains('done'))li.querySelector('input').click();},
  gen:function(){return JSON.parse(document.getElementById('review-config').textContent).generation;}};true`;

module.exports = {
  name: 'security',
  weight: 24, // seconds on a laptop, to start the longest suites first
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    t.use(HELPERS);
    const SEC = path.join(t.fixtures, 'sec');
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      /* 1. Markup in PR name, title, repo label, path, label, role, note, counts, removed paths. */
      await t.fresh(t.url(SEC, 'xss.html'), { dark });
      await sleep(300);
      const after = await B.ev(EXERCISE);
      t.check(`${th}: no markup from data runs or renders as an element anywhere`, after.pwn === null && after.imgs === 0 && after.rows === 2, after);
      const shown = await B.ev(`(function(){[].find.call(document.querySelectorAll('#g-order li.g-row'),function(li){return /svc/.test(li.textContent);}).querySelector('.nm').click();
        return {banner:document.getElementById('g-chg').innerText,tab:document.querySelector('#g-tabs button').textContent,detail:document.getElementById('g-detail').innerText,
          note:document.querySelector('#g-detail .g-note').innerHTML};})()`);
      t.check(`${th}: the banner and tab show the PR name as text`, shown.banner.includes('X <img src=x onerror=') && shown.tab.startsWith('X <img src=x'), shown);
      t.check(`${th}: the banner lists removed paths and a removed PR's file as text`, /src\/<img src=x onerror=.*'removed'.*\.ts/.test(shown.banner) && /Y · <img src=x onerror=.*'gonepr'/.test(shown.banner), shown.banner);
      const counts = await B.ev(`(document.querySelector('#g-order li.g-row:not(.sel) .nm').click(),document.getElementById('g-detail').innerText)`);
      t.check(`${th} detail: label, role, path, and counts show as text`, /svc <img src=x/.test(shown.detail) && /role <img src=x/.test(shown.detail) && /\+<img src=x onerror=.*'added'/.test(counts) && /src\/<img src=x onerror=.*'path'/.test(counts), { detail: shown.detail, counts });
      t.check(`${th}: a node note keeps <code> and an https link; img, script, and the javascript: link's href are gone`,
        shown.note.includes('<code>kept</code>') && shown.note.includes('<a href="https://example.com/x" rel="noopener noreferrer" target="_blank">ok</a>') && /<a>js<\/a>/.test(shown.note)
        && !/img|script|javascript|svg/i.test(shown.note), shown.note);
      t.noErrors(`${th} injection: no page errors`);
      if (!dark) { await B.ev(`document.getElementById('graph').scrollIntoView()`); await sleep(150); await t.shot('xss-1440-light'); }

      /* 2. A diffs.json without fingerprints: no "path=" fingerprint stored, the mark survives, nothing flagged changed. */
      await t.fresh(t.url(SEC, 'nofp.html'), { dark });
      await B.ev(`[].forEach.call(document.querySelectorAll('#g-order li.g-row input'),function(c){c.click();})`);
      const st1 = await B.ev(`({read:localStorage.getItem(T.key()+'read'),rfp:localStorage.getItem(T.key()+'readfp')})`);
      t.check(`${th} no fingerprints: marks stored, no fingerprint stored for them`, Object.keys(JSON.parse(st1.read).X).length === 2 && !/=/.test(st1.rfp), st1);
      await t.reload(t.url(SEC, 'nofp-prev.html'));
      const st2 = await B.ev(`({done:document.querySelectorAll('#g-order li.g-row.done').length,badges:[].map.call(document.querySelectorAll('.g-cb'),function(b){return b.textContent;}),banner:document.getElementById('g-chg').innerText})`);
      t.check(`${th} no fingerprints with a previous version: marks kept, no file flagged changed`, st2.done === 2 && !st2.badges.includes('changed') && /0 changed/.test(st2.banner), st2);
      t.noErrors(`${th} no fingerprints: no page errors`);
    }

    /* 3. Older page: build v1, keep a copy, refresh to v2, then go back and forth. */
    const demo = t.work, S2 = path.join(demo, 'scratch');
    const page = (f) => t.url(S2, f);
    const v1copy = () => fs.copyFileSync(path.join(S2, 'review.html'), path.join(S2, 'review-v1.html'));
    await t.fixture('demo-v1', demo);
    v1copy();
    await t.fixture('demo-move', demo);
    await t.skill('refresh.py', S2);
    await t.fresh(page('review-v1.html'));
    await B.ev(`R.mark('src/service.ts');R.mark('src/legacy.ts')`);
    t.check('older page: v1 is generation 0, v2 generation 1', await B.ev('R.gen()') === 0 && JSON.parse(fs.readFileSync(path.join(S2, 'previous.json'), 'utf8')).generation === 0);
    await t.reload(page('review.html'));
    t.check('v2 (newer): the mark on the changed service.ts is cleared, legacy.ts kept', !(await B.ev(`R.done('src/service.ts')`)) && await B.ev(`R.done('src/legacy.ts')`) && await B.ev('R.gen()') === 1);
    await B.ev(`R.mark('src/service.ts');R.mark('src/controller.ts')`);
    for (let i = 0; i < 2; i++) {
      await t.reload(page('review-v1.html'));
      const o = await B.ev(`({svc:R.done('src/service.ts'),ctl:R.done('src/controller.ts'),leg:R.done('src/legacy.ts'),was:!!document.querySelector('#g-order li.was')})`);
      t.check(`older page v1 (visit ${i + 1}): marks made on v2 stay (service, controller, legacy), nothing marked ↻`, o.svc && o.ctl && o.leg && !o.was, o);
      await t.reload(page('review.html'));
      const n = await B.ev(`({svc:R.done('src/service.ts'),ctl:R.done('src/controller.ts'),leg:R.done('src/legacy.ts')})`);
      t.check(`back on v2 (visit ${i + 1}): all three still read`, n.svc && n.ctl && n.leg, n);
    }
    // A mark made on the older page is cleared by the newer one when its file changed.
    await t.reload(page('review-v1.html'));
    await B.ev(`R.id('src/types.ts').querySelector('input').click()`);
    await t.reload(page('review.html'));
    t.check('a mark made on v1 for a file that changed in v2 is cleared on v2', !(await B.ev(`R.done('src/types.ts')`)) && await B.ev(`R.id('src/types.ts').classList.contains('was')`));
    t.noErrors('older page: no page errors');

    /* 4. Rebuilt by hand (no refresh.py, no --previous): v1, marks, branch moves, the three scripts again. */
    await t.fixture('demo-v1', demo);
    v1copy();
    const v1bytes = fs.readFileSync(path.join(S2, 'review.html'));
    await t.fixture('demo-rebuild', demo);
    t.check('by hand: rebuilding the same content gives the same bytes (generation 0 kept)', fs.readFileSync(path.join(S2, 'review.html')).equals(v1bytes));
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      if (dark) { await t.fixture('demo-v1', demo); v1copy(); }
      await t.fresh(page('review-v1.html'), { dark });
      await B.ev(`R.mark('src/service.ts');R.mark('src/legacy.ts');R.mark('src/types.ts')`);
      await t.fixture('demo-move', demo);
      await t.fixture('demo-rebuild', demo);
      await t.reload(page('review.html'));
      const hand = await B.ev(`({gen:R.gen(),svc:R.done('src/service.ts'),was:R.id('src/service.ts').classList.contains('was'),leg:R.done('src/legacy.ts'),typ:R.done('src/types.ts'),
        banner:document.getElementById('g-chg').hidden?null:document.getElementById('g-chg').innerText,badges:document.querySelectorAll('.g-cb').length})`);
      t.check(`${th} by hand: generation 1; marks on the changed service.ts and types.ts cleared (↻), legacy.ts kept`, hand.gen === 1 && !hand.svc && hand.was && !hand.typ && hand.leg, hand);
      t.check(`${th} by hand: the banner says which marks were cleared, with no comparison and no badges`, /Read marks cleared because the file changed: 2/.test(hand.banner) && /Read before, changed since \(2\)/.test(hand.banner) && !/Changed since the last version/.test(hand.banner) && hand.badges === 0, hand.banner);
      if (!dark) { await B.ev(`[].forEach.call(document.querySelectorAll('#g-chg details'),function(d){d.open=true;});document.getElementById('g-chg').scrollIntoView()`); await sleep(150); await t.shot('hand-rebuild-1440-light', '#g-chg', 300); }
      await B.ev(`R.mark('src/service.ts')`);
      await t.reload(page('review-v1.html'));
      t.check(`${th} by hand: the older v1 page keeps the mark made on v2`, await B.ev(`R.done('src/service.ts')`) && !(await B.ev(`!!document.querySelector('#g-order li.was')`)));
      await t.reload(page('review.html'));
      t.check(`${th} by hand: back on v2 the mark is still there`, await B.ev(`R.done('src/service.ts')`));
      const genAfter = await t.skill('refresh.py', S2);
      await t.reload(page('review.html'));
      t.check(`${th} refresh after a hand build of the same content: previous.json generation 1, the page keeps generation 1 and the mark`, JSON.parse(fs.readFileSync(path.join(S2, 'previous.json'), 'utf8')).generation === 1 && await B.ev('R.gen()') === 1 && await B.ev(`R.done('src/service.ts')`), genAfter);
      t.noErrors(`${th} by hand: no page errors`);
    }

    /* 5. Another history with the same storage key: a fresh directory built from v2 starts at generation 0. */
    await t.fixture('demo-v1', demo);
    v1copy();
    await t.fresh(page('review-v1.html'));
    await B.ev(`R.mark('src/types.ts');R.mark('src/legacy.ts')`);
    await t.fixture('demo-move', demo);
    await t.skill('refresh.py', S2);
    const FRESH = path.join(demo, 'scratch-fresh');
    await t.fixture('demo-rebuild', demo, FRESH);
    await t.reload(t.url(FRESH, 'review.html'));
    const fr = await B.ev(`({gen:R.gen(),typ:R.done('src/types.ts'),was:R.id('src/types.ts').classList.contains('was'),leg:R.done('src/legacy.ts')})`);
    t.check('other history at the same generation (0): a mark on changed code is cleared (↻), an unchanged file kept', fr.gen === 0 && !fr.typ && fr.was && fr.leg, fr);
    await t.reload(page('review.html'));
    await B.ev(`R.mark('src/service.ts')`);
    await t.reload(t.url(FRESH, 'review.html'));
    t.check('other history: a mark from a later generation (1) is kept on a generation-0 page (it cannot be ordered)', await B.ev(`R.done('src/service.ts')`));
    t.noErrors('histories: no page errors');
  },
};
