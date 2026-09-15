# Pi GLM profile orchestration

- This profile uses the Z.AI GLM Coding Plan provider the official `zai` provider through its OpenAI Chat Completions API at `https://api.z.ai/api/coding/paas/v4`.
- `glm-5.3` is the text-only Sol/control-plane model. `glm-5.3-flash` is the image-capable Luna/small-model model; use it for roles that must inspect supplied images or screenshots.
- Both GLM models have a 1,000,000-token context window and support the Pi thinking levels `low`, `high`, and `max`. Authentication is intentionally deferred to `/login zai` after launching `pi-glm`; this profile installer never copies or creates credentials.
- The GLM-5.3 status footer uses the official weekday 06:00–10:00 UTC peak window (14:00–18:00 Singapore time): `GLM peak ×3`; all other times, including weekends, show `GLM off-peak ×1`. GLM-5.3-Flash is billed at ×1.2 peak and ×0.4 off-peak; these Flash multipliers are documented separately and are not shown in the compact primary footer.
