"""/api/warm: the wake-up call the portfolio page and the daily keep-alive make."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from api import db
from api.main import app


class FakePool:
    queries: list[str] = []

    async def fetchval(self, sql: str):
        self.queries.append(sql)
        return 1


class FakeMcp:
    opened = 0

    @asynccontextmanager
    async def session(self, supplier_id: int):
        FakeMcp.opened += 1
        yield None


def test_warm_touches_the_database_and_opens_an_mcp_session(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(db, "pool", lambda: pool)
    monkeypatch.setattr(app.state, "mcp", FakeMcp(), raising=False)

    response = TestClient(app).get("/api/warm")   # no `with`: the lifespan would open a real pool

    assert response.status_code == 200
    assert pool.queries == ["SELECT 1"]
    assert FakeMcp.opened == 1
