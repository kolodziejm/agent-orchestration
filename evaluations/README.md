# Evaluation contract

`schema/evaluation.schema.json` is the portable, versioned Draft 2020-12 contract for:

- reusable task corpora (`corpora/*.json`), including a task class, immutable or fixture
  workspace reference, prompt, and deterministic acceptance commands;
- opt-in, profile-scoped, `EXPERIMENT_ONLY` configuration catalogs (`configurations/*.json`),
  including closed dimension values and their enforcement/support classification;
- plans (`plans/*.json`) pairing exactly two configuration references over selected corpus tasks;
- per-task, per-variant results (`results/*.json`). Result files are optional.
Every requested metric is required in a result. Use `status: OBSERVED` with a schema-typed `value` only when measured. Use `NOT_COLLECTED` when collection was not attempted or available, and `UNKNOWN` when collection occurred but no reliable value can be established; both require a reason and prohibit a value. Never substitute estimates, defaults, or fabricated outcomes.
Acceptance evidence is ordered by the task's `acceptance` list. An observed entry records the exact acceptance ID, pass/fail outcome, and process exit code. Unavailable evidence uses the same `NOT_COLLECTED`/`UNKNOWN` distinction and an explicit reason. Validation rejects missing, extra, duplicated, or reordered evidence IDs.
References are logical IDs, not harness-specific paths. `profile_ref` must resolve to a repository profile; `configuration_ref`, `corpus_ref`, `plan_ref`, `task_ref`, and `variant_ref` must resolve within the checked document set.
Catalogs describe evaluation inputs only. They do not activate configurations, modify profiles or generated bundles, or define runtime adapter behavior.
The canonical Pi/OpenAI catalog keeps one task-calibrated baseline and changes exactly one
dimension per candidate so paired plans do not confound turn budgeting, planning, action
space, and context management.
Each result has a one-based `run_index`, allowing repeated paired runs without changing the
task or variant identity. A task's `workspace_ref` is likewise opaque to this repository, but
the producer must resolve it to the same reproducible workspace for both paired variants.
The normal repository check validates the schema itself and all JSON documents before tests or generation:
```sh
uv run --locked ./scripts/check
```
To validate an isolated document tree with the same entrypoint:
```sh
uv run --locked python harnesses/validate.py --evaluations-root /path/to/evaluations
```

No runner, scheduler, provider integration, or live canary is defined by this contract.
