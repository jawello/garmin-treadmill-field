from treadmill_bridge.storage import Store


def test_bucket_upsert_and_closed_only(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    s.add_to_bucket(600, 10, 12.5, 8.0, 601.0)
    s.add_to_bucket(600, 5, 2.5, 2.0, 650.0)
    s.add_to_bucket(660, 7, 0.0, 3.0, 665.0)
    assert s.buckets(0, 660) == [
        {"start": 600, "end": 660, "steps": 15, "distance_m": 15.0, "active_seconds": 10.0, "version": 650.0}
    ]
    assert len(s.buckets(0, 720)) == 2
    assert s.buckets(660, 720)[0]["start"] == 660


def test_sessions_and_purge(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    s.save_session(1000, 1500, 400, 300.0)
    s.save_session(1000, 1600, 500, 350.0)
    s.save_session(5000, 5100, 50, 40.0)
    assert s.sessions(0) == [
        {"start": 1000, "end": 1600, "steps": 500, "distance_m": 350.0},
        {"start": 5000, "end": 5100, "steps": 50, "distance_m": 40.0},
    ]
    assert [x["start"] for x in s.sessions(2000)] == [5000]
    s.add_to_bucket(600, 1, 1.0, 1.0, 1.0)
    s.purge(4000)
    assert s.sessions(0)[0]["start"] == 5000 and s.buckets(0, 10_000) == []
