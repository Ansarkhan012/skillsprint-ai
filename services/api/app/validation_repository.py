"""Caller-JWT reads; only backend finalization uses the existing trusted credential."""
import asyncio
import httpx
from fastapi import HTTPException, Request

from .config import get_settings
from .generation_repository import GenerationRepository
from .rrm_repository import RRMRepository


class ValidationRepository(GenerationRepository):
    def __init__(self, rrm, trusted_key=None):
        super().__init__(rrm)
        self._trusted_key = trusted_key

    async def load_plan(self, token, plan_id):
        plans = await self.rrm.rows(token, "generated_plans", {
            "select": "id,run_id,status,schema_version,content,content_hash", "id": f"eq.{plan_id}", "limit": "1"})
        if len(plans) != 1:
            raise HTTPException(404, "VALIDATION_PLAN_NOT_FOUND")
        runs = await self.rrm.rows(token, "generation_runs", {
            "select": "id,employee_id,employee_profile_id,created_by,status,completed_at,input_snapshot,input_hash,projection_hash,prompt_version,template_hash,provider,model,schema_version",
            "id": f"eq.{plans[0]['run_id']}", "limit": "1"})
        if len(runs) != 1:
            raise HTTPException(404, "VALIDATION_PLAN_NOT_FOUND")
        return plans[0], runs[0]

    async def persist(self, actor_id, plan_id, result):
        if not self._trusted_key:
            raise HTTPException(503, "VALIDATION_PERSISTENCE_NOT_CONFIGURED")
        return await self._rpc("record_python_validation", {
            "p_actor": str(actor_id), "p_plan": str(plan_id), "p_result": result,
        }, {"apikey": self._trusted_key, "Authorization": f"Bearer {self._trusted_key}"})

    async def review(self, token, validation_id, request):
        return await self._rpc("review_validated_plan", {
            "p_validation": str(validation_id), "p_action": request.action, "p_reason": request.reason,
        }, self.rrm.headers(token))

    async def _rpc(self, name, payload, headers):
        try:
            response = await self.rrm.http().post(f"{self.rrm.url}/rest/v1/rpc/{name}",
                headers=headers, json=payload, timeout=30)
        except httpx.HTTPError:
            raise HTTPException(503, "VALIDATION_DATA_UNAVAILABLE") from None
        if not response.is_success:
            # Never forward raw SQL/provider messages or response bodies.
            if response.status_code in (401, 403):
                raise HTTPException(403, "VALIDATION_FORBIDDEN")
            if response.status_code in (400, 409, 422):
                raise HTTPException(409, "VALIDATION_STATE_CONFLICT")
            raise HTTPException(503, "VALIDATION_DATA_UNAVAILABLE")
        try:
            return response.json()
        except ValueError:
            raise HTTPException(503, "VALIDATION_DATA_UNAVAILABLE") from None

    async def read(self, token, validation_id=None, plan_id=None):
        params = {"select": "*", "limit": "1", "order": "completed_at.desc,id.desc"}
        params["id" if validation_id else "generated_plan_id"] = f"eq.{validation_id or plan_id}"
        rows = await self.rrm.rows(token, "validation_runs", params)
        if len(rows) != 1:
            raise HTTPException(404, "VALIDATION_NOT_FOUND")
        result = rows[0]
        vid = result["id"]
        count = result.get("summary", {}).get("finding_count")
        if not isinstance(count, int) or not 0 <= count <= 2000:
            raise HTTPException(503, "VALIDATION_DATA_UNAVAILABLE")
        pages = await asyncio.gather(*(self.rrm.rows(token, "validation_findings", {
            "select": "*", "validation_run_id": f"eq.{vid}", "order": "ordinal.asc",
            "offset": str(offset), "limit": "200"}) for offset in range(0, count, 200)))
        result["findings"] = [item for page in pages for item in page]
        decision = await self.rrm.rows(token, "jev_decisions", {
            "select": "*", "validation_run_id": f"eq.{vid}", "limit": "1"})
        if len(result["findings"]) != count or len(decision) != 1:
            raise HTTPException(503, "VALIDATION_DATA_UNAVAILABLE")
        result["decision"] = decision[0]
        result["review_actions"] = await self.rrm.rows(token, "plan_review_actions", {
            "select": "*", "validation_run_id": f"eq.{vid}", "order": "created_at.desc,id.desc", "limit": "101"})
        result["review_actions_has_more"] = len(result["review_actions"]) > 100
        result["review_actions"] = result["review_actions"][:100]
        return result


def get_validation_repository(request: Request):
    settings = get_settings()
    return ValidationRepository(RRMRepository(str(settings.supabase_url), settings.supabase_anon_key,
        request.app.state.supabase_http), settings.supabase_service_role_key)
