# Agent Orchestration

Harness-agnostic source of truth for agent roles, delegation boundaries, validation/review gates, model routing, and harness adapters.

The repository separates stable orchestration semantics from replaceable executors:

```text
policy + role contracts + logical model profiles
                    ↓
             harness adapter
                    ↓
      OpenCode / Claude Code / future harnesses
```

## Source of truth

- `policy/orchestration.md` — human-readable orchestration invariants and gates.
- `policy/routing.toml` — machine-readable roles, permissions, and delegation graph.
- `roles/*.md` — provider- and harness-agnostic role contracts.
- `profiles/*.toml` — concrete model/effort mapping for an execution profile.
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

`worker` is the routine executor. `worker-complex` is reserved for sufficiently specified changes whose implementation requires unusually difficult reasoning. A stronger worker must not compensate for unclear product intent.

## OpenCode adapter

Render committed snapshots:

```bash
./scripts/render
```

Run contract tests and ensure snapshots are current:

```bash
./scripts/check
```

Preview installation against the active OpenCode configuration:

```bash
./scripts/install-opencode --dry-run
```

Install, back up changed files, and validate every configured profile with `opencode debug config`:

```bash
./scripts/install-opencode
```

The installer merges generated agent routing into existing profile `opencode.json` files. It preserves unrelated provider, plugin, skill, MCP, compaction, and model-limit configuration. On validation failure it restores the original files.

The local `.agent-orchestration.manifest.json` records exactly which roles and profiles are managed. This allows later policy versions to remove obsolete generated agents without deleting unrelated user-defined agents or instructions.

Backups are written under, namespaced per adapter:

```text
~/.local/state/agent-orchestration/backups/<timestamp>/opencode/
~/.local/state/agent-orchestration/backups/<timestamp>/claude-code/
```

## Claude Code adapter

Render committed snapshots (also renders the OpenCode snapshot):

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

The installer copies each rendered `agents/<role>.md` subagent file into `<target>/agents/`, and merges the shared orchestration policy into `<target>/CLAUDE.md` by replacing only the section between the `<!-- agent-orchestration:start -->` / `<!-- agent-orchestration:end -->` markers (or appending it if absent). Content outside the markers is preserved untouched. The default target is `~/.claude`, overridable with `--target`.

Unlike OpenCode, a Claude Code subagent file has no separate profile-routing layer: the active profile's `model` and `effort` are baked directly into each agent's frontmatter at render time. Only one profile may declare `harness = "claude-code"` (currently `profiles/claude.toml`); the OpenCode renderer ignores it via the same `harness` field (profiles without a `harness` field default to `"opencode"` for backward compatibility).

### Claude Code permission degradation

Claude Code has no per-subagent equivalent of OpenCode's `bash = "ask"` permission; prompts are configured at the session level, not per agent file. `Bash` is therefore granted to every rendered agent, including read-only roles, since they still need it for investigation. Delegation (`delegates` in `policy/routing.toml`) is expressed as `Agent(<target>)` entries in the agent's `tools` frontmatter field. `vision-*` delegates are omitted for profiles that declare `[capabilities] native_vision = true`, since all current Claude models are natively multimodal.

The local `.agent-orchestration.manifest.json` under the target directory tracks managed roles the same way as the OpenCode adapter, so obsolete generated agents are removed without deleting unrelated agents or CLAUDE.md content.

## Generated snapshots

`generated/opencode/` and `generated/claude-code/` are committed intentionally. A policy change should show both:

1. the harness-agnostic semantic change;
2. its exact per-harness output.

CI rerenders snapshots and fails on drift.

## Adding a role

1. Add the role to `policy/routing.toml`.
2. Add `roles/<role>.md` without provider/model identifiers.
3. Map the role in every `profiles/*.toml` file.
4. Run `./scripts/render` and `./scripts/check`.
5. Review the generated permission and model-routing diff.

## Adding another harness

Create an adapter under `adapters/<harness>/` that consumes only `policy/`, `roles/`, and `profiles/`. Harness-specific permissions, prompt frontmatter, config paths, and installation mechanics belong in the adapter, not in role contracts.

Currently supported: OpenCode (`adapters/opencode/`) and Claude Code (`adapters/claude-code/`).

## Security

Do not commit credentials, environment files, session data, provider tokens, or complete runtime configurations. Profile files contain model IDs only. Installers must merge into local configs rather than copying secrets into this repository.
