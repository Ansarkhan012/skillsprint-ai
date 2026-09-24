"""Phase 3A.1 domain contracts. No routes, providers, or database credentials."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


# Explicit shared set, mirrored by SQL meaningful_reason; independent of locale/regex.
REASON_WHITESPACE = "".join(chr(n) for n in (
    *range(9, 14), *range(28, 33), 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288))


def meaningful_reason(value: str | None) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 2000 and bool(value.strip(REASON_WHITESPACE))


def validate_reason(value: str) -> str:
    if not meaningful_reason(value):
        raise ValueError("MEANINGFUL_REASON_REQUIRED")
    return value


Reason = Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(validate_reason)]

Text = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
Code = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(DomainModel):
    # Null is an explicit wildcard, never an application-role name.
    role_id: UUID | None = None
    department_id: UUID | None = None
    location_code: Annotated[str, Field(min_length=1, max_length=80, pattern=r"\S")] | None = None
    experience: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] | None = None


class EmployeeContext(DomainModel):
    role_id: UUID | None = None
    department_id: UUID | None = None
    location_code: str | None = None
    experience: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] | None = None


class EvidenceSpan(DomainModel):
    chunk_id: UUID
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    quote: Text

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("INVALID_EVIDENCE_RANGE")
        return self


class Timing(DomainModel):
    state: Literal["NOT_SPECIFIED", "AMBIGUOUS", "STRUCTURED"] = "NOT_SPECIFIED"
    original_text: Text | None = None
    trigger: Text | None = None
    relation: Literal["WITHIN", "BEFORE", "AFTER", "AT"] | None = None
    value: int | None = Field(default=None, ge=0, le=100000, strict=True)
    unit: Literal["HOUR", "DAY", "WEEK"] | None = None
    calendar_basis: Literal["CALENDAR", "BUSINESS"] | None = None
    evidence: dict[str, EvidenceSpan] = Field(default_factory=dict, max_length=7)

    @model_validator(mode="after")
    def complete(self):
        fields = (self.trigger, self.relation, self.value, self.unit, self.calendar_basis)
        if self.state == "STRUCTURED":
            if self.original_text is None or any(x is None for x in fields):
                raise ValueError("TIMING_INCOMPLETE")
            if set(self.evidence) != {"original_text", "trigger", "relation", "value", "unit", "calendar_basis"}:
                raise ValueError("TIMING_EVIDENCE_REQUIRED")
        elif any(x is not None for x in fields) or self.evidence:
            raise ValueError("TIMING_STRUCTURE_NOT_CONFIRMED")
        if (self.state == "NOT_SPECIFIED") != (self.original_text is None):
            raise ValueError("TIMING_TEXT_STATE_MISMATCH")
        return self


class Requirement(DomainModel):
    id: UUID
    code: Code
    revision: int = Field(ge=1, strict=True)
    predecessor_id: UUID | None = None
    statement: Text
    requirement_type: Literal["MUST_KNOW", "MUST_COMPLETE", "MUST_DEMONSTRATE", "MUST_ACKNOWLEDGE", "RECOMMENDED", "OPTIONAL", "NOT_APPLICABLE"]
    category: Code
    mandatory: bool = Field(strict=True)
    competency: Text | None = None
    assessment_required: bool = False
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    timing: Timing = Field(default_factory=Timing)
    scopes: tuple[Scope, ...] = Field(min_length=1, max_length=32)
    chunk_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    origin: Literal["MANUAL", "AI_CANDIDATE"] = "MANUAL"
    author_id: UUID

    @model_validator(mode="after")
    def integrity(self):
        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("DUPLICATE_SOURCE")
        if len({s.model_dump_json() for s in self.scopes}) != len(self.scopes):
            raise ValueError("DUPLICATE_SCOPE")
        if (self.revision == 1) != (self.predecessor_id is None) or self.predecessor_id == self.id:
            raise ValueError("INVALID_PREDECESSOR")
        must = self.requirement_type.startswith("MUST_")
        if self.mandatory != must:
            raise ValueError("MANDATORY_TYPE_MISMATCH")
        return self


class Source(DomainModel):
    """Construct only from repository joins, never a client evidence assertion."""
    chunk_id: UUID
    version_id: UUID
    document_id: UUID
    content: str
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_location: dict
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_status: str
    parse_status: str
    review_status: str
    effective_date: date
    expiry_date: date | None = None
    current_version_id: UUID | None


class MatrixStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class Entry(DomainModel):
    requirement_id: UUID
    sequence: int = Field(ge=0, le=100000, strict=True)
    stage_id: UUID | None = None
    exception_to: UUID | None = None
    downgrade_requested: bool = Field(default=False, strict=True)
    downgrade_justification: Reason | None = None
    downgrade_evidence: EvidenceSpan | None = None


class MatrixRevision(DomainModel):
    id: UUID
    role_id: UUID
    revision: int = Field(ge=1, strict=True)
    predecessor_id: UUID | None = None
    config_id: UUID
    status: MatrixStatus = MatrixStatus.DRAFT
    current_edit: int = Field(default=0, ge=0, strict=True)
    lock_version: int = Field(default=0, ge=0, strict=True)
    created_by: UUID
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: Reason | None = None
    admin_override: bool = False
    snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None

    @model_validator(mode="after")
    def lifecycle_metadata(self):
        if (self.revision == 1) != (self.predecessor_id is None) or self.predecessor_id == self.id:
            raise ValueError("INVALID_MATRIX_PREDECESSOR")
        if self.status != MatrixStatus.DRAFT and any(value is None for value in
                (self.submitted_by, self.submitted_at, self.snapshot_hash)):
            raise ValueError("MISSING_SUBMISSION_EVIDENCE")
        if self.status in {MatrixStatus.APPROVED, MatrixStatus.REJECTED, MatrixStatus.SUPERSEDED}:
            if self.decided_by is None or self.decided_at is None:
                raise ValueError("MISSING_REVIEW_EVIDENCE")
        if self.admin_override and not self.decision_reason:
            raise ValueError("OVERRIDE_REASON_REQUIRED")
        return self


class StageDefinition(DomainModel):
    id: UUID
    code: Code
    label: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    sequence: int = Field(ge=0, strict=True)
    start_day: int = Field(ge=0, strict=True)
    end_day: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def ordered_days(self):
        if self.end_day < self.start_day:
            raise ValueError("INVALID_STAGE_WINDOW")
        return self


class PrecedenceConfig(DomainModel):
    # Increasing rank means increasing authority. No implicit category mapping.
    ranks: dict[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")],
                Annotated[int, Field(strict=True, ge=0, le=1000)]] = Field(min_length=1, max_length=20)
    document_classes: dict[UUID, str]

    @model_validator(mode="after")
    def valid(self):
        if "ROLE_EXCEPTION" in self.ranks or any(type(v) is not int or not 0 <= v <= 1000 for v in self.ranks.values()):
            raise ValueError("INVALID_AUTHORITY_RANKS")
        if any(c not in self.ranks for c in self.document_classes.values()):
            raise ValueError("UNMAPPED_AUTHORITY_CLASS")
        return self


DEFAULT_AUTHORITY_RANKS = {"DEPARTMENT_SOP": 40, "COMPANY_POLICY": 30, "FAQ": 20, "INFORMAL_GUIDANCE": 10}
