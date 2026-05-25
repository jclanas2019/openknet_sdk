"""Initial schema — all tables for OpenKNet v2.0

Revision ID: 001
Revises:
Create Date: 2026-05-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This migration creates tables that may already exist (via init_db/create_all).
    # We use checkfirst=True so it is safe to run on both fresh and existing DBs.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    tables_sql = {
        "projects": """
            CREATE TABLE IF NOT EXISTS projects (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                schema_yaml TEXT DEFAULT '',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )""",
        "documents": """
            CREATE TABLE IF NOT EXISTS documents (
                id VARCHAR(64) PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                path TEXT NOT NULL,
                title VARCHAR(512) NOT NULL,
                format VARCHAR(16) DEFAULT 'txt',
                size_bytes INTEGER DEFAULT 0,
                text_hash VARCHAR(64) NOT NULL,
                metadata JSON,
                created_at DATETIME NOT NULL,
                UNIQUE(project_id, path)
            )""",
        "chunks": """
            CREATE TABLE IF NOT EXISTS chunks (
                id VARCHAR(64) PRIMARY KEY,
                document_id VARCHAR(64) NOT NULL REFERENCES documents(id),
                text TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                char_start INTEGER DEFAULT 0,
                char_end INTEGER DEFAULT 0
            )""",
        "build_logs": """
            CREATE TABLE IF NOT EXISTS build_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                status VARCHAR(32) NOT NULL,
                mode VARCHAR(16) DEFAULT 'full',
                stats JSON,
                error TEXT,
                started_at DATETIME NOT NULL,
                finished_at DATETIME
            )""",
        "processed_chunks": """
            CREATE TABLE IF NOT EXISTS processed_chunks (
                chunk_id VARCHAR(64) PRIMARY KEY REFERENCES chunks(id),
                build_log_id INTEGER NOT NULL REFERENCES build_logs(id),
                processed_at DATETIME NOT NULL
            )""",
        "entities": """
            CREATE TABLE IF NOT EXISTS entities (
                id VARCHAR(64) PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                name VARCHAR(512) NOT NULL,
                type VARCHAR(128) NOT NULL,
                aliases JSON,
                mention_count INTEGER DEFAULT 0,
                canonical_id VARCHAR(64),
                UNIQUE(project_id, type, name)
            )""",
        "relations": """
            CREATE TABLE IF NOT EXISTS relations (
                id VARCHAR(64) PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                source_id VARCHAR(64) NOT NULL REFERENCES entities(id),
                type VARCHAR(128) NOT NULL,
                target_id VARCHAR(64) NOT NULL REFERENCES entities(id),
                confidence FLOAT DEFAULT 0.75,
                UNIQUE(project_id, source_id, type, target_id)
            )""",
        "evidence": """
            CREATE TABLE IF NOT EXISTS evidence (
                id VARCHAR(64) PRIMARY KEY,
                relation_id VARCHAR(64) NOT NULL REFERENCES relations(id),
                chunk_id VARCHAR(64) NOT NULL REFERENCES chunks(id),
                quote TEXT NOT NULL,
                method VARCHAR(32) DEFAULT 'pattern',
                confidence FLOAT DEFAULT 0.75,
                UNIQUE(relation_id, chunk_id)
            )""",
        "graph_snapshots": """
            CREATE TABLE IF NOT EXISTS graph_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                build_log_id INTEGER NOT NULL REFERENCES build_logs(id),
                entity_count INTEGER DEFAULT 0,
                relation_count INTEGER DEFAULT 0,
                evidence_count INTEGER DEFAULT 0,
                schema_hash VARCHAR(16) NOT NULL,
                created_at DATETIME NOT NULL
            )""",
        "ingest_errors": """
            CREATE TABLE IF NOT EXISTS ingest_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                path TEXT NOT NULL,
                error_type VARCHAR(128) NOT NULL,
                message TEXT NOT NULL,
                occurred_at DATETIME NOT NULL
            )""",
        "api_keys": """
            CREATE TABLE IF NOT EXISTS api_keys (
                id VARCHAR(64) PRIMARY KEY,
                key_hash VARCHAR(64) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                project_id VARCHAR(64) REFERENCES projects(id),
                role VARCHAR(32) DEFAULT 'reader',
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME NOT NULL,
                last_used_at DATETIME,
                expires_at DATETIME
            )""",
        "entity_feedback": """
            CREATE TABLE IF NOT EXISTS entity_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
                entity_id VARCHAR(64) NOT NULL REFERENCES entities(id),
                query TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at DATETIME NOT NULL
            )""",
    }

    for table, ddl in tables_sql.items():
        if table not in existing:
            op.execute(sa.text(ddl))


def downgrade() -> None:
    tables = [
        "entity_feedback", "api_keys", "ingest_errors", "graph_snapshots",
        "evidence", "relations", "entities", "processed_chunks",
        "build_logs", "chunks", "documents", "projects",
    ]
    for t in tables:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {t}"))
