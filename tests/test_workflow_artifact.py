import json
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "policy" / "workflows" / "feature-workflow-pilot.md"
POLICY = ROOT / "policy" / "orchestration.md"


class FeatureWorkflowArtifactTests(unittest.TestCase):
    def _pi_render_commands(self):
        pi_renderer = ROOT / "adapters" / "pi" / "render.py"
        supported_profiles = runpy.run_path(str(pi_renderer))["SUPPORTED_PROFILES"]
        self.assertTrue(
            supported_profiles,
            "No supported Pi profiles discovered in adapters/pi/render.py.",
        )

        return {
            f"pi-{profile_name}": [pi_renderer, "--profile", profile_name]
            for profile_name in sorted(supported_profiles)
        }

    def test_feature_workflow_is_packaged_separately_without_inlining_into_base_prompts(self):
        """This test will fail when the detailed pilot remains in every base prompt."""
        self.assertTrue(WORKFLOW.is_file())
        workflow = WORKFLOW.read_text()
        policy = POLICY.read_text()
        self.assertIn("# Feature Workflow Pilot", workflow)
        self.assertNotIn("# Feature Workflow Pilot", policy)
        self.assertIn("workflows/feature-workflow-pilot.md", policy)
        self.assertIn("optional", policy.lower())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = {}
            commands = {
                "opencode": [ROOT / "adapters" / "opencode" / "render.py"],
                "codex": [ROOT / "adapters" / "codex" / "render.py", "--profile", "openai"],
                "claude-code": [ROOT / "adapters" / "claude-code" / "render.py"],
                "pi-hybrid": [ROOT / "adapters" / "pi" / "render.py", "--profile", "hybrid"],
                "pi-openai": [ROOT / "adapters" / "pi" / "render.py", "--profile", "openai"],
                "pi-deepseek": [ROOT / "adapters" / "pi" / "render.py", "--profile", "deepseek"],
                "pi-glm": [ROOT / "adapters" / "pi" / "render.py", "--profile", "glm"],
            }
            for name, parts in commands.items():
                output = root / name
                result = subprocess.run(
                    [sys.executable, *map(str, parts), "--output", str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs[name] = output

            self.assertEqual(
                (outputs["opencode"] / "workflows" / "feature-workflow-pilot.md").read_text(),
                workflow,
            )
            self.assertEqual(
                (outputs["codex"] / "workflows" / "feature-workflow-pilot.md").read_text(),
                workflow,
            )
            self.assertEqual(
                (outputs["claude-code"] / "workflows" / "feature-workflow-pilot.md").read_text(),
                workflow,
            )
            for name in ("pi-hybrid", "pi-openai", "pi-deepseek", "pi-glm"):
                self.assertEqual(
                    (outputs[name] / "workflows" / "feature-workflow-pilot.md").read_text(),
                    workflow,
                )
            for name, core_path in (
                ("opencode", outputs["opencode"] / "profiles" / "_shared" / "orchestration-core.md"),
                ("codex", outputs["codex"] / "AGENTS.md"),
                ("claude-code", outputs["claude-code"] / "_shared" / "orchestration-core.md"),
                ("pi-hybrid", outputs["pi-hybrid"] / "_shared" / "orchestration-core.md"),
                ("pi-openai", outputs["pi-openai"] / "_shared" / "orchestration-core.md"),
                ("pi-deepseek", outputs["pi-deepseek"] / "_shared" / "orchestration-core.md"),
                ("pi-glm", outputs["pi-glm"] / "_shared" / "orchestration-core.md"),
            ):
                content = core_path.read_text()
                self.assertIn("Mandatory analysis fanout", content, name)
                if name.startswith("pi-"):
                    self.assertIn("For every Pi Agent call, set `max_turns`", content, name)
                else:
                    self.assertNotIn("For every Pi Agent call", content, name)
            self.assertNotIn("# Feature Workflow Pilot", (outputs["opencode"] / "profiles" / "_shared" / "orchestration-core.md").read_text())
            self.assertNotIn("# Feature Workflow Pilot", (outputs["codex"] / "AGENTS.md").read_text())
            self.assertNotIn("# Feature Workflow Pilot", (outputs["claude-code"] / "_shared" / "orchestration-core.md").read_text())

            self.assertEqual(
                json.loads((outputs["opencode"] / "manifest.json").read_text())["workflows"],
                ["feature-workflow-pilot"],
            )

    def test_canonical_policy_requires_fanout_and_internal_language_rule(self):
        """REGRESSION CONTRACT: bounded delegation, blocking calls, and internal language rules must remain complete in canonical and rendered policies."""
        policy = POLICY.read_text()
        for phrase in (
            "large analysis spanning at least two independent top-level areas or a large file set MUST use 2–4 parallel",
            "one synthesis owner/writer",
            "implementation validation remains serial",
            "genuine data dependency, indivisible shared state, or too-small scope",
            "Handoffs, task instructions, workflow labels, schemas, acceptance contracts",
            "original language when nuance matters",
            "user-facing replies and explicitly user-facing artifacts in the language requested by the user",
        ):
            self.assertIn(phrase, policy)

        bounded_heading = "### Bounded delegation and responsiveness"
        bounded_start = policy.index(bounded_heading)
        bounded_end = policy.index("### Internal orchestration language", bounded_start)
        bounded_block = policy[bounded_start:bounded_end]
        bounded_phrases = (
            "Unbounded or whole-initiative delegation is prohibited",
            "at most one independently verifiable slice and one validator checkpoint",
            "explicit stopping condition",
            "strongest supported execution cap (turn, runtime, or tool-call)",
            "returns partial progress or `BLOCKED`",
            "never self-extends",
            "Potentially non-brief work MUST run in the background when the harness supports it",
            "Foreground delegation is reserved for demonstrably brief, bounded work whose result immediately gates the next action",
            "reports completion, blocker, and checkpoint events without polling",
            "serial validation or checkpoint occurs before the next dependent slice",
            "cannot be safely bounded, pause and decompose it or ask the user",
            "Every potentially blocking tool invocation",
            "shell, test/build, Docker, network, browser/device, or external-job monitoring",
            "enforceable per-call deadline or timeout",
            "Turn limits such as max_turns do not bound the duration of an individual tool call",
            "are insufficient on their own",
            "the agent MUST NOT own that operation",
            "Keep it in the primary with a bounded tool, use a bounded external runner, or return `BLOCKED`",
            "On expiry, terminate/cancel the underlying operation when supported",
            "return `BLOCKED` with last progress/evidence/prerequisite",
            "A steering message or request to stop is not equivalent to termination",
            "Never report an agent or task as terminated until it reaches a terminal state",
            "no replacement agent may duplicate the same scope while the prior task remains non-terminal",
            "#### Debugger and validator handoff contract",
            "Every primary handoff to `debugger` or `validator` MUST name",
            "bounded scope and exact checks",
            "terminal condition",
            "whole-lane deadline or maximum wait",
            "per-call timeout and termination expectation",
            "progress evidence",
            "last meaningful progress time",
            "unfinished operation",
            "exact prerequisite",
            "declarative handoff contract",
            "Do not invent a scheduler, watchdog, cancellation API, or timeout capability",
        )
        for phrase in bounded_phrases:
            self.assertIn(phrase, bounded_block)

        self.assertNotIn("two or three genuinely independent evidence scopes", policy)
        self.assertNotIn("prefer parallel explorer tasks", policy)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pi_commands = self._pi_render_commands()
            commands = {
                "opencode": [ROOT / "adapters" / "opencode" / "render.py"],
                "codex": [ROOT / "adapters" / "codex" / "render.py", "--profile", "openai"],
                "claude-code": [ROOT / "adapters" / "claude-code" / "render.py"],
                **pi_commands,
            }
            outputs = {}
            for name, parts in commands.items():
                output = root / name
                result = subprocess.run(
                    [sys.executable, *map(str, parts), "--output", str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs[name] = output

            non_pi_paths = {
                "opencode": outputs["opencode"] / "profiles" / "_shared" / "orchestration-core.md",
                "codex": outputs["codex"] / "AGENTS.md",
                "claude-code": outputs["claude-code"] / "_shared" / "orchestration-core.md",
            }
            pi_paths = {
                name: outputs[name] / "_shared" / "orchestration-core.md"
                for name in pi_commands
            }
            for name, path in {**non_pi_paths, **pi_paths}.items():
                content = path.read_text()
                start = content.index(bounded_heading)
                end = content.index("### Internal orchestration language", start)
                rendered_block = content[start:end]
                for phrase in bounded_phrases:
                    self.assertIn(phrase, rendered_block, name)

            pi_phrases = (
                "For every Pi Agent call, set `max_turns`",
                "Source-changing `worker` and `worker-complex` calls default to `run_in_background: true`",
                "foreground calls require a clearly brief, bounded scope and a low turn cap",
                "foreground ≤12 turns",
                "background mutation ≤30 turns",
                "exceeding a slice requires a new orchestrator decision rather than automatic continuation",
                "Every potentially blocking child tool call additionally uses its native timeout or an OS/harness-enforced timeout.",
                "`max_turns` alone is insufficient because it does not bound a single tool call.",
                "If enforceable timeout and termination are unavailable, do not delegate that operation; keep it bounded in the primary or return `BLOCKED`.",
            )
            for name, path in pi_paths.items():
                content = path.read_text()
                for phrase in pi_phrases:
                    self.assertIn(phrase, content, name)

    def test_pilot_propagates_reviewable_delivery_boundaries_and_checkpoint_requirements(self):
        """This fails when the pilot can start another slice without a bounded review unit or checkpoint."""
        workflow = WORKFLOW.read_text()
        start = workflow.index("### Explicit delivery slices and ordered review units")
        end = workflow.index("For a large initiative, persist a mindmap", start)
        delivery = workflow[start:end]

        for phrase in (
            "one bounded PR or fallback review unit and use one coherent concern per PR",
            "suitable hosting/remote support and harness capability/authorization",
            "PR is the default delivery unit",
            "equivalently reviewable local branch, commit, or patch",
            "does not assume a hosting provider or authorize automatic",
            "branch, commit, push, merge, or PR creation",
            "<=400` human-authored maintained changed lines",
            "<=12` human-authored maintained changed files",
            "generated artifacts and lockfiles",
            "count and report generated-artifact and lockfile lines/files separately",
            "401–800",
            "13–24",
            "concrete rationale and explicit user approval before implementation or promotion",
            ">800` human-authored changed lines",
            ">24` human-authored changed files",
            "absolute maximum violation",
            "must be split, not approved wholesale",
            "isolated, non-overlapping branches or worktrees",
            "promotion and user checkpoints remain ordered",
            "After every PR or fallback review unit",
            "waits for explicit user approval before the next PR or review unit",
            "purpose/concern",
            "behavior before/after",
            "key decisions and approvals",
            "human-authored diff lines/files",
            "separate generated-artifact and lockfile lines/files",
            "affected areas/files",
            "risks",
            "validation evidence or `not run`/`BLOCKED` status",
            "residual work",
            "next proposed PR or fallback unit",
            "Earlier initiative or slice approval never implies approval for the next unit",
        ):
            self.assertIn(phrase, delivery)

        expected_workflow = workflow
        for path in (
            ROOT / "generated" / "opencode" / "workflows" / "feature-workflow-pilot.md",
            ROOT / "generated" / "codex" / "workflows" / "feature-workflow-pilot.md",
            ROOT / "generated" / "claude-code" / "workflows" / "feature-workflow-pilot.md",
            ROOT / "generated" / "pi" / "hybrid" / "workflows" / "feature-workflow-pilot.md",
            ROOT / "generated" / "pi" / "openai" / "workflows" / "feature-workflow-pilot.md",
            ROOT / "generated" / "pi" / "deepseek" / "workflows" / "feature-workflow-pilot.md",
            ROOT / "generated" / "pi" / "glm" / "workflows" / "feature-workflow-pilot.md",
        ):
            self.assertEqual(path.read_text(), expected_workflow, path)

    def test_pilot_keeps_finding_repairs_decision_gated_without_blanket_authorization(self):
        """REGRESSION CONTRACT: pilot gates cover named scope; later findings need individual outcomes."""
        workflow = WORKFLOW.read_text()
        for phrase in (
            "authorize only the named original scope and acceptance criteria",
            "do not authorize future findings discovered by review, audit, exploration, or validation",
            "only a deterministic, reproducible failure of an already-authorized in-scope acceptance criterion",
            "individual Done / Skip / Snooze decision",
            "clear, structured explanation",
            "concrete problem or failure mode and evidence",
            "affected scope and impact, including user-visible behavior, systems/components/files/contracts",
            "detailed viable solution options—not just labels",
            "implementation direction, scope/cost, trade-offs/risks",
            "recommendation with rationale where appropriate",
            "self-contained enough that the user does not need to infer context",
            "These are disposition decisions, not solution selection or ambiguous package authorization.",
            "batch distinct questions up to its limit",
            "each finding remains a separate decision",
            "record every outcome",
            "do not silently create deferred tickets or re-propose skipped findings",
            "No separate pilot-specific gate or blanket authorization is added.",
        ):
            self.assertIn(phrase, workflow)

    def test_pilot_has_executable_pi_runs_all_writer_validator_order(self):
        """REGRESSION CONTRACT: the pilot must execute as one raw workflowScript with a fanout barrier and serial stages."""
        workflow = WORKFLOW.read_text()
        blocks = re.findall(r"```js\s+(.*?)```", workflow, flags=re.DOTALL)
        source = next((block.strip() for block in blocks if "subagent({" in block), None)
        self.assertIsNotNone(source)
        script = f'''
const source = {json.dumps(source)};
const calls = [];
function subagent(params) {{ calls.push(params); }}
eval(source);
if (calls.length !== 1) throw new Error("expected one outer subagent call");
const request = calls[0];
const events = [];
const runs = {{
  all(items) {{
    events.push({{ kind: "all", items }});
    return Promise.resolve(items.map((item) => ({{ key: item.key, output: "evidence:" + item.key }})));
  }},
  run(key, params) {{
    events.push({{ kind: "run", key, params }});
    return Promise.resolve({{ key, output: "result:" + key }});
  }}
}};
const execute = new Function("runs", "return (async () => {{" + request.workflowScript + "}})()");
const result = await execute(runs);
console.log(JSON.stringify({{ request: {{ async: request.async, context: request.context, workflowScriptType: typeof request.workflowScript }}, events, result }}));
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["request"], {
            "async": True,
            "context": "fresh",
            "workflowScriptType": "string",
        })
        events = payload["events"]
        self.assertEqual([event["kind"] for event in events], ["all", "run", "run"])
        lanes = events[0]["items"]
        self.assertGreaterEqual(len(lanes), 2)
        self.assertLessEqual(len(lanes), 4)
        self.assertEqual([lane["key"] for lane in lanes], ["policy-lane", "adapter-lane", "test-lane"])
        for lane in lanes:
            self.assertEqual(lane["agent"], "explorer")
            self.assertIsInstance(lane["phase"], str)
            self.assertIsInstance(lane["label"], str)
            self.assertIsInstance(lane["task"], str)
            self.assertTrue(lane["task"])
            self.assertFalse(lane["output"])
            self.assertNotIn("scope", lane)
        self.assertEqual(events[1]["key"], "writer")
        self.assertEqual(events[1]["params"]["agent"], "worker")
        self.assertIn("evidence:policy-lane", events[1]["params"]["task"])
        self.assertIn("evidence:adapter-lane", events[1]["params"]["task"])
        self.assertIn("evidence:test-lane", events[1]["params"]["task"])
        self.assertEqual(events[2]["key"], "validator")
        self.assertEqual(events[2]["params"]["agent"], "validator")
        self.assertIn("result:writer", events[2]["params"]["task"])
        self.assertIn("Do not run tests, checks, lint, typecheck, or builds.", events[1]["params"]["task"])
        self.assertIn("review remains separately authorized", workflow)
        self.assertIn("genuine data dependency, indivisible shared state, or too-small scope", workflow)


if __name__ == "__main__":
    unittest.main()
