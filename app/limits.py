from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings


class UploadGuard:
    """Bound multipart input before it is spooled to the temporary directory."""

    def __init__(self, app: ASGIApp, settings: Callable[[], Settings]):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if scope["method"] in {"POST", "PUT", "DELETE", "PATCH"}:
            origin = headers.get("origin")
            if origin and urlparse(origin).netloc != headers.get("host"):
                await JSONResponse({"detail": "不允许跨站修改任务。"}, status_code=403)(
                    scope, receive, send
                )
                return
        if scope["path"] != "/api/jobs" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        # Allow bounded overhead for multipart boundaries and form options.
        limit = self.settings().max_upload_mb * 1024 * 1024 + 1024 * 1024
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = limit + 1
        if length > limit or length < 0:
            await JSONResponse({"detail": "上传超过大小限制。"}, status_code=413)(
                scope, receive, send
            )
            return
        received = 0
        exceeded = False

        async def bounded_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    # Multipart parser closes temporary files for this exception.
                    raise MultiPartException("上传超过大小限制。")
            return message

        async def bounded_send(message: Message) -> None:
            if exceeded and message["type"] == "http.response.start":
                message["status"] = 413
            await send(message)

        await self.app(scope, bounded_receive, bounded_send)
