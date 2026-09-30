#!/bin/sh
# Bumble needs the controllers unblocked and down (HCI user channel); bluetoothd must not own them.
# A newly plugged adapter comes up soft-blocked by rfkill; there is no rfkill tool on Lite, so use sysfs.
for rf in /sys/class/rfkill/rfkill*; do
    [ -e "$rf/type" ] || continue
    [ "$(cat "$rf/type")" = bluetooth ] && echo 0 > "$rf/soft"
done
for dev in /sys/class/bluetooth/hci*; do
    [ -e "$dev" ] || continue
    /usr/bin/hciconfig "$(basename "$dev")" down || true
done
