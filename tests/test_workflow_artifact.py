import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "policy" / "workflows" / "feature-workflow-pilot.md"
POLICY = ROOT / "policy" / "orchestration.md"


class FeatureWorkflowArtifactTests(unittest.TestCase):
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
        """REGRESSION CONTRACT: qualifying analysis cannot silently regress to weak two-lane preference wording."""
        policy = POLICY.read_text()
        for phrase in (
            "large analysis spanning at least two independent top-level areas or a large file set MUST use 2–4 parallel",
            "one synthesis owner/writer",
            "implementation validation remains serial",
            "genuine data dependency, indivisible shared state, or too-small scope",
            "### Bounded delegation and responsiveness",
            "Unbounded or whole-initiative delegation is prohibited",
            "at most one independently verifiable slice and one validator checkpoint",
            "strongest supported execution cap (turn, runtime, or tool-call)",
            "Potentially non-brief work MUST run in the background",
            "reports completion, blocker, and checkpoint events without polling",
            "serial validation or checkpoint occurs before the next dependent slice",
            "cannot be safely bounded, pause and decompose it or ask the user",
            "Handoffs, task instructions, workflow labels, schemas, acceptance contracts",
            "original language when nuance matters",
            "user-facing replies and explicitly user-facing artifacts in the language requested by the user",
        ):
            self.assertIn(phrase, policy)
        self.assertNotIn("two or three genuinely independent evidence scopes", policy)
        self.assertNotIn("prefer parallel explorer tasks", policy)

    def test_pilot_keeps_finding_repairs_decision_gated_without_blanket_authorization(self):
        """REGRESSION CONTRACT: pilot gates cover named scope; later findings need individual outcomes."""
        workflow = WORKFLOW.read_text()
        for phrase in (
            "authorize only the named original scope and acceptance criteria",
            "do not authorize future findings discovered by review, audit, exploration, or validation",
            "only a deterministic, reproducible failure of an already-authorized in-scope acceptance criterion",
            "individual Done / Skip / Snooze decision",
            "concise evidence, impact, recommendation, and scope/cost",
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
