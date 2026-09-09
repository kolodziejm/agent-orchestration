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

Requires Python 3.11 or newer (`python3` on `PATH`).

Render committed snapshots:

```bash
./scripts/render
```

Run contract tests and ensure snapshots are current:

```bash
python3 -m pip install --requirement requirements-dev.txt
./scripts/check
```

Preview installation against the active OpenCode configuration:

```bash
./scripts/install-opencode --dry-run
```

On a first installation, existing managed role files, instruction files, or
managed agent entries are reported as collisions and no changes are made. If
those names are intentionally being taken over, rerun with `--adopt` (the
dry-run flag can be combined with it to inspect the takeover).

Install, back up changed files, and validate every configured profile with `opencode debug config`:

```bash
./scripts/install-opencode
```

The installer merges generated agent routing into existing profile `opencode.json` files. It preserves unrelated provider, plugin, skill, MCP, compaction, and model-limit configuration. On validation failure it restores the original files.

The local `.agent-orchestration.manifest.json` records exactly which roles and profiles are managed. This allows later policy versions to remove obsolete generated agents without deleting unrelated user-defined agents or instructions.

Backups are written under unique, namespaced directories per adapter:

```text
~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/opencode/
~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/claude-code/
```

## Codex adapter

The Codex adapter consumes the same canonical policy and the `openai` profile. It renders the ten role contracts as standalone Codex agent TOML files and renders the policy and profile addendum into `AGENTS.md`:

```bash
./scripts/render
./scripts/check
```

The adapter removes the `openai/` provider prefix from model identifiers, maps the profile `variant` to Codex `model_reasoning_effort` (`max` becomes Codex's `xhigh`), and maps canonical `edit = deny` to `read-only` while writable roles use `workspace-write`. Codex cannot represent canonical `bash = deny`; the renderer fails before writing if that capability is configured, so it never silently grants shell access. It does not write to `~/.codex`; it only generates repository snapshots. Copy or symlink `generated/codex/AGENTS.md` and `generated/codex/agents/*.toml` into the Codex locations you choose. There is no installer, deployment manager, backup, adoption, or rollback logic.

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

The installer copies each rendered `agents/<role>.md` subagent file into `<target>/agents/`, and merges the shared orchestration policy into `<target>/CLAUDE.md` by replacing only the section between the `<!-- agent-orchestration:start -->` / `<!-- agent-orchestration:end -->` markers (or appending it if absent). Content outside the markers is preserved untouched. The default target is `~/.claude`, overridable with `--target`.

Unlike OpenCode, a Claude Code subagent file has no separate profile-routing layer: the active profile's `model` and `effort` are baked directly into each agent's frontmatter at render time. The `harness` field controls which renderer picks up a profile: the OpenCode renderer selects profiles with `harness = "opencode"`, the default when the field is absent; the Claude Code renderer selects the single profile declaring `harness = "claude-code"` (currently `profiles/claude.toml`); the Codex renderer selects by explicit `--profile` and does not read `harness`, so the `openai` profile is rendered by both OpenCode and Codex.

### Claude Code permission degradation

Claude Code has no per-subagent equivalent of OpenCode's `bash = "ask"` permission; prompts are configured at the session level, not per agent file. `Bash` is therefore granted to every rendered agent, including read-only roles, since they still need it for investigation. If a role declares `bash = "deny"`, the renderer fails before writing because Claude Code cannot preserve that prohibition. Claude Code uses a flat subagent topology: the orchestrator performs the logical policy's nested delegation, invokes `explorer` directly when planner or reviewer evidence is needed, and includes that evidence in the handoff. Rendered subagent files contain no `Agent(explorer)` or `Agent(spec-writer)` entries; all delegated targets are omitted from their frontmatter. The native-vision Claude profile therefore needs no separate `vision-*` delegation.

Subagents rendered from role files start without parent history, which satisfies the policy's no-history default. `subagent_type: "fork"` (full-history) is allowed only as the documented exception, with the reason stated in the handoff. The `model` parameter of the `Agent` tool must never be passed; model and effort are baked into each role's frontmatter by the active profile. Built-in harness agents (e.g. `general-purpose`, `Explore`, `Plan`, `claude`) must not be used while a matching role exists; they are allowed only when no role covers the work, with the reason stated in the handoff.

The local `.agent-orchestration.manifest.json` under the target directory tracks managed roles the same way as the OpenCode adapter, so obsolete generated agents are removed without deleting unrelated agents or CLAUDE.md content.

## Generated snapshots

`generated/opencode/`, `generated/codex/`, and `generated/claude-code/` are committed snapshots, intentionally. A policy or profile change must show both:

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
