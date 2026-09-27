"""FE00 server for the Connect IQ data field (radio B)."""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections.abc import Callable

from bumble.core import AdvertisingData
from bumble.device import Device
from bumble.gatt import Characteristic, CharacteristicValue, Service
from bumble.hci import OwnAddressType

from .ble import advertising_payload, enable_just_works, peripheral_connections
from .hub import StatusHub
from .protocol import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID, command_kind

log = logging.getLogger(__name__)
FLAGS_GENERAL_DISCOVERABLE_LE_ONLY = 0x06


class CiqLink:
    def __init__(
        self,
        device: Device,
        hub: StatusHub,
        send_command: Callable[[bytes], None],
        own_address_type: OwnAddressType,
        clock: Callable[[], float] = time.monotonic,
        fresh_s: float = 3.0,
        name: str = "TM-Bridge",
    ) -> None:
        self._device = device
        self._hub = hub
        self._send_command = send_command
        self._own_address_type = own_address_type
        self._clock = clock
        self._fresh_s = fresh_s
        self._name = name
        self._tasks: set[asyncio.Task] = set()
        self.advertising = False
        self.notify = Characteristic(
            NOTIFY_UUID,
            Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
            Characteristic.READABLE,
            bytes(20),
        )
        self.write = Characteristic(
            WRITE_UUID,
            Characteristic.Properties.WRITE_WITHOUT_RESPONSE | Characteristic.Properties.WRITE,
            Characteristic.WRITEABLE,
            CharacteristicValue(write=self._on_write),
        )

    def install(self) -> None:
        self._device.add_service(Service(SERVICE_UUID, [self.notify, self.write]))
        enable_just_works(self._device)

    async def start(self) -> None:
        # Called every tick while the treadmill link is up. Advertise only when no watch is
        # connected and nothing is on air; no auto_restart, so stop() is final (Bumble's
        # auto_restart re-enables a stopped legacy advertiser when the watch disconnects).
        self.advertising = True
        if peripheral_connections(self._device) or self._device.is_advertising:
            return
        await self._device.start_advertising(
            own_address_type=self._own_address_type,
            advertising_data=advertising_payload(
                [
                    (AdvertisingData.FLAGS, bytes([FLAGS_GENERAL_DISCOVERABLE_LE_ONLY])),
                    (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, struct.pack("<H", 0xFE00)),
                ]
            ),
            scan_response_data=advertising_payload(
                [(AdvertisingData.COMPLETE_LOCAL_NAME, self._name.encode())]
            ),
            advertising_interval_min=100.0,
            advertising_interval_max=100.0,
            auto_restart=False,
        )
        log.info("field bridge advertising")

    async def stop(self) -> None:
        if self.advertising:
            log.info("field bridge going off air")
        self.advertising = False
        if self._device.is_advertising:
            await self._device.stop_advertising()
        for connection in peripheral_connections(self._device):
            await connection.disconnect()

    def _on_write(self, connection, value) -> None:
        data = bytes(value)
        kind = command_kind(data)
        if kind == "query":
            status = self._hub.fresh_status(self._fresh_s)
            if status is not None:
                task = asyncio.ensure_future(self._device.notify_subscriber(connection, self.notify, status.raw))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        elif kind in ("start", "stop"):
            log.info("field asked to %s the belt", kind)
            self._send_command(data)
        else:
            log.warning("dropped unknown field write %s", data.hex())
