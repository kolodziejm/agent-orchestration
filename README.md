# Agent Orchestration

Harness-agnostic source of truth for agent roles, delegation boundaries, validation/review gates, model routing, and harness adapters.

The repository separates stable orchestration semantics from replaceable executors:

```text
policy + role contracts + logical model profiles
                    ↓
             harness adapter
                    ↓
       OpenCode / Codex / Claude Code / Pi / future harnesses
```

## Source of truth

- `policy/orchestration.md` — human-readable orchestration invariants and gates.
- `policy/routing.toml` — machine-readable roles, permissions, and delegation graph.
- `roles/*.md` — provider- and harness-agnostic role contracts.
- `profiles/*.toml` — versioned concrete model/effort mapping for an execution profile,
  including the separate `[control_plane]` intent for the primary model, small model,
  and built-in `build`/`plan` mappings.
- `profiles/*.md` — profile-specific capability addenda.
- `adapters/validate.py` executes both Draft 2020-12 schemas before semantic
  checks, then validates the exact delegation graph: only known roles and the
  literal `vision-*` target are accepted, cycles fail closed, and every role
  outside the canonical delegator allowlist must remain a leaf.

Model identifiers belong only in profiles. Role contracts must not name providers.

## Current delegation model

```text
orchestrator
├── planner
│   ├── explorer
│   └── spec-writer
├── reviewer
│   └── explorer
├── worker
│   └── vision-*
├── worker-complex
│   └── vision-*
├── validator
├── debugger
├── design-partner
└── ux-critic
```

Delegation is for leverage, not ceremony. The primary may directly execute a coherent,
bounded low- or medium-risk change when no context-protection, independent-verification,
real parallelism, specialization, or risk separation reason requires delegation. Delegated
source-changing worker output still requires an independent validator. Workers may author
tests in scope but must not execute verification; `validator` owns predefined deterministic
acceptance, including browser/device checks. `worker` is the routine executor and
`worker-complex` is reserved for sufficiently specified changes whose implementation
requires unusually difficult reasoning. A stronger worker must not compensate for unclear
product intent. Independent ready mutation lanes are parallel-by-default when the harness
provides safe isolation; otherwise they are serialized with a concise reason. Planner and
reviewer delegate broad mechanical evidence gathering to `explorer` and prefer parallel
fanout for two or three genuinely independent scopes when the harness supports it.

## OpenCode adapter

Requires Python 3.11 or newer (`python3` on `PATH`).

Render committed snapshots:

```bash
./scripts/render
```

Run contract tests and ensure snapshots are current in the reproducible uv environment:

```bash
uv run --locked ./scripts/check
```

The project requires Python 3.11 or newer and pins PyYAML 6.0.2 and jsonschema 4.25.1
in `pyproject.toml` and `uv.lock`. The scripts also work when invoked directly with a
3.11+ `python3`; on macOS
systems whose `/usr/bin/python3` is 3.9, use the uv command above. Scripts detect an
already-active uv environment and do not recursively invoke uv.

Preview installation against the active OpenCode configuration:

```bash
./scripts/install-opencode --dry-run
```

For an isolated preview, always pass a fixture target rather than the active configuration:

```bash
uv run --locked ./scripts/install-opencode --target /tmp/opencode-fixture --dry-run --skip-validate
```

On a first installation, existing managed role files, instruction files, or
managed agent entries are reported as collisions and no changes are made. If
those names are intentionally being taken over, rerun with `--adopt` (the
dry-run flag can be combined with it to inspect the takeover).

Install, back up changed files, and validate every configured profile with `opencode debug config`:

```bash
./scripts/install-opencode
```

The installer merges generated agent routing and the selected versioned profile's control
plane into existing profile `opencode.json` files. The primary model/variant and
`small_model` are managed at the config root; built-in `build` and `plan` mappings are
managed under `agent`. It preserves unrelated provider, plugin, skill, MCP, compaction,
and model-limit configuration. On validation failure it restores the original files.

The optional `workflows/feature-workflow-pilot.md` artifact is copied separately and is
not added to profile `instructions`, so its detailed procedure is not injected into every
base prompt.

Compare an effective OpenCode configuration to the selected profile without changing it:

```bash
uv run --locked ./scripts/check-runtime --profile openai --target ~/.config/opencode
```

`check-runtime` reports actionable drift for the primary model/effort, `small_model`,
built-in mappings, managed instruction paths, and managed subagent model/variant entries.
It reads only known fields and never prints credentials or the complete runtime config.

The local `.agent-orchestration.manifest.json` records exactly which roles and profiles are managed. This allows later policy versions to remove obsolete generated agents without deleting unrelated user-defined agents or instructions.

Backups are written under unique, namespaced directories per adapter:

```text
~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/opencode/
~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/claude-code/
```

## Codex adapter

The Codex adapter consumes the same canonical policy and the `openai` profile. It renders the ten role contracts as standalone Codex agent TOML files, the selected control-plane intent as `control-plane.toml`, and the policy and profile addendum into `AGENTS.md`:

```bash
./scripts/render
./scripts/check
```

The adapter removes the `openai/` provider prefix from model identifiers, maps the profile `variant` to Codex `model_reasoning_effort` (`max` becomes Codex's `xhigh`), and maps canonical `edit = deny` to `read-only` while writable roles use `workspace-write`. Codex cannot represent canonical `bash = deny`; the renderer fails before writing if that capability is configured, so it never silently grants shell access. The optional feature workflow is copied separately under `generated/codex/workflows/`. It does not write to `~/.codex`; it only generates repository snapshots. Copy or symlink `generated/codex/AGENTS.md`, `generated/codex/control-plane.toml`, and `generated/codex/agents/*.toml` into the Codex locations you choose. There is no installer, deployment manager, backup, adoption, or rollback logic.

## Claude Code adapter

Render committed snapshots (also renders the OpenCode and Codex snapshots):

```bash
./scripts/render
```

Run contract tests and ensure snapshots are current:

```bash
./scripts/check
```

Preview installation against the active Claude Code configuration:

```bash
./scripts/install-claude-code --dry-run
```

Install and back up changed files:

```bash
./scripts/install-claude-code
```

Claude Code also reports existing unmanaged managed-name files or sections on
first install. Use `--adopt` to explicitly take ownership after reviewing the
collision list; subsequent installations use the manifest as before.

The installer copies each rendered `agents/<role>.md` subagent file into `<target>/agents/`,
copies the optional workflow under `<target>/workflows/`, and merges the shared
orchestration policy into `<target>/CLAUDE.md` by replacing only the section between the
`<!-- agent-orchestration:start -->` / `<!-- agent-orchestration:end -->` markers (or
appending it if absent). Content outside the markers is preserved untouched. The default
target is `~/.claude`, overridable with `--target`.

Unlike OpenCode, a Claude Code subagent file has no separate profile-routing layer: the active profile's `model` and `effort` are baked directly into each agent's frontmatter at render time. The renderer also emits `_shared/control-plane.md`, which records the profile intent and truthfully states that Claude Code cannot install the primary model, small model, or built-in `build`/`plan` mappings; those require manual session configuration. The `harness` field controls which renderer picks up a profile: OpenCode selects `harness = "opencode"` (the backward-compatible default), Claude Code selects the single `harness = "claude-code"` profile, and Pi-only profiles declare `harness = "pi"`. Codex accepts only explicitly selected OpenCode/Codex-compatible profiles. Every scanning adapter recognizes and intentionally skips known profiles for other harnesses while still rejecting unknown harness values.

### Claude Code permission degradation

Claude Code has no per-subagent equivalent of OpenCode's `bash = "ask"` permission; prompts are configured at the session level, not per agent file. `Bash` is therefore granted to every rendered agent, including read-only roles, since they still need it for investigation. If a role declares `bash = "deny"`, the renderer fails before writing because Claude Code cannot preserve that prohibition. Claude Code uses a flat subagent topology: the orchestrator performs the logical policy's nested delegation, invokes `explorer` directly when planner or reviewer evidence is needed, and includes that evidence in the handoff. Rendered subagent files contain no `Agent(explorer)` or `Agent(spec-writer)` entries; all delegated targets are omitted from their frontmatter. The native-vision Claude profile therefore needs no separate `vision-*` delegation.

Subagents rendered from role files start without parent history, which satisfies the policy's no-history default. `subagent_type: "fork"` (full-history) is allowed only as the documented exception, with the reason stated in the handoff. The `model` parameter of the `Agent` tool must never be passed; model and effort are baked into each role's frontmatter by the active profile. Built-in harness agents (e.g. `general-purpose`, `Explore`, `Plan`, `claude`) must not be used while a matching role exists; they are allowed only when no role covers the work, with the reason stated in the handoff.

The local `.agent-orchestration.manifest.json` under the target directory tracks managed roles,
the optional workflow, and the non-installable control-plane note the same way as the
OpenCode adapter, so obsolete generated agents and artifacts are removed without deleting
unrelated agents or CLAUDE.md content.

## Generated snapshots

`generated/opencode/`, `generated/codex/`, `generated/claude-code/`, and the isolated
`generated/pi/hybrid/`, `generated/pi/openai/`, and `generated/pi/deepseek/` bundles are committed snapshots,
intentionally. They include the separately
packaged optional workflow and the harness-specific control-plane artifact. A policy or
profile change must show both:

1. the harness-agnostic semantic change;
2. its exact per-harness output.

CI rerenders snapshots and fails on drift.

## Pi adapter

The Pi adapter requires a locally installed `pi-subagents` release at or above the
v0.67.0 minimum-supported, tested baseline in each profile directory. It renders a
default hybrid bundle plus provider-pure OpenAI and DeepSeek alternatives. The provider-pure
OpenAI profile routes `worker-complex` to GPT-5.6 Luna with maximum reasoning. The hybrid
profile keeps its primary, built-ins, debugger, planner, and reviewer on GPT-5.6 Sol
while routing the small model, routine and complex workers, validator, explorer,
spec-writer, design-partner, and UX critic to direct DeepSeek V4.1 Flash. The complex
worker uses the model's maximum reasoning level. Provider mapping is explicit and fail-closed:
`openai/<id>` becomes `openai-codex/<id>` and `deepseek/<id>` remains
`deepseek/<id>`; only the hybrid profile permits both prefixes, while provider-pure
profiles reject cross-provider, unknown, and malformed tokens. Each bundle bakes the
role's mapped model and variant (as `thinking`) into exactly ten `agents/*.md`
definitions. Every role explicitly uses
`defaultContext: fresh`, a strict tool allowlist, replacement system prompts, and no
inherited project context or skill catalog. The `extensions` field is intentionally
omitted, so normal Pi extensions remain available subject to each role's strict tool
allowlist.

Render and check the snapshot through the standard entrypoints:

```bash
./scripts/render
uv run --locked ./scripts/check
```

Preview a user installation without changing it:

```bash
./scripts/install-pi --profile hybrid --dry-run
./scripts/install-pi --profile openai --dry-run
./scripts/install-pi --profile deepseek --dry-run
```

The default profile is `hybrid`, and its target is the main bare-Pi runtime at
`~/.pi/agent`. Provider-pure OpenAI and DeepSeek target `~/.pi/profiles/openai` and
`~/.pi/profiles/deepseek`; use `--target` for an isolated fixture. The installer places the matching
`pi-hybrid`, `pi-openai`, or `pi-deepseek` launcher in `~/.local/bin` by default; use `--bin-dir`
for an isolated fixture. Launchers invoke `$HOME/.nvm/versions/node/v24.15.0/bin/pi` with its colocated
Node runtime rather than ambient `PATH`, share sessions under
`$HOME/.pi/agent/sessions`, forward all arguments exactly, and contain no credentials.
Install both switchable profiles, then exit the current Pi process before starting the
other launcher (profile roots are selected only at process startup):

```bash
./scripts/install-pi --profile hybrid
./scripts/install-pi --profile openai --source ~/.pi/agent
pi-hybrid   # mixed OpenAI + DeepSeek routing at ~/.pi/agent
pi-openai   # OpenAI-only routing at ~/.pi/profiles/openai
```

The OpenAI bootstrap validates the working hybrid runtime, resolves every configured
package to its real package root, installs provider-pure settings and model metadata,
and copies only the `openai-codex` OAuth record into the isolated root with mode `0600`.
Credential values are never printed or written to repository artifacts. The OpenAI
profile requires `@narumitw/pi-usage` 0.31.1 or newer with its public
`adapterForProvider`, `resolveUsageAuth`, and `queryProviderUsage` exports.

A real hybrid install reads `<target>/npm/node_modules/pi-subagents/package.json`; an
OpenAI install bootstraps that runtime metadata from the validated `--source` (default
`~/.pi/agent`). Both fail closed unless it reports a valid release at or above v0.67.0.
On first installation, existing files at managed
role or artifact names require explicit `--adopt`. The installer backs up every changed
or removed file under a unique
`~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/pi/` directory,
validates the installed definitions, removes only stale roles recorded in its own
manifest, and rolls back validation failures and interruptions. Hybrid settings remain
untouched; OpenAI settings are generated from validated package roots and forced to
OpenAI-only defaults. The hybrid installer preserves a valid existing direct
DeepSeek catalog entry (including valid newer data), otherwise seeds the committed
credential-free official DeepSeek V4.1 Flash entry; `--source` can instead supply a
validated provider entry from another `models-store.json`. A manifest-owned legacy OpenAI
installation at the main target is migrated in place to the hybrid profile; other profile
mismatches still fail closed. For DeepSeek, it merges the required source packages into `settings.json`
and seeds the validated `deepseek` provider/model entry from the source
`models-store.json`, preserving unrelated settings, providers, packages, extensions,
and agent files. An existing valid DeepSeek catalog entry is retained so a newer local
catalog is not downgraded. Catalog bootstrap does not authenticate the provider:
configure a provider environment variable or complete Pi's `/login deepseek` flow
manually. Shared policy, control-plane intent, degradation notes, and the optional
workflow are namespaced under `<target>/agent-orchestration/`.

### Pi profile status indicators

The indicators are versioned adapter sources, rendered into snapshots, and installed as
profile-owned extensions rather than patches to `node_modules`:

- Hybrid shows `DS peak ×1` during 01:00–04:00 and 06:00–10:00 UTC Monday–Friday.
  Every boundary outside those half-open periods, plus all weekend hours, shows
  `DS off-peak ×0.5`. This deterministic clock-only indicator makes the official
  half-price off-peak schedule visible without an API request and refreshes every minute.
- OpenAI keeps `@narumitw/pi-usage`'s remaining/reset status and adds weekly Codex pace.
  `pace` is `consumed% − elapsed%` in percentage points, so a positive value means usage
  is ahead of schedule. `proj` is projected end utilization (`consumed / elapsed × 100`)
  once at least 1% of the weekly window has elapsed. It refreshes at session start, model
  change, and every five minutes. Missing, stale, invalid, or failed weekly data renders
  `pace unavailable`; immediately after reset, projection is shown as `—`. Error bodies
  and OAuth values are never displayed or persisted.

Pi's native child permissions deliberately reject `permissions.bash`; if `bash` is in
an agent's tool list, pi-subagents always passes it through. The adapter therefore omits
`bash` from canonical shell-`ask` roles, enforcing a stricter no-shell ceiling. Use a
separately configured permission wrapper for command-level policy. Pi agent files
configure child roles and each profile launcher selects the primary model. Planner and
reviewer additionally load child-only, profile-owned guards through pi-subagents'
public `./capability-ceiling` export: planner allows only `explorer` and
`spec-writer`, while reviewer allows only `explorer`. Missing package resolution or
registration fails closed, and the guard is a child-selection boundary rather than an
OS sandbox or general command classifier. All other canonical roles lack `subagent`,
so they are leaves at the Pi tool boundary. Pi cannot install the small model or
built-in build/plan mappings, so each bundle's `_shared/control-plane.json` records
those values as non-installed intent. Neither profile has a concrete `vision-*` agent
among the canonical ten; both selected models declare native vision, so wildcard
visual delegation remains guidance rather than an advertised runtime agent.

The normal `./scripts/check` / `uv run --locked ./scripts/check` path is deterministic,
credential-free, and never invokes a provider. An optional paid OpenAI integration
canary is deliberately separate and local-only; it is available but not run by
CI/default checks. It refuses without both explicit opt-in and acknowledgement,
refuses whenever `CI` is set, requires the existing `pi-openai` launcher, and bounds
its temporary workspace, runtime, output, and child count. Run it only when you
accept OpenAI usage:

```bash
AGENT_ORCHESTRATION_PI_LIVE_CANARY=1 \
AGENT_ORCHESTRATION_PI_LIVE_CANARY_ACK=I_ACCEPT_OPENAI_USAGE \
./scripts/pi-live-canary
```

## Adding a role

1. Add the role to `policy/routing.toml`.
2. Add `roles/<role>.md` without provider/model identifiers.
3. Map the role in every versioned `profiles/*.toml` file.
4. Keep each profile's `[control_plane]` and `capabilities.supported_variants` valid.
5. Run `uv run --locked ./scripts/render` and `uv run --locked ./scripts/check`.
6. Review the generated permission, model-routing, and control-plane diff.

## Adding another harness

Create an adapter under `adapters/<harness>/` that consumes only `policy/`, `roles/`, and `profiles/`. Harness-specific permissions, prompt frontmatter, config paths, and installation mechanics belong in the adapter, not in role contracts.

Currently supported: OpenCode (`adapters/opencode/`), Codex (`adapters/codex/`),
Claude Code (`adapters/claude-code/`), and Pi (`adapters/pi/`).

## Security

Do not commit credentials, environment files, session data, provider tokens, or complete runtime configurations. Profile files contain model IDs only. Installers must merge into local configs rather than copying secrets into this repository. `scripts/check-runtime` is read-only and reports only the known model, effort, instruction, and managed-agent fields.
