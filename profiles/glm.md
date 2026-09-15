# GLM profile orchestration

- The primary agent is the orchestrator and follows the shared orchestration policy loaded before this file.
- GLM primary models are text-only in this setup. For image and screenshot work, the primary orchestrator delegates once to an existing image-capable role according to responsibility: `explorer` for visual repository evidence, `worker` or `worker-complex` for implementation, `validator` for deterministic visual/browser validation, `design-partner` for product-flow or prototype exploration, or `ux-critic` only for an explicitly authorized runtime UX audit.
- Preserve the primary model's context for authority, decomposition, decisions, approval gates, and synthesis. Delegate mechanical repository evidence gathering to the agents defined by the shared policy.
