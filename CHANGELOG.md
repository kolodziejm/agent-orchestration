# Changelog

All notable changes to the orchestration policy are documented here.

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
