from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from . import __version__
from .db import init_db

app = typer.Typer(no_args_is_help=True, help="OpenKNet — knowledge-network mining CLI")


def emit(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2))

def run(coro):
    return asyncio.run(coro)

@app.callback()
def main(
    version: bool = typer.Option(False, "--version", "-V"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    import sys
    logger.remove()
    logger.add(sys.stderr, level=log_level.upper(), colorize=True)
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init(project: str, schema: Optional[Path] = typer.Option(None, "--schema", "-s")) -> None:
    """Initialise a new project (or update its schema)."""
    from .project import Project
    async def _r():
        await init_db()
        await Project.init(project, schema=schema)
        return {"project": project, "initialized": True}
    emit(run(_r()))


@app.command()
def ingest(path: Path, project: str = typer.Option(..., "--project", "-p")) -> None:
    """Ingest documents (TXT, MD, PDF, DOCX, HTML) into a project."""
    from .project import Project
    emit(run(Project(project).ingest(path)))


@app.command()
def build(
    project: str = typer.Option(..., "--project", "-p"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Only process new chunks"),
) -> None:
    """Extract entities and relations and build the knowledge graph."""
    from .project import Project
    emit(run(Project(project).build(incremental=incremental)))


@app.command()
def rank(
    query: str,
    project: str = typer.Option(..., "--project", "-p"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Rank entities by relevance to a query."""
    from .project import Project
    emit(run(Project(project).rank(query, limit=limit)))


@app.command()
def ask(
    question: str,
    project: str = typer.Option(..., "--project", "-p"),
    limit: int = typer.Option(5, "--limit", "-n"),
) -> None:
    """Ask a natural-language question."""
    from .project import Project
    emit(run(Project(project).ask(question, limit=limit)))


@app.command()
def path(
    source: str, target: str,
    project: str = typer.Option(..., "--project", "-p"),
    max_depth: int = typer.Option(4, "--max-depth"),
) -> None:
    """Find paths between two entities in the knowledge graph."""
    from .project import Project
    emit(run(Project(project).path(source, target, max_depth=max_depth)))


@app.command()
def stats(project: str = typer.Option(..., "--project", "-p")) -> None:
    """Show project statistics (includes ranker backend and ingest errors)."""
    from .project import Project
    emit(run(Project(project).stats()))


@app.command()
def projects() -> None:
    """List all projects."""
    from .project import Project
    emit(run(Project.list_all()))


@app.command()
def snapshots(project: str = typer.Option(..., "--project", "-p")) -> None:
    """List graph version snapshots for a project."""
    from .project import Project
    emit(run(Project(project).snapshots()))


@app.command()
def errors(project: str = typer.Option(..., "--project", "-p")) -> None:
    """List documents that failed to ingest."""
    from .project import Project
    emit(run(Project(project).ingest_errors()))


@app.command()
def deduplicate(
    project: str = typer.Option(..., "--project", "-p"),
    threshold: float = typer.Option(0.85, "--threshold", "-t"),
) -> None:
    """Merge duplicate entity names within the same type."""
    from .project import Project
    emit(run(Project(project).deduplicate(threshold=threshold)))


@app.command()
def migrate() -> None:
    """Apply DB migrations and index setup (idempotent — safe to re-run)."""
    from .db import current_dialect
    async def _r():
        await init_db()
        return {"dialect": current_dialect(), "status": "ok"}
    emit(run(_r()))


@app.command()
def backup(label: str = typer.Option("manual", "--label")) -> None:
    """Create a point-in-time backup of the database."""
    from .backup.manager import BackupManager
    async def _r():
        bk = BackupManager()
        p = await bk.backup(label=label)
        return {"path": str(p), "size_kb": round(p.stat().st_size / 1024, 1)}
    emit(run(_r()))


@app.command()
def key_create(
    name: str = typer.Option(..., "--name", "-n"),
    role: str = typer.Option("reader", "--role"),
    project: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Create a new API key."""
    from .auth.middleware import generate_key, hash_key
    from .db import get_session
    from .models.orm import ApiKey
    async def _r():
        raw = generate_key()
        kid = hash_key(raw)[:16]
        async with get_session() as session:
            session.add(ApiKey(id=kid, key_hash=hash_key(raw), name=name,
                                role=role, project_id=project, is_active=True))
        return {"key": raw, "id": kid, "role": role, "note": "Store this — shown only once."}
    emit(run(_r()))


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    workers: int = typer.Option(1, "--workers"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the HTTP API server."""
    import uvicorn
    uvicorn.run("openknet.api.app:app", host=host, port=port, workers=workers, reload=reload, log_level="info")


@app.command()
def worker() -> None:
    """Start the ARQ background worker (requires Redis)."""
    try:
        from arq import run_worker
        from .workers.tasks import WorkerSettings
        run_worker(WorkerSettings)
    except ImportError:
        typer.echo("ARQ not installed. pip install arq", err=True)
        raise typer.Exit(1)
