"""Keeps contract/steps-response.json equal to what the API really serves.

The Android tests parse the same file, so an API change on one side fails a test.
Regenerate after an intended change: UPDATE_CONTRACT=1 uv run pytest tests/test_contract.py
"""

import json
import os
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from treadmill_bridge.api import make_app
from treadmill_bridge.storage import Store

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "steps-response.json"


async def test_steps_response_matches_contract(tmp_path):
    store = Store(str(tmp_path / "c.db"))
    store.add_to_bucket(1_759_400_000, 105, 80.0, 60.0, 1_759_400_061.25)
    store.add_to_bucket(1_759_400_060, 63, 40.0, 36.09, 1_759_400_121.5)
    store.add_to_bucket(1_759_400_120, 0, 0.0, 2.0, 1_759_400_181.0)
    app = make_app(store, lambda: {}, "t", wall_clock=lambda: 1_759_500_000.0)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = await (await client.get("/api/v1/steps?since=0", headers={"Authorization": "Bearer t"})).json()
    finally:
        await client.close()
    served = json.dumps(body, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_CONTRACT"):
        CONTRACT.parent.mkdir(exist_ok=True)
        CONTRACT.write_text(served)
    assert CONTRACT.read_text() == served
