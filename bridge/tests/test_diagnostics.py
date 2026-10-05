import asyncio
import logging

from treadmill_bridge.diagnostics import StatusGapMonitor, acl_snapshot, log_connections
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.protocol import parse_status
from tests.fakes import FakeWatch, virtual_device
from tests.fixtures import WALKING as STATUS_RUNNING


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def gap_records(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "treadmill_bridge.diagnostics"]


def test_steady_statuses_log_nothing(caplog):
    clock = Clock()
    hub = StatusHub(clock)
    monitor = StatusGapMonitor(hub, snapshot=lambda: "acl", clock=clock)
    for second in range(10):
        clock.t = float(second)
        hub.publish(parse_status(STATUS_RUNNING))
        monitor.check()
    assert gap_records(caplog) == []


def test_a_gap_is_logged_once_while_open_and_once_with_its_length(caplog):
    caplog.set_level(logging.INFO)
    clock = Clock()
    hub = StatusHub(clock)
    monitor = StatusGapMonitor(hub, snapshot=lambda: "acl in flight 8/8", clock=clock)
    hub.publish(parse_status(STATUS_RUNNING))
    for t in (1.0, 1.6, 2.2, 2.8):
        clock.t = t
        monitor.check()
    clock.t = 3.2
    hub.publish(parse_status(STATUS_RUNNING))
    messages = gap_records(caplog)
    assert len(messages) == 2
    assert "no treadmill status for 1.6 s" in messages[0] and "acl in flight 8/8" in messages[0]
    assert "treadmill status gap 3.2 s" in messages[1] and "acl in flight 8/8" in messages[1]


def test_no_gap_is_reported_before_the_first_status(caplog):
    clock = Clock()
    monitor = StatusGapMonitor(StatusHub(clock), snapshot=lambda: "acl", clock=clock)
    clock.t = 100.0
    monitor.check()
    assert gap_records(caplog) == []


async def test_watch_connections_and_disconnections_are_logged(link, caplog):
    caplog.set_level(logging.INFO)
    radio = virtual_device(link, "radio-a")
    log_connections(radio, "radio A")
    await radio.power_on()
    await radio.start_advertising(auto_restart=False)
    watch_dev = virtual_device(link, "watch")
    await watch_dev.power_on()
    connection = await FakeWatch(watch_dev).connect(radio.random_address)
    await asyncio.sleep(0.05)
    await connection.disconnect()
    await asyncio.sleep(0.05)
    messages = gap_records(caplog)
    assert any(m.startswith("radio A: peer connected") and "interval" in m and "latency" in m for m in messages)
    assert any(m.startswith("radio A: peer disconnected") for m in messages)


async def test_acl_snapshot_names_the_shared_buffers(link):
    radio = virtual_device(link, "radio-a")
    await radio.power_on()
    assert "acl in flight" in acl_snapshot(radio)
