# Pi adapter degradations

- Pi's native child permission model rejects `permissions.bash` and always allows shell calls
  when the `bash` tool is present. Pi cannot forward an `ask` decision from a headless child
  to the parent UI, so the adapter resolves every canonical `bash = "ask"` role to a concrete
  grant or denial. Validator, debugger, and explorer receive `bash`; reviewer omits `bash` and
  keeps a stricter no-shell ceiling. Command-level permissions are operator-owned runtime state;
  this bundle and its installer do not copy or claim permission configuration or bridges.
- The profile launcher selects the primary session and Pi user agent files configure
  subagents. Pi cannot install the small model or built-in build/plan mappings; their
  mapped values are recorded in `control-plane.json` as profile intent and are not installed.
- Validator, debugger, and explorer receive `bash` despite canonical `bash = "ask"` because
  their contracts require mechanical checks, repository commands, or repository evidence.
  This is an explicit, documented weakening: `bash` is unrestricted for these children and
  there is no hard read-only sandbox. Planner and design-partner are structurally read-only
  and omit `bash`, `edit`, and `write`; reviewer remains read-only and also omits `bash`.
  Debugger remains source-edit read-only.
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
- Every rendered profile manages no Pi extension package: there is no
  `extensions/agent-orchestration` directory, no extension `package.json`, and
  `managed_extensions` is empty. `explorer` receives Pi's built-in `bash` tool instead of
  the removed `git_read` extension.
- `explorer` frontmatter declares `acceptanceRole: read-only`, which is prompt/acceptance
  metadata for acceptance inference only. It does not grant or revoke tools, does not create a
  hard read-only sandbox, and does not constrain `bash`; `explorer` is expected to gather
  repository evidence through read-only commands and the non-mutating read tools. The
  installer validates only this tool allowlist and acceptance metadata, not the shell
  commands a child runs.
