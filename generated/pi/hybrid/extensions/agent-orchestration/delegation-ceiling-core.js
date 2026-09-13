import { readFileSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const PACKAGE_NAME = "pi-subagents";
const CAPABILITY_EXPORT = "./capability-ceiling";
const LOCAL_PACKAGE_RELATIVE = join("npm", "node_modules", PACKAGE_NAME);
const MAX_AGENT_NAMES = 16;

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new Error("Unable to load the Pi capability-ceiling package");
  }
}

function packageManifest(root) {
  const manifest = readJson(join(root, "package.json"));
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("Unable to load the Pi capability-ceiling package");
  }
  if (manifest.name !== PACKAGE_NAME) {
    throw new Error("Unable to load the Pi capability-ceiling package");
  }
  return manifest;
}

function validPackageRoot(root) {
  try {
    packageManifest(root);
    return true;
  } catch {
    return false;
  }
}

function absoluteConfiguredPackageSources(profileRoot) {
  let settings;
  try {
    settings = readJson(join(profileRoot, "settings.json"));
  } catch {
    throw new Error("Unable to resolve the Pi capability-ceiling package");
  }
  if (!settings || typeof settings !== "object" || !Array.isArray(settings.packages)) {
    throw new Error("Unable to resolve the Pi capability-ceiling package");
  }
  return settings.packages.flatMap((entry) => {
    const source = typeof entry === "string" ? entry : entry?.source;
    return typeof source === "string" && isAbsolute(source) ? [resolve(source)] : [];
  });
}

export function resolvePiSubagentsPackageRoot(profileRoot) {
  if (typeof profileRoot !== "string" || !profileRoot) {
    throw new Error("Pi profile root is unavailable");
  }
  const root = resolve(profileRoot);
  const localRoot = join(root, LOCAL_PACKAGE_RELATIVE);
  if (validPackageRoot(localRoot)) return localRoot;

  for (const configuredRoot of absoluteConfiguredPackageSources(root)) {
    if (validPackageRoot(configuredRoot)) return configuredRoot;
  }
  throw new Error("Unable to resolve the Pi capability-ceiling package");
}

export function resolvePiSubagentsCapabilityEntrypoint(profileRoot) {
  const packageRoot = resolvePiSubagentsPackageRoot(profileRoot);
  const manifest = packageManifest(packageRoot);
  const exportsField = manifest.exports;
  const target = exportsField && !Array.isArray(exportsField)
    ? exportsField[CAPABILITY_EXPORT]
    : undefined;
  if (typeof target !== "string" || !target.startsWith("./")) {
    throw new Error("Pi capability-ceiling public export is unavailable");
  }
  const entrypoint = resolve(packageRoot, target);
  const escaped = relative(packageRoot, entrypoint).startsWith("..")
    || isAbsolute(relative(packageRoot, entrypoint));
  if (escaped) throw new Error("Pi capability-ceiling public export is unavailable");
  return pathToFileURL(entrypoint).href;
}

export async function loadPiSubagentsCapabilityCeiling(profileRoot) {
  const entrypoint = resolvePiSubagentsCapabilityEntrypoint(profileRoot);
  const api = await import(entrypoint);
  if (!api || typeof api.registerSubagentCapabilityCeiling !== "function") {
    throw new Error("Pi capability-ceiling public export is unavailable");
  }
  return api.registerSubagentCapabilityCeiling;
}

const configuredRegisterSubagentCapabilityCeiling = await loadPiSubagentsCapabilityCeiling(
  process.env.PI_CODING_AGENT_DIR,
);

function validateExtensionOptions(options) {
  if (!options || typeof options !== "object") {
    throw new Error("Pi delegation ceiling options are unavailable");
  }
  if (typeof options.source !== "string" || !options.source) {
    throw new Error("Pi delegation ceiling source is unavailable");
  }
  if (!Array.isArray(options.allowedAgents) || options.allowedAgents.length > MAX_AGENT_NAMES) {
    throw new Error("Pi delegation ceiling allowed agents are unavailable");
  }
  if (!options.allowedAgents.length || options.allowedAgents.some(
    (agent) => typeof agent !== "string" || !agent,
  )) {
    throw new Error("Pi delegation ceiling allowed agents are unavailable");
  }
}

export function createDelegationCeilingExtension(pi, options) {
  validateExtensionOptions(options);
  const register = options.register ?? configuredRegisterSubagentCapabilityCeiling;
  if (typeof register !== "function") {
    throw new Error("Pi capability-ceiling registration is unavailable");
  }
  const source = options.source;
  const allowedAgents = Object.freeze([...options.allowedAgents]);
  let handle;

  const dispose = () => {
    if (!handle) return;
    const previous = handle;
    handle = undefined;
    if (typeof previous.dispose !== "function") {
      throw new Error("Pi capability-ceiling registration is unavailable");
    }
    previous.dispose();
  };

  const start = (_event, context) => {
    // A repeated session_start must not leave an earlier registration active.
    dispose();
    const sessionId = context?.sessionManager?.getSessionId?.();
    if (typeof sessionId !== "string" || !sessionId) {
      throw new Error("Pi session identity is unavailable");
    }
    const next = register({
      sessionId,
      source,
      ceiling: { allowedAgents },
    });
    if (!next || typeof next.dispose !== "function") {
      throw new Error("Pi capability-ceiling registration is unavailable");
    }
    handle = next;
  };

  pi.on("session_start", start);
  pi.on("session_shutdown", dispose);
}

export default createDelegationCeilingExtension;
