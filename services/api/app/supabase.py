from functools import lru_cache
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from .config import get_settings
from .models import AppRole, Profile


class SupabaseGateway:
    def __init__(self, url: str, anon_key: str) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    async def request(self, token: str, table: str, params: dict[str, str]) -> list[dict]:
        headers = {"apikey": self.anon_key, "Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    f"{self.url}/rest/v1/{table}", headers=headers, params=params
                )
                if response.status_code in (401, 403):
                    raise HTTPException(status_code=403, detail="DATA_ACCESS_DENIED")
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="DATA_SERVICE_UNAVAILABLE") from exc

    async def get_profile(self, token: str, user_id: UUID) -> Profile | None:
        profiles = await self.request(
            token,
            "profiles",
            {"select": "id,auth_user_id,display_name,status", "auth_user_id": f"eq.{user_id}", "limit": "1"},
        )
        if len(profiles) != 1:
            return None
        raw = profiles[0]
        memberships = await self.request(
            token, "profile_roles", {"select": "role", "profile_id": f"eq.{raw['id']}"}
        )
        try:
            result = Profile(**raw, roles=frozenset(AppRole(item["role"]) for item in memberships))
            return result if result.auth_user_id == user_id else None
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=403, detail="INVALID_PROFILE") from exc

    async def create(self, token: str, table: str, payload: dict) -> dict:
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {token}",
            "Prefer": "return=representation",
        }
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(
                    f"{self.url}/rest/v1/{table}", headers=headers, json=payload
                )
            if response.status_code == 409:
                raise HTTPException(status_code=409, detail="RECORD_CONFLICT")
            if response.status_code in (400, 422):
                raise HTTPException(status_code=422, detail="INVALID_REFERENCE_OR_VALUE")
            if response.status_code in (401, 403):
                raise HTTPException(status_code=403, detail="FORBIDDEN_ROLE")
            response.raise_for_status()
            items = response.json()
            return items[0]
        except (httpx.HTTPError, ValueError, IndexError) as exc:
            raise HTTPException(status_code=503, detail="DATA_SERVICE_UNAVAILABLE") from exc


@lru_cache
def get_gateway() -> SupabaseGateway:
    settings = get_settings()
    return SupabaseGateway(str(settings.supabase_url), settings.supabase_anon_key)
