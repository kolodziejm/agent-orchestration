'use strict';
// Runs the pr-review-map browser checks: builds the synthetic fixtures (fixtures.py) into a temporary directory, then
// runs each suite in its own headless Chrome, up to --jobs (default 4) at once, and prints one line per suite plus
// every failure. A suite whose needs are missing is skipped with the reason: Chrome (and Node 22+ to drive it),
// network access to cdnjs (the viewer loads highlight.js from it; without it the other suites run offline), or
// micromark (npm ci in this directory). Exit 0 when every check that ran passed, including when nothing could run;
// 1 on a failure; 2 on a usage or fixture-build error.
//
//   node run.js [--only core,hubs] [--jobs N] [--verbose] [--shots DIR] [--keep] [--offline]
//
// --verbose prints every check, --shots writes screenshots for eyeballing, --keep keeps the temporary directory,
// --offline runs as if cdnjs were unreachable. Environment: PYTHON (default python3) runs the fixture builder and the
// skill's scripts; CHROME names the browser binary (empty or not executable: no browser, so the browser suites skip).
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const SUITES = ['core', 'hubs', 'sfc', 'addon', 'refresh', 'security', 'mdnote', 'plan', 'workspace', 'wsmap', 'theme'];
const ROOT = path.resolve(__dirname, '..', '..');

function usage(msg) {
  console.error(`${msg}\nusage: run.js [--only ${SUITES.join(',')}] [--jobs N] [--verbose] [--shots DIR] [--keep] [--offline]`);
  process.exit(2);
}

function parseArgs(argv) {
  const o = { only: null, verbose: false, shots: null, keep: false, jobs: 4, offline: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--verbose' || a === '-v') o.verbose = true;
    else if (a === '--keep') o.keep = true;
    else if (a === '--offline') o.offline = true;
    else if (a === '--jobs' || a === '-j') { o.jobs = +argv[++i]; if (!(o.jobs >= 1)) usage('--jobs needs a number of 1 or more'); }
    else if (a === '--only') o.only = (argv[++i] || '').split(',').filter(Boolean);
    else if (a === '--shots') o.shots = path.resolve(argv[++i] || usage('--shots needs a directory'));
    else usage(`unknown argument ${a}`);
  }
  for (const s of o.only || []) if (!SUITES.includes(s)) usage(`unknown suite ${s}`);
  return o;
}

// micromark (CommonMark) from this directory's node_modules (npm ci here), else anywhere Node resolves it from here.
async function loadMicromark() {
  try {
    const resolved = require.resolve('micromark', { paths: [__dirname] });
    return (await import(require('url').pathToFileURL(resolved).href)).micromark || null;
  } catch (e) { return null; }
}

(async () => {
  const opts = parseArgs(process.argv.slice(2));
  const start = Date.now();
  const { findChrome, cdnReachable, launch, Suite } = require('./lib');
  const have = { chrome: null, micromark: null, cdn: false };
  const why = {};
  if (typeof WebSocket !== 'function') why.chrome = `Node ${process.version} has no built-in WebSocket (Node 22 or newer drives Chrome)`;
  else {
    const c = findChrome();
    if (c.path) have.chrome = c.path; else why.chrome = c.why;
  }
  if (have.chrome) {
    have.cdn = !opts.offline && await cdnReachable();
    if (!have.cdn) why.cdn = opts.offline ? 'run with --offline' : 'cdnjs.cloudflare.com is unreachable (the viewer loads highlight.js from it)';
  }
  have.micromark = await loadMicromark();
  if (!have.micromark) why.micromark = 'micromark is not installed (npm ci in tests/pr_review_map_browser)';

  const wanted = opts.only || SUITES;
  const runnable = [], skipped = [];
  for (const name of wanted) {
    const suite = require(`./${name}`);
    const missing = suite.needs.filter((n) => !have[n]);
    if (missing.length) skipped.push([name, missing.map((n) => why[n]).filter(Boolean).join('; ')]); // cdn has no reason without Chrome
    else runnable.push(suite);
  }
  for (const [name, reason] of skipped) console.log(`skipped ${name}: ${reason}`);
  if (!runnable.length) { console.log('pr-review-map browser checks: skipped (nothing could run)'); return process.exit(0); }

  const python = process.env.PYTHON || 'python3';
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'pr-review-map-browser-'));
  const fixtures = path.join(work, 'fixtures');
  if (opts.shots) fs.mkdirSync(opts.shots, { recursive: true });
  let failed = 0, passed = 0;
  if (runnable.some((s) => s.needs.includes('chrome'))) {
    try {
      execFileSync(python, [path.join(__dirname, 'fixtures.py'), 'build', fixtures], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) {
      console.error(`fixtures.py build failed:\n${e.stdout || ''}${e.stderr || e.message}`);
      fs.rmSync(work, { recursive: true, force: true });
      return process.exit(2);
    }
    console.log(`fixtures built in ${((Date.now() - start) / 1000).toFixed(1)}s (Chrome: ${have.chrome}${have.cdn ? '' : ', offline'})`);
  }
  try {
    const runOne = async (suite) => {
      const t0 = Date.now();
      const dir = fs.mkdtempSync(path.join(work, suite.name + '-'));
      const t = new Suite(suite.name, { fixtures, work: dir, python, root: ROOT, shots: opts.shots, verbose: opts.verbose, micromark: have.micromark, cdn: have.cdn });
      let B = null;
      try {
        if (suite.needs.includes('chrome')) t.B = B = await launch(have.chrome, dir, { offline: !have.cdn });
        await suite.run(t);
      } catch (e) {
        t.failures.push('exception: ' + (e && e.stack || e));
        console.log(`  FAIL ${suite.name}: exception ${e && e.stack || e}`);
      } finally {
        if (B) await B.close();
      }
      passed += t.passed; failed += t.failures.length;
      console.log(`${suite.name.padEnd(9)} ${String(t.passed).padStart(3)} passed, ${t.failures.length} failed${t.skips.length ? `, ${t.skips.length} skipped` : ''}  (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
      for (const s of t.skips) console.log(`  skipped: ${s}`);
    };
    // Each suite has its own Chrome and directory, so up to --jobs of them run at once (longest first).
    const queue = [...runnable].sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1));
    await Promise.all(Array.from({ length: Math.min(opts.jobs, queue.length) }, async () => { while (queue.length) await runOne(queue.shift()); }));
  } finally {
    if (opts.keep) console.log(`kept ${work}`);
    else fs.rmSync(work, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
  console.log(`pr-review-map browser checks: ${passed} passed, ${failed} failed${skipped.length ? `, ${skipped.length} suite(s) skipped` : ''} in ${((Date.now() - start) / 1000).toFixed(0)}s`);
  process.exit(failed ? 1 : 0);
})();
