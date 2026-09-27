"""Walking sessions and per-minute step buckets."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .protocol import Status
from .storage import BUCKET_SECONDS, Store

log = logging.getLogger(__name__)
MAX_ACTIVE_STEP_S = 5.0


class SessionRecorder:
    def __init__(self, store: Store, time_synced: Callable[[], bool], idle_gap_s: float = 120.0) -> None:
        self._store = store
        self._time_synced = time_synced
        self._idle_gap_s = idle_gap_s
        self._pending: dict[int, list[float]] = {}
        self._session: dict | None = None
        self._last_wall: float | None = None
        self._warned = False

    def record(self, status: Status, steps_delta: int, distance_delta_m: float, wall_now: float) -> None:
        if not self._time_synced():
            if not self._warned:
                log.warning("clock not synchronised yet; not recording steps")
                self._warned = True
            return
        previous = self._last_wall
        self._last_wall = wall_now
        if steps_delta <= 0 and distance_delta_m <= 0:
            return
        active = 0.0
        if status.running and previous is not None:
            active = min(wall_now - previous, MAX_ACTIVE_STEP_S)
        start = int(wall_now // BUCKET_SECONDS) * BUCKET_SECONDS
        bucket = self._pending.setdefault(start, [0, 0.0, 0.0])
        bucket[0] += steps_delta
        bucket[1] += distance_delta_m
        bucket[2] += active
        session = self._session
        if session is None or wall_now - session["end"] > self._idle_gap_s:
            if session is not None:
                self._store.save_session(**session)
            session = {"start": int(wall_now), "end": int(wall_now), "steps": 0, "distance_m": 0.0}
            self._session = session
        session["end"] = int(wall_now)
        session["steps"] += steps_delta
        session["distance_m"] += distance_delta_m

    def flush(self, wall_now: float) -> None:
        for start, (steps, distance, active) in self._pending.items():
            self._store.add_to_bucket(start, int(steps), distance, active, wall_now)
        self._pending.clear()
        if self._session is not None:
            self._store.save_session(**self._session)
