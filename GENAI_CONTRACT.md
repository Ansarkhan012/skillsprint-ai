# GenAI Structured Output Contract

Status: **PLANNED**. This contract is provider-neutral and intended for Pydantic plus JSON Schema validation. The model returns JSON only; all scores and final verification statuses are computed outside GenAI.

## Envelope

```json
{
  "schema_version": "1.0.0",
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

`generation_request_id` is supplied by the application and must echo exactly. Employee context is minimized; names and sensitive personal data are unnecessary. Allowed experience values are `BEGINNER`, `INTERMEDIATE`, `ADVANCED`.

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
| Completion criterion | `criterion_id`, `description`, `evidence_type`, `threshold` |

Quiz `question_type` is `SINGLE_CHOICE`, `MULTIPLE_RESPONSE`, `TRUE_FALSE`, or `SCENARIO`. Options have stable `option_id` and `text`; correctness is represented only through `correct_answer_ids`. A rubric row has `criterion_id`, `criterion`, `weight_percent`, `expected_performance`, and `pass_condition`; weights must total 100.

## Explanations and unsupported requests

Explanations are required for quiz answers and whenever a non-obvious sequence or role exception is applied. They are instructional text, never validation evidence. If grounding is insufficient, the model adds:

```json
{"request_path":"plan.stages[0]","topic":"expense approval","reason_code":"NO_APPROVED_SOURCE","detail":"No provided requirement or source supports this topic."}
```

Allowed reason codes: `NO_APPROVED_SOURCE`, `AMBIGUOUS_SOURCE`, `CONFLICTING_SOURCES`, `MISSING_ROLE_REQUIREMENT`. The model must omit unsupported factual content rather than invent it.

## Application-owned metadata

The service wraps validated provider output with `provider`, `model`, `prompt_version_id`, `generation_config`, `rrm_revision_id`, `source_snapshot_id`, timestamps, token/latency metadata, raw-response hash, and retry lineage. The model cannot set JEV status, validation metrics, approval state, audit identity, or policy precedence.

## Schema rules

- Reject unknown top-level/control fields (`extra="forbid"`).
- Enforce lengths, enum values, UUID/ID formats, bounded collections, unique IDs, and reference integrity.
- Reject HTML/scripts, external URLs unless explicitly allowed, and model-emitted secrets/tool directives.
- Enforce stage/module ordering numerically and prerequisite references acyclically in deterministic validation.
- Version breaking schema changes with a major version and retain readers for stored historical outputs.
