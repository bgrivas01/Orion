from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import flood_reports


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(flood_reports, "get_settings", lambda: SimpleNamespace(use_fixtures=False))
    app = FastAPI()
    app.include_router(flood_reports.router)
    return TestClient(app)


def test_reports_preserve_precision_and_nullable_fields(client, monkeypatch):
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetch(self, sql, limit):
            assert limit == 2
            assert "reported_at DESC NULLS LAST, id DESC" in sql
            return [dict(id="9007199254740993", location_name="Bayou", latitude=29.7,
                         longitude=-95.3, water_depth_inches=Decimal("12.5"),
                         severity="high", description=None,
                         reported_at=datetime(2026, 10, 10, tzinfo=timezone.utc))]

    monkeypatch.setattr(flood_reports.db, "pool", lambda: Pool())
    response = client.get("/api/flood-reports?limit=2")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "9007199254740993"
    assert response.json()[0]["water_depth_inches"] == 12.5
    assert response.json()[0]["description"] is None


def test_disconnected_database_is_explicit(client, monkeypatch):
    monkeypatch.setattr(flood_reports.db, "pool", lambda: None)
    assert client.get("/api/flood-reports").status_code == 503


def test_missing_table_does_not_expose_database_details(client, monkeypatch):
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            raise asyncpg.UndefinedTableError("private connection details")
            yield

    monkeypatch.setattr(flood_reports.db, "pool", lambda: Pool())
    response = client.get("/api/flood-reports")
    assert response.status_code == 503
    assert "private" not in response.text


def test_fixture_mode_does_not_query_live_reports(client, monkeypatch):
    monkeypatch.setattr(flood_reports, "get_settings", lambda: SimpleNamespace(use_fixtures=True))
    monkeypatch.setattr(flood_reports.db, "pool", lambda: pytest.fail("Unexpected live query"))
    assert client.get("/api/flood-reports").json() == []


@pytest.mark.parametrize("limit", [0, 501, "bad"])
def test_report_limit_is_validated(client, limit):
    assert client.get(f"/api/flood-reports?limit={limit}").status_code == 422
