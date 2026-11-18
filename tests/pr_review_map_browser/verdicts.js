'use strict';
// REQUIREMENT: the review ends in a decision. Each risk of the brief that has an id takes OK, Needs fix, or Question (on its
// row, and in the overlay's header, where the keys o, n, ? set it); each decision card takes one option or Question, and the
// chosen option shows on the card and on the brief's decision line; clicking the active button again clears it. Verdicts
// persist across a reload. One progress line at the top of the brief counts risks, decisions, must-read files, and spot-check
// files, says "Ready to merge" only when every risk is OK, every decision has an option, and every spot-check file is
// Routine, else "Not ready:" with counts that jump to the first such item. "Copy fix brief" copies the risks to fix or ask
// about, the chosen options, the open decision questions, the skim files that were not routine, and then the shown notes.
// A large change has a spot-check list after Read (its files open in the overlay under their own divider, with Routine and
// Not routine, keys o and n) and a warning when any file was not routine. In light and dark.
const { sleep } = require('./lib');

module.exports = {
  name: 'verdicts',
  weight: 5,
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const PAGE = t.url(t.fixtures, 'brief', 'review.html');
    const SPOT = t.url(t.fixtures, 'brief', 'spot', 'review.html');
    const SMALL = t.url(t.fixtures, 'brief', 'small', 'review.html');
    const stored = () => B.ev(`JSON.stringify(T.stored('verdicts'))`);
    const press = (sel, v) => B.ev(`document.querySelector(${JSON.stringify(sel + ' .vd-b[data-vd="' + v + '"]')}).click()`);
    const bySel = (sel, re) => B.ev(`[].find.call(document.querySelectorAll(${JSON.stringify(sel)}),function(b){return ${re}.test(b.textContent);}).click()`);
    const PROG = `(function(){var n=document.getElementById('pg-n'),s=document.getElementById('pg-state');return {n:n&&n.textContent,state:s&&s.textContent,cls:s&&s.className,copy:document.getElementById('vd-copy').disabled,
      jumps:[].map.call(document.querySelectorAll('#pg-state .pg-j'),function(b){return b.dataset.j;})};})()`;
    const GROUPS = (sel) => `[].map.call(document.querySelectorAll(${JSON.stringify(sel + ' .vd-b')}),function(b){return b.textContent+(b.getAttribute('aria-pressed')==='true'?'*':'');})`;
    const COPY = `(function(){window.__copied=null;navigator.clipboard.writeText=function(t){window.__copied=t;return Promise.resolve();};document.getElementById('vd-copy').click();
      return new Promise(function(r){var n=0;(function w(){if(window.__copied!==null||++n>20)r(window.__copied);else setTimeout(w,50);})();});})()`;
    const OV = `(function(){var g=document.getElementById('graph'),cur=document.querySelector('#ov-ol .ov-row.cur'),vr=document.querySelector('#ov-vd .vd:not([hidden])');
      return {open:g.classList.contains('ovl'),cur:cur?cur.textContent:null,rows:[].map.call(document.querySelectorAll('#ov-ol>li'),function(l){return (l.classList.contains('ov-div')?'--':'')+l.textContent;}),
        vd:vr?{k:vr.dataset.k,id:vr.dataset.id,btns:[].map.call(vr.querySelectorAll('.vd-b'),function(b){return b.textContent+(b.getAttribute('aria-pressed')==='true'?'*':'');})}:null,keys:document.getElementById('ov-keys').textContent,
        head:document.getElementById('ov-head').textContent};})()`;
    const NOTE = { id: 'n1', kind: 'issue', scope: 'pr', pr: 'A', text: 'Check the tenant.', ts: 1 };
    let s;

    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';

      // The controls and the progress line before any verdict.
      await t.fresh(PAGE, { steps: false, dark });
      t.check(`verdicts ${th}: each risk with an id has OK, Needs fix, and Question`, JSON.stringify(await B.ev(GROUPS('#risk-1'))) === '["OK","Needs fix","Question"]'
        && (await B.ev(`document.querySelectorAll('#brief .brief-risks .vd').length`)) === 3);
      t.check(`verdicts ${th}: a decision has a button per option (the recommended one named), or Decided, and Question`, JSON.stringify(await B.ev(GROUPS('#dec-1'))) === '["Now","Behind a flag","Question"]'
        && JSON.stringify(await B.ev(GROUPS('#dec-2'))) === '["Recommended: Keep 3 s","6 s","Question"]' && JSON.stringify(await B.ev(GROUPS('#dec-3'))) === '["Decided","Question"]');
      s = await B.ev(PROG);
      t.check(`verdicts ${th}: the progress line leads the brief with what is open, and Copy fix brief is off`, s.n === 'Risks 0/3 · Decisions 0/3 · Must read 0/4' && s.state === 'Not ready: 3 risks open, 3 decisions open' && s.copy
        && await B.ev(`(function(){var b=document.getElementById('brief'),p=document.getElementById('vd-prog');return p.parentNode===b&&p.previousElementSibling.tagName==='H2';})()`), s);

      // A verdict sets, shows, clears on a second click, and is kept.
      await press('#risk-1', 'fix');
      t.check(`verdicts ${th}: a click sets the verdict on its risk and stores it under the page's key`, (await stored()) === '{"risk-1":"fix"}' && JSON.stringify(await B.ev(GROUPS('#risk-1'))) === '["OK","Needs fix*","Question"]', await stored());
      await press('#risk-1', 'fix');
      t.check(`verdicts ${th}: the same button again clears it`, (await stored()) === '{}' && JSON.stringify(await B.ev(GROUPS('#risk-1'))) === '["OK","Needs fix","Question"]', await stored());
      await press('#risk-1', 'fix'); await press('#risk-2', 'q'); await press('#risk-3', 'ok');
      s = await B.ev(PROG);
      t.check(`verdicts ${th}: the line counts every risk with a verdict and names what is not ready, each count a button`, s.n === 'Risks 3/3 · Decisions 0/3 · Must read 0/4' && s.state === 'Not ready: 1 needs a fix, 1 question, 3 decisions open'
        && s.jumps.join() === 'fix,question,openDec', s);
      await press('#dec-1', 'o1'); await press('#dec-2', 'o0'); await press('#dec-3', 'd');
      const dec = await B.ev(`(function(){return {picked:[].map.call(document.querySelectorAll('.decisions .vd-picked'),function(e){return e.textContent.replace(/\\s+/g,' ').trim().slice(0,40);}),
        lines:[].map.call(document.querySelectorAll('#brief .brief-decisions li'),function(l){var c=l.querySelector('.vd-ch');return c&&!c.hidden?c.textContent:null;}),
        groups:[${JSON.stringify('#dec-1')},${JSON.stringify('#dec-2')},${JSON.stringify('#dec-3')}].map(function(s){return [].map.call(document.querySelectorAll(s+' .vd-b'),function(b){return b.getAttribute('aria-pressed')==='true'?b.textContent:'';}).join('');})};})()`);
      t.check(`verdicts ${th}: the chosen option is marked on its card and shown on the brief's decision line`, dec.picked.length === 2 && /^Behind a flag/.test(dec.picked[0]) && /^Recommended: keep it/.test(dec.picked[1])
        && dec.lines.join('|') === '→ Behind a flag|→ Keep 3 s|→ Decided' && dec.groups.join('|') === 'Behind a flag|Recommended: Keep 3 s|Decided', dec);
      s = await B.ev(PROG);
      t.check(`verdicts ${th}: with every decision given an option only the risks remain`, s.n === 'Risks 3/3 · Decisions 3/3 · Must read 0/4' && s.state === 'Not ready: 1 needs a fix, 1 question', s);

      // The count jumps to the first matching item.
      await B.ev(`window.scrollTo(0,0)`);
      await B.ev(`document.querySelector('#pg-state .pg-j[data-j="question"]').click()`); await sleep(200);
      t.check(`verdicts ${th}: a count jumps to the first item it counts and focuses its controls`, await B.ev(`(function(){var r=document.getElementById('risk-2').getBoundingClientRect(),a=document.activeElement;
        return r.top>=0&&r.bottom<=innerHeight&&!!a&&!!a.closest&&a.closest('#risk-2')!==null;})()`));

      // Persistence across a reload.
      const kept = await stored();
      await t.reload(PAGE, { steps: false });
      s = await B.ev(PROG);
      t.check(`verdicts ${th}: verdicts and the chosen options are still there after a reload, with the same progress`, (await stored()) === kept && JSON.stringify(await B.ev(GROUPS('#risk-2'))) === '["OK","Needs fix","Question*"]'
        && JSON.stringify(await B.ev(GROUPS('#dec-1'))) === '["Now","Behind a flag*","Question"]' && s.state === 'Not ready: 1 needs a fix, 1 question'
        && (await B.ev(`document.querySelector('#brief .brief-decisions li .vd-ch').hidden===false&&document.querySelectorAll('.decisions .vd-picked').length`)) === 2, { kept, s });

      // Ready to merge only when every risk is OK and every decision has an option; a question is not ready.
      await press('#risk-1', 'ok'); await press('#risk-2', 'ok');
      s = await B.ev(PROG);
      t.check(`verdicts ${th}: every risk OK and every decision given an option reads "Ready to merge"`, s.n === 'Risks 3/3 · Decisions 3/3 · Must read 0/4' && s.state === 'Ready to merge' && /ready/.test(s.cls) && s.jumps.length === 0, s);
      await press('#dec-3', 'q');
      s = await B.ev(PROG);
      t.check(`verdicts ${th}: a question on a decision takes the state back to not ready`, s.state === 'Not ready: 1 question' && s.n.includes('Decisions 3/3'), s);
      await press('#dec-3', 'q');
      await press('#dec-3', 'd');
      await press('#risk-3', 'q');
      t.check(`verdicts ${th}: so does a question on a risk`, (await B.ev(PROG)).state === 'Not ready: 1 question');
      await press('#risk-3', 'ok');
      t.check(`verdicts ${th}: and clearing the questions makes it ready again`, (await B.ev(PROG)).state === 'Ready to merge');
      const col = await B.ev(`(function(){function bg(sel){return getComputedStyle(document.querySelector(sel)).backgroundColor;}return {on:bg('#risk-1 .vd-b[data-vd="ok"]'),off:bg('#risk-1 .vd-b[data-vd="fix"]'),surface:getComputedStyle(document.querySelector('.vd-prog')).backgroundColor,
        ready:getComputedStyle(document.querySelector('#pg-state')).color,not:(function(){document.querySelector('#risk-1 .vd-b[data-vd="ok"]').click();return getComputedStyle(document.querySelector('#pg-state')).color;})()};})()`);
      t.check(`verdicts ${th}: a chosen button and the state read apart from the rest (colours from tokens)`, col.on !== col.off && col.ready !== col.not, col);
      await t.shot(`verdicts-${th}`, '#brief');
      t.noErrors(`verdicts ${th}: no page errors`);

      // Overlay: the header carries the risk's verdict, and o, n, ? set it.
      await t.fresh(PAGE, { steps: false, dark });
      await B.ev(`window.scrollTo(0,150)`); await sleep(100);
      await bySel('#brief .brief-risks button.g-ref', /items\.ts:3-6/); await sleep(900);
      s = await B.ev(OV);
      t.check(`verdicts ${th}: the overlay header of a risk entry shows its three buttons and the keys`, s.open && s.cur === 'items.ts3–6' && s.vd && s.vd.k === 'risk' && s.vd.id === 'risk-2' && s.vd.btns.join() === 'OK,Needs fix,Question' && /o OK · n needs fix · \? question/.test(s.keys), s);
      await B.key('o'); await sleep(100);
      t.check(`verdicts ${th}: o sets OK on the risk shown`, (await stored()) === '{"risk-2":"ok"}' && (await B.ev(OV)).vd.btns.join() === 'OK*,Needs fix,Question', await stored());
      await B.key('n'); await B.key('?', 8); await sleep(100);
      t.check(`verdicts ${th}: n sets Needs fix and ? Question, keys setting rather than toggling`, (await stored()) === '{"risk-2":"q"}', await stored());
      await B.key('?', 8); await sleep(60);
      t.check(`verdicts ${th}: a key pressed twice does not clear (the button does)`, (await stored()) === '{"risk-2":"q"}');
      await B.ev(`document.querySelector('#ov-vd .vd:not([hidden]) .vd-b[data-vd="q"]').click()`); await sleep(100);
      t.check(`verdicts ${th}: the header's active button clears it`, (await stored()) === '{}', await stored());
      await B.key('n'); await B.key('j'); await sleep(500);
      s = await B.ev(OV);
      t.check(`verdicts ${th}: j moves on, each entry shows its own risk's verdict, and the queue row names the verdict`, s.cur === 'ItemList.tsx2–3' && s.vd.id === 'risk-3' && s.vd.btns.join() === 'OK,Needs fix,Question'
        && s.rows[1] === 'items.ts3–6Needs fix' && s.rows[2] === 'ItemList.tsx2–3', s);
      await B.key('k'); await B.key('k'); await sleep(300);
      t.check(`verdicts ${th}: k steps back to the first risk, and its controls show its own verdict`, (await B.ev(OV)).vd.id === 'risk-1');
      await B.key('Escape'); await sleep(400);
      t.check(`verdicts ${th}: the verdict set in the overlay is on the risk row and counted after closing`, JSON.stringify(await B.ev(GROUPS('#risk-2'))) === '["OK","Needs fix*","Question"]'
        && (await B.ev(PROG)).state === 'Not ready: 1 needs a fix, 2 risks open, 3 decisions open', await B.ev(PROG));

      // Keys do nothing on other entries and while typing.
      await bySel('#budget button.g-ref', /session\.ts:5-9/); await sleep(900);
      s = await B.ev(OV);
      const before = await stored();
      await B.key('o'); await B.key('n'); await B.key('?', 8); await sleep(100);
      t.check(`verdicts ${th}: on a budget entry there are no verdict controls and the keys do nothing`, s.vd === null && !/needs fix/.test(s.keys) && (await stored()) === before, s);
      await B.key('Escape'); await sleep(400);
      await bySel('#brief .brief-risks button.g-ref', /session\.ts:5-9/); await sleep(900);
      await B.ev(`T.cell('src/auth/session.ts','new',7).click()`); await sleep(100);
      await B.ev(`document.querySelector('#dv-files [data-nt=add]').click()`); await sleep(100);
      const ta = await B.ev(`(function(){var e=document.querySelector('#dv-files .nt-ed textarea');if(e)e.focus();return !!e&&document.activeElement===e;})()`);
      await B.key('o'); await B.key('n'); await sleep(100);
      t.check(`verdicts ${th}: o and n do nothing while a note editor has the focus`, ta && (await stored()) === before, await stored());
      await B.key('Escape'); await B.key('Escape'); await sleep(400);
      t.noErrors(`verdicts ${th}: no page errors in the overlay`);

      // Copy fix brief.
      await t.fresh(PAGE, { steps: false, dark, seed: `(function(){var c=JSON.parse(document.getElementById('review-config').textContent),k='review-map:'+(c.storageKey||c.title)+':';localStorage.setItem(k+'notes',${JSON.stringify(JSON.stringify([NOTE]))});})()` });
      t.check(`verdicts ${th}: with only a note to say, Copy fix brief is on`, !(await B.ev(PROG)).copy);
      await press('#risk-1', 'fix'); await press('#risk-2', 'q'); await press('#risk-3', 'ok'); await press('#dec-1', 'o1'); await press('#dec-2', 'q'); await press('#dec-3', 'q'); await press('#dec-3', 'q');
      const md = await B.ev(COPY);
      const idx = (re) => md ? md.search(re) : -1;
      t.check(`verdicts ${th}: the fix brief names the risks to fix and ask about with PR, text, and path:start-end`, !!md && /^# Fix brief: Brief sample/.test(md) && /## Needs fix \(1\)\n\n1\. \*\*High\*\* · A #1 — The tenant check is gone, so a token of one clinic opens another's data\n   - `src\/auth\/session\.ts:5-9`/.test(md)
        && /## Questions \(1\)\n\n1\. \*\*Medium\*\* · B #2 — A retry after the timeout can list items twice\n   - `src\/api\/items\.ts:3-6`/.test(md), md);
      t.check(`verdicts ${th}: then the chosen options and the open decision questions`, /## Decisions \(1\)\n\n- Ship the 404 for an unknown clinic now, or behind a flag\? \(B #2\) → \*\*Behind a flag\*\*/.test(md) && /## Open decision questions \(1\)\n\n- Keep the 3 s timeout\? \(B #2\)/.test(md)
        && idx(/## Needs fix/) < idx(/## Questions/) && idx(/## Questions/) < idx(/## Decisions/) && idx(/## Decisions/) < idx(/## Open decision questions/), md);
      t.check(`verdicts ${th}: then the shown notes, as Copy notes writes them, and the sections with nothing in them are left out`, /\n---\n\n# Review notes: Brief sample/.test(md) && /Check the tenant\./.test(md) && idx(/## Open decision questions/) < idx(/# Review notes/)
        && !/Not routine|skim files that were not/i.test(md) && !/Rename the route|blank row/.test(md), md);
      t.check(`verdicts ${th}: the button confirms, and goes back after a moment`, await B.ev(`document.getElementById('vd-copy').textContent==='Copied ✓'`) && (await (async () => { await sleep(2300); return B.ev(`document.getElementById('vd-copy').textContent`); })()) === 'Copy fix brief');
      t.noErrors(`verdicts ${th}: no page errors copying`);

      // A brief with nothing to track has no progress line; a page without ids keeps rendering its risks.
      await t.fresh(SMALL, { steps: false, dark });
      t.check(`verdicts ${th}: a risk without an id has no verdict controls, and a brief with nothing to track has no progress line`, await B.ev(`document.querySelectorAll('#brief .vd, .decisions .vd').length===0&&!document.getElementById('vd-prog')&&document.querySelectorAll('#brief .brief-risks li').length===1`));
    }

    // The spot-check of the skim pile.
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(SPOT, { steps: false, dark });
      const sp = await B.ev(`(function(){var s=document.getElementById('budget'),h=s.querySelector('.b-spot h3'),det=s.querySelector('details.b-more');
        return {h:h&&h.textContent,note:s.querySelector('.b-spotnote').textContent,after:!!det&&!!(det.compareDocumentPosition(s.querySelector('.b-spot'))&Node.DOCUMENT_POSITION_FOLLOWING),
          files:[].map.call(s.querySelectorAll('.b-spot button.g-ref'),function(b){return b.textContent;}),prs:[].map.call(s.querySelectorAll('.b-spot .who'),function(e){return e.textContent;}),warn:s.querySelector('.b-spotwarn').hidden,
          groups:[].map.call(s.querySelectorAll('.b-spot li .vd'),function(g){return [].map.call(g.children,function(b){return b.textContent;}).join('/');}),prog:document.getElementById('pg-n').textContent};})()`);
      t.check(`spot-check ${th}: the budget lists the sample after Read, each file a code link, with one plain line under the heading`, sp.h === 'Spot-check (3)' && sp.after && sp.files.length === 3
        && sp.note === "Routine files picked at random. If any is not routine, the skim class can't be trusted." && sp.warn && sp.prs.join() === 'A,B,C', sp);
      t.check(`spot-check ${th}: the picks are source files of 15 lines or more first (format.ts, routes.ts), then a test; two never share a PR`, sp.files.join() === 'format.ts:1,routes.ts:1,ItemList.test.tsx:1', sp.files);
      t.check(`spot-check ${th}: each row has Routine and Not routine, and the progress line counts the sample`, sp.groups.join() === 'Routine/Not routine,Routine/Not routine,Routine/Not routine' && sp.prog === 'Risks 0/3 · Decisions 0/3 · Must read 0/2 · Spot-check 0/3', sp);

      // In the overlay the sample follows Read under its own divider.
      await B.ev(`window.scrollTo(0,150)`); await sleep(100);
      await bySel('#budget .b-spot button.g-ref', /format\.ts/); await sleep(900);
      s = await B.ev(OV);
      t.check(`spot-check ${th}: the queue lists the sample after Read under its own divider, and its header has Routine and Not routine`, s.open && s.rows.join('|') === '0042_slot.sql1|session.ts5–9|--Read (2)|items.ts1|ItemList.tsx1|--Spot-check (3)|format.ts1|routes.ts1|ItemList.test.tsx1'
        && s.cur === 'format.ts1' && s.vd && s.vd.k === 'spot' && s.vd.id === 'A:src/util/format.ts' && s.vd.btns.join() === 'Routine,Not routine' && /o routine · n not routine/.test(s.keys) && /picked at random/.test(s.head), s);
      await B.key('o'); await sleep(100);
      t.check(`spot-check ${th}: o marks the file Routine, keyed by PR and path`, (await stored()) === '{"A:src/util/format.ts":"ok"}' && (await B.ev(OV)).vd.btns.join() === 'Routine*,Not routine', await stored());
      await B.key('?', 8); await sleep(60);
      t.check(`spot-check ${th}: ? means nothing here`, (await stored()) === '{"A:src/util/format.ts":"ok"}');
      await B.key('j'); await sleep(500); await B.key('n'); await sleep(100);
      t.check(`spot-check ${th}: n marks the next file Not routine, and its queue row says so`, (await stored()) === '{"A:src/util/format.ts":"ok","B:src/api/routes.ts":"no"}' && (await B.ev(OV)).rows.slice(-3).join('|') === 'format.ts1Routine|routes.ts1Not routine|ItemList.test.tsx1', await B.ev(OV));
      await B.key('Escape'); await sleep(400);
      const w = await B.ev(`(function(){var e=document.querySelector('#budget .b-spotwarn'),r=e.getBoundingClientRect();return {t:e.textContent,hidden:e.hidden,vis:r.height>0,bg:getComputedStyle(e).backgroundColor,page:getComputedStyle(document.body).backgroundColor,prog:document.getElementById('pg-n').textContent,state:document.getElementById('pg-state').textContent};})()`);
      t.check(`spot-check ${th}: a file that was not routine shows the warning in the budget naming its PR`, w.t === "1 of 3 sampled skim files wasn't routine — review the skim files of PR B more closely" && !w.hidden && w.vis && w.bg !== w.page, w);
      t.check(`spot-check ${th}: the progress line counts the sample and the file that was not routine`, w.prog === 'Risks 0/3 · Decisions 0/3 · Must read 0/2 · Spot-check 2/3' && /3 risks open, 3 decisions open, 1 spot-check unmarked, 1 not routine$/.test(w.state), w);

      // Ready needs the sample marked Routine as well.
      for (const id of ['risk-1', 'risk-2', 'risk-3']) await press('#' + id, 'ok');
      await press('#dec-1', 'o0'); await press('#dec-2', 'o0'); await press('#dec-3', 'd');
      await B.ev(`[].find.call(document.querySelectorAll('#budget .b-spot li'),function(l){return /ItemList\\.test\\.tsx/.test(l.textContent);}).querySelector('.vd-b[data-vd="ok"]').click()`);
      s = await B.ev(PROG);
      t.check(`spot-check ${th}: with the risks and decisions done, a file that was not routine still keeps it not ready`, s.state === 'Not ready: 1 not routine' && s.n === 'Risks 3/3 · Decisions 3/3 · Must read 0/2 · Spot-check 3/3', s);
      await B.ev(`document.querySelector('#pg-state .pg-j[data-j="notRoutine"]').click()`); await sleep(200);
      t.check(`spot-check ${th}: its count jumps to the file`, await B.ev(`(function(){var l=[].find.call(document.querySelectorAll('#budget .b-spot li'),function(l){return /routes\\.ts/.test(l.textContent);}),r=l.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&document.activeElement.closest('li')===l;})()`));
      const md = await B.ev(COPY);
      t.check(`spot-check ${th}: the fix brief lists the file that was not routine`, md.includes('## Skim files that were not routine (1)\n\n- B #2 · `src/api/routes.ts:1`') && !/## Needs fix/.test(md), md);
      await B.ev(`[].find.call(document.querySelectorAll('#budget .b-spot li'),function(l){return /routes\\.ts/.test(l.textContent);}).querySelector('.vd-b[data-vd="ok"]').click()`);
      s = await B.ev(PROG);
      t.check(`spot-check ${th}: every file Routine (and the rest done) reads "Ready to merge", and the warning goes`, s.state === 'Ready to merge' && s.n.endsWith('Spot-check 3/3') && (await B.ev(`document.querySelector('#budget .b-spotwarn').hidden`)), s);
      await t.shot(`spot-${th}`, '#budget');

      // Kept across a reload; the warning comes back with its mark.
      await B.ev(`[].find.call(document.querySelectorAll('#budget .b-spot li'),function(l){return /format\\.ts/.test(l.textContent);}).querySelector('.vd-b[data-vd="no"]').click()`);
      await t.reload(SPOT, { steps: false });
      t.check(`spot-check ${th}: the marks persist across a reload, and so does the warning`, (await B.ev(`document.querySelector('#budget .b-spotwarn').textContent`)) === "1 of 3 sampled skim files wasn't routine — review the skim files of PR A more closely"
        && (await B.ev(PROG)).state === 'Not ready: 1 not routine', await stored());
      await B.ev(`[].find.call(document.querySelectorAll('#budget .b-spot li'),function(l){return /routes\\.ts/.test(l.textContent);}).querySelector('.vd-b[data-vd="no"]').click()`);
      t.check(`spot-check ${th}: two files that were not routine are counted and name both PRs`, (await B.ev(`document.querySelector('#budget .b-spotwarn').textContent`)) === "2 of 3 sampled skim files weren't routine — review the skim files of PR A, B more closely");
      t.noErrors(`spot-check ${th}: no page errors`);
    }

    // The sample is the same for the same branches, and a page without one has none.
    await t.fresh(PAGE, { steps: false });
    t.check('spot-check: a page built with --spot-check 0 has no sample, no Spot-check counter, and no warning', await B.ev(`!document.querySelector('#budget .b-spot')&&!document.querySelector('#budget .b-spotwarn')&&!/Spot-check/.test(document.getElementById('pg-n').textContent)`));
    t.noErrors('spot-check: no page errors without a sample');
  },
};
