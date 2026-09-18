# Feature Workflow Pilot

## Feature workflow pilot

Use the following proportional extension when a product change is large, uncertain, or both. The orchestrator is the sole owner of the initial scale and uncertainty classification: it classifies the work before delegating and states the reason in the handoff. Treat a change as large when it has several dependent slices or areas, needs more than one coherent planning/specification artifact, or cannot be reviewed as one bounded change. Treat it as uncertain when an unresolved product, architecture, data, or contract decision could materially change its behavior or scope. Small, unambiguous changes continue through the short workflow. The planner consumes the classification and may report an evidence-supported correction to the orchestrator; it does not independently classify every feature.

### Explicit delivery slices and ordered review units

For each implementation slice, the plan must define one bounded PR or fallback review unit and use one coherent concern per PR (and per fallback review unit). When suitable hosting/remote support and harness capability/authorization exist, the PR is the default delivery unit; otherwise the plan names an equivalently reviewable local branch, commit, or patch. The workflow does not assume a hosting provider or authorize automatic branch, commit, push, merge, or PR creation, and no report may imply that a remote action occurred when it did not.

Use the canonical accounting contract before implementation and at completion:

- treat `<=400` human-authored maintained changed lines and `<=12` human-authored maintained changed files as a reviewability heuristic/target, not a mandate; do not split a coherent concern solely to hit a number;
- exclude generated artifacts and lockfiles from those thresholds, but count and report generated-artifact and lockfile lines/files separately;
- a proposed `401–800` human-authored changed-line or `13–24` human-authored changed-file slice needs a concrete rationale and explicit user approval before implementation or promotion, unless a user-approved named stack/ordered-unit plan pre-authorizes that named unit and records the rationale;
- `>800` human-authored changed lines or `>24` human-authored changed files is an absolute maximum violation and must be split, not approved wholesale;
- prefer fewer units when adjacent units repeatedly touch the same 2–3 files and are not independently understandable, mergeable, and reviewable; coherence and independent merge/review value outrank numeric optimization.

The plan records expected human-authored, generated-artifact, and lockfile accounting, the rationale and approval status for any above-target slice or its pre-authorization in a named stack/ordered-unit plan, affected areas, dependencies, and order. Workers stay inside the assigned slice and stop before an unapproved threshold breach or at the absolute ceiling. Independent implementation may be parallel only in isolated, non-overlapping branches or worktrees; PR or fallback promotion remains ordered, and parallel lanes must not bypass accounting or serial validation.

A named stack/ordered-unit plan may group these bounded units in an explicit order. Once the user approves that plan, the orchestrator executes its already bounded units without inserting routine approval waits between them while scope, acceptance criteria, risks, and accounting remain unchanged. After every PR or fallback review unit, the orchestrator automatically presents a bird's-eye checkpoint as a non-blocking progress report. The checkpoint includes purpose/concern, behavior before/after, key decisions and approvals, human-authored diff lines/files, separate generated-artifact and lockfile lines/files, affected areas/files, risks, validation evidence or `not run`/`BLOCKED` status, residual work, and the next proposed PR or fallback unit. A checkpoint does not authorize merge, promotion, or remediation; existing review, finding/remediation, and merge authorization gates remain in force. Ask again only for a material scope or acceptance change, a new risk or product decision, or a failed/BLOCKED validation that requires a decision. A detected or projected absolute-ceiling breach requires stopping and re-decomposing/splitting; it is not waivable and cannot be pre-authorized. Outside a named approved stack/ordered-unit plan, an earlier initiative or slice approval never implies approval for a different unit.

For a large initiative, persist a mindmap as a navigational index. When the project uses OpenSpec, place it beside the relevant change at `openspec/changes/<change-id>/mindmap.md`. When OpenSpec is not present, place it beside the project's established specification or plan artifact; do not introduce OpenSpec or a new directory convention automatically. The map should link to the authoritative specification, decision records, and plan, and record building blocks, slices, dependencies, status, and open questions. Update it at meaningful decision, decomposition, and completion points.

For every large initiative, including one whose direction is already clear, the planner must identify the building blocks before the Decomposition gate. For each block, record its responsibility, boundary or owner, dependencies, and relationship to the slices, then challenge whether the boundaries are reusable and coherent. For an uncertain change, this follows ambiguity removal; the planner uses focused evidence from `explorer`, compares a small number of viable options, and returns a recommendation with assumptions, consequences, and the exact decision needed before finalizing the blocks. Building blocks may be proposed by the user or planner, but their ownership and contracts must be explicit.

### Concrete Pi fanout example

After scope and decomposition are established, a Pi orchestrator can launch one fresh asynchronous subagent wave. The example deliberately uses stable keys, concise technical-English labels, and bounded non-overlapping scopes:

```js
subagent({
  async: true,
  context: "fresh",
  workflowScript: `
    const evidence = await runs.all([
      {
        key: "policy-lane",
        agent: "explorer",
        phase: "Policy evidence",
        label: "Inspect orchestration policy and role contracts",
        task: "Read only policy/orchestration.md, roles/planner.md, and roles/reviewer.md. Return concise evidence about the approved contracts.",
        output: false
      },
      {
        key: "adapter-lane",
        agent: "explorer",
        phase: "Harness generation evidence",
        label: "Inspect Pi generation and installation boundaries",
        task: "Read only harnesses/pi/generate.py and harnesses/pi/install.py. Return concise evidence about generation and lifecycle boundaries.",
        output: false
      },
      {
        key: "test-lane",
        agent: "explorer",
        phase: "Regression evidence",
        label: "Inspect focused tests and harness generation contracts",
        task: "Read only tests/test_pi_*.py and scripts/generate. Return concise evidence about regression and generation contracts.",
        output: false
      }
    ]);
    const writer = await runs.run("writer", {
      agent: "worker",
      phase: "Synthesis and implementation",
      label: "Write the approved change from bounded evidence",
      task: "Use these bounded evidence summaries to write or update the approved scope and tests: " + evidence.map((result) => result.output).join("; ") + ". Do not run tests, checks, lint, typecheck, or builds."
    });
    const validator = await runs.run("validator", {
      agent: "validator",
      phase: "Serial validation",
      label: "Validate the writer result",
      task: "Inspect the writer result and execute the requested validation commands serially: " + writer.output
    });
    return { evidence, writer, validator };
  `
});
```

The same three serialization exceptions apply immediately beside this example: serialize only for a genuine data dependency, indivisible shared state, or too-small scope, and record the applicable reason in the handoff. This is an illustrative handoff shape, not a parser, workflow engine, durable chain, or automatic review mechanism; review remains separately authorized.

The specification phase should cover one to eight user stories in a coherent session. This is a pilot heuristic, not a quality guarantee or a hard limit. Keep each implementation slice small enough to produce a coherent, observable result. The resulting specification or plan must include product behavior, acceptance criteria, non-goals, dependencies, risks, and unresolved questions. The planner may self-review a low-risk plan; review remains an explicit user-directed activity except for the narrow multi-artifact OpenSpec exception in the canonical policy.

Before implementation of a large or uncertain slice, provide a compact handoff containing a TL;DR of at most ten items, links to the relevant artifacts, the selected building blocks, decisions and assumptions, slice ordering, risks, and an execution matrix. This handoff follows the short-handoff and history rules above. The matrix identifies required, recommended, and optional roles and checks without changing model profiles, routing, or policy-mandated validation or user-authorized review, except where that canonical OpenSpec exception applies. The applicable approval gates are conditional: Decision is required for uncertain work, Decomposition for large work, and Implementation for large or uncertain work. When more than one gate applies, the orchestrator may present their decisions in one combined interaction, but must record each applicable outcome separately. No additional approval gate is implied for a condition that does not apply. This policy does not require a particular question tool for those gates.

Those conditional pilot gates authorize only the named original scope and acceptance criteria; they do not authorize future findings discovered by review, audit, exploration, or validation. Apply the canonical finding decision policy: only a deterministic, reproducible failure of an already-authorized in-scope acceptance criterion is an acceptance blocker eligible for automatic repair. Every other actionable finding requires its own individual Done / Skip / Snooze decision before a repair worker is launched. Present a clear, structured explanation of the concrete problem or failure mode and evidence; affected scope and impact, including user-visible behavior, systems/components/files/contracts, and practical consequence; and detailed viable solution options—not just labels—with implementation direction, scope/cost, trade-offs/risks, and a recommendation with rationale where appropriate. The individual question must be self-contained enough that the user does not need to infer context and must faithfully summarize that problem, affected scope/impact, and solution options/trade-offs. These are disposition decisions, not solution selection or ambiguous package authorization. A question tool may batch distinct questions up to its limit, but each finding remains a separate decision; record every outcome, and do not silently create deferred tickets or re-propose skipped findings without materially changed evidence. No separate pilot-specific gate or blanket authorization is added.

After the pilot initiative, record a short retrospective using the existing project documentation convention. Capture preparation and maintenance time, ambiguities found before implementation, scope or contract changes after a gate, elapsed time, orchestrator interventions, rework, usage where the harness exposes it, and a one-to-five usefulness rating with a sentence of context. Treat usage as an available signal rather than an exact billing measure. Use the result to refine the workflow before creating a dedicated skill.
