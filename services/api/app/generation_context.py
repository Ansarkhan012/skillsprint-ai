"""Deterministic Phase 4A preflight. Gemini never receives unresolved policy decisions."""

from datetime import datetime, time, timezone
from hashlib import sha256
from uuid import UUID

from pydantic import ValidationError
from fastapi import HTTPException

from .generation_models import (ApprovedMatrixInput, EffectiveRequirement, EmployeeGenerationContext,
                                EvidenceRef, GenerationInputSnapshot, PreflightResult, StageSet)
from .generation_repository import GenerationRepository
from .models import AppRole, Principal
from .rrm_models import EmployeeContext, MatrixStatus
from .rrm_rules import RRMError, canonical_json, complete_snapshot, source_eligible, utc_date


def blocked(code: str) -> PreflightResult:
    return PreflightResult(status="BLOCKED", blocker_codes=(code,))


def select_stage_set(stage_sets: tuple[StageSet, ...]) -> StageSet:
    active = [item for item in stage_sets if item.status == "ACTIVE"]
    if not active:
        raise RRMError("NO_ACTIVE_STAGE_SET")
    if len(active) != 1:
        raise RRMError("MULTIPLE_ACTIVE_STAGE_SETS")
    selected = active[0]
    items = selected.items
    if (not items or len({item.stage_definition_id for item in items}) != len(items)
            or len({item.code for item in items}) != len(items)
            or [item.sequence for item in items] != list(range(1, len(items) + 1))
            or any(item.end_day < item.start_day for item in items)
            or any(items[index].start_day < items[index - 1].start_day for index in range(1, len(items)))):
        raise RRMError("INVALID_STAGE_CONFIGURATION")
    return selected


def canonical_input(snapshot: GenerationInputSnapshot) -> str:
    return canonical_json(snapshot.model_dump(mode="json"))


def input_hash(snapshot: GenerationInputSnapshot) -> str:
    return sha256(canonical_input(snapshot).encode("utf-8")).hexdigest()


def prepare_generation_input(employee: EmployeeGenerationContext, matrix: ApprovedMatrixInput,
                             stage_sets: tuple[StageSet, ...], as_of: datetime) -> PreflightResult:
    """Pure, fail-closed preflight over trusted repository material.

    as_of is collapsed to the UTC eligibility date, not an unstable request timestamp.
    The caller must retrieve matrix/sources through the existing trusted Phase 3 RPC.
    """
    try:
        on_date = utc_date(as_of)
        if matrix.status != "APPROVED" or matrix.role_id != employee.role_id:
            return blocked("NO_APPROVED_MATRIX")
        if not employee.role_code or not employee.department_code:
            return blocked("MISSING_EMPLOYEE_CONTEXT")
        if matrix.blocking_issues:
            return blocked("UNRESOLVED_CONFLICT" if "CONFLICT" in matrix.blocking_issues
                           else "UNRESOLVED_REVIEW_ISSUE")
        stage_set = select_stage_set(stage_sets)
        context = EmployeeContext(role_id=employee.role_id, department_id=employee.department_id,
                                  location_code=employee.location_code, experience=employee.experience)
        selected = complete_snapshot(matrix.requirements, matrix.entries, matrix.sources, context, on_date,
                                     matrix.dependencies, status=MatrixStatus.APPROVED,
                                     blocking_issues=matrix.blocking_issues, configuration=matrix.configuration)
        effective_ids = {UUID(value) for value in selected["effective_ids"]}
        if not effective_ids:
            return blocked("NO_APPLICABLE_REQUIREMENTS")
        stage_ids = {item.stage_definition_id for item in stage_set.items}
        entries = {entry.requirement_id: entry for entry in matrix.entries}
        requirements = {req.id: req for req in matrix.requirements}
        for entry in matrix.entries:
            if entry.requirement_id in effective_ids and entry.stage_id is not None and entry.stage_id not in stage_ids:
                return blocked("RRM_STAGE_NOT_IN_ACTIVE_SET")
        effective = []
        for req_id in sorted(effective_ids, key=str):
            req, entry = requirements[req_id], entries[req_id]
            evidence = tuple(EvidenceRef(
                document_id=matrix.sources[chunk].document_id,
                document_version_id=matrix.sources[chunk].version_id,
                chunk_id=chunk,
                locator=matrix.sources[chunk].source_location,
                text_hash=matrix.sources[chunk].text_hash,
                excerpt=matrix.sources[chunk].content[:1200],
            ) for chunk in sorted(req.chunk_ids, key=str))
            effective.append(EffectiveRequirement(
                revision_id=req.id, code=req.code, revision=req.revision, statement=req.statement,
                obligation_type=req.requirement_type, mandatory=req.mandatory, priority=req.priority,
                timing=req.timing, applicability=req.scopes, stage_definition_id=entry.stage_id,
                sequence=entry.sequence,
                dependencies=tuple(sorted((prerequisite for dependent, prerequisite in matrix.dependencies
                                           if dependent == req_id), key=str)),
                exception_to=entry.exception_to, downgrade_requested=entry.downgrade_requested,
                downgrade_justification=entry.downgrade_justification,
                downgrade_evidence=entry.downgrade_evidence.model_dump(mode="json") if entry.downgrade_evidence else None,
                evidence=evidence,
            ))
        snapshot = GenerationInputSnapshot(
            as_of=datetime.combine(on_date, time.min, tzinfo=timezone.utc), employee=employee,
            matrix_id=matrix.id, matrix_revision=matrix.revision, matrix_edit=matrix.edit,
            matrix_lock_version=matrix.lock_version, matrix_snapshot_hash=matrix.snapshot_hash,
            stage_set=stage_set, requirements=tuple(effective),
            dependencies=tuple(sorted(((d, p) for d, p in matrix.dependencies if d in effective_ids),
                                      key=lambda edge: (str(edge[0]), str(edge[1])))),
        )
        return PreflightResult(status="READY", snapshot=snapshot, input_hash=input_hash(snapshot))
    except (RRMError, ValidationError, ValueError, KeyError) as exc:
        code = str(exc) if isinstance(exc, RRMError) else "INVALID_GROUND_TRUTH"
        return blocked({
            "TIMING_MANUAL_REVIEW": "AMBIGUOUS_TIMING",
            "APPLICABILITY_MANUAL_REVIEW": "MISSING_EMPLOYEE_CONTEXT",
            "PREREQUISITE_NOT_APPLICABLE": "INVALID_DEPENDENCY",
            "DEPENDENCY_OUTSIDE_MATRIX": "INVALID_DEPENDENCY",
            "DEPENDENCY_CYCLE": "INVALID_DEPENDENCY",
            "DEPENDENCY_ORDER": "INVALID_DEPENDENCY",
            "INVALID_OR_STALE_SOURCE": "STALE_SOURCE",
            "MATRIX_NOT_ELIGIBLE": "UNRESOLVED_CONFLICT",
        }.get(code, code if code in {"NO_ACTIVE_STAGE_SET", "MULTIPLE_ACTIVE_STAGE_SETS",
                                     "INVALID_STAGE_CONFIGURATION"} else "INVALID_GROUND_TRUTH"))


async def preflight(principal: Principal, employee_id: UUID, repository: GenerationRepository,
                    as_of: datetime) -> PreflightResult:
    """Service boundary; never accepts a client-provided employee or matrix snapshot."""
    if principal.profile.status != "ACTIVE" or not principal.profile.roles.intersection(
            {AppRole.ADMIN, AppRole.TRAINING_MANAGER}):
        return blocked("FORBIDDEN_ROLE")
    try:
        employee = await repository.employee(principal.token, employee_id)
        if employee is None:
            return blocked("MISSING_EMPLOYEE_CONTEXT")
        matrix = await repository.approved_matrix(principal.token, employee.role_id)
        if matrix is None:
            return blocked("NO_APPROVED_MATRIX")
        try:
            stages = await repository.stage_sets(principal.token)
        except (KeyError, ValueError, ValidationError):
            return blocked("INVALID_STAGE_CONFIGURATION")
        return prepare_generation_input(employee, matrix, stages, as_of)
    except HTTPException as exc:
        if exc.status_code in (401, 403, 404):
            return blocked("GROUND_TRUTH_ACCESS_DENIED")
        if exc.detail == "RRM_STALE_SNAPSHOT":
            return blocked("STALE_MATRIX")
        if exc.detail == "RRM_INVALID_OR_STALE_SOURCE":
            return blocked("STALE_SOURCE")
        return blocked("GROUND_TRUTH_UNAVAILABLE")
