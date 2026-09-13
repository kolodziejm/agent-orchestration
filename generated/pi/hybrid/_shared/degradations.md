# Pi adapter degradations

- Supported pi-subagents releases at or above the v0.67.0 minimum-tested baseline reject `permissions.bash` and always allow shell calls
  when the `bash` tool is present. For canonical `bash = "ask"` roles other than validator,
  debugger, and planner this adapter omits `bash`, enforcing a stricter no-shell ceiling. Install and configure
  a separate permission wrapper if command-level allow/deny behavior is required; headless
  children still cannot forward an `ask` decision to the parent UI.
- The profile launcher selects the primary session and Pi user agent files configure
  subagents. Pi cannot install the small model or built-in build/plan mappings; their
  mapped values are recorded in `control-plane.json` as profile intent and are not installed.
- Validator, debugger, and planner receive `bash` despite canonical `bash = "ask"` because
  their contracts require mechanical checks or repository commands. Debugger remains source-edit
  read-only; planner retains its existing edit/write/subagent capabilities.
- UX-Critic is an on-demand, read-only runtime audit. Its Pi agent file has an
  explicit allowlist of verified Playwright MCP and Appium MCP interaction,
  inspection, screenshot, and recording tools, plus Pi's built-in image-capable
  `read` for opening saved screenshots. `read` is its only filesystem capability;
  it receives no `edit`, `write`, or shell tools. The primary must supply the
  running URL/session, device, scope, identity, reference, and screenshot
  destination first.
- Planner and reviewer receive the `subagent` tool plus a child-only,
  profile-owned capability ceiling. The planner ceiling allows only `explorer`
  and `spec-writer`; the reviewer ceiling allows only `explorer`. The guard
  resolves pi-subagents through its public `./capability-ceiling` export and
  fails closed if that package or registration is unavailable. This is a
  child-selection boundary, not an OS sandbox or a command-level shell policy.
- Every other canonical role is a leaf and receives no `subagent` tool. The
  selected profile has no concrete `vision-*` role among its ten canonical
  roles, so wildcard visual delegation remains guidance only.
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
  instead of Pi 0.85.1's unbounded `pi.exec` buffering; it never persists full
  output.
