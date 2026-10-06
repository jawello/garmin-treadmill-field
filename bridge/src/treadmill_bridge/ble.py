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


def link_backlog(connection: Connection) -> int:
    """Packets for this link the controller has not confirmed yet, plus those still in the host queue."""
    queue = getattr(connection.device.host, "le_acl_packet_queue", None)
    if queue is None:
        return 0
    state = getattr(queue, "_connection_state", {}).get(connection.handle)
    in_flight = state.in_flight if state is not None else 0
    waiting = sum(1 for _packet, handle in getattr(queue, "_packets", ()) if handle == connection.handle)
    return in_flight + waiting
