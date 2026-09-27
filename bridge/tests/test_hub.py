from treadmill_bridge import protocol as p
from treadmill_bridge.hub import StatusHub
from tests import fixtures as f


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_publish_and_freshness():
    clock = Clock()
    hub = StatusHub(clock)
    seen = []
    hub.on_status(seen.append)
    status = p.parse_status(f.WALKING)
    hub.publish(status)
    assert seen == [status] and hub.latest is status and hub.latest_at == 100.0
    clock.t = 103.0
    assert hub.fresh_status(3.0) is status
    clock.t = 103.1
    assert hub.fresh_status(3.0) is None


def test_link_changes_notify_once():
    clock = Clock()
    hub = StatusHub(clock)
    changes = []
    hub.on_link(changes.append)
    hub.set_link(True)
    hub.set_link(True)
    clock.t = 110.0
    hub.set_link(False)
    assert changes == [True, False]
    assert hub.link_changed_at == 110.0


def test_note_start():
    clock = Clock()
    hub = StatusHub(clock)
    assert hub.last_start_at is None
    hub.note_start()
    assert hub.last_start_at == 100.0
