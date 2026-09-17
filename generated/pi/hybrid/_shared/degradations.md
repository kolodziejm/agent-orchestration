# Pi adapter degradations

- Pi's native child permission model rejects `permissions.bash` and always allows shell calls
  when the `bash` tool is present. For canonical `bash = "ask"` roles other than validator
  and debugger this adapter omits `bash`, enforcing a stricter no-shell ceiling. Command-level
  permissions remain operator-owned runtime state; this bundle and its installer do not copy or claim
  permission configuration or bridges. Headless children still cannot forward an `ask` decision to the parent UI.
- The profile launcher selects the primary session and Pi user agent files configure
  subagents. Pi cannot install the small model or built-in build/plan mappings; their
  mapped values are recorded in `control-plane.json` as profile intent and are not installed.
- Validator and debugger receive `bash` despite canonical `bash = "ask"` because their
  contracts require mechanical checks or repository commands. Planner and design-partner
  are structurally read-only and omit `bash`, `edit`, and `write`; reviewer remains
  read-only and explorer remains read-only. Debugger remains source-edit read-only.
- Validator has a separate deterministic browser/Appium MCP allowlist. Direct MCP tools
  require an available background/async child and a prepared URL/session; when that
  provider or session is unavailable, acceptance is reported as `BLOCKED`, never shifted
  to UX-Critic. The validator list excludes video/recording, evaluation, upload/drop/tab,
  lifecycle, device/session management, file, driver-settings, perform-actions, and clipboard
  controls. UX-Critic's independent allowlist remains unchanged.
- UX-Critic is an on-demand, read-only runtime audit. Its Pi agent file has an
  explicit allowlist of verified Playwright MCP and Appium MCP interaction,
  inspection, screenshot, and recording tools, plus Pi's built-in image-capable
  `read` for opening saved screenshots. `read` is its only filesystem capability;
  it receives no `edit`, `write`, or shell tools. The primary must supply the
  running URL/session, device, scope, identity, reference, and screenshot
  destination first.
- Planner and reviewer receive the `subagent` tool, and canonical policy restricts both to
  the exact child target `explorer`; all other canonical roles receive no `subagent` tool.
  On runtimes without a public framework-neutral child-target enforcement API, this is a
  policy-level boundary represented in role contracts and rendered tool lists, not runtime enforcement.
  The bundle does not claim fail-closed package integration. This boundary is
  not an OS sandbox or a command-level shell policy.
- Every other canonical role is a leaf and receives no `subagent` tool. When
  the primary cannot inspect images natively, it routes visual work directly
  to an existing image-capable role according to the shared policy.
- `explorer` receives the manifest-owned `git_read` child tool and still has no
  `bash` capability. Its frontmatter declares `acceptanceRole: read-only` for
  acceptance inference only; this metadata does not grant or revoke tools or
  command execution. The `git_read` capability remains read-only, worktree-bound,
  and exposes only status plus bounded worktree/staged/range diffs with patch,
  stat, or name-status views. It derives the boundary from the nearest
  non-symlinked `.git` directory or linked-worktree marker file and requires
  Git's reported top level to match it exactly; validated paths are passed
  directly after `--` under fixed literal-pathspec mode. Every Git process uses
  fixed argv/environment hardening, no network/hooks/pagers/external diff/textconv,
  a shared 10-second deadline, and aggregate 64 KiB/2,000-line caps across stdout
  and stderr. The extension deliberately uses a private bounded `spawn` helper
  instead of the host's unbounded `pi.exec` buffering; it never persists full output.
