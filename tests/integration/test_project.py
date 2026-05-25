from __future__ import annotations
import pytest
from pathlib import Path

from openknet.project import Project


@pytest.mark.asyncio
async def test_init_creates_project(tmp_project, support_schema):
    p = await Project.init("test", schema=support_schema)
    projects = await Project.list_all()
    assert any(proj["name"] == "test" for proj in projects)


@pytest.mark.asyncio
async def test_ingest_documents(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    result = await Project("test").ingest(sample_docs)

    assert result["documents_added"] == 2
    assert result["chunks_added"] >= 2
    assert result["chunks_total"] >= 2


@pytest.mark.asyncio
async def test_ingest_deduplication(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    r1 = await Project("test").ingest(sample_docs)
    r2 = await Project("test").ingest(sample_docs)

    assert r1["documents_added"] == 2
    assert r2["documents_added"] == 0  # already ingested


@pytest.mark.asyncio
async def test_build_extracts_graph(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    await Project("test").ingest(sample_docs)
    result = await Project("test").build()

    assert result["entities"] > 0
    assert result["relations"] > 0
    assert result["evidence"] > 0
    assert result["chunks_processed"] >= 2


@pytest.mark.asyncio
async def test_rank_returns_results(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    await Project("test").ingest(sample_docs)
    await Project("test").build()

    result = await Project("test").rank("login error")
    assert result["total_matching"] > 0
    assert len(result["results"]) > 0
    # AuthService or error 503 should rank highly
    names = [r["entity"]["name"] for r in result["results"]]
    assert any(n in ("AuthService", "error 503", "login error") for n in names)


@pytest.mark.asyncio
async def test_ask_returns_answer(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    await Project("test").ingest(sample_docs)
    await Project("test").build()

    result = await Project("test").ask("what causes login errors?")
    assert result["answer"]
    assert isinstance(result["entities"], list)


@pytest.mark.asyncio
async def test_path_finds_connection(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    await Project("test").ingest(sample_docs)
    await Project("test").build()

    result = await Project("test").path("AuthService", "error 503")
    assert result["found"]
    assert len(result["paths"]) > 0


@pytest.mark.asyncio
async def test_stats(tmp_project, support_schema, sample_docs):
    await Project.init("test", schema=support_schema)
    await Project("test").ingest(sample_docs)
    await Project("test").build()

    result = await Project("test").stats()
    assert result["documents"] == 2
    assert result["chunks"] >= 2
    assert result["entities"] > 0
    assert result["last_build"]["status"] == "done"


@pytest.mark.asyncio
async def test_project_not_found(tmp_project):
    with pytest.raises(FileNotFoundError):
        await Project("nonexistent").stats()


@pytest.mark.asyncio
async def test_ingest_single_file(tmp_project, support_schema, tmp_path):
    await Project.init("test", schema=support_schema)
    f = tmp_path / "single.txt"
    f.write_text("ACME reported INC-1001 affecting Portal X.", encoding="utf-8")

    result = await Project("test").ingest(f)
    assert result["documents_added"] == 1


@pytest.mark.asyncio
async def test_ingest_oversized_file_skipped(tmp_project, support_schema, tmp_path, monkeypatch):
    from openknet.config import settings
    monkeypatch.setattr(settings, "max_file_size_mb", 0)  # every file is "oversized"

    await Project.init("test", schema=support_schema)
    f = tmp_path / "big.txt"
    f.write_text("some content", encoding="utf-8")

    result = await Project("test").ingest(f)
    assert result["documents_added"] == 0
    assert result["skipped_oversized"] == 1
