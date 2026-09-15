import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const PRIMARY_POLICY_START = "<!-- agent-orchestration:primary-policy:start -->";
export const PRIMARY_POLICY_END = "<!-- agent-orchestration:primary-policy:end -->";
export const MAX_POLICY_BYTES = 256 * 1024;
export const PRIMARY_POLICY_ERROR = "agent-orchestration: primary policy unavailable";

const POLICY_RELATIVE_PATH = join(
  "agent-orchestration",
  "_shared",
  "orchestration-core.md",
);
const UTF8_DECODER = new TextDecoder("utf-8", {
  fatal: true,
  ignoreBOM: true,
});

function isWithin(root, candidate) {
  const remainder = relative(root, candidate);
  return remainder === ""
    || (!remainder.startsWith(`..${sep}`) && remainder !== ".." && !isAbsolute(remainder));
}

function rejectSymlinkedPath(root, target) {
  const parts = relative(root, target).split(sep).filter(Boolean);
  let current = root;
  for (const part of parts) {
    current = join(current, part);
    const entry = lstatSync(current);
    if (entry.isSymbolicLink()) throw new Error("linked policy path");
  }
}

function profileRoot() {
  const configuredRoot = process.env.PI_CODING_AGENT_DIR;
  if (typeof configuredRoot !== "string" || !configuredRoot || !isAbsolute(configuredRoot)) {
    throw new Error("profile root unavailable");
  }

  const root = resolve(configuredRoot);
  const rootStat = lstatSync(root);
  if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) {
    throw new Error("profile root unavailable");
  }

  const realRoot = realpathSync(root);
  const installedRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
  if (realpathSync(installedRoot) !== realRoot) {
    throw new Error("extension is outside profile root");
  }
  return { root, realRoot };
}

function readInstalledPolicy() {
  const { root, realRoot } = profileRoot();
  const policyPath = resolve(root, POLICY_RELATIVE_PATH);
  if (!isWithin(root, policyPath)) throw new Error("policy path escaped profile root");

  rejectSymlinkedPath(root, policyPath);
  const policyRealPath = realpathSync(policyPath);
  if (!isWithin(realRoot, policyRealPath)) throw new Error("policy path escaped profile root");

  const noFollow = typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0;
  const descriptor = openSync(policyPath, constants.O_RDONLY | noFollow);
  try {
    const before = fstatSync(descriptor);
    if (!before.isFile() || before.size > MAX_POLICY_BYTES) {
      throw new Error("policy input is invalid");
    }
    const bytes = readFileSync(descriptor);
    const after = fstatSync(descriptor);
    if (!after.isFile() || after.size > MAX_POLICY_BYTES || bytes.length > MAX_POLICY_BYTES) {
      throw new Error("policy input is invalid");
    }

    let policy;
    try {
      policy = UTF8_DECODER.decode(bytes);
    } catch {
      throw new Error("policy input is invalid");
    }
    if (!policy.trim()) throw new Error("policy input is empty");
    return policy;
  } finally {
    closeSync(descriptor);
  }
}

function containsManagedPolicy(systemPrompt) {
  return systemPrompt.includes(PRIMARY_POLICY_START)
    || systemPrompt.includes(PRIMARY_POLICY_END);
}

function reportFailure(ctx) {
  try {
    if (typeof ctx?.ui?.notify === "function") {
      ctx.ui.notify(PRIMARY_POLICY_ERROR, "error");
      return;
    }
  } catch {
    // Fall through to the non-sensitive process diagnostic below.
  }
  try {
    console.error(PRIMARY_POLICY_ERROR);
  } catch {
    // Diagnostics must never affect prompt handling.
  }
}

function appendPolicy(systemPrompt, policy) {
  const wrapped = `${PRIMARY_POLICY_START}\n${policy}${policy.endsWith("\n") ? "" : "\n"}${PRIMARY_POLICY_END}`;
  return `${systemPrompt}\n\n${wrapped}`;
}

export default function primaryPolicy(pi) {
  let cached;

  pi.on("before_agent_start", (event, ctx) => {
    if (process.env.PI_SUBAGENT_CHILD === "1") return;
    if (!event || typeof event.systemPrompt !== "string") {
      reportFailure(ctx);
      return;
    }
    if (containsManagedPolicy(event.systemPrompt)) return;

    if (!cached) {
      try {
        cached = { policy: readInstalledPolicy() };
      } catch {
        cached = { error: true };
      }
    }
    if (cached.error) {
      reportFailure(ctx);
      return;
    }

    return { systemPrompt: appendPolicy(event.systemPrompt, cached.policy) };
  });
}
