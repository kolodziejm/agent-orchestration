# Usage audit

`scripts/usage-audit` reads the Claude Code transcripts on this machine and answers
three questions: where the tokens go, which agent types are started, and how much
verification each implementation run does. It needs only Python 3.11 or newer and the
standard library. It is the measuring tool behind
[`docs/subagent-routing-cost-plan.md`](../docs/subagent-routing-cost-plan.md).

Transcripts and the files the tool writes hold prompts, file paths, and project names.
Keep the output outside this repository and do not commit it.

## Run it

```bash
./scripts/usage-audit --since 2026-10-10 --until 2026-10-23 --out ~/audits/baseline
./scripts/usage-audit --since 2026-10-24 --until 2026-11-06      # default --out
```

| Flag | Meaning |
| --- | --- |
| `--since`, `--until` | First and last local day, inclusive, `YYYY-MM-DD`. Either may be left out. |
| `--out` | Output directory. Default `~/.local/state/agent-orchestration/audits/<today>/`. |
| `--projects-dir` | Transcript directory. Default `~/.claude/projects`. |
| `--tz` | IANA zone for day boundaries (`UTC`, `Europe/Warsaw`). Default the local zone. |
| `--config` | TOML file with command patterns and an optional price table (below). |
| `--full-gate`, `--targeted` | A regular expression; repeat to replace the default list for that class. |
| `--implementation-agents` | Agent types counted as implementation runs. Default `worker,worker-complex`. |
| `--review-agent`, `--batches` | Split this agent type's runs into review batches. Default `worker-complex`, 4. |
| `--no-prompts` | Leave the delegation prompts out of `runs.jsonl`. |
| `--quiet` | Do not print the summary table. |

A call counts when its timestamp falls in the window; a run counts when it starts in
it, with all its calls. Streaming repeats of one message (same message id and request
id) count once with the largest output.

## Output

| File | Content |
| --- | --- |
| `usage.json` | Tokens and weighted cost by agent type, model, day, project, and session; the model each agent type ran on each day; tool usage; spawns by `subagent_type`; model overrides. |
| `runs.jsonl` | One line per subagent run: type, duration, models, API calls, weighted cost, edited files, Bash calls, full-gate and targeted test calls, the delegation prompt, and the final report. |
| `run_stats.json` | Per agent type: run count, share of subagent cost, median and 90th percentile of calls, cost, files, and verification commands. |
| `headline.json` | The numbers the plan tracks: the `worker-complex` share of cost and of implementation runs, median verification calls per implementation run, and `general-purpose` and unspecified spawns. |
| `review/batch_N.jsonl` | The review agent's runs for the verdict pass. |

Weighted cost is relative and model-agnostic: input 1, cache write 1.25, cache read
0.1, output 5. It does not tell Opus from Sonnet; use a price table for that.

An `Agent` call without `subagent_type` is counted under the type the subagent's
`.meta.json` records, else as `unspecified`. It is never counted as `general-purpose`
on its own.

### Verification commands

A Bash command counts once. A **full gate** is `web:check`, `i18n:check`,
`scripts/check`, or a test runner (jest, vitest, pest, `artisan test`, `cargo test`,
pytest, unittest, `npm test`) with no file, test name, or package named. A
**targeted** run is a test runner that names a test file, a `tests/` path, `--filter`,
`-t`, `-k`, or a cargo package. `verification_bash_calls` is broader: it adds every
command that mentions test, lint, tsc, build, and the like. Override the patterns with
`--full-gate` and `--targeted`, or in the config file:

```toml
[commands]
full_gate = ['\bweb:check\b', '(^|[\s/])scripts/check\b']
runners = ['\b(jest|vitest|pest)\b', '\bartisan\s+test\b']
targeted = ['\S+\.(test|spec)\.[jt]sx?\b', '--filter\b']
verification = 'test|lint|tsc|build'
```

### Prices

Costs in USD appear only when the config file has a `[prices.<model>]` table, in USD
per million tokens. The tool ships no prices. A key also matches longer model ids that
start with it, and models without a price are listed under `unpriced_models`.

```toml
# Fill in from your own price list.
# [prices."claude-opus-5-5"]
# input = 0
# output = 0
# cache_read = 0
# cache_creation = 0
```

## Verdict rubric

The verdict pass reads each `worker-complex` run in `review/batch_N.jsonl` (prompt,
files, tool counts, final report) and decides whether `worker` would have been
enough. Give each batch to a reviewer with this rubric and one rule: size, file count,
and brief length are not evidence of difficulty.

| Verdict | Criteria |
| --- | --- |
| `JUSTIFIED` | The approach was not settled and needed hard reasoning: auth and security, a bug with an unknown root cause, a merge that keeps both sides' intent, an algorithm, concurrency, or a state machine. |
| `BORDERLINE` | Mostly settled work with one hard part, or a brief a careful `worker` might have handled; the run does not show which. |
| `WORKER_ENOUGH` | The approach was settled by a plan, an existing pattern, or an explicit list: a repetitive series following an established idiom, a plan-driven UI slice, copy, theme, or CRUD work, a list of review fixes, docs or specs. |
| `OTHER_AGENT` | The run was not implementation: it investigated, reviewed, or verified, which `debugger`, `explorer`, `reviewer`, or `validator` does. |

Ask the reviewer for one JSON line per run:

```json
{"id": "agent-a1b2c3", "verdict": "WORKER_ENOUGH", "reason": "one sentence naming the evidence"}
```

Store the lines as `verdicts_N.jsonl` beside the batches. The share of a verdict is
its count, or its summed `weighted_cost`, over all reviewed runs:

```bash
jq -s --slurpfile runs runs.jsonl \
  '($runs | map({(.id): .weighted_cost}) | add) as $cost
   | group_by(.verdict)
   | map({verdict: .[0].verdict, runs: length, cost: (map($cost[.id] // 0) | add)})' verdicts_*.jsonl
```

Review a re-audit with the same rubric, so the shares stay comparable. Compare a
verdict that changed after the rules changed, not only the totals.
