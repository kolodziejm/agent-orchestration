# Claude profile orchestration

- The primary agent is the orchestrator and follows the shared orchestration policy loaded before this file.
- All models in this profile are natively multimodal; use native vision for image and screenshot reading. Profile-provided `vision-*` delegation is unnecessary.
- Preserve the primary model's context for authority, decomposition, decisions, approval gates, and synthesis. Delegate mechanical repository evidence gathering to the agents defined by the shared policy.
