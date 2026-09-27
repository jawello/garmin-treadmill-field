"""Service entry point: open the radios, wire components, serve the API."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

from aiohttp import web
from bumble.device import Device, DeviceConfiguration
from bumble.hci import OwnAddressType
from bumble.transport import open_transport

from .api import make_app
from .app import build, status_snapshot
from .config import State, load_config
from .radios import find_controllers
from .storage import Store

log = logging.getLogger("treadmill_bridge")
TIME_SYNCED_FLAG = "/run/systemd/timesync/synchronized"


async def open_device(index: int, name: str, keystore: str) -> tuple[Device, object]:
    transport = await open_transport(f"hci-socket:{index}")
    config = DeviceConfiguration(name=name, keystore=f"JsonKeyStore:{keystore}")
    device = Device.from_config_with_hci(config, transport.source, transport.sink)
    return device, transport


async def serve(config_path: str) -> None:
    config = load_config(config_path)
    logging.basicConfig(level=config.log_level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("bumble").setLevel(logging.WARNING)
    os.makedirs(config.state_dir, exist_ok=True)
    radios = find_controllers()
    if "uart" not in radios:
        raise SystemExit("built-in Bluetooth controller not found")
    keystore = os.path.join(config.state_dir, "keys.json")
    dev_a, transport_a = await open_device(radios["uart"], "treadmill-bridge-a", keystore)
    dev_b = transport_b = None
    if "usb" in radios:
        dev_b, transport_b = await open_device(radios["usb"], "treadmill-bridge-b", keystore)
    else:
        log.warning("no USB Bluetooth adapter: running without the field bridge")
    store = Store(os.path.join(config.state_dir, "bridge.db"))
    state = State(os.path.join(config.state_dir, "state.json"))
    components = build(
        dev_a, dev_b, config, store, state, OwnAddressType.PUBLIC,
        time_synced=lambda: os.path.exists(TIME_SYNCED_FLAG),
    )
    await dev_a.power_on()
    if dev_b is not None:
        await dev_b.power_on()
    log.info("radio A %s, radio B %s", dev_a.public_address, dev_b.public_address if dev_b else "absent")
    runner = web.AppRunner(make_app(store, lambda: status_snapshot(components), config.api_token))
    await runner.setup()
    await web.TCPSite(runner, config.api_host, config.api_port).start()
    try:
        await components.run_ble()
    finally:
        components.recorder.flush(time.time())
        await runner.cleanup()
        for transport in (transport_a, transport_b):
            if transport is not None:
                await transport.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Kingsmith R1 Pro to Garmin bridge")
    parser.add_argument("--config", default="/etc/treadmill-bridge/config.toml")
    args = parser.parse_args()
    asyncio.run(serve(args.config))
