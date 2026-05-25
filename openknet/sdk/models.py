from __future__ import annotations

from pydantic import BaseModel, Field


class EntityResult(BaseModel):
    id: str
    name: str
    type: str
    mention_count: int
    score: float
    degree: int


class PathResult(BaseModel):
    nodes: list[str]
    relations: list[str]
    confidence: float
    length: int
    evidence_ids: list[str] = Field(default_factory=list)


class BuildInfo(BaseModel):
    status: str
    started_at: str
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# Operation responses
# ---------------------------------------------------------------------------

class IngestResponse(BaseModel):
    project: str
    documents_added: int
    documents_total: int
    chunks_added: int
    chunks_total: int
    skipped_oversized: int


class BuildResponse(BaseModel):
    project: str
    entities: int
    relations: int
    evidence: int
    chunks_processed: int
    mode: str = "full"
    dedup_merges: int = 0


class RankResponse(BaseModel):
    project: str
    query: str
    results: list[EntityResult]
    total_matching: int
    ranker: str = "unknown"


class AskResponse(BaseModel):
    project: str
    question: str
    answer: str
    entities: list[str]
    snippets: list[str]
    results: list[EntityResult]


class PathResponse(BaseModel):
    project: str
    source: str
    target: str
    paths: list[PathResult]
    found: bool


class StatsResponse(BaseModel):
    project: str
    ranker_backend: str = "unknown"
    documents: int
    chunks: int
    entities: int
    relations: int
    evidence: int
    last_build: BuildInfo | None = None
