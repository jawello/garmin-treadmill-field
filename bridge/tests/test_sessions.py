from treadmill_bridge import protocol as p
from treadmill_bridge.sessions import SessionRecorder
from treadmill_bridge.storage import Store

RUN = p.parse_status(p.build_status(1, 45, 0, 0, 0))
STOP = p.parse_status(p.build_status(0, 0, 0, 0, 0))


def make(tmp_path, synced=True):
    store = Store(str(tmp_path / "s.db"))
    flag = {"synced": synced}
    return store, SessionRecorder(store, lambda: flag["synced"]), flag


def test_minute_buckets_and_rollover(tmp_path):
    store, rec, _ = make(tmp_path)
    base = 1_790_000_080.0  # 40 s into a minute (1_790_000_040 is a minute start)
    for i in range(30):
        rec.record(RUN, 2, 1.25, base + i)
    rec.flush(base + 30)
    buckets = store.buckets(0, 2_000_000_000)
    assert [b["steps"] for b in buckets] == [40, 20]
    assert abs(sum(b["distance_m"] for b in buckets) - 37.5) < 1e-9
    first = int(base // 60) * 60
    assert buckets[0]["start"] == first and buckets[1]["start"] == first + 60


def test_nothing_recorded_until_time_synced(tmp_path):
    store, rec, flag = make(tmp_path, synced=False)
    rec.record(RUN, 5, 3.0, 50.0)  # 1970: clock not synced yet
    rec.flush(51.0)
    assert store.buckets(0, 10**10) == [] and store.sessions(0) == []
    flag["synced"] = True
    rec.record(RUN, 5, 3.0, 1_790_000_000.0)
    rec.flush(1_790_000_001.0)
    assert store.buckets(0, 10**10)[0]["steps"] == 5


def test_sessions_split_by_idle_gap(tmp_path):
    store, rec, _ = make(tmp_path)
    t = 1_790_000_000.0
    rec.record(RUN, 10, 5.0, t)
    rec.record(RUN, 10, 5.0, t + 60)
    rec.record(STOP, 0, 0.0, t + 100)
    rec.record(RUN, 10, 5.0, t + 150)  # 90 s pause: same session
    rec.record(RUN, 10, 5.0, t + 400)  # 250 s gap: new session
    rec.flush(t + 401)
    sessions = store.sessions(0)
    assert [(s["start"], s["end"], s["steps"]) for s in sessions] == [
        (int(t), int(t + 150), 30),
        (int(t + 400), int(t + 400), 10),
    ]


def test_idle_packets_do_not_create_buckets(tmp_path):
    store, rec, _ = make(tmp_path)
    for i in range(5):
        rec.record(STOP, 0, 0.0, 1_790_000_000.0 + i)
    rec.flush(1_790_000_010.0)
    assert store.buckets(0, 10**10) == [] and store.sessions(0) == []
