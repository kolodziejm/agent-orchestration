import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANARY = ROOT / "scripts" / "pi-live-canary"


class PiLiveCanaryTests(unittest.TestCase):
    def run_canary(self, root, *, mode="success", enabled=True, ci=None, ack=True, **extra):
        launcher = root / "pi-openai"
        marker = root / "launcher-invoked"
        launcher.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import json
                import os
                import pathlib
                import sys
                import time

                pathlib.Path({str(marker)!r}).write_text("invoked")
                record = os.environ.get("FAKE_CWD_RECORD")
                if record:
                    pathlib.Path(record).write_text(str(pathlib.Path.cwd()))
                argument_record = os.environ.get("FAKE_ARGUMENT_RECORD")
                if argument_record:
                    pathlib.Path(argument_record).write_text(json.dumps(sys.argv[1:]))
                mode = {mode!r}
                if mode == "timeout":
                    time.sleep(10)
                if mode == "output-bound":
                    while True:
                        print("x" * 4096, flush=True)
                if mode == "malformed":
                    print("not-json", flush=True)
                    raise SystemExit(0)
                session = pathlib.Path(sys.argv[sys.argv.index("--session-dir") + 1])
                marker_data = json.loads((pathlib.Path.cwd() / "immutable-marker.json").read_text())
                if mode == "unexpected-parent-tool":
                    print(json.dumps({{"type": "tool_execution_start", "toolName": "read"}}), flush=True)
                if mode == "marker-changed":
                    marker_path = pathlib.Path.cwd() / "immutable-marker.json"
                    marker_path.chmod(0o600)
                    marker_path.write_text("changed\\n")
                if mode == "workspace-dirty":
                    (pathlib.Path.cwd() / "unexpected.txt").write_text("unexpected")
                transcript = {{
                    "agent": "planner",
                    "events": [
                        {{"type": "tool_execution_start", "toolName": "subagent", "args": {{"agent": "explorer"}}}},
                        {{"type": "tool_execution_end", "toolName": "subagent", "result": "nonce {{}} token {{}}".format(marker_data["nonce"], marker_data["token"])}},
                        {{"error": "Capability ceiling denied validator before child start"}},
                    ],
                }}
                if mode == "redaction":
                    transcript["secret"] = "SECRET_TRANSCRIPT_VALUE"
                (session / "planner-transcript.json").write_text(json.dumps(transcript))
                print(json.dumps({{"type": "tool_execution_start", "toolName": "subagent", "args": {{"agent": "planner"}}}}), flush=True)
                print(json.dumps({{"type": "tool_execution_end", "toolName": "subagent", "args": {{"agent": "planner"}}}}), flush=True)
                """
            )
        )
        launcher.chmod(0o755)
        environment = os.environ.copy()
        if enabled:
            environment["AGENT_ORCHESTRATION_PI_LIVE_CANARY"] = "1"
        else:
            environment.pop("AGENT_ORCHESTRATION_PI_LIVE_CANARY", None)
        environment["AGENT_ORCHESTRATION_PI_LIVE_CANARY_LAUNCHER"] = str(launcher)
        if ack:
            environment["AGENT_ORCHESTRATION_PI_LIVE_CANARY_ACK"] = "I_ACCEPT_OPENAI_USAGE"
        else:
            environment["AGENT_ORCHESTRATION_PI_LIVE_CANARY_ACK"] = "wrong"
        if ci is None:
            environment.pop("CI", None)
        else:
            environment["CI"] = ci
        environment.update({key: str(value) for key, value in extra.items()})
        result = subprocess.run(
            [str(CANARY)], cwd=ROOT, env=environment, text=True,
            capture_output=True, timeout=15,
        )
        payload = json.loads(result.stdout)
        return result, payload, marker

    def test_canary_refuses_without_opt_in_or_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, payload, marker = self.run_canary(root, enabled=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["category"], "not-enabled")
            self.assertFalse(marker.exists())
            result, payload, marker = self.run_canary(root, ack=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["category"], "acknowledgement-required")
            self.assertFalse(marker.exists())

    def test_canary_refuses_in_ci_even_with_explicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            result, payload, marker = self.run_canary(Path(directory), ci="true")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["category"], "ci-refused")
            self.assertFalse(marker.exists())

    def test_canary_success_requires_nested_evidence_and_cleans_private_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd_record = root / "canary-cwd"
            result, payload, marker = self.run_canary(
                root, FAKE_CWD_RECORD=cwd_record
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["ok"])
            for key in (
                "planner_delegation", "planner_transcript", "explorer_result",
                "validator_denied", "marker_unchanged", "workspace_clean",
            ):
                self.assertTrue(payload[key], key)
            self.assertFalse(payload["validator_started"])
            self.assertFalse(payload["validator_receipt"])
            self.assertTrue(marker.exists())
            self.assertTrue(cwd_record.is_file())
            self.assertFalse(Path(cwd_record.read_text()).exists())
            self.assertEqual(result.stderr, "")

    def test_parent_invocation_is_limited_to_subagent_and_requires_first_only_planner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argument_record = root / "arguments.json"
            result, payload, _marker = self.run_canary(
                root, FAKE_ARGUMENT_RECORD=argument_record
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = json.loads(argument_record.read_text())
            self.assertEqual(arguments[arguments.index("--tools") + 1], "subagent")
            self.assertIn("first action", arguments[-1])
            self.assertIn("only parent action", arguments[-1])
            self.assertEqual(payload["unexpected_parent_tool_count"], 0)

    def test_canary_rejects_an_unexpected_parent_tool_with_a_sanitized_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            result, payload, _marker = self.run_canary(
                Path(directory), mode="unexpected-parent-tool"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["category"], "unexpected-parent-tool")
            self.assertEqual(payload["unexpected_parent_tool_count"], 1)
            self.assertNotIn("read", result.stdout + result.stderr)

    def test_canary_rejects_malformed_jsonl_marker_changes_and_unexpected_files(self):
        for mode, category in (
            ("malformed", "jsonl-parse-failed"),
            ("marker-changed", "marker-changed"),
            ("workspace-dirty", "workspace-dirty"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                result, payload, _marker = self.run_canary(Path(directory), mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(payload["category"], category)

    def test_canary_bounds_timeout_and_combined_output_without_leaking_child_output(self):
        for mode, variable, value, category in (
            ("timeout", "AGENT_ORCHESTRATION_PI_LIVE_CANARY_TIMEOUT_SECONDS", 0.1, "timeout"),
            ("output-bound", "AGENT_ORCHESTRATION_PI_LIVE_CANARY_MAX_OUTPUT_BYTES", 1024, "output-bound"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                result, payload, _marker = self.run_canary(
                    Path(directory), mode=mode, **{variable: value}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(payload["category"], category)
                self.assertNotIn("SECRET", result.stdout + result.stderr)

    def test_parser_accepts_real_parent_and_nested_retained_event_shapes(self):
        module = runpy.run_path(str(CANARY))
        def encode_args(agent):
            return json.dumps({"agent": agent})

        parent_events = [
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_start",
                "toolCallId": "planner-call",
                "data": {
                    "toolName": "subagent",
                    "argsPayload": encode_args("planner"),
                },
            },
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_end",
                "toolCallId": "planner-call",
                "data": {"toolName": "subagent", "result": "planner complete"},
            },
        ]
        self.assertEqual(
            module["_event_kind"](parent_events[0]), "tool_execution_start"
        )
        starts = module["tool_starts"](parent_events)
        self.assertEqual(len(starts), 1)
        self.assertEqual(module["target_of_event"](starts[0]), "planner")
        self.assertEqual(module["event_id"](starts[0]), "planner-call")

        nested_records = [
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_start",
                "data": {
                    "toolName": "subagent",
                    "argsPayload": encode_args("explorer"),
                },
            },
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_end",
                "data": {
                    "toolName": "subagent",
                    "result": "explorer returned the marker",
                },
            },
        ]
        nested_bytes = ("\n".join(json.dumps(record) for record in nested_records)).encode()
        artifact_events, malformed = module["_artifact_events"](
            [(Path("opaque-records.jsonl"), nested_bytes)]
        )
        self.assertFalse(malformed)
        nested_starts = module["tool_starts"](artifact_events)
        self.assertEqual(len(nested_starts), 1)
        self.assertEqual(module["target_of_event"](nested_starts[0]), "explorer")

    def test_allowed_planner_explorer_and_denied_validator_evidence_is_required(self):
        module = runpy.run_path(str(CANARY))
        nonce = "fixture-nonce"
        token = "fixture-token"

        def encode_args(agent):
            return json.dumps({"agent": agent})

        parent_events = [
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_start",
                "toolCallId": "planner-call",
                "payload": {
                    "toolName": "subagent",
                    "argsPayload": encode_args("planner"),
                },
            },
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_end",
                "toolCallId": "planner-call",
                "payload": {"toolName": "subagent", "result": "complete"},
            },
        ]
        planner_records = [
            {
                "recordType": "session",
                "agentName": "planner",
            },
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_start",
                "payload": {
                    "toolName": "subagent",
                    "argsPayload": encode_args("explorer"),
                },
            },
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_end",
                "payload": {
                    "toolName": "subagent",
                    "result": f"explorer read {nonce} {token}",
                },
            },
            {
                "recordType": "event",
                "sourceEventType": "tool_execution_end",
                "payload": {
                    "toolName": "subagent",
                    "argsPayload": encode_args("validator"),
                    "result": "capability ceiling denied validator before child start",
                },
            },
        ]
        artifact_bytes = ("\n".join(json.dumps(record) for record in planner_records)).encode()
        evidence, category = module["evaluate_evidence"](
            parent_events,
            [(Path("opaque-session.jsonl"), artifact_bytes)],
            nonce=nonce,
            token=token,
            marker_unchanged=True,
            workspace_clean=True,
        )
        self.assertEqual(category, "passed")
        self.assertTrue(evidence["planner_delegation"])
        self.assertTrue(evidence["explorer_result"])
        self.assertTrue(evidence["validator_denied"])
        self.assertFalse(evidence["validator_started"])
        self.assertEqual(evidence["unexpected_parent_tool_count"], 0)

    def test_canary_parser_is_bounded_and_does_not_return_raw_lines(self):
        module = runpy.run_path(str(CANARY))
        events, malformed = module["parse_jsonl"](
            b'{"type":"tool_execution_start"}\nnot-json\n'
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(malformed)
        self.assertNotIn("not-json", json.dumps(events))

        oversized = "{" + "\"agent\":\"planner\"," + (
            "x" * module["MAX_ARGS_PAYLOAD_BYTES"]
        ) + "}"
        event = {
            "recordType": "event",
            "sourceEventType": "tool_execution_start",
            "payload": {"toolName": "subagent", "argsPayload": oversized},
        }
        self.assertIsNone(module["target_of_event"](event))

    def test_canary_redacts_transcript_and_launcher_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            result, payload, _marker = self.run_canary(Path(directory), mode="redaction")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["ok"])
            self.assertNotIn("SECRET_TRANSCRIPT_VALUE", result.stdout + result.stderr)

    def test_canary_requires_the_explicit_openai_launcher_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / "pi-hybrid"
            launcher.write_text("#!/bin/sh\nexit 0\n")
            launcher.chmod(stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
            environment = os.environ.copy()
            environment.update({
                "AGENT_ORCHESTRATION_PI_LIVE_CANARY": "1",
                "AGENT_ORCHESTRATION_PI_LIVE_CANARY_ACK": "I_ACCEPT_OPENAI_USAGE",
                "AGENT_ORCHESTRATION_PI_LIVE_CANARY_LAUNCHER": str(launcher),
            })
            result = subprocess.run(
                [str(CANARY)], cwd=ROOT, env=environment, text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["category"], "openai-launcher-required")


if __name__ == "__main__":
    unittest.main()
