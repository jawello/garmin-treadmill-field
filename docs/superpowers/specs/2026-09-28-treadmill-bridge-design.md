# Treadmill Bridge (Raspberry Pi) — Design

Date: 2026-09-28
Status: approved in brainstorming, pending written-spec review
Related: [watch data field design](2026-09-25-treadmill-datafield-design.md)

## Goal

Walk on the Kingsmith R1 Pro with as few manual actions as possible and get accurate
data both in Garmin and in Google Fit / Health Connect:

- **Garmin:** native speed, pace, distance and cadence come from the treadmill; the
  belt starts and stops with the activity timer; treadmill steps are in the FIT file.
- **Google Fit / Health Connect:** treadmill steps count toward daily steps, without
  double counting (delivered by a later Android companion, see "System context").
- The watch keeps its normal phone connection during walks.

This spec covers the **Raspberry Pi daemon** (`bridge/`), the move to a monorepo, the
small watch-field changes it needs, and the HTTP contract the Android companion will use.

## Why a bridge (verified on hardware, 2026-09-25..27)

- The Instinct 3 cannot hold a BLE link to the treadmill: it connects with a 7.5 ms
  interval and the link drops after the 4 s supervision timeout, every ~4.4 s. The
  treadmill also rejects any BLE pairing request and then disconnects. Nothing in
  Connect IQ changes connection parameters, so the watch needs an intermediary.
- A Raspberry Pi 3B+ connects to the treadmill without pairing and keeps the link.
- The watch data field connects to an FE00 GATT server on the Pi and works through it
  (status, FIT, belt commands).
- The Pi can act as a Garmin BLE foot pod (RSC 0x1814) — native speed and distance on
  the watch — given: a primary RSC service, Flags "LE General Discoverable" and
  Appearance 0x0442 in the advert, bonding with Just Works or auto-accepted numeric
  comparison, and cadence sent as strides/min (half of steps/min).
- One Pi controller cannot serve two identities (foot pod + FE00) to the **same**
  central: the second link kills the first (reason 0x08). Links from different centrals
  coexist. → Foot pod and FE00 need **two radios**: built-in + USB adapter (TP-Link
  UB500, RTL8761BU, ordered).
- A phone-based proxy was rejected: Android advertises with the phone's resolvable
  address, the watch recognises it as the already-connected phone and refuses a second
  link; non-resolvable addresses need `BLUETOOTH_PRIVILEGED`.
- Foot pod steps never count toward Garmin daily steps, so Health Connect gets treadmill
  steps from the bridge via the Android companion.

## System context

| Part | Directory | Status |
|---|---|---|
| Connect IQ data field | `watch-field/` | exists; moves into the monorepo; default change below |
| Pi bridge daemon | `bridge/` | this spec |
| Android companion (bridge → Health Connect) | `android/` | later, own spec, after a Google Fit double-count probe |

## Architecture

One Python 3.13 asyncio process, systemd service `treadmill-bridge`, BLE stack
**Bumble** (user-space HCI). `bluetoothd` is disabled; Bumble owns both controllers.

```
        radio A: built-in (UART)                      radio B: USB adapter
  ┌──────────────────────────────────────┐        ┌───────────────────────┐
  │ TreadmillClient ──► StatusHub ◄──────┼────────┤ CiqLink (FE00 server) │◄── watch data field
  │ (central to treadmill)  │  ▲         │        │  query → cached status│
  │                         │  └ cmds ───┼────────┤  start/stop → belt    │
  │ FootPod (RSC server) ◄──┤            │        └───────────────────────┘
  │   → native Garmin fields│            │
  └─────────────────────────┼────────────┘
                            ▼
               SessionRecorder → SQLite ──► HTTP API (LAN) ──► Android → Health Connect
```

| Module | Responsibility | Depends on |
|---|---|---|
| `protocol.py` | FE00 commands and status parsing (port of the field's `WalkingPadProtocol`); pure | — |
| `treadmill.py` | The only treadmill link: find, connect without pairing, poll 1 Hz, reconnect, command queue | Bumble, `protocol`, `hub` |
| `hub.py` | Latest status + subscriptions (async fan-out) | — |
| `odometer.py` | Monotonic steps/distance from treadmill counters; smoothed distance; cadence | — |
| `footpod.py` | RSC foot pod server and advertising on radio A | Bumble, `hub`, `odometer` |
| `ciq_link.py` | FE00 server and advertising on radio B | Bumble, `hub`, `treadmill` |
| `sessions.py` | Walking sessions and per-minute step buckets in SQLite | `hub`, `odometer` |
| `api.py` | HTTP API for the Android companion | `sessions`, `hub` |
| `radios.py` | Map controllers by bus (UART = A, USB = B) to Bumble transports | — |
| `config.py`, `main.py` | TOML config, wiring, logging, lifecycle | all |

Key decisions:

- **Only the daemon polls the treadmill.** The field's status queries are answered
  from the cache, so there is one 1 Hz poll and no duplicate writes (KingSmith firmware
  drops writes that come too close together).
- **Radio A plays two roles:** central to the treadmill and peripheral (foot pod) to
  the watch — links from different centrals, which the Pi handled in the spikes.
- **Walking sessions follow the treadmill belt**, not the watch activity, so steps
  reach Health Connect even without a watch workout.
- **Watch-facing services exist only while the treadmill link is up** (see
  "Advertising lifecycle").

## Treadmill link (`treadmill.py`)

- **Discovery:** first run scans for FE00 in adverts and stores the address in the
  config; afterwards it connects to that address directly (faster, never picks a
  neighbour's WalkingPad).
- **Connection:** no pairing; subscribe to FE01 notifications.
- **Polling:** status query every 1 s; replies parsed and checksum-verified by
  `protocol`, then published to `StatusHub` together with the raw bytes.
- **Commands:** `start` and `stop` are queued ahead of the poll; a `stop` replaces a
  pending `start`; at least 0.4 s between writes. Bytes: query `f7 a2 00 00 a2 fd`,
  start `f7 a2 04 01 a7 fd`, stop `f7 a2 01 00 a3 fd`.
- **Lifecycle:** on disconnect the status becomes "no link" and reconnect attempts back
  off 1 → 2 → 5 → 10 s, then every 10 s until the treadmill wakes. With a live link but
  no valid reply for 5 s, the link is recreated.

## Advertising lifecycle

- Treadmill link up → start advertising foot pod (radio A) and FE00 (radio B).
- Treadmill link lost → for **30 s** the foot pod keeps notifying speed 0 (covers
  short reconnects); then the daemon disconnects the watch on both radios and stops
  advertising. The watch shows its native "foot pod lost" alert and the field shows
  "Searching..." — both match reality.
- Result: when the treadmill is off, no "foot pod" is on air, so other watch activities
  near home never pick it up.

## Foot pod (`footpod.py`, radio A)

- **Advert:** Flags `0x06`, complete 16-bit UUID list `0x1814`, Appearance `0x0442`
  (Running Walking Sensor: On-Shoe); scan response name "Treadmill Pod"; 100 ms
  interval; own address = radio A public address (stable identity for the bond).
- **GATT:**
  - RSC `0x1814`: Measurement `0x2A53` (notify), Feature `0x2A54` = `0x0002`
    (total distance supported);
  - Battery `0x180F`: level 100 (no low-battery alerts);
  - Device Information `0x180A`: manufacturer "treadmill-bridge".
- **Measurement, 2 Hz on a fixed grid** (changed 2026-10-05 from 1 Hz with a sleep after
  each tick: that ran at ~1.03 s, so every ~33 s a watch second got no measurement, the
  watch recorded speed 0 and Auto Pause stopped the belt), flags `0x02` (total distance
  present, walking):
  - speed = belt km/h ÷ 3.6 × 256 when belt state is 1 (running), else 0;
  - cadence = steps/min ÷ 2 over the last 10 s window (Garmin doubles it);
  - total distance, 0.1 m units, from the odometer: sums treadmill counter deltas,
    survives counter resets, smooths between 10 m steps (never more than +10 m ahead,
    never decreasing).
- **`hold_speed_during_start`** (config, default `false`): while the belt is in
  countdown (states 6–9) or within 15 s after a start command, report at least 1.0 km/h
  (the belt first crawls at ~0.4 km/h after the countdown) so Garmin Auto Pause does not
  pause the timer and make the field stop the belt. Enabled on the Pi since acceptance.
- **Pairing:** Just Works with bonding (IO capability NoInputNoOutput); numeric
  comparison is auto-accepted if the watch asks; keys in
  `/var/lib/treadmill-bridge/keys.json`. Lost keys → remove and re-add the foot pod on
  the watch (README). In the watch's sensor wizard, wait for it to finish — pressing a
  button early aborts it.

## Field link (`ciq_link.py`, radio B)

- **Advert:** Flags `0x06`, UUID `FE00`, name "TM-Bridge"; own address = radio B public
  address. The field matches on FE00 only, so it needs no change.
- **GATT:** FE00 with FE01 (read, notify) and FE02 (write, write without response).
- **FE02 writes:**
  - status query → notify that connection with the latest treadmill packet,
    byte-for-byte, if it is at most 3 s old; otherwise send nothing (the field then
    reports "Link error", which is true);
  - start / stop → the treadmill command queue;
  - anything else → dropped and logged (only three known commands ever reach the belt).
- **Pairing:** not required (Connect IQ does not pair); accepted if requested.
- **No radio B present:** the daemon runs without the field link and reports it in
  `/api/v1/status` and the log.

## Sessions and storage (`sessions.py`)

- **Minute buckets** (the unit synced to Health Connect): for each UTC minute with
  treadmill steps: `start`, `end`, `steps`, `distance_m`, `active_seconds`, `version`
  (last update time). Steps come from odometer deltas.
- **Session:** from "belt running" until the belt stays stopped or the treadmill stays
  unreachable for more than 2 min. Short stops stay in one session. Sessions serve
  status and history; buckets go to Health Connect.
- **Owner only (added 2026-09-30):** steps are recorded only while the owner's watch is
  connected to the bridge (foot pod on radio A or FE00 on radio B). The owner is any
  watch bonded with the foot pod (read from the bridge keystore, refreshed when a new
  bond is stored), so nothing needs configuring; someone else walking without such a
  watch is not counted. A watch link drop keeps counting for 5 minutes. Without the
  owner, the odometer baseline keeps moving so their steps never leak in later.
- **Time:** the Pi has no RTC. Until systemd-timesyncd reports synchronisation, the
  daemon does not record buckets and logs a warning.
- **Storage:** SQLite `/var/lib/treadmill-bridge/bridge.db` (`step_buckets`,
  `sessions`); 90-day retention.

## HTTP API (`api.py`)

LAN only, port 8080, `Authorization: Bearer <token>` from the config; JSON.

| Request | Response |
|---|---|
| `GET /api/v1/status` | link states (treadmill, foot pod, field), latest status (belt state, speed, counters), radio B presence, uptime |
| `GET /api/v1/steps?since=<unix>&until=<unix>` | final minute buckets (served 11 s after the minute ends, never changed afterwards): `start`, `end`, `steps`, `distance_m`, `active_seconds`, `version` (integer, ms) |
| `GET /api/v1/sessions?since=<unix>` | sessions: `start`, `end`, `steps`, `distance_m` |

Idempotent sync contract: the companion writes each bucket to Health Connect with
`clientRecordId = "tmb-<start>"` and `clientRecordVersion = version`, so repeated syncs
replace instead of duplicating. Overlap with Garmin's own steps is resolved in the
Android spec after the Google Fit probe.

Not in scope: writing exercise sessions (Garmin already does), access from outside the
home network, a web UI.

## Monorepo, deployment and operations

```
watch-field/   manifest, source, test, resources, Makefile, tools/mtp_send.py (moved)
bridge/        pyproject.toml + uv.lock, src/treadmill_bridge/, tests/, deploy/
android/       later
docs/          specs and plans for all parts
README.md      system overview, links to part READMEs
```

- **On the Pi:** code in `/opt/treadmill-bridge`; `uv sync` (Bumble pinned in
  `uv.lock`); systemd unit `treadmill-bridge` running as user `treadmill` with
  `AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW`, `Restart=always`; `bluetoothd`
  disabled; controllers powered down for Bumble in `ExecStartPre`.
- **Radio mapping by bus**, not index (`hci0`/`hci1` may swap): UART = radio A,
  USB = radio B.
- **Config** `/etc/treadmill-bridge/config.toml`: `treadmill_address` (filled on first
  connect), `api_token`, `api_port`, `hold_speed_during_start`, `log_level`.
- **Logs:** journald (`journalctl -u treadmill-bridge`), every state change and error
  reason.
- **Update from the laptop:** `make deploy` in `bridge/` — rsync, `uv sync`, restart.
- **Watch field changes:** code moves to `watch-field/`; `controlBelt` defaults to
  `true` (sideloaded apps cannot be configured from Garmin Connect); no on-watch toggle
  until needed.

## Testing

- **Unit (pytest):** `protocol` on the real captured packets plus corrupted ones;
  odometer (resets, smoothing, monotonicity); cadence ÷ 2 and RSC Measurement bytes
  (as seen in btmon); sessions/buckets with injected time (minute rollover, pauses
  under/over 2 min, lost treadmill, unsynced clock); `ciq_link` command whitelist and
  3 s cache freshness; API responses and missing-token rejection.
- **Integration without hardware:** Bumble virtual controllers on one local link — fake
  treadmill (FE00 server replying with real packets), the daemon, and a fake watch
  (connects to the foot pod and to FE00). Covers connect/poll, start/stop relay,
  treadmill loss and advertising stop, foot pod bonding.
- **Hardware gates, first in the plan (stop and report if they fail):**
  1. Bumble on the Pi connects to the treadmill as a central and polls it.
  2. With the UB500: the watch holds the foot pod (radio A) and FE00 (radio B) links at
     the same time.
- **Acceptance (README checklist, with the user):** native speed/pace/distance/cadence
  match the treadmill; the field shows data and start/pause/resume/stop drive the belt;
  Garmin Auto Pause behaviour → decide `hold_speed_during_start`; treadmill
  sleep/wake → foot pod disappears/returns, daemon reconnects; Pi reboot → 5 GHz Wi-Fi
  persists, service up, time synced; after a walk `GET /api/v1/steps` returns buckets
  whose sum matches the treadmill display.
