from __future__ import annotations
import time
from contextlib import asynccontextmanager

from loguru import logger

try:
    from prometheus_client import (
        Counter, Gauge, Histogram, CollectorRegistry,
        generate_latest, CONTENT_TYPE_LATEST,
    )
    _prometheus_available = True
except ImportError:
    _prometheus_available = False
    logger.debug("prometheus_client not installed — metrics endpoint disabled")


# ---------------------------------------------------------------------------
# Metric definitions (only created if prometheus available)
# ---------------------------------------------------------------------------

if _prometheus_available:
    BUILD_DURATION = Histogram(
        "openknet_build_duration_seconds",
        "Time spent on a full or incremental build",
        ["project", "mode"],
        buckets=[1, 5, 10, 30, 60, 120, 300],
    )
    INGEST_DOCS = Counter(
        "openknet_ingest_documents_total",
        "Total documents successfully ingested",
        ["project", "format"],
    )
    INGEST_ERRORS = Counter(
        "openknet_ingest_errors_total",
        "Documents that failed to ingest",
        ["project", "error_type"],
    )
    ENTITIES_GAUGE = Gauge(
        "openknet_entities_total",
        "Current entity count per project",
        ["project"],
    )
    RELATIONS_GAUGE = Gauge(
        "openknet_relations_total",
        "Current relation count per project",
        ["project"],
    )
    QUERY_DURATION = Histogram(
        "openknet_query_duration_seconds",
        "Time spent on rank/ask/path operations",
        ["operation"],
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    )
    CACHE_HITS = Counter(
        "openknet_cache_hits_total",
        "Index cache hits",
        ["backend"],
    )
    CACHE_MISSES = Counter(
        "openknet_cache_misses_total",
        "Index cache misses (rebuild triggered)",
        ["backend"],
    )
    DEDUP_MERGES = Counter(
        "openknet_dedup_merges_total",
        "Entity deduplication merges",
        ["project"],
    )
else:
    # Stub metrics that silently no-op
    class _Stub:
        def labels(self, **_): return self
        def observe(self, *_): pass
        def inc(self, *_): pass
        def set(self, *_): pass
        def time(self): return _TimerCtx()

    class _TimerCtx:
        def __enter__(self): return self
        def __exit__(self, *_): pass

    _s = _Stub()
    BUILD_DURATION = INGEST_DOCS = INGEST_ERRORS = ENTITIES_GAUGE = _s
    RELATIONS_GAUGE = QUERY_DURATION = CACHE_HITS = CACHE_MISSES = DEDUP_MERGES = _s


# ---------------------------------------------------------------------------
# Context manager for timing queries
# ---------------------------------------------------------------------------

@asynccontextmanager
async def timed(operation: str):
    """Async context manager that records query duration."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        QUERY_DURATION.labels(operation=operation).observe(time.monotonic() - t0)


# ---------------------------------------------------------------------------
# Metrics HTTP response helper
# ---------------------------------------------------------------------------

def metrics_response():
    """Return (content, media_type) for the /metrics endpoint."""
    if not _prometheus_available:
        return "# prometheus_client not installed\n", "text/plain"
    return generate_latest().decode(), CONTENT_TYPE_LATEST
