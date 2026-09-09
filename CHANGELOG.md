# Changelog

All notable changes to the orchestration policy are documented here.

## Unreleased

- Add a simple Codex renderer for the ten role contracts using the OpenAI profile's model, reasoning, and sandbox mappings.
- Render and check committed OpenCode and Codex snapshots; Codex artifacts are copied or symlinked manually without an installer.
- Make reviewer participation explicitly user-directed, while retaining independent validation for code and behavior changes.
- Require observable acceptance evidence, bounded review-fix cycles, compact handoffs, event-based orchestration updates, and lightweight pilot usage measurements.
- Add a Claude Code adapter (`adapters/claude-code/`) mirroring the OpenCode adapter's rendering, snapshot, diff, backup, install, and rollback architecture.
- Add a `claude` model-routing profile (`profiles/claude.toml` + `profiles/claude.md`) with per-role Claude model aliases and effort levels.
- Add a `harness` field to profile files (defaulting to `opencode` for backward compatibility): the OpenCode renderer selects profiles declaring `harness = "opencode"`, the Claude Code renderer selects the single profile declaring `harness = "claude-code"`, and the Codex renderer selects by explicit `--profile` without reading `harness`, so the `openai` profile is rendered by both OpenCode and Codex.
- Bake model and effort directly into each rendered Claude Code subagent's frontmatter, since Claude Code has no profile-routing layer equivalent to OpenCode's `agent-routing.json`.
- Express routing delegation as `Agent(<target>)` tool entries and document that Claude Code has no per-subagent equivalent of `bash = "ask"`.
- Merge the shared orchestration policy into a target `CLAUDE.md` using `<!-- agent-orchestration:start -->` / `<!-- agent-orchestration:end -->` markers, preserving unrelated content.
- Commit the `generated/claude-code/` snapshot and extend `scripts/render` and `scripts/check` to cover it.
- Clarify the definition of a trivial request, when validator involvement is mandatory, what counts as explicit review authorization, the one-sentence non-blocking form of the review recommendation, and the per-finding repair budget in the reviewer user-verdict gate.
- Document Claude Code subagent history defaults, the `Agent` tool's `model` parameter restriction, and built-in harness agent usage constraints in the Claude Code adapter README and the `claude` profile addendum.
- Render the active profile's addendum into the shared `orchestration-core.md` section, after the policy text, so installed `CLAUDE.md` files receive the Claude Code harness notes that were previously never rendered.
- Align mandatory-validation scope, the reviewer repair-budget cap, and the orchestrator's trivial-work exception with their surrounding rules, removing internal contradictions in the shared policy.
- Invoke `python3` instead of a hardcoded `python3.11` in every script and adapter shebang, relying on the caller's environment (e.g. CI's `actions/setup-python`) to provide 3.11+; each renderer fails fast with a clear message if run under an older interpreter.
- Fix the Codex renderer's default `--output` being resolved at import time, which bypassed the symlink guard for a symlinked `generated/codex` when no `--output` flag was passed; it now matches the unresolved-default pattern already used by the Claude Code and OpenCode renderers.

## 0.1.0 — 2026-08-22

- Establish a harness-agnostic policy and role-contract source of truth.
- Add OpenAI, GLM, and OpenCode Go model-routing profiles.
- Add routine `worker` and difficult-reasoning `worker-complex` tiers.
- Allow planner to delegate repository evidence to `explorer` and planning-artifact production to `spec-writer`.
- Keep reviewer read-only with explorer-only nested delegation and an explicit user-verdict gate.
- Separate worker self-checks from independent validator evidence.
- Add a single automatic repair-cycle budget and risk-based mandatory review.
- Add OpenCode rendering, snapshot, diff, backup, install, rollback, and profile-validation tooling.
- Track managed roles with a local manifest so obsolete generated roles can be removed safely.
- Preserve unrelated harness instructions and custom agents during installation.
- Restrict renderer replacement to the committed snapshot destination or temporary directories.
- Require confirmation for validator/debugger shell commands to keep read-only enforcement outside the prompt layer.
- Reject symlinked managed destinations before reading or displaying their contents.
- Remove all managed agents and artifacts when a profile leaves the policy.
- Roll back interrupted installs, including `KeyboardInterrupt` during mutation or validation.
- Restore the previous generated snapshot if atomic renderer replacement is interrupted.
