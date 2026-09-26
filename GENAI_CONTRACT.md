# GenAI Structured Output Contract

Phase 5 now independently checks persisted UNVERIFIED output using `python-validator/1.0.0` and `jev/1.0.0`. It never calls GenAI. Findings/JEV/human dispositions are separate immutable records; no output is promoted in the Phase 4 tables. Structured timing that cannot be expressed by onboarding-plan/1.0.0 requires MANUAL_REVIEW. No output-model changes were made for Phase 5.

Status: **Phase 4 structural contract implemented; compact-exact-output recovery pending its additive migration.** Historical Gemini and Groq failed runs remain unchanged. A provider response may be rejected by strict local structural validation; no Phase 4 output is verified. Scores and final decisions belong to independent Phase 5 validation/JEV.

Implementation version: `onboarding-plan/1.0.0` in `services/api/app/generation_output.py`.
Current prompt version: `phase4d-compact-exact-output/1.0.0` in `services/api/app/generation_prompt.py`; historical prompt pins remain in earlier migrations. The specification factors repeated scalar constraints into shared definitions and marks optional fields with `?`; tests expand it back to the exact Pydantic JSON Schema. This is prompt notation only, not a change to output JSON. The template hash covers the version, specification, mappings, instructions, projection serializer version and byte bounds. Separate hashes pin the immutable full snapshot and unchanged bounded projection. The new reservation pin requires review/manual application of `202609260001_compact_generation_output_contract.sql` before use. Groq's final HTTPX-serialized body is bounded to 24,576 bytes, including escaping and format-retry instructions; overflow fails closed as `GENERATION_PROJECTION_TOO_LARGE`. This internal bound is not a documented provider quota. See `docs/PHASE4D_COMPACT_REQUEST_AUDIT.md` for offline measurements and evidence limits.

## Envelope

```json
{
  "schema_version": "onboarding-plan/1.0.0",
  "generation_request_id": "uuid",
  "employee_context": {
    "employee_id": "EMP-001",
    "role_id": "ROLE-CS",
    "department_id": "DEPT-SUPPORT",
    "experience_level": "BEGINNER",
    "location_code": "PK-KHI",
    "joining_date": "2026-09-28"
  },
  "plan": {
    "title": "Customer Support onboarding",
    "summary": "Plan purpose, not a policy claim.",
    "stages": []
  },
  "insufficient_information": []
}
```

`generation_request_id` is supplied by the application and must echo exactly. Actual
IDs are UUIDs from the frozen Phase 4A snapshot; symbolic IDs below illustrate only
the shape. Employee context is minimized; names and sensitive personal data are
unnecessary. Allowed experience values are `BEGINNER`, `INTERMEDIATE`, `ADVANCED`.

## Stage and module

```json
{
  "stage_id": "STAGE-WEEK-1",
  "label": "Week 1",
  "sequence": 20,
  "target_start_day": 2,
  "target_end_day": 7,
  "modules": [
    {
      "module_id": "uuid",
      "title": "Customer escalation process",
      "purpose": "Apply the approved escalation workflow.",
      "category": "ROLE_PROCESS",
      "mandatory": true,
      "priority": "HIGH",
      "difficulty": "BEGINNER",
      "estimated_minutes": 45,
      "requirement_ids": ["REQ-001"],
      "source_refs": [{"document_version_id":"uuid","chunk_id":"uuid","locator":"section 4.2"}],
      "prerequisite_module_ids": [],
      "learning_objectives": [],
      "key_concepts": [],
      "activities": [],
      "checklist_items": [],
      "tasks": [],
      "scenarios": [],
      "quizzes": [],
      "assessments": [],
      "completion_criteria": []
    }
  ]
}
```

IDs must be unique within a plan. Stages use configured IDs rather than free-form interpretation. Each mandatory module and every factual generated item requires at least one valid `requirement_id` and `source_ref`. `source_refs` may only use IDs included in the generation evidence pack.
The strict parser also requires the exact authoritative stage IDs, order, labels and day
windows. It verifies only the *presence and syntax* of supplied reference IDs and
source-version/chunk pairs; whether a cited source supports a claim belongs to Phase 5.

## Child item contracts

| Item | Required fields |
|---|---|
| Objective | `objective_id`, measurable `statement`, `requirement_ids`, `source_refs` |
| Key concept | `concept_id`, `statement`, `requirement_ids`, `source_refs` |
| Activity | `activity_id`, `title`, `instructions`, `expected_outcome`, `requirement_ids`, `source_refs` |
| Checklist | `checklist_item_id`, `activity`, `required`, `due_stage_id`, `responsible_role`, `requirement_ids`, `source_refs` |
| Task | `task_id`, `description`, `expected_outcome`, `completion_criteria[]`, `difficulty`, `due_stage_id`, `requirement_ids`, `source_refs` |
| Scenario | `scenario_id`, `prompt`, `expected_actions[]`, `success_criteria[]`, `requirement_ids`, `source_refs` |
| Quiz | `quiz_id`, `question_type`, `question`, `options[]`, `correct_answer_ids[]`, `explanation`, `difficulty`, `requirement_ids`, `source_refs` |
| Assessment | `assessment_id`, `assessment_type`, `title`, `instructions`, `rubric[]`, `pass_condition`, `requirement_ids`, `source_refs` |
| Completion criterion | `criterion_id`, `description`, `evidence_type`, `threshold`, `requirement_ids`, `source_refs` |

Quiz `question_type` is `SINGLE_CHOICE`, `MULTIPLE_RESPONSE`, `TRUE_FALSE`, or `SCENARIO`. Options have stable `option_id` and `text`; correctness is represented only through `correct_answer_ids`. A rubric row has `criterion_id`, `criterion`, `weight_percent`, `expected_performance`, and `pass_condition`; weights must total 100.
Rubric rows also carry their own `requirement_ids` and `source_refs`. Phase 4B
checks their structure and reference allowlist, not the factual correctness of
the criterion or the suitability of the score.

## Explanations and unsupported requests

Explanations are required for quiz answers and whenever a non-obvious sequence or role exception is applied. They are instructional text, never validation evidence. If grounding is insufficient, the model adds:

```json
{"request_path":"plan.stages[0]","topic":"expense approval","reason_code":"NO_APPROVED_SOURCE","detail":"No provided requirement or source supports this topic."}
```

Allowed reason codes: `NO_APPROVED_SOURCE`, `AMBIGUOUS_SOURCE`, `CONFLICTING_SOURCES`, `MISSING_ROLE_REQUIREMENT`. The model must omit unsupported factual content rather than invent it.

## Application-owned metadata

Phase 4C/4D stores a strict parsed `UNVERIFIED` output with provider/model, prompt/schema versions, template hash, immutable full input snapshot/hash, bounded projection hash, stage-set/version IDs, timestamps, attempt latency/outcome/response hashes, and retry lineage. Raw generated text is not retained by this path. Token usage is not yet supplied by the current provider adapter. The model cannot set JEV status, validation metrics, approval state, audit identity, or policy precedence.

Phase 4B has an in-memory `UNVERIFIED` result. Phase 4C/4D adds
UNVERIFIED persistence and metadata storage. The Gemini/Groq adapters take backend-only configuration and an
injected HTTP client; it does not create a client or make a request on import. Its
JSON-mode response is parsed again by strict local Pydantic validation. Trusted
system/rule instructions are separate from the user-role JSON data part. Source
text inside that data part is untrusted even if it contains apparent instructions.

Transient transport/5xx retry is capped at two backoffs per generation. A 429 fails without retry unless the provider supplies a numeric, bounded 0.5–2 second Retry-After; at most one delayed 429 retry is permitted within the same overall retry budget. One separate format/schema
regeneration is permitted using the unchanged frozen input. Phase 5 findings such as
missing coverage, unsupported claims, contradiction, timing and dependency errors
are never silently repaired into a verified result. All errors returned by the
service are safe application-owned codes; provider exception bodies and secrets are
not included.

## Schema rules

- Reject unknown top-level/control fields (`extra="forbid"`).
- Enforce lengths, enum values, UUID/ID formats, bounded collections, unique IDs, and reference integrity.
- Phase 4 rejects malformed JSON, schema-invalid types/fields/enums, mismatched request/employee/stage identity, and unknown or mismatched requirement/source references and locators. Structural error logs contain only bounded allowlisted path/type diagnostics, never generated values.
- Phase 5 independently checks factual support, coverage, unsafe content, timing/dependencies and JEV outcomes. Phase 4 structural parsing is not a factual approval.
- Version breaking schema changes with a major version and retain readers for stored historical outputs.
