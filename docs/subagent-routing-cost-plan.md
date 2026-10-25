# Subagent routing and cost — approved goal: implementation goes to the cheaper `worker` unless the work needs hard reasoning, and full verification gates run once, in `validator`.

**Trigger:** a usage audit of 2026-10-10 → 2026-10-23 (aggregate numbers only; no project names, prompts, or session ids are kept here). `worker-complex` (Opus, xhigh) carried about 63% of the weighted cost, and most of that went to work `worker` could have done.

**Non-goals:** no hooks or other enforcement (text policy only); no role body or prompt text in agent definitions (the bodies stay empty, enforced by `tests/test_agent_definition_contract.py`); no change to the other roles' models.

## Audit summary

- `worker-complex` = about 63% of weighted cost (input 1, cache write 1.25, cache read 0.1, output 5; model-agnostic) and about 41% of implementation runs (`worker` plus `worker-complex`).
- 129 `worker-complex` runs reviewed by hand against a rubric (see `audit/README.md`):

| Verdict | Runs | Share of the cost of those runs |
| --- | --- | --- |
| JUSTIFIED | 33 | 45% |
| BORDERLINE | 48 | 34% |
| WORKER_ENOUGH | 46 (36% of runs) | 21% |
| OTHER_AGENT | 2 | — |

- Unneeded `worker-complex`: repetitive series that follow an established idiom (an i18n PR series), plan-driven UI slices, copy, theme, and CRUD work, explicit review-fix lists, docs and specs.
- Justified: auth and security, bugs with an unknown root cause, merges that keep both sides' intent, algorithms, concurrency, state machines.
- The choice tracked brief length and file count, not difficulty.
- The main cost driver is verification: up to 70 to 300 test and build Bash calls in the costliest runs, full gates re-run repeatedly.
- The built-in `general-purpose` agent was started 53 times although the policy prefers roles.

## Decisions (owner, 2026-10-23)

1. Agent bodies stay empty. The rules live only in `policy/orchestration.md` and the `policy/routing.toml` descriptions.
2. `validator` always runs the full gates, once per deliverable (a PR, or a batch that lands together), whoever made the change. Full gates are the project's complete documented checks: the full test suite, lint, typecheck, and build. Implementers (`worker`, `worker-complex`) run only targeted checks while working: the affected tests and the package typecheck.
3. When `validator` reports FAIL, the primary agent continues the same implementer with the validator's report, which keeps its context. If the harness cannot continue it, a new run of the same role gets the original brief, the current diff, and the report, and counts as the next round. At most 2 implement → validate rounds: the first implementation and its validation are round 1, and if `validator` still reports a failure in round 2 the primary agent stops and asks the user. It moves to another role (for example `worker` to `worker-complex`) only after asking.
4. A bug with an unknown root cause goes straight to `worker-complex`. `worker` is the default implementer for everything else, including large changes; when the approach is not settled, the primary agent settles it first, itself or with `planner`, and puts it in the brief.
5. `worker-complex` effort drops from `xhigh` to `high` now, in its own commit.
6. The audit tooling lives in this repository. Code, tests, and the rubric are committed; audit outputs stay outside it.
7. No hooks and no enforcement.

## Units (status; dependencies)

**A — This plan:** completed; deps: none. **B — Audit tool (`audit/`, `scripts/usage-audit`, `tests/test_usage_audit.py`):** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS); deps: A. **C — Routing descriptions and verification policy (`policy/routing.toml`, `policy/orchestration.md`, `profiles/claude.md`):** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS); deps: none. **D — `worker-complex` effort `xhigh` → `high` (`profiles/claude.toml`):** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS); deps: none.

Each unit ends with `uv run --locked ./scripts/check`, one `CHANGELOG.md` "## Unreleased" bullet, and the README updated where it applies. The final check also runs `./scripts/install-claude-code --dry-run`; installing happens after merge.

## Metrics and re-audit

Re-audit on or about 2026-11-06 with `./scripts/usage-audit --since 2026-10-24 --until 2026-11-06` and the same review rubric.

| Metric | Baseline | Target |
| --- | --- | --- |
| `worker-complex` share of weighted cost | 63% | ≤ 35% |
| `worker-complex` share of implementation runs | 41% | ≤ 20% |
| WORKER_ENOUGH share of `worker-complex` runs | 36% | < 10% |
| Median test and build Bash calls per implementation run | 6 | −50% (≤ 3) |
| `general-purpose` spawns | 53 | ≤ 5 |

Baseline measured with `./scripts/usage-audit --since 2026-10-10 --until 2026-10-23`, using the segment-based command classifier of `audit/usage_audit.py` as committed in this PR (a later change to the classifier needs a re-run of the baseline): 63% of weighted cost, 41% of 320 implementation runs (131 `worker-complex`, 189 `worker`; the hand review covered 129 of those `worker-complex` runs), 53 `general-purpose` spawns, none unspecified. Per implementation run the median is 6 test, lint, and build Bash calls (mean 12.0), of which the median is 2 full gates (mean 2.4) and 2 targeted test runs. 64 of the 320 implementation runs (19 `worker`, 45 `worker-complex`) were continued, 85 of 758 subagent runs in all; per round the median is 5 verification calls for an implementation run (2 for `worker`, 12 for `worker-complex`). A continuation is a coordinator message (`origin.kind` `coordinator`) in the run's own transcript. A call counts as verification only when a command segment starts with a test runner, a lint, typecheck, or build tool, or a gate, so reading a test file or a directory named `tests` does not count; calls through wrapper scripts the tool does not know go uncounted.

Quality guardrails, which must not get worse: the `validator` FAIL rate, review-fix rounds per series, and escalations approved by the user after a stop. The audit tool does not compute them: `validator` reports are free-form, so a FAIL cannot be detected reliably. Read the validator reports and the continued runs (`rounds` in `runs.jsonl`) by hand at the re-audit.

The rules (C) and the effort change (D) land together, so compare per task category rather than in total. Tasks that moved to `worker` show the rules effect. The per-run cost of auth, bug, and merge tasks that stay on `worker-complex` shows the effort effect.

## Risks

- A task the primary agent files under "settled approach" turns out hard: `worker` fails validation twice, and the escalation the user approves shows it.
- Sonnet at high effort is slower on a large settled change; run time is not a metric here.
- Moving full gates to `validator` adds a handoff; the 2-round cap and the targeted checks keep it bounded.

## Canonical references: [policy](../policy/orchestration.md) · [routing](../policy/routing.toml) · [claude profile](../profiles/claude.toml) · [README](../README.md)
