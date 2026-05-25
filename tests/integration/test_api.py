from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client(tmp_project):
    from openknet.api.app import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_project(client):
    r = await client.post("/projects/api-test")
    assert r.status_code == 201
    assert r.json()["created"] is True


@pytest.mark.asyncio
async def test_list_projects(client):
    await client.post("/projects/p1")
    await client.post("/projects/p2")
    r = await client.get("/projects")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "p1" in names
    assert "p2" in names


@pytest.mark.asyncio
async def test_project_stats_not_found(client):
    r = await client.get("/projects/does-not-exist/stats")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rank_not_found(client):
    r = await client.get("/rank?project=ghost&query=test")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_build_sync(client, support_schema, sample_docs):
    from openknet.project import Project
    await Project.init("myproj", schema=support_schema)
    await Project("myproj").ingest(sample_docs)
    r = await client.post("/projects/myproj/build?sync=true")
    assert r.status_code == 200
    data = r.json()
    assert data["entities"] > 0


@pytest.mark.asyncio
async def test_rank_endpoint(client, support_schema, sample_docs):
    await client.post("/projects/myproj")
    from openknet.project import Project
    await Project("myproj").ingest(sample_docs)
    await Project("myproj").build()
    r = await client.get("/rank?project=myproj&query=login+error&limit=5")
    assert r.status_code == 200
    assert "results" in r.json()


@pytest.mark.asyncio
async def test_path_endpoint(client, support_schema, sample_docs):
    await client.post("/projects/myproj")
    from openknet.project import Project
    await Project("myproj").ingest(sample_docs)
    await Project("myproj").build()
    r = await client.get("/path?project=myproj&source=AuthService&target=error+503")
    assert r.status_code == 200
    assert "paths" in r.json()
