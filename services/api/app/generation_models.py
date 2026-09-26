"""Phase 4A input contracts. No provider output or validation decision lives here."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .rrm_models import Entry, PrecedenceConfig, Requirement, Scope, Source, Timing


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmployeeGenerationContext(FrozenModel):
    employee_id: UUID
    profile_id: UUID | None = None
    role_id: UUID
    role_code: str
    department_id: UUID
    department_code: str
    experience: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"]
    location_code: str | None = None
    joining_date: date


class StageSetItem(FrozenModel):
    stage_definition_id: UUID
    code: str
    revision: int = Field(ge=1)
    label: str
    sequence: int = Field(ge=0)
    start_day: int = Field(ge=0)
    end_day: int = Field(ge=0)


class StageSet(FrozenModel):
    id: UUID
    code: str
    version: int = Field(ge=1)
    name: str
    status: Literal["ACTIVE", "INACTIVE"]
    items: tuple[StageSetItem, ...]


class EvidenceRef(FrozenModel):
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    locator: dict
    text_hash: str
    excerpt: str


class EffectiveRequirement(FrozenModel):
    revision_id: UUID
    code: str
    revision: int
    statement: str
    obligation_type: str
    mandatory: bool
    priority: str
    timing: Timing
    applicability: tuple[Scope, ...]
    stage_definition_id: UUID | None
    sequence: int
    dependencies: tuple[UUID, ...]
    exception_to: UUID | None
    downgrade_requested: bool
    downgrade_justification: str | None
    downgrade_evidence: dict | None
    evidence: tuple[EvidenceRef, ...]


class GenerationInputSnapshot(FrozenModel):
    context_schema_version: Literal["generation-context/1.0.0"] = "generation-context/1.0.0"
    as_of: datetime
    employee: EmployeeGenerationContext
    matrix_id: UUID
    matrix_revision: int
    matrix_edit: int
    matrix_lock_version: int
    matrix_snapshot_hash: str
    stage_set: StageSet
    requirements: tuple[EffectiveRequirement, ...]
    dependencies: tuple[tuple[UUID, UUID], ...]


class PreflightResult(FrozenModel):
    status: Literal["READY", "BLOCKED"]
    blocker_codes: tuple[str, ...] = ()
    snapshot: GenerationInputSnapshot | None = None
    input_hash: str | None = None


class ApprovedMatrixInput(FrozenModel):
    id: UUID
    role_id: UUID
    revision: int
    edit: int
    lock_version: int
    status: str
    snapshot_hash: str
    requirements: tuple[Requirement, ...]
    entries: tuple[Entry, ...]
    dependencies: tuple[tuple[UUID, UUID], ...]
    sources: dict[UUID, Source]
    configuration: PrecedenceConfig
    blocking_issues: tuple[str, ...] = ()
