"""Diagnostic logs for the radio A stalls (treadmill status gone for ~3 s every ~32 s).

Nothing here changes behaviour; it only records who is connected with which link
parameters, and the shared ACL buffers whenever the treadmill status stops coming.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from bumble.device import Device

from .hub import StatusHub

log = logging.getLogger(__name__)
GAP_S = 1.5


def _parameters(connection) -> str:
    p = connection.parameters
    return (
        f"interval {p.connection_interval:.2f} ms, latency {p.peripheral_latency}, "
        f"timeout {p.supervision_timeout:.0f} ms"
    )


def log_connections(device: Device, label: str) -> None:
    """Log every link on this radio: connect, parameter updates, disconnect."""

    def on_connection(connection) -> None:
        peer = connection.peer_address
        log.info("%s: peer connected %s (%s), %s", label, peer, connection.role.name, _parameters(connection))
        connection.on(
            "connection_parameters_update",
            lambda: log.info("%s: peer %s parameters now %s", label, peer, _parameters(connection)),
        )
        connection.on(
            "disconnection",
            lambda reason: log.info("%s: peer disconnected %s, reason %s", label, peer, reason),
        )

    device.on("connection", on_connection)


def acl_snapshot(device: Device) -> str:
    """The controller's LE ACL buffers, shared by every link on the radio."""
    queue = getattr(device.host, "le_acl_packet_queue", None)
    if queue is None:
        return "acl queue unknown"
    per_link = ", ".join(
        f"handle {handle}: {state.in_flight}"
        for handle, state in getattr(queue, "_connection_state", {}).items()
    )
    return (
        f"acl in flight {getattr(queue, '_in_flight', '?')}/{queue.max_in_flight}, "
        f"waiting {len(getattr(queue, '_packets', ()))} ({per_link or 'no links'})"
    )


class StatusGapMonitor:
    """Reports when the treadmill status stops arriving, and how long it stayed away."""

    def __init__(self, hub: StatusHub, snapshot: Callable[[], str],
                 clock: Callable[[], float] = time.monotonic, gap_s: float = GAP_S) -> None:
        self._snapshot = snapshot
        self._clock = clock
        self._gap_s = gap_s
        self._last: float | None = None
        self._open = False
        hub.on_status(self._on_status)

    def _on_status(self, _status) -> None:
        now = self._clock()
        if self._last is not None and now - self._last >= self._gap_s:
            log.warning("treadmill status gap %.1f s, %s", now - self._last, self._snapshot())
        self._last = now
        self._open = False

    def check(self) -> None:
        if self._last is None or self._open:
            return
        age = self._clock() - self._last
        if age >= self._gap_s:
            self._open = True
            log.warning("no treadmill status for %.1f s, %s", age, self._snapshot())


class AclRecorder:
    """Per link: packets handed to the controller, completions, and how long each took.

    Wraps the host's LE ACL queue (enqueue and the Number Of Completed Packets
    handler) without changing what it does; logs one summary per window.
    """

    def __init__(self, device: Device, clock: Callable[[], float] = time.monotonic, window_s: float = 5.0) -> None:
        self._device = device
        self._clock = clock
        self._window_s = window_s
        self._queue = None
        self._window_start = clock()
        self._sent_at: dict[int, list[float]] = {}
        self._sent: dict[int, int] = {}
        self._latencies: dict[int, list[float]] = {}

    def _install(self) -> None:
        queue = getattr(self._device.host, "le_acl_packet_queue", None)
        if queue is None:
            return
        enqueue, completed, flush = queue.enqueue, queue.on_packets_completed, queue.flush

        def recorded_enqueue(packet, connection_handle):
            self._sent_at.setdefault(connection_handle, []).append(self._clock())
            self._sent[connection_handle] = self._sent.get(connection_handle, 0) + 1
            return enqueue(packet, connection_handle)

        def recorded_completed(packet_count, connection_handle):
            now, pending = self._clock(), self._sent_at.get(connection_handle, [])
            done = self._latencies.setdefault(connection_handle, [])
            for _ in range(min(packet_count, len(pending))):
                done.append(now - pending.pop(0))
            return completed(packet_count, connection_handle)

        def recorded_flush(connection_handle):
            # A dropped link's packets never complete; its handle gets reused.
            self._sent_at.pop(connection_handle, None)
            return flush(connection_handle)

        queue.enqueue, queue.on_packets_completed, queue.flush = recorded_enqueue, recorded_completed, recorded_flush
        self._queue = queue

    def _peer(self, handle: int) -> str:
        connection = self._device.connections.get(handle)
        return f" ({connection.peer_address})" if connection is not None else ""

    def tick(self) -> None:
        if self._queue is None:
            self._install()
            self._window_start = self._clock()
            return
        now = self._clock()
        if now - self._window_start < self._window_s:
            return
        self._window_start = now
        handles = sorted(set(self._sent) | {h for h, v in self._latencies.items() if v})
        if not handles:
            return
        parts = []
        for handle in handles:
            latencies = sorted(self._latencies.get(handle, []))
            part = f"handle {handle}{self._peer(handle)}: sent {self._sent.get(handle, 0)}, done {len(latencies)}"
            if latencies:
                part += (f", latency min {latencies[0]:.1f} med {latencies[len(latencies) // 2]:.1f}"
                         f" max {latencies[-1]:.1f} s")
            parts.append(part)
        log.info("acl %g s: %s; %s", self._window_s, "; ".join(parts), acl_snapshot(self._device))
        self._sent.clear()
        self._latencies.clear()
