# Treadmill Sync (Android)

Copies treadmill minutes recorded by the [bridge](../bridge/README.md) into Health Connect,
so they count in Google Fit / Google Health and any app reading Health Connect.

## Install

1. Download `treadmill-sync-<version>.apk` from the latest `android-v*` GitHub Release.
2. Open it on the phone and allow installing from this source once.

## Set up (once)

1. Open Treadmill Sync, enter the bridge address (default `http://192.168.31.250:8080`) and
   the `api_token` from `/etc/treadmill-bridge/config.toml`, tap **Save** and **Test connection**.
2. Tap **Health Connect permissions** and allow Steps and Distance.
3. In Health Connect → App permissions → Data and access → Activity → data priority, put
   **Treadmill Sync above Garmin Connect**. Health Connect then counts treadmill minutes from
   the bridge and all other minutes from Garmin.
4. Optional: fill **Home network** (or tap **Use current network**) and allow location
   "All the time"; the token is then sent only on that Wi-Fi.
5. Recommended on OnePlus: Settings → Apps → Treadmill Sync → Battery → Unrestricted, so
   background sync is not deferred.

The app syncs about every 15 minutes on Wi-Fi and on **Sync now**. Away from home it
reports "Bridge unreachable" and catches up later (up to 30 days back).

## Develop

`./gradlew test lint assembleDebug` (JDK 21, Android SDK in `local.properties`).
Release: tag `android-vX.Y.Z` and push; CI builds and signs the APK.
