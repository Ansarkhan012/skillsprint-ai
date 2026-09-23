"""Bound multipart requests before FastAPI's parser spools the upload."""

import asyncio

from starlette.responses import JSONResponse

from .config import get_settings


class UploadRequestLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or scope.get("method") != "POST" or not (
            path == "/api/v1/documents/uploads" or
            (path.startswith("/api/v1/document-versions/") and path.endswith("/retry"))
        ):
            await self.app(scope, receive, send)
            return

        limit = get_settings().max_upload_bytes + 1024 * 1024
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > limit:
            await self._reject(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            await asyncio.Event().wait()

        await self.app(scope, bounded_receive, send)

    @staticmethod
    async def _reject(scope, receive, send):
        response = JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)
        await response(scope, receive, send)
