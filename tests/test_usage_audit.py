from __future__ import annotations

import contextlib
import datetime
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "audit" / "usage_audit.py"
SCRIPT = ROOT / "scripts" / "usage-audit"
PROJECT = "-work-demo"


def load_module():
    spec = importlib.util.spec_from_file_location("usage_audit_for_tests", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_module()


def usage(input_tokens=1, output=10, cache_read=100, cache_creation=20):
    return {"input_tokens": input_tokens, "output_tokens": output,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_creation}


def assistant(ts, model, message_id, tokens, content=None, request_id=None, uuid=None):
    return {
        "type": "assistant", "timestamp": ts, "cwd": "/work/demo", "uuid": uuid or f"u-{message_id}-{tokens['output_tokens']}",
        "requestId": request_id or f"r-{message_id}",
        "message": {"id": message_id, "model": model, "usage": tokens, "content": content or []},
    }


def tool_use(tool_id, name, tool_input):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def bash(tool_id, command):
    return tool_use(tool_id, "Bash", {"command": command})


def write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))


class Fixture:
    """A small synthetic ~/.claude/projects tree."""

    def __init__(self, root: Path):
        self.projects = root / "projects"
        self.session = "sess-1"

    def main(self, records):
        write_jsonl(self.projects / PROJECT / f"{self.session}.jsonl", records)

    def subagent(self, agent_id, agent_type, tool_use_id, records, description="demo run"):
        base = self.projects / PROJECT / self.session / "subagents"
        write_jsonl(base / f"agent-{agent_id}.jsonl", records)
        meta = {"agentType": agent_type, "toolUseId": tool_use_id, "description": description, "finished": True}
        if agent_type is None:
            del meta["agentType"]
        (base / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))


OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"


def build_fixture(root: Path) -> Fixture:
    fixture = Fixture(root)
    fixture.main([
        {"type": "user", "timestamp": "2026-10-10T08:00:00.000Z", "message": {"content": "hi"}},
        assistant("2026-10-10T08:00:01.000Z", OPUS, "m1", usage(output=5), [
            tool_use("t-worker", "Agent", {"subagent_type": "worker", "prompt": "Implement the thing", "description": "w"}),
            tool_use("t-complex", "Agent", {"subagent_type": "worker-complex", "prompt": "Fix the auth bug"}),
            tool_use("t-bare-meta", "Agent", {"prompt": "no type, but the meta says validator"}),
            tool_use("t-bare-none", "Agent", {"prompt": "no type and no transcript"}),
            tool_use("t-gp", "Agent", {"subagent_type": "general-purpose", "prompt": "search", "model": "haiku"}),
        ]),
        # a streaming repeat of m1: the larger output replaces the smaller one, and counts once
        assistant("2026-10-10T08:00:02.000Z", OPUS, "m1", usage(output=50), [
            tool_use("t-worker", "Agent", {"subagent_type": "worker", "prompt": "Implement the thing", "description": "w"}),
        ]),
        assistant("2026-10-11T09:00:00.000Z", OPUS, "m2", usage(output=7)),
        assistant("2026-10-12T09:00:00.000Z", "<synthetic>", "m3", usage(output=999)),
    ])
    fixture.subagent("w1", "worker", "t-worker", [
        {"type": "user", "timestamp": "2026-10-10T08:01:00.000Z", "message": {"content": "Implement the thing"}},
        assistant("2026-10-10T08:01:10.000Z", SONNET, "s1", usage(output=3), [
            tool_use("e1", "Edit", {"file_path": "/work/demo/src/a.ts"}),
            tool_use("e2", "Write", {"file_path": "/work/demo/src/b.ts"}),
            bash("b1", "pnpm exec vitest run src/a.test.ts"),
            bash("b2", "pnpm web:check"),
            bash("b3", "ls -la"),
        ]),
        assistant("2026-10-10T08:01:20.000Z", SONNET, "s1", usage(output=30), []),
        assistant("2026-10-10T08:03:00.000Z", SONNET, "s2", usage(output=4), [
            bash("b4", "cd app && vendor/bin/pest"),
            tool_use("e3", "Edit", {"file_path": "/work/demo/src/a.ts"}),
            tool_use("hb", "SubagentHandback", {"message": "Done: 2 files."}),
        ]),
    ])
    fixture.subagent("c1", "worker-complex", "t-complex", [
        {"type": "user", "timestamp": "2026-10-11T10:00:00.000Z", "message": {"content": "Fix the auth bug"}},
        assistant("2026-10-11T10:00:30.000Z", OPUS, "c-1", usage(output=40, cache_read=1000), [
            bash("cb1", "cargo test"),
            bash("cb2", "cargo test -p core"),
            bash("cb3", "npm run lint"),
            tool_use("ce1", "Edit", {"file_path": "/work/demo/lib/auth.rs"}),
        ]),
    ])
    fixture.subagent("v1", "validator", "t-bare-meta", [
        {"type": "user", "timestamp": "2026-10-12T11:00:00.000Z", "message": {"content": "validate"}},
        assistant("2026-10-12T11:00:30.000Z", SONNET, "v-1", usage(output=2), [
            bash("vb1", "./scripts/check"),
            bash("vb2", "uv run --locked ./scripts/check"),
        ]),
    ])
    return fixture


class AuditTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.fixture = build_fixture(self.root)
        self.utc = audit.resolve_timezone("UTC")

    def window(self, since=None, until=None):
        return audit.Window(audit.parse_day(since, "--since"), audit.parse_day(until, "--until"), self.utc)

    def transcripts(self):
        return audit.load_transcripts(self.fixture.projects)

    def runs(self, window=None, prices=None, include_prompts=True):
        return audit.build_runs(self.transcripts(), window or self.window(), audit.CommandClassifier(),
                                prices or audit.PriceTable(None), include_prompts)


class CommandClassifierTests(AuditTestCase):
    def test_full_gates_targeted_runs_and_other_commands_are_told_apart(self):
        """This test will fail when a full gate is counted as targeted, or the other way round."""
        classifier = audit.CommandClassifier()
        full = [
            "pnpm web:check", "pnpm i18n:check", "./scripts/check", "uv run --locked ./scripts/check",
            "pnpm exec vitest run", "npx jest", "vendor/bin/pest", "php artisan test", "docker exec app php artisan test",
            "cargo test", "pytest", "python3 -m unittest discover", "npm test", "cd app && npx jest --coverage",
        ]
        targeted = [
            "pnpm exec vitest run src/a.test.ts", "npx jest resources/js/x.spec.tsx", "vendor/bin/pest tests/Feature/AuthTest.php",
            "php artisan test --filter=LoginTest", "cargo test -p core", "cargo test --lib", "pytest -k login",
            "pytest tests/test_usage_audit.py", "npx jest -t 'renders'", "npx jest --findRelatedTests src/a.ts",
        ]
        other = ["ls -la", "git status", "npm run lint", "tsc --noEmit", "pnpm build", ""]
        for command in full:
            self.assertEqual(classifier.classify(command), "full", command)
        for command in targeted:
            self.assertEqual(classifier.classify(command), "targeted", command)
        for command in other:
            self.assertIsNone(classifier.classify(command), command)

    def test_words_that_only_mention_a_runner_are_not_runs(self):
        """This test will fail when a command that reads or installs a runner is counted as a test run."""
        classifier = audit.CommandClassifier()
        for command in ("cat jest.config.js", "rg vitest package.json", "uv add --dev pytest", "git commit -m 'add tests'",
                        'git commit -m "run pnpm web:check && npm test"', "echo pnpm web:check", "pnpm add -D vitest",
                        "ls vendor/bin/pest", "grep -rn 'scripts/check' README.md"):
            with self.subTest(command=command):
                self.assertIsNone(classifier.classify(command))
                self.assertFalse(classifier.is_verification(command))

    def test_a_path_argument_makes_a_run_targeted_but_a_flag_value_does_not(self):
        """This test will fail when a directory argument counts as a full run, or a flag value as a path."""
        classifier = audit.CommandClassifier()
        for command in ("npx jest src/components", "yarn jest path/to/thing", "pnpm exec vitest run packages/ui",
                        "vendor/bin/pest tests/Feature", "pytest tests/", "npx jest ./src/a.ts",
                        "python -m unittest tests.test_usage_audit", "npm test -- src/a.test.ts"):
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "targeted")
        for command in ("npx jest --config jest.config.js", "npx jest --coverage --maxWorkers 4", "vitest run --reporter verbose",
                        "pytest .", "npx jest 2>&1", "npm test > /tmp/out.log", "pytest -p no:cacheprovider"):
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "full")

    def test_go_test_all_packages_is_a_full_gate_and_a_package_is_targeted(self):
        """This test will fail when ./... is read as a path, or a named package as the whole module."""
        classifier = audit.CommandClassifier()
        for command in ("go test ./...", "go test ...", "go test -race -count=1 ./...", "cd svc && go test ./..."):
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "full")
        for command in ("go test ./pkg/foo", "go test ./pkg/...", "go test ./cmd/api ./internal/...", "go test -run TestLogin ./...",
                        "go test ./... ./pkg/foo"):
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "targeted")

    def test_make_just_playwright_and_turbo_runs_are_recognised(self):
        """This test will fail when make, just, Playwright, or Turborepo test runs are missed or mistaken for targeted."""
        classifier = audit.CommandClassifier()
        full = ["make test", "make check", "make lint", "make test-unit", "just test", "just check", "just lint",
                "cd app && make test", "playwright test", "npx playwright test", "pnpm exec playwright test",
                "yarn playwright test --project=chromium", "turbo run test", "turbo test", "pnpm turbo run test",
                "npx turbo run lint", "pnpm turbo run test:unit"]
        targeted = ["make test TEST=tests/test_a.py", "make test FILTER=login", "just test tests/unit", "npx playwright test e2e/login.spec.ts",
                    "playwright test --grep login", "playwright test -g login", "turbo run test --filter=web",
                    "pnpm turbo run test --filter web", "turbo run test --filter=web...", "make test ONLY=a"]
        none = ["make build", "make", "just --list", "make install", "playwright install", "turbo run dev", "just deploy"]
        for command in full:
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "full")
                self.assertTrue(classifier.is_verification(command))
        for command in targeted:
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "targeted")
        for command in none:
            with self.subTest(command=command):
                self.assertIsNone(classifier.classify(command))

    def test_a_package_scoped_test_script_is_targeted(self):
        """This test will fail when pnpm --filter or -F runs are not counted, or counted as full."""
        classifier = audit.CommandClassifier()
        for command in ("pnpm --filter web test", "pnpm -F web test", "pnpm --filter=web test", "pnpm -F web run test:unit",
                        "npm test --workspace=web", "npm -w web test", "pnpm --filter web exec vitest run"):
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "targeted")
        self.assertEqual(classifier.classify("pnpm -r test"), "full")
        self.assertEqual(classifier.classify("pnpm --filter web web:check"), "full")

    def test_tests_in_a_directory_name_do_not_make_a_run_targeted(self):
        """This test will fail when a directory such as latest/ is mistaken for tests/ in a cd segment."""
        classifier = audit.CommandClassifier()
        self.assertEqual(classifier.classify("cd ~/code/latest/app && npm test"), "full")
        self.assertEqual(classifier.classify("cd ~/code/tests-app && npx jest"), "full")
        self.assertEqual(classifier.classify("cd tests && pytest"), "full")
        self.assertEqual(classifier.classify("pytest tests/unit"), "targeted")

    def test_check_scripts_with_a_longer_name_are_not_the_full_gate(self):
        """This test will fail when check-browser or check-runtime is counted as scripts/check."""
        classifier = audit.CommandClassifier()
        for command in ("./scripts/check-browser", "./scripts/check-runtime", "scripts/checks"):
            with self.subTest(command=command):
                self.assertIsNone(classifier.classify(command))
        for command in ("./scripts/check", "scripts/check --quick", "SKIP_BROWSER_CHECKS=1 ./scripts/check", "bash scripts/check",
                        "uv run --locked ./scripts/check", "PYTHON=.venv/bin/python ./scripts/check"):
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command), "full")

    def test_wrappers_and_separators_are_looked_through(self):
        """This test will fail when a runner behind a wrapper or after a separator is missed."""
        classifier = audit.CommandClassifier()
        cases = {
            "docker exec -w /var/www/html app-container php artisan test": "full",
            "docker compose exec -T app php artisan test --filter=A": "targeted",
            "sail artisan test": "full",
            "FOO=1 BAR=2 npx vitest run": "full",
            "time npm test": "full",
            "cd app; pnpm web:check": "full",
            "echo start\nnpx jest src/a.ts\n": "targeted",
            "(cd app && pnpm exec vitest)": "full",
            "npm test 2>&1 | tail -20": "full",
            "bash -c 'cd app && npx jest src/a.ts'": "targeted",
            "bash -c 'cd app && npm test'": "full",
            "corepack pnpm@10.1.0 exec vitest run packages/ui": "targeted",
            "/tmp/tools/sail.sh php artisan test": "full",
            "cat > notes.md <<'EOF'\nnpm test\nEOF\nls": None,
            "python3 - <<EOF\nprint('pnpm web:check')\nEOF\npnpm web:check": "full",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(classifier.classify(command.replace("\\n", "\n")), expected)

    def test_segments_ignore_operators_inside_quotes(self):
        """This test will fail when an operator inside a quoted string splits a command."""
        self.assertEqual(audit.split_segments('git commit -m "a && b; c" && ls'), [["git", "commit", "-m", "a && b; c"], ["ls"]])
        self.assertEqual(audit.split_segments("echo 'x | y' | tail -1"), [["echo", "x | y"], ["tail", "-1"]])
        self.assertEqual(audit.split_segments("npm test 2>&1"), [["npm", "test", "2>&1"]])
        self.assertEqual(audit.split_segments(""), [])

    def test_verification_uses_segments_not_substrings(self):
        """This test will fail when a directory name or a commit message makes a command count as verification."""
        classifier = audit.CommandClassifier()
        for command in ("cd ~/code/expo-app && git status", 'git commit -m "add tests"', "cd ~/code/build-tools && ls",
                        "cat tests/test_a.py", "rg lint src", "git log --oneline -- tests"):
            with self.subTest(command=command):
                self.assertFalse(classifier.is_verification(command))
        for command in ("tsc --noEmit", "npx tsc -p web", "cd web && pnpm lint", "pnpm --filter web typecheck",
                        "cargo clippy", "xcodebuild -scheme App build", "vendor/bin/pint --test", "pnpm build"):
            with self.subTest(command=command):
                self.assertTrue(classifier.is_verification(command))

    def test_a_chained_command_counts_once_and_a_full_gate_wins(self):
        """This test will fail when a chained command is counted twice or a gate is hidden by a filter."""
        classifier = audit.CommandClassifier()
        self.assertEqual(classifier.classify("pnpm web:check && npx jest src/a.test.ts"), "full")

    def test_verification_is_broader_than_the_two_gate_classes(self):
        """This test will fail when lint, typecheck, or build commands stop counting as verification."""
        classifier = audit.CommandClassifier()
        for command in ("tsc --noEmit", "npm run lint", "pnpm build", "pnpm web:check", "npx jest a.test.ts"):
            self.assertTrue(classifier.is_verification(command), command)
        for command in ("ls -la", "git status", "rg foo"):
            self.assertFalse(classifier.is_verification(command), command)

    def test_the_default_patterns_can_be_replaced_from_a_config_file(self):
        """This test will fail when the config file's command lists stop replacing the defaults."""
        config_path = self.root / "audit.toml"
        config_path.write_text('[commands]\nfull_gate = ["make ci"]\nrunners = ["make unit"]\ntargeted = ["only="]\n')
        classifier = audit.classifier_from(audit.load_config(str(config_path)), [], [])
        self.assertEqual(classifier.classify("make ci"), "full")
        self.assertEqual(classifier.classify("make unit"), "full")
        self.assertEqual(classifier.classify("make unit only=a"), "targeted")
        self.assertIsNone(classifier.classify("pnpm web:check"))
        replaced = audit.classifier_from({}, [r"\bgate\b"], [])
        self.assertEqual(replaced.classify("run gate"), "full")
        self.assertIsNone(replaced.classify("pnpm web:check"))

    def test_a_bad_config_is_reported_not_raised_as_a_traceback(self):
        """This test will fail when a malformed config surfaces a raw exception."""
        for body in ('[commands]\nfull_gate = "x"\n', '[commands]\nfull_gate = ["("]\n', "not toml [", '[prices.m]\nspeed = 1\n',
                     '[prices.m]\ninput = -1\n'):
            path = self.root / "bad.toml"
            path.write_text(body)
            with self.subTest(body=body), self.assertRaises(audit.AuditError):
                audit.load_config(str(path))
        with self.assertRaises(audit.AuditError):
            audit.load_config(str(self.root / "missing.toml"))


class UsageAggregationTests(AuditTestCase):
    def aggregate(self, since=None, until=None, prices=None):
        return audit.aggregate_usage(self.transcripts(), self.window(since, until), prices or audit.PriceTable(None))

    def test_streaming_repeats_count_once_with_the_largest_output(self):
        """This test will fail when a repeated streaming message is double counted or keeps the smaller output."""
        result = self.aggregate()
        main = result["by_agent"]["main"]
        self.assertEqual(main["calls"], 2)
        self.assertEqual(main["output"], 50 + 7)
        worker = result["by_agent"]["worker"]
        self.assertEqual(worker["calls"], 2)
        self.assertEqual(worker["output"], 30 + 4)
        self.assertEqual(result["totals"]["api_calls"], 2 + 2 + 1 + 1)
        self.assertNotIn("<synthetic>", result["by_model"])

    def test_weighted_cost_and_shares_use_the_documented_weights(self):
        """This test will fail when the weighted-cost formula or the agent shares change."""
        result = self.aggregate()
        complex_entry = result["by_agent"]["worker-complex"]
        self.assertEqual(complex_entry["weighted_cost_units"], round(1 + 1.25 * 20 + 0.1 * 1000 + 5 * 40))
        self.assertAlmostEqual(sum(a["share_weighted_cost"] for a in result["by_agent"].values()), 1.0, places=2)
        self.assertEqual(result["by_agent"]["worker"]["transcripts"], 1)
        self.assertEqual(result["by_agent"]["main"]["transcripts"], 1)

    def test_model_per_agent_per_day(self):
        """This test will fail when the per-day model table loses an agent, a day, or a model."""
        result = self.aggregate()["model_by_agent_by_day"]
        self.assertEqual(result["2026-10-10"], {"main": {OPUS: 1}, "worker": {SONNET: 2}})
        self.assertEqual(result["2026-10-11"], {"main": {OPUS: 1}, "worker-complex": {OPUS: 1}})
        self.assertEqual(result["2026-10-12"], {"validator": {SONNET: 1}})

    def test_the_window_limits_calls_spawns_and_days(self):
        """This test will fail when --since or --until stops bounding the aggregates."""
        result = self.aggregate("2026-10-11", "2026-10-11")
        self.assertEqual(list(result["by_day"]), ["2026-10-11"])
        self.assertEqual(result["totals"]["api_calls"], 2)
        self.assertEqual(result["agent_spawns_by_subagent_type"], {})
        everything = self.aggregate()
        self.assertEqual(list(everything["by_day"]), ["2026-10-10", "2026-10-11", "2026-10-12"])

    def test_day_boundaries_follow_the_requested_time_zone(self):
        """This test will fail when days are cut in UTC regardless of --tz."""
        warsaw = audit.Window(None, None, audit.resolve_timezone("Europe/Warsaw"))
        self.assertEqual(warsaw.day_of("2026-10-10T23:30:00.000Z"), "2026-10-11")
        self.assertEqual(self.window().day_of("2026-10-10T23:30:00.000Z"), "2026-10-10")

    def test_spawns_without_subagent_type_are_unspecified_unless_meta_says_otherwise(self):
        """This test will fail when an Agent call without subagent_type is counted as general-purpose."""
        result = self.aggregate()
        self.assertEqual(result["agent_spawns_by_subagent_type"], {
            "worker": 1, "worker-complex": 1, "validator": 1, "general-purpose": 1, "unspecified": 1})
        self.assertEqual(result["agent_spawns_without_subagent_type"], 2)
        self.assertEqual(result["agent_spawns_by_caller"], {"main": 5})
        self.assertEqual(result["agent_model_overrides"], {"general-purpose:haiku": 1})

    def test_cost_is_priced_by_default_per_model(self):
        """This test will fail when the cost ignores the model or the default price table changes."""
        result = self.aggregate()
        opus_calls = [(50, 100), (7, 100), (40, 1000)]  # (output, cache_read) of the three Opus calls
        opus = sum((1 * 4 + out * 20 + read * 0.20 + 20 * 5) / 1e6 for out, read in opus_calls)
        sonnet = sum((1 * 2 + out * 10 + 100 * 0.10 + 20 * 2.50) / 1e6 for out in (30, 4, 2))
        self.assertAlmostEqual(result["by_model"][OPUS]["cost_usd"], opus, places=6)
        self.assertAlmostEqual(result["by_model"][SONNET]["cost_usd"], sonnet, places=6)
        self.assertAlmostEqual(result["totals"]["cost_usd"], opus + sonnet, places=6)
        self.assertEqual(result["unpriced_models"], {})
        self.assertEqual(result["prices"]["fetched"], "2026-10-26")
        self.assertIn("platform.claude.com", result["prices"]["url"])
        self.assertEqual(result["prices"]["overridden_by_config"], [])

    def test_the_priced_share_differs_from_the_token_weighted_share(self):
        """This test will fail when the headline share stays token-weighted and blind to the model."""
        result = self.aggregate()
        entry = result["by_agent"]["worker-complex"]
        self.assertAlmostEqual(entry["share_cost"], entry["cost_usd"] / result["totals"]["cost_usd"], places=3)
        self.assertNotAlmostEqual(entry["share_cost"], entry["share_weighted_cost"], places=2)
        self.assertEqual(list(result["by_agent"]), sorted(result["by_agent"], key=lambda a: -result["by_agent"][a]["cost_usd"]))
        runs = self.runs()
        stats = audit.run_stats(runs, audit.PriceTable())
        head = audit.headline(result, runs, stats, ("worker", "worker-complex"))
        self.assertEqual(head["worker_complex_share_of_cost"], entry["share_cost"])
        self.assertEqual(head["worker_complex_share_of_weighted_cost"], entry["share_weighted_cost"])
        self.assertAlmostEqual(sum(a["share_cost"] for a in result["by_agent"].values()), 1.0, places=2)

    def test_a_config_price_replaces_the_default_for_that_model(self):
        """This test will fail when the config file cannot override the shipped table."""
        prices = audit.PriceTable({OPUS: {"input": 10, "output": 100, "cache_read": 1, "cache_creation": 12.5}})
        priced = self.aggregate(prices=prices)
        opus_calls = [(50, 100), (7, 100), (40, 1000)]
        expected = sum((1 * 10 + out * 100 + read * 1 + 20 * 12.5) / 1e6 for out, read in opus_calls)
        self.assertAlmostEqual(priced["by_model"][OPUS]["cost_usd"], expected, places=6)
        self.assertEqual(priced["prices"]["overridden_by_config"], [OPUS])
        self.assertGreater(priced["by_model"][SONNET]["cost_usd"], 0)

    def test_an_unknown_model_is_unpriced_but_its_tokens_are_counted(self):
        """This test will fail when an unknown model gets a guessed price or drops out of the token counts."""
        self.fixture.subagent("m1", "worker", "t-mystery", [
            {"type": "user", "timestamp": "2026-10-10T14:00:00.000Z", "message": {"content": "go"}},
            assistant("2026-10-10T14:00:10.000Z", "claude-mystery-9", "x-1", usage(output=77)),
        ])
        result = self.aggregate()
        self.assertEqual(result["unpriced_models"], {"claude-mystery-9": 1})
        self.assertEqual(result["by_model"]["claude-mystery-9"]["output"], 77)
        self.assertEqual(result["by_model"]["claude-mystery-9"]["cost_usd"], 0)
        runs = {run["id"]: run for run in self.runs()}
        self.assertEqual(runs["agent-m1"]["cost_usd"], 0)
        self.assertGreater(runs["agent-m1"]["weighted_cost"], 0)

    def test_haiku_5_5_is_priced_by_prompt_length(self):
        """This test will fail when the Haiku 5.5 tier boundary at 100k prompt tokens moves."""
        table = audit.PriceTable()
        small = {"input": 40_000, "output": 1000, "cache_read": 60_000, "cache_creation": 0}  # prompt 100,000
        large = {"input": 40_001, "output": 1000, "cache_read": 60_000, "cache_creation": 0}  # prompt 100,001
        self.assertAlmostEqual(table.cost("claude-haiku-5-5", small), (40_000 * 0.10 + 1000 * 0.50 + 60_000 * 0.01) / 1e6)
        self.assertAlmostEqual(table.cost("claude-haiku-5-5", large), (40_001 * 0.50 + 1000 * 2.50 + 60_000 * 0.05) / 1e6)
        written = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 90_000, "cache_5m": 50_000, "cache_1h": 40_000}
        self.assertAlmostEqual(table.cost("claude-haiku-5-5", written), (50_000 * 0.125 + 40_000 * 0.20) / 1e6)

    def test_haiku_4_5_matches_dated_ids_and_cache_writes_split_by_ttl(self):
        """This test will fail when a dated Haiku 4.5 id is unpriced or one-hour cache writes use the 5-minute rate."""
        table = audit.PriceTable()
        counts = audit.token_counts({"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
                                     "cache_creation_input_tokens": 100,
                                     "cache_creation": {"ephemeral_5m_input_tokens": 60, "ephemeral_1h_input_tokens": 40}})
        self.assertEqual((counts["cache_5m"], counts["cache_1h"]), (60, 40))
        self.assertAlmostEqual(table.cost("claude-haiku-4-5-20251001", counts),
                               (10 * 1 + 20 * 5 + 30 * 0.10 + 60 * 1.25 + 40 * 2) / 1e6)
        plain = audit.token_counts({"cache_creation_input_tokens": 100})
        self.assertNotIn("cache_5m", plain)
        self.assertEqual(audit.cache_split(plain), (100, 0))
        self.assertIsNone(table.lookup("claude-opus-4-1"))

    def test_a_price_key_matches_a_dated_model_id_by_prefix(self):
        """This test will fail when a price for a model family no longer matches its dated ids."""
        prices = audit.PriceTable({"claude-opus-5": {"input": 1}, "claude-opus-5-5": {"input": 2}}, defaults={})
        self.assertEqual(prices.lookup("claude-opus-5-5-20261001"), [(None, {"input": 2.0})])
        self.assertEqual(prices.lookup("claude-opus-5-1"), [(None, {"input": 1.0})])
        self.assertIsNone(prices.lookup("claude-sonnet-5"))


class RunStatisticsTests(AuditTestCase):
    def by_id(self, runs):
        return {run["id"]: run for run in runs}

    def test_every_subagent_run_is_listed_with_its_agent_type_and_prompt(self):
        """This test will fail when a run is dropped, mistyped, or loses its delegation prompt."""
        runs = self.by_id(self.runs())
        self.assertEqual(set(runs), {"agent-w1", "agent-c1", "agent-v1"})
        self.assertEqual(runs["agent-w1"]["agent"], "worker")
        self.assertEqual(runs["agent-w1"]["prompt"], "Implement the thing")
        self.assertTrue(runs["agent-w1"]["prompt_matched"])
        self.assertEqual(runs["agent-v1"]["parent_subagent_type_in_call"], None)
        self.assertEqual(runs["agent-w1"]["final_report"], "Done: 2 files.")
        self.assertEqual(runs["agent-w1"]["final_report_source"], "SubagentHandback")
        self.assertEqual(runs["agent-w1"]["project"], "/work/demo")
        self.assertNotIn("prompt", self.by_id(self.runs(include_prompts=False))["agent-w1"])

    def test_a_run_counts_each_api_call_once_and_edits_each_file_once(self):
        """This test will fail when streaming repeats or repeated edits inflate a run."""
        run = self.by_id(self.runs())["agent-w1"]
        self.assertEqual(run["api_calls"], 2)
        self.assertEqual(run["output_tokens"], 30 + 4)
        self.assertEqual(run["files_edited_total"], 2)
        self.assertEqual(run["files_edited"], ["/work/demo/src/a.ts", "/work/demo/src/b.ts"])
        self.assertEqual(run["top_level_dirs_edited"], ["src"])
        self.assertEqual(self.by_id(self.runs())["agent-c1"]["top_level_dirs_edited"], ["lib"])
        self.assertEqual(run["duration_min"], 2.0)
        self.assertEqual(run["models"], {SONNET: 2})

    def test_full_gate_and_targeted_commands_are_counted_per_run(self):
        """This test will fail when a run's gate and targeted-test counts drift from its Bash commands."""
        runs = self.by_id(self.runs())
        worker = runs["agent-w1"]
        self.assertEqual((worker["bash_calls"], worker["full_gate_calls"], worker["targeted_test_calls"],
                          worker["verification_bash_calls"]), (4, 2, 1, 3))
        complex_run = runs["agent-c1"]
        self.assertEqual((complex_run["full_gate_calls"], complex_run["targeted_test_calls"],
                          complex_run["verification_bash_calls"]), (1, 1, 3))
        validator = runs["agent-v1"]
        self.assertEqual((validator["full_gate_calls"], validator["targeted_test_calls"]), (2, 0))

    def test_runs_are_selected_by_their_start_day(self):
        """This test will fail when the window no longer selects runs by start."""
        runs = self.runs(self.window("2026-10-11", "2026-10-11"))
        self.assertEqual([run["id"] for run in runs], ["agent-c1"])

    def test_statistics_cover_every_agent_type_not_only_the_workers(self):
        """This test will fail when per-type statistics are limited to worker and worker-complex."""
        runs = self.runs()
        stats = audit.run_stats(runs, audit.PriceTable(None))
        self.assertEqual(set(stats), {"worker", "worker-complex", "validator"})
        self.assertEqual(stats["validator"]["count"], 1)
        self.assertEqual(stats["validator"]["full_gate_calls"]["total"], 2)
        self.assertEqual(stats["worker"]["files_edited_median"], 2)
        shares = sum(entry["weighted_cost"]["share_of_subagent_runs"] for entry in stats.values())
        self.assertAlmostEqual(shares, 1.0, places=2)
        self.assertNotIn("cost_usd_total", stats["worker"])

    def test_the_headline_reports_the_plan_metrics(self):
        """This test will fail when the headline numbers the plan tracks are miscomputed."""
        runs = self.runs()
        stats = audit.run_stats(runs, audit.PriceTable(None))
        usage_result = audit.aggregate_usage(self.transcripts(), self.window(), audit.PriceTable(None))
        headline = audit.headline(usage_result, runs, stats, ("worker", "worker-complex"))
        self.assertEqual(headline["implementation_runs"], {"worker": 1, "worker-complex": 1})
        self.assertEqual(headline["worker_complex_share_of_implementation_runs"], 0.5)
        self.assertEqual(headline["median_verification_bash_calls_per_implementation_run"], 3.0)
        self.assertEqual(headline["median_full_gate_calls_per_implementation_run"], 1.5)
        self.assertEqual(headline["general_purpose_spawns"], 1)
        self.assertEqual(headline["unspecified_spawns"], 1)
        self.assertEqual(headline["validator_runs"], 1)
        self.assertEqual(headline["worker_complex_share_of_weighted_cost"],
                         usage_result["by_agent"]["worker-complex"]["share_weighted_cost"])

    def test_run_and_round_costs_use_the_runs_models(self):
        """This test will fail when a run's cost ignores its model or the rounds' costs stop adding up."""
        priced = self.by_id(self.runs())
        self.assertAlmostEqual(priced["agent-c1"]["cost_usd"], (1 * 4 + 40 * 20 + 1000 * 0.20 + 20 * 5) / 1e6, places=6)
        self.assertAlmostEqual(priced["agent-w1"]["cost_usd"], sum((1 * 2 + o * 10 + 100 * 0.10 + 20 * 2.50) / 1e6 for o in (30, 4)), places=6)
        stats = audit.run_stats(self.runs(), audit.PriceTable())
        self.assertAlmostEqual(sum(e["cost_usd"]["share_of_subagent_runs"] for e in stats.values()), 1.0, places=2)
        self.assertEqual(stats["worker"]["cost_usd"]["total"], round(priced["agent-w1"]["cost_usd"], 6))
        override = self.by_id(self.runs(prices=audit.PriceTable({SONNET: {"output": 10}, OPUS: {"output": 100}})))
        self.assertAlmostEqual(override["agent-c1"]["cost_usd"], 40 * 100 / 1e6, places=8)


class RoundsAndWindowTests(AuditTestCase):
    def continued_run(self):
        tool_result = {"type": "user", "timestamp": "2026-10-10T12:00:20.000Z",
                       "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}
        self.fixture.subagent("r1", "worker", "t-continued", [
            {"type": "user", "timestamp": "2026-10-10T12:00:00.000Z", "message": {"content": "Implement the thing"}},
            {"type": "user", "isMeta": True, "timestamp": "2026-10-10T12:00:01.000Z", "message": {"content": "reminder"}},
            {"type": "user", "isMeta": True, "origin": {"kind": "task-notification"}, "timestamp": "2026-10-10T12:00:02.000Z",
             "message": {"content": "<task-notification>done</task-notification>"}},
            assistant("2026-10-10T12:00:10.000Z", SONNET, "r-1", usage(output=5), [
                bash("rb1", "pnpm web:check"), bash("rb2", "pnpm exec vitest run src/a.test.ts"), bash("rb3", "ls")]),
            tool_result,
            {"type": "user", "isMeta": True, "origin": {"kind": "coordinator"}, "timestamp": "2026-10-10T12:05:00.000Z",
             "message": {"content": [{"type": "text", "text": "The coordinator sent a message: web:check failed, fix the types"}]}},
            {"type": "user", "timestamp": "2026-10-10T12:05:30.000Z",
             "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
            assistant("2026-10-10T12:06:00.000Z", SONNET, "r-2", usage(output=6), [
                bash("rb4", "pnpm exec tsc --noEmit"), bash("rb5", "pnpm web:check")]),
        ])
        return next(run for run in self.runs() if run["id"] == "agent-r1")

    def test_a_continued_run_reports_its_rounds_and_their_counts(self):
        """This test will fail when a continuation is not counted as a round or its commands land in the wrong round."""
        run = self.continued_run()
        self.assertEqual(run["rounds"], 2)
        self.assertEqual(run["by_round"], [
            {"round": 1, "api_calls": 1, "cost_usd": round((1 * 2 + 5 * 10 + 100 * 0.10 + 20 * 2.50) / 1e6, 6),
             "weighted_cost": round(1 + 1.25 * 20 + 0.1 * 100 + 5 * 5), "bash_calls": 3,
             "verification_bash_calls": 2, "full_gate_calls": 1, "targeted_test_calls": 1},
            {"round": 2, "api_calls": 1, "cost_usd": round((1 * 2 + 6 * 10 + 100 * 0.10 + 20 * 2.50) / 1e6, 6),
             "weighted_cost": round(1 + 1.25 * 20 + 0.1 * 100 + 5 * 6), "bash_calls": 2,
             "verification_bash_calls": 2, "full_gate_calls": 1, "targeted_test_calls": 0},
        ])
        self.assertEqual((run["bash_calls"], run["full_gate_calls"], run["targeted_test_calls"]), (5, 2, 1))

    def test_an_ordinary_run_is_one_round_and_statistics_report_per_round_counts(self):
        """This test will fail when a run without continuations reports more than one round."""
        self.continued_run()
        runs = self.runs()
        by_id = {run["id"]: run for run in runs}
        self.assertEqual(by_id["agent-w1"]["rounds"], 1)
        self.assertEqual(len(by_id["agent-w1"]["by_round"]), 1)
        stats = audit.run_stats(runs, audit.PriceTable(None))["worker"]
        self.assertEqual(stats["rounds"], {"continued_runs": 1, "max": 2, "total": 3})
        self.assertEqual(stats["per_round"]["verification_bash_calls"]["median"], 2.0)
        usage_result = audit.aggregate_usage(self.transcripts(), self.window(), audit.PriceTable(None))
        head = audit.headline(usage_result, runs, audit.run_stats(runs, audit.PriceTable(None)), ("worker", "worker-complex"))
        self.assertEqual(head["continued_implementation_runs"], 1)

    def test_transcripts_are_counted_only_for_runs_starting_in_the_window(self):
        """This test will fail when the transcript count includes runs that started outside the window."""
        result = audit.aggregate_usage(self.transcripts(), self.window("2026-10-11", "2026-10-11"), audit.PriceTable(None))
        self.assertEqual(result["by_agent"]["worker-complex"]["transcripts"], 1)
        self.assertEqual(result["by_agent"]["main"]["transcripts"], 0)
        full = audit.aggregate_usage(self.transcripts(), self.window(), audit.PriceTable(None))
        self.assertEqual(full["by_agent"]["main"]["transcripts"], 1)

    def test_a_subagent_without_a_type_in_its_meta_file_is_unspecified(self):
        """This test will fail when an unknown agent type gets a second label."""
        self.fixture.subagent("n1", None, "t-none", [
            {"type": "user", "timestamp": "2026-10-10T13:00:00.000Z", "message": {"content": "go"}},
            assistant("2026-10-10T13:00:10.000Z", SONNET, "n-1", usage(output=1)),
        ])
        runs = {run["id"]: run for run in self.runs()}
        self.assertEqual(runs["agent-n1"]["agent"], audit.UNSPECIFIED)
        result = audit.aggregate_usage(self.transcripts(), self.window(), audit.PriceTable(None))
        self.assertIn(audit.UNSPECIFIED, result["by_agent"])
        self.assertNotIn("unknown", result["by_agent"])
        self.assertEqual(result["agent_spawns_by_subagent_type"]["unspecified"], 1)


class TimeZoneTests(unittest.TestCase):
    def test_the_local_zone_follows_daylight_saving_per_timestamp(self):
        """This test will fail when day boundaries use one fixed offset for the whole window."""
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset is not available")
        previous = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", previous) if previous is not None else os.environ.pop("TZ", None), time.tzset()))
        os.environ["TZ"] = "Europe/Warsaw"
        time.tzset()
        if time.tzname[0] != "CET":
            self.skipTest("the time zone database has no Europe/Warsaw")
        window = audit.Window(None, None, audit.resolve_timezone(None), audit.zone_label(None))
        self.assertEqual(window.day_of("2026-01-31T22:30:00.000Z"), "2026-01-31")  # CET, UTC+1
        self.assertEqual(window.day_of("2026-07-31T22:30:00.000Z"), "2026-08-01")  # CEST, UTC+2
        self.assertEqual(window.label, "Europe/Warsaw (system local zone)")
        bounded = audit.Window(datetime.date(2026, 8, 1), datetime.date(2026, 8, 1), None)
        self.assertTrue(bounded.contains("2026-07-31T22:30:00.000Z"))
        self.assertFalse(bounded.contains("2026-01-31T22:30:00.000Z"))

    def test_a_named_zone_is_reported_by_name(self):
        """This test will fail when the output stops naming the zone it cut days in."""
        self.assertEqual(audit.zone_label("UTC"), "UTC")
        self.assertEqual(audit.zone_label("Europe/Warsaw"), "Europe/Warsaw")


class CommandLineTests(AuditTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = audit.main([*args])
        return code, out.getvalue(), err.getvalue()

    def test_a_run_writes_the_documented_files_outside_the_repository(self):
        """This test will fail when the CLI stops writing its outputs to --out."""
        out = self.root / "out" / "nested"
        code, stdout, _ = self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(out),
                                       "--since", "2026-10-10", "--until", "2026-10-12", "--tz", "UTC")
        self.assertEqual(code, 0)
        names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        self.assertEqual(names, ["headline.json", "review/batch_1.jsonl", "review/batch_2.jsonl", "review/batch_3.jsonl",
                                 "review/batch_4.jsonl", "run_stats.json", "runs.jsonl", "usage.json"])
        usage_data = json.loads((out / "usage.json").read_text())
        self.assertEqual(usage_data["date_range"]["since"], "2026-10-10")
        self.assertEqual(len((out / "runs.jsonl").read_text().splitlines()), 3)
        self.assertIn("worker-complex", stdout)
        self.assertIn("wrote 8 files", stdout)

    def test_review_batches_split_one_agent_type_evenly(self):
        """This test will fail when the review batches lose a run or include another agent type."""
        out = self.root / "out"
        self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(out), "--quiet", "--tz", "UTC",
                     "--review-agent", "worker", "--batches", "2")
        batches = [(out / "review" / f"batch_{i}.jsonl").read_text().splitlines() for i in (1, 2)]
        self.assertEqual([len(b) for b in batches], [0, 1])
        self.assertNotIn('"agent"', batches[1][0])
        self.assertEqual(json.loads(batches[1][0])["id"], "agent-w1")
        out2 = self.root / "out2"
        self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(out2), "--quiet", "--review-agent", "")
        self.assertFalse((out2 / "review").exists())

    def test_the_default_output_directory_is_dated_under_the_state_directory(self):
        """This test will fail when the default --out moves away from ~/.local/state/agent-orchestration/audits/<date>/."""
        home = self.root / "home"
        home.mkdir()
        environment = {**os.environ, "HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(MODULE), "--projects-dir", str(self.fixture.projects), "--quiet", "--tz", "UTC"],
            capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        audits = home / ".local" / "state" / "agent-orchestration" / "audits"
        directories = list(audits.iterdir())
        self.assertEqual(len(directories), 1)
        self.assertRegex(directories[0].name, r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue((directories[0] / "usage.json").is_file())

    def test_usage_errors_exit_with_a_message_and_no_traceback(self):
        """This test will fail when a bad argument produces a traceback or a zero exit."""
        cases = [
            ("--since", "10-10-2026"),
            ("--since", "2026-10-12", "--until", "2026-10-10"),
            ("--tz", "Not/AZone"),
            ("--config", str(self.root / "nope.toml")),
            ("--projects-dir", str(self.root / "nope")),
            ("--implementation-agents", ","),
        ]
        for args in cases:
            with self.subTest(args=args):
                code, _, err = self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(self.root / "o"),
                                            *args)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("usage-audit: "), err)
                self.assertNotIn("Traceback", err)

    def test_prices_are_default_and_the_config_file_overrides_them(self):
        """This test will fail when the CLI stops pricing by default or ignores the config's price table."""
        config = self.root / "audit.toml"
        config.write_text(f'[prices."{OPUS}"]\ninput = 15\noutput = 75\n')
        plain, priced = self.root / "plain", self.root / "priced"
        self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(plain), "--quiet")
        self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(priced), "--quiet", "--config", str(config))
        plain_usage = json.loads((plain / "usage.json").read_text())
        priced_usage = json.loads((priced / "usage.json").read_text())
        self.assertGreater(plain_usage["totals"]["cost_usd"], 0)
        self.assertEqual(plain_usage["unpriced_models"], {})
        self.assertEqual(priced_usage["prices"]["overridden_by_config"], [OPUS])
        self.assertGreater(priced_usage["by_model"][OPUS]["cost_usd"], plain_usage["by_model"][OPUS]["cost_usd"])
        self.assertIn("worker_complex_share_of_cost", json.loads((plain / "headline.json").read_text()))
        self.assertIn("$", self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(plain))[1])

    def test_output_inside_the_repository_is_refused(self):
        """This test will fail when --out can point into the repository, where prompts and paths could be committed."""
        for target in (ROOT / "audit-output-should-not-exist", ROOT, ROOT / "audit" / "out", ROOT / "x" / ".." / "y"):
            with self.subTest(target=str(target)):
                code, _, err = self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(target), "--quiet")
                self.assertEqual(code, 2)
                self.assertIn("inside the repository", err)
        self.assertFalse((ROOT / "audit-output-should-not-exist").exists())
        self.assertFalse((ROOT / "audit" / "out").exists())
        code, _, _ = self.run_cli("--projects-dir", str(self.fixture.projects), "--out", str(self.root / "fine"), "--quiet")
        self.assertEqual(code, 0)

    def test_the_wrapper_uses_the_python_named_by_the_environment(self):
        """This test will fail when scripts/usage-audit stops honoring PYTHON like scripts/check does."""
        environment = {**os.environ, "AGENT_ORCHESTRATION_UV_RUN": "1"}
        good = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True, env={**environment, "PYTHON": sys.executable})
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn("--since", good.stdout)
        bad = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True, env={**environment, "PYTHON": "/bin/false"})
        self.assertEqual(bad.returncode, 2)
        self.assertIn("Python 3.11+ is required", bad.stderr)

    def test_the_entrypoint_script_runs_the_module(self):
        """This test will fail when scripts/usage-audit stops being an executable entrypoint."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertIn("audit/usage_audit.py", SCRIPT.read_text())
        result = subprocess.run([sys.executable, str(MODULE), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        for flag in ("--since", "--until", "--out"):
            self.assertIn(flag, result.stdout)

    def test_the_tool_hardcodes_no_home_or_session_paths(self):
        """This test will fail when a user's home directory or a session path is written into the tool."""
        source = MODULE.read_text() + (ROOT / "audit" / "README.md").read_text()
        for needle in ("/Users/", ".t3/scratch", "/home/"):
            self.assertNotIn(needle, source)


if __name__ == "__main__":
    unittest.main()
