"""The response headers, which are the only defence the browser applies for us."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

# No `with`: the lifespan opens a database pool, and nothing here needs one.
client = TestClient(app)


def test_a_data_route_allows_nothing_at_all():
    """The session token lives in localStorage, so an injected script is a session takeover.
    This API serves JSON, SSE and one CSV - there is nothing for a script tag to be doing."""
    csp = client.get("/health").headers["Content-Security-Policy"]
    assert csp.startswith("default-src 'none'")
    assert "jsdelivr" not in csp
    assert "frame-ancestors 'none'" in csp


def test_the_docs_page_may_load_its_own_bundle_and_nothing_else():
    """Swagger UI is the one HTML page here and the README links it. A strict policy that
    silently breaks a documented URL is a policy someone deletes in a hurry."""
    csp = client.get("/docs").headers["Content-Security-Policy"]
    assert "script-src 'self' https://cdn.jsdelivr.net" in csp
    assert "default-src 'none'" in csp, "the exception is for scripts and styles, not for data"


def test_the_usual_four_are_still_set():
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
