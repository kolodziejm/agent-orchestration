## Delegation

- The main agent's context is valuable. Protect it.
- Delegate work to subagents by default: searching and reading code, implementing changes, running tests and builds.
- Do a small, clear task yourself when a handoff would cost more than the work: one file, one command, a quick check.
- Otherwise, do not read source files yourself. Ask a subagent.
- Prefer user-defined subagents over built-in ones. Use a built-in agent only when no user-defined one fits.
- Ask each subagent for a short result: what it found or did, check results, and file paths with line numbers. No code dumps or logs.
