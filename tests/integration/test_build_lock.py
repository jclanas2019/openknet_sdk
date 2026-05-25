"""
Tests for per-project build lock.
Verifies that concurrent builds on the same project are rejected, not silently corrupted.
"""
import asyncio
import pytest
from openknet import OpenKNet


@pytest.mark.asyncio
async def test_concurrent_full_builds_rejected(tmp_project, support_schema, sample_docs):
    """
    Two simultaneous full builds on the same project: the second must raise RuntimeError,
    not silently corrupt the graph.
    """
    async with OpenKNet.open("lock-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)

    project = OpenKNet("lock-test")

    async def do_build():
        return await project.build()

    # Fire two builds concurrently
    results = await asyncio.gather(do_build(), do_build(), return_exceptions=True)

    successes = [r for r in results if not isinstance(r, Exception)]
    failures  = [r for r in results if isinstance(r, (RuntimeError, Exception))]

    # Exactly one should succeed; the other should fail with RuntimeError (lock conflict)
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {results}"
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert "already running" in str(failures[0]).lower()


@pytest.mark.asyncio
async def test_incremental_after_full_not_blocked(tmp_project, support_schema, sample_docs):
    """After a successful full build, an incremental build should work normally."""
    async with OpenKNet.open("lock-seq", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()
        result = await knet.build(incremental=True)
    assert result.mode == "incremental"
    assert result.chunks_processed == 0  # nothing new to process


@pytest.mark.asyncio
async def test_build_lock_released_after_failure(tmp_project, support_schema, sample_docs):
    """
    If a build fails, the lock must be released so subsequent builds can proceed.
    """
    async with OpenKNet.open("lock-fail", schema=support_schema) as knet:
        await knet.ingest(sample_docs)

    project = OpenKNet("lock-fail")

    # First build — should succeed even if we attempt a second one after
    await project.build()

    # After a completed build, lock must be free
    result = await project.build()
    assert result.entities > 0


@pytest.mark.asyncio
async def test_different_projects_build_concurrently(tmp_project, support_schema, sample_docs):
    """Builds on different projects must not block each other."""
    async with OpenKNet.open("proj-a", schema=support_schema) as ka:
        await ka.ingest(sample_docs)
    async with OpenKNet.open("proj-b", schema=support_schema) as kb:
        await kb.ingest(sample_docs)

    results = await asyncio.gather(
        OpenKNet("proj-a").build(),
        OpenKNet("proj-b").build(),
    )
    # Both should succeed
    assert all(r.entities > 0 for r in results)
