from __future__ import annotations

import asyncio
import concurrent.futures
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from loguru import logger

from .exceptions import ProjectNotFoundError, ProjectNotInitializedError
from .models import (
    AskResponse,
    BuildResponse,
    EntityResult,
    IngestResponse,
    PathResponse,
    PathResult,
    RankResponse,
    StatsResponse,
    BuildInfo,
)


# ---------------------------------------------------------------------------
# Sync helper — works both inside and outside a running event loop
# ---------------------------------------------------------------------------

def _run_sync(coro):
    """
    Run an async coroutine synchronously.
    Compatible with Jupyter notebooks (where a loop is already running).
    """
    try:
        asyncio.get_running_loop()
        # Already inside a loop (Jupyter / async framework): offload to a thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# OpenKNet client
# ---------------------------------------------------------------------------

class OpenKNet:
    """
    Primary SDK entry point for OpenKNet.

    Usage — async (recommended):

        async with OpenKNet.open("my-project", schema="schema.yaml") as knet:
            await knet.ingest("docs/")
            await knet.build()
            answer = await knet.ask("what caused the outage?")

    Usage — sync (scripts / notebooks):

        knet = OpenKNet("my-project")
        knet.initialize_sync(schema="schema.yaml")
        knet.ingest_sync("docs/")
        knet.build_sync()
        answer = knet.ask_sync("what caused the outage?")

    Usage — standalone (no init required if project already exists):

        knet = OpenKNet("my-project")
        print(knet.stats_sync())
    """

    def __init__(self, project: str) -> None:
        self.project = project
        self._initialized = False

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        project: str,
        schema: str | Path | None = None,
    ) -> AsyncIterator["OpenKNet"]:
        """Async context manager: initializes project on enter."""
        client = cls(project)
        await client.initialize(schema=schema)
        yield client

    @classmethod
    def create(
        cls,
        project: str,
        schema: str | Path | None = None,
    ) -> "OpenKNet":
        """Sync factory: creates and initializes the project."""
        client = cls(project)
        client.initialize_sync(schema=schema)
        return client

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self, schema: str | Path | None = None) -> "OpenKNet":
        """Create the project in the store (idempotent)."""
        from ..project import Project
        from ..db import init_db
        await init_db()
        await Project.init(self.project, schema=schema)
        self._initialized = True
        return self

    def initialize_sync(self, schema: str | Path | None = None) -> "OpenKNet":
        return _run_sync(self.initialize(schema=schema))

    def _project(self):
        from ..project import Project
        return Project(self.project)

    # ------------------------------------------------------------------
    # Async API
    # ------------------------------------------------------------------

    async def ingest(self, path: str | Path) -> IngestResponse:
        """Ingest documents from *path* (file or directory) into the project."""
        try:
            raw = await self._project().ingest(path)
        except FileNotFoundError as exc:
            raise ProjectNotFoundError(str(exc)) from exc
        return IngestResponse(**raw)

    async def build(self) -> BuildResponse:
        """Extract entities and relations and persist the knowledge graph."""
        try:
            raw = await self._project().build()
        except FileNotFoundError as exc:
            raise ProjectNotFoundError(str(exc)) from exc
        return BuildResponse(**raw)

    async def rank(self, query: str, limit: int = 10) -> RankResponse:
        """Rank entities by relevance to *query*."""
        raw = await self._project().rank(query, limit=limit)
        return RankResponse(
            project=raw["project"],
            query=raw["query"],
            total_matching=raw["total_matching"],
            results=[
                EntityResult(
                    id=r["entity"]["id"],
                    name=r["entity"]["name"],
                    type=r["entity"]["type"],
                    mention_count=r["entity"]["mention_count"],
                    score=r["score"],
                    degree=r["degree"],
                )
                for r in raw["results"]
            ],
        )

    async def ask(self, question: str, limit: int = 5) -> AskResponse:
        """Ask a natural-language question; returns entities, snippets, and a summary."""
        raw = await self._project().ask(question, limit=limit)
        return AskResponse(
            project=raw["project"],
            question=raw["question"],
            answer=raw["answer"],
            entities=raw["entities"],
            snippets=raw["snippets"],
            results=[
                EntityResult(
                    id=r["entity"]["id"],
                    name=r["entity"]["name"],
                    type=r["entity"]["type"],
                    mention_count=r["entity"]["mention_count"],
                    score=r["score"],
                    degree=r["degree"],
                )
                for r in raw["results"]
            ],
        )

    async def path(
        self,
        source: str,
        target: str,
        max_depth: int = 4,
    ) -> PathResponse:
        """Find relationship paths between *source* and *target* entities."""
        raw = await self._project().path(source, target, max_depth=max_depth)
        return PathResponse(
            project=raw["project"],
            source=raw["source"],
            target=raw["target"],
            found=raw["found"],
            paths=[PathResult(**p) for p in raw["paths"]],
        )

    async def stats(self) -> StatsResponse:
        """Return project statistics."""
        try:
            raw = await self._project().stats()
        except FileNotFoundError as exc:
            raise ProjectNotFoundError(str(exc)) from exc
        last = raw.get("last_build")
        return StatsResponse(
            project=raw["project"],
            documents=raw["documents"],
            chunks=raw["chunks"],
            entities=raw["entities"],
            relations=raw["relations"],
            evidence=raw["evidence"],
            last_build=BuildInfo(**last) if last else None,
        )

    async def entities(self, entity_type: str | None = None) -> list[EntityResult]:
        """Return all entities, optionally filtered by type."""
        resp = await self.rank("", limit=500)
        if entity_type:
            return [e for e in resp.results if e.type == entity_type]
        return resp.results

    # ------------------------------------------------------------------
    # Sync wrappers (convenience for scripts / notebooks)
    # ------------------------------------------------------------------

    def ingest_sync(self, path: str | Path) -> IngestResponse:
        return _run_sync(self.ingest(path))

    def build_sync(self) -> BuildResponse:
        return _run_sync(self.build())

    def rank_sync(self, query: str, limit: int = 10) -> RankResponse:
        return _run_sync(self.rank(query, limit=limit))

    def ask_sync(self, question: str, limit: int = 5) -> AskResponse:
        return _run_sync(self.ask(question, limit=limit))

    def path_sync(self, source: str, target: str, max_depth: int = 4) -> PathResponse:
        return _run_sync(self.path(source, target, max_depth=max_depth))

    def stats_sync(self) -> StatsResponse:
        return _run_sync(self.stats())

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"OpenKNet(project={self.project!r}, initialized={self._initialized})"
