'use strict';
// Copied notes as CommonMark: the viewer's mdNote(), cut out of assets/viewer.html, wraps each case's note body in a
// copied-notes document, and micromark renders it. A note body must not break the document's structure (its headings,
// the next note's heading, the text after it), and the code blocks the note means (the note rendered on its own) must
// come out unchanged inside the document. Runs in Node with micromark; no browser.
const fs = require('fs');
const path = require('path');

const CASES = {
  atx: '# Top\nSome text\n## Sub\n###### Six',
  atxIndented: '   # three spaces\n> # quoted\n- # in a list\n1. ## numbered',
  setextEq: 'Title\n===\nmore',
  setextDash: 'Line\n---',
  setextMultiline: 'one\ntwo\n  ===  ',
  dashAfterBlank: 'para\n\n---\n\nnext',
  fenceOpen: '```js\nconst a = 1;\n# not a heading',
  fenceTilde: '~~~~\ncode\n~~~',
  fenceClosed: '```\n# inside code\n```\n# outside',
  inlineBackticks: '``` not a fence `x` ```\n# h',
  htmlComment: '<!-- todo\nstill comment?',
  htmlClosed: '<!-- fine -->\ntext',
  htmlPre: '<pre>\nraw',
  htmlScriptClosed: '<script>x</script>\nok',
  hashNoSpace: '#hashtag\n####### seven',
  quoteFence: '> ```\n> code',
  // Fences in containers, HTML blocks, thematic breaks, CR line endings.
  listItemFence: '1. Run:\n- ```sh\n  # install\n  ```',
  listItemFenceThenHeading: '1. Run:\n- ```sh\n  # install\n  ```\n# outside',
  quotedFenceComment: '> ```py\n> # comment\n> x = 1\n> ```\n# outside',
  quotedFenceOpen: '> ```py\n> # comment',
  listFenceOpen: '- item\n  ```\n  # code',
  listFenceDedent: '- item\n  ```\n  # code\n# outside',
  deepListFence: '10. step\n    ```\n    # code\n    ```\n# outside',
  commentFence: '<!--\n```\n-->\n# heading',
  divFence: '<div>\n```\n</div>\n\n# h',
  listComment: '- <!-- open\n  # x',
  quoteComment: '> <!-- open\n> # x',
  atxThenBreak: '# H\n---',
  fenceThenBreak: '```\nx\n```\n---',
  listThenBreak: '- a\n---',
  listUnderline: '- a\n  ===',
  quoteUnderline: '> b\n> ---',
  lazyEq: '> a\nlazy\n===',
  crlf: 'Title\r\n===\r\n# c\rd\r\n',
  crlfFence: '```\r\n# in\r\n```\r\n# out',
  nestedQuoteList: '> - ```\n>   # code\n>   ```\n> # q',
  tabIndent: '-\tTitle\n\t===',
  ordered2: 'a\n2. b\n===',
};

function loadMdNote(viewer) {
  const html = fs.readFileSync(viewer, 'utf8');
  const start = html.indexOf('  var MD_Q='), fstart = html.indexOf('function mdNote(text){');
  if (start < 0 || fstart < 0) throw new Error('mdNote not found in ' + viewer);
  let depth = 0, end = -1;
  for (let i = html.indexOf('{', fstart); i < html.length; i++) { if (html[i] === '{') depth++; else if (html[i] === '}' && --depth === 0) { end = i + 1; break; } }
  return new Function(html.slice(start, end) + '\nreturn mdNote;')();
}

module.exports = {
  name: 'mdnote',
  weight: 0, // seconds on a laptop, to start the longest suites first
  needs: ['micromark'],
  async run(t) {
    const micromark = t.micromark;
    const mdNote = loadMdNote(path.join(t.root, 'skills', 'pr-review-map', 'assets', 'viewer.html'));
    const codes = (s) => [...s.matchAll(/<pre><code[^>]*>([\s\S]*?)<\/code><\/pre>/g)].map((m) => m[1].replace(/\n$/, ''));
    for (const [name, text] of Object.entries(CASES)) {
      const body = mdNote(text);
      const doc = `# Notes: T\n\n## Issue (1): fix it\n\n### PR A\n\n#### 1. \`a.ts:1\` · new\n\n${body}\n\n#### 2. \`b.ts:2\` · new\n\nAFTER-MARK\n`;
      const out = micromark(doc, { allowDangerousHtml: true });
      const top = [...out.matchAll(/<h([1-6])>([\s\S]*?)<\/h\1>/g)].map((m) => [+m[1], m[2]]).filter((h) => h[0] <= 4);
      const structure = top.length === 5 && top[4][1].includes('2.') && /<p>AFTER-MARK<\/p>/.test(out)
        && !/<h[1-4]>[^<]*(Top|Sub|Title|Line|three|quoted|list|numbered|outside|one|heading|install|comment|code|lazy|\bH\b|\bh\b|\bb\b|\ba\b)/.test(out);
      // Code blocks: the note rendered alone vs. the note's part of the document.
      const part = out.slice(out.indexOf('</h4>') + 5, out.lastIndexOf('<h4>'));
      const want = codes(micromark(text.replace(/\r\n?/g, '\n'), { allowDangerousHtml: true }));
      const got = codes(part);
      t.check(`${name}: the note keeps the copied document's structure and its own code blocks`, structure && JSON.stringify(want) === JSON.stringify(got), { structure, want, got, body, out });
    }
  },
};
