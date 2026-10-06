# Agent Orchestration

Harness-agnostic source of truth for agent and subagent definitions, their
capability data, and the model/reasoning-effort routing used to generate
per-harness configuration.

This repository carries no role prompts and installs no global instruction file.
A generated bundle contains agent or subagent definitions plus the model and
effort values each harness needs to run them:

```text
policy/routing.toml + profiles/*.toml
                  ↓
           harness generator
                  ↓
OpenCode / Codex / Claude Code / Pi / OMP / DeepSeek Harness
```

## Sources of truth

- `policy/routing.toml` — the canonical roles and their capability data
  (`description`, `mode`, `edit`, `bash`). It contains no model identifiers and no
  delegation graph between roles.
- `profiles/*.toml` — the versioned model and reasoning-effort mapping for one
  execution profile. Each profile declares one `[models.<role>]` entry per role and
  a `[control_plane]` intent for the primary model, the small model, and the
  built-in `build`/`plan` mappings.
- `profiles/*.md` — profile addenda. The `addendum` key names the file and
  `harnesses/validate.py` requires it to exist, but no generator copies it into
  generated output. The addenda are inert, hand-copy sources for an operator's own
  global instructions.
- `schema/*.json` — Draft 2020-12 schemas for routing documents, profiles, and
  evaluations, executed before the semantic checks.
- `harnesses/validate.py` — validates routing, every versioned profile, the profile
  addenda, and the evaluation documents without provider calls.

Model identifiers live only in `profiles/*.toml`; the generators read
`policy/routing.toml` for role capability data and validate each profile before
writing output.

## Generated output

`./scripts/generate` writes every supported harness output into the untracked
`build/` tree (`build/` and `generated/` are ignored). Agent bodies are empty: a
bundle carries definitions and model/effort carriers, never a role prompt or a
global instruction file.

| Bundle | Contents |
| --- | --- |
| `build/opencode/` | `agents/<role>.md` (description, mode, permissions), `profiles/<profile>/agent-routing.json` (per-role model/variant), `profiles/<profile>/control-plane.json`, `manifest.json` |
| `build/codex/` | `agents/<role>.toml` (`model`, `model_reasoning_effort`, `sandbox_mode`), `control-plane.toml` |
| `build/claude-code/` | `agents/<role>.md` with the profile model and effort baked into frontmatter, `_shared/control-plane.md` intent note, `manifest.json` |
| `build/pi/{hybrid,openai,deepseek,glm}/` | `agents/<role>.md`, `_shared/control-plane.json`, `pi-<profile>` launcher, `manifest.json` |
| `build/omp/{hybrid,openai,deepseek,glm}/` | `agents/<role>.md`, `config.yml` `modelRoles`, `manifest.json` |
| `build/dsh/` | `patch/cordis.patch.yml` (one subagent lane per role carrying provider, model, and effort, with a tool filter for restricted roles), `_shared/control-plane.md`, `manifest.json` |

The Pi launcher selects the profile's primary `--model` and `--thinking` and
exports `AGENT_ORCHESTRATION_PROFILE` before starting Pi. Where a harness cannot
install the primary model, small model, or built-in `build`/`plan` mappings, the
bundle records those values as control-plane intent only.

A custom output root is accepted only when it is the repository `build/<harness>`
destination or a directory below the process temporary root; any other destination
is refused before any file is written.

## Generate and check

The project requires Python 3.11 or newer and pins PyYAML 6.0.2 and jsonschema
4.25.1 in `pyproject.toml`, `requirements-dev.txt`, and `uv.lock`.

```bash
./scripts/generate
uv run --locked ./scripts/check
```

`./scripts/check` runs `harnesses/validate.py`, the `tests/` unittest suite, then
generates each OpenCode, Codex, Claude Code, four Pi, four OMP, and DeepSeek
Harness output twice into separate temporary roots and diffs the results. It never
reads or updates a committed snapshot, so nondeterministic generation fails the
check. Where `uv` is unavailable, the documented local fallback is:

```bash
PYTHON=.venv/bin/python ./scripts/check
```

## Installation

Installers merge generated artifacts into a harness configuration, record what they
own in a manifest, delete files a previous manifest claimed, and roll back on
failure. Except for the OMP installer, which rolls back in memory, keeps no backups,
and removes the retired `APPEND_SYSTEM.md` name unconditionally even with no prior
manifest, every installer backs up each changed or removed file under
`~/.local/state/agent-orchestration/backups/<timestamp>-<unique>/<harness>/`.
Operator-owned runtime state — settings, catalogs, auth, MCP configuration, themes,
provider state, sessions, and caches — keeps its bytes, and the installers
never install, select, migrate, or validate framework packages. A first
installation reports existing files at managed names as collisions; every
installer except OMP requires `--adopt` before taking them over, while OMP refuses
the collision.

### OpenCode

```bash
./scripts/install-opencode --dry-run
./scripts/install-opencode
```

Merges each profile's `agent-routing.json` and `control-plane.json` into an
existing `<target>/profiles/<profile>/opencode.json` (default
`~/.config/opencode`), preserving unrelated configuration, and copies
`agents/<role>.md`. On a target with no profile config it writes only
`agents/<role>.md` and the manifest, so the `check-runtime` step below then fails
with `OpenCode runtime config is missing` until that config exists. It also removes
the managed instruction files an earlier version registered.

Compare an effective configuration to the selected profile without changing it:

```bash
uv run --locked ./scripts/check-runtime --profile openai --target ~/.config/opencode
```

### Claude Code

```bash
./scripts/install-claude-code --dry-run
./scripts/install-claude-code
```

Copies `agents/<role>.md` and the `_shared/control-plane.md` note into `<target>/`
(default `~/.claude`). As legacy cleanup, it strips the managed instruction section
an earlier version of this installer wrote into `CLAUDE.md`, preserving
operator-authored content outside the managed section.

### Pi

```bash
./scripts/install-pi --profile hybrid --dry-run
./scripts/install-pi --profile hybrid
```

The four profiles are `hybrid` (default), `openai`, `deepseek`, and `glm`. The
default target is `~/.pi/agent` for `hybrid` and `~/.pi/profiles/<profile>` for the
others; `--target` selects an isolated fixture and `--bin-dir` overrides the
launcher directory (default `~/.local/bin`). The bundle manifest records every
managed file, and the installer deletes files a previous manifest claimed. Its
`format_version: 1` names the internal orchestration bundle schema, not a Pi host
or runtime version. Install each profile, then exit the current Pi process and
start the matching launcher, because profile roots are selected only at process
startup:

```bash
pi-hybrid    # mixed OpenAI + DeepSeek routing at ~/.pi/agent
pi-openai    # OpenAI routing at ~/.pi/profiles/openai
pi-deepseek  # DeepSeek routing at ~/.pi/profiles/deepseek
pi-glm       # Z.AI GLM routing at ~/.pi/profiles/glm
```

### OMP

```bash
./scripts/install-omp --profile hybrid --dry-run
./scripts/install-omp --profile hybrid
```

Installs `config.yml` and `agents/<role>.md` into
`~/.omp/profiles/<profile>/agent` (override with `--target`). It has no adoption or
overwrite mode: a collision at a managed name is refused. An `APPEND_SYSTEM.md` at
that retired managed name is removed on every install, including a first install
where no prior manifest claims it, and OMP keeps no on-disk backups. Start OMP with
the matching `omp --profile <profile>`.

### DeepSeek Harness

```bash
./scripts/install-dsh --dry-run
./scripts/install-dsh
```

Manages `cordis.patch.yml`, `.agent-orchestration/`, and the manifest under
`$DSH_HOME` (default `~/.dsh`). `AGENTS.md` is not generated or installed; as legacy
cleanup, a managed section an earlier version wrote into `AGENTS.md` is stripped
while operator-authored content outside the managed section is preserved.
Generate a Windows bundle with `--shell pwsh`.

### Codex (manual installation)

Codex is generator-only: there is no `scripts/install-codex`, and nothing in this
repository writes to `~/.codex`. Copy the generated files yourself:

```bash
tmp_root="$(mktemp -d)"
python3 harnesses/codex/generate.py --output "$tmp_root/codex" --profile openai
mkdir -p ~/.codex/agents
cp "$tmp_root/codex/agents/"*.toml ~/.codex/agents/
cp "$tmp_root/codex/control-plane.toml" ~/.codex/
```

**Manual cleanup when upgrading from an earlier version.** Because no installer
manages Codex, nothing removes the artifacts an earlier version installed. Delete
the previously installed policy text from `~/.codex/AGENTS.md` (remove the file too
if it held only that text) and delete the old role TOML files under
`~/.codex/agents/` before copying the new bundle. Nothing in this repository
rewrites those files for you.

## Repository layout

- `harnesses/<harness>/generate.py` — renders one harness bundle from `policy/` and
  `profiles/`.
- `harnesses/<harness>/install.py` — optional installer for that bundle.
- `harnesses/common.py` — profile contract validation shared by the generators, and
  `harnesses/validate.py` — the source-validation entrypoint run by `scripts/check`.
- `scripts/` — `generate`, `check`, `check-runtime`, and the per-harness installers.
- `skills/change-report/` — optional portable Agent Skills package, installed
  through a harness's own Agent Skills mechanism rather than by this repository.
- `evaluations/` — versioned evaluation configuration validated by `validate.py`.

## Security

Do not commit credentials, environment files, session data, provider tokens, or
complete runtime configurations. Profile files contain model identifiers, effort values,
and capability flags, never credentials. Installers merge into local configuration
rather than copying secrets into this repository, and `scripts/check-runtime` is
read-only and reports only known model, effort, instruction, and managed-agent fields.
