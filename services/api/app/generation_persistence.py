"""Phase 4C caller-JWT storage boundary. No service-role credential is used."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import HTTPException, Request

from .config import get_settings
from .generation_repository import GenerationRepository
from .generation_service import AttemptTelemetry
from .rrm_repository import RRMRepository

_LOG = logging.getLogger(__name__)
# Local, content-free record of every failed attempt's diagnostics (JSON lines). Relative paths
# resolve against the backend's working directory; set GENERATION_DIAGNOSTICS_FILE to blank to disable.
DEFAULT_DIAGNOSTICS_FILE = "logs/generation_diagnostics.jsonl"
_SAFE_DB_CODE = re.compile(r"[A-Z0-9_]{1,40}")


def diagnostics_file() -> Path | None:
    value = os.environ.get("GENERATION_DIAGNOSTICS_FILE", DEFAULT_DIAGNOSTICS_FILE)
    return Path(value) if value.strip() else None


def _safe_error_code(response: httpx.Response) -> str | None:
    """PostgREST/Postgres error code (e.g. PGRST202, 42501) or our GEN4_* code; never messages."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for value in (body.get("message"), body.get("code")):
        if isinstance(value, str) and _SAFE_DB_CODE.fullmatch(value) and (
                value.startswith(("GEN4_", "PGRST")) or value.isdigit() or re.fullmatch(r"[0-9A-Z]{5}", value)):
            return value
    return None


def write_local_diagnostics(run_id: UUID, attempt_no: int | None, item: AttemptTelemetry, outcome: dict) -> None:
    """Append one content-free line; never raises (diagnostics must not break generation)."""
    path = diagnostics_file()
    if path is None:
        return
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": str(run_id),
              "attempt_no": attempt_no, "error_code": item.error_code, "response_size": item.response_size,
              "usage": dict(item.usage), **outcome, "diagnostics": item.diagnostics}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        _LOG.warning("generation_local_diagnostics_not_written run_id=%s reason=%s", run_id, type(exc).__name__)


SAFE_RPC_ERRORS = {
    "GEN4_FORBIDDEN": 403,
    "GEN4_FORBIDDEN_OR_STATE": 403,
    "GEN4_IDEMPOTENCY_CONFLICT": 409,
    "GEN4_EMPLOYEE_CONTEXT_STALE": 409,
    "GEN4_STAGE_SET_STALE": 409,
    "GEN4_MATRIX_STALE": 409,
    "GEN4_EFFECTIVE_REQUIREMENTS_MISMATCH": 409,
    "GEN4_SOURCE_MISMATCH": 409,
    "GEN4_BOOTSTRAP_CONFLICT": 409,
    "GEN4_BOOTSTRAP_PARTIAL_CONFIGURATION": 409,
    "GEN4_RECOVERY_TOO_EARLY": 409,
    "GEN4_INVALID_STAGE_CONFIGURATION": 422,
    "GEN4_INVALID_INPUT": 422,
    "GEN4_INVALID_ATTEMPT": 422,
    "GEN4_INVALID_FINISH": 422,
}


class GenerationStore(GenerationRepository):
    async def rpc(self, token: str, name: str, payload: dict) -> object:
        try:
            response = await self.rrm.http().post(
                f"{self.rrm.url}/rest/v1/rpc/{name}", headers=self.rrm.headers(token),
                json=payload, timeout=30)
        except httpx.HTTPError:
            raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE") from None
        if not response.is_success:
            try:
                error = response.json()
                code = error.get("message", "")
            except (ValueError, AttributeError):
                error = {}
                code = ""
            if code in SAFE_RPC_ERRORS:
                raise HTTPException(SAFE_RPC_ERRORS[code], code)
            if response.status_code in (401, 403):
                raise HTTPException(403, "GENERATION_FORBIDDEN")
            if response.status_code == 409 or error.get("code") == "23505":
                raise HTTPException(409, "GENERATION_CONFLICT")
            if response.status_code in (400, 422):
                raise HTTPException(422, "GENERATION_INVALID_INPUT")
            raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE")
        try:
            return response.json() if response.content else None
        except ValueError:
            raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE") from None

    async def reserve(self, token: str, payload: dict) -> dict:
        result = await self.rpc(token, "reserve_generation_run_bounded", payload)
        if not isinstance(result, dict) or "id" not in result or "created" not in result:
            raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE")
        return result

    async def claim(self, token: str, run_id: UUID) -> bool:
        return await self.rpc(token, "claim_generation_run", {"p_run": str(run_id)}) is True

    async def record_attempt(self, token: str, run_id: UUID, item: AttemptTelemetry) -> None:
        attempt_no = await self.rpc(token, "record_generation_attempt", {
            "p_run": str(run_id), "p_type": item.attempt_type,
            "p_outcome": item.provider_outcome, "p_latency": item.latency_ms,
            "p_usage": dict(item.usage), "p_response_hash": item.response_hash,
            "p_response_size": item.response_size, "p_parse": item.parse_outcome,
            "p_error": item.error_code,
        })
        if not item.diagnostics:
            return
        # Best effort and additive (migration 202609280010): a failed diagnostics write must never
        # fail a generation whose attempt is already recorded. Every outcome is recorded locally
        # (content-free) so the exact failure survives even if the database write fails.
        outcome = {"db_persisted": False, "db_status": None, "db_code": None}
        if not isinstance(attempt_no, int) or isinstance(attempt_no, bool):
            outcome["db_code"] = "ATTEMPT_NUMBER_NOT_INTEGER:" + type(attempt_no).__name__
        else:
            outcome.update(await self._record_diagnostics(token, run_id, attempt_no, item.diagnostics))
        if not outcome["db_persisted"]:
            _LOG.warning("generation_attempt_diagnostics_not_persisted run_id=%s attempt=%s db_status=%s db_code=%s",
                         run_id, attempt_no, outcome["db_status"], outcome["db_code"])
        write_local_diagnostics(run_id, attempt_no if isinstance(attempt_no, int) else None, item, outcome)

    async def _record_diagnostics(self, token: str, run_id: UUID, attempt_no: int, diagnostics: dict) -> dict:
        """Write diagnostics; report the HTTP status and a safe error code instead of raising."""
        try:
            response = await self.rrm.http().post(
                f"{self.rrm.url}/rest/v1/rpc/record_generation_attempt_diagnostics", headers=self.rrm.headers(token),
                json={"p_run": str(run_id), "p_attempt": attempt_no, "p_diagnostics": diagnostics}, timeout=30)
        except httpx.HTTPError as exc:
            return {"db_persisted": False, "db_status": None, "db_code": "TRANSPORT_" + type(exc).__name__}
        if response.is_success:
            return {"db_persisted": True, "db_status": response.status_code, "db_code": None}
        return {"db_persisted": False, "db_status": response.status_code, "db_code": _safe_error_code(response)}

    async def finish(self, token: str, run_id: UUID, postflight_hash: str | None,
                     plan: dict | None, content_hash: str | None, error: str | None) -> str:
        result = await self.rpc(token, "finish_generation_run", {
            "p_run": str(run_id), "p_postflight_hash": postflight_hash,
            "p_plan": plan, "p_content_hash": content_hash, "p_error": error,
        })
        if result not in ("UNVERIFIED", "FAILED", "STALE_INPUT"):
            raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE")
        return result

    async def list_runs(self, token: str, offset: int, limit: int, employee_id: UUID | None = None) -> dict:
        params = {
            "select": "id,employee_id,created_by,matrix_id,matrix_revision,stage_set_id,stage_set_code,stage_set_version,provider,model,prompt_version,schema_version,status,error_code,created_at,started_at,completed_at",
            "order": "created_at.desc,id.desc", "offset": str(offset), "limit": str(limit + 1),
        }
        if employee_id is not None:
            params["employee_id"] = f"eq.{employee_id}"
        rows = await self.rrm.rows(token, "generation_runs", params)
        return {"items": rows[:limit], "offset": offset, "limit": limit, "has_more": len(rows) > limit}

    async def detail(self, token: str, run_id: UUID) -> dict:
        rows = await self.rrm.rows(token, "generation_runs", {
            "select": "id,employee_id,employee_profile_id,created_by,matrix_id,matrix_revision,matrix_edit,matrix_lock_version,matrix_snapshot_hash,input_hash,projection_hash,input_snapshot,stage_set_id,stage_set_code,stage_set_version,provider,model,provider_config,prompt_version,template_hash,schema_version,status,error_code,created_at,started_at,completed_at",
            "id": f"eq.{run_id}", "limit": "1",
        })
        if len(rows) != 1:
            raise HTTPException(404, "GENERATION_NOT_FOUND")
        row = rows[0]
        attempts = await self.rrm.rows(token, "generation_attempts", {
            "select": "id,attempt_no,attempt_type,provider_outcome,latency_ms,usage_metadata,response_hash,response_size,parse_outcome,error_code,created_at",
            "run_id": f"eq.{run_id}", "order": "attempt_no.asc", "limit": "4",
        })
        plans = await self.rrm.rows(token, "generated_plans", {
            "select": "id,schema_version,content,content_hash,status,created_at",
            "run_id": f"eq.{run_id}", "limit": "1",
        })
        snapshot = row.pop("input_snapshot")
        row["provenance"] = {
            "context_schema_version": snapshot.get("context_schema_version"),
            "as_of": snapshot.get("as_of"),
            "stage_set": snapshot.get("stage_set"),
            "requirement_ids": [item.get("revision_id") for item in snapshot.get("requirements", [])],
            "source_refs": [evidence for item in snapshot.get("requirements", [])
                            for evidence in item.get("evidence", [])],
        }
        row["attempts"] = attempts
        row["plan"] = plans[0] if plans else None
        return row


def get_generation_store(request: Request) -> GenerationStore:
    settings = get_settings()
    return GenerationStore(RRMRepository(str(settings.supabase_url), settings.supabase_anon_key,
                                         request.app.state.supabase_http))
