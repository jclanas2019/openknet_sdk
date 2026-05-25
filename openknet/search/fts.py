"""
Full-text search abstraction.

SQLite  → FTS5 virtual table (chunks_fts) with Porter stemmer.
          Populated explicitly during ingest.

PostgreSQL → functional GIN index on to_tsvector('english', chunks.text).
             No extra table; index maintained automatically by Postgres.
             Uses ts_rank for relevance ordering.

Both backends receive entity names (not the user's raw query) so retrieval
is language-agnostic: a Spanish question that surfaces "AuthService" will
fetch English chunks mentioning AuthService.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import select, text

from ..db import current_dialect


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

async def fts_insert_chunk(
    session,
    chunk_id: str,
    project_id: str,
    chunk_text: str,
) -> None:
    """
    Register a chunk in the FTS index.
    PostgreSQL: no-op — the GIN index updates automatically on INSERT into chunks.
    SQLite:     explicit INSERT into chunks_fts.
    """
    if current_dialect() == "sqlite":
        await session.execute(
            text(
                "INSERT INTO chunks_fts(chunk_id, project_id, text) "
                "VALUES (:cid, :pid, :txt)"
            ),
            {"cid": chunk_id, "pid": project_id, "txt": chunk_text},
        )


async def fts_delete_project(session, project_id: str) -> None:
    """
    Remove FTS entries for a project (called before a clean re-ingest).
    PostgreSQL: no-op.
    SQLite:     DELETE from chunks_fts.
    """
    if current_dialect() == "sqlite":
        await session.execute(
            text("DELETE FROM chunks_fts WHERE project_id = :pid"),
            {"pid": project_id},
        )


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

async def fts_search(
    session,
    project_id: str,
    entity_names: list[str],
    limit: int = 5,
) -> list[str]:
    """
    Return up to *limit* chunk texts that best match the given entity names.
    Falls back to a linear scan if FTS fails.
    """
    if not entity_names:
        return []

    dialect = current_dialect()

    if dialect == "postgresql":
        return await _pg_search(session, project_id, entity_names, limit)
    else:
        return await _sqlite_search(session, project_id, entity_names, limit)


async def _pg_search(
    session,
    project_id: str,
    entity_names: list[str],
    limit: int,
) -> list[str]:
    """
    PostgreSQL FTS using tsvector + GIN index.

    Query strategy:
      - Build a plainto_tsquery from entity names (handles multi-word phrases)
      - Filter by project via documents join
      - Rank by ts_rank (term-frequency-based relevance)
    """
    query_text = " ".join(entity_names[:4])
    try:
        result = await session.execute(
            text("""
                SELECT c.text
                FROM   chunks c
                JOIN   documents d ON c.document_id = d.id
                WHERE  d.project_id = :pid
                  AND  to_tsvector('english', c.text)
                       @@ plainto_tsquery('english', :q)
                ORDER BY ts_rank(
                    to_tsvector('english', c.text),
                    plainto_tsquery('english', :q)
                ) DESC
                LIMIT :lim
            """),
            {"pid": project_id, "q": query_text, "lim": limit},
        )
        rows = result.fetchall()
        if rows:
            return [row[0][:400] for row in rows]
    except Exception as exc:
        logger.warning(f"PostgreSQL FTS failed: {exc}")

    return await _fallback_scan(session, project_id, entity_names, limit)


async def _sqlite_search(
    session,
    project_id: str,
    entity_names: list[str],
    limit: int,
) -> list[str]:
    """
    SQLite FTS5 search.
    Phrases are quoted so "error 503" matches as a phrase, not two separate tokens.
    Multiple entities are OR-ed so any match surfaces the chunk.
    """
    fts_terms = " OR ".join(f'"{name}"' for name in entity_names[:4])
    try:
        result = await session.execute(
            text(
                "SELECT c.text "
                "FROM   chunks c "
                "JOIN   chunks_fts f ON c.id = f.chunk_id "
                "WHERE  chunks_fts MATCH :q "
                "  AND  f.project_id = :pid "
                "ORDER BY rank "
                "LIMIT :lim"
            ),
            {"q": fts_terms, "pid": project_id, "lim": limit},
        )
        rows = result.fetchall()
        if rows:
            return [row[0][:400] for row in rows]
    except Exception as exc:
        logger.warning(f"SQLite FTS5 failed: {exc}")

    return await _fallback_scan(session, project_id, entity_names, limit)


async def _fallback_scan(
    session,
    project_id: str,
    entity_names: list[str],
    limit: int,
) -> list[str]:
    """Linear scan fallback when FTS is unavailable or returns nothing."""
    from ..models.orm import Chunk, Document

    chunks_res = await session.execute(
        select(Chunk).join(Document).where(Document.project_id == project_id)
    )
    snippets: list[str] = []
    for chunk in chunks_res.scalars():
        if any(n.lower() in chunk.text.lower() for n in entity_names[:3]):
            snippets.append(chunk.text[:400])
            if len(snippets) >= limit:
                break
    return snippets
