from __future__ import annotations
import hashlib
import secrets
import datetime
from functools import wraps

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import select

from ..config import settings
from ..db import get_session
from ..models.orm import ApiKey


# ---------------------------------------------------------------------------
# Key utilities
# ---------------------------------------------------------------------------

def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def generate_key(prefix: str = "ok") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

async def validate_request(request: Request) -> tuple[bool, str]:
    """
    Return (is_valid, role).
    role is one of: "admin" | "writer" | "reader" | "anonymous"
    """
    if not settings.require_auth:
        return True, "admin"

    raw_key = (
        request.headers.get("X-API-Key")
        or request.headers.get("Authorization", "").removeprefix("Bearer ")
        or request.query_params.get("api_key", "")
    ).strip()

    if not raw_key:
        return False, ""

    # Admin master key (env var — never stored in DB)
    admin = settings.admin_api_key
    if admin and secrets.compare_digest(raw_key, admin):
        return True, "admin"

    # DB-stored keys
    async with get_session() as session:
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == hash_key(raw_key),
                ApiKey.is_active.is_(True),
            )
        )
        key_obj = result.scalar_one_or_none()
        if key_obj is None:
            return False, ""
        # Check expiry
        if key_obj.expires_at and key_obj.expires_at < datetime.datetime.utcnow():
            return False, ""
        # Record last use (fire-and-forget; don't fail auth if this errors)
        try:
            key_obj.last_used_at = datetime.datetime.utcnow()
        except Exception:
            pass
        return True, key_obj.role


# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------

class APIKeyMiddleware:
    """
    ASGI middleware that enforces API key authentication.
    Skipped for: /health, /docs, /openapi.json, /metrics.
    """

    PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.PUBLIC_PATHS or not settings.require_auth:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        valid, role = await validate_request(request)
        if not valid:
            resp = JSONResponse(
                {"detail": "Missing or invalid API key. Pass X-API-Key header."},
                status_code=401,
            )
            await resp(scope, receive, send)
            return

        # Inject role into request state for downstream use
        scope.setdefault("state", {})["auth_role"] = role
        await self.app(scope, receive, send)
