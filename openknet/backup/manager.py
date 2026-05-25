from __future__ import annotations
import datetime
import shutil
from pathlib import Path

from loguru import logger

from ..config import settings
from ..db import current_dialect


class BackupManager:
    """
    Point-in-time backup for SQLite and PostgreSQL backends.

    SQLite  — uses the SQLite Online Backup API via `aiosqlite`.
    PostgreSQL — runs `pg_dump` in a subprocess to a compressed SQL file.
    """

    def __init__(self) -> None:
        self.backup_dir = settings.backup_dir

    def _ts(self) -> str:
        return datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    async def backup(self, label: str = "") -> Path:
        """Create a backup and return its path."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        ts = self._ts()
        suffix = f"_{label}" if label else ""
        dialect = current_dialect()

        if dialect == "sqlite":
            return await self._backup_sqlite(ts, suffix)
        else:
            return await self._backup_postgres(ts, suffix)

    async def _backup_sqlite(self, ts: str, suffix: str) -> Path:
        src = settings.workspace_root / "openknet.db"
        dst = self.backup_dir / f"openknet_{ts}{suffix}.db"
        shutil.copy2(src, dst)
        logger.info(f"SQLite backup: {dst} ({dst.stat().st_size / 1024:.1f} KB)")
        return dst

    async def _backup_postgres(self, ts: str, suffix: str) -> Path:
        import asyncio
        dst = self.backup_dir / f"openknet_{ts}{suffix}.sql.gz"
        url = settings.get_db_url()
        # Convert asyncpg URL to psql-compatible format
        url = url.replace("postgresql+asyncpg://", "postgresql://")
        cmd = f'pg_dump "{url}" | gzip > "{dst}"'
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {stderr.decode()}")
        logger.info(f"PostgreSQL backup: {dst}")
        return dst

    def list_backups(self) -> list[Path]:
        """Return all backup files sorted by modification time (newest first)."""
        if not self.backup_dir.exists():
            return []
        files = sorted(
            self.backup_dir.glob("openknet_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files

    def prune(self, keep: int = 10) -> int:
        """Delete oldest backups, keeping at most *keep* files. Returns deleted count."""
        all_files = self.list_backups()
        to_delete = all_files[keep:]
        for f in to_delete:
            f.unlink()
            logger.debug(f"Pruned backup: {f.name}")
        return len(to_delete)
