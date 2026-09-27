"""Garmin foot pod (BLE Running Speed and Cadence) fed by the treadmill."""

from __future__ import annotations

import logging
import struct
import time
from collections.abc import Callable

from bumble.core import AdvertisingData
from bumble.device import Device
from bumble.gatt import Characteristic, Service
from bumble.hci import OwnAddressType

from .ble import advertising_payload, enable_just_works, peripheral_connections
from .hub import StatusHub
from .odometer import Odometer
from .protocol import Status, is_countdown

log = logging.getLogger(__name__)

RSC_SERVICE = "1814"
RSC_MEASUREMENT = "2A53"
RSC_FEATURE = "2A54"
BATTERY_SERVICE = "180F"
BATTERY_LEVEL = "2A19"
DEVICE_INFORMATION = "180A"
MANUFACTURER_NAME = "2A29"
APPEARANCE_ON_SHOE = 0x0442
FLAGS_GENERAL_DISCOVERABLE_LE_ONLY = 0x06
MEASUREMENT_FLAGS = 0x02  # total distance present, walking
FEATURE_TOTAL_DISTANCE = 0x0002
HOLD_SPEED_MPS = 1.0 / 3.6
HOLD_AFTER_START_S = 8.0
STATUS_FRESH_S = 3.0


def rsc_measurement(speed_mps: float, cadence_strides: int, distance_m: float) -> bytes:
    speed = max(0, min(0xFFFF, round(speed_mps * 256)))
    cadence = max(0, min(0xFF, int(cadence_strides)))
    distance = max(0, min(0xFFFFFFFF, int(distance_m * 10)))
    return struct.pack("<BHBI", MEASUREMENT_FLAGS, speed, cadence, distance)


def pod_speed_mps(status: Status | None, now: float, last_start_at: float | None, hold: bool) -> float:
    if status is None:
        return 0.0
    speed = status.speed_mps
    if hold and speed == 0.0:
        starting = is_countdown(status.state) or (
            last_start_at is not None and now - last_start_at < HOLD_AFTER_START_S
        )
        if starting:
            return HOLD_SPEED_MPS
    return speed


class FootPod:
    def __init__(
        self,
        device: Device,
        hub: StatusHub,
        odometer: Odometer,
        own_address_type: OwnAddressType,
        hold_speed_during_start: bool = False,
        clock: Callable[[], float] = time.monotonic,
        name: str = "Treadmill Pod",
    ) -> None:
        self._device = device
        self._hub = hub
        self._odometer = odometer
        self._own_address_type = own_address_type
        self._hold = hold_speed_during_start
        self._clock = clock
        self._name = name
        self.advertising = False
        self.measurement = Characteristic(
            RSC_MEASUREMENT, Characteristic.Properties.NOTIFY, Characteristic.READABLE, bytes(8)
        )

    def install(self) -> None:
        self._device.add_services(
            [
                Service(
                    RSC_SERVICE,
                    [
                        self.measurement,
                        Characteristic(
                            RSC_FEATURE,
                            Characteristic.Properties.READ,
                            Characteristic.READABLE,
                            struct.pack("<H", FEATURE_TOTAL_DISTANCE),
                        ),
                    ],
                ),
                Service(
                    BATTERY_SERVICE,
                    [
                        Characteristic(
                            BATTERY_LEVEL,
                            Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
                            Characteristic.READABLE,
                            bytes([100]),
                        )
                    ],
                ),
                Service(
                    DEVICE_INFORMATION,
                    [
                        Characteristic(
                            MANUFACTURER_NAME,
                            Characteristic.Properties.READ,
                            Characteristic.READABLE,
                            b"treadmill-bridge",
                        )
                    ],
                ),
            ]
        )
        enable_just_works(self._device)

    async def start(self) -> None:
        if self.advertising:
            return
        await self._device.start_advertising(
            own_address_type=self._own_address_type,
            advertising_data=advertising_payload(
                [
                    (AdvertisingData.FLAGS, bytes([FLAGS_GENERAL_DISCOVERABLE_LE_ONLY])),
                    (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, struct.pack("<H", 0x1814)),
                    (AdvertisingData.APPEARANCE, struct.pack("<H", APPEARANCE_ON_SHOE)),
                ]
            ),
            scan_response_data=advertising_payload(
                [(AdvertisingData.COMPLETE_LOCAL_NAME, self._name.encode())]
            ),
            advertising_interval_min=100.0,
            advertising_interval_max=100.0,
            auto_restart=True,
        )
        self.advertising = True
        log.info("foot pod advertising")

    async def stop(self) -> None:
        if self.advertising:
            await self._device.stop_advertising()
            self.advertising = False
            log.info("foot pod stopped advertising")
        for connection in peripheral_connections(self._device):
            await connection.disconnect()

    def payload(self, now: float) -> bytes:
        status = self._hub.fresh_status(STATUS_FRESH_S)
        speed = pod_speed_mps(status, now, self._hub.last_start_at, self._hold)
        strides = self._odometer.cadence_spm(now) // 2 if status is not None else 0
        return rsc_measurement(speed, strides, self._odometer.smoothed_distance_m(now))

    async def tick(self, now: float) -> None:
        await self._device.notify_subscribers(self.measurement, self.payload(now))
