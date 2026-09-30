# Treadmill bridge (Raspberry Pi)

Python/Bumble daemon on a Raspberry Pi 3B+ that sits between a Kingsmith R1 Pro and a
Garmin Instinct 3. Design: [spec](../docs/superpowers/specs/2026-09-28-treadmill-bridge-design.md).

- Radio A (built-in): connects to the treadmill; acts as a BLE foot pod so the watch's
  native speed, pace, distance and cadence come from the belt.
- Radio B (USB adapter, e.g. TP-Link UB500): FE00 bridge for the Connect IQ field
  (belt start/stop with the activity timer, treadmill steps in FIT). Without it the
  daemon runs radio A only.
- Minute step buckets in SQLite, served over HTTP for the Health Connect companion.

## Install / update

From the laptop: `make deploy` (rsync + `deploy/install.sh` on the Pi). The installer
creates user `treadmill`, installs `uv`, syncs dependencies, writes
`/etc/treadmill-bridge/config.toml` with a random API token, disables `bluetoothd` and
enables `treadmill-bridge.service`.

## Operate

- Logs: `make logs` (`journalctl -u treadmill-bridge`).
- Status: `make status` (`GET /api/v1/status`).
- API (`Authorization: Bearer <api_token>`): `/api/v1/status`,
  `/api/v1/steps?since=<unix>&until=<unix>`, `/api/v1/sessions?since=<unix>`.
- Data: `/var/lib/treadmill-bridge/` (`bridge.db`, `keys.json`, `state.json`).

## Whose steps are recorded

Only while **your** watch is connected to the bridge (the watch that paired the foot pod,
typically during a Treadmill Walk activity). Someone else walking on the treadmill, or you
walking without the activity open, is not recorded. A drop of the watch link keeps counting
for 5 minutes. `GET /api/v1/status` shows `owner.present` and the bonded watches.

## Pair the foot pod

Watch: hold MENU → Sensors & Accessories → Add New → Foot Pod, pick "Treadmill Pod",
then **wait** until the watch finishes (pressing a button early aborts the wizard). The
treadmill must be on: the foot pod is only on air while the bridge is connected to it.
If `keys.json` is lost, remove the foot pod on the watch and add it again.

## Acceptance checklist

1. Native speed, pace, distance and cadence on the watch match the treadmill.
2. The field shows data; START / pause / resume / stop drive the belt (needs radio B).
3. Garmin Auto Pause: check start/resume does not pause-and-stop the belt; if it does,
   set `hold_speed_during_start = true`.
4. Treadmill off → after ~30 s the foot pod is lost on the watch; treadmill on → it
   returns and the daemon reconnects.
5. Pi reboot → service active, 5 GHz Wi-Fi, clock synchronised.
6. After a walk `GET /api/v1/steps` returns buckets whose steps add up to the treadmill
   display.
