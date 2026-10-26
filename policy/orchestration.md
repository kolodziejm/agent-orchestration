## Delegation

- The main agent's context is valuable. Protect it.
- Delegate work to subagents by default: searching and reading code, implementing changes, running tests and builds.
- If you are a subagent, do the work yourself and do not delegate further.
- Do a small, clear task yourself when a handoff would cost more than the work: one file, one command, a quick check.
- Otherwise, do not read source files yourself. Ask a subagent.
- Prefer user-defined subagents over built-in ones. Use a built-in agent such as `general-purpose` only when no user-defined one fits, and state the reason in the brief.
- Implement with `worker`: the default implementer for everything not listed under `worker-complex`, including large changes. If the approach is not settled, settle it first and put it in the brief: do it yourself for a small one; use `planner` only for a decision big enough to deserve its own document, and then point the implementer at that document, not at a summary.
- Use `worker-complex` only for auth and security, bugs with an unknown root cause, merges that must keep both sides' intent, and algorithms, concurrency, or state machines. Size, file count, and brief length are not reasons.
- In a series of similar changes, only the first, which sets the pattern, may go to `worker-complex`, and only if it meets the criteria above. Send the rest to `worker` and name the first as the reference.
- Use `explorer` to search and read code, and `debugger` to find a root cause when no fix is wanted.
- Full gates are the project's complete documented checks: the full test suite, lint, typecheck, and build. An implementer runs only targeted checks (the affected tests, the package typecheck), so its brief names them and says that the full gates are `validator`'s.
- Run `validator` for the full gates once per round, on a deliverable (a PR, or a batch that lands together), whoever made the change. Its brief names the full gates when they are known.
- When `validator` reports a failure, continue the same implementer with the report. If the harness cannot continue it, start a new run of the same role with the original brief, the current diff, and the report; it counts as the next round.
- The first implementation and its validation are round 1; a fix and its re-validation are round 2. If `validator` still reports a failure in round 2, stop and ask the user. Never switch the implementer to another role without asking.
- The user controls which models run. By default, start subagents through the harness's native subagent tool, so each user-defined agent runs with the model and effort set in its definition, even when a host app's instructions recommend its own tools. Do not override an agent's model or effort.
- A host app such as T3 Code can run subagents on other harnesses and providers. Use its tools when the user turns on a preset with the `save-subscription` skill, or asks for another provider or model, a separate thread, or a child task in its own worktree.
- Ask each subagent for a short result: what it found or did, check results, and file paths with line numbers. No code dumps or logs.

## Visuals

- Leave out secondary labels and descriptions the reader does not need. Let the layout explain the content.
