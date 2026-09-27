#!/bin/sh
# Bumble needs the controllers down (HCI user channel); bluetoothd must not own them.
for dev in /sys/class/bluetooth/hci*; do
    [ -e "$dev" ] || continue
    /usr/bin/hciconfig "$(basename "$dev")" down || true
done
