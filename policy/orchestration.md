## Delegation

- The main agent's context is valuable. Protect it.
- Delegate work to subagents by default: searching and reading code, implementing changes, running tests and builds.
- Do a small, clear task yourself when a handoff would cost more than the work: one file, one command, a quick check.
- Otherwise, do not read source files yourself. Ask a subagent.
- Prefer user-defined subagents over built-in ones. Use a built-in agent only when no user-defined one fits.
- The user controls which models run. By default, start subagents through the harness's native subagent tool, so each user-defined agent runs with the model and effort set in its definition, even when a host app's instructions recommend its own tools. Do not override an agent's model or effort.
- A host app such as T3 Code can run subagents on other harnesses and providers. Use its tools when the user asks for another provider or model, a separate thread, or a child task in its own worktree.
- Budget mode: when the user asks to spare their subscription limits, send subagent work through the host's tools to the cheaper model they name, such as DeepSeek Flash or a local Qwen through OpenCode, until they end budget mode. If they name no model, ask which one. Keep your own work to briefing subagents and checking their results.
- Ask each subagent for a short result: what it found or did, check results, and file paths with line numbers. No code dumps or logs.

## Visuals

- Leave out secondary labels and descriptions the reader does not need. Let the layout explain the content.
