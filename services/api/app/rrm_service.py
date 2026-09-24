"""RLS-protected bulk read composition for the human RRM workflow."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException

from .rrm_repository import RRMRepository

REQUIREMENT_SELECT = ("id,requirement_code,revision,predecessor_id,statement,requirement_type,"
                      "category,mandatory,competency,assessment_required,priority,timing,origin,created_by,created_at")
CHUNK_SELECT = ("id,document_version_id,sequence,content,text_hash,heading,section_path,"
                "source_location,page_number,paragraph_start,paragraph_end")
VERSION_SELECT = ("id,document_id,version_label,parse_status,review_status,effective_date,"
                  "expiry_date,sha256,approved_at")
DOCUMENT_SELECT = "id,document_code,title,status"


def page(rows: list[dict], offset: int, limit: int) -> dict:
    return {"items": rows[:limit], "offset": offset, "limit": limit, "has_more": len(rows) > limit}


async def relation_rows(repo: RRMRepository, token: str, table: str,
                        params: dict[str, str], maximum: int = 10000) -> list[dict]:
    """Never return a truncated relation for readiness or complete-replacement edits.

    Use bounded 100-row requests, including an end probe for exact multiples.
    Callers provide a unique, stable order. At the safety bound, fail closed.
    """
    result: list[dict] = []
    while True:
        batch = await repo.rows(token, table, {**params, "offset": str(len(result)), "limit": "100"})
        result.extend(batch)
        if len(result) > maximum:
            raise HTTPException(422, "RRM_MATRIX_DETAIL_LIMIT")
        if len(batch) < 100:
            return result


async def bulk_rows(repo: RRMRepository, token: str, table: str, key: str,
                    ids: list[str], select: str, batch_size: int = 100,
                    rows_per_id: int = 1) -> list[dict]:
    """Bound URL size and PostgREST row limits; always use the caller's JWT."""
    distinct = list(dict.fromkeys(ids))
    if not distinct:
        return []
    batches = [distinct[start:start + batch_size] for start in range(0, len(distinct), batch_size)]
    semaphore = asyncio.Semaphore(8)

    async def fetch(batch: list[str]) -> list[dict]:
        async with semaphore:
            return await repo.rows(token, table, {
                "select": select, key: f"in.({','.join(batch)})",
                "limit": str(len(batch) * rows_per_id),
            })

    return [row for batch in await asyncio.gather(*(fetch(batch) for batch in batches)) for row in batch]


def _project(row: dict | None, fields: tuple[str, ...]) -> dict | None:
    return {field: row[field] for field in fields if field in row} if row is not None else None


async def resolve_sources(repo: RRMRepository, token: str, chunk_ids: list[str],
                          preloaded_chunks: list[dict] | None = None) -> dict[str, dict]:
    """Resolve exact chunks with unchanged UTC/current-effective/hash eligibility."""
    ids = list(dict.fromkeys(chunk_ids))
    chunk_rows = preloaded_chunks if preloaded_chunks is not None else await bulk_rows(
        repo, token, "document_chunks", "id", ids, CHUNK_SELECT)
    chunks = {row["id"]: row for row in chunk_rows if row["id"] in ids}
    versions = {row["id"]: row for row in await bulk_rows(
        repo, token, "document_versions", "id",
        [row["document_version_id"] for row in chunks.values()], VERSION_SELECT)}
    documents = {row["id"]: row for row in await bulk_rows(
        repo, token, "documents", "id", [row["document_id"] for row in versions.values()], DOCUMENT_SELECT)}
    today = datetime.now(timezone.utc).date().isoformat()

    def locally_eligible(chunk: dict, version: dict | None, document: dict | None) -> bool:
        return bool(version and document and document["status"] == "ACTIVE"
                    and version["parse_status"] == "PARSED" and version["review_status"] == "APPROVED"
                    and version["effective_date"] <= today
                    and (version["expiry_date"] is None or version["expiry_date"] >= today)
                    and sha256(chunk["content"].encode("utf-8")).hexdigest() == chunk["text_hash"])

    current_docs = list(dict.fromkeys(version["document_id"] for chunk in chunks.values()
                                  if (version := versions.get(chunk["document_version_id"]))
                                  and locally_eligible(chunk, version, documents.get(version["document_id"]))))
    semaphore = asyncio.Semaphore(8)

    async def current(document_id: str) -> tuple[str, str | None]:
        async with semaphore:
            result = await repo.rpc(token, "current_effective_document_version", {
                "p_document_id": document_id, "p_on_date": today,
            })
        current_id = result[0]["id"] if isinstance(result, list) and result else (result or {}).get("id")
        return document_id, current_id

    current_versions = dict(await asyncio.gather(*(current(document_id) for document_id in current_docs)))
    resolved = {}
    for chunk_id in ids:
        chunk = chunks.get(chunk_id)
        version = versions.get(chunk["document_version_id"]) if chunk else None
        document = documents.get(version["document_id"]) if version else None
        eligible = bool(chunk and locally_eligible(chunk, version, document)
                        and current_versions.get(version["document_id"]) == version["id"])
        resolved[chunk_id] = {
            "chunk_id": chunk_id,
            "chunk": chunk if eligible else _project(chunk, ("id", "document_version_id", "content", "heading",
                                                       "section_path", "source_location", "text_hash")),
            "version": version if eligible else _project(version, ("id", "document_id", "version_label",
                                                           "parse_status", "review_status", "effective_date", "expiry_date")),
            "document": document,
            "current_eligible": eligible,
        }
    return resolved


async def eligible_sources(repo: RRMRepository, token: str, chunk_ids: list[str],
                           preloaded_chunks: list[dict] | None = None) -> dict[str, dict]:
    resolved = await resolve_sources(repo, token, chunk_ids, preloaded_chunks)
    if any(not resolved[chunk_id]["current_eligible"] for chunk_id in chunk_ids):
        raise HTTPException(422, "RRM_INVALID_OR_STALE_SOURCE")
    return resolved


async def eligible_source(repo: RRMRepository, token: str, chunk_id: UUID) -> dict:
    item = (await eligible_sources(repo, token, [str(chunk_id)]))[str(chunk_id)]
    return {"chunk": item["chunk"], "version": item["version"], "document": item["document"]}


async def requirement_detail(repo: RRMRepository, token: str, requirement_id: UUID) -> dict:
    return (await requirement_details(repo, token, [str(requirement_id)]))[str(requirement_id)]


async def requirement_details(repo: RRMRepository, token: str, requirement_ids: list[str]) -> dict[str, dict]:
    ids = list(dict.fromkeys(requirement_ids))
    if not ids:
        return {}
    rows, sources, scopes = await asyncio.gather(
        bulk_rows(repo, token, "requirements", "id", ids, REQUIREMENT_SELECT),
        bulk_rows(repo, token, "requirement_sources", "requirement_id", ids,
                  "requirement_id,chunk_id", batch_size=10, rows_per_id=100),
        bulk_rows(repo, token, "requirement_applicability", "requirement_id", ids,
                  "requirement_id,ordinal,role_id,department_id,location_code,experience",
                  batch_size=25, rows_per_id=32),
    )
    requirements = {row["id"]: row for row in rows}
    if any(requirement_id not in requirements for requirement_id in ids):
        raise HTTPException(404, "RRM_NOT_FOUND")
    resolved = await resolve_sources(repo, token, [source["chunk_id"] for source in sources])
    by_requirement: dict[str, list[dict]] = {requirement_id: [] for requirement_id in ids}
    for source in sources:
        evidence = resolved[source["chunk_id"]]
        by_requirement[source["requirement_id"]].append(
            {key: value for key, value in evidence.items() if key != "chunk_id"}
            if evidence["current_eligible"] else evidence)
    scopes_by_requirement: dict[str, list[dict]] = {requirement_id: [] for requirement_id in ids}
    for scope in scopes:
        scopes_by_requirement[scope["requirement_id"]].append({key: value for key, value in scope.items()
                                                                 if key != "requirement_id"})
    return {requirement_id: {**requirements[requirement_id],
                             "scopes": sorted(scopes_by_requirement[requirement_id], key=lambda row: row["ordinal"]),
                             "evidence": by_requirement[requirement_id]}
            for requirement_id in ids}


async def matrix_detail(repo: RRMRepository, token: str, matrix_id: UUID) -> dict:
    matrices = await repo.rows(token, "role_requirement_matrices", {
        "select": "id,role_id,revision,predecessor_id,config_id,status,current_edit,lock_version,created_by,created_at,submitted_by,submitted_at,decided_by,decided_at,decision_reason,admin_override,snapshot_hash",
        "id": f"eq.{matrix_id}", "limit": "1",
    })
    if not matrices:
        raise HTTPException(404, "RRM_NOT_FOUND")
    matrix = matrices[0]
    edit = matrix["current_edit"]
    async def entries_read() -> list[dict]:
        return await relation_rows(repo, token, "role_requirements", {
            "select": "requirement_id,sequence,stage_id,exception_to,downgrade_requested,downgrade_justification,downgrade_evidence",
            "matrix_id": f"eq.{matrix_id}", "edit_no": f"eq.{edit}", "order": "sequence.asc,requirement_id.asc",
        }, maximum=1000) if edit else []

    async def dependencies_read() -> list[dict]:
        return await relation_rows(repo, token, "requirement_dependencies", {
            "select": "dependent_id,prerequisite_id", "matrix_id": f"eq.{matrix_id}",
            "edit_no": f"eq.{edit}", "order": "dependent_id.asc,prerequisite_id.asc",
        }, maximum=5000) if edit else []

    async def issues_read() -> list[dict]:
        return await relation_rows(repo, token, "rrm_issues", {
            "select": "id,raised_edit,kind,detail,requirement_id,related_requirement_id,created_by,created_at",
            "matrix_id": f"eq.{matrix_id}", "order": "created_at.asc,id.asc",
        })

    async def resolutions_read() -> list[dict]:
        return await relation_rows(repo, token, "rrm_issue_resolutions", {
            "select": "issue_id,edit_no,resolved_by,resolved_at,reason,admin_override",
            "matrix_id": f"eq.{matrix_id}", "edit_no": f"eq.{edit}", "order": "issue_id.asc",
        }) if edit else []

    entries, dependencies, issues, resolutions = await asyncio.gather(
        entries_read(), dependencies_read(), issues_read(), resolutions_read())
    resolved = {row["issue_id"] for row in resolutions}
    for issue in issues:
        issue["blocking"] = issue["id"] not in resolved
    requirements = await requirement_details(repo, token, [entry["requirement_id"] for entry in entries])
    ambiguous = [entry["requirement_id"] for entry in entries
                 if requirements.get(entry["requirement_id"], {}).get("timing", {}).get("state") == "AMBIGUOUS"]
    return {**matrix, "entries": entries, "dependencies": dependencies,
            "issues": issues, "requirements": requirements,
            "readiness": {"blocking_codes": (["RRM_EMPTY_MATRIX"] if not entries else [])
                          + (["RRM_UNRESOLVED_ISSUE"] if any(i["blocking"] for i in issues) else [])
                          + (["RRM_TIMING_MANUAL_REVIEW"] if ambiguous else [])
                          + (["RRM_INVALID_OR_STALE_SOURCE"] if any(
                              not evidence["current_eligible"] for req in requirements.values()
                              for evidence in req["evidence"]) else [])}}
