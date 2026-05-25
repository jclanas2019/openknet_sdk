"""
ARQ background worker tasks.

Usage:
    # Start worker (requires Redis)
    arq openknet.workers.tasks.WorkerSettings

    # Enqueue a build from Python
    from arq import create_pool
    from openknet.workers.tasks import enqueue_build

    redis = await create_pool(RedisSettings.from_dsn("redis://localhost"))
    await enqueue_build(redis, "my-project")
"""
from __future__ import annotations

from loguru import logger

from ..config import settings


# ---------------------------------------------------------------------------
# Task functions
# ---------------------------------------------------------------------------

async def build_project(ctx: dict, project_name: str, incremental: bool = False) -> dict:
    """Background build task."""
    from ..project import Project
    logger.info(f"[worker] build_project: {project_name} incremental={incremental}")
    result = await Project(project_name).build(incremental=incremental)
    logger.success(f"[worker] build done: {result}")
    return result


async def ingest_documents(ctx: dict, project_name: str, path: str) -> dict:
    """Background ingest task."""
    from ..project import Project
    logger.info(f"[worker] ingest: {project_name} ← {path}")
    result = await Project(project_name).ingest(path)
    logger.success(f"[worker] ingest done: {result}")
    return result


async def deduplicate_project(ctx: dict, project_name: str, threshold: float | None = None) -> dict:
    """Background deduplication task."""
    from ..project import Project
    return await Project(project_name).deduplicate(threshold=threshold)


# ---------------------------------------------------------------------------
# Worker startup / shutdown hooks
# ---------------------------------------------------------------------------

async def startup(ctx: dict) -> None:
    from ..db import init_db
    from ..cache.store import get_cache
    await init_db()
    await get_cache().connect()
    logger.info("ARQ worker ready")


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ worker shutting down")


# ---------------------------------------------------------------------------
# WorkerSettings
# ---------------------------------------------------------------------------

class WorkerSettings:
    functions = [build_project, ingest_documents, deduplicate_project]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = settings.worker_concurrency
    job_timeout = 3600  # 1 hour max per job

    @property
    def redis_settings(self):
        try:
            from arq.connections import RedisSettings
            url = settings.redis_url or "redis://localhost:6379"
            return RedisSettings.from_dsn(url)
        except ImportError:
            raise RuntimeError("arq is not installed. pip install arq")


# ---------------------------------------------------------------------------
# Convenience enqueue helpers
# ---------------------------------------------------------------------------

async def enqueue_build(redis, project_name: str, incremental: bool = False) -> str:
    """Enqueue a build job and return its job ID."""
    job = await redis.enqueue_job("build_project", project_name, incremental)
    return job.job_id


async def enqueue_ingest(redis, project_name: str, path: str) -> str:
    job = await redis.enqueue_job("ingest_documents", project_name, path)
    return job.job_id
