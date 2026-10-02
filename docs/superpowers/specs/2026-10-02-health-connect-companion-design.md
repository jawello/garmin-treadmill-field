# Health Connect Companion (Android) — Design

Date: 2026-10-02
Status: approved in brainstorming, pending written-spec review
Related: [treadmill bridge design](2026-09-28-treadmill-bridge-design.md) (HTTP API contract)

## Goal

Treadmill steps and distance recorded by the bridge reach Health Connect on the owner's
phone, so they count toward daily steps in Google Fit / Google Health and in any app that
reads Health Connect, without double counting against Garmin Connect, and without manual
actions after a one-time setup.

- Phone: OnePlus 13 (Android 15/16). Health Connect is part of the system there.
- Only the owner's walks reach the phone: the bridge records buckets only while the
  owner's watch is connected (owner rule in the bridge spec).

## Why Health Connect, and how double counting is avoided

Documentation review on 2026-10-02 replaced the planned manual double-count probe:

- Health Connect aggregates Activity data (steps, distance) with a **user-set app
  priority**: where two apps write overlapping intervals, the aggregate keeps the
  higher-priority app's data
  ([aggregate data](https://developer.android.com/health-and-fitness/guides/health-connect/develop/aggregate-data)).
  With the companion above Garmin Connect, treadmill minutes come from the bridge and
  every other minute from Garmin. Per-minute records keep the overlap minimal.
- Google Fit dashboards show Health Connect data; the Google Fit APIs end in 2026 and
  Google Health replaces Google Fit
  ([Fit migration guide](https://developer.android.com/health-and-fitness/health-connect/migration/fit)).
  Health Connect is the durable target.
- Health Connect is on-device only, so a phone app must do the writing; the bridge
  cannot.

Setting the priority is a one-time manual step, documented in the README and hinted at
in the app.

## Scope

In: periodic sync of final minute buckets from `GET /api/v1/steps` into `StepsRecord` and
`DistanceRecord`; settings screen; optional home-network gate; unit and contract tests;
CI build and signed release APK.

Out: exercise sessions (Garmin Connect already writes the workout), reading Health
Connect, deleting records, notifications, Google Play publication, iOS.

## Architecture

Gradle project `android/`, single module `app`, Kotlin, Jetpack Compose.
`minSdk = 34`, `targetSdk` = latest stable.

| Unit | Responsibility | Depends on |
|---|---|---|
| `BridgeClient` | OkHttp `GET /api/v1/steps?since=&until=` and `GET /api/v1/status` with `Authorization: Bearer <token>`, 10 s timeout; parses `Bucket(start, end, steps, distanceM, version)` | network |
| `RecordMapper` | Pure function: bucket → `StepsRecord` + `DistanceRecord` | — |
| `SyncEngine` | One sync pass: gate, window, fetch, write in batches, advance watermark | `NetworkGate`, `BridgeClient`, `HealthConnectClient`, `SyncState` |
| `NetworkGate` | Decides whether the current network may reach the bridge | `ConnectivityManager` |
| `SyncState` | Watermark and last result (time, records written, error) | DataStore |
| `SyncWorker` | Periodic WorkManager job, ~15 min, `NetworkType.UNMETERED`, exponential backoff | `SyncEngine` |
| `MainActivity` | Compose settings and status screen | `SyncEngine`, settings |

Settings (EncryptedSharedPreferences): bridge URL (default `http://192.168.31.250:8080`),
token, home SSID (default empty). Cleartext HTTP is allowed only for the bridge host,
via a network security config.

## Sync algorithm

One `SyncEngine` pass:

1. `NetworkGate`: with an empty home SSID the gate is open. Otherwise read the current
   Wi-Fi SSID via `ConnectivityManager` with `FLAG_INCLUDE_LOCATION_INFO`. A different
   SSID ends the pass as **not home**. An unknown SSID (no permission, location off)
   ends the pass as **network unknown**. In both cases nothing is sent to the bridge.
2. Window: `now` = phone time; `since = max(watermark − 1 h, now − 30 days)`;
   `until = now − 60 s`. With no watermark yet (first run), `since = now − 30 days`.
3. `GET /api/v1/steps?since=&until=`. The bridge serves only final buckets.
4. Map each bucket:
   - `StepsRecord(count = steps)` with `clientRecordId = "tmb-<start>"`;
   - `DistanceRecord(distance = distance_m metres)` with `clientRecordId = "tmb-dist-<start>"`;
   - both with `clientRecordVersion = version`, `startTime = start`, `endTime = end`,
     zone offsets from the system time zone at those instants, and
     `Metadata` recording method "automatically recorded";
   - a bucket with 0 steps yields no steps record; 0 m yields no distance record.
5. `insertRecords` in batches of at most 1000 records. Health Connect upserts by
   `clientRecordId` and ignores a record whose version is not newer, so the 1 h overlap
   and repeated passes never duplicate.
6. Only after every batch succeeds: `watermark = until`, and the result is stored.

A failure at any step ends the pass without moving the watermark; the next pass repeats
the same window safely.

Permissions: `health.WRITE_STEPS`, `health.WRITE_DISTANCE`; with a home SSID set, also
`ACCESS_FINE_LOCATION` and `ACCESS_BACKGROUND_LOCATION`. Background writes need no
extra Health Connect permission.

## Errors

| Situation | Shown status | Worker retries |
|---|---|---|
| Not the home network | "Not home network" | next schedule |
| SSID unknown | "Can't identify network: enable location / allow all the time" + grant button | next schedule |
| Bridge unreachable (connect error, 10 s timeout) | "Bridge unreachable" | backoff |
| HTTP 401 | "Wrong token" | no |
| HTTP 400, other status, malformed JSON | "Bridge response error" + code | no |
| Health Connect permissions missing | "Health Connect permissions needed" + grant button | no |
| Health Connect unavailable or needs update | "Health Connect unavailable" | backoff |
| Health Connect rate limit / quota | "Health Connect limit, retrying later" | backoff |

Away from the bridge's network the status reads "Bridge unreachable" (or "Not home
network"); the bridge keeps its history, so the next pass at home catches up within the
30-day window.

Security note: without a home SSID, a device at the bridge address on a foreign network
would receive the bearer token in cleartext. The token only reads step history; it is
rotated in the bridge config and the app if leaked. The home SSID gate removes this case.

## Screen

One Compose screen, English and Russian strings following the phone language:

- status: last successful sync time, records written, last error;
- "Sync now";
- bridge URL and token fields, "Test connection" (`GET /api/v1/status`);
- home SSID field with "Use current network", which requests the location permissions;
- "Health Connect permissions" button and the priority hint, which opens Health Connect
  settings.

No notifications.

## Testing

JVM unit tests only, no device or emulator:

- `RecordMapper`: steps and distance records from one bucket, ids and versions, zero
  values skipped, zone offsets including a DST transition.
- `BridgeClient` against MockWebServer: bearer header, `since`/`until`, 401, 400,
  timeout, malformed JSON.
- `SyncEngine` with `FakeHealthConnectClient` (`androidx.health.connect:connect-testing`):
  window and first-run backfill; re-sync writes no duplicates; failure in the middle
  keeps the watermark and the next pass completes; batching; missing permissions;
  `NetworkGate` open / home / not home / unknown.
- **Contract test:** a bridge test writes a sample `/api/v1/steps` response to
  `contract/steps-response.json` (and fails if the committed file differs); an Android
  test parses that file. A one-sided API change breaks a test.

The Compose screen holds no logic and is not tested automatically.

## Build, CI and release

- Gradle wrapper, version catalog, Android lint.
- `.github/workflows/android.yml` on changes to `android/**` or `contract/**`:
  `./gradlew test lint assembleRelease`; the APK is uploaded as an artifact.
- Tag `android-v*`: GitHub Release with the signed APK.
- Signing key generated locally, stored outside the repository, passed to CI through
  repository secrets; its values are never printed.

## Setup and acceptance

README steps: install the APK from the Release (allow unknown sources once), enter the
token, grant Health Connect permissions, put the companion above Garmin Connect in Health
Connect's priority for steps and distance, optionally set the home SSID.

Acceptance: CI green; after a treadmill walk the steps appear in Health Connect. No
manual double-count experiment.

## Repository layout

```
android/        Gradle project (this spec)
bridge/         Raspberry Pi daemon
contract/       steps-response.json shared by bridge and Android tests
watch-field/    Connect IQ field
```
