# Agent Orchestration

Harness-agnostic source of truth for agent roles, delegation boundaries, validation/review gates, model routing, and harness adapters.

The repository separates stable orchestration semantics from replaceable executors:

```text
policy + role contracts + logical model profiles
                    ↓
             harness adapter
                    ↓
              OpenCode / Codex / future harnesses
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

Backups are written under:

```text
~/.local/state/agent-orchestration/backups/
```

## Codex adapter

The Codex adapter consumes the same canonical policy and the `openai` profile. It renders the ten role contracts as standalone Codex agent TOML files and renders the policy and profile addendum into `AGENTS.md`:

```bash
./scripts/render
./scripts/check
```

The adapter removes the `openai/` provider prefix from model identifiers, maps the profile `variant` to Codex `model_reasoning_effort` (`max` becomes Codex's `xhigh`), and maps canonical `edit = deny` to `read-only` while writable roles use `workspace-write`. It does not write to `~/.codex`; it only generates repository snapshots. Copy or symlink `generated/codex/AGENTS.md` and `generated/codex/agents/*.toml` into the Codex locations you choose. There is no installer, deployment manager, backup, adoption, or rollback logic.

## Generated snapshots

`generated/opencode/` is committed intentionally. A policy change should show both:

1. the harness-agnostic semantic change;
2. its exact OpenCode output.

CI rerenders snapshots and fails on drift.

Both `generated/opencode/` and `generated/codex/` are committed snapshots. A policy or profile change must update the corresponding semantic source and its exact harness output in the same change.

## Adding a role

1. Add the role to `policy/routing.toml`.
2. Add `roles/<role>.md` without provider/model identifiers.
3. Map the role in every `profiles/*.toml` file.
4. Run `./scripts/render` and `./scripts/check`.
5. Review the generated permission and model-routing diff.

## Adding another harness

Create an adapter under `adapters/<harness>/` that consumes only `policy/`, `roles/`, and `profiles/`. Harness-specific permissions, prompt frontmatter, config paths, and installation mechanics belong in the adapter, not in role contracts.

## Security

Do not commit credentials, environment files, session data, provider tokens, or complete runtime configurations. Profile files contain model IDs only. Installers must merge into local configs rather than copying secrets into this repository.
