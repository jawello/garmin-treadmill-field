"""Monotonic treadmill totals that survive counter resets."""

from __future__ import annotations

from collections import deque

from .protocol import Status

SMOOTH_CAP_M = 10.0
CADENCE_WINDOW_S = 10.0
DIST_UNIT_M = 10.0


def _delta(raw: int, last: int) -> int:
    # A counter that went down means the treadmill started a new session from zero.
    return raw - last if raw >= last else raw


class Odometer:
    def __init__(self) -> None:
        self.steps_total = 0
        self.distance_m = 0.0
        self._last_steps: int | None = None
        self._last_dist: int | None = None
        self._speed_mps = 0.0
        self._running = False
        self._display_m = 0.0
        self._display_at: float | None = None
        self._history: deque[tuple[float, int]] = deque()

    def update(self, status: Status, now: float) -> tuple[int, float]:
        if self._last_steps is None or self._last_dist is None:
            steps, dist = 0, 0.0
        else:
            steps = _delta(status.steps, self._last_steps)
            dist = _delta(status.dist_tens, self._last_dist) * DIST_UNIT_M
        self._last_steps, self._last_dist = status.steps, status.dist_tens
        self._advance_display(now)
        self.steps_total += steps
        self.distance_m += dist
        self._display_m = max(self._display_m, self.distance_m)
        self._speed_mps = status.speed_mps
        self._running = status.running
        self._history.append((now, self.steps_total))
        while len(self._history) > 1 and self._history[1][0] <= now - CADENCE_WINDOW_S:
            self._history.popleft()
        return steps, dist

    def smoothed_distance_m(self, now: float) -> float:
        self._advance_display(now)
        return self._display_m

    def cadence_spm(self, now: float) -> int:
        if not self._running or len(self._history) < 2:
            return 0
        (t0, s0), (t1, s1) = self._history[0], self._history[-1]
        if t1 <= t0:
            return 0
        return round((s1 - s0) * 60 / (t1 - t0))

    def stall(self) -> None:
        self._running = False
        self._speed_mps = 0.0

    def _advance_display(self, now: float) -> None:
        if self._display_at is not None and self._running:
            grown = self._display_m + self._speed_mps * (now - self._display_at)
            cap = self.distance_m + SMOOTH_CAP_M
            self._display_m = max(self._display_m, min(grown, cap))
        self._display_at = now
