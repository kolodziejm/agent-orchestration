# Agent Orchestration

Harness-agnostic source of truth for agent roles, delegation boundaries, validation/review gates, model routing, and harness adapters.

The repository separates stable orchestration semantics from replaceable executors:

```text
policy + role contracts + logical model profiles
                    ↓
             harness adapter
                    ↓
       OpenCode / Codex / Claude Code / future harnesses
```

## Source of truth

- `policy/orchestration.md` — human-readable orchestration invariants and gates.
- `policy/routing.toml` — machine-readable roles, permissions, and delegation graph.
- `roles/*.md` — provider- and harness-agnostic role contracts.
- `profiles/*.toml` — versioned concrete model/effort mapping for an execution profile,
  including the separate `[control_plane]` intent for the primary model, small model,
  and built-in `build`/`plan` mappings.
- `profiles/*.md` — profile-specific capability addenda.

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
source-changing worker output still requires an independent validator; a direct low-risk
primary change may use targeted self-checks. `worker` is the routine executor and
`worker-complex` is reserved for sufficiently specified changes whose implementation
requires unusually difficult reasoning. A stronger worker must not compensate for unclear
product intent.

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

The project requires Python 3.11 or newer and pins PyYAML 6.0.2 in `pyproject.toml` and
`uv.lock`. The scripts also work when invoked directly with a 3.11+ `python3`; on macOS
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

Unlike OpenCode, a Claude Code subagent file has no separate profile-routing layer: the active profile's `model` and `effort` are baked directly into each agent's frontmatter at render time. The renderer also emits `_shared/control-plane.md`, which records the profile intent and truthfully states that Claude Code cannot install the primary model, small model, or built-in `build`/`plan` mappings; those require manual session configuration. The `harness` field controls which renderer picks up a profile: the OpenCode renderer selects profiles with `harness = "opencode"`, the default when the field is absent; the Claude Code renderer selects the single profile declaring `harness = "claude-code"` (currently `profiles/claude.toml`); the Codex renderer selects by explicit `--profile` and does not read `harness`, so the `openai` profile is rendered by both OpenCode and Codex.

### Claude Code permission degradation

Claude Code has no per-subagent equivalent of OpenCode's `bash = "ask"` permission; prompts are configured at the session level, not per agent file. `Bash` is therefore granted to every rendered agent, including read-only roles, since they still need it for investigation. If a role declares `bash = "deny"`, the renderer fails before writing because Claude Code cannot preserve that prohibition. Claude Code uses a flat subagent topology: the orchestrator performs the logical policy's nested delegation, invokes `explorer` directly when planner or reviewer evidence is needed, and includes that evidence in the handoff. Rendered subagent files contain no `Agent(explorer)` or `Agent(spec-writer)` entries; all delegated targets are omitted from their frontmatter. The native-vision Claude profile therefore needs no separate `vision-*` delegation.

Subagents rendered from role files start without parent history, which satisfies the policy's no-history default. `subagent_type: "fork"` (full-history) is allowed only as the documented exception, with the reason stated in the handoff. The `model` parameter of the `Agent` tool must never be passed; model and effort are baked into each role's frontmatter by the active profile. Built-in harness agents (e.g. `general-purpose`, `Explore`, `Plan`, `claude`) must not be used while a matching role exists; they are allowed only when no role covers the work, with the reason stated in the handoff.

The local `.agent-orchestration.manifest.json` under the target directory tracks managed roles,
the optional workflow, and the non-installable control-plane note the same way as the
OpenCode adapter, so obsolete generated agents and artifacts are removed without deleting
unrelated agents or CLAUDE.md content.

## Generated snapshots

`generated/opencode/`, `generated/codex/`, and `generated/claude-code/` are committed snapshots, intentionally. They include the separately packaged optional workflow and the harness-specific control-plane artifact. A policy or profile change must show both:

1. the harness-agnostic semantic change;
2. its exact per-harness output.

CI rerenders snapshots and fails on drift.

## Adding a role

1. Add the role to `policy/routing.toml`.
2. Add `roles/<role>.md` without provider/model identifiers.
3. Map the role in every versioned `profiles/*.toml` file.
4. Keep each profile's `[control_plane]` and `capabilities.supported_variants` valid.
5. Run `uv run --locked ./scripts/render` and `uv run --locked ./scripts/check`.
6. Review the generated permission, model-routing, and control-plane diff.

## Adding another harness

Create an adapter under `adapters/<harness>/` that consumes only `policy/`, `roles/`, and `profiles/`. Harness-specific permissions, prompt frontmatter, config paths, and installation mechanics belong in the adapter, not in role contracts.

Currently supported: OpenCode (`adapters/opencode/`), Codex (`adapters/codex/`), and Claude Code (`adapters/claude-code/`).

## Security

Do not commit credentials, environment files, session data, provider tokens, or complete runtime configurations. Profile files contain model IDs only. Installers must merge into local configs rather than copying secrets into this repository. `scripts/check-runtime` is read-only and reports only the known model, effort, instruction, and managed-agent fields.
