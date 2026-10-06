"""Fixed-rate ticks: slots on a grid from the start, so the work in a tick never adds drift."""

from __future__ import annotations

import time
from collections.abc import Callable


class FixedRate:
    def __init__(self, period: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._period = period
        self._clock = clock
        self._start = clock()

    def delay(self) -> float:
        """Seconds until the next slot; a late tick skips the slots it missed."""
        elapsed = self._clock() - self._start
        return self._period - elapsed % self._period
