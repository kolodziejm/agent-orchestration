# DeepSeek Harness profile

DeepSeek Flash is the recorded model for the primary session, the small model, built-in build
and plan intent, and every canonical child role. DeepSeek Harness 0.2 advertises
`deepseek-flash` (DeepSeek-V41-Flash) with `inputModalities: ["text", "image"]` on the
`deepseek-official` route, so this profile declares native vision.

## Vision

The primary model and every canonical role inspect image and screenshot attachments directly.
Visual evidence is still validator-owned runtime proof: a reviewer interprets comparable
before/after captures read-only, and a missing baseline stays unavailable rather than being
reconstructed.

## Installed routing

- Every canonical child role runs `deepseek-flash` through the `deepseek-official` provider
  route. The dsh adapter installs that provider, model, and reasoning effort on each generated
  delegation lane, so a child keeps the role's routed model and effort regardless of the
  session model.
- A DeepSeek Harness agent preset cannot select the session's own model route. The primary
  model, the small model, and the built-in build/plan mappings stay DeepSeek Harness model
  settings; the generated control-plane note records the intended values.

## Delegation

The generated preset carries one delegation lane per canonical role. Each lane pins the role's
provider, model, and reasoning effort, and the capability ceiling the route allows: a tool
filter removes write/edit from read-only roles and the shell from roles that must not run
commands.
