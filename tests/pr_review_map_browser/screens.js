'use strict';
// REQUIREMENT: before/after screenshots supplement the brief's "what changes for users". When the page was built with
// screens.json (assemble.py --screens), a "Screens" block follows that list in the brief (at the top of the brief when the
// narrative has no such list): one card per pair with its title, PR chip, a "New" badge when there is no before and "Removed"
// when there is no after, the optional note, and the Before and After thumbnails side by side (stacked below 700 px); a pair
// taken at a tip the PR has left says so. A thumbnail opens a full-window dialog (role dialog, aria-modal, the page behind
// inert, a focus trap): the image fitted to the window, a Before/After toggle (button and the b key), "Side by side" on wide
// windows, the arrow keys and buttons between pairs with a "3 / 8" counter, Esc or Back closes it and the scroll position and
// the focus on the thumbnail come back, and no other shortcut of the page fires meanwhile. Images load lazily and carry alt
// text from the title and the side. In light and dark.
const { sleep } = require('./lib');

module.exports = {
  name: 'screens',
  weight: 4,
  needs: ['chrome'],
  async run(t) {
    const B = t.B;
    const PAGE = t.url(t.fixtures, 'screens', 'page', 'review.html');
    const PLAIN = t.url(t.fixtures, 'screens', 'plain', 'review.html');
    const STALE = t.url(t.fixtures, 'screens', 'stale', 'review.html');
    const BLOCK = `(function(){var b=document.getElementById('screens'),users=document.querySelector('#brief ul.brief-users'),prog=document.getElementById('vd-prog');
      var pairs=[].map.call(document.querySelectorAll('#screens .scr-pair'),function(li){
        var th=[].map.call(li.querySelectorAll('.scr-th'),function(b){var i=b.querySelector('img'),r=b.getBoundingClientRect();return {s:b.dataset.s,alt:i.alt,lazy:i.loading,w:i.naturalWidth,label:b.getAttribute('aria-label'),x:Math.round(r.left),y:Math.round(r.top)};});
        return {title:li.querySelector('.scr-t').textContent,chip:li.querySelector('.who').textContent,chipCls:li.querySelector('.who').className,badges:[].map.call(li.querySelectorAll('.scr-bd'),function(e){return e.textContent;}),
          note:(li.querySelector('.scr-note')||{}).textContent||null,stale:(li.querySelector('.scr-stale')||{}).textContent||null,none:[].map.call(li.querySelectorAll('.scr-none'),function(e){return e.textContent;}),
          th:th,mobile:li.classList.contains('mobile'),vp:(li.querySelector('.scr-vp')||{}).textContent||null,cols:getComputedStyle(li.querySelector('.scr-pics')).gridTemplateColumns.split(' ').length};});
      return b?{inBrief:!!b.closest('#brief'),afterUsers:!!users&&b.previousElementSibling===users,afterProg:!!prog&&b.previousElementSibling===prog,heading:b.querySelector('h3').textContent,role:b.getAttribute('role'),
        labelled:b.getAttribute('aria-labelledby'),pairs:pairs,hs:T.hscroll()}:null;})()`;
    const DLG = `(function(){var d=document.getElementById('scd');if(!d)return null;var a=document.activeElement,fig=function(s){return d.querySelector('.scd-fig[data-s='+s+']');},vis=function(s){var f=fig(s);return !!f&&!f.hidden&&f.getClientRects().length>0;};
      var imgs={};['before','after'].forEach(function(s){var i=fig(s).querySelector('img'),b=fig(s).querySelector('.scd-box').getBoundingClientRect(),r=i.getBoundingClientRect();
        imgs[s]={vis:vis(s),shown:!i.hidden,alt:i.alt,nat:i.naturalWidth,w:Math.round(r.width),h:Math.round(r.height),fits:r.width<=b.width+0.5&&r.height<=b.height+0.5&&r.left>=b.left-0.5&&r.top>=b.top-0.5,none:getComputedStyle(fig(s).querySelector('.scr-none')).display!=='none',
        x:Math.round(fig(s).getBoundingClientRect().left),y:Math.round(fig(s).getBoundingClientRect().top)};});
      var sb=document.getElementById('scd-sbs'),pressed=function(s){return d.querySelector('.scd-tog [data-s='+s+']').getAttribute('aria-pressed');},dis=function(s){return d.querySelector('.scd-tog [data-s='+s+']').getAttribute('aria-disabled');};
      return {open:!d.hidden,role:d.getAttribute('role'),modal:d.getAttribute('aria-modal'),labelledby:d.getAttribute('aria-labelledby'),title:document.getElementById('scd-t').textContent,pos:d.querySelector('.scd-pos').textContent,
        badge:d.querySelector('.scd-head .scr-bd').hidden?'':d.querySelector('.scd-head .scr-bd').textContent,inDlg:!!a&&d.contains(a),active:a?(a.id||a.tagName+'.'+a.className):'',imgs:imgs,sbs:d.classList.contains('sbs'),sbsBtn:{hidden:sb.hidden,pressed:sb.getAttribute('aria-pressed')},
        before:{pressed:pressed('before'),disabled:dis('before')},after:{pressed:pressed('after'),disabled:dis('after')},prev:d.querySelector('#scd-prev').getAttribute('aria-disabled'),next:d.querySelector('#scd-next').getAttribute('aria-disabled'),
        meta:d.querySelector('.scd-meta').textContent,note:d.querySelector('.scd-note').textContent,wrapInert:document.querySelector('.wrap').hasAttribute('inert'),lock:document.documentElement.classList.contains('scd-lock'),
        sy:Math.round(scrollY),state:history.state,ws:document.getElementById('graph').classList.contains('ws'),
        box:(function(){var r=d.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)};})(),bg:getComputedStyle(d).backgroundColor,pageBg:getComputedStyle(document.body).backgroundColor};})()`;
    const THUMB = (i, side) => `document.querySelector('#screens .scr-pair[data-i="${i}"] .scr-th[data-s="${side}"]')`;
    const focusIs = (i, side) => B.ev(`document.activeElement===${THUMB(i, side)}`);
    let s, d;

    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';

      // The block in the brief, after "What changes for users".
      await t.fresh(PAGE, { steps: false, dark });
      s = await B.ev(BLOCK);
      t.check(`screens ${th}: the Screens block sits in the brief right after "What changes for users"`, s && s.inBrief && s.afterUsers && s.heading === 'Screens' && s.role === 'region' && s.labelled === 'screens-h', s);
      t.check(`screens ${th}: one card per pair, with its title and PR chip`, s.pairs.map((p) => p.title).join('|') === 'First-run welcome|Settings on a phone|Billing tab'
        && s.pairs.every((p) => p.chip === 'O' && /\bc-O\b/.test(p.chipCls)), s.pairs);
      t.check(`screens ${th}: only the pair with no before is badged New, the viewport shows, and the note is one muted line`, s.pairs.map((p) => p.badges.join('+')).join('|') === '||New'
        && s.pairs[2].none.join() === 'No before: a new screen' && s.pairs[0].vp === 'Desktop' && s.pairs[1].vp === 'Mobile' && s.pairs[1].note === 'The billing tab sits under Profile.' && s.pairs[0].note === null && s.pairs[0].stale === null, s.pairs);
      t.check(`screens ${th}: thumbnails are lazy, have alt text from the title and the side, and Before stands left of After`, s.pairs[0].th.length === 2 && s.pairs[2].th.length === 1
        && s.pairs.every((p) => p.th.every((x) => x.lazy === 'lazy' && x.alt === `${p.title} – ${x.s === 'before' ? 'Before' : 'After'}` && /open full size/.test(x.label)))
        && s.pairs[0].th[0].x < s.pairs[0].th[1].x && s.pairs[0].th[0].y === s.pairs[0].th[1].y && s.pairs[1].mobile && s.hs === 0, s.pairs[0]);
      await B.ev(`document.getElementById('screens').scrollIntoView()`); await sleep(500);
      t.check(`screens ${th}: the images decode`, await B.ev(`[].every.call(document.querySelectorAll('#screens img'),function(i){return i.naturalWidth>0;})`));
      await t.shot(`block-${th}`, '#screens');

      // The dialog: the Before thumbnail of the first pair, from a scrolled page.
      await B.ev(`window.scrollTo(0,0);document.getElementById('screens').scrollIntoView();window.scrollBy(0,-40)`); await sleep(200);
      const y0 = await B.ev('Math.round(scrollY)');
      await B.ev(`${THUMB(0, 'before')}.focus();${THUMB(0, 'before')}.click()`); await sleep(300);
      d = await B.ev(DLG);
      t.check(`screens ${th}: a thumbnail opens a modal dialog on its pair and side, the page behind inert and locked, focus inside, one history entry`, d && d.open && d.role === 'dialog' && d.modal === 'true' && d.labelledby === 'scd-t'
        && d.title === 'First-run welcome' && d.pos === '1 / 3' && d.imgs.before.vis && !d.imgs.after.vis && d.before.pressed === 'true' && d.after.pressed === 'false' && d.wrapInert && d.lock && d.inDlg && d.state && d.state.prmSc === 1
        && d.meta === 'Desktop · from a preview', d);
      t.check(`screens ${th}: the image is shown at its own size, fitted inside the window, with alt text`, d.imgs.before.shown && d.imgs.before.nat === 640 && d.imgs.before.w <= 640 && d.imgs.before.w > 100 && d.imgs.before.fits
        && d.imgs.before.alt === 'First-run welcome – Before' && d.box.w === 1440 && d.box.h === 900, d.imgs.before);
      t.check(`screens ${th}: the dialog is painted with the page's own theme tokens`, d.bg === d.pageBg, [d.bg, d.pageBg]);
      await t.shot(`dialog-${th}`);

      // b flips Before and After; the toggle buttons do the same.
      await B.key('b'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: b shows the After image and marks it on the toggle`, d.imgs.after.vis && !d.imgs.before.vis && d.after.pressed === 'true' && d.before.pressed === 'false' && d.imgs.after.alt === 'First-run welcome – After', d);
      await B.ev(`document.querySelector('#scd .scd-tog [data-s=before]').click()`); await sleep(100); d = await B.ev(DLG);
      t.check(`screens ${th}: the Before button shows the before again`, d.imgs.before.vis && !d.imgs.after.vis, d);
      await B.key('B'); await sleep(100); d = await B.ev(DLG);
      t.check(`screens ${th}: B works as b`, d.imgs.after.vis, d);

      // Arrow keys and buttons between pairs; a pair with no before opens on its After.
      await B.key('ArrowRight'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: → goes to the next pair and keeps the side, the counter says 2 / 3, and the note shows`, d.title === 'Settings on a phone' && d.pos === '2 / 3' && d.imgs.after.vis && d.note === 'The billing tab sits under Profile.'
        && d.meta === 'Mobile · run locally' && d.imgs.after.nat === 390 && d.imgs.after.fits && d.prev === 'false' && d.next === 'false', d);
      await B.ev(`document.getElementById('scd-next').click()`); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: Next on a new screen shows its After, badges it New, and disables Before`, d.title === 'Billing tab' && d.pos === '3 / 3' && d.imgs.after.vis && !d.imgs.before.vis && d.badge === 'New'
        && d.before.disabled === 'true' && d.after.disabled === 'false' && d.next === 'true', d);
      await B.key('b'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: b on a new screen stays on After`, d.imgs.after.vis && !d.imgs.before.vis && d.after.pressed === 'true', d);
      await B.key('ArrowRight'); await sleep(100);
      t.check(`screens ${th}: → at the last pair stays there`, (await B.ev(DLG)).pos === '3 / 3');
      await B.key('ArrowLeft'); await B.key('ArrowLeft'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: ← goes back to the first pair, where Previous is off`, d.pos === '1 / 3' && d.prev === 'true' && d.title === 'First-run welcome', d);
      await B.key('ArrowLeft'); await sleep(100);
      t.check(`screens ${th}: ← at the first pair stays there`, (await B.ev(DLG)).pos === '1 / 3');

      // Side by side on a wide window.
      await B.ev(`document.getElementById('scd-sbs').click()`); await sleep(200); d = await B.ev(DLG);
      t.check(`screens ${th}: "Side by side" shows both images, Before on the left, at the same height`, d.sbs && !d.imgs.before.none && !d.imgs.after.none && d.imgs.before.vis && d.imgs.after.vis && d.imgs.before.x < d.imgs.after.x && d.imgs.before.y === d.imgs.after.y
        && d.sbsBtn.pressed === 'true' && d.before.pressed === 'false' && d.after.pressed === 'false' && d.imgs.before.fits && d.imgs.after.fits, d);
      await t.shot(`dialog-sbs-${th}`);
      await B.key('ArrowRight'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: side by side stays while moving between pairs`, d.sbs && d.pos === '2 / 3' && d.imgs.before.vis && d.imgs.after.vis, d);
      await B.key('ArrowRight'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: a new screen side by side shows its missing before as such`, d.pos === '3 / 3' && d.imgs.before.vis && d.imgs.before.none && !d.imgs.before.shown && d.imgs.after.shown, d);
      await B.key('s'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: s leaves side by side`, !d.sbs && d.sbsBtn.pressed === 'false' && d.imgs.after.vis && !d.imgs.before.vis, d);
      await B.key('s'); await sleep(100);
      t.check(`screens ${th}: s enters it again`, (await B.ev(DLG)).sbs);
      await B.key('b'); await sleep(100); d = await B.ev(DLG);
      t.check(`screens ${th}: b from side by side goes back to one image`, !d.sbs && (d.imgs.before.vis !== d.imgs.after.vis), d);

      // The page's own shortcuts do not fire, and Tab stays in the dialog.
      await B.key('f'); await B.key('j'); await B.key('x'); await sleep(150); d = await B.ev(DLG);
      t.check(`screens ${th}: the page's own keys (f, j, x) do nothing while the dialog is open`, d.open && !d.ws && d.state && d.state.prmSc === 1, d);
      let outside = 0;
      for (let i = 0; i < 12; i++) { await B.key('Tab'); if (!(await B.ev(DLG)).inDlg) outside++; }
      for (let i = 0; i < 12; i++) { await B.key('Tab', 8); if (!(await B.ev(DLG)).inDlg) outside++; }
      t.check(`screens ${th}: Tab and Shift+Tab never leave the dialog`, outside === 0, outside);

      // Esc closes: scroll, focus, inert, and the history entry come back.
      await B.key('Escape'); await sleep(500); d = await B.ev(DLG);
      t.check(`screens ${th}: Esc closes it, the page is live again at the same scroll position, and the focus is back on the thumbnail`, !d.open && !d.wrapInert && !d.lock && d.sy === y0 && d.state === null && await focusIs(0, 'before'), [d.open, d.wrapInert, d.lock, d.sy, y0, d.state]);

      // Back closes it too.
      await B.ev(`${THUMB(1, 'after')}.focus();${THUMB(1, 'after')}.click()`); await sleep(300); d = await B.ev(DLG);
      t.check(`screens ${th}: opening on an After thumbnail shows that image`, d.open && d.title === 'Settings on a phone' && d.imgs.after.vis && !d.imgs.before.vis && d.pos === '2 / 3', d);
      await B.ev('history.back()'); await sleep(500); d = await B.ev(DLG);
      t.check(`screens ${th}: Back closes it, with the scroll position and the focus on its thumbnail`, !d.open && !d.wrapInert && d.sy === y0 && d.state === null && await focusIs(1, 'after'), [d.open, d.sy, d.state]);
      await B.ev(`${THUMB(2, 'after')}.click()`); await sleep(300);
      await B.ev(`document.getElementById('scd-x').click()`); await sleep(400); d = await B.ev(DLG);
      t.check(`screens ${th}: the Close button closes it and takes its history entry off`, !d.open && d.state === null && await focusIs(2, 'after'), d);
      t.noErrors(`screens ${th}: no page errors`);

      // The page without the "What changes" list: the block leads the brief; a removed screen.
      await t.fresh(PLAIN, { steps: false, dark });
      s = await B.ev(BLOCK);
      t.check(`screens ${th}: with no "What changes for users" list the block goes at the top of the brief, after the progress line`, s && s.inBrief && !s.afterUsers && s.afterProg, s && [s.inBrief, s.afterProg]);
      t.check(`screens ${th}: a pair with no after is badged Removed and says so`, s.pairs[1].badges.join() === 'Removed' && s.pairs[1].none.join() === 'No after: a removed screen' && s.pairs[1].th.length === 1 && s.pairs[1].th[0].s === 'before', s.pairs[1]);
      await B.ev(`${THUMB(1, 'before')}.click()`); await sleep(300); d = await B.ev(DLG);
      t.check(`screens ${th}: a removed screen opens on its Before with After disabled and the badge`, d.open && d.imgs.before.vis && d.badge === 'Removed' && d.after.disabled === 'true', d);
      await B.key('b'); await sleep(100);
      t.check(`screens ${th}: b on a removed screen stays on Before`, (await B.ev(DLG)).imgs.before.vis);
      await B.key('Escape'); await sleep(300);

      // A pair taken at an older tip says so, in the block and in the dialog.
      await t.fresh(STALE, { steps: false, dark });
      s = await B.ev(BLOCK);
      t.check(`screens ${th}: a pair taken at a tip the PR has left says "taken at 1234567, code changed since"; a current pair does not`, s.pairs[0].stale === 'taken at 1234567, code changed since' && s.pairs[1].stale === null, s.pairs.map((p) => p.stale));
      await B.ev(`${THUMB(0, 'after')}.click()`); await sleep(300); d = await B.ev(DLG);
      t.check(`screens ${th}: the dialog carries the same notice`, /taken at 1234567, code changed since/.test(d.meta), d.meta);
      await B.key('Escape'); await sleep(300);
    }

    // Layout by width: stacked below 700 px, the dialog without "Side by side" below 900 px.
    for (const dark of [false, true]) {
      const th = dark ? 'dark' : 'light';
      await t.fresh(PAGE, { steps: false, dark, width: 600, height: 900 });
      s = await B.ev(BLOCK);
      t.check(`screens ${th}: at 600 px the thumbnails stack (After below Before) without a horizontal scroll`, s.pairs[0].th[1].y > s.pairs[0].th[0].y && s.pairs[0].th[0].x === s.pairs[0].th[1].x && s.pairs[0].cols === 1 && s.hs === 0, [s.pairs[0].th, s.pairs[0].cols, s.hs]);
      await t.shot(`narrow-${th}`, '#screens', 2800);
      await B.ev(`${THUMB(0, 'before')}.click()`); await sleep(300); d = await B.ev(DLG);
      t.check(`screens ${th}: at 600 px the dialog fits the window and has no "Side by side"`, d.open && d.sbsBtn.hidden && d.imgs.before.fits && d.box.w === 600, d);
      await B.key('s'); await sleep(100);
      t.check(`screens ${th}: s does nothing there`, !(await B.ev(DLG)).sbs);
      await t.shot(`dialog-narrow-${th}`);
      await B.key('Escape'); await sleep(300);
      await t.fresh(PAGE, { steps: false, dark, width: 800, height: 900 });
      s = await B.ev(BLOCK);
      t.check(`screens ${th}: at 800 px the pairs sit side by side again`, s.pairs[0].cols === 2 && s.pairs[0].th[0].y === s.pairs[0].th[1].y, s.pairs[0].cols);
      await B.ev(`${THUMB(0, 'before')}.click()`); await sleep(300);
      t.check(`screens ${th}: at 800 px "Side by side" is still off the dialog`, (await B.ev(DLG)).sbsBtn.hidden);
      await B.key('Escape'); await sleep(300);
      t.noErrors(`screens ${th}: no page errors at the narrow widths`);
    }
  },
};
