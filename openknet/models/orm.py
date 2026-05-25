from __future__ import annotations
import datetime
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


# ── Projects ─────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    schema_yaml: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    documents:   Mapped[list[Document]]    = relationship(back_populates="project", cascade="all, delete-orphan")
    entities:    Mapped[list[Entity]]      = relationship(back_populates="project", cascade="all, delete-orphan")
    relations:   Mapped[list[Relation]]    = relationship(back_populates="project", cascade="all, delete-orphan")
    build_logs:  Mapped[list[BuildLog]]    = relationship(back_populates="project", cascade="all, delete-orphan")
    api_keys:    Mapped[list[ApiKey]]      = relationship(back_populates="project", cascade="all, delete-orphan")
    ingest_errors: Mapped[list[IngestError]] = relationship(back_populates="project", cascade="all, delete-orphan")
    snapshots:   Mapped[list[GraphSnapshot]] = relationship(back_populates="project", cascade="all, delete-orphan")
    feedback:    Mapped[list[EntityFeedback]] = relationship(back_populates="project", cascade="all, delete-orphan")


# ── Documents & Chunks ───────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="txt")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="documents")
    chunks:  Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_doc_project_path"),
        Index("ix_doc_project_id", "project_id"),
    )


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)

    document:  Mapped[Document]  = relationship(back_populates="chunks")
    evidence:  Mapped[list[Evidence]] = relationship(back_populates="chunk", cascade="all, delete-orphan")
    processed: Mapped[list[ProcessedChunk]] = relationship(back_populates="chunk", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_chunk_document_id", "document_id"),)


class ProcessedChunk(Base):
    """Tracks which chunks have been included in a build (enables incremental builds)."""
    __tablename__ = "processed_chunks"
    chunk_id:    Mapped[str] = mapped_column(ForeignKey("chunks.id"), primary_key=True)
    build_log_id: Mapped[int] = mapped_column(ForeignKey("build_logs.id"), nullable=False)
    processed_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    chunk:     Mapped[Chunk]    = relationship(back_populates="processed")
    build_log: Mapped[BuildLog] = relationship()


# ── Knowledge Graph ───────────────────────────────────────────────────────────

class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    canonical_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # dedup: points to canonical entity

    project:          Mapped[Project]       = relationship(back_populates="entities")
    source_relations: Mapped[list[Relation]] = relationship(foreign_keys="Relation.source_id", back_populates="source", cascade="all, delete-orphan")
    target_relations: Mapped[list[Relation]] = relationship(foreign_keys="Relation.target_id", back_populates="target", cascade="all, delete-orphan")
    feedback:         Mapped[list[EntityFeedback]] = relationship(back_populates="entity", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "type", "name", name="uq_entity_project_type_name"),
        Index("ix_entity_project_id", "project_id"),
        Index("ix_entity_name", "name"),
        Index("ix_entity_rank", "project_id", "mention_count"),
    )


class Relation(Base):
    __tablename__ = "relations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.75)

    project:  Mapped[Project]       = relationship(back_populates="relations")
    source:   Mapped[Entity]        = relationship(foreign_keys=[source_id], back_populates="source_relations")
    target:   Mapped[Entity]        = relationship(foreign_keys=[target_id], back_populates="target_relations")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="relation", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "source_id", "type", "target_id", name="uq_relation"),
        Index("ix_relation_project_id", "project_id"),
        Index("ix_relation_source_id", "source_id"),
        Index("ix_relation_target_id", "target_id"),
    )


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    relation_id: Mapped[str] = mapped_column(ForeignKey("relations.id"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id"), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(32), default="pattern")
    confidence: Mapped[float] = mapped_column(Float, default=0.75)

    relation: Mapped[Relation] = relationship(back_populates="evidence")
    chunk:    Mapped[Chunk]    = relationship(back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("relation_id", "chunk_id", name="uq_evidence_rel_chunk"),
        Index("ix_evidence_relation_id", "relation_id"),
    )


# ── Operational tables ────────────────────────────────────────────────────────

class BuildLog(Base):
    __tablename__ = "build_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)   # running|done|failed
    mode: Mapped[str] = mapped_column(String(16), default="full")      # full|incremental
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="build_logs")


class IngestError(Base):
    """Records documents that failed to ingest."""
    __tablename__ = "ingest_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="ingest_errors")
    __table_args__ = (Index("ix_ingest_error_project", "project_id"),)


class GraphSnapshot(Base):
    """Immutable snapshot of graph statistics after each build (versioning)."""
    __tablename__ = "graph_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    build_log_id: Mapped[int] = mapped_column(ForeignKey("build_logs.id"), nullable=False)
    entity_count: Mapped[int] = mapped_column(Integer, default=0)
    relation_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="snapshots")
    __table_args__ = (Index("ix_snapshot_project", "project_id"),)


class ApiKey(Base):
    """API authentication keys with optional project scoping."""
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)  # None = global
    role: Mapped[str] = mapped_column(String(32), default="reader")  # admin|writer|reader
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project | None] = relationship(back_populates="api_keys")
    __table_args__ = (Index("ix_api_key_hash", "key_hash"),)


class EntityFeedback(Base):
    """User feedback on entity relevance for a given query."""
    __tablename__ = "entity_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)   # 1–5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="feedback")
    entity:  Mapped[Entity]  = relationship(back_populates="feedback")
    __table_args__ = (Index("ix_feedback_project", "project_id"),)
