# Agent Orchestration

Harness-agnostic source of truth for agent and subagent definitions, their
capability data, and the model/reasoning-effort routing used to generate
per-harness configuration.

This repository carries no role prompts. A generated bundle contains agent or
subagent definitions, the model and effort values each harness needs to run them,
and, for every harness except DeepSeek Harness, one short orchestration policy for
the harness's global instruction file and the repository's Agent Skills:

```text
policy/routing.toml + policy/orchestration.md + profiles/*.toml + skills/
                  ↓
           harness generator
                  ↓
OpenCode / Codex / Claude Code / Pi / OMP / DeepSeek Harness
```

## Sources of truth

- `policy/routing.toml` — the canonical roles and their capability data
  (`description`, `mode`, `edit`, `bash`). It contains no model identifiers and no
  delegation graph between roles.
- `policy/orchestration.md` — the short orchestration policy for the primary agent
  and the only source of that text. Generators copy it unchanged between the
  `<!-- agent-orchestration:start -->` and `<!-- agent-orchestration:end -->` markers;
  installers merge that managed section into the harness's global instruction file.
- `skills/<name>/` — the Agent Skills packages and the only source of their
  content: a `SKILL.md` plus any supporting files (scripts, references, assets) at
  any depth below it. Generators discover every `skills/<name>/` directory and copy
  each of its files byte-for-byte; installers install each one as a managed file.
  Hidden entries and `__pycache__` directories are ignored. The skill name must be
  lowercase letters, digits, and single hyphens, every other path component must
  start with a letter or digit and use only letters, digits, `.`, `_`, and `-`, every
  file must be UTF-8 text, and no file below the skill's own `SKILL.md` may be named
  `SKILL.md`; generation fails rather than leave a file out.
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
bundle carries definitions and model/effort carriers, never a role prompt. Its one
instruction artifact is the marker-wrapped `policy/orchestration.md`: `CLAUDE.md`
for Claude Code and `AGENTS.md` for OpenCode, Codex, Pi, and OMP. The same five
bundles carry each repository skill unchanged below `skills/<name>/`: its `SKILL.md`
and every supporting file. A bundle manifest lists the skill names under `skills`
and each supporting file, relative to `skills/`, under `skill_files`; the OMP
manifest claims every skill file in `files` instead. The DeepSeek Harness bundle
carries no instruction artifact and no skills.

| Bundle | Contents |
| --- | --- |
| `build/opencode/` | `agents/<role>.md` (description, mode, permissions), `profiles/<profile>/agent-routing.json` (per-role model/variant), `profiles/<profile>/control-plane.json`, `AGENTS.md` policy section, `skills/<name>/`, `manifest.json` |
| `build/codex/` | `agents/<role>.toml` (`model`, `model_reasoning_effort`, `sandbox_mode`), `control-plane.toml`, `AGENTS.md` policy section, `skills/<name>/` |
| `build/claude-code/` | `agents/<role>.md` with the profile model and effort baked into frontmatter, `_shared/control-plane.md` intent note, `CLAUDE.md` policy section, `skills/<name>/`, `manifest.json` |
| `build/pi/{hybrid,openai,deepseek,glm}/` | `agents/<role>.md`, `_shared/control-plane.json`, `pi-<profile>` launcher, `AGENTS.md` policy section, `skills/<name>/`, `manifest.json` |
| `build/omp/{hybrid,openai,deepseek,glm}/` | `agents/<role>.md`, `config.yml` `modelRoles`, `AGENTS.md` policy section (not a manifest `files` claim), `skills/<name>/` (each file a manifest `files` claim), `manifest.json` |
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

The OpenCode, Claude Code, Pi, and OMP installers also keep the orchestration policy
in a managed section of the harness's global instruction file, between the
`<!-- agent-orchestration:start -->` and `<!-- agent-orchestration:end -->` markers.
That file stays operator-owned. A missing file is created with only the managed
section, an existing section is replaced in place, and a file without markers gets
the section appended after one blank line; bytes outside the markers are never
changed. The file is not a managed name: it is never deleted or claimed in a
manifest, and a pre-existing one is merged without `--adopt` and without an OMP
collision. The write appears in `--dry-run` output and follows the backup and
rollback behavior above, so OMP rolls it back in memory and keeps no backup. Two
cases are refused before any file changes: an instruction file that is a symlink,
like every other symlinked destination, and one whose markers are malformed
(anything but none, or exactly one start marker followed by one end marker).

The same four installers install each repository skill as
`<target>/skills/<name>/`, the directory the harness discovers Agent Skills in: its
`SKILL.md` and every supporting file. Unlike the instruction file, each skill file is
an ordinary managed file: the manifest claims it, a reinstall replaces it with the
repository bytes, a skill or supporting file a later version drops or renames is
deleted, and it follows the collision, `--adopt`, backup, rollback, and `--dry-run`
behavior above. On a target that already has a manifest
from before skills were managed, a hand-copied skill at a managed name is taken over
without `--adopt`, backed up first when its bytes differ, while OMP refuses it until
you remove the copy.

Only those claimed skill files are ever written or deleted. Other skills in the
same `skills/` directory, and any other file inside a managed skill's directory, are
never touched; a directory a removed skill file leaves empty is removed, from the
file's own directory up to `skills/<name>/`, and a directory that still holds other
files is kept. A `skills` directory or skill directory that is a symlink is refused before
any file changes. If you copied these skills by hand into a directory several
harnesses read, such as `~/.agents/skills`, delete those copies after installing so a
stale duplicate cannot shadow the installed one.

### OpenCode

```bash
./scripts/install-opencode --dry-run
./scripts/install-opencode
```

Merges each profile's `agent-routing.json` and `control-plane.json` into an
existing `<target>/profiles/<profile>/opencode.json` (default
`~/.config/opencode`), preserving unrelated configuration, copies
`agents/<role>.md` and every `skills/<name>/` file, and upserts the policy section into
`<target>/AGENTS.md`. On a target with no profile config it writes only
`agents/<role>.md`, the skills, the `AGENTS.md` policy section, and the manifest, so
the `check-runtime` step below then fails
with `OpenCode runtime config is missing` until that config exists. It also removes
the legacy instruction files an earlier version registered.

Compare an effective configuration to the selected profile without changing it:

```bash
uv run --locked ./scripts/check-runtime --profile openai --target ~/.config/opencode
```

### Claude Code

```bash
./scripts/install-claude-code --dry-run
./scripts/install-claude-code
```

Copies `agents/<role>.md`, every `skills/<name>/` file, and the
`_shared/control-plane.md` note into `<target>/` (default `~/.claude`) and upserts
the policy section into `<target>/CLAUDE.md`. A
managed section an earlier version of this installer wrote there is replaced in
place, preserving operator-authored content outside the managed section.

### Pi

```bash
./scripts/install-pi --profile hybrid --dry-run
./scripts/install-pi --profile hybrid
```

The four profiles are `hybrid` (default), `openai`, `deepseek`, and `glm`. The
default target is `~/.pi/agent` for `hybrid` and `~/.pi/profiles/<profile>` for the
others; `--target` selects an isolated fixture and `--bin-dir` overrides the
launcher directory (default `~/.local/bin`). The bundle manifest records every
managed file, and the installer deletes files a previous manifest claimed. Skills
are installed below `skills/<name>/` in the target of each profile. The
policy section is upserted into `AGENTS.md` in the target, the directory the
launcher exports as `PI_CODING_AGENT_DIR`, and is not a manifest claim. The
manifest's `format_version: 1` names the internal orchestration bundle schema, not a Pi host
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

Installs `config.yml`, `agents/<role>.md`, and every `skills/<name>/` file into
`~/.omp/profiles/<profile>/agent` (override with `--target`) and upserts the policy
section into `AGENTS.md` in the same directory. It has no adoption or
overwrite mode: a collision at a managed name, including an existing skill file with
the same name, is refused. An `APPEND_SYSTEM.md` at
that retired managed name is removed on every install, including a first install
where no prior manifest claims it, and OMP keeps no on-disk backups. Start OMP with
the matching `omp --profile <profile>`.

### DeepSeek Harness

```bash
./scripts/install-dsh --dry-run
./scripts/install-dsh
```

Manages `cordis.patch.yml`, `.agent-orchestration/`, and the manifest under
`$DSH_HOME` (default `~/.dsh`). Neither `AGENTS.md` nor any skill is generated or
installed; as legacy
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
[ -e ~/.codex/AGENTS.md ] || cp "$tmp_root/codex/AGENTS.md" ~/.codex/
mkdir -p ~/.codex/skills
cp -R "$tmp_root/codex/skills/." ~/.codex/skills/
```

The `AGENTS.md` line copies the generated policy section only when
`~/.codex/AGENTS.md` does not exist yet. If you already have one, paste the
generated section (the two marker lines and everything between them) into it
yourself, replacing any earlier section between the same markers. The last line
copies each skill directory, `SKILL.md` and supporting files, into
`~/.codex/skills/`, overwriting files of the same name and leaving every other skill
there alone.

**Manual cleanup when upgrading from an earlier version.** Because no installer
manages Codex, nothing removes the artifacts an earlier version installed. Delete
the previously installed policy text from `~/.codex/AGENTS.md` (remove the file too
if it held only that text) and delete the old role TOML files under
`~/.codex/agents/` before copying the new bundle. A skill this repository later
drops or renames likewise stays in `~/.codex/skills/` until you delete its directory,
and so does a supporting file a skill no longer carries.
Nothing in this repository rewrites those files for you.

## Repository layout

- `harnesses/<harness>/generate.py` — renders one harness bundle from `policy/` and
  `profiles/`.
- `harnesses/<harness>/install.py` — optional installer for that bundle.
- `harnesses/common.py` — profile contract validation shared by the generators and
  the managed policy-section and skill helpers shared by the generators and
  installers, and `harnesses/validate.py` — the source-validation entrypoint run by
  `scripts/check`.
- `scripts/` — `generate`, `check`, `check-runtime`, and the per-harness installers.
- `skills/<name>/` — the Agent Skills packages this repository distributes.
  `planned-change-report` and `completed-change-report` render a visual HTML
  explanation of a change before and after it is made; a harness may invoke them
  itself or the user may request them. `promote-changes-to-prod` ships a reviewed
  pull request through `develop` and `master` to a Railway deployment and runs only
  when the user asks for it. `pr-review-map` builds an interactive HTML review map
  for one large pull request or a stack of dependent ones: a per-PR reading graph
  of the changed files and their real dependencies with a side-by-side diff viewer
  and line-anchored review notes that copy as Markdown for an agent, plus
  architecture, rules, risks, and verification; it carries its viewer
  template, Python scripts, and subagent prompts as supporting files and is covered
  by `tests/test_pr_review_map.py`. Every generator except DeepSeek Harness
  copies them into its bundle, the OpenCode, Claude Code, Pi, and OMP installers
  install them into the harness's skills directory, and Codex takes a manual copy.
- `evaluations/` — versioned evaluation configuration validated by `validate.py`.

## Security

Do not commit credentials, environment files, session data, provider tokens, or
complete runtime configurations. Profile files contain model identifiers, effort values,
and capability flags, never credentials. Installers merge into local configuration
rather than copying secrets into this repository, and `scripts/check-runtime` is
read-only and reports only known model, effort, instruction, and managed-agent fields.
