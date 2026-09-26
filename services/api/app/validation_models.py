"""Independent Phase 5 evidence contract. No provider imports or output mutation."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from .rrm_models import Reason

VALIDATOR_VERSION = "python-validator/1.0.0"
JEV_VERSION = "jev/1.0.0"
Decision = Literal["VERIFIED", "VERIFIED_WITH_WARNING", "INCOMPLETE", "UNSUPPORTED",
                   "CONTRADICTORY", "MANUAL_REVIEW"]
FindingCode = Literal[
    "MISSING_MANDATORY_REQUIREMENT", "UNSUPPORTED_REQUIREMENT", "SOURCE_SUPPORT_MISSING",
    "SOURCE_REFERENCE_INVALID", "ROLE_APPLICABILITY_MISMATCH", "TIMING_MISMATCH",
    "TIMING_UNRESOLVED", "DEPENDENCY_MISSING", "DEPENDENCY_INVALID",
    "DEPENDENCY_ORDER_VIOLATION", "DEPENDENCY_CYCLE", "DUPLICATE_REQUIREMENT",
    "CONTRADICTION_DETECTED", "OUTDATED_SOURCE", "STALE_INPUT", "STRUCTURAL_REFERENCE_INVALID",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    locator: str = Field(max_length=240)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: FindingCode
    severity: Literal["WARNING", "ERROR", "REVIEW"]
    requirement_id: UUID | None = None
    location: str = Field(max_length=240)
    explanation: str = Field(max_length=300)
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=100)


class ValidationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    validator_version: Literal["python-validator/1.0.0"] = VALIDATOR_VERSION
    mandatory_total: int = Field(ge=0)
    mandatory_covered: int = Field(ge=0)
    structurally_valid: bool
    current_input: bool
    findings: tuple[Finding, ...] = Field(max_length=2000)


class JEVDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["jev/1.0.0"] = JEV_VERSION
    status: Decision
    rule: str
    reason_codes: tuple[FindingCode, ...]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["APPROVE", "REJECT", "REGENERATE", "OVERRIDE"]
    reason: Reason
