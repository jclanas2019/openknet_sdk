from __future__ import annotations
import threading
from dataclasses import dataclass, field

from .ranker import UnifiedRanker


@dataclass
class ChunkData:
    id: str
    text: str


@dataclass
class EntityData:
    id: str
    name: str
    type: str
    mention_count: int
    degree: int
    relevant_chunks: list[ChunkData] = field(default_factory=list)


@dataclass
class ProjectIndex:
    build_log_id: int
    ranker: UnifiedRanker
    entities: list[EntityData]


# ---------------------------------------------------------------------------
# Cache backend: Redis (async) when available, thread-safe dict otherwise
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_mem_cache: dict[str, ProjectIndex] = {}


def get_index(project_name: str) -> ProjectIndex | None:
    with _lock:
        return _mem_cache.get(project_name)


def put_index(project_name: str, index: ProjectIndex) -> None:
    with _lock:
        _mem_cache[project_name] = index


def invalidate(project_name: str) -> None:
    with _lock:
        _mem_cache.pop(project_name, None)


def invalidate_all() -> None:
    with _lock:
        _mem_cache.clear()
