"""Find the built-in (UART) and USB Bluetooth controllers, whatever their hci index."""

from __future__ import annotations

import os
import re


def find_controllers(sys_root: str = "/sys/class/bluetooth") -> dict[str, int]:
    if not os.path.isdir(sys_root):
        return {}
    found: dict[str, int] = {}
    for entry in sorted(os.listdir(sys_root)):
        match = re.fullmatch(r"hci(\d+)", entry)
        if not match:
            continue
        target = os.path.realpath(os.path.join(sys_root, entry, "device"))
        bus = "usb" if "/usb" in target else "uart"
        found.setdefault(bus, int(match.group(1)))
    return found
