# Agent Orchestration

Harness-agnostic source of truth for agent roles, delegation boundaries, validation/review gates, model routing, and harness configuration generation.

The repository separates stable orchestration semantics from replaceable executors:

```text
policy + role contracts + logical model profiles
                    ↓
            harness generator
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
- `harnesses/validate.py` executes both Draft 2020-12 schemas before semantic
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
a logical stopping condition and a separate enforceable whole-lane execution cap; every
potentially blocking tool call also has its own enforceable per-call timeout. Potentially
non-brief work runs in the background when supported so the primary remains responsive.
Delegated source-changing worker output still requires an independent validator. Workers
may author tests in scope but must not execute verification; `validator` owns predefined
deterministic acceptance, including browser/device checks. Both worker tiers are leaves; the
primary routes visual work directly to existing image-capable roles. `worker` is the routine executor and
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

If PR creation or remote access is unavailable or unauthorized, prepare an equivalently reviewable local branch, commit, or patch and label it as a fallback—never claim a remote action. Parallel implementation is limited to isolated, non-overlapping branches/worktrees, while promotion remains ordered. A user-approved named stack/ordered-unit plan authorizes uninterrupted execution of its already bounded units in the named order without routine approval waits between them. After every PR or fallback unit, present a bird's-eye checkpoint automatically as a non-blocking progress report covering purpose/concern, before/after behavior, decisions, separate human-authored/generated/lockfile diff stats, affected areas/files, risks, validation evidence, residual work, and the next proposed unit. Checkpoints do not authorize merge, promotion, or remediation; existing review, finding/remediation, and merge authorization gates remain in force. Ask again only for a material scope or acceptance change, a new risk or product decision, or a failed/BLOCKED validation that requires a decision. A detected or projected absolute-ceiling breach requires stopping and re-decomposing/splitting; it is not waivable and cannot be pre-authorized. This contract does not add GitHub-provider automation, credentials, or hosting assumptions, and does not automatically create branches, commits, or pull requests.

## OpenCode harness

Requires Python 3.11 or newer (`python3` on `PATH`).

Generate every supported harness configuration into the untracked `build/` tree:

```bash
./scripts/generate
```

`./scripts/generate` accepts an optional first positional output root (default
`build/`). A custom root must satisfy each generator's fail-closed output-path
policy: the repository's `build/` destination or a directory below the process
temporary root.

Run contract tests and verify every generated harness/profile output is
deterministic in the reproducible uv environment:

```bash
uv run --locked ./scripts/check
```

`./scripts/check` rebuilds each OpenCode, Codex, Claude Code, and four Pi
profile output twice in separate temporary roots and diffs the corresponding
results. It never reads or updates a committed snapshot.

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

Backups are written under unique, namespaced directories per harness:

```text
~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/opencode/
~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/claude-code/
```

## Codex harness

Codex is generator-only: there is no Codex installer, no `scripts/install-codex`, and
no write to `~/.codex`. The Codex generator consumes the same canonical policy and
the `openai` profile, and generates the nine role contracts as standalone Codex
agent TOML files, the selected control-plane intent as `control-plane.toml`, and the
policy and profile addendum into `AGENTS.md`:

```bash
./scripts/generate
```

That writes every harness output, including the Codex output at the default
untracked `build/codex/`. To generate only Codex output, invoke its generator
directly:

```bash
python3 harnesses/codex/generate.py --output build/codex --profile openai
```

To inspect the output outside the repository, generate into a safe temporary
output root and copy the files you want:

```bash
tmp_root="$(mktemp -d)"
python3 harnesses/codex/generate.py --output "$tmp_root/codex" --profile openai
mkdir -p /desired/codex/location/agents
cp "$tmp_root/codex/AGENTS.md" "$tmp_root/codex/control-plane.toml" /desired/codex/location/
cp "$tmp_root/codex/agents/"*.toml /desired/codex/location/agents/
```

A custom output path is accepted only when it stays below the process temporary
root, so an accidental repository or user-configuration destination fails closed
before any file is written.

The generator removes the `openai/` provider prefix from model identifiers, maps the profile `variant` to Codex `model_reasoning_effort` (`max` becomes Codex's `xhigh`), and maps canonical `edit = deny` to `read-only` while writable roles use `workspace-write`. Codex cannot represent canonical `bash = deny`; the generator fails before writing if that capability is configured, so it never silently grants shell access. The optional feature workflow is copied separately under `build/codex/workflows/`. Copy `build/codex/AGENTS.md`, `build/codex/control-plane.toml`, and `build/codex/agents/*.toml` into the Codex locations you choose. There is no installer, deployment manager, backup, adoption, or rollback logic.

## Claude Code harness

Generate the Claude Code harness configuration (this also generates the OpenCode and Codex output) into `build/`:

```bash
./scripts/generate
```

Run contract tests and verify generated-output determinism:

```bash
uv run --locked ./scripts/check
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

The installer copies each generated `agents/<role>.md` subagent file into `<target>/agents/`,
copies the optional workflow under `<target>/workflows/`, and merges the shared
orchestration policy into `<target>/CLAUDE.md` by replacing only the section between the
`<!-- agent-orchestration:start -->` / `<!-- agent-orchestration:end -->` markers (or
appending it if absent). Content outside the markers is preserved untouched. The default
target is `~/.claude`, overridable with `--target`.

Unlike OpenCode, a Claude Code subagent file has no separate profile-routing layer: the active profile's `model` and `effort` are baked directly into each agent's frontmatter at generation time. The generator also emits `_shared/control-plane.md`, which records the profile intent and truthfully states that Claude Code cannot install the primary model, small model, or built-in `build`/`plan` mappings; those require manual session configuration. The `harness` field controls which harness generator picks up a profile: OpenCode selects `harness = "opencode"` (the backward-compatible default), Claude Code selects the single `harness = "claude-code"` profile, and Pi-only profiles declare `harness = "pi"`. Codex accepts only explicitly selected OpenCode/Codex-compatible profiles. Every profile-scanning generator recognizes and intentionally skips known profiles for other harnesses while still rejecting unknown harness values.

### Claude Code permission degradation

Claude Code has no per-subagent equivalent of OpenCode's `bash = "ask"` permission; prompts are configured at the session level, not per agent file. `Bash` is therefore granted to every generated agent, including read-only roles, since they still need it for investigation. If a role declares `bash = "deny"`, the generator fails before writing because Claude Code cannot preserve that prohibition. Claude Code uses a flat subagent topology: the orchestrator performs the logical policy's nested delegation, invokes `explorer` directly when planner or reviewer evidence is needed, and includes that evidence in the handoff. Generated subagent files contain no `Agent(explorer)` entries; all delegated targets are omitted from their frontmatter. The native-vision Claude profile inspects images directly.

Generated subagents start without parent history, which satisfies the policy's no-history default. `subagent_type: "fork"` (full-history) is allowed only as the documented exception, with the reason stated in the handoff. The `model` parameter of the `Agent` tool must never be passed; model and effort are baked into each role's frontmatter by the active profile. Built-in harness agents (e.g. `general-purpose`, `Explore`, `Plan`, `claude`) must not be used while a matching role exists; they are allowed only when no role covers the work, with the reason stated in the handoff.

The local `.agent-orchestration.manifest.json` under the target directory tracks managed roles,
the optional workflow, and the non-installable control-plane note the same way as the
OpenCode harness, so obsolete generated agents and artifacts are removed without deleting
unrelated agents or CLAUDE.md content.

## Generated output

`build/opencode/`, `build/codex/`, `build/claude-code/`, and the isolated
`build/pi/hybrid/`, `build/pi/openai/`, `build/pi/deepseek/`, and `build/pi/glm/` bundles are
untracked generator output; `build/` and `generated/` are ignored so no generated
harness configuration is committed. They include the separately
packaged optional workflow and the harness-specific control-plane artifact. A policy or
profile change shows the harness-agnostic semantic change in review, while CI proves
that every harness output is reproducible from it.

`./scripts/generate` writes every supported harness/profile output under the default
untracked `build/` tree. `./scripts/check` generates each output twice into separate
temporary roots and diffs the corresponding results, so CI fails on nondeterministic
generation without relying on committed snapshots.

## Pi harness

The Pi generator produces a default hybrid bundle plus OpenAI, DeepSeek, and Z.AI GLM
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
allowlist, and every profile bundle generates no managed extension package. The
`git-read.ts` explorer runtime extension and its `extensions/agent-orchestration/package.json`,
the provider status extensions, and the former `primary-policy` extension are retired; files
left by a previous install are migration-only stale artifacts that the installer removes
rather than loads, and the manifest's `managed_extensions` is empty. The generated Pi shared
policy requires each Pi Agent call to state its logical stopping condition and use an
enforceable whole-lane execution cap. Set a task-specific `max_turns` unless an equivalent
enforceable whole-lane runtime deadline bounds total lane execution and cancels the lane at
expiry; only then may `max_turns` be omitted. Source-changing worker calls default to
`run_in_background: true`. Potentially blocking child tool calls independently require a
native or OS/harness-enforced per-call timeout: `max_turns` cannot bound one tool call, and
a per-call timeout cannot bound the whole lane. When timeout and termination cannot be
enforced, the operation is not delegated and stays bounded in the primary or returns
`BLOCKED`. Pi's manual UI stop is recovery after a breach, not a pre-launch safety guarantee.

The native CLI boundary replaces the former extension hook. Each profile launcher starts Pi
with its profile's primary `--model` and `--thinking`, then appends the installed
`agent-orchestration/_shared/orchestration-core.md` through Pi's public
`--append-system-prompt` flag. The launcher fails closed before `exec` when that policy file
is missing or unreadable. Because the policy is supplied on the command line, the bundle
does not hook `before_agent_start`, does not load a managed policy extension, and does not
manage or replace user `AGENTS.md`, `APPEND_SYSTEM.md`, or project context files. Each
launcher also exports `AGENT_ORCHESTRATION_PROFILE` (`hybrid`, `openai`, `deepseek`, or
`glm`) so optional native Pi packages can select profile-specific behavior without copying
runtime implementation into this repository.

Optional Pi runtime integrations live in the separate
[`kolodziejm/harness-extensions`](https://github.com/kolodziejm/harness-extensions)
repository. Install that repository with Pi's native package manager in each profile where
the watchdog or status UI is wanted. The package maps `hybrid`/`deepseek` to the DeepSeek
price period, `openai` to Codex weekly pace, and `glm` to the GLM price period.

The Pi subagent watchdog covers top-level agents and enforces three independent defaults:

- startup: 120 seconds before the first meaningful child-session state change;
- idle: 5 minutes since the last meaningful state change;
- total runtime: 30 minutes regardless of continued progress.

On expiry it requests targeted cancellation through `subagents:rpc:stop`. It emits terminal
`BLOCKED` only after cancellation is acknowledged and includes the last meaningful progress
time and kind. Failed or missing acknowledgement remains non-terminal, produces one visible
watchdog error, and retries cancellation every 30 seconds until the child becomes terminal or
the host shuts down. This watchdog-owned safety retry is not child-lane continuation and never
authorizes duplicate work. Nested agents and workflow-owned agents are not covered
because `pi-subagents` 0.19.0 intentionally hides their lifecycle records and rejects external
stop requests. The underlying native record remains `stopped`; `BLOCKED` is
the companion package's terminal evidence contract.

This installer deliberately does not mutate package settings or own that runtime package.

```bash
PI_CODING_AGENT_DIR="$HOME/.pi/agent" pi install git:github.com/kolodziejm/harness-extensions
PI_CODING_AGENT_DIR="$HOME/.pi/profiles/openai" pi install git:github.com/kolodziejm/harness-extensions
PI_CODING_AGENT_DIR="$HOME/.pi/profiles/deepseek" pi install git:github.com/kolodziejm/harness-extensions
PI_CODING_AGENT_DIR="$HOME/.pi/profiles/glm" pi install git:github.com/kolodziejm/harness-extensions
```

Generate and check the output through the standard entrypoints:

```bash
./scripts/generate
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

### Pi explorer shell degradation

Every generated hybrid, OpenAI, DeepSeek, and GLM Pi profile manages no extension package:
there is no `extensions/agent-orchestration` directory, no extension `package.json`, and the
manifest's `managed_extensions` is empty. The former manifest-owned
`extensions/agent-orchestration/git-read.ts` explorer runtime extension is retired; any file
left by a previous install is migration-only stale that the installer deletes. Explorer now
receives Pi's built-in `bash` tool for repository evidence instead of the removed extension,
and every other role excludes `git_read`.

Canonical policy sets `bash = "ask"` for explorer. Pi cannot forward an `ask` decision from a
headless child to the parent UI, so the Pi integration explicitly degrades that ask to an allowed
shell. This is a documented weakening, not a read-only guarantee: `bash` is unrestricted for
explorer and there is no hard read-only sandbox. Explorer frontmatter declares
`acceptanceRole: read-only`, which is prompt/acceptance metadata for acceptance inference only;
it does not grant or revoke tools, does not constrain `bash`, and is not runtime enforcement.
The installer validates the explorer tool allowlist and acceptance metadata during adoption,
idempotent updates, stale managed-file cleanup, backup, and rollback; it does not validate the
shell commands a child runs.

Pi's native child permissions deliberately reject `permissions.bash`; if `bash` is in
an agent's tool list, the Pi host passes it through. The Pi integration degrades canonical
shell-`ask` roles explicitly: validator, debugger, and explorer receive `bash`, while reviewer
omits it and keeps a stricter no-shell ceiling. Command-level
permission configuration remains operator-owned and is not copied or claimed by this project.
Pi agent files configure child roles and each profile launcher selects the primary model.
Planner and reviewer retain the `subagent` tool, while canonical policy restricts each to the
exact child target `explorer`; all other canonical roles lack `subagent`, so they are leaves at
the Pi tool boundary. Under runtimes without a public framework-neutral child-target
enforcement API, that exact restriction is a policy-level boundary represented in role
contracts and generated tool lists, not runtime enforcement. This bundle does not claim
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
5. Run `uv run --locked ./scripts/generate` and `uv run --locked ./scripts/check`.
6. Review the generated model-routing and control-plane output; operator-owned permission,
   auth, MCP, and theme files are never generated or claimed.

## Adding another harness

Create a harness generator and optional installer under `harnesses/<harness>/` that consume only `policy/`, `roles/`, and `profiles/`. Harness-specific permissions, prompt frontmatter, config paths, and installation mechanics belong in the harness generator and installer, not in role contracts.

Currently supported: OpenCode (`harnesses/opencode/`), Codex (`harnesses/codex/`),
Claude Code (`harnesses/claude-code/`), and Pi (`harnesses/pi/`).

## Security

Do not commit credentials, environment files, session data, provider tokens, or complete runtime configurations. Profile files contain model IDs only. Installers must merge into local configs rather than copying secrets into this repository. `scripts/check-runtime` is read-only and reports only the known model, effort, instruction, and managed-agent fields.

## Change reports

`change-report` is an optional, prompt-only, harness-agnostic Agent Skills package for one
standalone HTML evidence document per initiative. It has exactly two requested modes: `PRE`
before implementation and `POST` after implementation and validation, before human review or
merge. The model may suggest either mode, but a report file is created or updated only after an
explicit current-user request. The document distinguishes repository evidence, proposals,
estimates, actuals, agent review, human review, and unverified or not-run status. It never creates
a PR or authorizes a merge. If POST has no genuine PRE, it says so rather than fabricating one.

Portable skills live once in the repository at `skills/<name>/` and are installed by the current
harness's native Agent Skills mechanism. For this skill, tell the harness:

> Install the `change-report` skill globally from the `kolodziejm/agent-orchestration` repository.

The harness chooses its native installation mechanism; this repository does not prescribe a
package manager or harness-specific destination. When invoked, the skill writes by default to
`change-reports/<change-id>.html` under the active project so the report is visible in editors
such as VS Code. Report prose follows the language of the user's current conversation while
preserving code, paths, commands, API names, and identifiers. The skill never edits `.gitignore`,
stages, or commits the report automatically.

The skill is model-rendered from its prompt and needs no additional repository runtime or
skill-specific tests. A harness without Agent Skills support must report that this skill is
unsupported rather than mutating unrelated configuration. This repository does not provide a
custom skill installer or manage harness settings. Harness generators and installers remain a
separate concern and are not replaced or reclassified by the portable-skill rule.
