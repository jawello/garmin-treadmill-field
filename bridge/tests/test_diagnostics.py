import asyncio
import logging

from treadmill_bridge.diagnostics import AclRecorder, StatusGapMonitor, acl_snapshot, log_connections
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


class FakeQueue:
    """The two DataPacketQueue entry points the recorder wraps, plus its counters."""

    max_in_flight = 7

    def __init__(self):
        self._packets = []
        self._connection_state = {}
        self.enqueued = []
        self.completed = []

    def enqueue(self, packet, connection_handle):
        self.enqueued.append((packet, connection_handle))

    def on_packets_completed(self, packet_count, connection_handle):
        self.completed.append((packet_count, connection_handle))

    def flush(self, connection_handle):
        pass


def recorder_with(queue, clock):
    device = type("D", (), {})()
    device.host = type("H", (), {"le_acl_packet_queue": queue})()
    device.connections = {}
    return AclRecorder(device, clock=clock, window_s=5.0)


def test_acl_recorder_reports_sends_completions_and_latency_per_link(caplog):
    caplog.set_level(logging.INFO)
    clock, queue = Clock(), FakeQueue()
    recorder = recorder_with(queue, clock)
    recorder.tick()  # installs on the live queue
    for t in (0.0, 1.0, 2.0):
        clock.t = t
        queue.enqueue(b"n", 65)
    clock.t = 1.5
    queue.on_packets_completed(1, 65)
    clock.t = 3.0
    queue.on_packets_completed(2, 65)
    clock.t = 5.0
    recorder.tick()
    messages = gap_records(caplog)
    assert len(messages) == 1
    assert "handle 65: sent 3, done 3, latency min 1.0 med 1.5 max 2.0 s" in messages[0]
    assert len(queue.enqueued) == 3 and len(queue.completed) == 2  # the real queue still runs


def test_acl_recorder_stays_quiet_without_traffic_and_starts_a_new_window(caplog):
    caplog.set_level(logging.INFO)
    clock, queue = Clock(), FakeQueue()
    recorder = recorder_with(queue, clock)
    recorder.tick()
    clock.t = 5.0
    recorder.tick()
    assert gap_records(caplog) == []
    queue.enqueue(b"n", 64)
    clock.t = 7.0
    recorder.tick()  # window not over yet
    assert gap_records(caplog) == []
    clock.t = 10.0
    recorder.tick()
    assert "handle 64: sent 1, done 0" in gap_records(caplog)[0]


def test_a_dropped_link_does_not_leak_old_send_times_into_a_reused_handle(caplog):
    caplog.set_level(logging.INFO)
    clock, queue = Clock(), FakeQueue()
    recorder = recorder_with(queue, clock)
    recorder.tick()
    queue.enqueue(b"n", 65)
    queue.flush(65)  # disconnection: Bumble drops the link's packets, no completion comes
    clock.t = 10.0
    queue.enqueue(b"n", 65)  # the handle is reused by the next link
    clock.t = 10.5
    queue.on_packets_completed(1, 65)
    clock.t = 11.0
    recorder.tick()
    assert "latency min 0.5 med 0.5 max 0.5 s" in gap_records(caplog)[0]
