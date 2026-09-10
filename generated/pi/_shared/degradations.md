# Pi adapter degradations

- Supported pi-subagents releases at or above the v0.67.0 minimum-tested baseline reject `permissions.bash` and always allow shell calls
  when the `bash` tool is present. For every canonical `bash = "ask"` role this
  adapter omits `bash`, enforcing a stricter no-shell ceiling. Install and configure
  a separate permission wrapper if command-level allow/deny behavior is required; headless
  children still cannot forward an `ask` decision to the parent UI.
- Pi user agent files configure subagents, not the primary session, small model, or
  built-in build/plan agents. Their mapped values are recorded in `control-plane.json`
  as profile intent and are not installed by this adapter.
- The OpenAI profile has no concrete `vision-*` role among its ten canonical roles.
  Wildcard visual delegation is therefore guidance only; no nonexistent agent is
  advertised in a strict tool allowlist.
