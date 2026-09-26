# Phase 4D compact request recovery — offline evidence

No provider/database calls, live mutations, migration application or deployment were performed.

## Evidence limits

The user reports HTTP 413 for run `ddf79e0b-4fb5-41ba-b688-26e6634a223e` before parsing. No safe provider error body or live frozen snapshot is available locally. Consequently the exact provider limit and exact historical wire bytes are NOT proven. These measurements use the existing repository's synthetic 6-requirement/8-dependency/5-stage fixture through the real prompt and HTTPX encoding path, not the live snapshot. They must not be described as measurements of that historical run.

| UTF-8 bytes unless stated | Before | After |
|---|---:|---:|
| Full frozen snapshot | 8,157 | 8,157 |
| Provider projection | 5,931 | 5,931 |
| Output specification | 11,931 | 6,149 |
| System safety text | 342 | 342 |
| Instructions including specification/mapping | 14,014 | 8,420 |
| Final system message content | 14,357 | 8,763 |
| Final user message content | 6,071 | 6,071 |
| Serialized messages array | 23,247 | 16,499 |
| Complete serialized Groq body | 23,392 | 16,644 |
| Max completion tokens | 8,192 | 8,192 |
| Rough input tokens (content UTF-8 bytes / 4, rounded up) | 5,107 | 3,709 |

Body reduction: 6,748 bytes / 28.85%. Token figures are heuristic, NOT Groq tokenizer/quota measurements. JSON escaping accounts for the difference between text size and wire size. No keys/headers/content are included in this report.

## Findings and correction

The full snapshot is not sent. There is one system message, one projection message, one specification; no duplicate full prompt/schema or examples. The old schema repeated identical scalar types, UUID constraints, bounds and enums across grounded structures. Shared definitions now factor those losslessly; a round-trip test reconstructs the exact annotation-stripped Pydantic schema. Requiredness, types, enum values, bounds and extra-field prohibition remain unchanged. Field names remain explicit. Grounding field names recur where required by the output contract; evidence is not removed/deduplicated across requirements. Projection data, timings, references, dependencies and stages are unchanged.

The mapping now correctly names projection `employee.experience_level` (the previous prose incorrectly said `experience`). Stage and canonical locator mappings remain explicit. Provider JSON mode and request parameter names are unchanged. No evidence proves that JSON mode or output allowance caused the 413. Keep 8,192 output tokens: prior reported real output used 5,885, and lowering to a small cap risks truncation of a complete plan.

An internal 24 KiB final serialized-body limit provides headroom above the 16.6 KiB fixture while bounding escaping/format-retry growth. It is measured with HTTPX's encoder and the exact resulting bytes are transmitted. Overflow yields `GENERATION_PROJECTION_TOO_LARGE`, without transport invocation or partial input. The fixture regression ceiling is stricter at 18,000 bytes. Neither ceiling guarantees provider acceptance for this account.

## Provenance and security

New prompt: `phase4d-compact-exact-output/1.0.0`.
Template hash: `ed734c3b6d71d456bbd5114c63cc945ae7147f07d4a3a41e72ec284abea6c7c1`.
Projection serializer remains `generation-projection/1.1.0`; output remains `onboarding-plan/1.0.0`.

New migration `202609260001_compact_generation_output_contract.sql` adds the new prompt's non-null projection constraint and replaces the bounded reservation function's prompt/template pin only. A test normalizes those intentional changes and compares the entire migration with its predecessor. No historical UPDATE/DELETE/backfill, grants/RLS changes or old migration edits. Caller authorization, full input hash, projection hash, provider/model, idempotency, frozen input locks and lifecycle remain intact. Prior prompt pins remain auditable. Successful output is still UNVERIFIED; no Phase 5 semantics added. Safe loc/type diagnostics and bounded 429 Retry-After policy remain unchanged.

## Automated checks

Focused generation/context/API/provider/SQL suite: 130 passed.
Full backend: 421 passed, one existing Starlette TestClient deprecation warning, exit 0 and normal termination.
SQL contracts: 11 passed (included above).
`git diff --check` passed. Scoped credential-pattern scan across all 11 touched files found no matches. Additional whole-file whitespace scan found only an existing Markdown two-space line break at `ARCHITECTURE.md:4`; no new whitespace defect.

Static migration verdict: SAFE_TO_APPLY after human review, exactly once; not applied here. SQL execution is not claimed. One subsequent human-authorized run is reasonable after migration application, but provider acceptance is not proven by offline size reduction. Preserve all failed runs.
