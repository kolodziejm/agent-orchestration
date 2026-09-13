import { createDelegationCeilingExtension } from "./delegation-ceiling-core.js";

export default function delegationCeilingPlanner(pi) {
  return createDelegationCeilingExtension(pi, {
    source: "agent-orchestration:planner",
    allowedAgents: ["explorer", "spec-writer"],
  });
}
