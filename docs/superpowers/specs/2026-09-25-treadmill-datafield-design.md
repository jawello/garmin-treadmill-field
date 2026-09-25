# Treadmill Data Field for Garmin Instinct 3 — Design

Date: 2026-09-25
Status: approved in brainstorming, pending written-spec review

## Goal

A Connect IQ **data field** for the Garmin Instinct 3 Solar 45mm (monochrome MIP,
176×176) that connects over Bluetooth LE to a Kingsmith R1 Pro treadmill, shows the
belt's speed, distance and step count during a "Treadmill Walk" activity, records
them into the activity FIT file, and optionally starts/stops the belt together with
the activity timer.

The treadmill counts steps with pressure sensors, which is more accurate than the
watch's wrist-based estimate; that is the main reason for the project.

## Non-goals

- Replacing the watch's native distance/speed/steps (not possible from a data field).
- Manual belt control (speed up/down) — data fields receive no button input.
- Choosing among several treadmills, remembering the treadmill between workouts.
- FTMS support — the R1 Pro does not expose it (see below).
- Per-lap FIT fields.

## Treadmill protocol (verified on the user's device, 2026-09-25)

The treadmill advertises as `RE` and exposes **no FTMS service (0x1826)**. It uses the
proprietary Kingsmith/WalkingPad protocol (same as the open-source `ph4-walkingpad`):

| Service / characteristic | Properties | Use |
|---|---|---|
| `0000fe00-0000-1000-8000-00805f9b34fb` | service | advertised; used as scan filter |
| `0000fe01-…` | read, notify | status packets (enable via CCCD `0x2902`) |
| `0000fe02-…` | write without response | commands |

The treadmill does not push status on its own; it answers each status query.
It accepts one BLE connection at a time — the KS Fit phone app must not be connected.

### Commands (all verified)

| Command | Bytes |
|---|---|
| Status query | `f7 a2 00 00 a2 fd` |
| Start belt | `f7 a2 04 01 a7 fd` |
| Stop belt (speed 0) | `f7 a2 01 00 a3 fd` |

### Status packet (20 bytes observed)

| Offset | Field | Scale |
|---|---|---|
| 0 | header `f8` | |
| 1 | type `a2` | |
| 2 | belt state | `0` stopped, `1` running, `3` stopping, `6..9` start countdown |
| 3 | speed | 0.1 km/h |
| 4 | mode | `1` manual |
| 5–7 | time | seconds, big-endian |
| 8–10 | distance | **10 m** units, big-endian |
| 11–13 | steps | count, big-endian |
| 14–17 | misc | byte 16 = remote-button event; ignored |
| len−2 | checksum | sum of bytes `[1 .. len−3]` mod 256 |
| len−1 | footer `fd` | |

Observed behaviour:
- Start: ~4 s countdown (state 9→6), then state 1 and a ~8 s ramp to the last-used speed.
- Stop: one stop command is enough; state goes 1 → 3 → 0 within ~3 s.
- Counters survive a stop and reset to zero on the next start.
- One connection attempt dropped right after a start command; not reproduced, but
  reconnection must be handled.

## Architecture

Single Connect IQ data field, Monkey C, `minApiLevel` 5.0.0, product
`instinct3solar45mm` (exact ID to be confirmed against the SDK device list).
Permissions: `BluetoothLowEnergy`, `FitContributor`. Languages: `eng` (default), `rus`.

Units:

| Unit | Responsibility | Depends on |
|---|---|---|
| `WalkingPadProtocol` | Build command byte arrays; parse and validate status packets. Stateless. | nothing |
| `SessionAccumulator` | Turn raw treadmill counters into workout totals; smooth distance; staleness. | `WalkingPadProtocol` output |
| `TreadmillLink` | BLE scan/pair/subscribe/poll, GATT request queue, reconnect, belt commands, link state. | `BluetoothLowEnergy`, `WalkingPadProtocol` |
| `TreadmillView` (DataField) | `compute()`, `onUpdate()`, timer events, units, FIT fields, settings. | all above |
| `DemoLink` `(:debug)` | Replays recorded packets in the simulator in place of `TreadmillLink`. | `WalkingPadProtocol` |

### TreadmillLink

- `registerProfile` for `FE00` with `FE01` (+ CCCD) and `FE02`; set delegate; start scan.
- `onScanResults`: first result advertising `FE00` → stop scan → `pairDevice`.
- On connect: write `01 00` to the `FE01` CCCD; ready once the descriptor write completes.
- Connect IQ allows one outstanding GATT operation: keep a busy flag, cleared in
  `onDescriptorWrite` / `onCharacteristicWrite`. Pending belt commands take priority
  over the status query. `FE02` requires write-without-response; the exact Monkey C
  write-type option is to be confirmed against SDK docs during implementation.
- Poll: each `compute()` (~1 Hz) sends a status query when ready and not busy.
- `onCharacteristicChanged(FE01)` → `parseStatus`; valid packets update `lastPacketTime`.
- Link states:
  - `SEARCHING` — scanning or connecting.
  - `CONNECTED` — last valid packet ≤ 5 s ago.
  - `ERROR` — disconnect, pairing/CCCD failure, or connected with no valid packet for
    > 5 s. Unpair, hold `ERROR` for 3 s, then return to `SEARCHING` automatically.
    Accumulated totals are kept.

### Belt control

Setting `controlBelt` (boolean, default **off**).

- `onTimerStart` / `onTimerResume`: if `CONNECTED` and belt state is `0`, send start.
  If not connected at that moment, do nothing — never start the belt later.
- `onTimerPause` / `onTimerStop`: if belt state is `1` or `6..9`, send stop. If still
  state `1` after 3 s, resend once.
- Speed is never set; the treadmill uses its own last speed.

### SessionAccumulator

State: `totalDistM`, `totalSteps`, `lastRawDist`, `lastRawSteps` (initially null),
`timerRunning`, `displayDistM`, `speedMps`, `lastPacketTime`.

- First packet: store raw values as baseline; add nothing (pre-workout treadmill
  totals are excluded).
- Later packets: `delta = raw − last`; if `raw < last` the treadmill started a new
  session and `delta = raw`. Add deltas only while `timerRunning`. Always update the
  baseline, so walking during a watch pause is not counted and resume causes no jump.
- Reconnect keeps the baseline: steps walked during an outage are counted on the
  first packet after recovery.
- Smoothed distance: between packets `displayDistM += speedMps × dt`, capped at
  `totalDistM + 10`; on each packet `displayDistM = max(displayDistM, totalDistM)`.
  Never decreases. The screen uses `displayDistM`; FIT session totals use
  `totalDistM`.
- Speed = `speedTenths / 10` km/h, stored as m/s; forced to 0 when state ≠ 1.
- No valid packet for > 5 s: speed is shown as `--`; totals freeze.

### TreadmillView

- Colors: background from `getBackgroundColor()`, text in the contrasting color;
  only `COLOR_BLACK` / `COLOR_WHITE`. All text via `dc.drawText`.
- Layout by field height:
  - ≥ 90 px: three lines — large speed, then distance, then steps.
  - < 90 px: two small lines — `4.5 km/h` and `1.34 · 1520`.
- Status: `SEARCHING` / `ERROR` text replaces values (with last distance/steps below
  if data exists and space allows). "Connected" is shown for 3 s after connecting.
- Strings in resources: English default, Russian in `resources-rus`
  ("Поиск дорожки...", "Подключено", "Ошибка связи").
- Units from `System.getDeviceSettings().distanceUnits`: metric → km/h (1 decimal),
  km (2 decimals); statute → mph, miles. Steps as an integer.

### FIT recording (FitContributor)

| Field | Message | Content |
|---|---|---|
| `treadmill_speed` | RECORD | belt speed, km/h |
| `treadmill_distance` | SESSION | accumulated treadmill distance |
| `treadmill_steps` | SESSION | accumulated treadmill steps |

Labels/units declared in `fitContributions` resources so Garmin Connect shows them.
FIT values are always metric (km/h, km): Connect IQ FIT unit labels are static
resources and cannot follow the device unit setting. The screen follows device units.

## Error handling summary

| Situation | Behaviour |
|---|---|
| Treadmill not advertising / taken by phone | stays `SEARCHING` |
| Invalid / foreign packet | ignored, not an error |
| Disconnect or no valid packet > 5 s | `ERROR` 3 s → rescan; totals kept |
| Belt command while not connected | skipped |
| Stop not effective after 3 s | resent once |

## Testing

- Unit tests `(:test)` run in the simulator (`monkeydo … -t`):
  - `WalkingPadProtocol` with fixtures from real captured packets (stopped;
    4.5 km/h / 16 dist units / 230 steps; countdown `state=9`; stopping `state=3`)
    and corrupted ones (bad checksum, wrong header, short); command bytes match
    the verified ones.
  - `SessionAccumulator`: baseline, normal delta, treadmill reset, watch pause,
    reconnect gap, smoothing cap and monotonicity, speed 0 on state ≠ 1, staleness.
- Build gate, done **first** in implementation: release build for
  `instinct3solar45mm` with the `BluetoothLowEnergy` permission. If the compiler
  rejects BLE for a data field on this device, stop and revisit the architecture
  (custom activity app) with the user before writing the rest.
- Simulator demo `(:debug)`: `DemoLink` replays captured packets to check every
  layout size, all three states and FIT output.
- On-watch checklist (README, performed by the user): sideload `.prg`, add the field
  to "Treadmill Walk", compare with the treadmill display over 5 minutes, test
  `controlBelt` with start/pause/resume/stop, unplug the treadmill mid-workout and
  confirm recovery, check fields in Garmin Connect.

## Tooling

Connect IQ SDK is not yet installed on the dev laptop; implementation plan includes
installing the SDK Manager, the `instinct3solar45mm` device, `monkeyc`, and
generating a developer key. Repository: `~/Documents/personal/garmin-treadmill-field`,
public on GitHub.
