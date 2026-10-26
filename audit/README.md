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
| `--out` | Output directory. Default `~/.local/state/agent-orchestration/audits/<today>/`. A path inside this repository is refused. |
| `--projects-dir` | Transcript directory. Default `~/.claude/projects`. |
| `--tz` | IANA zone for day boundaries (`UTC`, `Europe/Warsaw`). Default the system's local zone, with daylight saving applied to each timestamp; `usage.json` names the zone it used. |
| `--config` | TOML file with command patterns and an optional price table (below). |
| `--full-gate`, `--targeted` | A regular expression; repeat to replace the default list for that class. |
| `--implementation-agents` | Agent types counted as implementation runs. Default `worker,worker-complex`. |
| `--review-agent`, `--batches` | Split this agent type's runs into review batches. Default `worker-complex`, 4. |
| `--no-prompts` | Leave the delegation prompts out of `runs.jsonl`. |
| `--quiet` | Do not print the summary table. |

A call counts when its timestamp falls in the window; a run, and the per-agent
`transcripts` count, count when the run starts in it, with all its calls. Streaming repeats of one message (same message id and request
id) count once with the largest output.

## Output

| File | Content |
| --- | --- |
| `usage.json` | Tokens, priced cost (`cost_usd`, `share_cost`), and token-weighted cost by agent type, model, day, project, and session; the model each agent type ran on each day; tool usage; spawns by `subagent_type`; model overrides. |
| `runs.jsonl` | One line per subagent run: type, duration, models, API calls, weighted cost, edited files, Bash calls, `cost_usd`, full-gate and targeted test calls, `rounds` and the same counts `by_round`, the delegation prompt, and the final report. |
| `run_stats.json` | Per agent type: run count, share of subagent cost, median and 90th percentile of calls, cost, files, and verification commands, per run and per round, and how many runs were continued. |
| `headline.json` | The numbers the plan tracks: the `worker-complex` share of cost and of implementation runs, median and mean verification calls per implementation run, `general-purpose` and unspecified spawns. |
| `review/batch_N.jsonl` | The review agent's runs for the verdict pass. |

Cost is priced per call from the model's rates (see Prices) and is the headline:
`cost_usd` and `share_cost`. Weighted cost is the secondary, model-agnostic figure: input 1,
cache write 1.25, cache read 0.1, output 5. It does not tell Opus from Sonnet.

An `Agent` call without `subagent_type` is counted under the type the subagent's
`.meta.json` records, else as `unspecified`. It is never counted as `general-purpose`
on its own. `unspecified` is the one label for an unknown type everywhere: a spawn
with no type and no meta file, and a subagent transcript whose meta file names none.

### Rounds

A continued subagent appends to the same `agent-*.jsonl`. A user record that carries
text starts a round: the brief, and each message the coordinator sends later (stored
as a meta record with `origin.kind` `coordinator`). Tool results, other meta records
(system reminders), compaction summaries, interruption notices, background-task
notifications (`origin.kind` `task-notification`), and peer messages do not. A run's
`rounds` is 1 plus its continuations, and each API call and Bash command is counted
in the round it happened in (`by_round`). Round 1 is the brief and the work it triggered, the same convention as the policy's
implement and validate rounds.

### Verification commands

A Bash call is split into segments at unquoted `&&`, `||`, `;`, `|`, `&`, parentheses,
and newlines; here-document bodies and quoted text are not commands. Each segment is
stripped of what runs the command: environment assignments, `time`, `npx`,
`pnpm exec`, `corepack`, `uv run`, `php`, `python -m`, `docker exec`, `sail`,
`sh -c`, and `*.sh` wrappers in front of a known tool. A runner counts only at the
start of a segment, so `cat jest.config.js`, `rg vitest`, `uv add --dev pytest`, and
`git commit -m "add tests"` match nothing. A package-manager script is read as
`<pm> run <script>`: `pnpm web:check` is `pnpm run web:check` and `npm test` is
`npm run test`. A call counts once, and a full gate wins over a targeted run.

- A **full gate** is `web:check`, `i18n:check`, `scripts/check` (not `check-browser`),
  or a test runner (jest, vitest, pest, phpunit, `artisan test`, `cargo test`, pytest,
  unittest, `go test`, `npm test`) that names nothing in particular.
- A run is **targeted** when an argument is a path, a file, or a test name (`src/components`,
  `tests/Feature`, `a.test.ts`), or it has `--filter`, `-t`, `-k`, a cargo package, or a
  package-manager `--filter`, `-F`, or `--workspace` (`pnpm --filter web test`).
- `verification_bash_calls` also counts the lint, typecheck, and build tools (`tsc`,
  `eslint`, `pint`, `xcodebuild`, `npm run lint`, `npm run build`, `cargo clippy`, and the like).

A wrapper script the tool does not know (`$S/dm php artisan test`, `$D pnpm test`) is
not looked through, so such calls go uncounted; add a pattern for them. Override the
patterns with `--full-gate` and `--targeted`, or in the config file. They are matched
against the normalized segment, for example `pnpm run web:check` or `pest tests/Feature`:

```toml
[commands]
full_gate = ['^(npm|pnpm|yarn|bun) run (web|i18n):check(\s|$)', '^(\S*/)?scripts/check(\s|$)']
runners = ['^(\S*/)?(jest|vitest|pest)(\s|$)', '^(\S*/)?artisan test(\s|$)']
targeted = ['--filter\b', '(^|\s)-t\s']
verification = '^(\S*/)?(tsc|eslint)(\s|$)'
```

### Prices

Cost is priced by default from a table in `audit/usage_audit.py` (USD per million
tokens, from <https://platform.claude.com/docs/en/about-claude/pricing>, fetched
2026-10-26; `usage.json` records the source). A call is priced from its own tokens:
input, output, cache reads, and cache writes, split into 5-minute and 1-hour writes
when the transcript says so (`usage.cache_creation`), else all 5-minute. Rates of a
model id also apply to its dated ids (`claude-haiku-4-5-20251001`). Haiku 5.5 has two
tiers by the request's prompt (input, cache read, and cache write tokens): up to 100k
and above. Batch and fast-mode pricing are not modelled, so an audit of such usage
overstates it.

| Model | Input | Cache write 5m | Cache write 1h | Cache read | Output |
| --- | --- | --- | --- | --- | --- |
| `claude-opus-5-5` | 4 | 5 | 8 | 0.20 | 20 |
| `claude-sonnet-5-5` | 2 | 2.50 | 4 | 0.10 | 10 |
| `claude-haiku-5-5`, prompt up to 100k | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 |
| `claude-haiku-5-5`, prompt over 100k | 0.50 | 0.625 | 1 | 0.05 | 2.50 |
| `claude-haiku-4-5` | 1 | 1.25 | 2 | 0.10 | 5 |

A model that is not in the table is reported under `unpriced_models` (calls per model):
its tokens are counted, its cost is 0, and nothing is guessed. Rates change; check the
table against the pricing page before an audit, and replace or add a model in the
config file. An entry there replaces the default for that model id (it has no tiers;
`cache_creation` sets both cache-write rates):

```toml
[prices."claude-sonnet-5-5"]
input = 2
output = 10
cache_read = 0.10
cache_write_5m = 2.50
cache_write_1h = 4
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

Store the lines as `review/verdicts_N.jsonl` beside the batches. The share of a verdict
is its count, or its summed `weighted_cost`, over all reviewed runs. From the output
directory:

```bash
cd ~/audits/baseline
jq -s --slurpfile runs runs.jsonl \
  '($runs | map({(.id): .weighted_cost}) | add) as $cost
   | group_by(.verdict)
   | map({verdict: .[0].verdict, runs: length, cost: (map($cost[.id] // 0) | add)})' review/verdicts_*.jsonl
```

Review a re-audit with the same rubric, so the shares stay comparable. Compare a
verdict that changed after the rules changed, not only the totals.

## What the tool does not measure

The `validator` FAIL rate, review-fix rounds per series, and escalations approved by
the user need a reading of the reports and the conversation: a `validator` report is
free-form, so a FAIL cannot be told from a PASS reliably. Read the `final_report` of
the validator runs and the continued runs (`rounds` above 1) at a re-audit.
