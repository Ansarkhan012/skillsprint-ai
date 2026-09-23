"""User-token-scoped PostgREST and private Storage operations for Phase 2."""

from urllib.parse import quote
import re

import httpx
from fastapi import HTTPException

from .config import get_settings


BUCKET = "company-documents"


class DocumentRepository:
    def __init__(self, url: str, public_key: str, service_role_key: str | None = None):
        self.url = url.rstrip("/")
        self.public_key = public_key
        self._service_role_key = service_role_key

    def headers(self, token: str) -> dict[str, str]:
        return {"apikey": self.public_key, "Authorization": f"Bearer {token}"}

    @staticmethod
    def check(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            code = response.json().get("code")
        except (ValueError, AttributeError):
            code = None
        if response.status_code == 409 or code == "23505":
            raise HTTPException(status_code=409, detail="DOCUMENT_DUPLICATE")
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")
        if response.status_code in (401, 403) or code == "42501":
            raise HTTPException(status_code=403, detail="DOCUMENT_FORBIDDEN")
        if response.status_code in (400, 422) or code in ("22023", "23503", "23514"):
            raise HTTPException(status_code=422, detail="DOCUMENT_INVALID_OR_STATE_CONFLICT")
        raise HTTPException(status_code=503, detail="DOCUMENT_SERVICE_UNAVAILABLE")

    async def rpc(self, token: str, name: str, payload: dict) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.url}/rest/v1/rpc/{name}", headers=self.headers(token), json=payload
                )
            self.check(response)
            return response.json() if response.content else None
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="DOCUMENT_SERVICE_UNAVAILABLE") from exc

    async def finalize_processing(self, payload: dict) -> None:
        if not self._service_role_key:
            raise HTTPException(status_code=503, detail="DOCUMENT_PROCESSING_NOT_CONFIGURED")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.url}/rest/v1/rpc/finish_document_processing",
                    headers={"apikey": self._service_role_key,
                             "Authorization": f"Bearer {self._service_role_key}"},
                    json=payload,
                )
            self.check(response)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="DOCUMENT_SERVICE_UNAVAILABLE") from exc

    async def rows(self, token: str, table: str, params: dict[str, str]) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{self.url}/rest/v1/{table}", headers=self.headers(token), params=params
                )
            self.check(response)
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="DOCUMENT_SERVICE_UNAVAILABLE") from exc

    async def upload_original(self, token: str, path: str, mime_type: str, data: bytes) -> None:
        if not re.fullmatch(r"[0-9a-f-]{36}/[0-9a-f-]{36}\.(pdf|docx)", path):
            raise HTTPException(status_code=422, detail="UNSAFE_STORAGE_PATH")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.url}/storage/v1/object/{BUCKET}/{quote(path, safe='/')}",
                    headers={**self.headers(token), "Content-Type": mime_type, "x-upsert": "false"},
                    content=data,
                )
            self.check(response)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="DOCUMENT_STORAGE_UNAVAILABLE") from exc

    async def download_original(self, token: str, path: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f-]{36}/[0-9a-f-]{36}\.(pdf|docx)", path):
            raise HTTPException(status_code=422, detail="UNSAFE_STORAGE_PATH")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.url}/storage/v1/object/authenticated/{BUCKET}/{quote(path, safe='/')}",
                    headers=self.headers(token),
                )
            self.check(response)
            return response.content
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="DOCUMENT_STORAGE_UNAVAILABLE") from exc


def get_document_repository() -> DocumentRepository:
    settings = get_settings()
    return DocumentRepository(str(settings.supabase_url), settings.supabase_anon_key,
                              settings.supabase_service_role_key)
