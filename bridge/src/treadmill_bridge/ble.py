"""Small Bumble helpers shared by the peripherals."""

from __future__ import annotations

from bumble.core import AdvertisingData
from bumble.device import Connection, Device
from bumble.hci import Role
from bumble.pairing import PairingConfig, PairingDelegate


def peripheral_connections(device: Device) -> list[Connection]:
    """Links where this device is the peripheral (the watch), never our own central links."""
    return [c for c in device.connections.values() if c.role == Role.PERIPHERAL]


def enable_just_works(device: Device) -> None:
    device.pairing_config_factory = lambda _connection: PairingConfig(
        sc=True,
        mitm=False,
        bonding=True,
        delegate=PairingDelegate(PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT),
    )


def advertising_payload(entries: list[tuple[int, bytes]]) -> bytes:
    return bytes(AdvertisingData(entries))
