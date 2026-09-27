"""HTTP API for the Android companion (LAN only, bearer token)."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable

from aiohttp import web

from .storage import Store


def _int_param(request: web.Request, name: str, default: int) -> int:
    raw = request.query.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise web.HTTPBadRequest(text=f"{name} must be an integer unix time") from error


def make_app(
    store: Store,
    status_snapshot: Callable[[], dict],
    token: str,
    wall_clock: Callable[[], float] = time.time,
) -> web.Application:
    expected = f"Bearer {token}"

    @web.middleware
    async def auth(request: web.Request, handler):
        if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(status_snapshot())

    async def steps(request: web.Request) -> web.Response:
        now = int(wall_clock())
        since = _int_param(request, "since", 0)
        until = min(_int_param(request, "until", now), now)
        return web.json_response({"buckets": store.buckets(since, until)})

    async def sessions(request: web.Request) -> web.Response:
        return web.json_response({"sessions": store.sessions(_int_param(request, "since", 0))})

    app = web.Application(middlewares=[auth])
    app.router.add_get("/api/v1/status", status)
    app.router.add_get("/api/v1/steps", steps)
    app.router.add_get("/api/v1/sessions", sessions)
    return app
