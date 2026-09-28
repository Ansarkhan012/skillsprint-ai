# Compact context V2 review

Implemented offline on 2026-09-27. Architecture and onboarding-plan/1.0.0 validation are unchanged.

## Contracts and provenance

- Prompt: `phase4d-compact-context/2.0.0`.
- Projection: `generation-projection/2.0.0`.
- Output: `onboarding-plan/1.0.0`.
- Template hash: `11b1127daf611a0d6739c185f9815570cff9abd29e73bcee7117121daf85abbc`.
- Historical implementation: `services/api/app/generation_prompt_v1.py`, an unchanged copy of the previous prompt module. Golden tests pin its original template and projection hashes. Current generation uses V2; the historical module supports offline reconstruction/testing, not a runtime fallback.
- Migration: `supabase/migrations/202609270001_compact_context_v2.sql` (CREATED, NOT APPLIED). The database reservation function pins the prompt version and template hash, so application rollout requires this separately reviewed migration. It adds the V2 non-null projection-hash constraint and replaces the reservation function with the same authorization, source, snapshot, lifecycle, and idempotency guards. A normalization test proves only contract pins and constraint name change. No historical rows or migrations are rewritten.

## Projection policy

Provider data omits timing evidence dictionaries/quotes/offsets, structured timing original text duplicated by the confirmed tuple, resolved exception and downgrade bookkeeping, redundant requirement code/revision, document_id, and null timing fields. It retains state, trigger, relation, value (including zero), unit, calendar basis, full requirement statement and revision UUID, mandatory status, obligation type, priority, stage assignment/sequence, fixed stages, all dependency edges, and exact document-version/chunk/canonical-locator references. Role and department codes remain useful personalization labels alongside output-required employee fields.

Ambiguous timing remains blocked by preflight; diagnostic projections preserve its original text without inventing a deadline. Null employee location and stage assignment retain their existing meanings.

Additional excerpts: ZERO. Approved structured RRM is the generation authority; no document bodies, chunk collections, or extra evidence text are sent. There is no excerpt truncation path or batching. Unrelated requirements are eliminated by existing deterministic applicability before projection.

The authoritative snapshot construction, canonical hash, reservation payload and validator input are unchanged: original timing text and full evidence spans, source provenance and hashes, existing bounded source excerpts, applicability, exception/downgrade evidence, matrix revisions/lock/hash, stage-set version and definitions, and dependencies remain server-side. This change does not expand the existing snapshot into whole-document storage.

## Output and trust boundary

The schema compressor uses shorter shared scalar identifiers and removes duplicated mapping prose. Reconstruction tests compare the entire compact contract with the validator's schema, including types, enums, bounds, required fields and unknown-field prohibitions. Generation tests still parse valid onboarding-plan/1.0.0 output.

System instructions remain separate from organization data. Markup delimiters in data are escaped. Regression tests show injection-like text cannot change the trusted system message, rules or template hash, and explicitly retain the prohibition on source-driven approval, VERIFIED status, or Python validator/JEV changes. This verifies construction and downstream safeguards, not live-model resistance.

## Measurements

UTF-8 bytes, same synthetic snapshot per before/after pair, fixed generation request UUID, Groq HTTPX JSON serialization, model openai/gpt-oss-20b, temperature 0.1, max output tokens 8192, no retry. The controlled fixture has six requirements, eight edges and five stages. The timing-heavy variant gives all six requirements a structured deadline with six exact evidence spans each. These are deterministic serialization fixtures, not claims of production generation quality.

| Fixture | Component | Before | After | Bytes saved | Reduction |
|---|---|---:|---:|---:|---:|
| Controlled | Frozen snapshot | 8,157 | 8,157 | 0 | 0% |
| Controlled | Projection | 5,931 | 4,479 | 1,452 | 24.48% |
| Controlled | System message | 8,763 | 7,664 | 1,099 | 12.54% |
| Controlled | User message | 6,071 | 4,619 | 1,452 | 23.92% |
| Controlled | Serialized request | 16,644 | 13,925 | 2,719 | 16.34% |
| Timing-heavy | Frozen snapshot | 12,735 | 12,735 | 0 | 0% |
| Timing-heavy | Projection | 10,503 | 5,235 | 5,268 | 50.16% |
| Timing-heavy | System message | 8,763 | 7,664 | 1,099 | 12.54% |
| Timing-heavy | User message | 10,643 | 5,375 | 5,268 | 49.50% |
| Timing-heavy | Serialized request | 21,780 | 14,789 | 6,991 | 32.10% |

Reproduce from services/api with PYTHONPATH=. using `D:/SkillSprint-AI/tmp/phase4d-py312/Scripts/python.exe tests/test_compact_context_v2.py`. No provider is called by this script.

## Guards and limitations

- Projection: 24,576 UTF-8 bytes after sentinel escaping. System plus user messages: 32,768 bytes, now including the separating newline. PromptPack exposes separate message byte counts.
- Exact serialized body: 24,576 bytes in both Groq and Gemini, including format-retry text and JSON escaping. The checked encoded bytes are the transmitted bytes; adapter checks also honor within_budget. Overflow raises GENERATION_PROJECTION_TOO_LARGE before HTTP transport. Existing locator maximum remains 240 characters.
- No requirement-count cap: tests admit 13 requirements and prove 100 remain in an oversized projection, which fails rather than dropping any.
- No available tiktoken/tokenizers/transformers installation or configured-model tokenizer was found. No tokenizer dependency added. estimated_input_tokens is ceil(combined message UTF-8 bytes / 4), explicitly a rough estimate, not a token limit or live token savings. Byte guards are authoritative.
- H12 remains deferred: requirement-level structured deadline output needs a separately versioned output-schema change. Existing MANUAL_REVIEW behavior remains tested. No Phase 4/5 redesign.
- Future batching could address contexts exceeding the aggregate cap, but must preserve full requirement/dependency coverage and audit provenance; not implemented here.
- SQL migration checks are static; no live database migration/RLS validation was performed.

## Validation and next step

Focused suite: 238 passed, covering compact context, generation, Phase 7 and Phase 5 validator/JEV. Full backend: 538 passed with external socket connections blocked (loopback allowed for Windows asyncio). One existing Starlette/httpx deprecation warning. Test environment: tmp/phase4d-py312; the root .venv mixes Python 3.14 with a CPython 3.12 pydantic_core binary and was not modified.

Live provider calls: 0. Tests use fake providers/in-memory HTTP transports. No deployment, commit, push, migration application, vector retrieval, or NaraRouter integration.

Exact next NaraRouter step: in a separate change, define and implement a GenerationProvider adapter consuming the existing V2 PromptPack, with offline request/response, size, error and retry contract tests first. Add separately reviewed provider configuration and database provider/model allow-list provenance; keep retrieval and projection provider-neutral. Live smoke testing requires separate authorization and credentials.
