"""Latest treadmill status and link state, with listeners."""

from __future__ import annotations

import time
from collections.abc import Callable

from .protocol import Status


class StatusHub:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.latest: Status | None = None
        self.latest_at: float | None = None
        self.link_up = False
        self.link_changed_at = clock()
        self.last_start_at: float | None = None
        self._status_listeners: list[Callable[[Status], None]] = []
        self._link_listeners: list[Callable[[bool], None]] = []
        self._start_listeners: list[Callable[[], None]] = []

    def on_status(self, listener: Callable[[Status], None]) -> None:
        self._status_listeners.append(listener)

    def on_link(self, listener: Callable[[bool], None]) -> None:
        self._link_listeners.append(listener)

    def on_start(self, listener: Callable[[], None]) -> None:
        self._start_listeners.append(listener)

    def publish(self, status: Status) -> None:
        self.latest = status
        self.latest_at = self._clock()
        for listener in self._status_listeners:
            listener(status)

    def set_link(self, up: bool) -> None:
        if up == self.link_up:
            return
        self.link_up = up
        self.link_changed_at = self._clock()
        for listener in self._link_listeners:
            listener(up)

    def note_start(self) -> None:
        self.last_start_at = self._clock()
        for listener in self._start_listeners:
            listener()

    def fresh_status(self, max_age: float) -> Status | None:
        if self.latest is None or self.latest_at is None:
            return None
        return self.latest if self._clock() - self.latest_at <= max_age else None
