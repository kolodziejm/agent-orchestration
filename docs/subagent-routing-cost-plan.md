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
- The main cost driver is verification: 70 to 300 test and build Bash calls per run, full gates re-run repeatedly.
- The built-in `general-purpose` agent was started 53 times although the policy prefers roles.

## Decisions (owner, 2026-10-23)

1. Agent bodies stay empty. The rules live only in `policy/orchestration.md` and the `policy/routing.toml` descriptions.
2. `validator` always runs the full gates. Implementers (`worker`, `worker-complex`) run only targeted checks while working: the affected tests and the package typecheck.
3. When `validator` reports FAIL, the primary agent continues the same implementer with the validator's report, which keeps its context. At most 2 implement → validate rounds; then it stops and asks the user.
4. A bug with an unknown root cause goes straight to `worker-complex`.
5. `worker-complex` effort drops from `xhigh` to `high` now, in its own commit.
6. The audit tooling lives in this repository. Code, tests, and the rubric are committed; audit outputs stay outside it.
7. No hooks and no enforcement.

## Units (status; dependencies)

**A — This plan:** completed; deps: none. **B — Audit tool (`audit/`, `scripts/usage-audit`, `tests/test_usage_audit.py`):** completed (`PYTHON=.venv/bin/python ./scripts/check` PASS); deps: A. **C — Routing descriptions and verification policy (`policy/routing.toml`, `policy/orchestration.md`, `profiles/claude.md`):** pending; deps: none. **D — `worker-complex` effort `xhigh` → `high` (`profiles/claude.toml`):** pending; deps: none.

Each unit ends with `uv run --locked ./scripts/check`, one `CHANGELOG.md` "## Unreleased" bullet, and the README updated where it applies. The final check also runs `./scripts/install-claude-code --dry-run`; installing happens after merge.

## Metrics and re-audit

Re-audit on or about 2026-11-06 with `./scripts/usage-audit --since 2026-10-24 --until 2026-11-06` and the same review rubric.

| Metric | Baseline | Target |
| --- | --- | --- |
| `worker-complex` share of weighted cost | 63% | ≤ 35% |
| `worker-complex` share of implementation runs | 41% | ≤ 20% |
| WORKER_ENOUGH share of `worker-complex` runs | 36% | < 10% |
| Median test and build Bash calls per implementation run | 34 | −50% (≤ 17) |
| `general-purpose` spawns | 53 | ≤ 5 |

Baseline measured with `./scripts/usage-audit --since 2026-10-10 --until 2026-10-23`: 63% of weighted cost, 41% of 320 implementation runs (131 `worker-complex`, 189 `worker`; the hand review covered 129 of those `worker-complex` runs), 53 `general-purpose` spawns, none unspecified. Per implementation run the median is 34 test, lint, and build Bash calls, of which 4 are full gates and 2 are targeted test runs.

Quality guardrails, which must not get worse: the `validator` FAIL rate, review-fix rounds per series, and re-delegations from `worker` to `worker-complex`.

The rules (C) and the effort change (D) land together, so compare per task category rather than in total. Tasks that moved to `worker` show the rules effect. The per-run cost of auth, bug, and merge tasks that stay on `worker-complex` shows the effort effect.

## Risks

- A task the primary agent files under "settled approach" turns out hard: `worker` fails, and the re-delegation counter shows it.
- Sonnet at high effort is slower on a large settled change; run time is not a metric here.
- Moving full gates to `validator` adds a handoff; the 2-round cap and the targeted checks keep it bounded.

## Canonical references: [policy](../policy/orchestration.md) · [routing](../policy/routing.toml) · [claude profile](../profiles/claude.toml) · [README](../README.md)
