"""Phase 2 document API; existing JWT/RBAC dependencies remain the boundary."""

from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings
from .document_processing import (
    DOCX_MIME, PARSER_VERSION, DocumentInput, DocumentProblem,
    chunk_units, parse_docx, parse_pdf, validate_file,
)
from .document_repository import DocumentRepository, get_document_repository
from .models import AppRole, Principal
from .security import require_roles


router = APIRouter(prefix="/api/v1", tags=["documents"])
READ = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER)
AUTHOR = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)
DECIDER = require_roles(AppRole.ADMIN, AppRole.REVIEWER)


class DecisionInput(BaseModel):
    reason: str | None = None
    admin_override: bool = False


async def process_reserved_version(version_id: UUID, data: bytes,
                                   repository: DocumentRepository, settings: Settings,
                                   mime_type: str, document_id: str) -> dict:
    try:
        units = parse_docx(data) if mime_type == DOCX_MIME else parse_pdf(data)
        chunks = chunk_units(units, version_id, settings.document_chunk_chars, settings.document_chunk_overlap)
        if len(chunks) > 5000:
            raise DocumentProblem("TOO_MANY_CHUNKS")
        parse_status = "PARSED" if chunks else "NEEDS_REVIEW"
        reason = None if chunks else "NO_EXTRACTABLE_TEXT"
    except DocumentProblem as exc:
        chunks = []
        parse_status = "NEEDS_REVIEW" if exc.code == "PDF_ENCRYPTED_NEEDS_REVIEW" else "FAILED"
        reason = exc.code
    except Exception:
        chunks, parse_status, reason = [], "FAILED", "DOCUMENT_PARSE_FAILED"

    await repository.finalize_processing({
        "p_version_id": str(version_id), "p_status": parse_status,
        "p_error_code": reason, "p_chunks": chunks, "p_parser_version": PARSER_VERSION,
    })
    return {"document_id": document_id, "version_id": str(version_id),
            "parse_status": parse_status, "review_status": "DRAFT", "chunk_count": len(chunks),
            "reason_code": reason}


@router.post("/documents/uploads", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    document_code: str = Form(...), title: str = Form(...), category: str = Form(...),
    version_label: str = Form(...), effective_date: date = Form(...),
    expiry_date: date | None = Form(default=None),
    department_id: UUID | None = Form(default=None), document_id: UUID | None = Form(default=None),
    principal: Principal = Depends(AUTHOR),
    repository: DocumentRepository = Depends(get_document_repository),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="DOCUMENT_PROCESSING_NOT_CONFIGURED")
    try:
        metadata = DocumentInput(
            document_id=document_id, document_code=document_code, title=title,
            category=category, department_id=department_id, version_label=version_label,
            effective_date=effective_date, expiry_date=expiry_date,
        )
        data = await file.read(settings.max_upload_bytes + 1)
        mime_type, checksum = validate_file(file.filename, file.content_type, data, settings.max_upload_bytes)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="INVALID_DOCUMENT_METADATA") from exc
    except DocumentProblem as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    finally:
        await file.close()

    version_id = uuid4()
    reserved = await repository.rpc(principal.token, "begin_document_upload", {
        "p_document_id": str(metadata.document_id) if metadata.document_id else None,
        "p_document_code": metadata.document_code, "p_title": metadata.title,
        "p_category": metadata.category,
        "p_department_id": str(metadata.department_id) if metadata.department_id else None,
        "p_version_id": str(version_id), "p_version_label": metadata.version_label,
        "p_effective_date": metadata.effective_date.isoformat(),
        "p_expiry_date": metadata.expiry_date.isoformat() if metadata.expiry_date else None,
        "p_original_filename": file.filename, "p_mime_type": mime_type,
        "p_size_bytes": len(data), "p_sha256": checksum,
    })
    if not isinstance(reserved, dict) or reserved.get("version_id") != str(version_id):
        raise HTTPException(status_code=503, detail="DOCUMENT_RESERVATION_FAILED")

    try:
        await repository.upload_original(principal.token, reserved["storage_path"], mime_type, data)
    except HTTPException:
        try:
            await repository.finalize_processing({
                "p_version_id": str(version_id), "p_status": "FAILED",
                "p_error_code": "STORAGE_FAILED", "p_chunks": [], "p_parser_version": PARSER_VERSION,
            })
        except HTTPException:
            pass  # UPLOADED is still not PARSED; manual repair remains possible.
        raise
    # If this RPC fails after Storage succeeded, leave UPLOADED for checksum-verified retry.
    await repository.rpc(principal.token, "mark_document_processing", {"p_version_id": str(version_id)})

    return await process_reserved_version(version_id, data, repository, settings,
                                          mime_type, reserved["document_id"])


@router.post("/document-versions/{version_id}/retry", status_code=202)
async def retry_document_processing(
    version_id: UUID, file: UploadFile | None = File(default=None),
    principal: Principal = Depends(AUTHOR),
    repository: DocumentRepository = Depends(get_document_repository),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="DOCUMENT_PROCESSING_NOT_CONFIGURED")
    rows = await repository.rows(principal.token, "document_versions", {
        "select": "id,document_id,parse_status,review_status,uploaded_by,storage_path,sha256,size_bytes,mime_type,original_filename",
        "id": f"eq.{version_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="DOCUMENT_VERSION_NOT_FOUND")
    version = rows[0]
    if version["uploaded_by"] != str(principal.profile.id) or version["review_status"] != "DRAFT" \
       or version["parse_status"] not in ("UPLOADED", "PROCESSING"):
        raise HTTPException(status_code=409, detail="DOCUMENT_STATE_CONFLICT")
    try:
        data = await repository.download_original(principal.token, version["storage_path"])
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        if version["parse_status"] != "UPLOADED" or file is None:
            raise HTTPException(status_code=409, detail="DOCUMENT_ORIGINAL_MISSING") from exc
        try:
            data = await file.read(settings.max_upload_bytes + 1)
            actual_mime, checksum = validate_file(file.filename, file.content_type, data, settings.max_upload_bytes)
        except DocumentProblem as problem:
            raise HTTPException(status_code=problem.status, detail=problem.code) from problem
        finally:
            await file.close()
        if actual_mime != version["mime_type"] or checksum != version["sha256"] or len(data) != version["size_bytes"]:
            raise HTTPException(status_code=409, detail="DOCUMENT_ORIGINAL_MISMATCH")
        await repository.upload_original(principal.token, version["storage_path"], actual_mime, data)
    if sha256(data).hexdigest() != version["sha256"] or len(data) != version["size_bytes"]:
        raise HTTPException(status_code=409, detail="DOCUMENT_ORIGINAL_MISMATCH")
    if version["parse_status"] == "UPLOADED":
        await repository.rpc(principal.token, "mark_document_processing", {"p_version_id": str(version_id)})
    return await process_reserved_version(version_id, data, repository, settings,
                                          version["mime_type"], version["document_id"])


@router.get("/documents")
async def list_documents(
    offset: int = 0, limit: int = 100,
    principal: Principal = Depends(READ),
    repository: DocumentRepository = Depends(get_document_repository),
) -> dict:
    if offset < 0 or limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="INVALID_PAGE")
    rows = await repository.rows(principal.token, "documents", {
        "select": "id,document_code,title,category,department_id,status,created_at,document_versions(id,version_label,parse_status,review_status,effective_date,expiry_date,uploaded_by,created_at)",
        "order": "created_at.desc,id.desc", "limit": str(limit + 1), "offset": str(offset),
    })
    return {"items": rows[:limit], "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, principal: Principal = Depends(READ),
                       repository: DocumentRepository = Depends(get_document_repository)) -> dict:
    rows = await repository.rows(principal.token, "documents", {
        "select": "id,document_code,title,category,department_id,status,created_at,document_versions(id,version_label,parse_status,parse_error_code,review_status,effective_date,expiry_date,original_filename,mime_type,size_bytes,uploaded_by,submitted_by,approved_by,created_at)",
        "id": f"eq.{document_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")
    return rows[0]


@router.get("/documents/{document_id}/current-effective-version")
async def current_effective_version(document_id: UUID, on_date: date | None = None,
                                    principal: Principal = Depends(READ),
                                    repository: DocumentRepository = Depends(get_document_repository)) -> dict | None:
    rows = await repository.rpc(principal.token, "current_effective_document_version", {
        "p_document_id": str(document_id), "p_on_date": (on_date or date.today()).isoformat(),
    })
    return rows[0] if isinstance(rows, list) and rows else None


@router.get("/document-versions/{version_id}")
async def get_document_version(version_id: UUID, principal: Principal = Depends(READ),
                               repository: DocumentRepository = Depends(get_document_repository)) -> dict:
    rows = await repository.rows(principal.token, "document_versions", {
        "select": "id,document_id,version_label,parse_status,parse_error_code,review_status,effective_date,expiry_date,original_filename,mime_type,size_bytes,storage_path,sha256,parser_version,uploaded_by,submitted_by,approved_by,rejected_by,decision_reason,created_at,updated_at",
        "id": f"eq.{version_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="DOCUMENT_VERSION_NOT_FOUND")
    return rows[0]


@router.get("/document-versions/{version_id}/chunks")
async def get_document_chunks(version_id: UUID, offset: int = 0, limit: int = 100,
                              principal: Principal = Depends(READ),
                              repository: DocumentRepository = Depends(get_document_repository)) -> dict:
    if offset < 0 or limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="INVALID_PAGE")
    rows = await repository.rows(principal.token, "document_chunks", {
        "select": "id,document_version_id,chunk_key,sequence,content,heading,section_path,source_location,page_number,paragraph_start,paragraph_end,char_start,char_end,parser_version",
        "document_version_id": f"eq.{version_id}", "order": "sequence.asc",
        "limit": str(limit + 1), "offset": str(offset),
    })
    return {"items": rows[:limit], "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.get("/document-versions/{version_id}/original")
async def download_document_original(version_id: UUID, principal: Principal = Depends(READ),
                                     repository: DocumentRepository = Depends(get_document_repository)) -> Response:
    rows = await repository.rows(principal.token, "document_versions", {
        "select": "storage_path,mime_type,original_filename", "id": f"eq.{version_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="DOCUMENT_VERSION_NOT_FOUND")
    version = rows[0]
    data = await repository.download_original(principal.token, version["storage_path"])
    return Response(content=data, media_type=version["mime_type"], headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(version['original_filename'], safe='')}"
    })


@router.post("/document-versions/{version_id}/submit")
async def submit_document(version_id: UUID, principal: Principal = Depends(AUTHOR),
                          repository: DocumentRepository = Depends(get_document_repository)) -> dict:
    await repository.rpc(principal.token, "submit_document_version", {"p_version_id": str(version_id)})
    return {"version_id": str(version_id), "review_status": "SUBMITTED"}


@router.post("/document-versions/{version_id}/approve")
async def approve_document(version_id: UUID, decision: DecisionInput,
                           principal: Principal = Depends(DECIDER),
                           repository: DocumentRepository = Depends(get_document_repository)) -> dict:
    await repository.rpc(principal.token, "decide_document_version", {
        "p_version_id": str(version_id), "p_approve": True, "p_reason": decision.reason,
        "p_admin_override": decision.admin_override,
    })
    return {"version_id": str(version_id), "review_status": "APPROVED"}


@router.post("/document-versions/{version_id}/reject")
async def reject_document(version_id: UUID, decision: DecisionInput,
                          principal: Principal = Depends(DECIDER),
                          repository: DocumentRepository = Depends(get_document_repository)) -> dict:
    if not decision.reason or not decision.reason.strip():
        raise HTTPException(status_code=422, detail="DOCUMENT_REASON_REQUIRED")
    await repository.rpc(principal.token, "decide_document_version", {
        "p_version_id": str(version_id), "p_approve": False, "p_reason": decision.reason,
        "p_admin_override": decision.admin_override,
    })
    return {"version_id": str(version_id), "review_status": "REJECTED"}
