import { createDelegationCeilingExtension } from "./delegation-ceiling-core.js";

export default function delegationCeilingReviewer(pi) {
  return createDelegationCeilingExtension(pi, {
    source: "agent-orchestration:reviewer",
    allowedAgents: ["explorer"],
  });
}
