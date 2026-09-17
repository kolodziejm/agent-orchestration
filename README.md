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
  checks, then validates the exact delegation graph: only known canonical roles
  are accepted, cycles fail closed, and every role outside the canonical
  delegator allowlist must remain a leaf.

Model identifiers belong only in profiles. Role contracts must not name providers.

## Current delegation model

```text
orchestrator
├── planner
│   └── explorer
├── reviewer
│   └── explorer
├── worker
├── worker-complex
├── validator
├── debugger
├── design-partner
└── ux-critic
```

Delegation is for leverage, not ceremony. The primary may directly execute a coherent,
bounded low- or medium-risk change when no context-protection, independent-verification,
real parallelism, specialization, or risk separation reason requires delegation. Every
source-changing handoff owns at most one independently verifiable slice and one validator
checkpoint; unbounded or whole-initiative delegation is prohibited. Each delegation has
an explicit stop condition and execution cap, and potentially non-brief work runs in the
background when supported so the primary remains responsive. Delegated source-changing
worker output still requires an independent validator. Workers may author tests in scope
but must not execute verification; `validator` owns predefined deterministic acceptance,
including browser/device checks. Both worker tiers are leaves; the primary routes visual
work directly to existing image-capable roles. `worker` is the routine executor and
`worker-complex` is reserved for sufficiently specified changes whose implementation
requires unusually difficult reasoning. A stronger worker must not compensate for unclear
product intent. After scope is known, large analysis spanning at least two independent
top-level areas or a large file set MUST use 2–4 concurrent, non-overlapping `explorer`
evidence lanes, followed by one synthesis owner/writer and a serial validator. Pi uses a
single `runs.all` wave; other harnesses use their equivalent concurrent batch. Serialize
only for a genuine data dependency, indivisible shared state, or too-small scope, and
record the reason. Internal handoffs, schemas, workflow labels, and non-user-facing
reports default to concise technical English; preserve original-language quotations plus
an English normalization when nuance matters, while user-facing replies and artifacts stay
in the user's requested language.

## Reviewable-PR delivery

When a repository has suitable hosting/remote support and the harness has the capability and authorization, a pull request is the default delivery and review unit. Use one coherent concern per PR (and per fallback unit). Treat `<=400` human-authored maintained changed lines and `<=12` human-authored maintained changed files as a reviewability heuristic/target, not a mandate; do not split a coherent concern solely to hit a number. Generated artifacts and lockfiles are excluded from those limits, but their lines/files are counted and reported separately. A `401–800` line or `13–24` file slice needs concrete rationale and explicit user approval before implementation or promotion unless a user-approved named stack/ordered-unit plan pre-authorizes that named unit and records the rationale; `>800` human-authored lines or `>24` human-authored files must be split and cannot be approved wholesale. Prefer fewer units when adjacent units repeatedly touch the same 2–3 files and are not independently understandable, mergeable, and reviewable; coherence and independent merge/review value outrank numeric optimization.

If PR creation or remote access is unavailable or unauthorized, prepare an equivalently reviewable local branch, commit, or patch and label it as a fallback—never claim a remote action. Parallel implementation is limited to isolated, non-overlapping branches/worktrees, while promotion remains ordered. A user-approved named stack/ordered-unit plan authorizes uninterrupted execution of its already bounded units in the named order without routine approval waits between them. After every PR or fallback unit, present a bird's-eye checkpoint automatically as a non-blocking progress report covering purpose/concern, before/after behavior, decisions, separate human-authored/generated/lockfile diff stats, affected areas/files, risks, validation evidence, residual work, and the next proposed unit. Checkpoints do not authorize merge, promotion, or remediation; existing review, finding/remediation, and merge authorization gates remain in force. Ask again only for a material scope or acceptance change, a requested hard-ceiling exception, a new risk or product decision, or a failed/BLOCKED validation that requires a decision. This contract does not add GitHub-provider automation, credentials, or hosting assumptions, and does not automatically create branches, commits, or pull requests.

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

The Codex adapter consumes the same canonical policy and the `openai` profile. It renders the nine role contracts as standalone Codex agent TOML files, the selected control-plane intent as `control-plane.toml`, and the policy and profile addendum into `AGENTS.md`:

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

Claude Code has no per-subagent equivalent of OpenCode's `bash = "ask"` permission; prompts are configured at the session level, not per agent file. `Bash` is therefore granted to every rendered agent, including read-only roles, since they still need it for investigation. If a role declares `bash = "deny"`, the renderer fails before writing because Claude Code cannot preserve that prohibition. Claude Code uses a flat subagent topology: the orchestrator performs the logical policy's nested delegation, invokes `explorer` directly when planner or reviewer evidence is needed, and includes that evidence in the handoff. Rendered subagent files contain no `Agent(explorer)` entries; all delegated targets are omitted from their frontmatter. The native-vision Claude profile inspects images directly.

Subagents rendered from role files start without parent history, which satisfies the policy's no-history default. `subagent_type: "fork"` (full-history) is allowed only as the documented exception, with the reason stated in the handoff. The `model` parameter of the `Agent` tool must never be passed; model and effort are baked into each role's frontmatter by the active profile. Built-in harness agents (e.g. `general-purpose`, `Explore`, `Plan`, `claude`) must not be used while a matching role exists; they are allowed only when no role covers the work, with the reason stated in the handoff.

The local `.agent-orchestration.manifest.json` under the target directory tracks managed roles,
the optional workflow, and the non-installable control-plane note the same way as the
OpenCode adapter, so obsolete generated agents and artifacts are removed without deleting
unrelated agents or CLAUDE.md content.

## Generated snapshots

`generated/opencode/`, `generated/codex/`, `generated/claude-code/`, and the isolated
`generated/pi/hybrid/`, `generated/pi/openai/`, `generated/pi/deepseek/`, and `generated/pi/glm/` bundles are committed snapshots,
intentionally. They include the separately
packaged optional workflow and the harness-specific control-plane artifact. A policy or
profile change must show both:

1. the harness-agnostic semantic change;
2. its exact per-harness output.

CI rerenders snapshots and fails on drift.

## Pi adapter

The Pi adapter renders a default hybrid bundle plus OpenAI, DeepSeek, and Z.AI GLM
routing profiles. The manifest's `format_version: 1` is the internal orchestration bundle schema, not a Pi host or runtime version.
The installer manages only manifest-owned policy, agent, workflow, extension, and launcher artifacts; it does not install, select, migrate, or validate framework packages.
Active Tintinweb and other runtime packages remain operator-owned. The installer never modifies settings, catalogs, auth, MCP, themes, and provider state.

The OpenAI profile routes `worker-complex` to GPT-5.6 Luna with maximum reasoning. The
hybrid profile keeps its primary, built-ins, debugger, planner, and reviewer on GPT-5.6
Sol while routing the small model, routine and complex workers, validator, explorer,
design-partner, and UX critic to direct DeepSeek V4.1 Flash. The complex worker uses the
model's maximum reasoning level. Model mapping is explicit and fail-closed:
`openai/<id>` becomes `openai-codex/<id>`, `deepseek/<id>` remains
`deepseek/<id>`, and `zai/<id>` remains `zai/<id>`. Unknown and malformed tokens are
rejected. Each bundle bakes the role's mapped model and variant (as `thinking`) into
exactly nine `agents/*.md` definitions. Every role explicitly uses
`defaultContext: fresh`, a strict tool allowlist, replacement system prompts, and no
inherited project context or skill catalog. The `extensions` field is intentionally
omitted, so normal Pi extensions remain available subject to each role's strict tool
allowlist. Each profile bundle also loads the managed `primary-policy.js` extension.
The rendered Pi shared policy requires `max_turns` on every Agent call, defaults
source-changing worker calls to `run_in_background: true`, and recommends caps of
foreground ≤12 turns and background mutation ≤30 turns. Potentially blocking child tool
calls must use their native timeout or an OS/harness-enforced timeout; `max_turns` alone
cannot bound one tool call. When timeout and termination cannot be enforced, the operation
is not delegated and stays bounded in the primary or returns `BLOCKED`. On primary
`before_agent_start`, it appends the installed
`agent-orchestration/_shared/orchestration-core.md` exactly once; child processes marked
`PI_SUBAGENT_CHILD=1` are left unchanged. This uses Pi's system-prompt hook without
managing or replacing user `AGENTS.md`, `APPEND_SYSTEM.md`, or project context files.

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
./scripts/install-pi --profile glm --dry-run
```

The default profile is `hybrid`, and its target is the main bare-Pi runtime at
`~/.pi/agent`. The OpenAI, DeepSeek, and Z.AI GLM profiles target
`~/.pi/profiles/openai`, `~/.pi/profiles/deepseek`, and `~/.pi/profiles/glm`; use
`--target` for an isolated fixture. The installer places the matching `pi-hybrid`,
`pi-openai`, `pi-deepseek`, or `pi-glm` launcher in `~/.local/bin` by default; use
`--bin-dir` for an isolated fixture. Launchers invoke the configured Pi executable with its colocated Node runtime rather than ambient `PATH`,
share sessions under `$HOME/.pi/agent/sessions`, forward all arguments exactly, and contain no credentials. Install switchable profiles, then exit the current Pi process before starting the other launcher (profile roots are selected only at
process startup):

```bash
./scripts/install-pi --profile hybrid
./scripts/install-pi --profile openai
./scripts/install-pi --profile glm
pi-hybrid   # mixed OpenAI + DeepSeek routing at ~/.pi/agent
pi-openai   # OpenAI routing at ~/.pi/profiles/openai
pi-glm      # Z.AI GLM Coding Plan at ~/.pi/profiles/glm
```

On first installation, existing files at manifest-owned names require explicit `--adopt`.
The installer backs up every changed or removed manifest-owned file under a unique
`~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/pi/` directory,
validates only the installed bundle artifacts and launchers, removes stale claims recorded
in its own manifest, and rolls back validation failures and interruptions. Each managed-file
write is atomic: existing destination modes are preserved unless a mode is specified, new
ordinary bundle files use `0644`, and launchers are explicitly executable. Caught failures
restore the snapshotted bytes and modes. Abrupt process or host termination cannot produce
a partially written individual managed file, but it may leave a mix of complete old and new
bundle files; rerun the installer to repair that mix. Dry-run prints the planned writes and
deletions without changing the target. Existing runtime files are
left byte-for-byte untouched, including settings, catalogs, auth, MCP, themes, provider
state, sessions, caches, logs, analytics, and runtime history. Credential values are never
printed or written to repository artifacts. A prior manifest's legacy operator-owned
claims are dropped without deleting those files; retired project artifacts remain subject
to the manifest's ordinary stale cleanup. Shared policy, control-plane intent, degradation
notes, and the optional workflow are namespaced under `<target>/agent-orchestration/`.

### Pi planning, validator MCP, and operator-owned runtime state

Planner is structurally read-only, delegates only to `explorer`, and returns its complete
implementation-ready plan/spec through the harness-managed child result/output facility.
After the applicable approval, one selected `worker` or `worker-complex` persists authorized
plans, specs, prototypes, source, configuration, tests, and documentation. No planner path
binding or replacement planning-artifact guard is installed.

Validator has a separate deterministic browser/Appium MCP allowlist from UX-Critic.
It excludes lifecycle, session/device management, code evaluation, upload/drop/tab,
video/recording, file, driver-settings, perform-actions, and clipboard controls.
Direct MCP execution requires a prepared URL/session and supported async child; when
those prerequisites are unavailable, validator acceptance is `BLOCKED`, not delegated
to UX-Critic. UX-Critic remains a separate, explicit, on-demand heuristic audit.

Permissions, authentication, MCP configuration, theme selection, and theme files are
operator-owned runtime state. The Pi bundle and installer never copy, create, adopt,
validate, or claim those paths; existing files retain their bytes and metadata, and fresh
roots contain none of them. The one-time manifest migration drops legacy permission/theme
claims without deleting those files, while retired project artifacts continue through the
ordinary stale cleanup and rollback transaction.

### Pi `git_read` explorer capability

Every rendered hybrid, OpenAI, DeepSeek, and GLM Pi profile copies the manifest-owned
`extensions/agent-orchestration/git-read.ts` extension and loads it from the extension
package alongside the profile's existing status entrypoint. Only the `explorer` child
allowlist contains `git_read`; explorer still has no `bash`, and every other role excludes
it. Explorer frontmatter declares `acceptanceRole: read-only` for acceptance inference only;
that metadata does not grant or revoke tools or command execution. The installer validates
this ownership, allowlist, and role metadata during adoption, idempotent updates, stale
managed-file cleanup, backup, and rollback.

`git_read` supports exactly `status`, or `diff` against `worktree`, `staged`, or a
conservatively resolved `range`. Diff views are `patch`, `stat`, and `name-status`, with
at most 32 unique repository-relative literal paths. It accepts no repository or cwd
parameter: the extension canonicalizes Pi's current cwd, finds the nearest non-symlinked `.git`
directory or linked-worktree marker file independently of Git configuration, requires Git's
reported top level to exactly equal that trusted marker boundary, rejects configured worktrees
that widen it, and runs all later commands at the canonical worktree root. Range endpoints are
validated and resolved independently to full commit OIDs before the final diff; authored
revision expressions never reach Git's diff command.

The dedicated reader uses literal `git` with argv arrays, `shell: false`, a fixed system
PATH (`/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:/opt/local/bin`) and allowlisted
deterministic environment; unusual Git installations fail closed rather than accepting a
request-controlled executable. Every invocation disables network/lazy
fetching, hooks, pagers, external diff, textconv, color, rename detection, and submodule
recursion. One execution-wide 10-second deadline and aggregate 64 KiB/2,000-line
stdout+stderr caps cover probing, ref resolution, and the final command; cancellation and
timeout use bounded termination. No full output is persisted. This extension deliberately
uses a private bounded `child_process.spawn` helper because the host's `pi.exec` buffers
output without a hard transient cap.

### Pi profile status indicators

The indicators are versioned adapter sources, rendered into snapshots, and installed as
profile-owned extensions rather than patches to the operator's installed package tree:

- Hybrid and standalone DeepSeek show `DS peak ×1` for 01:00–04:00 and 06:00–10:00 UTC Monday–Friday. Every boundary outside those half-open periods, plus all weekend hours,
  shows `DS off-peak ×0.5`. This deterministic clock-only indicator makes the official
  half-price off-peak schedule visible without an API request and refreshes every minute.
- OpenAI keeps the configured usage integration's remaining/reset status and adds weekly Codex pace.
  `pace` is `consumed% − elapsed%` in percentage points, so a positive value means usage
  is ahead of schedule. `proj` is projected end utilization (`consumed / elapsed × 100`)
  once at least 1% of the weekly window has elapsed. It refreshes at session start, model
  change, and every five minutes. Missing, stale, invalid, or failed weekly data renders
  `pace unavailable`; immediately after reset, projection is shown as `—`. Error bodies
  and OAuth values are never displayed or persisted.
- GLM shows `GLM peak ×3` for GLM-5.3 during 06:00–10:00 UTC Monday–Friday and
  `GLM off-peak ×1` at all other times, including weekends. GLM-5.3-Flash is billed at
  ×1.2 during peak and ×0.4 off-peak; those Flash multipliers are documented here but
  are not shown in the compact footer. The clock-only indicator refreshes at each UTC
  minute boundary and makes no network or API calls.

Pi's native child permissions deliberately reject `permissions.bash`; if `bash` is in
an agent's tool list, the Pi host passes it through. The adapter therefore omits
`bash` from canonical shell-`ask` roles, enforcing a stricter no-shell ceiling. Command-level
permission configuration remains operator-owned and is not copied or claimed by this project.
Pi agent files configure child roles and each profile launcher selects the primary model.
Planner and reviewer retain the `subagent` tool, while canonical policy restricts each to the
exact child target `explorer`; all other canonical roles lack `subagent`, so they are leaves at
the Pi tool boundary. Under runtimes without a public framework-neutral child-target
enforcement API, that exact restriction is a policy-level boundary represented in role
contracts and rendered tool lists, not runtime enforcement. This bundle does not claim
fail-closed package integration, and the policy guidance is not an OS sandbox or general
command classifier. Pi cannot install the small model or built-in build/plan mappings, so
each bundle's `_shared/control-plane.json` records those values as non-installed intent.
When the primary cannot inspect images natively, it routes visual work once directly to
existing image-capable canonical roles: `explorer` for repository evidence, `worker` or
`worker-complex` for implementation, `validator` for deterministic checks, `design-partner`
for product-flow exploration, and `ux-critic` only for an explicitly authorized runtime
audit. Workers remain leaves, while validator and UX-critic boundaries continue to govern
their visual checks.

The normal `./scripts/check` / `uv run --locked ./scripts/check` path is deterministic,
credential-free, and never invokes a provider. An optional paid OpenAI integration
canary is deliberately separate and local-only; it is available but not run by
CI/default checks. It refuses without both explicit opt-in and acknowledgement,
refuses whenever `CI` is set, requires the existing `pi-openai` launcher, and bounds
its temporary workspace, runtime, output, and child count. The deterministic stalled
`debugger`/`validator` coverage uses a local fake launcher to exercise the harness-owned
wall-clock and cleanup boundary; it does not certify upstream Pi child scheduling or
cancellation. Run it only when you accept OpenAI usage:

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
6. Review the generated model-routing and control-plane diff; operator-owned permission,
   auth, MCP, and theme files are never generated or claimed.

## Adding another harness

Create an adapter under `adapters/<harness>/` that consumes only `policy/`, `roles/`, and `profiles/`. Harness-specific permissions, prompt frontmatter, config paths, and installation mechanics belong in the adapter, not in role contracts.

Currently supported: OpenCode (`adapters/opencode/`), Codex (`adapters/codex/`),
Claude Code (`adapters/claude-code/`), and Pi (`adapters/pi/`).

## Security

Do not commit credentials, environment files, session data, provider tokens, or complete runtime configurations. Profile files contain model IDs only. Installers must merge into local configs rather than copying secrets into this repository. `scripts/check-runtime` is read-only and reports only the known model, effort, instruction, and managed-agent fields.
