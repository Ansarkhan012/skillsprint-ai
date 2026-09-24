"""Phase 3A.2 human RRM API. All mutations invoke the applied SQL RPCs as the user."""

import asyncio
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import AppRole, Principal
from .rrm_models import Entry, PrecedenceConfig, Reason, Scope, Timing, meaningful_reason
from .rrm_repository import RRMRepository, get_rrm_repository
from .rrm_service import CHUNK_SELECT, bulk_rows, eligible_sources, matrix_detail, page, requirement_detail
from .security import require_roles


router = APIRouter(prefix="/api/v1", tags=["rrm"])
READ = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER)
AUTHOR = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)
REVIEW = require_roles(AppRole.ADMIN, AppRole.REVIEWER)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateInput(Input):
    predecessor_id: UUID | None = None
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    statement: str = Field(min_length=1, max_length=4000)
    requirement_type: Literal["MUST_KNOW", "MUST_COMPLETE", "MUST_DEMONSTRATE", "MUST_ACKNOWLEDGE", "RECOMMENDED", "OPTIONAL", "NOT_APPLICABLE"]
    category: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    mandatory: bool
    competency: str | None = Field(default=None, max_length=4000)
    assessment_required: bool = False
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    timing: Timing = Field(default_factory=Timing)
    scopes: list[Scope] = Field(min_length=1, max_length=32)
    chunk_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def consistent(self):
        if self.mandatory != self.requirement_type.startswith("MUST_") or len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("RRM_INVALID_CANDIDATE")
        return self


class MatrixCreate(Input):
    config_id: UUID
    predecessor_id: UUID | None = None


class DependencyInput(Input):
    dependent_id: UUID
    prerequisite_id: UUID


class MatrixEdit(Input):
    expected_version: int = Field(ge=0)
    entries: list[Entry] = Field(min_length=1, max_length=1000)
    dependencies: list[DependencyInput] = Field(default_factory=list, max_length=5000)
    reason: Reason


class Transition(Input):
    expected_version: int = Field(ge=0)
    reason: Reason | None = None
    admin_override: bool = False


class IssueInput(Input):
    expected_version: int = Field(ge=0)
    kind: Literal["CONFLICT", "AMBIGUITY", "DUPLICATE", "SUSPICIOUS_CONTENT", "MISSING_EVIDENCE"]
    detail: str = Field(min_length=1, max_length=4000)
    requirement_id: UUID | None = None
    related_requirement_id: UUID | None = None


class ResolveInput(Input):
    expected_version: int = Field(ge=0)
    reason: Reason
    admin_override: bool = False


class ConfigInput(Input):
    config: PrecedenceConfig
    reason: Reason
    predecessor_id: UUID | None = None


def paging(offset: int, limit: int) -> None:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "INVALID_PAGE")


@router.get("/requirements")
async def requirements(offset: int = 0, limit: int = 50, search: str = "", origin: str | None = None,
                       mandatory: bool | None = None, source_document: UUID | None = None,
                       author: UUID | None = None, principal: Principal = Depends(READ),
                       repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    paging(offset, limit)
    if len(search) > 120 or origin not in (None, "MANUAL", "AI_CANDIDATE"):
        raise HTTPException(422, "RRM_INVALID_FILTER")
    params = {"select": "id,requirement_code,revision,statement,requirement_type,category,mandatory,timing,origin,created_by,created_at",
              "order": "created_at.desc,id.desc", "limit": str(limit + 1), "offset": str(offset)}
    if search:
        # Escape PostgREST quoted filter metacharacters; no raw filter language accepted.
        safe = search.replace("\\", "\\\\").replace('"', '\\"').replace("*", "\\*")
        params["or"] = f'(requirement_code.ilike."*{safe}*",statement.ilike."*{safe}*")'
    if origin:
        params["origin"] = f"eq.{origin}"
    if mandatory is not None:
        params["mandatory"] = f"eq.{str(mandatory).lower()}"
    if author:
        params["created_by"] = f"eq.{author}"
    if source_document:
        chunks = await repo.rows(principal.token, "document_versions", {
            "select": "id", "document_id": f"eq.{source_document}", "limit": "100",
        })
        if not chunks:
            return page([], offset, limit)
        if len(chunks) == 100:
            raise HTTPException(422, "RRM_FILTER_TOO_BROAD")
        # Source-document filtering is resolved through the relational source chain.
        version_ids = ",".join(row["id"] for row in chunks)
        source_chunks = await repo.rows(principal.token, "document_chunks", {
            "select": "id", "document_version_id": f"in.({version_ids})", "limit": "100",
        })
        if not source_chunks:
            return page([], offset, limit)
        if len(source_chunks) == 100:
            raise HTTPException(422, "RRM_FILTER_TOO_BROAD")
        source_ids = ",".join(row["id"] for row in source_chunks)
        links = await repo.rows(principal.token, "requirement_sources", {
            "select": "requirement_id", "chunk_id": f"in.({source_ids})", "limit": "100",
        })
        if not links:
            return page([], offset, limit)
        if len(links) == 100:
            raise HTTPException(422, "RRM_FILTER_TOO_BROAD")
        params["id"] = "in.(" + ",".join(sorted({row["requirement_id"] for row in links})) + ")"
    return page(await repo.rows(principal.token, "requirements", params), offset, limit)


@router.post("/requirements", status_code=201)
async def create_requirement(data: CandidateInput, principal: Principal = Depends(AUTHOR),
                             repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    await eligible_sources(repo, principal.token, [str(chunk_id) for chunk_id in data.chunk_ids])
    payload = data.model_dump(mode="json", exclude_none=True, exclude={"predecessor_id"})
    result = await repo.rpc(principal.token, "create_requirement_candidate", {
        "p_data": {**payload, "origin": "MANUAL"},
        "p_predecessor": str(data.predecessor_id) if data.predecessor_id else None,
    })
    return {"id": result}


@router.get("/requirements/{requirement_id}")
async def get_requirement(requirement_id: UUID, principal: Principal = Depends(READ),
                          repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    return await requirement_detail(repo, principal.token, requirement_id)


@router.get("/rrm/evidence")
async def evidence(offset: int = 0, limit: int = 30, principal: Principal = Depends(READ),
                   repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    paging(offset, limit)
    versions = await repo.rows(principal.token, "document_versions", {
        "select": "id,document_id,version_label,parse_status,review_status,effective_date,expiry_date",
        "parse_status": "eq.PARSED", "review_status": "eq.APPROVED",
        "order": "approved_at.desc,id.desc", "limit": str(limit + 1), "offset": str(offset),
    })
    listed = versions[:limit]
    documents = {row["id"]: row for row in await bulk_rows(
        repo, principal.token, "documents", "id", [version["document_id"] for version in listed],
        "id,document_code,title,status")}
    today = datetime.now(timezone.utc).date().isoformat()
    semaphore = asyncio.Semaphore(8)

    async def current(document_id: str) -> tuple[str, str | None]:
        async with semaphore:
            result = await repo.rpc(principal.token, "current_effective_document_version", {
                "p_document_id": document_id, "p_on_date": today,
            })
        current_id = result[0]["id"] if isinstance(result, list) and result else (result or {}).get("id")
        return document_id, current_id

    current_versions = dict(await asyncio.gather(*(current(document_id) for document_id in
                                                  dict.fromkeys(version["document_id"] for version in listed))))
    eligible = []
    for version in listed:
        document = documents.get(version["document_id"])
        if current_versions.get(version["document_id"]) == version["id"] and document and document["status"] == "ACTIVE":
            eligible.append({**version, "document": document})
    return {"items": eligible, "offset": offset, "limit": limit, "has_more": len(versions) > limit}


@router.get("/rrm/evidence/{version_id}/chunks")
async def evidence_chunks(version_id: UUID, offset: int = 0, limit: int = 50,
                          principal: Principal = Depends(READ),
                          repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    paging(offset, limit)
    rows = await repo.rows(principal.token, "document_chunks", {
        "select": CHUNK_SELECT,
        "document_version_id": f"eq.{version_id}", "order": "sequence.asc", "limit": str(limit + 1), "offset": str(offset),
    })
    await eligible_sources(repo, principal.token, [row["id"] for row in rows[:limit]], rows[:limit])
    return page([{key: value for key, value in row.items() if key != "text_hash"} for row in rows], offset, limit)


@router.get("/rrm/configs")
async def configs(principal: Principal = Depends(READ), repo: RRMRepository = Depends(get_rrm_repository)) -> list[dict]:
    rows = await repo.rows(principal.token, "rrm_precedence_configs", {
        "select": "id,revision,ranks,created_at,reason", "order": "revision.desc", "limit": "100",
    })
    authorities = await bulk_rows(repo, principal.token, "rrm_document_authorities", "config_id",
                                  [row["id"] for row in rows], "config_id,document_id,authority_class",
                                  batch_size=1, rows_per_id=1000)
    by_config: dict[str, list[dict]] = {row["id"]: [] for row in rows}
    for authority in authorities:
        by_config[authority["config_id"]].append({"document_id": authority["document_id"],
                                                  "authority_class": authority["authority_class"]})
    for row in rows:
        row["documents"] = by_config[row["id"]]
    return rows


@router.post("/rrm/configs", status_code=201)
async def create_config(data: ConfigInput, principal: Principal = Depends(require_roles(AppRole.ADMIN)),
                        repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    result = await repo.rpc(principal.token, "create_rrm_precedence_config", {
        "p_ranks": data.config.ranks, "p_documents": {str(k): v for k, v in data.config.document_classes.items()},
        "p_reason": data.reason, "p_predecessor": str(data.predecessor_id) if data.predecessor_id else None,
    })
    return {"id": result}


@router.get("/roles/{role_id}/matrices")
async def matrices(role_id: UUID, offset: int = 0, limit: int = 50,
                   principal: Principal = Depends(READ), repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    paging(offset, limit)
    rows = await repo.rows(principal.token, "role_requirement_matrices", {
        "select": "id,role_id,revision,status,current_edit,lock_version,created_by,submitted_by,decided_by,snapshot_hash,created_at",
        "role_id": f"eq.{role_id}", "order": "revision.desc", "limit": str(limit + 1), "offset": str(offset),
    })
    return page(rows, offset, limit)


@router.post("/roles/{role_id}/matrices", status_code=201)
async def create_matrix(role_id: UUID, data: MatrixCreate, principal: Principal = Depends(AUTHOR),
                        repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    result = await repo.rpc(principal.token, "create_rrm_matrix", {
        "p_role": str(role_id), "p_config": str(data.config_id),
        "p_predecessor": str(data.predecessor_id) if data.predecessor_id else None,
    })
    return {"id": result}


@router.get("/matrices/{matrix_id}")
async def get_matrix(matrix_id: UUID, principal: Principal = Depends(READ),
                     repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    return await matrix_detail(repo, principal.token, matrix_id)


@router.patch("/matrices/{matrix_id}")
async def edit_matrix(matrix_id: UUID, data: MatrixEdit, principal: Principal = Depends(AUTHOR),
                      repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    result = await repo.rpc(principal.token, "edit_rrm_matrix", {
        "p_matrix": str(matrix_id), "p_expected_version": data.expected_version,
        "p_entries": [entry.model_dump(mode="json", exclude_none=True) for entry in data.entries],
        "p_dependencies": [edge.model_dump(mode="json") for edge in data.dependencies],
        "p_reason": data.reason,
    })
    return {"id": str(matrix_id), "lock_version": result}


async def transition(matrix_id: UUID, action: str, data: Transition, principal: Principal, repo: RRMRepository) -> dict:
    if action == "SUBMIT" and data.admin_override:
        raise HTTPException(422, "RRM_INVALID_ACTION")
    if action == "REJECT" and not meaningful_reason(data.reason):
        raise HTTPException(422, "RRM_REASON_REQUIRED")
    if data.admin_override and (AppRole.ADMIN not in principal.profile.roles or not meaningful_reason(data.reason)):
        raise HTTPException(403, "RRM_OVERRIDE_FORBIDDEN")
    result = await repo.rpc(principal.token, "transition_rrm_matrix", {
        "p_matrix": str(matrix_id), "p_expected_version": data.expected_version,
        "p_action": action, "p_reason": data.reason, "p_admin_override": data.admin_override,
    })
    return {"id": str(matrix_id), "status": result}


@router.post("/matrices/{matrix_id}/submit")
async def submit_matrix(matrix_id: UUID, data: Transition, principal: Principal = Depends(AUTHOR),
                        repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    return await transition(matrix_id, "SUBMIT", data, principal, repo)


@router.post("/matrices/{matrix_id}/approve")
async def approve_matrix(matrix_id: UUID, data: Transition, principal: Principal = Depends(REVIEW),
                         repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    return await transition(matrix_id, "APPROVE", data, principal, repo)


@router.post("/matrices/{matrix_id}/reject")
async def reject_matrix(matrix_id: UUID, data: Transition, principal: Principal = Depends(REVIEW),
                        repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    return await transition(matrix_id, "REJECT", data, principal, repo)


@router.post("/matrices/{matrix_id}/issues", status_code=201)
async def raise_issue(matrix_id: UUID, data: IssueInput, principal: Principal = Depends(READ),
                      repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    result = await repo.rpc(principal.token, "raise_rrm_issue", {
        "p_matrix": str(matrix_id), "p_expected_version": data.expected_version,
        "p_kind": data.kind, "p_detail": data.detail,
        "p_requirement": str(data.requirement_id) if data.requirement_id else None,
        "p_related": str(data.related_requirement_id) if data.related_requirement_id else None,
    })
    return {"id": result}


@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(issue_id: UUID, data: ResolveInput, principal: Principal = Depends(REVIEW),
                        repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    if data.admin_override and AppRole.ADMIN not in principal.profile.roles:
        raise HTTPException(403, "RRM_OVERRIDE_FORBIDDEN")
    await repo.rpc(principal.token, "resolve_rrm_issue", {
        "p_issue": str(issue_id), "p_expected_version": data.expected_version,
        "p_reason": data.reason, "p_admin_override": data.admin_override,
    })
    return {"id": str(issue_id), "resolved": True}


@router.get("/roles/{role_id}/ground-truth")
async def ground_truth(role_id: UUID, principal: Principal = Depends(READ),
                       repo: RRMRepository = Depends(get_rrm_repository)) -> dict:
    rows = await repo.rows(principal.token, "role_requirement_matrices", {
        "select": "id,revision,created_by,submitted_by,submitted_at,decided_by,decided_at,decision_reason,admin_override",
        "role_id": f"eq.{role_id}", "status": "eq.APPROVED", "limit": "2",
    })
    if not rows:
        raise HTTPException(409, "RRM_NO_APPROVED_MATRIX")
    result = await repo.rpc(principal.token, "get_rrm_ground_truth", {"p_matrix": rows[0]["id"]})
    if not isinstance(result, dict) or "snapshot" not in result or "snapshot_hash" not in result:
        raise HTTPException(503, "RRM_SERVICE_UNAVAILABLE")
    return {**result, "approval": rows[0]}
