"""
API key authentication + RBAC enforcement for OpenKNet.

Middleware:   validates every request except public paths
Dependencies: FastAPI Depends() used per-endpoint for role enforcement
"""
from __future__ import annotations
import datetime
import hashlib
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import select

from ..config import settings
from ..db import get_session
from ..models.orm import ApiKey


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_LEVELS: dict[str, int] = {"reader": 0, "writer": 1, "admin": 2}


def _role_level(role: str) -> int:
    return ROLE_LEVELS.get(role, -1)


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
    """Return (is_valid, role). Role: 'admin'|'writer'|'reader'."""
    raw_key = (
        request.headers.get("X-API-Key")
        or request.headers.get("Authorization", "").removeprefix("Bearer ")
        or request.query_params.get("api_key", "")
    ).strip()

    if not raw_key:
        return False, ""

    # Master key from env (never stored in DB)
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
        if key_obj.expires_at and key_obj.expires_at < datetime.datetime.utcnow():
            return False, ""
        try:
            key_obj.last_used_at = datetime.datetime.utcnow()
        except Exception:
            pass
        return True, key_obj.role


# ---------------------------------------------------------------------------
# ASGI middleware — authentication only
# ---------------------------------------------------------------------------

class APIKeyMiddleware:
    """
    Validates API keys and stores the role in request.scope["auth_role"].
    Does NOT enforce roles — that is done per-endpoint via require_role().
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
            scope["auth_role"] = "admin" if not settings.require_auth else "anonymous"
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

        scope["auth_role"] = role
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# FastAPI Depends — per-endpoint role enforcement
# ---------------------------------------------------------------------------

def require_role(minimum: str):
    """
    FastAPI dependency factory. Usage:

        @app.post("/build")
        async def build(role=Depends(require_role("writer"))):
            ...

    When OPENKNET_REQUIRE_AUTH=false, all roles are implicitly "admin".
    """
    min_level = ROLE_LEVELS[minimum]

    async def _check(request: Request) -> str:
        if not settings.require_auth:
            return "admin"
        role = request.scope.get("auth_role", "anonymous")
        if _role_level(role) < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{minimum}' required. Your role: '{role or 'anonymous'}'.",
            )
        return role

    return Depends(_check)


# Convenience shortcuts
require_reader: Depends = require_role("reader")
require_writer: Depends = require_role("writer")
require_admin:  Depends = require_role("admin")
