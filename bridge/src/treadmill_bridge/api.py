"""HTTP API for the Android companion (LAN only, bearer token)."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable

from aiohttp import web

from .storage import Store


MAX_UNIX = 2**40  # far beyond any real timestamp, well inside SQLite's INTEGER range
SETTLE_S = 11  # steps reach SQLite every 10 s: a minute is final 11 s after it ends


def _int_param(request: web.Request, name: str, default: int) -> int:
    raw = request.query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise web.HTTPBadRequest(text=f"{name} must be an integer unix time") from error
    if not 0 <= value <= MAX_UNIX:
        raise web.HTTPBadRequest(text=f"{name} is out of range")
    return value


def _served(bucket: dict) -> dict:
    # Health Connect's clientRecordVersion is a Long: expose the version in milliseconds.
    return {**bucket, "version": int(round(bucket["version"] * 1000))}


def make_app(
    store: Store,
    status_snapshot: Callable[[], dict],
    token: str,
    wall_clock: Callable[[], float] = time.time,
) -> web.Application:
    expected = f"Bearer {token}".encode()

    @web.middleware
    async def auth(request: web.Request, handler):
        given = request.headers.get("Authorization", "").encode("utf-8", "surrogateescape")
        if not hmac.compare_digest(given, expected):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(status_snapshot())

    async def steps(request: web.Request) -> web.Response:
        now = int(wall_clock())
        since = _int_param(request, "since", 0)
        until = min(_int_param(request, "until", now), now - SETTLE_S)
        return web.json_response({"buckets": [_served(b) for b in store.buckets(since, until)]})

    async def sessions(request: web.Request) -> web.Response:
        return web.json_response({"sessions": store.sessions(_int_param(request, "since", 0))})

    app = web.Application(middlewares=[auth])
    app.router.add_get("/api/v1/status", status)
    app.router.add_get("/api/v1/steps", steps)
    app.router.add_get("/api/v1/sessions", sessions)
    return app
