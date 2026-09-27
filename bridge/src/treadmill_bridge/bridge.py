"""Watch-facing services exist only while the treadmill link is up."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from .hub import StatusHub

log = logging.getLogger(__name__)


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
            await self._guard("foot pod start", self._footpod.start())
            if self._ciq is not None:
                await self._guard("field bridge start", self._ciq.start())
        elif now - self._hub.link_changed_at >= self._grace_s:
            await self._guard("foot pod stop", self._footpod.stop())
            if self._ciq is not None:
                await self._guard("field bridge stop", self._ciq.stop())
        await self._guard("foot pod notify", self._footpod.tick(now))

    @staticmethod
    async def _guard(what: str, action: Awaitable[None]) -> None:
        # One failing component (an HCI race, a rejected command) must not take the
        # daemon down; the next tick simply tries again.
        try:
            await action
        except Exception as error:
            log.warning("%s failed: %s", what, str(error) or type(error).__name__)
