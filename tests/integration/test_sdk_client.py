import pytest
from pathlib import Path
from openknet import OpenKNet
from openknet.sdk.exceptions import ProjectNotFoundError


@pytest.mark.asyncio
async def test_open_context_manager(tmp_project, support_schema, sample_docs):
    async with OpenKNet.open("sdk-test", schema=support_schema) as knet:
        assert knet._initialized
        result = await knet.ingest(sample_docs)
        assert result.documents_added == 2

        build = await knet.build()
        assert build.entities > 0
        assert build.relations > 0


@pytest.mark.asyncio
async def test_rank_returns_typed_response(tmp_project, support_schema, sample_docs):
    async with OpenKNet.open("sdk-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()
        resp = await knet.rank("login error")

    from openknet import RankResponse, EntityResult
    assert isinstance(resp, RankResponse)
    assert all(isinstance(r, EntityResult) for r in resp.results)
    assert resp.total_matching > 0


@pytest.mark.asyncio
async def test_ask_returns_typed_response(tmp_project, support_schema, sample_docs):
    async with OpenKNet.open("sdk-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()
        resp = await knet.ask("what causes errors?")

    from openknet import AskResponse
    assert isinstance(resp, AskResponse)
    assert resp.answer
    assert isinstance(resp.entities, list)


@pytest.mark.asyncio
async def test_path_returns_typed_response(tmp_project, support_schema, sample_docs):
    async with OpenKNet.open("sdk-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()
        resp = await knet.path("AuthService", "error 503")

    from openknet import PathResponse
    assert isinstance(resp, PathResponse)
    assert resp.found
    assert len(resp.paths) > 0


@pytest.mark.asyncio
async def test_stats_returns_typed_response(tmp_project, support_schema, sample_docs):
    async with OpenKNet.open("sdk-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()
        resp = await knet.stats()

    from openknet.sdk.models import StatsResponse
    assert isinstance(resp, StatsResponse)
    assert resp.documents == 2
    assert resp.last_build is not None
    assert resp.last_build.status == "done"


@pytest.mark.asyncio
async def test_entities_filter_by_type(tmp_project, support_schema, sample_docs):
    async with OpenKNet.open("sdk-test", schema=support_schema) as knet:
        await knet.ingest(sample_docs)
        await knet.build()
        components = await knet.entities(entity_type="Component")

    assert all(e.type == "Component" for e in components)
    assert len(components) > 0


@pytest.mark.asyncio
async def test_create_sync_factory(tmp_project, support_schema):
    knet = OpenKNet.create("sync-test", schema=support_schema)
    assert knet._initialized
    stats = knet.stats_sync()
    assert stats.project == "sync-test"


@pytest.mark.asyncio
async def test_project_not_found(tmp_project):
    knet = OpenKNet("ghost-project")
    with pytest.raises(ProjectNotFoundError):
        await knet.stats()
