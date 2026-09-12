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
- The selected profile has no concrete `vision-*` role among its ten canonical roles.
  Wildcard visual delegation is therefore guidance only; no nonexistent agent is
  advertised in a strict tool allowlist.
