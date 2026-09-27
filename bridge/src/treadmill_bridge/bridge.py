"""Watch-facing services exist only while the treadmill link is up."""

from __future__ import annotations

import time
from collections.abc import Callable

from .hub import StatusHub


class Bridge:
    def __init__(self, hub: StatusHub, footpod, ciq, clock: Callable[[], float] = time.monotonic, grace_s: float = 30.0) -> None:
        self._hub = hub
        self._footpod = footpod
        self._ciq = ciq
        self._clock = clock
        self._grace_s = grace_s

    async def tick(self) -> None:
        now = self._clock()
        if self._hub.link_up:
            await self._footpod.start()
            if self._ciq is not None:
                await self._ciq.start()
        elif now - self._hub.link_changed_at >= self._grace_s:
            await self._footpod.stop()
            if self._ciq is not None:
                await self._ciq.stop()
        await self._footpod.tick(now)
