from __future__ import annotations
import asyncio
import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def tmp_project(tmp_path, monkeypatch):
    """Isolated project in a temp directory."""
    from openknet.config import settings
    monkeypatch.setattr(settings, "workspace_root", tmp_path / ".openknet")
    # Reset engine so it picks up new path
    import openknet.db as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    from openknet.db import init_db
    await init_db()
    yield tmp_path


@pytest.fixture
def support_schema(tmp_path) -> Path:
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        """\
entities:
  Customer:
    seed_terms: [ACME, Globex]
  Product:
    seed_terms: [Portal X, Billing API]
  Component:
    seed_terms: [AuthService, BillingService, SessionStore]
  Error:
    seed_terms: [error 503, timeout, login error]
  Incident:
    seed_terms: [INC-1001, INC-1002]

relations:
  reports:
    source: Customer
    target: Incident
    triggers: [reported, reports]
  affects:
    source: Incident
    target: Product
    triggers: [affects, affected]
  involves:
    source: Incident
    target: Component
    triggers: [involves, related to, traced to]
  causes:
    source: Component
    target: Error
    triggers: [causes, caused, triggering, trigger]
  depends_on:
    source: Product
    target: Component
    triggers: [depends on, dependency]
  resolved_by:
    source: Incident
    target: Component
    triggers: [resolved by, mitigated by]
""",
        encoding="utf-8",
    )
    return schema


@pytest.fixture
def sample_docs(tmp_path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "incidents.txt").write_text(
        "INC-1001 reported by ACME affects Portal X. "
        "The login error presents as error 503. "
        "The investigation traced to AuthService triggering error 503. "
        "Portal X depends on AuthService and SessionStore. "
        "INC-1001 was mitigated by AuthService rollback.",
        encoding="utf-8",
    )
    (docs / "runbook.md").write_text(
        "# Runbook\n\n"
        "For login error or error 503 in Portal X, inspect AuthService first. "
        "Portal X depends on AuthService for token validation. "
        "If AuthService causes error 503, restart the service and check SessionStore.",
        encoding="utf-8",
    )
    return docs
