from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger

from .. import __version__
from ..auth.middleware import (
    APIKeyMiddleware, generate_key, hash_key,
    require_reader, require_writer, require_admin,
)
from ..cache.store import get_cache
from ..config import settings
from ..db import check_db_health, get_session, init_db
from ..models.orm import ApiKey
from ..monitoring.metrics import metrics_response
from ..project import Project
from ..backup.manager import BackupManager


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"OpenKNet v{__version__} starting …")
    await init_db()
    await get_cache().connect()
    if settings.require_auth and not settings.admin_api_key:
        key = generate_key("admin")
        logger.warning(
            f"Auth enabled but OPENKNET_ADMIN_API_KEY not set. "
            f"Generated one-time key (not persisted): {key}"
        )
    yield
    logger.info("OpenKNet API shut down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OpenKNet",
    version=__version__,
    description="Production knowledge-network mining API",
    lifespan=lifespan,
)

# Auth middleware (validates key, injects role into scope)
app.add_middleware(APIKeyMiddleware)

# CORS — configurable via OPENKNET_CORS_ORIGINS (default "*" for local/SDK use)
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=settings.cors_origins != "*",
    allow_methods=[m.strip() for m in settings.cors_methods.split(",")],
    allow_headers=[h.strip() for h in settings.cors_headers.split(",")],
)


# ── Error handlers ────────────────────────────────────────────────────────────

@app.exception_handler(FileNotFoundError)
async def _not_found(req: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def _runtime(req: Request, exc: RuntimeError):
    # Includes build-lock conflicts
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _bad_value(req: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _generic(req: Request, exc: Exception):
    logger.exception(exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Meta (public) ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    db = await check_db_health()
    from ..llm.providers import get_llm_info
    return {
        "status": "ok" if db["ok"] else "degraded",
        "version": __version__,
        "db": db,
        "cache": get_cache().backend,
        "auth": settings.require_auth,
        "llm": get_llm_info(),
    }


@app.get("/metrics", tags=["meta"], response_class=PlainTextResponse)
async def metrics():
    content, media_type = metrics_response()
    return PlainTextResponse(content=content, media_type=media_type)


# ── Projects  (reader: read, writer: create/update) ──────────────────────────

@app.get("/projects", tags=["projects"])
async def list_projects(_=require_reader):
    return await Project.list_all()


@app.post("/projects/{project}", tags=["projects"], status_code=201)
async def create_project(
    project: str,
    schema_yaml: str | None = Body(
        None,
        media_type="text/yaml",
        description="Schema YAML content (preferred over schema_path)",
        example="entities:\n  Component:\n    seed_terms: [AuthService]\n",
    ),
    _=require_writer,
):
    """
    Create a project. Pass the schema YAML as the request body.
    The deprecated `schema_path` query param is no longer supported via the API
    to prevent server-side path traversal.
    """
    await Project.init(project, schema_yaml=schema_yaml or None)
    return {"project": project, "created": True}


@app.get("/projects/{project}/stats", tags=["projects"])
async def project_stats(project: str, _=require_reader):
    return await Project(project).stats()


@app.get("/projects/{project}/errors", tags=["projects"])
async def project_errors(project: str, _=require_reader):
    return await Project(project).ingest_errors()


@app.get("/projects/{project}/snapshots", tags=["projects"])
async def project_snapshots(project: str, _=require_reader):
    return await Project(project).snapshots()


# ── Build (writer) ────────────────────────────────────────────────────────────

@app.post("/projects/{project}/build", tags=["build"])
async def build(
    project: str,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False),
    incremental: bool = Query(False),
    _=require_writer,
):
    """
    Build the knowledge graph.
    Returns 409 if a build is already running for this project.
    """
    if sync:
        return await Project(project).build(incremental=incremental)
    background_tasks.add_task(_bg_build, project, incremental)
    return {"project": project, "status": "build started", "incremental": incremental}


async def _bg_build(project: str, incremental: bool) -> None:
    try:
        await Project(project).build(incremental=incremental)
    except RuntimeError as exc:
        logger.warning(f"Build skipped (lock conflict): {exc}")
    except Exception as exc:
        logger.error(f"Background build failed: {exc}")


@app.post("/projects/{project}/deduplicate", tags=["build"])
async def deduplicate(
    project: str,
    threshold: float = Query(0.92, ge=0.5, le=1.0),
    _=require_writer,
):
    return await Project(project).deduplicate(threshold=threshold)


# ── Query (reader) ────────────────────────────────────────────────────────────

@app.get("/rank", tags=["query"])
async def rank(
    project: str = Query(...),
    query: str = Query(...),
    limit: int = Query(10, ge=1, le=100),
    _=require_reader,
):
    return await Project(project).rank(query, limit=limit)


@app.get("/ask", tags=["query"])
async def ask(
    project: str = Query(...),
    question: str = Query(...),
    limit: int = Query(5, ge=1, le=20),
    _=require_reader,
):
    return await Project(project).ask(question, limit=limit)


@app.get("/path", tags=["query"])
async def path(
    project: str = Query(...),
    source: str = Query(...),
    target: str = Query(...),
    max_depth: int = Query(4, ge=1, le=6),
    _=require_reader,
):
    return await Project(project).path(source, target, max_depth=max_depth)


# ── Feedback (reader can submit) ─────────────────────────────────────────────

@app.post("/feedback", tags=["feedback"])
async def feedback(
    project: str = Query(...),
    entity_id: str = Query(...),
    query: str = Query(...),
    rating: int = Query(..., ge=1, le=5),
    comment: str | None = Query(None),
    _=require_reader,
):
    return await Project(project).submit_feedback(entity_id, query, rating, comment)


# ── Backup (admin) ────────────────────────────────────────────────────────────

@app.post("/backup", tags=["ops"])
async def create_backup(label: str = Query("manual"), _=require_admin):
    path = await BackupManager().backup(label=label)
    return {"path": str(path), "size_kb": round(path.stat().st_size / 1024, 1)}


@app.get("/backup/list", tags=["ops"])
async def list_backups(_=require_admin):
    return [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in BackupManager().list_backups()
    ]


# ── API Keys (admin) ──────────────────────────────────────────────────────────

@app.post("/keys", tags=["auth"])
async def create_api_key(
    name: str = Query(...),
    role: str = Query("reader", pattern="^(reader|writer|admin)$"),
    project: str | None = Query(None),
    _=require_admin,
):
    raw = generate_key()
    kid = hash_key(raw)[:16]
    async with get_session() as session:
        session.add(ApiKey(
            id=kid, key_hash=hash_key(raw), name=name,
            role=role, project_id=project, is_active=True,
        ))
    return {"key": raw, "id": kid, "role": role, "note": "Store this — shown only once."}


@app.get("/keys", tags=["auth"])
async def list_api_keys(_=require_admin):
    async with get_session() as session:
        from sqlalchemy import select
        res = await session.execute(select(ApiKey).where(ApiKey.is_active.is_(True)))
        return [
            {
                "id": k.id, "name": k.name, "role": k.role, "project": k.project_id,
                "created_at": k.created_at.isoformat(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in res.scalars()
        ]


@app.delete("/keys/{key_id}", tags=["auth"])
async def revoke_api_key(key_id: str, _=require_admin):
    async with get_session() as session:
        from sqlalchemy import select
        res = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = res.scalar_one_or_none()
        if not key:
            raise HTTPException(status_code=404, detail="Key not found")
        key.is_active = False
    return {"revoked": key_id}
