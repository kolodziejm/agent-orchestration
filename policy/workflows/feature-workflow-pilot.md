# Feature Workflow Pilot

## Feature workflow pilot

Use the following proportional extension when a product change is large, uncertain, or both. The orchestrator is the sole owner of the initial scale and uncertainty classification: it classifies the work before delegating and states the reason in the handoff. Treat a change as large when it has several dependent slices or areas, needs more than one coherent planning/specification artifact, or cannot be reviewed as one bounded change. Treat it as uncertain when an unresolved product, architecture, data, or contract decision could materially change its behavior or scope. Small, unambiguous changes continue through the short workflow. The planner consumes the classification and may report an evidence-supported correction to the orchestrator; it does not independently classify every feature.

### Explicit delivery slices and ordered review units

For each implementation slice, the plan must define one bounded PR or fallback review unit with one coherent reviewer question and an observable outcome. When suitable hosting/remote support and harness capability/authorization exist, the PR is the default delivery unit; otherwise the plan names an equivalently reviewable local branch, commit, or patch. The workflow does not assume a hosting provider or authorize automatic branch, commit, push, merge, or PR creation, and no report may imply that a remote action occurred when it did not.

Use the canonical accounting contract before implementation and at completion:

- line and file counts are diagnostics, not approval gates or hard ceilings;
- count and report human-authored maintained changes, generated artifacts, and lockfiles separately, while treating every artifact the reviewer must inspect as cognitive review burden;
- split when a unit contains independently valuable behavior, answers more than one reviewer question, spans separable risk boundaries, or cannot be validated as one outcome;
- keep a unit together when splitting would create unused scaffolding, partial abstractions, duplicated setup, or dependent units repeatedly touching the same core files;
- prefer the smallest end-to-end slice that proves core behavior before generalized hardening.

The plan records expected human-authored, generated-artifact, and lockfile accounting, the cognitive-coherence rationale, observable outcome, affected areas, dependencies, and order. Workers stay inside the assigned reviewer question and stop before expanding into a second independent concern. Independent implementation may be parallel only in isolated, non-overlapping branches or worktrees when parallelism offers concrete leverage; PR or fallback promotion remains ordered, and parallel lanes must not bypass serial validation.

A named stack/ordered-unit plan may group these bounded units in an explicit order. Plan only the next one to three implementation units concretely. Later units remain a revisable roadmap and must be reshaped using evidence from completed working slices rather than pre-authorized as fixed implementation. Once the user approves the concrete units, the orchestrator executes them without inserting routine approval waits while scope, acceptance criteria, risks, and accounting remain unchanged. After every PR or fallback review unit, the orchestrator automatically presents a bird's-eye checkpoint as a non-blocking progress report. The checkpoint includes purpose/reviewer question, behavior before/after, key decisions, human-authored diff lines/files, separate generated-artifact and lockfile lines/files, affected areas/files, risks, self-check and independent validation evidence or `not run`/`BLOCKED` status, residual work, and the next proposed PR or fallback unit. A checkpoint does not authorize merge, promotion, or remediation; existing review, finding/remediation, and merge authorization gates remain in force. Ask again only for a material scope or acceptance change, a new risk or product decision, a decomposition change, or a failed/BLOCKED validation that requires a decision. Outside a named approved stack/ordered-unit plan, an earlier initiative or slice approval never implies approval for a different unit.

For a large initiative, keep one authoritative planning artifact by default using the repository's existing issue, OpenSpec change, ADR, or plan convention. Mindmaps, execution matrices, HTML reports, evidence ledgers, and retrospectives are optional and require a distinct approved consumer or an explicit user request. Do not introduce OpenSpec, a new directory convention, or parallel representations merely because the initiative is large.

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
      task: "Use these bounded evidence summaries to implement the smallest approved end-to-end slice: " + evidence.map((result) => result.output).join("; ") + ". Run only focused development checks as SELF-CHECKS and report them for independent validation."
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

The specification phase should cover a coherent set of product behavior without a numeric story target. Keep each implementation slice focused on a coherent, observable result. The resulting specification or plan must include only the product behavior, acceptance criteria, non-goals, dependencies, material risks, and unresolved questions needed for the next concrete units. The planner may self-review a low-risk plan; semantic review remains explicitly user-directed, including for OpenSpec.

Before implementation of a large or uncertain slice, provide a compact handoff containing a short TL;DR, links to the authoritative artifact, decisions and assumptions, the next concrete units, material risks, and only the roles/checks needed to execute them. This handoff follows the short-handoff and history rules above. The applicable approval gates are conditional: Decision is required for uncertain work, Decomposition for large work, and Implementation for large or uncertain work. When more than one gate applies, the orchestrator may present their decisions in one combined interaction, but must record each applicable outcome separately. No execution matrix, additional artifact, or approval gate is implied unless it changes a real decision. This policy does not require a particular question tool for those gates.

Those conditional pilot gates authorize only the named original scope and acceptance criteria; they do not authorize future findings discovered by review, audit, exploration, or validation. Apply the canonical finding decision policy: only a deterministic, reproducible failure of an already-authorized in-scope acceptance criterion is an acceptance blocker eligible for automatic repair. Every other actionable finding requires its own individual Done / Skip / Snooze decision before a repair worker is launched. Present a clear, structured explanation of the concrete problem or failure mode and evidence; affected scope and impact, including user-visible behavior, systems/components/files/contracts, and practical consequence; and detailed viable solution options—not just labels—with implementation direction, scope/cost, trade-offs/risks, and a recommendation with rationale where appropriate. The individual question must be self-contained enough that the user does not need to infer context and must faithfully summarize that problem, affected scope/impact, and solution options/trade-offs. These are disposition decisions, not solution selection or ambiguous package authorization. A question tool may batch distinct questions up to its limit, but each finding remains a separate decision; record every outcome, and do not silently create deferred tickets or re-propose skipped findings without materially changed evidence. No separate pilot-specific gate or blanket authorization is added.

After the pilot initiative, record a retrospective only when the user requests one or when it will inform an explicit workflow decision. Keep it short and use existing project documentation rather than creating a new report format.
