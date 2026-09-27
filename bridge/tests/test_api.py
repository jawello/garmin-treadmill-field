from aiohttp.test_utils import TestClient, TestServer

from treadmill_bridge.api import make_app
from treadmill_bridge.storage import Store

TOKEN = "secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def client_for(tmp_path, now=10_000.0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = Store(str(tmp_path / "a.db"))
    store.add_to_bucket(9_900, 50, 40.0, 30.0, 9_950.0)
    store.add_to_bucket(9_960, 10, 8.0, 6.0, 9_990.0)  # still open at now=10_000
    store.save_session(9_900, 9_990, 60, 48.0)
    app = make_app(store, lambda: {"treadmill": "up"}, TOKEN, wall_clock=lambda: now)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_status_steps_sessions(tmp_path):
    client = await client_for(tmp_path)
    try:
        r = await client.get("/api/v1/status", headers=AUTH)
        assert r.status == 200 and (await r.json()) == {"treadmill": "up"}
        r = await client.get("/api/v1/steps?since=0", headers=AUTH)
        body = await r.json()
        assert [b["start"] for b in body["buckets"]] == [9_900]
        assert body["buckets"][0] == {
            "start": 9_900, "end": 9_960, "steps": 50, "distance_m": 40.0, "active_seconds": 30.0, "version": 9_950_000,
        }
        r = await client.get("/api/v1/sessions?since=0", headers=AUTH)
        assert (await r.json())["sessions"][0]["steps"] == 60
    finally:
        await client.close()


async def test_rejects_bad_token_and_bad_params(tmp_path):
    client = await client_for(tmp_path)
    try:
        assert (await client.get("/api/v1/status")).status == 401
        assert (await client.get("/api/v1/status", headers={"Authorization": "Bearer nope"})).status == 401
        assert (await client.get("/api/v1/steps?since=abc", headers=AUTH)).status == 400
        assert (await client.get("/api/v1/sessions?since=1.5x", headers=AUTH)).status == 400
    finally:
        await client.close()


async def test_rejects_non_ascii_token_and_out_of_range_params(tmp_path):
    client = await client_for(tmp_path)
    try:
        assert (await client.get("/api/v1/status", headers={"Authorization": "Bearer é"})).status == 401
        for query in ("since=99999999999999999999", "since=-1", "until=99999999999999999999"):
            assert (await client.get(f"/api/v1/steps?{query}", headers=AUTH)).status == 400, query
        assert (await client.get("/api/v1/sessions?since=-5", headers=AUTH)).status == 400
    finally:
        await client.close()


async def test_bucket_served_only_after_it_can_no_longer_change(tmp_path):
    # Steps reach SQLite every 10 s, so a minute is final only 11 s after it ends.
    client = await client_for(tmp_path, now=9_970.0)  # bucket 9_900..9_960 ended 10 s ago
    try:
        body = await (await client.get("/api/v1/steps?since=0", headers=AUTH)).json()
        assert body["buckets"] == []
    finally:
        await client.close()
    client = await client_for(tmp_path / "second", now=9_971.0)
    try:
        body = await (await client.get("/api/v1/steps?since=0", headers=AUTH)).json()
        assert [b["start"] for b in body["buckets"]] == [9_900]
    finally:
        await client.close()
