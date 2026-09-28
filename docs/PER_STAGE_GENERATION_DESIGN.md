# Per-stage parallel generation — design (not implemented)

Status: proposed on 2026-09-28. Not implemented; build only on explicit approval.

## Problem

One provider call generates the whole onboarding plan. On the free NaraRouter
models a complete plan takes about 136 s (agnes-2.5-flash, 6-requirement fixture):
the output is roughly 7–8k tokens and the model reasons before writing it. That is
far above the SRS 30-second target. Disabling reasoning (`reasoning_effort: none`)
made both free models fast (17–26 s) but they then returned plans with **no
modules**, so reasoning cannot simply be switched off for a whole plan.

## Idea

Generate one stage per call, run the calls in parallel, and merge. Each call
produces about one fifth of the output, so latency should fall to the slowest
single stage rather than the sum.

## Design

1. **Split (Python, deterministic).** Group the frozen snapshot's requirements by
   `stage_definition_id`. Requirements without a stage form one extra group
   whose call may place modules in any stage. Stages with no requirements get no call.
2. **Pre-assign module IDs.** For every requirement, Python computes
   `module_id = uuid5(run_id, requirement_revision_id)`. The projection tells the
   model which `module_id` to use for each requirement and gives the IDs of
   prerequisite modules in other stages. Cross-stage `prerequisite_module_ids` can
   then be written correctly without seeing the other calls' output. Nothing is
   repaired after generation.
3. **Per-stage call.** Same system rules and the same provider JSON Schema. The
   untrusted data contains only that group's requirements, their evidence, the
   prerequisite module IDs and the full stage list. The output must still contain
   every stage, with modules only in its own stage, so `parse_plan` works unchanged
   on each part.
4. **Parallel execution.** `asyncio.gather` over the calls. Each keeps the existing
   total per-call deadline, and one run budget covers the whole fan-out.
5. **Merge.** Stage-wise union of modules plus concatenated `insufficient_information`.
   Duplicate module IDs across parts fail the run with a structural error.
6. **Validate unchanged.** The merged plan goes through `parse_plan`, the Python
   validator and JEV exactly as today. The validator remains the only authority on
   coverage, sources, timing and dependencies.
7. **All or nothing.** If any stage call fails after its bounded retries, the run
   fails. Partial plans are never persisted.

## Required changes

| Area | Change |
|---|---|
| `generation_service.py` | Split, fan out, merge, one run budget |
| `generation_prompt.py` | Per-group projection plus the module-ID instruction, as a new prompt version |
| Migration | The new prompt version and template hash are pinned in `reserve_generation_run_bounded`; the per-run attempt limit (`attempt_no between 1 and 4`) must grow to cover several calls (for example 1–20) |
| Tests | Split/merge unit tests, cross-stage prerequisite IDs, all-or-nothing failure, mocked parallel calls, SQL contract test |

Estimated effort: 3–4 hours including a live check.

## Expectations and risks

- Expected: about 5 parallel calls of 25–40 s each, so roughly 30–45 s end to end. Unproven.
- Free-tier rate limits may serialise parallel calls; bounded 429 retries still apply.
- Smaller calls may allow `reasoning_effort: none` again. This must be re-measured,
  because a whole plan came back empty without reasoning.
- More calls means more provenance rows per run. Each attempt stays individually
  recorded, as today.
