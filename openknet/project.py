from __future__ import annotations
import datetime
import difflib
import hashlib
import time
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import selectinload

from .config import settings
from .db import get_session, init_db
from .extract.pipeline import ExtractionPipeline, _id
from .ingest.chunker import chunk_text
from .ingest.readers import is_supported, read_document
from .models.orm import (
    BuildLog, Chunk, Document, Entity, EntityFeedback,
    Evidence, GraphSnapshot, IngestError,
    ProcessedChunk, Project as ProjectORM, Relation,
)
from .monitoring.metrics import (
    BUILD_DURATION, ENTITIES_GAUGE, INGEST_DOCS,
    INGEST_ERRORS, RELATIONS_GAUGE, DEDUP_MERGES, timed,
)
from .search.fts import fts_delete_project, fts_insert_chunk, fts_search
from .search.graph import bfs_paths
from .search.index_cache import (
    ChunkData, EntityData, ProjectIndex,
    get_index, invalidate, put_index,
)
from .search.ranker import UnifiedRanker, score_entity_data


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65_536), b""):
            h.update(block)
    return h.hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────

import asyncio as _asyncio
import hashlib as _hashlib

# ── Per-project build locks ────────────────────────────────────────────────
# Prevents concurrent builds (full + incremental) on the same project.
# In-process lock (asyncio.Lock) covers single-process deployments.
# PostgreSQL advisory lock covers multi-process deployments.

_build_locks: dict[str, _asyncio.Lock] = {}
_locks_meta = _asyncio.Lock()


async def _acquire_build_lock(project_name: str, project_id: str, session) -> None:
    global _build_locks
    async with _locks_meta:
        if project_name not in _build_locks:
            _build_locks[project_name] = _asyncio.Lock()
    lock = _build_locks[project_name]
    if lock.locked():
        raise RuntimeError(
            f"Build already running for project {project_name!r}. "
            "Wait for it to finish or use incremental=True."
        )
    await lock.acquire()
    from .db import current_dialect
    if current_dialect() == "postgresql":
        lid = int(_hashlib.md5(project_id.encode()).hexdigest()[:8], 16) % (2**31 - 1)
        await session.execute(text("SELECT pg_advisory_lock(:l)"), {"l": lid})


async def _release_build_lock(project_name: str, project_id: str, session) -> None:
    lock = _build_locks.get(project_name)
    if lock and lock.locked():
        lock.release()
    from .db import current_dialect
    if current_dialect() == "postgresql":
        lid = int(_hashlib.md5(project_id.encode()).hexdigest()[:8], 16) % (2**31 - 1)
        try:
            await session.execute(text("SELECT pg_advisory_unlock(:l)"), {"l": lid})
        except Exception:
            pass


import re as _re

def _numeric_variants(a: str, b: str) -> bool:
    """Return True when two strings differ only in a trailing number sequence."""
    na = _re.sub(r'\d+$', '', a.strip())
    nb = _re.sub(r'\d+$', '', b.strip())
    # Also handle embedded numbers like "error 503" vs "error 500"
    na2 = _re.sub(r'\d+', '#', a.strip().lower())
    nb2 = _re.sub(r'\d+', '#', b.strip().lower())
    return (na.lower() == nb.lower() and na != a) or (na2 == nb2 and na2 != a.strip().lower())


class Project:
    def __init__(self, name: str) -> None:
        self.name = name

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _require(self, session) -> ProjectORM:
        result = await session.execute(
            select(ProjectORM).where(ProjectORM.name == self.name)
        )
        p = result.scalar_one_or_none()
        if p is None:
            raise FileNotFoundError(f"Project not found: {self.name!r}")
        return p

    async def _last_build(self, session, project_id: str, status: str = "done"):
        result = await session.execute(
            select(BuildLog)
            .where(BuildLog.project_id == project_id, BuildLog.status == status)
            .order_by(BuildLog.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _build_index(self, session, proj: ProjectORM) -> ProjectIndex:
        """Build the in-memory ProjectIndex from DB data."""
        chunks_res = await session.execute(
            select(Chunk).join(Document).where(Document.project_id == proj.id)
        )
        orm_chunks = chunks_res.scalars().all()
        chunk_data = {c.id: ChunkData(id=c.id, text=c.text) for c in orm_chunks}

        ents_res = await session.execute(
            select(Entity).where(Entity.project_id == proj.id)
            .options(selectinload(Entity.source_relations), selectinload(Entity.target_relations))
        )
        orm_entities = ents_res.scalars().all()

        entity_list: list[EntityData] = []
        for ent in orm_entities:
            if ent.canonical_id:
                continue  # skip duplicates merged by dedup
            name_l = ent.name.lower()
            relevant = [cd for cd in chunk_data.values() if name_l in cd.text.lower()]
            entity_list.append(EntityData(
                id=ent.id, name=ent.name, type=ent.type,
                mention_count=ent.mention_count,
                degree=len(ent.source_relations) + len(ent.target_relations),
                relevant_chunks=relevant,
            ))

        ranker = UnifiedRanker()
        if orm_chunks:
            ranker.fit([c.text for c in orm_chunks])

        last = await self._last_build(session, proj.id)
        build_id = last.id if last else -1
        index = ProjectIndex(build_log_id=build_id, ranker=ranker, entities=entity_list)
        put_index(self.name, index)
        logger.debug(f"Index built: {len(entity_list)} entities, ranker={ranker.backend}")
        return index

    async def _get_index(self, session, proj: ProjectORM) -> ProjectIndex:
        cached = get_index(self.name)
        current_id = (await self._last_build(session, proj.id)).id if await self._last_build(session, proj.id) else -1
        if cached is not None and cached.build_log_id == current_id:
            from .monitoring.metrics import CACHE_HITS
            CACHE_HITS.labels(backend="memory").inc()
            return cached
        from .monitoring.metrics import CACHE_MISSES
        CACHE_MISSES.labels(backend="memory").inc()
        return await self._build_index(session, proj)

    async def _save_snapshot(self, session, proj: ProjectORM, build_log_id: int, stats: dict) -> None:
        schema_hash = hashlib.sha256(proj.schema_yaml.encode()).hexdigest()[:16]
        session.add(GraphSnapshot(
            project_id=proj.id, build_log_id=build_log_id,
            entity_count=stats["entities"], relation_count=stats["relations"],
            evidence_count=stats["evidence"], schema_hash=schema_hash,
        ))
        # Prune old snapshots
        old_res = await session.execute(
            select(GraphSnapshot).where(GraphSnapshot.project_id == proj.id)
            .order_by(GraphSnapshot.created_at.desc())
            .offset(settings.max_snapshots)
        )
        for old in old_res.scalars():
            await session.delete(old)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    async def init(
        cls,
        name: str,
        schema: str | Path | None = None,
        schema_yaml: str | None = None,   # raw YAML string — safer for API calls
    ) -> "Project":
        await init_db()
        if schema_yaml is None:
            schema_yaml = Path(schema).read_text(encoding="utf-8") if schema else "entities: {}\nrelations: {}\n"
        pid = _id("proj", name)
        async with get_session() as session:
            result = await session.execute(select(ProjectORM).where(ProjectORM.name == name))
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(ProjectORM(id=pid, name=name, schema_yaml=schema_yaml))
                logger.info(f"Created project {name!r}")
            elif schema:
                existing.schema_yaml = schema_yaml
                logger.info(f"Updated schema for {name!r}")
        return cls(name)

    async def schema(self) -> dict[str, Any]:
        async with get_session() as session:
            p = await self._require(session)
            return yaml.safe_load(p.schema_yaml) or {}

    # ── ingest ────────────────────────────────────────────────────────────────

    async def ingest(self, path: str | Path) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Input path not found: {path}")

        max_bytes = settings.max_file_size_mb * 1024 * 1024
        candidates = [p] if p.is_file() else sorted(
            f for f in p.rglob("*") if f.is_file() and is_supported(f)
        )
        oversized = [f for f in candidates if f.stat().st_size > max_bytes]
        files = [f for f in candidates if f.stat().st_size <= max_bytes]
        if oversized:
            logger.warning(f"Skipping {len(oversized)} file(s) > {settings.max_file_size_mb} MB")

        added = chunks_added = 0

        async with get_session() as session:
            proj = await self._require(session)

            path_res = await session.execute(
                select(Document.path, Document.text_hash).where(Document.project_id == proj.id)
            )
            existing_paths: set[str] = set()
            existing_hashes: set[str] = set()
            for row in path_res:
                existing_paths.add(row.path)
                existing_hashes.add(row.text_hash)

            for f in files:
                fstr = str(f.resolve())
                fhash = _file_hash(f)

                if fstr in existing_paths or fhash in existing_hashes:
                    logger.debug(f"Skip (duplicate): {f.name}")
                    continue

                try:
                    text_content = read_document(f)
                except Exception as exc:
                    logger.error(f"Could not read {f.name}: {exc}")
                    session.add(IngestError(
                        project_id=proj.id, path=fstr,
                        error_type=type(exc).__name__, message=str(exc),
                    ))
                    INGEST_ERRORS.labels(project=self.name, error_type=type(exc).__name__).inc()
                    continue

                if not text_content.strip():
                    logger.warning(f"Empty document: {f.name}")
                    continue

                doc_id = _id("doc", proj.id, fhash)
                session.add(Document(
                    id=doc_id, project_id=proj.id, path=fstr,
                    title=f.name, format=f.suffix.lower().lstrip("."),
                    size_bytes=f.stat().st_size, text_hash=fhash,
                    doc_metadata={"suffix": f.suffix},
                ))

                doc_chunks = chunk_text(text_content)
                for c in doc_chunks:
                    chk_id = _id("chk", doc_id, str(c.ordinal))
                    session.add(Chunk(
                        id=chk_id, document_id=doc_id, text=c.text,
                        ordinal=c.ordinal, char_start=c.char_start, char_end=c.char_end,
                    ))
                    await fts_insert_chunk(session, chk_id, proj.id, c.text)

                chunks_added += len(doc_chunks)
                added += 1
                existing_paths.add(fstr)
                existing_hashes.add(fhash)
                fmt = f.suffix.lower().lstrip(".")
                INGEST_DOCS.labels(project=self.name, format=fmt).inc()
                logger.info(f"Ingested {f.name!r}: {len(text_content):,} chars → {len(doc_chunks)} chunks")

            doc_total  = await session.scalar(select(func.count()).where(Document.project_id == proj.id).select_from(Document)) or 0
            chunk_total = await session.scalar(select(func.count()).select_from(Chunk).join(Document).where(Document.project_id == proj.id)) or 0

        return dict(project=self.name, documents_added=added, documents_total=doc_total,
                    chunks_added=chunks_added, chunks_total=chunk_total, skipped_oversized=len(oversized))

    # ── build ─────────────────────────────────────────────────────────────────

    async def build(self, incremental: bool = False) -> dict[str, Any]:
        schema_data = await self.schema()
        pipeline = ExtractionPipeline(schema_data)
        batch = settings.build_batch_size
        t0 = time.monotonic()

        # Optional: backup before full rebuild
        if settings.backup_on_build and not incremental:
            from .backup.manager import BackupManager
            try:
                bk = BackupManager()
                await bk.backup(label="pre_build")
            except Exception as exc:
                logger.warning(f"Pre-build backup failed: {exc}")

        async with get_session() as session:
            proj = await self._require(session)
            await _acquire_build_lock(self.name, proj.id, session)
            build_log = BuildLog(project_id=proj.id, status="running",
                                 mode="incremental" if incremental else "full")
            session.add(build_log)
            await session.flush()

            try:
                if incremental:
                    # Only process chunks NOT yet in processed_chunks
                    chunks_res = await session.execute(
                        select(Chunk).join(Document)
                        .where(Document.project_id == proj.id)
                        .where(
                            ~Chunk.id.in_(select(ProcessedChunk.chunk_id))
                        )
                        .order_by(Chunk.id)
                    )
                    all_chunks = chunks_res.scalars().all()
                    logger.info(f"Incremental build: {len(all_chunks)} new chunks")

                    # Load existing entity map
                    ents_res = await session.execute(
                        select(Entity).where(Entity.project_id == proj.id)
                    )
                    entities_by_key: dict[tuple, Entity] = {
                        (e.type, e.name.lower()): e for e in ents_res.scalars()
                    }
                else:
                    # Full rebuild: clear graph
                    await session.execute(delete(Evidence).where(
                        Evidence.relation_id.in_(
                            select(Relation.id).where(Relation.project_id == proj.id)
                        )
                    ))
                    await session.execute(delete(ProcessedChunk).where(
                        ProcessedChunk.chunk_id.in_(
                            select(Chunk.id).join(Document).where(Document.project_id == proj.id)
                        )
                    ))
                    await session.execute(delete(Relation).where(Relation.project_id == proj.id))
                    await session.execute(delete(Entity).where(Entity.project_id == proj.id))
                    await session.flush()

                    chunks_res = await session.execute(
                        select(Chunk).join(Document).where(Document.project_id == proj.id).order_by(Chunk.id)
                    )
                    all_chunks = chunks_res.scalars().all()
                    entities_by_key = {}
                    logger.info(f"Full build: {len(all_chunks)} chunks")

                mention_count: dict[str, int] = {}
                chunk_entity_ids: dict[str, list[str]] = {}

                # Pass 1 – entity extraction
                for i, chunk in enumerate(all_chunks):
                    ent_dicts = pipeline.extract_entities(chunk.text, proj.id)

                    # Optional spaCy augmentation
                    if settings.nlp_backend in ("auto", "spacy"):
                        from .extract.nlp import get_nlp_extractor
                        nlp = get_nlp_extractor()
                        if nlp.available:
                            ent_dicts += nlp.extract(chunk.text, proj.id)

                    ids: list[str] = []
                    for ed in ent_dicts:
                        key = (ed["type"], ed["name"].lower())
                        ent = entities_by_key.get(key)
                        if ent is None:
                            ent = Entity(id=ed["id"], project_id=proj.id, name=ed["name"],
                                         type=ed["type"], aliases=[], mention_count=0)
                            entities_by_key[key] = ent
                            session.add(ent)
                        mention_count[ent.id] = mention_count.get(ent.id, 0) + 1
                        ids.append(ent.id)
                    chunk_entity_ids[chunk.id] = ids
                    if (i + 1) % batch == 0:
                        await session.flush()

                for ent in entities_by_key.values():
                    ent.mention_count = mention_count.get(ent.id, ent.mention_count)
                await session.flush()

                ent_by_id = {e.id: e for e in entities_by_key.values()}

                # Pass 2 – relation + evidence extraction
                relations_by_key: dict[tuple, Relation] = {}
                evidence_seen: set[str] = set()

                for i, chunk in enumerate(all_chunks):
                    ent_dicts = [
                        {"id": eid, "type": ent_by_id[eid].type, "name": ent_by_id[eid].name}
                        for eid in chunk_entity_ids.get(chunk.id, [])
                        if eid in ent_by_id
                    ]
                    rel_dicts, ev_dicts = pipeline.extract_relations(chunk.text, chunk.id, ent_dicts, proj.id)

                    for rd in rel_dicts:
                        key = (rd["source_id"], rd["type"], rd["target_id"])
                        if key not in relations_by_key:
                            rel = Relation(id=rd["id"], project_id=proj.id, source_id=rd["source_id"],
                                           type=rd["type"], target_id=rd["target_id"], confidence=rd["confidence"])
                            relations_by_key[key] = rel
                            session.add(rel)
                    if (i + 1) % batch == 0:
                        await session.flush()

                    for evd in ev_dicts:
                        if evd["id"] not in evidence_seen:
                            evidence_seen.add(evd["id"])
                            session.add(Evidence(id=evd["id"], relation_id=evd["relation_id"],
                                                  chunk_id=evd["chunk_id"], quote=evd["quote"],
                                                  method=evd["method"], confidence=evd["confidence"]))

                    # Mark chunk as processed
                    session.add(ProcessedChunk(chunk_id=chunk.id, build_log_id=build_log.id))

                await session.flush()

                stats = dict(entities=len(entities_by_key), relations=len(relations_by_key),
                             evidence=len(evidence_seen), chunks_processed=len(all_chunks),
                             mode="incremental" if incremental else "full")

                build_log.status = "done"
                build_log.stats = stats
                build_log.finished_at = datetime.datetime.utcnow()

                # Graph versioning snapshot
                if settings.versioning_enabled:
                    await self._save_snapshot(session, proj, build_log.id, stats)

                duration = time.monotonic() - t0
                BUILD_DURATION.labels(project=self.name, mode=stats["mode"]).observe(duration)
                ENTITIES_GAUGE.labels(project=self.name).set(stats["entities"])
                RELATIONS_GAUGE.labels(project=self.name).set(stats["relations"])
                logger.success(f"Build done in {duration:.1f}s: {stats}")

            except Exception as exc:
                build_log.status = "failed"
                build_log.error = str(exc)
                build_log.finished_at = datetime.datetime.utcnow()
                logger.exception(f"Build failed for {self.name!r}")
                raise

            finally:
                await _release_build_lock(self.name, proj.id, session)

        invalidate(self.name)

        # Deduplication (post-build, non-blocking on failure)
        if settings.dedup_enabled and not incremental:
            try:
                dedup = await self.deduplicate()
                stats["dedup_merges"] = dedup["merges"]
            except Exception as exc:
                logger.warning(f"Deduplication failed (non-fatal): {exc}")

        return {"project": self.name, **stats}

    # ── deduplication ─────────────────────────────────────────────────────────

    async def deduplicate(self, threshold: float | None = None) -> dict[str, Any]:
        """
        Merge entity pairs within the same type whose names are highly similar.
        The entity with fewer mentions is marked as a duplicate (canonical_id set).
        """
        threshold = threshold if threshold is not None else settings.dedup_threshold
        merges = 0

        async with get_session() as session:
            proj = await self._require(session)
            ents_res = await session.execute(
                select(Entity).where(Entity.project_id == proj.id, Entity.canonical_id.is_(None))
            )
            all_ents = ents_res.scalars().all()

            by_type: dict[str, list[Entity]] = {}
            for e in all_ents:
                by_type.setdefault(e.type, []).append(e)

            for etype, ents in by_type.items():
                for i, e1 in enumerate(ents):
                    for e2 in ents[i + 1:]:
                        if e2.canonical_id:
                            continue
                        sim = difflib.SequenceMatcher(
                            None, e1.name.lower(), e2.name.lower()
                        ).ratio()
                        # Skip pairs that differ primarily in a trailing number
                        # e.g. "error 503" vs "error 500", "INC-1001" vs "INC-1002"
                        if sim >= threshold and not _numeric_variants(e1.name, e2.name):
                            canonical = e1 if e1.mention_count >= e2.mention_count else e2
                            dup = e2 if canonical is e1 else e1
                            dup.canonical_id = canonical.id
                            logger.debug(f"Dedup: '{dup.name}' → '{canonical.name}' (sim={sim:.2f})")
                            merges += 1

        DEDUP_MERGES.labels(project=self.name).inc(merges)
        return {"project": self.name, "merges": merges, "threshold": threshold}

    # ── rank ─────────────────────────────────────────────────────────────────

    async def rank(self, query: str, limit: int = 10) -> dict[str, Any]:
        async with timed("rank"):
            async with get_session() as session:
                proj = await self._require(session)
                index = await self._get_index(session, proj)

            rows = []
            for ent in index.entities:
                s = score_entity_data(ent, query, index.ranker)
                if s > 0:
                    rows.append(dict(
                        entity=dict(id=ent.id, name=ent.name, type=ent.type, mention_count=ent.mention_count),
                        score=round(s, 4), degree=ent.degree,
                    ))
            rows.sort(key=lambda x: (-x["score"], x["entity"]["name"]))
            return dict(project=self.name, query=query, results=rows[:limit],
                        total_matching=len(rows), ranker=index.ranker.backend)

    # ── ask ──────────────────────────────────────────────────────────────────

    async def ask(self, question: str, limit: int = 5) -> dict[str, Any]:
        async with timed("ask"):
            ranked = (await self.rank(question, limit=limit))["results"]
            entity_names = [r["entity"]["name"] for r in ranked]
            snippets: list[str] = []

            if entity_names:
                async with get_session() as session:
                    proj = await self._require(session)
                    snippets = await fts_search(session, proj.id, entity_names, limit=5)

            answer = "Related entities: " + ", ".join(entity_names) + "." if entity_names else "No related entities found."
            if snippets:
                answer += "\n\nSupporting evidence:\n" + "\n---\n".join(snippets)

        return dict(project=self.name, question=question, answer=answer,
                    entities=entity_names, snippets=snippets, results=ranked)

    # ── path ─────────────────────────────────────────────────────────────────

    async def path(self, source: str, target: str, max_depth: int = 4) -> dict[str, Any]:
        async with timed("path"):
            async with get_session() as session:
                proj = await self._require(session)
                ents_res = await session.execute(
                    select(Entity).where(Entity.project_id == proj.id)
                    .options(selectinload(Entity.source_relations).selectinload(Relation.evidence))
                )
                entities = ents_res.scalars().all()

            entity_map = {e.id: e for e in entities}
            srcs = [e for e in entities if e.name.lower() == source.lower()]
            tgts = [e for e in entities if e.name.lower() == target.lower()]

            if not srcs or not tgts:
                return dict(project=self.name, source=source, target=target, paths=[], found=False)

            adjacency = {e.id: e.source_relations for e in entities}
            paths = bfs_paths(srcs, {e.id for e in tgts}, adjacency, entity_map, max_depth)
        return dict(project=self.name, source=source, target=target, paths=paths, found=bool(paths))

    # ── feedback ─────────────────────────────────────────────────────────────

    async def submit_feedback(self, entity_id: str, query: str, rating: int, comment: str | None = None) -> dict:
        async with get_session() as session:
            proj = await self._require(session)
            session.add(EntityFeedback(
                project_id=proj.id, entity_id=entity_id,
                query=query, rating=rating, comment=comment,
            ))
        return {"project": self.name, "recorded": True}

    # ── snapshots ─────────────────────────────────────────────────────────────

    async def snapshots(self) -> list[dict[str, Any]]:
        async with get_session() as session:
            proj = await self._require(session)
            res = await session.execute(
                select(GraphSnapshot).where(GraphSnapshot.project_id == proj.id)
                .order_by(GraphSnapshot.created_at.desc())
            )
            return [
                dict(id=s.id, entities=s.entity_count, relations=s.relation_count,
                     evidence=s.evidence_count, schema_hash=s.schema_hash,
                     created_at=s.created_at.isoformat())
                for s in res.scalars()
            ]

    # ── ingest errors ─────────────────────────────────────────────────────────

    async def ingest_errors(self) -> list[dict[str, Any]]:
        async with get_session() as session:
            proj = await self._require(session)
            res = await session.execute(
                select(IngestError).where(IngestError.project_id == proj.id)
                .order_by(IngestError.occurred_at.desc())
            )
            return [
                dict(path=e.path, error_type=e.error_type,
                     message=e.message, occurred_at=e.occurred_at.isoformat())
                for e in res.scalars()
            ]

    # ── stats ─────────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        async with get_session() as session:
            proj = await self._require(session)
            doc_count   = await session.scalar(select(func.count()).where(Document.project_id == proj.id).select_from(Document)) or 0
            chunk_count = await session.scalar(select(func.count()).select_from(Chunk).join(Document).where(Document.project_id == proj.id)) or 0
            ent_count   = await session.scalar(select(func.count()).where(Entity.project_id == proj.id).select_from(Entity)) or 0
            rel_count   = await session.scalar(select(func.count()).where(Relation.project_id == proj.id).select_from(Relation)) or 0
            ev_count    = await session.scalar(select(func.count()).select_from(Evidence).join(Relation).where(Relation.project_id == proj.id)) or 0
            err_count   = await session.scalar(select(func.count()).where(IngestError.project_id == proj.id).select_from(IngestError)) or 0

            last_build = await self._last_build(session, proj.id)
            cached = get_index(self.name)
            ranker_backend = cached.ranker.backend if cached else "not_built"

        return dict(project=self.name, ranker_backend=ranker_backend,
                    documents=doc_count, chunks=chunk_count, entities=ent_count,
                    relations=rel_count, evidence=ev_count, ingest_errors=err_count,
                    last_build=dict(
                        status=last_build.status,
                        mode=last_build.mode,
                        started_at=last_build.started_at.isoformat(),
                        finished_at=last_build.finished_at.isoformat() if last_build.finished_at else None,
                    ) if last_build else None)

    # ── list all ──────────────────────────────────────────────────────────────

    @staticmethod
    async def list_all() -> list[dict[str, Any]]:
        await init_db()
        async with get_session() as session:
            result = await session.execute(select(ProjectORM).order_by(ProjectORM.created_at))
            return [dict(name=p.name, id=p.id, created_at=p.created_at.isoformat()) for p in result.scalars()]
