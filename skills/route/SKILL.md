---
name: route
description: >-
  Route this thread's subagent work to another provider's models through the
  host app, such as DeepSeek Flash through OpenCode in T3 Code, while the primary
  agent keeps its model. Use it only when the user invokes it with a preset name
  or `off`; never start it on your own initiative.
compatibility: Requires a host app that runs child tasks on another provider, such as T3 Code with its `orchestrator_capabilities`, `delegate_task`, and `task_status` tools.
---

# Route

The user picks a preset for this thread: `/route <preset>` turns it on, `/route off` turns it off, `/route` alone reports the current routing and lists the presets from `presets.json`. A preset holds until the user turns it off or picks another one.

## Presets

Presets live in `presets.json` next to this file, generated from the repo profiles that have a `[route]` table. A preset is a profile name with its `providerInstanceId` and, per role, a `model` and `options`. It routes every role it lists to that model and options through `delegate_task` (`target` = `providerInstanceId` + `model` + `options`). A role the preset does not list, and your own work, keep their native model.

## Turning a preset on

1. Call the host's `orchestrator_capabilities`. Check that the preset's provider instance can run cross-provider child tasks and lists every model the preset uses. If it cannot, tell the user what is missing and keep the native routing.
2. Tell the user in one line which roles now go to which model, and which stay native.

## While a preset is on

- Start every role the preset lists with the host's `delegate_task`: `target` is the preset's `providerInstanceId`, and that role's model and options, and `mode` is `async`. Give each task its own `clientRequestId`. Its completion wakes this thread, so do not poll; use `task_status` only when you need the result mid-turn, and `task_cancel` to stop it.
- Brief the child as you would a native subagent.
- Start a role the preset does not list through the native subagent tool as before.
- If a routed task fails because of the provider (unavailable model, quota, auth), tell the user and ask whether to run it natively.

## Turning it off

Go back to the native subagent tool for every role and say so in one line.
