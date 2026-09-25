# Treadmill data field for Garmin Instinct 3

Connect IQ data field for the Garmin Instinct 3 Solar 45mm that reads a
Kingsmith R1 Pro treadmill over Bluetooth LE and shows belt speed, distance and
steps (the treadmill counts steps with pressure sensors). The values are also
written to the activity FIT file, and the belt can optionally start and stop
with the activity timer.

The R1 Pro does not implement FTMS; it uses the proprietary Kingsmith/WalkingPad
`FE00` protocol. Details: [design spec](docs/superpowers/specs/2026-09-25-treadmill-datafield-design.md).

## Build

Requirements: Java 17+, Connect IQ SDK (SDK Manager) with the Instinct 3 Solar
45mm device, a developer key at `~/.config/garmin/developer_key.der`:

```bash
mkdir -p ~/.config/garmin
openssl genrsa -out ~/.config/garmin/developer_key.pem 4096
openssl pkcs8 -topk8 -inform PEM -outform DER \
  -in ~/.config/garmin/developer_key.pem -out ~/.config/garmin/developer_key.der -nocrypt
```

```bash
make build   # release build -> bin/TreadmillField.prg (real BLE)
make sim     # start the simulator
make test    # unit tests in the simulator
make demo    # debug build with a simulated treadmill
make install # release build, sideloaded to the watch over MTP (Linux)
```

Only the release build (`make build`) talks to the real treadmill; debug builds
use the simulated one.

## Install

1. Connect the watch by USB and copy `bin/TreadmillField.prg` to `GARMIN/APPS/`.
   On Linux, gvfs and `mtp-sendfile` cannot write to the Instinct 3; use
   `make install` instead (needs `libmtp`, e.g. `sudo apt install mtp-tools`).
   It stops the gvfs MTP daemon and sends the file through libmtp.
2. On the watch: Treadmill Walk → hold MENU → Data Screens → pick a screen →
   Edit → pick a field → Connect IQ (bottom of the list) → Treadmill.
3. Optional: in Garmin Connect (phone) → device → Connect IQ apps → Treadmill →
   settings, enable "Start/stop the belt with the activity timer".

The treadmill accepts one Bluetooth connection: close the KS Fit app or turn
off the phone's Bluetooth before the workout.

## Belt control

When enabled: starting or resuming the activity timer starts the belt (after
the treadmill's ~4 s countdown, at its last speed) if the treadmill is
connected and stopped at that moment; pausing or stopping the timer stops the
belt. The belt is never started later than the button press.

## On-watch checklist

1. Walk 5 minutes; speed, distance and steps match the treadmill display.
2. With belt control on: start, pause, resume, stop the timer; the belt follows.
3. Unplug the treadmill mid-workout: "Link error", then "Searching..."; plug it
   back in: values continue without losing the accumulated totals.
4. Full-screen, half and third field sizes are readable; the subscreen does not
   cover important text.
5. In Garmin Connect: treadmill speed chart, treadmill distance and steps in the
   summary.
