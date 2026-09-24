"""User-JWT PostgREST access for the applied Phase 3A.1 contract."""

import httpx
from fastapi import HTTPException, Request

from .config import get_settings


SAFE_ERRORS = {
    "RRM_EDIT_CONFLICT": (409, "RRM_EDIT_CONFLICT"),
    "RRM_STALE_SUBMISSION": (409, "RRM_STALE_SUBMISSION"),
    "RRM_STALE_SNAPSHOT": (409, "RRM_STALE_SNAPSHOT"),
    "RRM_STALE_REVISION": (409, "RRM_STALE_REVISION"),
    "RRM_SELF_REVIEW_FORBIDDEN": (403, "RRM_SELF_REVIEW_FORBIDDEN"),
    "RRM_DRAFT_OWNER_REQUIRED": (403, "RRM_DRAFT_OWNER_REQUIRED"),
    "RRM_FORBIDDEN": (403, "RRM_FORBIDDEN"),
    "RRM_INVALID_OR_STALE_SOURCE": (409, "RRM_INVALID_OR_STALE_SOURCE"),
    "RRM_BLOCKING_ISSUE_OR_EMPTY_MATRIX": (409, "RRM_BLOCKING_ISSUE_OR_EMPTY_MATRIX"),
    "RRM_DEPENDENCY_CYCLE_OR_ORDER": (422, "RRM_DEPENDENCY_CYCLE_OR_ORDER"),
    "RRM_DOWNGRADE_MANUAL_REVIEW": (422, "RRM_DOWNGRADE_MANUAL_REVIEW"),
    "RRM_DOWNGRADE_EVIDENCE_MISMATCH": (422, "RRM_DOWNGRADE_EVIDENCE_MISMATCH"),
    "RRM_REASON_REQUIRED": (422, "RRM_REASON_REQUIRED"),
    "RRM_NOT_APPROVED": (409, "RRM_NOT_APPROVED"),
    "RRM_TIMING_MANUAL_REVIEW": (422, "RRM_TIMING_MANUAL_REVIEW"),
}


class RRMRepository:
    def __init__(self, url: str, public_key: str, client: httpx.AsyncClient | None = None):
        self.url = url.rstrip("/")
        self.public_key = public_key
        self.client = client

    def http(self) -> httpx.AsyncClient:
        if self.client is None:
            raise RuntimeError("RRM HTTP client is not initialized")
        return self.client

    def headers(self, token: str) -> dict[str, str]:
        return {"apikey": self.public_key, "Authorization": f"Bearer {token}"}

    @staticmethod
    def check(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            error = response.json()
            code = error.get("code", "")
            message = error.get("message", "")
        except (ValueError, AttributeError):
            code = message = ""
        # Only published RRM error identifiers cross the API boundary.
        if message in SAFE_ERRORS:
            status, public_code = SAFE_ERRORS[message]
            raise HTTPException(status_code=status, detail=public_code)
        if code == "40001" or response.status_code == 409:
            raise HTTPException(status_code=409, detail="RRM_CONFLICT")
        if code == "42501" or response.status_code in (401, 403):
            raise HTTPException(status_code=403, detail="RRM_FORBIDDEN")
        if code == "P0002" or response.status_code == 404:
            raise HTTPException(status_code=404, detail="RRM_NOT_FOUND")
        if code in ("22023", "23503", "23505", "23514") or response.status_code in (400, 422):
            raise HTTPException(status_code=422, detail="RRM_INVALID_INPUT")
        raise HTTPException(status_code=503, detail="RRM_SERVICE_UNAVAILABLE")

    async def rows(self, token: str, table: str, params: dict[str, str]) -> list[dict]:
        try:
            response = await self.http().get(f"{self.url}/rest/v1/{table}",
                                             headers=self.headers(token), params=params, timeout=15)
            self.check(response)
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="RRM_SERVICE_UNAVAILABLE") from exc

    async def rpc(self, token: str, name: str, payload: dict) -> object:
        try:
            response = await self.http().post(f"{self.url}/rest/v1/rpc/{name}",
                                              headers=self.headers(token), json=payload, timeout=30)
            self.check(response)
            return response.json() if response.content else None
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="RRM_SERVICE_UNAVAILABLE") from exc


def get_rrm_repository(request: Request) -> RRMRepository:
    settings = get_settings()
    return RRMRepository(str(settings.supabase_url), settings.supabase_anon_key,
                         request.app.state.supabase_http)
