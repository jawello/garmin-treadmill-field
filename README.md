# Kingsmith R1 Pro ↔ Garmin Instinct 3

Walk on a Kingsmith R1 Pro treadmill and get accurate data in Garmin and Health Connect
with minimal manual steps.

| Part | What it does |
|---|---|
| [`watch-field/`](watch-field/README.md) | Connect IQ data field: treadmill speed, distance, steps on the watch, FIT fields, belt start/stop with the activity timer |
| [`bridge/`](bridge/README.md) | Raspberry Pi daemon: owns the treadmill link, acts as a Garmin foot pod, bridges FE00 for the field, records minute step buckets, HTTP API |
| `android/` | planned: syncs step buckets from the bridge into Health Connect |

Design documents: [`docs/superpowers/specs/`](docs/superpowers/specs/).
