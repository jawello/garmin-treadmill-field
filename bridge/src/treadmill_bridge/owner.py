"""Is the owner's watch connected? Treadmill steps are recorded only while it is.

The owner is any watch bonded with the bridge (it paired the foot pod); someone else
walking on the treadmill without such a watch is not counted. A short drop of the watch
link keeps counting for grace_s.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from bumble.device import Device

from .ble import peripheral_connections

GRACE_S = 300.0


def _key(address) -> str:
    return str(address).split("/")[0].upper()


class OwnerPresence:
    def __init__(self, radios: Iterable[Device | None], clock: Callable[[], float] = time.monotonic,
                 grace_s: float = GRACE_S) -> None:
        self._radios = [r for r in radios if r is not None]
        self._clock = clock
        self._grace_s = grace_s
        self._owners: set[str] = set()
        self._last_seen: float | None = None

    @property
    def owners(self) -> set[str]:
        return set(self._owners)

    def set_owners(self, addresses: Iterable[str]) -> None:
        self._owners = {_key(a) for a in addresses}

    async def refresh_owners(self, device: Device) -> None:
        """Owners = peers bonded with the foot pod radio (keystore names are addresses)."""
        if device.keystore is None:
            return
        self.set_owners(name for name, _keys in await device.keystore.get_all())

    def connected(self) -> bool:
        return any(
            _key(c.peer_address) in self._owners
            for radio in self._radios
            for c in peripheral_connections(radio)
        )

    def present(self) -> bool:
        now = self._clock()
        if self.connected():
            self._last_seen = now
            return True
        return self._last_seen is not None and now - self._last_seen <= self._grace_s
