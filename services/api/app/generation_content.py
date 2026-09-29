"""Phase 4D content-only generation (phase4d-content-only/4.0.0).

The backend owns every mechanical field of onboarding-plan/1.0.0: plan/stage structure,
one module per requirement in its approved stage, all generated UUIDs, requirement_ids,
source_refs, prerequisite wiring, due stages, mandatory/priority, quiz option ids and the
correct answer id. The model returns only prose (plus a duration estimate and the index of
the correct quiz option), keyed by backend-provided requirement keys R1..Rn.

Source rule (4.0.0): every node of a requirement's module cites exactly that requirement
and all of its frozen evidence references (deduplicated by document version, chunk and
locator, in snapshot order). The model never selects sources, so unknown or
wrongly-owned source keys cannot occur.
"""

from typing import Annotated
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .generation_models import GenerationInputSnapshot
from .rrm_rules import canonical_json

CONTENT_V400 = "phase4d-content-only/4.0.0"   # historical; reproducible, never live-selected
CONTENT_V401 = "phase4d-content-only/4.0.1"   # historical; reproducible, never live-selected
CONTENT_V410 = "phase4d-content-only/4.1.0"   # current intended live contract (demo-minimal)
CURRENT_CONTENT_VERSION = CONTENT_V410
CONTENT_PROMPT_VERSIONS = frozenset({CONTENT_V400, CONTENT_V401, CONTENT_V410})
CONTENT_PROJECTION_VERSION = "generation-content/4.0.0"  # 4.0.0 and 4.0.1 projection
CONTENT_PROJECTION_VERSIONS = {CONTENT_V400: CONTENT_PROJECTION_VERSION, CONTENT_V401: CONTENT_PROJECTION_VERSION,
                               CONTENT_V410: "generation-content/4.1.0"}
# 4.1.0: fields the model no longer writes are filled by Python from trusted requirement data.
DEFAULT_MODULE_MINUTES = 30  # backend default estimate; not a policy fact
OUTPUT_SCHEMA_VERSION = "onboarding-plan/1.0.0"
QUIZ_OPTION_COUNT = 3
# Fixed namespace for backend-assigned ids; changing it changes every generated id.
ID_NAMESPACE = UUID("0f4a7c2e-9d31-5b8e-a6c4-3e2d1f0b9a57")

# Same bounds as OnboardingPlan's ShortText / Text.
Short = Annotated[str, Field(min_length=1, max_length=240, pattern=r"\S")]
Prose = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


def _distinct_options(options: tuple[str, ...]) -> None:
    # Business rule: a single-choice quiz whose options repeat has no well-defined answer.
    if len({" ".join(option.lower().split()) for option in options}) != len(options):
        raise ValueError("DUPLICATE_QUIZ_OPTION")


class RequirementContent(BaseModel):
    """4.0.1: everything the model writes for one requirement; nothing mechanical.

    Bounds equal the final OnboardingPlan contract, except two intentional content-generation
    bounds: exactly 3 quiz options (the backend maps correct_option_index 0-2 to option ids)
    and distinct options (business rule). 4.0.0's narrower minutes (5-480) and criteria
    (max 3) were accidental: they could reject plans the final contract accepts.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    module_title: Short                                                   # Module.title ShortText
    module_purpose: Prose                                                 # Module.purpose Text
    estimated_minutes: int = Field(ge=1, le=10080)                         # Module.estimated_minutes
    objective: Prose                                                      # Objective.statement Text
    task_description: Prose                                               # Task.description Text
    task_expected_outcome: Prose                                          # Task.expected_outcome Text
    task_completion_criteria: tuple[Short, ...] = Field(min_length=1, max_length=20)  # Task bounds
    checklist_activity: Prose                                             # ChecklistItem.activity Text
    quiz_question: Prose                                                  # Quiz.question Text
    quiz_options: tuple[Short, ...] = Field(min_length=QUIZ_OPTION_COUNT, max_length=QUIZ_OPTION_COUNT)
    correct_option_index: int = Field(ge=0, le=QUIZ_OPTION_COUNT - 1)
    quiz_explanation: Prose                                               # Quiz.explanation Text

    @model_validator(mode="after")
    def distinct_options(self):
        _distinct_options(self.quiz_options)
        return self


class ContentResponse(BaseModel):
    """4.0.1 response: plan prose plus one entry per backend-issued requirement key."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    plan_title: Short                                                     # Plan.title ShortText
    plan_summary: Prose                                                   # Plan.summary Text
    requirements: dict[str, RequirementContent]


class RequirementContentV400(BaseModel):
    """4.0.0 item contract, frozen byte-for-byte: its JSON schema is bound into the 4.0.0 hash."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    module_title: Short
    module_purpose: Prose
    estimated_minutes: int = Field(ge=5, le=480)
    objective: Prose
    task_description: Prose
    task_expected_outcome: Prose
    task_completion_criteria: tuple[Short, ...] = Field(min_length=1, max_length=3)
    checklist_activity: Prose
    quiz_question: Prose
    quiz_options: tuple[Short, ...] = Field(min_length=QUIZ_OPTION_COUNT, max_length=QUIZ_OPTION_COUNT)
    correct_option_index: int = Field(ge=0, le=QUIZ_OPTION_COUNT - 1)
    quiz_explanation: Prose

    @model_validator(mode="after")
    def distinct_options(self):
        _distinct_options(self.quiz_options)
        return self


class ContentResponseV400(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    plan_title: Short
    plan_summary: Prose
    requirements: dict[str, RequirementContentV400]


def _text(max_length: int):
    return Annotated[str, Field(min_length=1, max_length=max_length, pattern=r"\S")]


class RequirementContentV410(BaseModel):
    """4.1.0: the smallest useful per-requirement content, 7 fields, all required.

    The provider JSON schema is generated from this model (identical bounds). Limits are short
    on purpose and all within OnboardingPlan's ShortText/Text bounds. The one rule JSON Schema
    cannot express exactly: options must differ ignoring case and spacing (the schema carries
    uniqueItems for exact duplicates); a quiz with repeated options has no well-defined answer.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    module_title: _text(120)                                   # -> Module.title
    objective: _text(400)                                      # -> Objective.statement
    task: _text(400)                                           # -> Task.description
    checklist: _text(240)                                      # -> ChecklistItem.activity
    quiz_question: _text(400)                                  # -> Quiz.question
    quiz_options: tuple[_text(160), ...] = Field(min_length=QUIZ_OPTION_COUNT, max_length=QUIZ_OPTION_COUNT,
                                                 json_schema_extra={"uniqueItems": True})
    correct_option_index: int = Field(ge=0, le=QUIZ_OPTION_COUNT - 1)

    @model_validator(mode="after")
    def distinct_options(self):
        _distinct_options(self.quiz_options)
        return self


class ContentResponseV410(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    plan_title: _text(120)                                     # -> Plan.title
    requirements: dict[str, RequirementContentV410]


CONTENT_ITEM_MODELS = {CONTENT_V400: RequirementContentV400, CONTENT_V401: RequirementContent,
                       CONTENT_V410: RequirementContentV410}
CONTENT_RESPONSE_MODELS = {CONTENT_V400: ContentResponseV400, CONTENT_V401: ContentResponse,
                           CONTENT_V410: ContentResponseV410}


def _module_text(item, req) -> dict:
    """Uniform module prose. 4.0.x items carry every field; for 4.1.0 the fields the model no
    longer writes are derived deterministically from the approved requirement (no new facts)."""
    if isinstance(item, RequirementContentV410):
        return {"title": item.module_title, "purpose": req.statement[:4000], "minutes": DEFAULT_MODULE_MINUTES,
                "objective": item.objective, "task": item.task,
                "expected_outcome": f"Requirement {req.code} is completed and recorded.",
                "criteria": [f"Completion of {req.code} is recorded"], "checklist": item.checklist,
                "question": item.quiz_question, "options": item.quiz_options, "index": item.correct_option_index,
                "explanation": f"The correct option follows approved requirement {req.code}."}
    return {"title": item.module_title, "purpose": item.module_purpose, "minutes": item.estimated_minutes,
            "objective": item.objective, "task": item.task_description, "expected_outcome": item.task_expected_outcome,
            "criteria": list(item.task_completion_criteria), "checklist": item.checklist_activity,
            "question": item.quiz_question, "options": item.quiz_options, "index": item.correct_option_index,
            "explanation": item.quiz_explanation}


def plan_summary(content, snapshot: GenerationInputSnapshot) -> str:
    if hasattr(content, "plan_summary"):
        return content.plan_summary
    return (f"Onboarding plan for role {snapshot.employee.role_code} covering "
            f"{len(snapshot.requirements)} approved requirements across {len(snapshot.stage_set.items)} stages.")


def requirement_keys(snapshot: GenerationInputSnapshot) -> dict[str, object]:
    """R1..Rn in frozen snapshot order; the only identifiers the model ever sees or returns."""
    return {"R" + str(index): req for index, req in enumerate(snapshot.requirements, 1)}


def generated_id(request_id: UUID, owner: UUID, kind: str, index: int = 0) -> str:
    """Deterministic and collision-safe: UUIDv5 of run, owning requirement, node kind and index.
    Distinct runs never share ids; within a run every (requirement, kind, index) is unique."""
    return str(uuid5(ID_NAMESPACE, f"{request_id}/{owner}/{kind}/{index}"))


def source_refs(req) -> list[dict]:
    seen, refs = set(), []
    for ref in req.evidence:
        item = {"document_version_id": str(ref.document_version_id), "chunk_id": str(ref.chunk_id),
                "locator": canonical_json(ref.locator)}
        identity = (item["document_version_id"], item["chunk_id"], item["locator"])
        if identity not in seen:
            seen.add(identity)
            refs.append(item)
    if not refs or len(refs) > 100:  # OnboardingPlan Sources bounds; preflight guarantees evidence
        raise ValueError("SOURCE_REFS_OUT_OF_BOUNDS")
    return refs


def module_layout(snapshot: GenerationInputSnapshot) -> list[list[object]]:
    """Requirements per stage, each stage in dependency (topological) order.

    Staged requirements go to their approved stage. An unstaged requirement goes to the
    earliest stage not before any of its prerequisites. Ties keep snapshot order.
    """
    stages = [stage.stage_definition_id for stage in snapshot.stage_set.items]
    index = {stage: position for position, stage in enumerate(stages)}
    order = {req.revision_id: position for position, req in enumerate(snapshot.requirements)}
    prerequisites = {req.revision_id: [p for d, p in snapshot.dependencies if d == req.revision_id]
                     for req in snapshot.requirements}
    remaining = {req.revision_id: req for req in snapshot.requirements}
    placed: dict[UUID, int] = {}
    sequence = []
    while remaining:  # Kahn's algorithm; a cycle is an input error the preflight blocks
        ready = [rid for rid in remaining if all(p in placed or p not in remaining and p not in order
                                                 for p in prerequisites[rid])]
        if not ready:
            raise ValueError("DEPENDENCY_CYCLE")
        rid = min(ready, key=lambda item: order[item])
        req = remaining.pop(rid)
        if req.stage_definition_id is not None:
            if req.stage_definition_id not in index:
                raise ValueError("RRM_STAGE_NOT_IN_ACTIVE_SET")
            placed[rid] = index[req.stage_definition_id]
        else:
            placed[rid] = max([placed[p] for p in prerequisites[rid] if p in placed] or [0])
        sequence.append(req)
    layout = [[] for _ in stages]
    for req in sequence:  # topological order is preserved inside each stage
        layout[placed[req.revision_id]].append(req)
    return layout


def assemble_plan(content: ContentResponse, snapshot: GenerationInputSnapshot, request_id: UUID) -> dict:
    """Deterministically build the complete onboarding-plan/1.0.0 object from model prose."""
    keys = {req.revision_id: key for key, req in requirement_keys(snapshot).items()}
    module_ids = {req.revision_id: generated_id(request_id, req.revision_id, "module") for req in snapshot.requirements}
    experience = snapshot.employee.experience
    stages = []
    for stage, requirements in zip(snapshot.stage_set.items, module_layout(snapshot)):
        modules = []
        for req in requirements:
            text = _module_text(content.requirements[keys[req.revision_id]], req)
            rid, owner = str(req.revision_id), req.revision_id
            grounded = {"requirement_ids": [rid], "source_refs": source_refs(req)}
            stage_id = str(stage.stage_definition_id)
            option_ids = [generated_id(request_id, owner, "quiz_option", n) for n in range(QUIZ_OPTION_COUNT)]
            modules.append({
                **grounded, "module_id": module_ids[owner], "title": text["title"],
                "purpose": text["purpose"], "category": req.obligation_type.replace("_", " ").title(),
                "mandatory": req.mandatory, "priority": req.priority, "difficulty": experience,
                "estimated_minutes": text["minutes"],
                "prerequisite_module_ids": [module_ids[p] for d, p in snapshot.dependencies
                                            if d == owner and p in module_ids],
                "learning_objectives": [{**grounded, "objective_id": generated_id(request_id, owner, "objective"),
                                         "statement": text["objective"]}],
                "key_concepts": [], "activities": [], "scenarios": [], "assessments": [], "completion_criteria": [],
                "checklist_items": [{**grounded, "checklist_item_id": generated_id(request_id, owner, "checklist"),
                                     "activity": text["checklist"], "required": req.mandatory,
                                     "due_stage_id": stage_id, "responsible_role": "Employee"}],
                "tasks": [{**grounded, "task_id": generated_id(request_id, owner, "task"),
                           "description": text["task"], "expected_outcome": text["expected_outcome"],
                           "completion_criteria": list(text["criteria"]),
                           "difficulty": experience, "due_stage_id": stage_id}],
                "quizzes": [{**grounded, "quiz_id": generated_id(request_id, owner, "quiz"),
                             "question_type": "SINGLE_CHOICE", "question": text["question"],
                             "options": [{"option_id": option_id, "text": option}
                                         for option_id, option in zip(option_ids, text["options"])],
                             "correct_answer_ids": [option_ids[text["index"]]],
                             "explanation": text["explanation"], "difficulty": experience}]})
        stages.append({"stage_id": str(stage.stage_definition_id), "label": stage.label, "sequence": stage.sequence,
                       "target_start_day": stage.start_day, "target_end_day": stage.end_day, "modules": modules})
    employee = snapshot.employee
    return {"schema_version": OUTPUT_SCHEMA_VERSION, "generation_request_id": str(request_id),
            "employee_context": {"employee_id": str(employee.employee_id), "role_id": str(employee.role_id),
                                 "department_id": str(employee.department_id), "experience_level": experience,
                                 "location_code": employee.location_code,
                                 "joining_date": employee.joining_date.isoformat()},
            "plan": {"title": content.plan_title, "summary": plan_summary(content, snapshot), "stages": stages},
            "insufficient_information": []}
