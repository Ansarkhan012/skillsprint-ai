"""Versioned Phase 4B provider output. Valid structure is never verification."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Text = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
ShortText = Annotated[str, Field(min_length=1, max_length=240, pattern=r"\S")]
Refs = Annotated[tuple[UUID, ...], Field(min_length=1, max_length=100)]


class SourceRef(OutputModel):
    document_version_id: UUID
    chunk_id: UUID
    locator: ShortText


Sources = Annotated[tuple[SourceRef, ...], Field(min_length=1, max_length=100)]


class Grounded(OutputModel):
    requirement_ids: Refs
    source_refs: Sources


class Objective(Grounded):
    objective_id: UUID
    statement: Text


class KeyConcept(Grounded):
    concept_id: UUID
    statement: Text


class Activity(Grounded):
    activity_id: UUID
    title: ShortText
    instructions: Text
    expected_outcome: Text


class ChecklistItem(Grounded):
    checklist_item_id: UUID
    activity: Text
    required: bool
    due_stage_id: UUID
    responsible_role: ShortText


class Task(Grounded):
    task_id: UUID
    description: Text
    expected_outcome: Text
    completion_criteria: tuple[ShortText, ...] = Field(min_length=1, max_length=20)
    difficulty: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"]
    due_stage_id: UUID


class Scenario(Grounded):
    scenario_id: UUID
    prompt: Text
    expected_actions: tuple[ShortText, ...] = Field(min_length=1, max_length=20)
    success_criteria: tuple[ShortText, ...] = Field(min_length=1, max_length=20)


class QuizOption(OutputModel):
    option_id: UUID
    text: ShortText


class Quiz(Grounded):
    quiz_id: UUID
    question_type: Literal["SINGLE_CHOICE", "MULTIPLE_RESPONSE", "TRUE_FALSE", "SCENARIO"]
    question: Text
    options: tuple[QuizOption, ...] = Field(min_length=2, max_length=12)
    correct_answer_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    explanation: Text
    difficulty: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"]

    @model_validator(mode="after")
    def answers_are_options(self):
        options = {option.option_id for option in self.options}
        if not set(self.correct_answer_ids).issubset(options):
            raise ValueError("UNKNOWN_QUIZ_OPTION")
        return self


class RubricRow(Grounded):
    criterion_id: UUID
    criterion: ShortText
    weight_percent: int = Field(ge=0, le=100)
    expected_performance: Text
    pass_condition: Text


class Assessment(Grounded):
    assessment_id: UUID
    assessment_type: Literal["KNOWLEDGE", "PRACTICAL", "ROLE"]
    title: ShortText
    instructions: Text
    rubric: tuple[RubricRow, ...] = Field(min_length=1, max_length=20)
    pass_condition: Text

    @model_validator(mode="after")
    def rubric_weights(self):
        if sum(row.weight_percent for row in self.rubric) != 100:
            raise ValueError("INVALID_RUBRIC_WEIGHT")
        return self


class CompletionCriterion(Grounded):
    criterion_id: UUID
    description: Text
    evidence_type: ShortText
    threshold: ShortText


class Module(Grounded):
    module_id: UUID
    title: ShortText
    purpose: Text
    category: ShortText
    mandatory: bool
    priority: Literal["LOW", "MEDIUM", "HIGH"]
    difficulty: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"]
    estimated_minutes: int = Field(ge=1, le=10080)
    prerequisite_module_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    learning_objectives: tuple[Objective, ...] = Field(default=(), max_length=100)
    key_concepts: tuple[KeyConcept, ...] = Field(default=(), max_length=100)
    activities: tuple[Activity, ...] = Field(default=(), max_length=100)
    checklist_items: tuple[ChecklistItem, ...] = Field(default=(), max_length=100)
    tasks: tuple[Task, ...] = Field(default=(), max_length=100)
    scenarios: tuple[Scenario, ...] = Field(default=(), max_length=100)
    quizzes: tuple[Quiz, ...] = Field(default=(), max_length=100)
    assessments: tuple[Assessment, ...] = Field(default=(), max_length=100)
    completion_criteria: tuple[CompletionCriterion, ...] = Field(default=(), max_length=100)


class Stage(OutputModel):
    stage_id: UUID
    label: ShortText
    sequence: int = Field(ge=1)
    target_start_day: int = Field(ge=0)
    target_end_day: int = Field(ge=0)
    modules: tuple[Module, ...] = Field(default=(), max_length=100)


class Plan(OutputModel):
    title: ShortText
    summary: Text
    stages: tuple[Stage, ...] = Field(min_length=1, max_length=100)


class InsufficientInformation(OutputModel):
    request_path: ShortText
    topic: ShortText
    requirement_id: UUID | None = None
    reason_code: Literal["NO_APPROVED_SOURCE", "AMBIGUOUS_SOURCE", "CONFLICTING_SOURCES", "MISSING_ROLE_REQUIREMENT"]
    detail: Text


class OutputEmployeeContext(OutputModel):
    employee_id: UUID
    role_id: UUID
    department_id: UUID
    experience_level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"]
    location_code: str | None = Field(default=None, max_length=80)
    joining_date: date


class OnboardingPlan(OutputModel):
    schema_version: Literal["onboarding-plan/1.0.0"]
    generation_request_id: UUID
    employee_context: OutputEmployeeContext
    plan: Plan
    insufficient_information: tuple[InsufficientInformation, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def unique_generated_ids(self):
        seen: set[UUID] = set()
        for stage in self.plan.stages:
            for module in stage.modules:
                nodes = [module.module_id]
                for field, key in (("learning_objectives", "objective_id"), ("key_concepts", "concept_id"),
                                   ("activities", "activity_id"), ("checklist_items", "checklist_item_id"),
                                   ("tasks", "task_id"), ("scenarios", "scenario_id"),
                                   ("quizzes", "quiz_id"), ("assessments", "assessment_id"),
                                   ("completion_criteria", "criterion_id")):
                    for item in getattr(module, field):
                        nodes.append(getattr(item, key))
                        if field == "quizzes":
                            nodes.extend(option.option_id for option in item.options)
                        if field == "assessments":
                            nodes.extend(row.criterion_id for row in item.rubric)
                for node in nodes:
                    if node in seen:
                        raise ValueError("DUPLICATE_GENERATED_ID")
                    seen.add(node)
        return self
