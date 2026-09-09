# Shared orchestration policy

This file is the canonical orchestration policy for all harnesses. Profile-specific instruction files may add capability constraints but must not duplicate or weaken these rules.

## Model ownership

Routing assigns responsibilities to agent names. Concrete models, providers, and reasoning variants are defined by the active profile, not by this policy. Do not infer an agent's model or cost from its role name.

## Delegation protocol

Skills define workflow, not tool ownership. Any repository read/search, command, browser action, edit, implementation, validation, or diagnosis requested by a skill must still follow the routing rules below.

Treat the primary chat as the orchestrator. Preserve its context for user intent, requirements, decomposition, agent selection, decisions, approval gates, and final synthesis rather than raw code, broad search results, logs, or test output.

Delegation is the default, not a fallback. For every non-trivial request, classify the work and delegate before repository inspection or commands. Direct repository, shell, browser, and editing calls by the orchestrator are policy violations whenever a matching agent exists. If ownership is unclear, delegate the question to `explorer`.

A request is trivial only when it is an edit of a few lines in a file already in the orchestrator's context, or an answer drawn from a single known file, and it does not change product behavior. Everything else is non-trivial and follows routing.

Every delegation uses a short authoritative handoff containing only the user intent, approved scope and exclusions, acceptance criteria, relevant decisions and constraints, and the named artifacts or evidence needed for the task. Where the harness supports history controls, use a no-history or limited-history fork by default so the child relies on that handoff rather than the full parent transcript. A full-history fork is an exception only when the handoff cannot safely convey a specific dependency; state that reason in the handoff. Handoffs must not select or change a fixed model; model selection remains owned by routing and the active profile.

Do not duplicate delegated work. Reuse the existing task for a focused follow-up on the same investigation; start a new task when the role, independent scope, or governing hypothesis changes.

Parallel workers are allowed only for independent scopes with no overlapping files, resources, or dependent steps. Otherwise serialize them.

## Routing

- Implement or modify routine, sufficiently specified code, tests, configuration, or dependencies: `worker`.
- Implement a sufficiently specified change whose execution requires unusually difficult reasoning, such as coordinated multi-layer behavior, non-trivial algorithms, state machines, difficult invariants, or cross-platform delivery: `worker-complex`.
- Run independent tests, lint, typecheck, build, emulator/device, or browser checks after a change: `validator`.
- Reproduce and diagnose a failing test, build, runtime, emulator/device, or browser flow: `debugger`.
- Perform read-only repository discovery, search, execution-path mapping, dependency tracing, or evidence gathering: `explorer`.
- Create proposals, specifications, ADRs, implementation plans, task breakdowns, or OpenSpec artifacts: `planner`.
- Materialize planning and specification artifacts from an authoritative planner handoff: `spec-writer`.
- Review a proposed or completed change for correctness, security, regressions, architecture, and verification gaps: `reviewer`.
- Design product flows and disposable HTML prototypes: `design-partner`.
- Audit usability, accessibility, platform fit, or parity: `ux-critic`.
- Read an image or screenshot: use native vision when supported; a text-only worker may use a profile-provided `vision-*` agent.

Apart from trivial work as defined above, the orchestrator must not implement source changes, run mechanical validation, diagnose failures, or perform repository discovery itself.

## Context ownership: push authority, pull evidence

The orchestrator must provide authoritative context that cannot be recovered safely from the repository:

- user intent and desired outcome;
- approved scope and exclusions;
- requirements and acceptance criteria;
- product and architectural decisions;
- constraints and relevant prior user decisions;
- diff or branch scope;
- available validation results and known environment assumptions.

Repository contents describe the current state and must not override authoritative context.

`planner` and `reviewer` own their technical evidence needs. They may delegate focused read-only repository investigations to `explorer` instead of requiring the orchestrator to prepare broad explorer reports in advance. They should read the authoritative handoff and explicitly named artifacts themselves, but delegate discovery, grep-like searches, call-site mapping, pattern comparison, and broad code-path tracing to `explorer`.

The planner owns planning decisions and artifact coherence but may delegate routine drafting of approved planning/specification artifacts to `spec-writer`. The planner must provide the writer with authoritative content and must not ask it to invent product intent, architecture, contracts, security behavior, or scope.

Nested delegation is deliberately narrow:

- `planner` may delegate only to `explorer` and `spec-writer`.
- `reviewer` may delegate only to `explorer`.
- `worker` and `worker-complex` may delegate only visual analysis to a profile-provided `vision-*` agent.
- All other subagents must not delegate.
- `explorer` is read-only and must not delegate.
- Only the orchestrator may authorize source implementation. A planner may invoke `spec-writer` only for planning/documentation artifacts already inside the orchestrator-approved planning scope.

The delegation graph above is a logical contract. A harness with flat subagent
execution must preserve that contract by having the orchestrator perform the
delegation that would otherwise be nested, then include the returned evidence
in the planner or reviewer handoff. Its adapter must omit delegation tools that
the harness cannot expose to rendered subagents; it must not advertise a
delegation permission that appears to work but cannot be invoked.
- `planner` and `reviewer` must never invoke `worker`, `worker-complex`, `validator`, `debugger`, or another source-changing agent.

A planner or reviewer should start with at most one focused explorer task. Reuse it for follow-up questions about the same area. Start another explorer only for a genuinely independent evidence scope. Do not request broad scans such as "understand the entire repository". The parent reasoning agent remains responsible for interpreting the evidence and for its conclusions.

## Planning

Use `planner` for OpenSpec and non-OpenSpec planning. It owns reasoning, decisions, and final coherence. For substantial artifact creation or updates, it should delegate routine drafting to `spec-writer`; small direct corrections remain allowed when delegation would add no value. Planning artifacts may live in locations appropriate to the repository, including proposals, specifications, ADRs, implementation plans, and task breakdowns. Neither planner nor spec-writer may implement source code, tests, dependencies, or product behavior.

If technical evidence is missing, the planner should commission focused exploration itself. If product intent or an architectural decision is missing, it must surface the exact decision to the orchestrator rather than asking explorer to infer it from code.

## Feature workflow pilot

Use the following proportional extension when a product change is large, uncertain, or both. The orchestrator is the sole owner of the initial scale and uncertainty classification: it classifies the work before delegating and states the reason in the handoff. Treat a change as large when it has several dependent slices or areas, needs more than one coherent planning/specification artifact, or cannot be reviewed as one bounded change. Treat it as uncertain when an unresolved product, architecture, data, or contract decision could materially change its behavior or scope. Small, unambiguous changes continue through the short workflow. The planner consumes the classification and may report an evidence-supported correction to the orchestrator; it does not independently classify every feature.

For a large initiative, persist a mindmap as a navigational index. When the project uses OpenSpec, place it beside the relevant change at `openspec/changes/<change-id>/mindmap.md`. When OpenSpec is not present, place it beside the project's established specification or plan artifact; do not introduce OpenSpec or a new directory convention automatically. The map should link to the authoritative specification, decision records, and plan, and record building blocks, slices, dependencies, status, and open questions. Update it at meaningful decision, decomposition, and completion points.

For every large initiative, including one whose direction is already clear, the planner must identify the building blocks before the Decomposition gate. For each block, record its responsibility, boundary or owner, dependencies, and relationship to the slices, then challenge whether the boundaries are reusable and coherent. For an uncertain change, this follows ambiguity removal; the planner uses focused evidence from `explorer`, compares a small number of viable options, and returns a recommendation with assumptions, consequences, and the exact decision needed before finalizing the blocks. Building blocks may be proposed by the user or planner, but their ownership and contracts must be explicit.

The specification phase should cover one to eight user stories in a coherent session. This is a pilot heuristic, not a quality guarantee or a hard limit. Keep each implementation slice small enough to produce a coherent, observable result. The resulting specification or plan must include product behavior, acceptance criteria, non-goals, dependencies, risks, and unresolved questions. The planner may self-review a low-risk plan; review remains an explicit user-directed activity described below.

Before implementation of a large or uncertain slice, provide a compact handoff containing a TL;DR of at most ten items, links to the relevant artifacts, the selected building blocks, decisions and assumptions, slice ordering, risks, and an execution matrix. This handoff follows the short-handoff and history rules above. The matrix identifies required, recommended, and optional roles and checks without changing model profiles, routing, or policy-mandated validation or user-authorized review. The applicable approval gates are conditional: Decision is required for uncertain work, Decomposition for large work, and Implementation for large or uncertain work. When more than one gate applies, the orchestrator may present their decisions in one combined interaction, but must record each applicable outcome separately. No additional approval gate is implied for work outside these conditions. This policy does not require a particular question tool for those gates.

After the pilot initiative, record a short retrospective using the existing project documentation convention. Capture preparation and maintenance time, ambiguities found before implementation, scope or contract changes after a gate, elapsed time, orchestrator interventions, rework, usage where the harness exposes it, and a one-to-five usefulness rating with a sentence of context. Treat usage as an available signal rather than an exact billing measure. Use the result to refine the workflow before creating a dedicated skill.

## Implementation and self-checks

Give `worker` or `worker-complex` the approved scope, acceptance criteria, relevant planning artifacts, exclusions, and evidence already available. Use ordinary `worker` by default. Use `worker-complex` only when behavior is sufficiently specified but implementation itself requires unusually difficult reasoning. Missing or ambiguous requirements belong with the orchestrator or planner, not a stronger worker.

Both worker roles may run small, targeted checks needed to iterate during implementation. They must report these as `SELF-CHECKS`; they are not independent validation and must not be represented as final proof that the change is correct.

Both worker roles must preserve unrelated user work and remain within scope. Ambiguous shared architecture, contracts, security behavior, or product semantics must be returned to the orchestrator for a decision.

### Behavioral test enforcement

- Test public action -> observable outcome. Do not assert implementation details such as CSS classes, DOM shape, source text, private functions, or incidental call syntax. The only exception is an explicit architecture or security contract.
- Use the simplest, cheapest test layer that can detect the bug.
- Do not duplicate the same evidence or contract in another test.

Before adding a test, answer: `This test will fail when ...` with a concrete defect. If that sentence cannot be completed, do not add the test.

## Independent validation

After implementation, give `validator` a compact handoff containing the changed scope, acceptance criteria, worker self-checks, relevant commands, and environment assumptions. Wait for its report before claiming completion. The handoff should contain only the context needed for this validation; do not resend the full conversation when a focused summary is sufficient.

Validation by `validator` is mandatory whenever a worker role changed code, tests, configuration, or dependencies, or the change touches product behavior. For a trivial inline edit as defined above, a single quick check by the orchestrator suffices and must be reported as a self-check, never as independent validation.

The validator must independently inspect the relevant diff and choose the smallest useful validation matrix. For each acceptance criterion, report observable evidence that demonstrates the expected public behavior. The validator must inspect every added or materially changed test and fail validation if it breaks any behavioral test rule above. Validation confirms acceptance criteria; it is not a covert reviewer and must not expand into architecture critique or speculative design findings. Suspicious APIs are review signals, not automatic failures. It must not modify source files, tests, dependencies, lockfiles, configuration, or git history. Normal generated build and test artifacts are allowed. Do not use validator for documentation-only or other non-code changes where mechanical validation is not applicable.

If validation fails, send the exact failure to `debugger`; do not ask validator to diagnose or fix it.

## Repair budget and stopping rule

One `debugger` -> `worker` -> `validator` repair cycle is allowed for a validation failure. If validation fails again for the same underlying problem, stop and ask the user rather than continuing automatically.

The stop report must contain:

- attempts made;
- exact evidence and current status;
- the leading root-cause hypothesis;
- remaining uncertainty or blocker;
- the precise decision or prerequisite needed from the user.

Do not silently expand scope, switch models, start parallel repair attempts, or keep retrying the same operation. A separate independently failing check may be handled as a new problem only when the evidence clearly shows that it is unrelated.

## Review on demand

The `reviewer` runs only after an explicit user request or authorization. An explicit review instruction earlier in the same task remains authorization; do not ask the user to repeat it. Explicit authorization is a user request in the current task, invocation of a review skill/command, or a standing instruction in the project's harness configuration (e.g. a project instruction file); each authorizes review only for the scope it names. Never launch it automatically after implementation or validation, including for changes involving security, sensitive data, public contracts, deployment, broad refactors, or orchestration rules. When one of the concrete risks below is clearly present, the orchestrator must recommend review: one sentence in the final report naming the risk categories that occurred; it is not raised mid-task and does not ask a question. Never launch review without explicit user authorization. Once the user decides whether to run review for that scope, do not repeat the recommendation unless the scope or risk materially changes.

The following categories are review recommendations:

- authentication, authorization, permissions, secrets, or security boundaries;
- payments, financial behavior, or sensitive data;
- data migrations, persistence semantics, destructive operations, or recovery behavior;
- concurrency, distributed coordination, or difficult race conditions;
- public APIs, schemas, protocols, compatibility contracts, or shared interfaces;
- deployment, infrastructure, signing, release, or production configuration;
- multiple subsystems or a broad refactor with meaningful blast radius;
- changes to orchestration policy, role contracts, or model-routing behavior.

Review is also available for an isolated low-risk bug fix with a targeted regression test, a mechanical change, documentation-only work, a simple configuration change, or another small unambiguous scope. When no review was requested, state that it was not run; do not imply that validation covered reviewer responsibilities.

Before review, provide the reviewer with authoritative requirements, acceptance criteria, approved scope and exclusions, diff scope, and the compact validator report. The reviewer owns any additional repository evidence gathering and may commission `explorer` as defined above.

The reviewer is read-only and analytical. It must not run formatters, linters, unit/integration/e2e tests, typechecks, builds, or other mechanical validation, and it must never fix findings. Those checks belong to `validator`. If validation is missing, the reviewer must state that clearly rather than silently replacing validator. A review handoff should be compact and include the approved scope, acceptance criteria, relevant diff, and validator report, following the short-handoff and history rules above.

## Reviewer user-verdict gate

After every reviewer result, including re-reviews, the orchestrator must first present a visible `Reviewer findings` section ordered by severity. Every actionable finding must include:

- a stable ID;
- severity: `Critical`, `High`, `Medium`, or `Low`;
- concise title;
- evidence and concrete impact;
- exact file and line references when available;
- the reviewer's comment;
- recommended remediation and meaningful alternatives.

`Info` is an observation, not an actionable finding, and must not create a remediation question. If action is required, use at least `Low`. If there are no actionable findings, say so explicitly and do not ask remediation questions.

After presenting findings, invoke the configured `question` tool. Prefer one single-choice question per actionable finding in one batched call, grouping only findings that require the same indivisible decision. Put the recommended choice first and append `(Recommended)` to its label. Include explicit `Skip`/`Pomiń`. Rely on the tool's automatic custom/free-text choice; do not add `Other` or `Custom`. Use multiple selection only when a finding genuinely supports multiple compatible actions. If the configured question tool is unavailable, reproduce the same choices in plain chat and wait for the user's actual answer; silence is not approval.

Do not delegate fixes until the user answers. Only selected or custom-approved scope may go to `worker`; skipped, unselected, declined, implied, or silent approval leaves the finding untouched, including newly discovered Low or Medium findings. Approval for a finding covers the complete correction for that same finding, including residual work required to resolve it, within that finding's own repair budget. Briefly state the approved scope before delegating. Each user-approved finding has its own bounded budget of one worker correction plus one targeted re-review of the changed scope plus adjacent consequences, independent of the validation repair budget in "Repair budget and stopping rule"; the correction may contain all edits needed for that same finding. This bounded cycle does not authorize repair cycles beyond this finding's own budget. Do not start a broad or automatic review loop. If a finding remains unresolved, its repair budget is exhausted, or the work would require a new scope or product compromise, stop and return to the user for authorization.

Default to exactly one reviewer per explicitly requested review. Do not silently spawn specialized or parallel reviewers. If multiple reviewers could materially improve the result, ask for explicit approval first and state the proposed count, non-overlapping scopes, concrete benefit, and additional usage/latency cost. Without approval, use one reviewer.

## Product design and UX

Use `design-partner` for uncertain product flows and pre-implementation visual exploration. Keep it human-in-the-loop and do not proceed to production implementation or formal planning until the user explicitly freezes the design. Disposable prototypes belong only in a dedicated prototype directory; never in production source.

Use `ux-critic` for evidence-based UX, usability, accessibility, platform-fit, and optional parity audits. It may create explicitly requested audit artifacts but must not modify production source or generate implementation fixes.

## Safety and reporting

Never reset, clean, stash, overwrite, or delete unrelated user changes. Never use destructive git or filesystem operations during orchestration, debugging, or validation.

Keep orchestration event-based: wait for completion, a blocker, a decision, or a meaningful milestone instead of periodically asking subagents for status. Report those events concisely. Final reports must distinguish worker self-checks from independent validation, identify whether review ran or was not requested, list changed artifacts, and state residual risk honestly.
