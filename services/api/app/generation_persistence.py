"""Phase 4C caller-JWT storage boundary. No service-role credential is used."""

from uuid import UUID

import httpx
from fastapi import HTTPException, Request

from .config import get_settings
from .generation_repository import GenerationRepository
from .generation_service import AttemptTelemetry
from .rrm_repository import RRMRepository


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
        await self.rpc(token, "record_generation_attempt", {
            "p_run": str(run_id), "p_type": item.attempt_type,
            "p_outcome": item.provider_outcome, "p_latency": item.latency_ms,
            "p_usage": {}, "p_response_hash": item.response_hash,
            "p_response_size": item.response_size, "p_parse": item.parse_outcome,
            "p_error": item.error_code,
        })

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
