# Changelog

All notable changes to the agent and subagent definitions, capability data, and model/effort routing are documented here.

## Unreleased
- Fix three weaknesses of the `pr-review-map` reading order. Core files with no non-test edge to another core file of the same PR (edges to tests, docs/config/i18n, and other PRs do not count), such as a collapsed import-change group, now read after the connected files and before docs/config/i18n in both modes, ordered by layer then path, instead of opening the "from the entry point" order; `build_graph.py` and the viewer apply the same rule, and the viewer reverses only the connected part. Tests are now also recognised by their language's name marker, not only by a test directory or a `.test.`/`.spec.` segment: a `-test`/`_test`/`-spec`/`_spec`/`-e2e`/`_e2e` suffix in JS/TS, Vue, and Svelte, `_spec.rb`, `_test` in Go, Python, Ruby, and Elixir, and `test_*.rb` next to `test_*.py` (`test-utils.ts`, `contest.ts`, `api-spec.yaml`, `pod_spec.go`, `openapi_spec.py`, and `build_spec.rs` stay non-tests; a JS feature file such as `ab-test.tsx` needs an overlay `layer`), and matched to their subject with the marker removed (`mobile-state-panel-test.tsx` → `mobile-state-panel.tsx`); a test anchors only to a core file, its name-matched subject first. The viewer numbers the steps on the whole PR, tests included, so the test filter hides tests without renumbering the others; the side list and graph keep the numbers with gaps, and the path overlay and prev/next skip hidden steps.
- Add review notes to the `pr-review-map` diff viewer. Click a line number in the diff, Shift+click another to extend the range on the same side of the same file (clicks in the code are left to normal text selection), or use the keyboard (Tab to a line number, arrows, Enter, Shift+Enter or Shift+arrow, Esc); "Add note" opens an inline editor. Saved notes show as markers on their lines and in a notes panel where each can be edited, deleted, or opened at its line, and persist in localStorage under the report's storage key (the page keeps working, with a warning, where storage is unavailable). "Clear all notes" asks for an inline confirmation, and "Copy notes" copies every note as Markdown for an agent: a header naming the report and PRs and explaining the sides, one section per PR (name, repository, title, and the base and tip commits when known), then per note one `path:line` or `path:start-end` reference from the repository root with its side ("new (PR)" or "old (base)"), the referenced code in a fenced block with a language hint, and the note, falling back to `execCommand` and then a select-to-copy text box where the Clipboard API is blocked. `build_graph.py` now records each PR's `repo` label (`--repo`, else `owner/name` from the `origin` remote URL path, never its host, credentials, query, or fragment, else the directory name) and the short `base` and `tip` SHAs its diff compares (the merge base for `A...B`; left out when git cannot resolve them), and `assemble.py` passes them and the report title to the viewer.
- Add the `pr-review-map` skill. It turns one large pull request or a stack of dependent pull requests, possibly across repositories, into one interactive HTML page: per-PR tabs with a graph of the changed files and their real dependencies (resolved imports, DI and routing bindings, test → subject, config readers, HTTP calls, dashed nodes for files of earlier PRs), a numbered reading order from the entry point or from the dependencies, a detail panel with per-file notes, read marks, and a side-by-side or unified diff of the selected file, around authored sections on architecture, request flow, data shapes, business rules, per-PR purpose, ranked risks, and verification. The package carries the viewer template with Polish and English UI strings, `build_graph.py` (graph scaffold from git with an authored overlay), `gen_diffs.py`, `assemble.py`, and `validate.py` (node compile check, JSON, markup balance, CDN allowlist), plus subagent prompts and the data schema; it publishes through the Claude Code Artifact tool or writes a local HTML file.
- Distribute skill packages, not only `SKILL.md`. A skill directory may now carry supporting files (scripts, references, assets) at any depth; every generator except DeepSeek Harness copies each of them byte-for-byte below `skills/<name>/`, and the OpenCode, Claude Code, Pi, and OMP installers install them as managed files with the same manifest claims, collision and `--adopt` rules, backups, rollback, and `--dry-run` output as `SKILL.md`. Bundle manifests list the supporting files, relative to `skills/`, under a new optional `skill_files` key (OMP claims them in `files`); a manifest without the key claims only each skill's `SKILL.md`, so existing installations upgrade in place. A supporting file a later version drops is deleted, along with each directory that leaves empty up to `skills/<name>/`. Generation fails on a symlink, a non-UTF-8 file, an unsafe path component, or a nested `SKILL.md` inside a skill; hidden entries and `__pycache__` directories are ignored.
- Add the `promote-changes-to-prod` skill. It takes an already reviewed pull request to production: merges it into `develop`, waits for CI, promotes `develop` to `master` through a pull request, waits for the Railway deployment of that commit to succeed, then merges `master` back into `develop`. It runs only when the user asks for it and stops at the first failing stage without bypassing checks, force-pushing, or redeploying.
- Grant the Claude Code `design-partner` subagent the Figma MCP server (`mcp__plugin_figma_figma`) in its generated `tools:` frontmatter. It stays read-only: no Edit, Write, or Bash. Other harnesses are unchanged.
- Distribute the Agent Skills in `skills/` through the generators and installers instead of by hand. Every generator except DeepSeek Harness discovers each `skills/<name>/` directory and copies its `SKILL.md` byte-for-byte into the bundle as `skills/<name>/SKILL.md`; a skill directory holding anything else (hidden files aside), a linked one, or one whose name is not lowercase letters, digits, and single hyphens fails generation. The OpenCode, Claude Code, Pi, and OMP installers install each skill as `<target>/skills/<name>/SKILL.md` (for OMP the profile agent root, which OMP reads skills from) as an ordinary managed file: claimed in the manifest, deleted when a later version drops or renames the skill, backed up and rolled back like agent files, and subject to the existing collision and `--adopt` rules, with OMP refusing a collision. Only the claimed `SKILL.md` files are written or deleted; other skills in the same directory are never touched, and a removed skill's directory is removed only when empty. Codex stays generator-only (copy `skills/` into `~/.codex/skills/` by hand) and the DeepSeek Harness adapter is unchanged.
- Make the repository the single source of the orchestration policy again, in one short form. The new `policy/orchestration.md` is emitted by the OpenCode, Codex, Claude Code, Pi, and OMP generators as a marker-wrapped instruction artifact (`CLAUDE.md` for Claude Code, `AGENTS.md` for the others), and the OpenCode, Claude Code, Pi, and OMP installers upsert it as a managed section of the harness's global instruction file: created when the file is missing, replaced in place when a section exists, appended after one blank line otherwise. Bytes outside the markers are never changed, the file is never deleted or claimed in a manifest, a pre-existing file needs no `--adopt` and causes no OMP collision, and a file with malformed markers is refused before any file changes. The Claude Code installer therefore replaces a previously installed managed section instead of stripping it. Codex stays generator-only (copy `AGENTS.md` by hand) and the DeepSeek Harness adapter is unchanged.
- Route the Claude profile's `worker`, `explorer`, and `validator` roles to Sonnet (5.5 through the `sonnet` alias on the Anthropic API) with one effort step up each: `worker` → `high`, `explorer` and `validator` → `medium`. The other six roles and the control plane stay on Opus. These roles briefly went to Haiku 5.5, which turned out more expensive than Sonnet in practice.
- Rewrite the nine role descriptions in `policy/routing.toml` to say what each agent does and when to use it. The description is now the only signal a harness has for choosing an agent, so it no longer uses vocabulary from the removed policy.
- Replace the `change-report` skill with two visual-first skills, `planned-change-report` and `completed-change-report`. A harness may invoke them on its own for a non-trivial change or the user may request them; the authorization, gate, and mandate rules tied to the removed policy are gone.
- Stop generating orchestration policy and instruction content. The role contracts (`roles/*.md`), `policy/orchestration.md`, the feature workflow, the routing delegation graph, and every generated global instruction artifact are removed. Each generated bundle now carries only agent and subagent definitions plus their model/effort carriers, and the installers strip previously installed managed instruction artifacts while preserving user bytes (except OMP, which removes the retired `APPEND_SYSTEM.md` name unconditionally even with no prior manifest and keeps no backups).
- Rewrite `README.md` against the post-reset repository and delete the two `docs/reports/` pages that linked to removed paths. Codex remains generator-only, so an operator upgrading from an earlier version must remove the stale `~/.codex/AGENTS.md` policy text and old agent TOMLs by hand.
- Add a DeepSeek Harness adapter (`harnesses/dsh/`) that exposes the nine roles as delegation lanes on a generated `agent-orchestration` agent preset in the harness home patch, with per-lane model, reasoning effort, and tool filter; a managed section an earlier adapter wrote into `AGENTS.md` is stripped as legacy cleanup.
- Label finding authorization options with the specific fix instead of repeating `Do now`; retain per-finding approval and `Not now`.
- Migrate active OpenAI Sol routing to GPT-6.1, retaining GPT-6 Luna without changing role or effort mappings.

- Require user-facing status and explanations to lead with the outcome and next decision in plain language, avoid redundant recaps and framing, and keep mandatory evidence compact without hiding uncertainty.
- Replace the finding-disposition labels with `Do now — [specific fix]` and `Not now`; require explicit choice of the authorized route when findings have multiple viable fixes, and avoid default action recommendations or untracked deferrals.

- Route every Claude profile role and the control-plane small model to Opus, dropping
  Sonnet; former Sonnet roles take a lower effort instead (`worker`, `design-partner`,
  `ux-critic` → `medium`; `validator`, `explorer` → `low`).
- Allow bounded external-job monitoring by delegated `validator`/`debugger` lanes in the
  shared policy when the handoff names the whole-lane deadline, poll interval, and
  per-call timeout, and hard cancellation of the lane and its in-flight process/tool call
  is available; the one-shot-only restriction moves to the Pi operational note, since Pi
  cannot reliably hard-cancel a child's in-flight tool call.
- Require startup, idle, and total-runtime watchdog boundaries wherever a harness exposes
  child progress plus targeted cancellation, with terminal `BLOCKED` only after an
  acknowledged stop and evidence of the last meaningful progress.
- Document the optional `harness-extensions` Pi watchdog, its 120-second startup, 5-minute
  idle, and 30-minute total defaults, real `subagents:rpc:stop` cancellation, and the
  upstream limitation for nested and workflow-owned children.
- Rename the harness layer from `adapters/` to `harnesses/`, rename each harness
  renderer module to `generate.py`, and standardize the user-facing wording on generating
  harness configuration. Remove the committed `generated/` tree and move the default
  generator output to the untracked `build/` tree (`build/` and `generated/` are ignored);
  `scripts/generate` rebuilds every supported harness/profile output under `build/` by
  default, and `scripts/check` proves full-output determinism by generating each
  OpenCode, Codex, Claude Code, and four Pi profile output twice in separate temporary
  roots and diffing the corresponding results instead of validating committed snapshots.
  Codex remains generator-only with no installer.
- Remove the custom Pi `git-read.ts` runtime extension: no profile generates or manages a Pi
  extension package, `managed_extensions` is empty, and explorer uses Pi's built-in `bash`
  instead. Canonical `bash = "ask"` for explorer is explicitly degraded to allow because Pi
  cannot forward an ask from a headless child; `acceptanceRole: read-only` remains
  prompt/acceptance metadata rather than a hard read-only sandbox. The installer treats
  `git-read.ts` and `extensions/agent-orchestration/package.json` as retired migration-only
  managed paths and deletes them on upgrade.
- Move Pi provider status implementations to the separate `harness-extensions` runtime
  repository and replace the `primary-policy` extension with Pi's native CLI boundary. Each
  profile launcher selects its primary `--model` and `--thinking`, exports
  `AGENT_ORCHESTRATION_PROFILE` for optional native packages, and appends the generated shared
  `orchestration-core.md` through `--append-system-prompt`. The installer removes retired
  in-repo status/primary extensions as migration-only stale artifacts without managing the
  separately installed runtime package.
- Add bounded delegation and responsiveness rules: source-changing handoffs own one
  independently verifiable slice and validator checkpoint, capped work stops without
  self-extension, and potentially non-brief work stays in the background when supported.
  Pi generates explicit `max_turns` and `run_in_background` guidance with conservative
  foreground and background mutation defaults, plus hard per-call deadlines for potentially
  blocking child tool calls. Operations are not delegated when timeout and termination cannot
  be enforced.
- Remove dedicated `vision-*` delegation: `worker` and `worker-complex` are leaves, and
  vision-incapable primaries route directly to existing image-capable roles.
- Simplify orchestration by removing the `spec-writer` role and planning-artifact guard;
  planners now return managed output, while selected worker tiers own repository persistence.
- Make Pi permissions, authentication, MCP configuration, and theme selection/files
  operator-owned: installers neither copy nor claim them, preserve legacy files during the
  one-time manifest migration, and continue transactional cleanup of retired project files.

- Extend the production Pi adapter with isolated OpenAI and DeepSeek bundles, explicit
  fail-closed provider mapping, exact all-role DeepSeek Flash routing, native vision,
  executable profile launchers, and deterministic committed snapshots.
- Extend the dry-run-first Pi installer with profile isolation, launcher adoption and
  rollback, target-specific runtime validation, a preserving DeepSeek settings merge,
  and validated `deepseek` model-catalog bootstrap while keeping authentication manual.
- Add versioned profile control-plane intent for the primary/small models and built-in
  `build`/`plan` mappings, with OpenAI Sol/Luna routing and explicit harness validation.
- Replace ceremonial mandatory delegation with proportional delegation for leverage while
  retaining independent validation for delegated source changes and the strict reviewer
  user-verdict gate.
- Move the detailed Feature Workflow Pilot into a separately packaged optional workflow
  artifact so base prompts remain compact.
- Add Codex/OpenCode/Claude Code control-plane artifacts and extend installers to manage
  optional workflows without overwriting unrelated configuration.
- Add the read-only `scripts/check-runtime` drift check for effective OpenCode settings,
  with secret-safe diagnostics and fixture-based tests.
- Add explicit profile schema/source validation, a pinned uv/Python 3.11+ workflow, and CI
  coverage through `uv run --locked ./scripts/check`.
- Add a simple Codex generator for the ten role contracts using the OpenAI profile's model, reasoning, and sandbox mappings.
- Generate and check OpenCode and Codex harness configuration; Codex artifacts are copied or symlinked manually without an installer.
- Make reviewer participation explicitly user-directed, while retaining independent validation for code and behavior changes.
- Require observable acceptance evidence, bounded review-fix cycles, compact handoffs, event-based orchestration updates, and lightweight pilot usage measurements.
- Add a Claude Code adapter (`harnesses/claude-code/`) mirroring the OpenCode adapter's generation, diff, backup, install, and rollback architecture.
- Add a `claude` model-routing profile (`profiles/claude.toml` + `profiles/claude.md`) with per-role Claude model aliases and effort levels.
- Add a `harness` field to profile files (defaulting to `opencode` for backward compatibility): OpenCode and Claude Code skip Pi-only profiles, Codex rejects incompatible explicit profiles, and the Pi generator selects its supported profile explicitly.
- Bake model and effort directly into each generated Claude Code subagent's frontmatter, since Claude Code has no profile-routing layer equivalent to OpenCode's `agent-routing.json`.
- Express routing delegation as `Agent(<target>)` tool entries and document that Claude Code has no per-subagent equivalent of `bash = "ask"`.
- Merge the shared orchestration policy into a target `CLAUDE.md` using `<!-- agent-orchestration:start -->` / `<!-- agent-orchestration:end -->` markers, preserving unrelated content.
- Extend `scripts/generate` and `scripts/check` to cover Claude Code output.
- Clarify the definition of a trivial request, when validator involvement is mandatory, what counts as explicit review authorization, the one-sentence non-blocking form of the review recommendation, and the per-finding repair budget in the reviewer user-verdict gate.
- Document Claude Code subagent history defaults, the `Agent` tool's `model` parameter restriction, and built-in harness agent usage constraints in the Claude Code adapter README and the `claude` profile addendum.
- Generate the active profile's addendum into the shared `orchestration-core.md` section, after the policy text, so installed `CLAUDE.md` files receive the Claude Code harness notes that were previously never generated.
- Align mandatory-validation scope, the reviewer repair-budget cap, and the orchestrator's trivial-work exception with their surrounding rules, removing internal contradictions in the shared policy.
- Invoke `python3` instead of a hardcoded `python3.11` in every script and adapter shebang, relying on the caller's environment (e.g. CI's `actions/setup-python`) to provide 3.11+; each generator fails fast with a clear message if run under an older interpreter.
- Fix the Codex generator's default `--output` being resolved at import time, which bypassed the symlink guard for a symlinked `build/codex` when no `--output` flag was passed; it now matches the unresolved-default pattern already used by the Claude Code and OpenCode generators.

## 0.1.0 — 2026-08-22

- Establish a harness-agnostic policy and role-contract source of truth.
- Add OpenAI, GLM, and OpenCode Go model-routing profiles.
- Add routine `worker` and difficult-reasoning `worker-complex` tiers.
- Allow planner to delegate repository evidence to `explorer` and planning-artifact production to `spec-writer`.
- Keep reviewer read-only with explorer-only nested delegation and an explicit user-verdict gate.
- Separate worker self-checks from independent validator evidence.
- Add a single automatic repair-cycle budget and risk-based mandatory review.
- Add OpenCode rendering, snapshot, diff, backup, install, rollback, and profile-validation tooling.
- Track managed roles with a local manifest so obsolete generated roles can be removed safely.
- Preserve unrelated harness instructions and custom agents during installation.
- Restrict renderer replacement to the committed snapshot destination or temporary directories.
- Require confirmation for validator/debugger shell commands to keep read-only enforcement outside the prompt layer.
- Reject symlinked managed destinations before reading or displaying their contents.
- Remove all managed agents and artifacts when a profile leaves the policy.
- Roll back interrupted installs, including `KeyboardInterrupt` during mutation or validation.
- Restore the previous generated snapshot if atomic renderer replacement is interrupted.
