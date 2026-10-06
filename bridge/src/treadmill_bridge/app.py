"""Component wiring shared by the service entry point and the end-to-end tests."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from bumble.device import Device
from bumble.hci import OwnAddressType

from .bridge import Bridge
from .ciq_link import CiqLink
from .config import Config, State
from .diagnostics import StatusGapMonitor, acl_snapshot, log_connections
from .footpod import FootPod
from .hub import StatusHub
from .odometer import Odometer
from .owner import OwnerPresence
from .sessions import SessionRecorder
from .storage import Store
from .treadmill import TreadmillClient

log = logging.getLogger(__name__)
RETENTION_S = 90 * 86400
STARTED = time.monotonic()


@dataclass(frozen=True)
class Timings:
    poll_interval: float = 1.0
    write_gap: float = 0.4
    stale_after: float = 5.0
    backoff: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)
    grace_s: float = 30.0
    tick_s: float = 1.0
    flush_s: float = 10.0


@dataclass
class Components:
    dev_a: Device
    dev_b: Device | None
    hub: StatusHub
    odometer: Odometer
    store: Store
    recorder: SessionRecorder
    treadmill: TreadmillClient
    footpod: FootPod
    ciq: CiqLink | None
    bridge: Bridge
    owner: OwnerPresence
    timings: Timings
    gaps: StatusGapMonitor

    async def run_ble(self) -> None:
        async def ticker() -> None:
            last_flush = time.monotonic()
            await self._refresh_owners()
            while True:
                await self.bridge.tick()
                self.gaps.check()
                if time.monotonic() - last_flush >= self.timings.flush_s:
                    await self._refresh_owners()
                    try:
                        self.recorder.flush(time.time())
                        self.store.purge(int(time.time()) - RETENTION_S)
                    except Exception:
                        log.exception("saving steps failed")
                    last_flush = time.monotonic()
                await asyncio.sleep(self.timings.tick_s)

        await asyncio.gather(self.treadmill.run(), ticker())

    async def _refresh_owners(self) -> None:
        try:
            await self.owner.refresh_owners(self.dev_a)
        except Exception:
            log.exception("reading bonded watches failed")


def build(
    dev_a: Device,
    dev_b: Device | None,
    config: Config,
    store: Store,
    state: State,
    own_address_type: OwnAddressType,
    time_synced: Callable[[], bool],
    timings: Timings = Timings(),
) -> Components:
    hub = StatusHub()
    odometer = Odometer()
    recorder = SessionRecorder(store, time_synced)
    owner = OwnerPresence([dev_a, dev_b])
    refreshes: set[asyncio.Task] = set()

    def on_bond(*_args) -> None:
        # A watch just bonded with the foot pod: it counts from now on, not from the next poll.
        task = asyncio.ensure_future(owner.refresh_owners(dev_a))
        refreshes.add(task)
        task.add_done_callback(refreshes.discard)

    dev_a.on(Device.EVENT_KEY_STORE_UPDATE, on_bond)

    def on_status(status) -> None:
        steps, distance = odometer.update(status, time.monotonic())
        if not owner.present():
            # Someone else is walking (or the owner's watch is gone): keep the counter
            # baseline moving, but record nothing for the owner.
            steps, distance = 0, 0.0
        recorder.record(status, steps, distance, time.time())

    hub.on_status(on_status)
    log_connections(dev_a, "radio A")
    if dev_b is not None:
        log_connections(dev_b, "radio B")
    gaps = StatusGapMonitor(hub, lambda: acl_snapshot(dev_a))
    hub.on_link(lambda up: None if up else odometer.stall())
    treadmill = TreadmillClient(
        dev_a,
        hub,
        config.treadmill_address or state.treadmill_address,
        own_address_type,
        on_address=state.save_address,
        poll_interval=timings.poll_interval,
        write_gap=timings.write_gap,
        stale_after=timings.stale_after,
        backoff=timings.backoff,
    )
    footpod = FootPod(dev_a, hub, odometer, own_address_type, config.hold_speed_during_start)
    footpod.install()
    ciq = None
    if dev_b is not None:
        ciq = CiqLink(dev_b, hub, treadmill.send_command, own_address_type)
        ciq.install()
    bridge = Bridge(hub, footpod, ciq, grace_s=timings.grace_s)
    pushes: set[asyncio.Task] = set()

    def push_foot_pod() -> None:
        # A start was requested: send the (held) speed now instead of on the next tick.
        task = asyncio.ensure_future(footpod.tick(time.monotonic()))
        pushes.add(task)
        task.add_done_callback(pushes.discard)

    hub.on_start(push_foot_pod)
    return Components(dev_a, dev_b, hub, odometer, store, recorder, treadmill, footpod, ciq, bridge, owner, timings, gaps)


def status_snapshot(c: Components) -> dict:
    latest = c.hub.latest
    return {
        "treadmill": {
            "link_up": c.hub.link_up,
            "belt_state": latest.state if latest else None,
            "speed_kmh": latest.speed_tenths / 10 if latest else None,
            "steps_counter": latest.steps if latest else None,
        },
        "foot_pod": {"advertising": c.footpod.advertising},
        "field_bridge": {"present": c.ciq is not None, "advertising": bool(c.ciq and c.ciq.advertising)},
        "owner": {"present": c.owner.present(), "connected": c.owner.connected(), "watches": sorted(c.owner.owners)},
        "totals": {"steps": c.odometer.steps_total, "distance_m": c.odometer.distance_m},
        "uptime_s": round(time.monotonic() - STARTED),
    }
