import { spawn } from "node:child_process";
import { lstatSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { StringEnum, Type } from "@earendil-works/pi-ai";

/**
 * This extension is intentionally the only place in the repository that uses
 * child_process.spawn. It is a Git-specific, fixed-argv reader rather than a
 * general command runner. The host's pi.exec buffers output before resolving,
 * so it cannot provide the aggregate transient cap required here.
 */
export const GIT_EXECUTABLE = "git";
export const MAX_OUTPUT_BYTES = 64 * 1024;
export const MAX_OUTPUT_LINES = 2_000;
export const EXECUTION_TIMEOUT_MS = 10_000;
export const KILL_FALLBACK_MS = 250;
export const MAX_PATHS = 32;
export const MAX_PATH_LENGTH = 512;
export const MAX_REF_LENGTH = 128;

const MAX_RESULT_METADATA_BYTES = 48 * 1024;
const CONTROL_CHARACTER_PATTERN = /[\p{Cc}]/u;
const GLOB_CHARACTER_PATTERN = /[?*\[]/;
const OID_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const DRIVE_OR_UNC_PATTERN = /^(?:[A-Za-z]:|\\\\|\/\/)/;
const REF_CHARACTER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/@+\-]*$/;
const STATUS_ACTION = "status";
const DIFF_ACTION = "diff";
const TARGETS = ["worktree", "staged", "range"];
const VIEWS = ["patch", "stat", "name-status"];

/**
 * These arguments are prepended to every Git invocation. Keep this list
 * immutable and do not derive any entry from tool input.
 */
export const FIXED_GIT_ARGS = Object.freeze([
  "--no-pager",
  "--no-replace-objects",
  "--no-optional-locks",
  "--literal-pathspecs",
  "-c",
  "core.hooksPath=/dev/null",
  "-c",
  "core.fsmonitor=false",
  "-c",
  "core.pager=cat",
  "-c",
  "pager.status=false",
  "-c",
  "pager.diff=false",
  "-c",
  "diff.external=",
  "-c",
  "diff.trustExitCode=false",
  "-c",
  "protocol.allow=never",
  "-c",
  "submodule.recurse=false",
]);

/**
 * Git receives no ambient process environment. The paths listed here are
 * system locations used by supported macOS/Linux installations only; an
 * operator-controlled PATH is deliberately never accepted.
 */
export const FIXED_GIT_ENV = Object.freeze({
  PATH: "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:/opt/local/bin",
  HOME: "/nonexistent",
  XDG_CONFIG_HOME: "/nonexistent",
  LC_ALL: "C",
  LANG: "C",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_TERMINAL_PROMPT: "0",
  GIT_OPTIONAL_LOCKS: "0",
  GIT_PAGER: "cat",
  PAGER: "cat",
  GIT_EXTERNAL_DIFF: "",
  GIT_NO_LAZY_FETCH: "1",
});

export const GitReadParameters = Type.Object(
  {
    action: StringEnum([STATUS_ACTION, DIFF_ACTION], {
      description: "Read bounded Git status or diff evidence",
    }),
    target: Type.Optional(
      StringEnum(TARGETS, {
        description: "Diff target: worktree, staged, or independently resolved range",
      }),
    ),
    view: Type.Optional(
      StringEnum(VIEWS, {
        description: "Diff presentation: patch, stat, or name-status",
      }),
    ),
    base: Type.Optional(
      Type.String({
        minLength: 1,
        maxLength: MAX_REF_LENGTH,
        description: "Conservative range base ref; resolved before diff",
      }),
    ),
    head: Type.Optional(
      Type.String({
        minLength: 1,
        maxLength: MAX_REF_LENGTH,
        description: "Conservative range head ref; resolved before diff",
      }),
    ),
    paths: Type.Optional(
      Type.Array(
        Type.String({
          minLength: 1,
          maxLength: MAX_PATH_LENGTH,
          description: "Repository-relative literal path",
        }),
        {
          maxItems: MAX_PATHS,
          uniqueItems: true,
          description: "At most 32 unique repository-relative paths",
        },
      ),
    ),
  },
  { additionalProperties: false },
);

class GitReadFailure extends Error {
  constructor(code, message) {
    super(message);
    this.name = "GitReadFailure";
    this.code = code;
  }
}

function failure(code, message) {
  return new GitReadFailure(code, message);
}

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function invalidInput() {
  return failure("invalid-input", "git_read input is invalid");
}

/** Normalize Pi's documented one-character @ path marker, then validate. */
export function normalizeRepoPath(value) {
  if (typeof value !== "string" || value.length < 1 || value.length > MAX_PATH_LENGTH) {
    throw invalidInput();
  }
  const normalized = value.startsWith("@") ? value.slice(1) : value;
  if (
    !normalized
    || normalized.includes("\\")
    || normalized.includes("\0")
    || CONTROL_CHARACTER_PATTERN.test(normalized)
    || DRIVE_OR_UNC_PATTERN.test(normalized)
    || isAbsolute(normalized)
    || normalized.startsWith(":")
  ) {
    throw invalidInput();
  }
  const components = normalized.split("/");
  if (components.some((component) => !component || component === "." || component === "..")) {
    throw invalidInput();
  }
  // A colon anywhere is rejected instead of allowing pathspec magic or an
  // ambiguous drive-like token to reach Git.
  if (normalized.includes(":")) throw invalidInput();
  if (normalized.length > MAX_PATH_LENGTH) throw invalidInput();
  return normalized;
}

/** Validate a conservative branch, tag, or full object-id token. */
export function validateRef(value) {
  if (typeof value !== "string" || value.length < 1 || value.length > MAX_REF_LENGTH) {
    throw invalidInput();
  }
  if (
    value.startsWith("-")
    || /\s/.test(value)
    || CONTROL_CHARACTER_PATTERN.test(value)
    || value.includes("\\")
    || value.includes("..")
    || value.includes("@{")
    || value.includes("~")
    || value.includes("^")
    || value.includes(":")
    || GLOB_CHARACTER_PATTERN.test(value)
    || !REF_CHARACTER_PATTERN.test(value)
    || value.endsWith(".")
  ) {
    throw invalidInput();
  }
  const components = value.split("/");
  if (
    components.some(
      (component) => !component || component === "." || component === ".." || component.endsWith(".lock"),
    )
    || value === "@"
  ) {
    throw invalidInput();
  }
  return value;
}

function normalizePaths(paths) {
  if (paths === undefined) return [];
  if (!Array.isArray(paths) || paths.length > MAX_PATHS) throw invalidInput();
  const normalized = paths.map(normalizeRepoPath);
  if (new Set(normalized).size !== normalized.length) throw invalidInput();
  return normalized;
}

function validateStringField(value, maxLength) {
  return typeof value === "string" && value.length >= 1 && value.length <= maxLength;
}

/** Fail closed for conditional combinations the flat provider schema cannot express. */
export function normalizeRequest(params) {
  if (!isObject(params)) throw invalidInput();
  const allowed = new Set(["action", "target", "view", "base", "head", "paths"]);
  if (Object.keys(params).some((key) => !allowed.has(key))) throw invalidInput();
  if (params.action !== STATUS_ACTION && params.action !== DIFF_ACTION) throw invalidInput();
  const paths = normalizePaths(params.paths);

  if (params.action === STATUS_ACTION) {
    if (hasOwn(params, "target") || hasOwn(params, "view") || hasOwn(params, "base") || hasOwn(params, "head")) {
      throw invalidInput();
    }
    return { action: STATUS_ACTION, paths };
  }

  if (!TARGETS.includes(params.target) || !VIEWS.includes(params.view)) throw invalidInput();
  if (params.target === "range") {
    if (!validateStringField(params.base, MAX_REF_LENGTH) || !validateStringField(params.head, MAX_REF_LENGTH)) {
      throw invalidInput();
    }
    return {
      action: DIFF_ACTION,
      target: params.target,
      view: params.view,
      base: validateRef(params.base),
      head: validateRef(params.head),
      paths,
    };
  }
  if (hasOwn(params, "base") || hasOwn(params, "head")) throw invalidInput();
  return { action: DIFF_ACTION, target: params.target, view: params.view, paths };
}

/** Paths follow `--` and the fixed `--literal-pathspecs` mode, so they must stay literal. */
function pathspecs(paths) {
  return [...paths];
}

function assertPathsWithinRoot(paths, root) {
  for (const path of paths) {
    const candidate = resolve(root, path);
    if (!isWithin(root, candidate)) throw failure("invalid-input", "Git path is outside the worktree");
  }
}

const COMMON_DIFF_ARGS = Object.freeze([
  "diff",
  "--no-ext-diff",
  "--no-textconv",
  "--no-renames",
  "--ignore-submodules=all",
  "--no-color",
]);

/** Build only fixed-subcommand argv from already validated internal values. */
export function buildGitArgv(request, resolvedOids = {}) {
  const suffix = ["--", ...pathspecs(request.paths)];
  if (request.action === STATUS_ACTION) {
    return [
      ...FIXED_GIT_ARGS,
      "status",
      "--porcelain=v1",
      "-z",
      "--untracked-files=all",
      "--no-renames",
      "--ignore-submodules=all",
      ...suffix,
    ];
  }

  const viewArgs = request.view === "patch"
    ? ["--patch", "--unified=3"]
    : request.view === "stat"
      ? ["--stat"]
      : ["--name-status", "-z"];
  let targetArgs;
  if (request.target === "worktree") {
    targetArgs = [];
  } else if (request.target === "staged") {
    if (!OID_PATTERN.test(resolvedOids.head || "")) throw failure("internal", "staged diff commit is unavailable");
    targetArgs = ["--cached", resolvedOids.head];
  } else {
    if (!OID_PATTERN.test(resolvedOids.base || "") || !OID_PATTERN.test(resolvedOids.head || "")) {
      throw failure("internal", "range diff commits are unavailable");
    }
    targetArgs = [resolvedOids.base, resolvedOids.head];
  }
  return [...FIXED_GIT_ARGS, ...COMMON_DIFF_ARGS, ...viewArgs, ...targetArgs, ...suffix];
}

function isWithin(root, candidate) {
  const child = relative(root, candidate);
  return child === "" || (!child.startsWith(`..${sep}`) && child !== ".." && !isAbsolute(child));
}

function canonicalDirectory(pathValue) {
  if (
    typeof pathValue !== "string"
    || !pathValue
    || CONTROL_CHARACTER_PATTERN.test(pathValue)
  ) throw failure("invalid-cwd", "Git worktree is unavailable");
  let candidate;
  try {
    candidate = realpathSync(resolve(pathValue));
    if (!statSync(candidate).isDirectory()) throw new Error("not a directory");
  } catch {
    throw failure("invalid-cwd", "Git worktree is unavailable");
  }
  return candidate;
}

/**
 * Find the repository boundary without trusting Git configuration. A regular
 * repository has a `.git` directory; a linked worktree has a regular `.git`
 * file. Symlinked markers are rejected because their containing directory
 * would not be an independently trusted boundary.
 */
function trustedWorktreeRoot(cwd) {
  let candidate = cwd;
  while (true) {
    const marker = resolve(candidate, ".git");
    try {
      const markerStat = lstatSync(marker);
      if (markerStat.isSymbolicLink()) {
        throw failure("invalid-cwd", "Git worktree marker is unavailable");
      }
      if (!markerStat.isDirectory() && !markerStat.isFile()) {
        throw failure("invalid-cwd", "Git worktree marker is unavailable");
      }
      return candidate;
    } catch (error) {
      if (error instanceof GitReadFailure) throw error;
      if (error?.code !== "ENOENT") {
        throw failure("invalid-cwd", "Git worktree marker is unavailable");
      }
    }
    const parent = dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  throw failure("not-worktree", "Current directory is not a Git worktree");
}

function oneLine(buffer) {
  const value = buffer.toString("utf8");
  if (value.includes("\0")) throw failure("malformed-output", "Git returned malformed output");
  const lines = value.split("\n");
  if (lines.length > 2 || (lines.length === 2 && lines[1] !== "")) {
    throw failure("malformed-output", "Git returned malformed output");
  }
  return lines[0].replace(/\r$/, "");
}

function objectIdFrom(buffer) {
  const value = oneLine(buffer).trim();
  if (!OID_PATTERN.test(value)) throw failure("malformed-output", "Git returned an invalid object id");
  return value;
}

function boundedChunk(value) {
  if (Buffer.isBuffer(value)) return { buffer: value, complete: true };
  if (typeof value === "string") {
    const maximumCharacters = MAX_OUTPUT_BYTES + 1;
    const candidate = value.length > maximumCharacters ? value.slice(0, maximumCharacters) : value;
    const buffer = Buffer.from(candidate, "utf8");
    return { buffer, complete: value.length <= maximumCharacters && Buffer.byteLength(value, "utf8") <= MAX_OUTPUT_BYTES };
  }
  if (ArrayBuffer.isView(value)) {
    const view = new Uint8Array(value.buffer, value.byteOffset, Math.min(value.byteLength, MAX_OUTPUT_BYTES + 1));
    return { buffer: Buffer.from(view), complete: value.byteLength <= MAX_OUTPUT_BYTES };
  }
  return { buffer: Buffer.from(String(value).slice(0, MAX_OUTPUT_BYTES + 1), "utf8"), complete: false };
}

class AggregateOutputBudget {
  constructor() {
    this.bytes = 0;
    this.lines = 0;
    this.overflow = false;
  }

  accept(value) {
    if (this.overflow) return { chunk: Buffer.alloc(0), overflow: true };
    const { buffer, complete } = boundedChunk(value);
    const remainingBytes = MAX_OUTPUT_BYTES - this.bytes;
    let keepLength = Math.min(buffer.length, Math.max(0, remainingBytes));
    let localLines = 0;
    let lineOverflow = false;
    for (let index = 0; index < keepLength; index += 1) {
      if (buffer[index] !== 0x0a) continue;
      if (this.lines + localLines >= MAX_OUTPUT_LINES) {
        keepLength = index;
        lineOverflow = true;
        break;
      }
      localLines += 1;
    }
    const byteOverflow = !complete || buffer.length > keepLength;
    const kept = buffer.subarray(0, keepLength);
    this.bytes += kept.length;
    this.lines += localLines;
    if (byteOverflow || lineOverflow) this.overflow = true;
    return { chunk: kept, overflow: this.overflow };
  }
}

function concatChunks(chunks) {
  if (!chunks.length) return Buffer.alloc(0);
  return Buffer.concat(chunks);
}

function runBoundedGit(args, cwd, execution, signal) {
  if (execution.deadlineAt <= Date.now()) return Promise.reject(failure("timeout", "Git read timed out"));
  if (signal?.aborted) return Promise.reject(failure("cancelled", "Git read was cancelled"));

  return new Promise((resolvePromise, rejectPromise) => {
    let child;
    let settled = false;
    let terminationReason;
    let deadlineTimer;
    let killTimer;
    const stdoutChunks = [];
    const stderrChunks = [];

    const cleanup = () => {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      if (killTimer) clearTimeout(killTimer);
      signal?.removeEventListener?.("abort", onAbort);
      child?.stdout?.removeListener?.("data", onStdout);
      child?.stderr?.removeListener?.("data", onStderr);
      child?.removeListener?.("error", onError);
      child?.removeListener?.("close", onClose);
    };

    const finishFailure = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      rejectPromise(error);
    };

    const finishSuccess = (value) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolvePromise(value);
    };

    const terminate = (reason) => {
      if (settled || terminationReason) return;
      terminationReason = reason;
      try {
        child?.kill?.("SIGTERM");
      } catch {
        // The close/error event still determines the bounded failure result.
      }
      killTimer = setTimeout(() => {
        if (settled) return;
        try {
          child?.kill?.("SIGKILL");
        } catch {
          // A failed fallback kill must not expose process details.
        }
        finishFailure(failure(terminationReason, terminationReason === "output-limit"
          ? "Git output limit exceeded"
          : terminationReason === "cancelled"
            ? "Git read was cancelled"
            : "Git read timed out"));
      }, KILL_FALLBACK_MS);
    };

    const onAbort = () => terminate("cancelled");
    const onStdout = (chunk) => {
      const accepted = execution.budget.accept(chunk);
      if (accepted.chunk.length) stdoutChunks.push(accepted.chunk);
      if (accepted.overflow) terminate("output-limit");
    };
    const onStderr = (chunk) => {
      const accepted = execution.budget.accept(chunk);
      if (accepted.chunk.length) stderrChunks.push(accepted.chunk);
      if (accepted.overflow) terminate("output-limit");
    };
    const onError = () => {
      // A failed termination can emit `error`; preserve the original bounded
      // reason so the SIGKILL fallback remains responsible for settlement.
      if (terminationReason) return;
      finishFailure(failure("spawn-failed", "Git could not be started"));
    };
    const onClose = (exitCode, signalName) => {
      if (settled) return;
      if (terminationReason) {
        finishFailure(failure(
          terminationReason,
          terminationReason === "output-limit"
            ? "Git output limit exceeded"
            : terminationReason === "cancelled"
              ? "Git read was cancelled"
              : "Git read timed out",
        ));
        return;
      }
      finishSuccess({
        stdout: concatChunks(stdoutChunks),
        stderr: concatChunks(stderrChunks),
        exitCode,
        signal: signalName,
      });
    };

    const remaining = Math.max(1, execution.deadlineAt - Date.now());
    try {
      child = spawn(GIT_EXECUTABLE, args, {
        cwd,
        env: FIXED_GIT_ENV,
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch {
      finishFailure(failure("spawn-failed", "Git could not be started"));
      return;
    }

    child.stdout?.on("data", onStdout);
    child.stderr?.on("data", onStderr);
    child.once("error", onError);
    child.once("close", onClose);
    deadlineTimer = setTimeout(() => terminate("timeout"), remaining);
    if (signal) {
      signal.addEventListener("abort", onAbort, { once: true });
      if (signal.aborted) onAbort();
    }
  });
}

async function resolveWorktree(cwd, execution, signal) {
  const requestedCwd = canonicalDirectory(cwd);
  const trustedRoot = trustedWorktreeRoot(requestedCwd);
  const probe = await runBoundedGit(
    [...FIXED_GIT_ARGS, "rev-parse", "--is-inside-work-tree"],
    requestedCwd,
    execution,
    signal,
  );
  if (probe.exitCode !== 0) throw failure("not-worktree", "Current directory is not a Git worktree");
  if (oneLine(probe.stdout).trim() !== "true") throw failure("not-worktree", "Current directory is not a Git worktree");
  const rootProbe = await runBoundedGit(
    [...FIXED_GIT_ARGS, "rev-parse", "--show-toplevel"],
    requestedCwd,
    execution,
    signal,
  );
  if (rootProbe.exitCode !== 0) throw failure("not-worktree", "Current directory is not a Git worktree");
  const rootValue = oneLine(rootProbe.stdout);
  if (!rootValue || !isAbsolute(rootValue)) throw failure("malformed-output", "Git returned malformed output");
  const root = canonicalDirectory(rootValue);
  if (root !== trustedRoot) {
    throw failure("outside-worktree", "Git worktree root exceeds the trusted repository boundary");
  }
  if (!isWithin(root, requestedCwd)) throw failure("outside-worktree", "Current directory is outside the Git worktree");
  return root;
}

async function resolveCommit(ref, root, execution, signal) {
  const result = await runBoundedGit(
    [...FIXED_GIT_ARGS, "rev-parse", "--verify", "--quiet", "--end-of-options", `${ref}^{commit}`],
    root,
    execution,
    signal,
  );
  if (result.exitCode !== 0) throw failure("ref-resolution-failed", "Git ref resolution failed");
  return objectIdFrom(result.stdout);
}

function parseStatus(buffer) {
  const value = buffer.toString("utf8");
  if (!value) return [];
  const entries = value.split("\0");
  if (entries[entries.length - 1] === "") entries.pop();
  return entries.map((entry) => {
    if (entry.length < 3 || entry[2] !== " ") throw failure("malformed-output", "Git returned malformed status output");
    return { index: entry[0], worktree: entry[1], path: entry.slice(3) };
  });
}

function parseNameStatus(buffer) {
  const value = buffer.toString("utf8");
  if (!value) return [];
  const entries = value.split("\0");
  if (entries[entries.length - 1] === "") entries.pop();
  if (entries.length % 2 !== 0) throw failure("malformed-output", "Git returned malformed name-status output");
  const records = [];
  for (let index = 0; index < entries.length; index += 2) {
    if (!entries[index] || !entries[index + 1]) throw failure("malformed-output", "Git returned malformed name-status output");
    records.push({ status: entries[index], path: entries[index + 1] });
  }
  return records;
}

function errorText(code) {
  switch (code) {
    case "output-limit":
      return "output limit exceeded; narrow paths or use stat/name-status";
    case "cancelled":
      return "git_read cancelled";
    case "timeout":
      return "git_read timed out";
    case "not-worktree":
    case "outside-worktree":
      return "git_read requires a current Git worktree";
    case "invalid-cwd":
      return "git_read could not resolve the current worktree";
    case "invalid-input":
      return "git_read input is invalid";
    case "ref-resolution-failed":
      return "git_read could not resolve the requested range ref";
    case "git-failed":
      return "git_read Git command failed";
    case "spawn-failed":
      return "git_read could not start Git";
    case "malformed-output":
      return "git_read received malformed Git output";
    case "binary-output":
      return "git_read omitted binary patch output";
    default:
      return "git_read failed";
  }
}

function detailsFor(request, execution, extra = {}) {
  return {
    action: request.action,
    ...(request.target ? { target: request.target } : {}),
    ...(request.view ? { view: request.view } : {}),
    paths: request.paths,
    bytes: execution.budget.bytes,
    lines: execution.budget.lines,
    caps: { bytes: MAX_OUTPUT_BYTES, lines: MAX_OUTPUT_LINES },
    ...extra,
  };
}

function makeErrorResult(code, execution, request, extra = {}) {
  return {
    content: [{ type: "text", text: errorText(code) }],
    details: {
      error: code,
      ...(request ? detailsFor(request, execution, extra) : {}),
      ...(request ? {} : { caps: { bytes: MAX_OUTPUT_BYTES, lines: MAX_OUTPUT_LINES }, ...extra }),
    },
    isError: true,
  };
}

function contentFitsResult(content, details) {
  const metadataBytes = Buffer.byteLength(JSON.stringify(details), "utf8");
  return metadataBytes <= MAX_RESULT_METADATA_BYTES
    && Buffer.byteLength(content, "utf8") + metadataBytes + 512 <= MAX_OUTPUT_BYTES;
}

async function executeGitRead(params, signal, ctx) {
  let request;
  try {
    request = normalizeRequest(params);
  } catch (error) {
    const code = error instanceof GitReadFailure ? error.code : "invalid-input";
    return makeErrorResult(code, { budget: new AggregateOutputBudget() });
  }

  const execution = {
    budget: new AggregateOutputBudget(),
    deadlineAt: Date.now() + EXECUTION_TIMEOUT_MS,
  };
  if (signal?.aborted) return makeErrorResult("cancelled", execution, request);

  try {
    const root = await resolveWorktree(ctx?.cwd, execution, signal);
    assertPathsWithinRoot(request.paths, root);
    const resolvedOids = {};
    if (request.action === DIFF_ACTION && request.target === "staged") {
      resolvedOids.head = await resolveCommit("HEAD", root, execution, signal);
    } else if (request.action === DIFF_ACTION && request.target === "range") {
      resolvedOids.base = await resolveCommit(request.base, root, execution, signal);
      resolvedOids.head = await resolveCommit(request.head, root, execution, signal);
    }

    const command = buildGitArgv(request, resolvedOids);
    const result = await runBoundedGit(command, root, execution, signal);
    if (result.exitCode !== 0) {
      const error = failure("git-failed", "Git returned a nonzero status");
      error.exitCode = result.exitCode;
      throw error;
    }
    let content;
    let extra = { exitCode: result.exitCode };
    if (request.action === STATUS_ACTION) {
      const records = parseStatus(result.stdout);
      content = JSON.stringify(records, null, 2);
      extra = { ...extra, recordCount: records.length };
    } else if (request.view === "name-status") {
      const records = parseNameStatus(result.stdout);
      content = JSON.stringify(records, null, 2);
      extra = { ...extra, recordCount: records.length };
    } else {
      content = result.stdout.toString("utf8");
      if (content.includes("\0")) throw failure("binary-output", "Git returned binary patch output");
    }
    if (request.target === "range") extra = { ...extra, baseOid: resolvedOids.base, headOid: resolvedOids.head };
    if (request.target === "staged") extra = { ...extra, headOid: resolvedOids.head };
    const details = detailsFor(request, execution, extra);
    if (!contentFitsResult(content, details)) throw failure("output-limit", "Git result is too large");
    return { content: [{ type: "text", text: content }], details };
  } catch (error) {
    const code = error instanceof GitReadFailure ? error.code : "git-failed";
    const extra = error instanceof GitReadFailure && Number.isInteger(error.exitCode)
      ? { exitCode: error.exitCode }
      : {};
    return makeErrorResult(code, execution, request, extra);
  }
}

const gitReadTool = {
  name: "git_read",
  label: "git_read",
  description: [
    "Read bounded Git status or diff evidence without shell access.",
    "Supports status and worktree, staged, or independently resolved range diffs",
    "with patch, stat, or name-status views and at most 32 literal repository paths.",
    "The current worktree is resolved from the Pi context; output is capped at 64 KiB",
    "and 2,000 line delimiters across all internal Git processes.",
  ].join(" "),
  promptSnippet: "Read bounded Git status or diff evidence",
  promptGuidelines: [
    "Use git_read for Git status/diff evidence instead of requesting generic shell access.",
    "Narrow paths or use stat/name-status when output-limit errors occur.",
  ],
  parameters: GitReadParameters,
  async execute(_toolCallId, params, signal, _onUpdate, ctx) {
    return executeGitRead(params, signal, ctx);
  },
};

export default function gitReadExtension(pi) {
  pi.registerTool(gitReadTool);
}
