"""
Tests for RBAC enforcement.
Verifies that reader/writer/admin roles are actually enforced per endpoint,
not just stored in the scope.
"""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def auth_client(tmp_project):
    """Client with auth enabled."""
    from openknet.config import settings
    from openknet.api.app import app

    # Enable auth with a known admin key
    original_require = settings.require_auth
    original_key = settings.admin_api_key
    settings.require_auth = True
    settings.admin_api_key = "test-admin-key-12345"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    settings.require_auth = original_require
    settings.admin_api_key = original_key


@pytest.fixture
async def reader_key(auth_client):
    """Create a reader API key and return the raw key string."""
    r = await auth_client.post(
        "/keys?name=test-reader&role=reader",
        headers={"X-API-Key": "test-admin-key-12345"},
    )
    assert r.status_code == 200
    return r.json()["key"]


@pytest.fixture
async def writer_key(auth_client):
    r = await auth_client.post(
        "/keys?name=test-writer&role=writer",
        headers={"X-API-Key": "test-admin-key-12345"},
    )
    assert r.status_code == 200
    return r.json()["key"]


# ── No key → 401 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_key_returns_401(auth_client):
    r = await auth_client.get("/projects")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_key_returns_401(auth_client):
    r = await auth_client.get("/projects", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401


# ── Public paths always accessible ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_is_public(auth_client):
    r = await auth_client.get("/health")
    assert r.status_code == 200


# ── Reader can read, cannot write ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reader_can_list_projects(auth_client, reader_key):
    r = await auth_client.get("/projects", headers={"X-API-Key": reader_key})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_reader_cannot_create_project(auth_client, reader_key):
    r = await auth_client.post("/projects/new-proj", headers={"X-API-Key": reader_key})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reader_cannot_build(auth_client, reader_key, support_schema, sample_docs):
    from openknet import OpenKNet
    async with OpenKNet.open("rbac-test", schema=support_schema):
        pass
    r = await auth_client.post(
        "/projects/rbac-test/build",
        headers={"X-API-Key": reader_key},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reader_cannot_create_key(auth_client, reader_key):
    r = await auth_client.post(
        "/keys?name=x&role=reader",
        headers={"X-API-Key": reader_key},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reader_cannot_backup(auth_client, reader_key):
    r = await auth_client.post("/backup", headers={"X-API-Key": reader_key})
    assert r.status_code == 403


# ── Writer can build, cannot manage keys ─────────────────────────────────────

@pytest.mark.asyncio
async def test_writer_can_create_project(auth_client, writer_key):
    r = await auth_client.post("/projects/writer-proj", headers={"X-API-Key": writer_key})
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_writer_cannot_manage_keys(auth_client, writer_key):
    r = await auth_client.post(
        "/keys?name=x&role=reader",
        headers={"X-API-Key": writer_key},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_writer_cannot_backup(auth_client, writer_key):
    r = await auth_client.post("/backup", headers={"X-API-Key": writer_key})
    assert r.status_code == 403


# ── Admin can do everything ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_can_list_keys(auth_client):
    r = await auth_client.get(
        "/keys", headers={"X-API-Key": "test-admin-key-12345"}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_key_via_query_param(auth_client):
    r = await auth_client.get("/projects?api_key=test-admin-key-12345")
    assert r.status_code == 200


# ── schema_path removed from API ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_with_yaml_body(auth_client):
    """Schema must be passed as YAML body, not a server path."""
    schema_yaml = "entities:\n  Component:\n    seed_terms: [AuthService]\n"
    r = await auth_client.post(
        "/projects/yaml-body-test",
        content=schema_yaml,
        headers={
            "X-API-Key": "test-admin-key-12345",
            "Content-Type": "text/yaml",
        },
    )
    assert r.status_code == 201
