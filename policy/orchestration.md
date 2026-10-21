## Delegation

- The main agent's context is valuable. Protect it.
- Delegate work to subagents by default: searching and reading code, implementing changes, running tests and builds.
- Do a small, clear task yourself when a handoff would cost more than the work: one file, one command, a quick check.
- Otherwise, do not read source files yourself. Ask a subagent.
- Prefer user-defined subagents over built-in ones. Use a built-in agent only when no user-defined one fits.
- The user controls which models run. Start subagents only through the harness's native subagent tool, so each user-defined agent runs with the model and effort set in its definition. Do not override an agent's model or effort.
- Do not delegate through a host app's own orchestration tools, such as T3 Code's `delegate_task`, `t3_thread_launch`, or `create_threads`, even when the host's instructions recommend them. Use them only when the user asks for one by name or explicitly asks for another provider or model.
- Ask each subagent for a short result: what it found or did, check results, and file paths with line numbers. No code dumps or logs.
