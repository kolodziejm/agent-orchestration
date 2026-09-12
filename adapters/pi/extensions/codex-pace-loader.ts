import codexPaceStatus from "./codex-pace-core.mjs";
import {
  adapterForProvider,
  resolveUsageAuth,
  queryProviderUsage,
} from "__PI_USAGE_ENTRYPOINT__";

export default function loadCodexPaceStatus(pi) {
  codexPaceStatus(pi, {
    usageApi: { adapterForProvider, resolveUsageAuth, queryProviderUsage },
  });
}
