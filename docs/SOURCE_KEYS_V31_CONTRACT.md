# Source keys 3.1.0: OnboardingPlan vs NaraRouter response schema

Generated from `tests/test_contract_v31.py::contract_diff` (uncapped schemas; compact caps only lower maxItems/maxLength).
3.0.0 column = what failed runs received; 3.1.0 column = what NaraRouter/Groq now receive. Direct Gemini keeps the relaxed 3.0.0-style schema (it rejects bounds/patterns).

| Pydantic field | Rule | Pydantic | 3.0.0 provider | 3.1.0 provider | 3.1.0 verdict | Action |
|---|---|---|---|---|---|---|
| Activity | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Activity | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Activity | required | `["activity_id", "expected_outcome", "instructions", "requirement_ids", "source_refs", "title"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Activity.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Activity.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Activity.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Activity.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Activity.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Activity.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Activity.activity_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Activity.activity_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Activity.title | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Activity.title | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Activity.title | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Activity.title | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Activity.instructions | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Activity.instructions | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Activity.instructions | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Activity.instructions | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Activity.expected_outcome | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Activity.expected_outcome | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Activity.expected_outcome | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Activity.expected_outcome | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Assessment | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Assessment | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Assessment | required | `["assessment_id", "assessment_type", "instructions", "pass_condition", "requirement_ids", "rubric", "source_refs", "title"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Assessment.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Assessment.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Assessment.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Assessment.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Assessment.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Assessment.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Assessment.assessment_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Assessment.assessment_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Assessment.assessment_type | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Assessment.assessment_type | enum | `["KNOWLEDGE", "PRACTICAL", "ROLE"]` | `["KNOWLEDGE", "PRACTICAL", "ROLE"]` | `["KNOWLEDGE", "PRACTICAL", "ROLE"]` | MATCH | unchanged (already sent) |
| Assessment.title | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Assessment.title | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Assessment.title | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Assessment.title | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Assessment.instructions | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Assessment.instructions | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Assessment.instructions | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Assessment.instructions | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Assessment.rubric | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Assessment.rubric | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Assessment.rubric | maxItems | `20` | — | `20` | MATCH | added in 3.1.0 |
| Assessment.pass_condition | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Assessment.pass_condition | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Assessment.pass_condition | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Assessment.pass_condition | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| ChecklistItem | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| ChecklistItem | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| ChecklistItem | required | `["activity", "checklist_item_id", "due_stage_id", "required", "requirement_ids", "responsible_role", "source_refs"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| ChecklistItem.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| ChecklistItem.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| ChecklistItem.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| ChecklistItem.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| ChecklistItem.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| ChecklistItem.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| ChecklistItem.checklist_item_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| ChecklistItem.checklist_item_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| ChecklistItem.activity | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| ChecklistItem.activity | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| ChecklistItem.activity | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| ChecklistItem.activity | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| ChecklistItem.required | type | `"boolean"` | `"boolean"` | `"boolean"` | MATCH | unchanged (already sent) |
| ChecklistItem.due_stage_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| ChecklistItem.due_stage_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| ChecklistItem.responsible_role | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| ChecklistItem.responsible_role | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| ChecklistItem.responsible_role | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| ChecklistItem.responsible_role | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| CompletionCriterion | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| CompletionCriterion | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| CompletionCriterion | required | `["criterion_id", "description", "evidence_type", "requirement_ids", "source_refs", "threshold"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| CompletionCriterion.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| CompletionCriterion.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| CompletionCriterion.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| CompletionCriterion.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| CompletionCriterion.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| CompletionCriterion.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| CompletionCriterion.criterion_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| CompletionCriterion.criterion_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| CompletionCriterion.description | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| CompletionCriterion.description | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| CompletionCriterion.description | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| CompletionCriterion.description | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| CompletionCriterion.evidence_type | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| CompletionCriterion.evidence_type | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| CompletionCriterion.evidence_type | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| CompletionCriterion.evidence_type | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| CompletionCriterion.threshold | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| CompletionCriterion.threshold | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| CompletionCriterion.threshold | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| CompletionCriterion.threshold | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| InsufficientInformation | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| InsufficientInformation | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| InsufficientInformation | required | `["detail", "reason_code", "request_path", "topic"]` | `"all properties"` | `"all properties"` | STRICTER | unchanged (already sent) |
| InsufficientInformation.request_path | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| InsufficientInformation.request_path | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| InsufficientInformation.request_path | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| InsufficientInformation.request_path | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| InsufficientInformation.topic | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| InsufficientInformation.topic | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| InsufficientInformation.topic | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| InsufficientInformation.topic | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| InsufficientInformation.requirement_id| | type | `"string"` | `"null"` | `"string"` | MATCH | unchanged (already sent) |
| InsufficientInformation.requirement_id| | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| InsufficientInformation.requirement_id| | type | `"null"` | `"null"` | `"null"` | MATCH | unchanged (already sent) |
| InsufficientInformation.reason_code | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| InsufficientInformation.reason_code | enum | `["NO_APPROVED_SOURCE", "AMBIGUOUS_SOURCE", "CONFLICTING_SOURCES", "MISSING_ROLE_REQUIREMENT"]` | `["NO_APPROVED_SOURCE", "AMBIGUOUS_SOURCE", "CONFLICTING_SOURCES", "MISSING_ROLE_REQUIREMENT"]` | `["NO_APPROVED_SOURCE", "AMBIGUOUS_SOURCE", "CONFLICTING_SOURCES", "MISSING_ROLE_REQUIREMENT"]` | MATCH | unchanged (already sent) |
| InsufficientInformation.detail | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| InsufficientInformation.detail | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| InsufficientInformation.detail | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| InsufficientInformation.detail | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| KeyConcept | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| KeyConcept | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| KeyConcept | required | `["concept_id", "requirement_ids", "source_refs", "statement"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| KeyConcept.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| KeyConcept.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| KeyConcept.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| KeyConcept.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| KeyConcept.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| KeyConcept.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| KeyConcept.concept_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| KeyConcept.concept_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| KeyConcept.statement | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| KeyConcept.statement | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| KeyConcept.statement | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| KeyConcept.statement | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Module | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Module | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Module | required | `["category", "difficulty", "estimated_minutes", "mandatory", "module_id", "priority", "purpose", "requirement_ids", "source_refs", "title"]` | `"all properties"` | `"all properties"` | STRICTER | unchanged (already sent) |
| Module.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Module.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Module.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Module.module_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.module_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Module.title | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.title | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Module.title | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Module.title | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Module.purpose | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.purpose | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Module.purpose | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Module.purpose | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Module.category | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.category | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Module.category | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Module.category | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Module.mandatory | type | `"boolean"` | `"boolean"` | `"boolean"` | MATCH | unchanged (already sent) |
| Module.priority | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.priority | enum | `["LOW", "MEDIUM", "HIGH"]` | `["LOW", "MEDIUM", "HIGH"]` | `["LOW", "MEDIUM", "HIGH"]` | MATCH | unchanged (already sent) |
| Module.difficulty | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.difficulty | enum | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | MATCH | unchanged (already sent) |
| Module.estimated_minutes | type | `"integer"` | `"integer"` | `"integer"` | MATCH | unchanged (already sent) |
| Module.estimated_minutes | minimum | `1` | — | `1` | MATCH | added in 3.1.0 |
| Module.estimated_minutes | maximum | `10080` | — | `10080` | MATCH | added in 3.1.0 |
| Module.prerequisite_module_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.prerequisite_module_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.prerequisite_module_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Module.prerequisite_module_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Module.learning_objectives | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.learning_objectives | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.learning_objectives | minItems | — | `1` | `1` | STRICTER | unchanged (already sent) |
| Module.key_concepts | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.key_concepts | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.activities | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.activities | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.checklist_items | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.checklist_items | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.checklist_items | minItems | — | `1` | `1` | STRICTER | unchanged (already sent) |
| Module.tasks | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.tasks | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.tasks | minItems | — | `1` | `1` | STRICTER | unchanged (already sent) |
| Module.scenarios | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.scenarios | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.quizzes | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.quizzes | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.quizzes | minItems | — | `1` | `1` | STRICTER | unchanged (already sent) |
| Module.assessments | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.assessments | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Module.completion_criteria | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Module.completion_criteria | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Objective | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Objective | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Objective | required | `["objective_id", "requirement_ids", "source_refs", "statement"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Objective.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Objective.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Objective.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Objective.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Objective.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Objective.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Objective.objective_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Objective.objective_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Objective.statement | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Objective.statement | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Objective.statement | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Objective.statement | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| OutputEmployeeContext | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| OutputEmployeeContext | required | `["department_id", "employee_id", "experience_level", "joining_date", "role_id"]` | `"all properties"` | `"all properties"` | STRICTER | unchanged (already sent) |
| OutputEmployeeContext.employee_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.employee_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.role_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.role_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.department_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.department_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.experience_level | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.experience_level | enum | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.location_code| | type | `"string"` | `"null"` | `"string"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.location_code| | maxLength | `80` | — | `80` | MATCH | added in 3.1.0 |
| OutputEmployeeContext.location_code| | type | `"null"` | `"null"` | `"null"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.joining_date | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OutputEmployeeContext.joining_date | format | `"date"` | `"date"` | `"date"` | MATCH | unchanged (already sent) |
| Plan | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Plan | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Plan | required | `["stages", "summary", "title"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Plan.title | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Plan.title | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Plan.title | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Plan.title | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Plan.summary | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Plan.summary | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Plan.summary | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Plan.summary | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Plan.stages | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Plan.stages | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Plan.stages | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Quiz | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Quiz | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Quiz | required | `["correct_answer_ids", "difficulty", "explanation", "options", "question", "question_type", "quiz_id", "requirement_ids", "source_refs"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Quiz.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Quiz.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Quiz.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Quiz.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Quiz.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Quiz.quiz_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.quiz_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Quiz.question_type | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.question_type | enum | `["SINGLE_CHOICE", "MULTIPLE_RESPONSE", "TRUE_FALSE", "SCENARIO"]` | `["SINGLE_CHOICE", "MULTIPLE_RESPONSE", "TRUE_FALSE", "SCENARIO"]` | `["SINGLE_CHOICE", "MULTIPLE_RESPONSE", "TRUE_FALSE", "SCENARIO"]` | MATCH | unchanged (already sent) |
| Quiz.question | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.question | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Quiz.question | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Quiz.question | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Quiz.options | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Quiz.options | minItems | `2` | — | `2` | MATCH | added in 3.1.0 |
| Quiz.options | maxItems | `12` | — | `12` | MATCH | added in 3.1.0 |
| Quiz.correct_answer_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Quiz.correct_answer_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Quiz.correct_answer_ids | maxItems | `12` | — | `12` | MATCH | added in 3.1.0 |
| Quiz.correct_answer_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.correct_answer_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Quiz.explanation | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.explanation | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Quiz.explanation | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Quiz.explanation | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Quiz.difficulty | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Quiz.difficulty | enum | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | MATCH | unchanged (already sent) |
| QuizOption | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| QuizOption | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| QuizOption | required | `["option_id", "text"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| QuizOption.option_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| QuizOption.option_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| QuizOption.text | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| QuizOption.text | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| QuizOption.text | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| QuizOption.text | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| RubricRow | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| RubricRow | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| RubricRow | required | `["criterion", "criterion_id", "expected_performance", "pass_condition", "requirement_ids", "source_refs", "weight_percent"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| RubricRow.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| RubricRow.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| RubricRow.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| RubricRow.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| RubricRow.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| RubricRow.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| RubricRow.criterion_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| RubricRow.criterion_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| RubricRow.criterion | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| RubricRow.criterion | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| RubricRow.criterion | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| RubricRow.criterion | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| RubricRow.weight_percent | type | `"integer"` | `"integer"` | `"integer"` | MATCH | unchanged (already sent) |
| RubricRow.weight_percent | minimum | `0` | — | `0` | MATCH | added in 3.1.0 |
| RubricRow.weight_percent | maximum | `100` | — | `100` | MATCH | added in 3.1.0 |
| RubricRow.expected_performance | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| RubricRow.expected_performance | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| RubricRow.expected_performance | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| RubricRow.expected_performance | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| RubricRow.pass_condition | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| RubricRow.pass_condition | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| RubricRow.pass_condition | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| RubricRow.pass_condition | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Scenario | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Scenario | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Scenario | required | `["expected_actions", "prompt", "requirement_ids", "scenario_id", "source_refs", "success_criteria"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Scenario.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Scenario.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Scenario.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Scenario.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Scenario.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Scenario.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Scenario.scenario_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Scenario.scenario_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Scenario.prompt | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Scenario.prompt | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Scenario.prompt | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Scenario.prompt | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Scenario.expected_actions | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Scenario.expected_actions | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Scenario.expected_actions | maxItems | `20` | — | `20` | MATCH | added in 3.1.0 |
| Scenario.expected_actions[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Scenario.expected_actions[] | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Scenario.expected_actions[] | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Scenario.expected_actions[] | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Scenario.success_criteria | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Scenario.success_criteria | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Scenario.success_criteria | maxItems | `20` | — | `20` | MATCH | added in 3.1.0 |
| Scenario.success_criteria[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Scenario.success_criteria[] | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Scenario.success_criteria[] | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Scenario.success_criteria[] | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Stage | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Stage | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Stage | required | `["label", "sequence", "stage_id", "target_end_day", "target_start_day"]` | `"all properties"` | `"all properties"` | STRICTER | unchanged (already sent) |
| Stage.stage_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Stage.stage_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Stage.label | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Stage.label | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Stage.label | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Stage.label | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Stage.sequence | type | `"integer"` | `"integer"` | `"integer"` | MATCH | unchanged (already sent) |
| Stage.sequence | minimum | `1` | — | `1` | MATCH | added in 3.1.0 |
| Stage.target_start_day | type | `"integer"` | `"integer"` | `"integer"` | MATCH | unchanged (already sent) |
| Stage.target_start_day | minimum | `0` | — | `0` | MATCH | added in 3.1.0 |
| Stage.target_end_day | type | `"integer"` | `"integer"` | `"integer"` | MATCH | unchanged (already sent) |
| Stage.target_end_day | minimum | `0` | — | `0` | MATCH | added in 3.1.0 |
| Stage.modules | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Stage.modules | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Task | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| Task | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| Task | required | `["completion_criteria", "description", "difficulty", "due_stage_id", "expected_outcome", "requirement_ids", "source_refs", "task_id"]` | `"all properties"` | `"all properties"` | MATCH | unchanged (already sent) |
| Task.requirement_ids | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Task.requirement_ids | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Task.requirement_ids | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
| Task.requirement_ids[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.requirement_ids[] | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Task.source_refs | source_refs | SourceRef objects, 1–100 | `S# array` | `S#` array, 1–100, `^S[0-9]+$` | REPLACED | Python expands S# to SourceRef, then Pydantic checks it |
| Task.task_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.task_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| Task.description | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.description | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Task.description | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Task.description | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Task.expected_outcome | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.expected_outcome | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Task.expected_outcome | maxLength | `4000` | — | `4000` | MATCH | added in 3.1.0 |
| Task.expected_outcome | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Task.completion_criteria | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| Task.completion_criteria | minItems | `1` | — | `1` | MATCH | added in 3.1.0 |
| Task.completion_criteria | maxItems | `20` | — | `20` | MATCH | added in 3.1.0 |
| Task.completion_criteria[] | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.completion_criteria[] | minLength | `1` | — | `1` | MATCH | added in 3.1.0 |
| Task.completion_criteria[] | maxLength | `240` | — | `240` | MATCH | added in 3.1.0 |
| Task.completion_criteria[] | pattern | `"\\S"` | — | `"\\S"` | MATCH | added in 3.1.0 |
| Task.difficulty | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.difficulty | enum | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | `["BEGINNER", "INTERMEDIATE", "ADVANCED"]` | MATCH | unchanged (already sent) |
| Task.due_stage_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| Task.due_stage_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| OnboardingPlan | type | `"object"` | `"object"` | `"object"` | MATCH | unchanged (already sent) |
| OnboardingPlan | additionalProperties | `false` | `false` | `false` | MATCH | unchanged (already sent) |
| OnboardingPlan | required | `["employee_context", "generation_request_id", "plan", "schema_version"]` | `"all properties"` | `"all properties"` | STRICTER | unchanged (already sent) |
| OnboardingPlan.schema_version | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OnboardingPlan.schema_version | enum | `["onboarding-plan/1.0.0"]` | `["onboarding-plan/1.0.0"]` | `["onboarding-plan/1.0.0"]` | MATCH | unchanged (already sent) |
| OnboardingPlan.generation_request_id | type | `"string"` | `"string"` | `"string"` | MATCH | unchanged (already sent) |
| OnboardingPlan.generation_request_id | format | `"uuid"` | `"uuid"` | `"uuid"` | MATCH | unchanged (already sent) |
| OnboardingPlan.insufficient_information | type | `"array"` | `"array"` | `"array"` | MATCH | unchanged (already sent) |
| OnboardingPlan.insufficient_information | maxItems | `100` | — | `100` | MATCH | added in 3.1.0 |
