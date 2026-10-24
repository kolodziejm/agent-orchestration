## Delegation

- The main agent's context is valuable. Protect it.
- Delegate work to subagents by default: searching and reading code, implementing changes, running tests and builds.
- If you are a subagent, do the work yourself and do not delegate further.
- Do a small, clear task yourself when a handoff would cost more than the work: one file, one command, a quick check.
- Otherwise, do not read source files yourself. Ask a subagent.
- Prefer user-defined subagents over built-in ones. Use a built-in agent such as `general-purpose` only when no user-defined one fits, and say why.
- Implement with `worker`. It is the default, including for large changes whose approach a plan, an existing pattern, or an explicit list has settled.
- Use `worker-complex` only for auth and security, bugs with an unknown root cause, merges that must keep both sides' intent, and algorithms, concurrency, or state machines. Size, file count, and brief length are not reasons.
- In a series of similar changes, only the first, which sets the pattern, may go to `worker-complex`. Send the rest to `worker` and name the first as the reference.
- Use `explorer` to search and read code, and `debugger` to find a root cause when no fix is wanted.
- In an implementer's brief, name the targeted checks it runs (the affected tests, the package typecheck) and say that the full gates are `validator`'s. An implementer runs only the targeted checks.
- After implementation, run `validator` for the full gates.
- When `validator` reports a failure, continue the same implementer with its report. After 2 rounds of implementing and validating, stop and ask the user.
- The user controls which models run. By default, start subagents through the harness's native subagent tool, so each user-defined agent runs with the model and effort set in its definition, even when a host app's instructions recommend its own tools. Do not override an agent's model or effort.
- A host app such as T3 Code can run subagents on other harnesses and providers. Use its tools when the user turns on a preset with the `save-subscription` skill, or asks for another provider or model, a separate thread, or a child task in its own worktree.
- Ask each subagent for a short result: what it found or did, check results, and file paths with line numbers. No code dumps or logs.

## Visuals

- Leave out secondary labels and descriptions the reader does not need. Let the layout explain the content.
