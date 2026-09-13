import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "adapters/pi/extensions/git-read.ts"


FAKE_CHILD = r'''
import { EventEmitter } from "node:events";

export const calls = [];

function chunk(value) {
  if (typeof value === "string") return Buffer.from(value, "utf8");
  if (value && typeof value === "object" && value.repeat !== undefined) {
    return Buffer.from(String(value.value ?? "").repeat(value.repeat), "utf8");
  }
  if (value && typeof value === "object" && value.bytes !== undefined) {
    return Buffer.alloc(value.bytes, value.value ?? 120);
  }
  return Buffer.from(String(value ?? ""), "utf8");
}

function emitChunks(stream, values) {
  for (const value of values ?? []) stream.emit("data", chunk(value));
}

export function spawn(file, args, options) {
  const plan = globalThis.__gitPlans.shift() ?? {};
  if (plan.throw) throw new Error("synthetic spawn failure");
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  let closed = false;
  const entry = {
    file,
    args: [...args],
    options: { ...options, env: { ...options.env }, stdio: [...options.stdio] },
    kills: [],
    child,
  };
  calls.push(entry);
  const close = (code = 0, signal = null) => {
    if (closed) return;
    closed = true;
    child.emit("close", code, signal);
  };
  child.kill = (signal) => {
    entry.kills.push(signal);
    if (signal === "SIGTERM" && plan.errorAfterSigterm) {
      queueMicrotask(() => child.emit("error", new Error("synthetic termination error")));
    }
    if (plan.closeOnKill !== false) setTimeout(() => close(plan.killExitCode ?? null, signal), 0);
    return true;
  };
  if (plan.error) {
    queueMicrotask(() => child.emit("error", new Error("synthetic child error")));
    return child;
  }
  if (!plan.hold) {
    queueMicrotask(() => {
      emitChunks(child.stdout, plan.stdoutChunks ?? (plan.stdout === undefined ? [] : [plan.stdout]));
      emitChunks(child.stderr, plan.stderrChunks ?? (plan.stderr === undefined ? [] : [plan.stderr]));
      if (plan.close !== false) close(plan.exitCode ?? 0, null);
    });
  }
  return child;
}

export function snapshot() {
  return calls.map((entry) => ({
    file: entry.file,
    args: entry.args,
    options: entry.options,
    kills: entry.kills,
    stdoutListeners: entry.child.stdout.listenerCount("data"),
    stderrListeners: entry.child.stderr.listenerCount("data"),
  }));
}
'''


TYPEBOX_STUB = r'''
function withOptions(value, options = {}) {
  return { ...value, ...options };
}
export const Type = {
  String: (options = {}) => withOptions({ type: "string" }, options),
  Array: (items, options = {}) => withOptions({ type: "array", items }, options),
  Optional: (schema) => ({ ...schema, optional: true }),
  Object: (properties, options = {}) => ({
    type: "object",
    properties,
    required: Object.keys(properties).filter((key) => !properties[key].optional),
    ...options,
  }),
};
export function StringEnum(values, options = {}) {
  return { type: "string", enum: [...values], ...options };
}
'''


class PiGitReadTests(unittest.TestCase):
    def _fixture(self, *, real_git=False):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / ".git").mkdir()
        extension = root / "extensions" / "git-read.mjs"
        extension.parent.mkdir(parents=True)
        source = SOURCE.read_text()
        if not real_git:
            source = source.replace(
                'import { spawn } from "node:child_process";',
                'import { spawn } from "./fake-child.mjs";',
            )
            (extension.parent / "fake-child.mjs").write_text(FAKE_CHILD)
        extension.write_text(source)
        package = root / "node_modules" / "@earendil-works" / "pi-ai"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"type": "module", "exports": "./index.mjs"}))
        (package / "index.mjs").write_text(TYPEBOX_STUB)
        return directory, root, extension

    def _run(self, request, plans, *, abort=False, timeout=False):
        directory, root, extension = self._fixture()
        self.addCleanup(directory.cleanup)
        script = f'''
const originalSetTimeout = globalThis.setTimeout;
if ({json.dumps(timeout)}) {{
  globalThis.setTimeout = (callback, milliseconds, ...args) =>
    originalSetTimeout(callback, milliseconds >= 10000 ? 0 : milliseconds, ...args);
}}
const module = await import({json.dumps(extension.as_uri())});
const fake = await import({json.dumps((root / "extensions/fake-child.mjs").as_uri())});
'''
        plans_json = json.dumps(plans).replace("/synthetic/worktree", str(root))
        script += f'''
globalThis.__gitPlans = {plans_json};
const registered = {{}};
module.default({{ registerTool(tool) {{ registered.tool = tool; }} }});
const controller = new AbortController();
if ({json.dumps(abort)}) originalSetTimeout(() => controller.abort(), 0);
const result = await registered.tool.execute("test", {json.dumps(request)}, controller.signal, undefined, {{ cwd: {json.dumps(str(root))} }});
console.log(JSON.stringify({{ result, calls: fake.snapshot() }}));
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def _run_real(self, repo, requests):
        directory, root, extension = self._fixture(real_git=True)
        self.addCleanup(directory.cleanup)
        script = f'''
const module = await import({json.dumps(extension.as_uri())});
const registered = {{}};
module.default({{ registerTool(tool) {{ registered.tool = tool; }} }});
const controller = new AbortController();
const results = [];
for (const request of {json.dumps(requests)}) {{
  results.push(await registered.tool.execute("test", request, controller.signal, undefined, {{ cwd: {json.dumps(str(repo))} }}));
}}
console.log(JSON.stringify(results));
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def _plans(self, root, final=None):
        return [
            {"stdout": "true\n"},
            {"stdout": f"{root}\n"},
            final or {"stdout": ""},
        ]

    def test_schema_is_small_and_tool_is_named_git_read(self):
        """REGRESSION CONTRACT: model input cannot select arbitrary commands, paths, or unbounded arrays."""
        directory, root, extension = self._fixture()
        self.addCleanup(directory.cleanup)
        script = f'''
const module = await import({json.dumps(extension.as_uri())});
const registered = {{}};
module.default({{ registerTool(tool) {{ registered.tool = tool; }} }});
console.log(JSON.stringify({{ name: registered.tool.name, schema: registered.tool.parameters }}));
'''
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["name"], "git_read")
        schema = payload["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["action"]["enum"], ["status", "diff"])
        self.assertEqual(schema["properties"]["target"]["enum"], ["worktree", "staged", "range"])
        self.assertEqual(schema["properties"]["view"]["enum"], ["patch", "stat", "name-status"])
        self.assertEqual(schema["properties"]["paths"]["maxItems"], 32)
        self.assertTrue(schema["properties"]["paths"]["uniqueItems"])
        self.assertEqual(schema["properties"]["paths"]["items"]["maxLength"], 512)
        self.assertEqual(schema["properties"]["base"]["maxLength"], 128)
        self.assertEqual(schema["properties"]["head"]["maxLength"], 128)

    def test_status_uses_literal_git_argv_fixed_environment_and_targeted_paths(self):
        """REGRESSION CONTRACT: explorer Git reads cannot become shell commands or escape the worktree path boundary."""
        root = "/synthetic/worktree"
        payload = self._run(
            {"action": "status", "paths": ["src/main.ts", "@README.md"]},
            self._plans(root, {"stdout": " M src/main.ts\0?? README.md\0"}),
        )
        self.assertFalse(payload["result"].get("isError", False))
        self.assertEqual(json.loads(payload["result"]["content"][0]["text"]), [
            {"index": " ", "worktree": "M", "path": "src/main.ts"},
            {"index": "?", "worktree": "?", "path": "README.md"},
        ])
        self.assertEqual(len(payload["calls"]), 3)
        for call in payload["calls"]:
            self.assertEqual(call["file"], "git")
            self.assertIsInstance(call["args"], list)
            self.assertFalse(call["options"]["shell"])
            self.assertTrue(call["options"]["cwd"])
            self.assertEqual(call["options"]["stdio"], ["ignore", "pipe", "pipe"])
            self.assertNotIn("GIT_READ_REQUEST", call["options"]["env"])
            self.assertEqual(call["options"]["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(call["options"]["env"]["GIT_NO_LAZY_FETCH"], "1")
        final = payload["calls"][-1]["args"]
        self.assertIn("status", final)
        self.assertIn("src/main.ts", final)
        self.assertIn("README.md", final)
        self.assertIn("--literal-pathspecs", final)
        self.assertNotIn(":(top,literal)src/main.ts", final)
        self.assertEqual({arg for arg in final if arg in {"rev-parse", "status", "diff"}}, {"status"})
        self.assertEqual(len({call["options"]["cwd"] for call in payload["calls"]}), 1)

    def test_git_reported_ancestor_root_cannot_widen_the_trusted_marker_boundary(self):
        """REGRESSION CONTRACT: repository-local core.worktree settings cannot make Git read outside the opened project."""
        root = "/synthetic/worktree"
        payload = self._run(
            {"action": "status"},
            [
                {"stdout": "true\n"},
                {"stdout": f"{root}/..\n"},
            ],
        )
        self.assertTrue(payload["result"]["isError"])
        self.assertEqual(payload["result"]["details"]["error"], "outside-worktree")
        self.assertEqual(len(payload["calls"]), 2)

    def test_scoped_paths_use_real_git_literal_semantics_in_regular_and_linked_worktrees(self):
        """REGRESSION CONTRACT: fixed literal mode must select a real bracketed path in both worktree marker forms."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = Path(directory.name) / "repo"
        repo.mkdir()
        environment = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }

        def git(*args, cwd=repo):
            return subprocess.run(
                ["git", *args],
                cwd=cwd,
                env={**environment},
                text=True,
                capture_output=True,
                check=True,
            )

        git("init")
        (repo / "src").mkdir()
        tracked = repo / "src" / "[main].txt"
        tracked.write_text("before\n")
        (repo / "other.txt").write_text("other\n")
        git("add", "--", "src/[main].txt", "other.txt")
        git("-c", "user.name=Pi Test", "-c", "user.email=pi@example.invalid", "commit", "-m", "initial")
        tracked.write_text("after\n")

        results = self._run_real(
            repo,
            [
                {"action": "status", "paths": ["src/[main].txt"]},
                {"action": "diff", "target": "worktree", "view": "patch", "paths": ["src/[main].txt"]},
            ],
        )
        self.assertEqual(json.loads(results[0]["content"][0]["text"]), [
            {"index": " ", "worktree": "M", "path": "src/[main].txt"},
        ])
        self.assertIn("src/[main].txt", results[1]["content"][0]["text"])
        self.assertIn("-before", results[1]["content"][0]["text"])
        self.assertIn("+after", results[1]["content"][0]["text"])
        nested_results = self._run_real(
            repo / "src",
            [{"action": "status", "paths": ["src/[main].txt"]}],
        )
        self.assertEqual(json.loads(nested_results[0]["content"][0]["text"]), [
            {"index": " ", "worktree": "M", "path": "src/[main].txt"},
        ])

        linked = Path(directory.name) / "linked"
        git("worktree", "add", "--detach", str(linked), "HEAD")
        (linked / "src" / "[main].txt").write_text("linked-after\n")
        linked_results = self._run_real(
            linked,
            [{"action": "status", "paths": ["src/[main].txt"]}],
        )
        self.assertEqual(json.loads(linked_results[0]["content"][0]["text"]), [
            {"index": " ", "worktree": "M", "path": "src/[main].txt"},
        ])

    def test_diff_views_and_range_resolution_keep_raw_refs_out_of_final_diff(self):
        """REGRESSION CONTRACT: revision expressions are resolved independently and only exact OIDs reach diff."""
        root = "/synthetic/worktree"
        oid_a = "a" * 40
        oid_b = "b" * 40
        plans = self._plans(root, {"stdout": "M\0src/main.ts\0"})[:2] + [
            {"stdout": f"{oid_a}\n"},
            {"stdout": f"{oid_b}\n"},
            {"stdout": "M\0src/main.ts\0"},
        ]
        payload = self._run(
            {"action": "diff", "target": "range", "view": "name-status", "base": "main", "head": "feature", "paths": ["src/main.ts"]},
            plans,
        )
        self.assertFalse(payload["result"].get("isError", False))
        self.assertEqual(payload["result"]["details"]["baseOid"], oid_a)
        self.assertEqual(payload["result"]["details"]["headOid"], oid_b)
        self.assertEqual(payload["calls"][-1]["args"][-4:], [oid_a, oid_b, "--", "src/main.ts"])
        self.assertIn("main^{commit}", payload["calls"][2]["args"])
        self.assertIn("feature^{commit}", payload["calls"][3]["args"])
        self.assertNotIn("main", payload["calls"][-1]["args"])
        self.assertNotIn("feature", payload["calls"][-1]["args"])
        self.assertNotIn("--binary", payload["calls"][-1]["args"])
        self.assertIn("--no-ext-diff", payload["calls"][-1]["args"])
        self.assertIn("--no-textconv", payload["calls"][-1]["args"])

    def test_worktree_patch_and_staged_stat_use_only_their_declared_targets(self):
        """REGRESSION CONTRACT: worktree and staged views preserve Git target semantics without exposing extra diff modes."""
        worktree = self._run(
            {"action": "diff", "target": "worktree", "view": "patch", "paths": []},
            self._plans("/synthetic/worktree", {"stdout": "@@ -1 +1 @@\n-old\n+new\n"}),
        )
        self.assertFalse(worktree["result"].get("isError", False))
        self.assertIn("--patch", worktree["calls"][-1]["args"])
        self.assertIn("--unified=3", worktree["calls"][-1]["args"])
        self.assertNotIn("--cached", worktree["calls"][-1]["args"])
        self.assertEqual(worktree["calls"][-1]["args"][-1], "--")

        oid = "c" * 40
        staged_plans = self._plans("/synthetic/worktree", {"stdout": "1 file changed, 1 insertion(+)\n"})[:2]
        staged_plans.extend([{"stdout": f"{oid}\n"}, {"stdout": "1 file changed, 1 insertion(+)\n"}])
        staged = self._run(
            {"action": "diff", "target": "staged", "view": "stat", "paths": ["src/main.ts"]},
            staged_plans,
        )
        self.assertFalse(staged["result"].get("isError", False))
        final = staged["calls"][-1]["args"]
        self.assertIn("--stat", final)
        self.assertIn("--cached", final)
        self.assertIn(oid, final)
        self.assertIn("src/main.ts", final)

    def test_invalid_refs_paths_combinations_and_unknown_fields_fail_before_spawn(self):
        """REGRESSION CONTRACT: hostile pathspecs and revision expressions never reach a Git process."""
        cases = [
            {"action": "status", "target": "worktree"},
            {"action": "diff", "target": "range", "view": "patch", "base": "main..bad", "head": "feature"},
            {"action": "diff", "target": "range", "view": "patch", "base": "main", "head": "feature~1"},
            {"action": "status", "paths": ["../escape"]},
            {"action": "status", "paths": ["/absolute"]},
            {"action": "status", "paths": ["C:/drive"]},
            {"action": "status", "paths": ["foo\\bar"]},
            {"action": "status", "paths": [":(glob)foo"]},
            {"action": "status", "extra": True},
        ]
        for request in cases:
            with self.subTest(request=request):
                payload = self._run(request, [])
                self.assertTrue(payload["result"]["isError"])
                self.assertEqual(payload["result"]["details"]["error"], "invalid-input")
                self.assertEqual(payload["calls"], [])

    def test_aggregate_byte_and_line_caps_terminate_without_disclosing_prefix(self):
        """REGRESSION CONTRACT: stdout/stderr overflow is terminated, bounded, and never returned as partial content."""
        root = "/synthetic/worktree"
        for final in (
            {"stdoutChunks": [{"bytes": 65537, "value": 120}]},
            {"stderrChunks": [{"bytes": 65537, "value": 101}]},
            {"stdoutChunks": [{"repeat": 2001, "value": "x\n"}]},
        ):
            with self.subTest(final=final):
                payload = self._run({"action": "status"}, self._plans(root, final))
                self.assertTrue(payload["result"]["isError"])
                self.assertEqual(payload["result"]["details"]["error"], "output-limit")
                self.assertEqual(
                    payload["result"]["content"][0]["text"],
                    "output limit exceeded; narrow paths or use stat/name-status",
                )
                self.assertTrue(payload["calls"][-1]["kills"])
                self.assertNotIn("x\\n", payload["result"]["content"][0]["text"])

    def test_cancellation_spawn_failure_and_bounded_kill_fallback_clean_up_listeners(self):
        """REGRESSION CONTRACT: cancellation and spawn failures are distinguishable and cannot leak process listeners."""
        cancelled = self._run(
            {"action": "status"},
            self._plans("/synthetic/worktree", {"hold": True, "closeOnKill": False}),
            abort=True,
        )
        self.assertEqual(cancelled["result"]["details"]["error"], "cancelled")
        self.assertEqual(cancelled["calls"][-1]["kills"], ["SIGTERM", "SIGKILL"])
        self.assertEqual(cancelled["calls"][-1]["stdoutListeners"], 0)
        self.assertEqual(cancelled["calls"][-1]["stderrListeners"], 0)

        termination_error = self._run(
            {"action": "status"},
            self._plans("/synthetic/worktree", {"hold": True, "closeOnKill": False, "errorAfterSigterm": True}),
            abort=True,
        )
        self.assertEqual(termination_error["result"]["details"]["error"], "cancelled")
        self.assertEqual(termination_error["calls"][-1]["kills"], ["SIGTERM", "SIGKILL"])
        self.assertEqual(termination_error["calls"][-1]["stdoutListeners"], 0)
        self.assertEqual(termination_error["calls"][-1]["stderrListeners"], 0)

        timed_out = self._run(
            {"action": "status"},
            self._plans("/synthetic/worktree", {"hold": True, "closeOnKill": False}),
            timeout=True,
        )
        self.assertEqual(timed_out["result"]["details"]["error"], "timeout")
        self.assertEqual(timed_out["calls"][-1]["kills"], ["SIGTERM", "SIGKILL"])
        self.assertEqual(timed_out["calls"][-1]["stdoutListeners"], 0)
        self.assertEqual(timed_out["calls"][-1]["stderrListeners"], 0)

        failed = self._run(
            {"action": "status"},
            [{"throw": True}],
        )
        self.assertEqual(failed["result"]["details"]["error"], "spawn-failed")
        self.assertEqual(failed["calls"], [])

        emitted_error = self._run(
            {"action": "status"},
            self._plans("/synthetic/worktree", {"error": True}),
        )
        self.assertEqual(emitted_error["result"]["details"]["error"], "spawn-failed")
        self.assertEqual(emitted_error["calls"][-1]["stdoutListeners"], 0)
        self.assertEqual(emitted_error["calls"][-1]["stderrListeners"], 0)

    def test_timeout_constant_and_fixed_hardening_surface_are_documented(self):
        """REGRESSION CONTRACT: the reader retains a fixed deadline and hardening surface instead of request-controlled execution."""
        directory, root, extension = self._fixture()
        self.addCleanup(directory.cleanup)
        script = f'''
const module = await import({json.dumps(extension.as_uri())});
console.log(JSON.stringify({{ timeout: module.EXECUTION_TIMEOUT_MS, bytes: module.MAX_OUTPUT_BYTES, lines: module.MAX_OUTPUT_LINES, executable: module.GIT_EXECUTABLE, argv: module.FIXED_GIT_ARGS }}));
'''
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["timeout"], 10_000)
        self.assertEqual(payload["bytes"], 64 * 1024)
        self.assertEqual(payload["lines"], 2_000)
        self.assertEqual(payload["executable"], "git")
        self.assertIn("--no-pager", payload["argv"])
        self.assertIn("protocol.allow=never", payload["argv"])
        self.assertIn("diff.external=", payload["argv"])


if __name__ == "__main__":
    unittest.main()
