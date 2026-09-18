# Claude profile orchestration

- The primary agent is the orchestrator and follows the shared orchestration policy loaded before this file.
- All models in this profile are natively multimodal; use native vision for image and screenshot reading.
- Preserve the primary model's context for authority, decomposition, decisions, approval gates, and synthesis.
- Claude Code uses a flat subagent topology. The orchestrator invokes `explorer` directly when planner or reviewer evidence is needed, then includes that evidence in the planner or reviewer handoff. The orchestrator performs the selected-worker handoff for any approved repository persistence.
- Generated role files do not expose nested `Agent(explorer)` tools. Planner and reviewer must use evidence supplied by the orchestrator and return any follow-up investigation request to it.
- Generated subagents start without parent history, which satisfies the policy's no-history default. `subagent_type: "fork"` (full-history) is allowed only as the documented exception, with the reason stated in the handoff.
- The `model` parameter of the `Agent` tool must never be passed; model and effort are baked into each role's frontmatter by the active profile.
- Built-in harness agents (e.g. `general-purpose`, `Explore`, `Plan`, `claude`) must not be used while a matching role exists; they are allowed only when no role covers the work, with the reason stated in the handoff.
