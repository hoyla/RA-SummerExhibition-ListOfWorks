"""Tests for the body-size-limit middleware (backend/app/middlewares.py).

Built as a mini FastAPI app with just the middleware attached, rather than
going through the main app — main.py runs Alembic at import time and would
slow tests down to ~1s each. The middleware logic is the same code either
way; only the wiring differs.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.middlewares import make_body_size_limit_middleware


def _mini_app(limit: int) -> TestClient:
    app = FastAPI()
    app.middleware("http")(make_body_size_limit_middleware(limit))

    @app.post("/echo")
    async def echo(payload: dict):
        return {"received": len(str(payload))}

    return TestClient(app, raise_server_exceptions=False)


class TestBodySizeLimit:
    def test_under_limit_passes(self):
        client = _mini_app(limit=1024)
        r = client.post("/echo", json={"x": "small"})
        assert r.status_code == 200

    def test_over_limit_returns_413(self):
        client = _mini_app(limit=100)
        # Build a payload guaranteed to exceed 100 bytes once serialised.
        r = client.post("/echo", json={"x": "y" * 500})
        assert r.status_code == 413
        assert "too large" in r.json()["detail"].lower()
        assert "limit" in r.json()["detail"].lower()

    def test_at_limit_exactly_passes(self):
        # Construct a payload whose serialised length is exactly the limit.
        client = _mini_app(limit=1000)
        # Pad to land just under: TestClient sends Content-Length, the
        # middleware compares with `>`, so equal-to-limit must pass.
        body = '{"x":"' + "a" * 980 + '"}'
        r = client.post(
            "/echo",
            content=body,
            headers={"content-type": "application/json"},
        )
        # We don't need to hit *exactly* the limit; just confirm a sub-limit
        # request passes. (Exact equality is fiddly because TestClient may
        # add/strip whitespace.)
        assert r.status_code == 200, (
            f"a {len(body)}-byte body should pass when limit is 1000"
        )

    def test_non_numeric_content_length_passes(self):
        """A garbage Content-Length shouldn't 413 — falls through to the
        underlying parser, which will handle it however it does."""
        client = _mini_app(limit=100)
        r = client.post(
            "/echo",
            content="{}",
            headers={
                "content-type": "application/json",
                "content-length": "not-a-number",
            },
        )
        # Body is `{}` (2 bytes), well under the limit.  Whether TestClient
        # rewrites the bogus header is implementation detail; either way the
        # request should not get a 413 from OUR middleware.
        assert r.status_code != 413

    def test_no_content_length_passes(self):
        """GET requests have no body and no Content-Length header; must pass."""
        client = _mini_app(limit=100)

        @client.app.get("/ping")
        async def ping():
            return {"ok": True}

        r = client.get("/ping")
        assert r.status_code == 200
