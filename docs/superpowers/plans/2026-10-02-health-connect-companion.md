# Health Connect Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Android app in `android/` that periodically pulls final minute step buckets from the Pi bridge and writes them to Health Connect as idempotent `StepsRecord` and `DistanceRecord` entries.

**Architecture:** Single-module Kotlin app. Pure units (`BridgeClient`, `RecordMapper`, `NetworkGate`, `SyncEngine`) are JVM-tested; thin Android adapters (`AndroidSsidSource`, `SettingsStore`, `SyncWorker`, Compose `MainActivity`) wire them together. A JSON fixture in `contract/` is produced by a bridge test and parsed by an Android test.

**Tech Stack:** Kotlin, Jetpack Compose (Material 3), Health Connect Jetpack client + `connect-testing`, WorkManager, DataStore Preferences, EncryptedSharedPreferences, OkHttp + MockWebServer, kotlinx.serialization, JUnit 4, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-02-health-connect-companion-design.md`

## Global Constraints

- `minSdk = 34`, `targetSdk` = `compileSdk` = latest stable platform installed in Task 2 (36 unless a newer stable exists).
- Package / applicationId: `io.github.jawello.treadmillsync`; app name "Treadmill Sync".
- Default bridge URL `http://192.168.31.250:8080`; cleartext HTTP allowed only for `192.168.31.250` (network security config).
- Steps record id `tmb-<start>`, distance record id `tmb-dist-<start>`, `clientRecordVersion = version` (bridge ms).
- Window: `since = max(watermark − 3600, now − 30 days)`, `until = now − 60`; first run `since = now − 30 days`.
- Batches of at most 1000 records per `insertRecords`.
- Bridge HTTP timeout 10 s.
- Periodic work ~15 min, `NetworkType.UNMETERED`, exponential backoff; retry only for bridge unreachable, Health Connect unavailable, rate limit.
- Strings in English (`values/`) and Russian (`values-ru/`).
- No notifications, no reading Health Connect, no deletes, no exercise sessions.
- Code, comments, commits in English; commits end with the `Co-Authored-By` trailer from the session instructions; push to `main` is allowed.
- Signing secret values are never printed (no `cat`, no `echo` of passwords/keystore).
- `$SP` in commands = the session scratchpad directory; Gradle output goes to a log there and is checked by exit code.

## Review Focus

1. **App opened before setup (token empty).** A pass must end as `NotConfigured` without any HTTP request or crash. → Task 7 test `notConfiguredWhenTokenBlank`.
2. **Token pasted with a trailing newline or a non-ASCII character.** OkHttp rejects such header values with `IllegalArgumentException`. Expected result: tokens are trimmed, and a still-invalid token gives `WrongToken`, not a crash. → Task 3 test `nonAsciiTokenIsReportedNotThrown`, Task 5 test `normalizedTrimsFields`.
3. **Bridge URL typo or a host outside the cleartext allow-list.** Expected result: a visible error (`BridgeError` / `CleartextBlocked`), no crash, no endless retry. → Task 3 tests `badUrlIsReported`, `cleartextBlockedIsReported`.
4. **Phone clock moved back, so the watermark is in the future.** The window must still be valid (`since < until`) and re-sync the last hour. → Task 7 test `watermarkInFutureIsClamped`.
5. **One malformed bucket from the bridge (`end <= start`, steps above the Health Connect limit).** It must be skipped, and the rest of the window must still sync. → Task 4 test `invalidBucketYieldsNoRecords`.

---

## File Structure

```
contract/steps-response.json                 bridge→android API sample (Task 1)
bridge/tests/test_contract.py                writes/verifies the sample (Task 1)
.github/workflows/bridge.yml                 + contract/** path (Task 1)
.github/workflows/android.yml                test+lint+assemble on push (Task 2)
.github/workflows/android-release.yml        signed APK on tag android-v* (Task 10)
android/
  settings.gradle.kts, build.gradle.kts, gradle.properties, gradle/libs.versions.toml, gradlew…
  README.md                                   setup guide (Task 10)
  app/build.gradle.kts
  app/src/main/AndroidManifest.xml
  app/src/main/res/xml/network_security_config.xml
  app/src/main/res/values{,-ru}/strings.xml
  app/src/main/java/io/github/jawello/treadmillsync/
    bridge/Bucket.kt             Bucket, StepsResponse (Task 3)
    bridge/BridgeApi.kt          BridgeApi interface, BridgeException (Task 3)
    bridge/BridgeClient.kt       OkHttp implementation (Task 3)
    health/RecordMapper.kt       bucket → records (Task 4)
    health/HealthStore.kt        HealthStore, HealthConnectStore, UnavailableHealthStore (Task 7)
    net/NetworkGate.kt           GateResult, SsidSource, NetworkGate, normalizeSsid (Task 5)
    net/AndroidSsidSource.kt     ConnectivityManager SSID (Task 8)
    settings/Settings.kt         Settings + normalized() + DEFAULT_BRIDGE_URL (Task 5)
    settings/SettingsStore.kt    EncryptedSharedPreferences (Task 8)
    sync/SyncState.kt            SyncSnapshot, SyncStateStore, DataStoreSyncState (Task 6)
    sync/SyncOutcome.kt          outcomes, retry flag, keys (Task 7)
    sync/SyncEngine.kt           one pass (Task 7)
    sync/SyncWorker.kt           worker, workResult(), SyncScheduler (Task 8)
    Graph.kt                     manual wiring (Task 8)
    TreadmillSyncApp.kt          Application: schedules work (Task 8)
    ui/MainActivity.kt           Compose screen (Task 9)
    ui/OutcomeText.kt            outcome key → string (Task 9)
    ui/PermissionsRationaleActivity.kt (Task 9)
  app/src/test/java/io/github/jawello/treadmillsync/…  JVM tests mirroring the above
```

---

### Task 1: Shared API contract fixture (bridge side)

**Files:**
- Create: `bridge/tests/test_contract.py`, `contract/steps-response.json`
- Modify: `.github/workflows/bridge.yml`

**Interfaces:**
- Produces: `contract/steps-response.json` — exact body of `GET /api/v1/steps?since=0` for a fixed store, pretty-printed with `indent=2, sort_keys=True` and a trailing newline. Keys: `buckets[]` with `active_seconds` (float), `distance_m` (float), `end` (int), `start` (int), `steps` (int), `version` (int, ms).

- [ ] **Step 1: Write the failing test**

```python
# bridge/tests/test_contract.py
"""Keeps contract/steps-response.json equal to what the API really serves.

The Android tests parse the same file, so an API change on one side fails a test.
Regenerate after an intended change: UPDATE_CONTRACT=1 uv run pytest tests/test_contract.py
"""

import json
import os
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from treadmill_bridge.api import make_app
from treadmill_bridge.storage import Store

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "steps-response.json"


async def test_steps_response_matches_contract(tmp_path):
    store = Store(str(tmp_path / "c.db"))
    store.add_to_bucket(1_759_400_000, 105, 80.0, 60.0, 1_759_400_061.25)
    store.add_to_bucket(1_759_400_060, 63, 40.0, 36.09, 1_759_400_121.5)
    store.add_to_bucket(1_759_400_120, 0, 0.0, 2.0, 1_759_400_181.0)
    app = make_app(store, lambda: {}, "t", wall_clock=lambda: 1_759_500_000.0)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        body = await (await client.get("/api/v1/steps?since=0", headers={"Authorization": "Bearer t"})).json()
    finally:
        await client.close()
    served = json.dumps(body, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_CONTRACT"):
        CONTRACT.parent.mkdir(exist_ok=True)
        CONTRACT.write_text(served)
    assert CONTRACT.read_text() == served
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd bridge && uv run pytest tests/test_contract.py -q`
Expected: FAIL with `FileNotFoundError` for `contract/steps-response.json`.

- [ ] **Step 3: Generate the fixture and check it by eye**

Run: `cd bridge && UPDATE_CONTRACT=1 uv run pytest tests/test_contract.py -q && cat ../contract/steps-response.json`
Expected: PASS. The file has 3 buckets with starts 1759400000/1759400060/1759400120, versions 1759400061250/1759400121500/1759400181000, and the third bucket has `"steps": 0`.

- [ ] **Step 4: Run the whole bridge suite without the env var**

Run: `cd bridge && uv run pytest -q`
Expected: all pass (72 tests).

- [ ] **Step 5: Add `contract/**` to the bridge workflow paths**

In `.github/workflows/bridge.yml`, change both `paths:` lines to:

```yaml
    paths: ["bridge/**", "contract/**", ".github/workflows/bridge.yml"]
```

- [ ] **Step 6: Commit and push**

```bash
git add bridge/tests/test_contract.py contract/steps-response.json .github/workflows/bridge.yml
git commit -m "Add bridge/Android steps API contract fixture"
git push origin HEAD:main
```

---

### Task 2: Toolchain and Android project skeleton with CI

**Files:**
- Create: `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`, `android/gradle/libs.versions.toml`, `android/app/build.gradle.kts`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/res/values/strings.xml`, `android/app/src/main/res/values-ru/strings.xml`, `android/app/src/main/res/xml/network_security_config.xml`, `android/app/src/test/java/io/github/jawello/treadmillsync/SmokeTest.kt`, `android/.gitignore`, `.github/workflows/android.yml`, Gradle wrapper files.

**Interfaces:**
- Produces: a buildable module `:app` with all dependencies used by later tasks; JVM tests run with `./gradlew test`; system property `contractDir` points at the absolute `contract/` path in every unit test JVM.

- [ ] **Step 1: Install the Android SDK command-line tools locally (no sudo)**

```bash
mkdir -p ~/Android/Sdk/cmdline-tools && cd /tmp/claude-1000/-home-akhadiev-Documents-personal/f8f78205-380d-4a0b-9546-cac3f16b9144/scratchpad
URL=$(curl -fsSL https://developer.android.com/studio | grep -o 'https://dl.google.com/android/repository/commandlinetools-linux-[0-9]*_latest.zip' | head -1)
curl -fsSLo cmdline-tools.zip "$URL" && unzip -qo cmdline-tools.zip -d ~/Android/Sdk/cmdline-tools && rm -rf ~/Android/Sdk/cmdline-tools/latest && mv ~/Android/Sdk/cmdline-tools/cmdline-tools ~/Android/Sdk/cmdline-tools/latest
export ANDROID_HOME=~/Android/Sdk
yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses >/dev/null
$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --list 2>/dev/null | grep -E '^\s+platforms;android-[0-9]+ ' | tail -3
```
Expected: the last line names the newest platform (e.g. `platforms;android-36`). Use the newest one **without** a letter or `-ext` suffix as `<API>`; then:

```bash
$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "platform-tools" "platforms;android-<API>" >/dev/null && ls $ANDROID_HOME/platforms
```
Expected: `android-<API>`. If `<API>` is not 36, record `Ruling: compileSdk <API>`.

- [ ] **Step 2: Resolve dependency versions**

```bash
latest() { # repo group artifact [allow-prerelease]
  curl -fsSL "$1/${2//.//}/$3/maven-metadata.xml" | grep -o '<version>[^<]*</version>' | sed 's/<[^>]*>//g' \
    | { [ -n "$4" ] && cat || grep -Evi 'alpha|beta|rc|dev|eap|-m[0-9]'; } | sort -V | tail -1; }
G=https://dl.google.com/android/maven2; C=https://repo1.maven.org/maven2
for a in "$G com.android.tools.build gradle" "$G androidx.core core-ktx" "$G androidx.activity activity-compose" \
  "$G androidx.compose compose-bom" "$G androidx.health.connect connect-client" "$G androidx.work work-runtime-ktx" \
  "$G androidx.datastore datastore-preferences" "$G androidx.security security-crypto" \
  "$C org.jetbrains.kotlin kotlin-gradle-plugin" "$C com.squareup.okhttp3 okhttp" \
  "$C org.jetbrains.kotlinx kotlinx-serialization-json" "$C org.jetbrains.kotlinx kotlinx-coroutines-core"; do
  set -- $a; echo "$3 $(latest $1 $2 $3)"; done
echo "connect-testing $(latest $G androidx.health.connect connect-testing pre)"
```
Expected: one version per line. Write the versions into `libs.versions.toml` (Step 3). Then check compatibility:
- AGP must be ≤ 8.x or 9.x with a Gradle release it supports (see the AGP release notes table);
- the Kotlin Gradle plugin must be supported by that AGP.

If the newest AGP is 9.x and the build fails because of its built-in Kotlin changes, fall back to the newest 8.x AGP and record a Ruling. `okhttp` stays on the newest 4.x line: MockWebServer 4.x matches it. The default when lookup fails is: AGP 8.13.0, Kotlin 2.2.20, Gradle 8.14.3.

- [ ] **Step 3: Write the Gradle files**

`android/gradle/libs.versions.toml` (replace version strings with Step 2 results):

```toml
[versions]
agp = "8.13.0"
kotlin = "2.2.20"
coreKtx = "1.17.0"
activityCompose = "1.11.0"
composeBom = "2025.09.01"
healthConnect = "1.1.0"
healthConnectTesting = "1.0.0-alpha03"
work = "2.10.5"
datastore = "1.1.7"
securityCrypto = "1.1.0"
okhttp = "4.12.0"
serialization = "1.9.0"
coroutines = "1.10.2"
junit = "4.13.2"

[libraries]
core-ktx = { module = "androidx.core:core-ktx", version.ref = "coreKtx" }
activity-compose = { module = "androidx.activity:activity-compose", version.ref = "activityCompose" }
compose-bom = { module = "androidx.compose:compose-bom", version.ref = "composeBom" }
compose-material3 = { module = "androidx.compose.material3:material3" }
compose-ui = { module = "androidx.compose.ui:ui" }
health-connect = { module = "androidx.health.connect:connect-client", version.ref = "healthConnect" }
health-connect-testing = { module = "androidx.health.connect:connect-testing", version.ref = "healthConnectTesting" }
work-runtime = { module = "androidx.work:work-runtime-ktx", version.ref = "work" }
datastore-preferences = { module = "androidx.datastore:datastore-preferences", version.ref = "datastore" }
security-crypto = { module = "androidx.security:security-crypto", version.ref = "securityCrypto" }
okhttp = { module = "com.squareup.okhttp3:okhttp", version.ref = "okhttp" }
okhttp-mockwebserver = { module = "com.squareup.okhttp3:mockwebserver", version.ref = "okhttp" }
serialization-json = { module = "org.jetbrains.kotlinx:kotlinx-serialization-json", version.ref = "serialization" }
coroutines-android = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-android", version.ref = "coroutines" }
coroutines-test = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "coroutines" }
junit = { module = "junit:junit", version.ref = "junit" }
kotlin-test = { module = "org.jetbrains.kotlin:kotlin-test-junit", version.ref = "kotlin" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
kotlin-serialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
```

`android/settings.gradle.kts`:

```kotlin
pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "treadmill-sync"
include(":app")
```

`android/build.gradle.kts`:

```kotlin
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
}
```

`android/gradle.properties`:

```properties
org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
```

`android/app/build.gradle.kts`:

```kotlin
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "io.github.jawello.treadmillsync"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.jawello.treadmillsync"
        minSdk = 34
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
    lint {
        abortOnError = true
        warningsAsErrors = false
    }
    testOptions {
        unitTests.all { test ->
            test.systemProperty("contractDir", rootProject.file("../contract").absolutePath)
        }
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation(libs.core.ktx)
    implementation(libs.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.material3)
    implementation(libs.compose.ui)
    implementation(libs.health.connect)
    implementation(libs.work.runtime)
    implementation(libs.datastore.preferences)
    implementation(libs.security.crypto)
    implementation(libs.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.coroutines.android)

    testImplementation(libs.junit)
    testImplementation(libs.kotlin.test)
    testImplementation(libs.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.health.connect.testing)
}
```

Replace `36` with `<API>` from Step 1 if different. `jvmToolchain(17)` uses the local JDK 21 through toolchain resolution only if a JDK 17 is present; if Gradle reports no JDK 17, change both `VERSION_17` and `jvmToolchain(17)` to 21 and record a Ruling.

`android/.gitignore`:

```
.gradle/
build/
local.properties
*.jks
.idea/
```

- [ ] **Step 4: Minimal manifest, resources, network security config**

`android/app/src/main/AndroidManifest.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

    <application
        android:label="@string/app_name"
        android:networkSecurityConfig="@xml/network_security_config"
        android:allowBackup="false"
        android:supportsRtl="true" />
</manifest>
```

`android/app/src/main/res/xml/network_security_config.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">192.168.31.250</domain>
    </domain-config>
</network-security-config>
```

`res/values/strings.xml`:

```xml
<resources>
    <string name="app_name">Treadmill Sync</string>
</resources>
```

`res/values-ru/strings.xml`:

```xml
<resources>
    <string name="app_name">Treadmill Sync</string>
</resources>
```

- [ ] **Step 5: Smoke test that proves the contract path is wired**

`android/app/src/test/java/io/github/jawello/treadmillsync/SmokeTest.kt`:

```kotlin
package io.github.jawello.treadmillsync

import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

class SmokeTest {
    @Test
    fun contractFixtureIsReachable() {
        val file = File(System.getProperty("contractDir"), "steps-response.json")
        assertTrue(file.isFile, "missing ${file.absolutePath}")
    }
}
```

- [ ] **Step 6: Generate the Gradle wrapper**

```bash
cd /tmp/claude-1000/-home-akhadiev-Documents-personal/f8f78205-380d-4a0b-9546-cac3f16b9144/scratchpad
GV=8.14.3   # or the Gradle version the chosen AGP requires
curl -fsSLo gradle.zip https://services.gradle.org/distributions/gradle-$GV-bin.zip && unzip -qo gradle.zip
cd /home/akhadiev/Documents/personal/garmin-treadmill-field/android
/tmp/claude-1000/-home-akhadiev-Documents-personal/f8f78205-380d-4a0b-9546-cac3f16b9144/scratchpad/gradle-$GV/bin/gradle wrapper --gradle-version $GV
echo "sdk.dir=$HOME/Android/Sdk" > local.properties
```
Expected: `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.{jar,properties}` exist.

- [ ] **Step 7: Run the tests and the build**

Run: `cd android && ./gradlew test assembleDebug lint > /tmp/claude-1000/-home-akhadiev-Documents-personal/f8f78205-380d-4a0b-9546-cac3f16b9144/scratchpad/gradle.log 2>&1; echo exit=$?; tail -20 /tmp/claude-1000/-home-akhadiev-Documents-personal/f8f78205-380d-4a0b-9546-cac3f16b9144/scratchpad/gradle.log`
Expected: `exit=0`, `BUILD SUCCESSFUL`. The SmokeTest passes. Check the exit code; do not rely on `| tail`, which hides failures.

- [ ] **Step 8: CI workflow**

`.github/workflows/android.yml`:

```yaml
name: android
on:
  push:
    branches: [main]
    paths: ["android/**", "contract/**", ".github/workflows/android.yml"]
  pull_request:
    paths: ["android/**", "contract/**", ".github/workflows/android.yml"]
jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: android
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "21"
      - uses: android-actions/setup-android@v3
      - uses: gradle/actions/setup-gradle@v4
      - run: ./gradlew test lint assembleRelease
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: android-build
          path: |
            android/app/build/outputs/apk/release/*.apk
            android/app/build/reports/
```

- [ ] **Step 9: Commit, push, check CI**

```bash
git add android .github/workflows/android.yml
git commit -m "Add Android companion project skeleton and CI"
git push origin HEAD:main
gh run watch "$(gh run list --workflow android.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
```
Expected: the run succeeds. Release without signing config produces `app-release-unsigned.apk`; that is fine until Task 10.

---

### Task 3: Bucket model and BridgeClient

**Files:**
- Create: `android/app/src/main/java/io/github/jawello/treadmillsync/bridge/Bucket.kt`, `.../bridge/BridgeApi.kt`, `.../bridge/BridgeClient.kt`
- Test: `android/app/src/test/java/io/github/jawello/treadmillsync/bridge/BridgeClientTest.kt`, `.../bridge/ContractTest.kt`

**Interfaces:**
- Produces:
  - `data class Bucket(val start: Long, val end: Long, val steps: Long, val distanceM: Double, val version: Long)`
  - `interface BridgeApi { suspend fun steps(since: Long, until: Long): List<Bucket>; suspend fun ping() }`
  - `sealed class BridgeException : Exception` with `Unreachable(cause: IOException)`, `CleartextBlocked`, `Unauthorized`, `BadToken`, `BadUrl`, `BadResponse(val code: Int?)`
  - `class BridgeClient(baseUrl: String, token: String, http: OkHttpClient = BridgeClient.defaultHttp()) : BridgeApi`
  - `fun parseStepsResponse(json: String): List<Bucket>` (throws `BridgeException.BadResponse(200)` on bad JSON)

- [ ] **Step 1: Write the failing tests**

`BridgeClientTest.kt`:

```kotlin
package io.github.jawello.treadmillsync.bridge

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import java.net.UnknownServiceException
import java.util.concurrent.TimeUnit
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs

class BridgeClientTest {
    private val server = MockWebServer()

    @BeforeTest fun start() = server.start()
    @AfterTest fun stop() = server.shutdown()

    private fun client(token: String = "secret", http: OkHttpClient = BridgeClient.defaultHttp()) =
        BridgeClient(server.url("/").toString().trimEnd('/'), token, http)

    private val body = """{"buckets":[{"active_seconds":60.0,"distance_m":80.0,"end":1060,"start":1000,"steps":105,"version":1061250}]}"""

    @Test fun sendsBearerAndWindowAndParses() = runTest {
        server.enqueue(MockResponse().setBody(body))
        val buckets = client().steps(1000, 2000)
        assertEquals(listOf(Bucket(1000, 1060, 105, 80.0, 1061250)), buckets)
        val request = server.takeRequest()
        assertEquals("Bearer secret", request.getHeader("Authorization"))
        assertEquals("/api/v1/steps?since=1000&until=2000", request.path)
    }

    @Test fun unauthorized() = runTest {
        server.enqueue(MockResponse().setResponseCode(401))
        assertFailsWith<BridgeException.Unauthorized> { client().steps(0, 1) }
    }

    @Test fun badRequestKeepsCode() = runTest {
        server.enqueue(MockResponse().setResponseCode(400))
        val e = assertFailsWith<BridgeException.BadResponse> { client().steps(0, 1) }
        assertEquals(400, e.code)
    }

    @Test fun malformedJson() = runTest {
        server.enqueue(MockResponse().setBody("""{"buckets":[{"start":"x"}]}"""))
        assertFailsWith<BridgeException.BadResponse> { client().steps(0, 1) }
    }

    @Test fun timeoutIsUnreachable() = runTest {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val fast = OkHttpClient.Builder().readTimeout(200, TimeUnit.MILLISECONDS).build()
        assertFailsWith<BridgeException.Unreachable> { client(http = fast).steps(0, 1) }
    }

    @Test fun nonAsciiTokenIsReportedNotThrown() = runTest {
        assertFailsWith<BridgeException.BadToken> { client(token = "tök\n").steps(0, 1) }
    }

    @Test fun badUrlIsReported() = runTest {
        assertFailsWith<BridgeException.BadUrl> { BridgeClient("not a url", "t").steps(0, 1) }
    }

    @Test fun cleartextBlockedIsReported() = runTest {
        val blocking = OkHttpClient.Builder().addInterceptor { throw UnknownServiceException("CLEARTEXT communication to x not permitted") }.build()
        assertFailsWith<BridgeException.CleartextBlocked> { client(http = blocking).steps(0, 1) }
    }

    @Test fun pingHitsStatus() = runTest {
        server.enqueue(MockResponse().setBody("{}"))
        client().ping()
        assertEquals("/api/v1/status", server.takeRequest().path)
    }

    @Test fun defaultTimeoutIsTenSeconds() {
        assertEquals(10_000, BridgeClient.defaultHttp().callTimeoutMillis)
        assertIs<OkHttpClient>(BridgeClient.defaultHttp())
    }
}
```

`ContractTest.kt`:

```kotlin
package io.github.jawello.treadmillsync.bridge

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

class ContractTest {
    @Test fun parsesTheBridgeSample() {
        val json = File(System.getProperty("contractDir"), "steps-response.json").readText()
        val buckets = parseStepsResponse(json)
        assertEquals(
            listOf(
                Bucket(1_759_400_000, 1_759_400_060, 105, 80.0, 1_759_400_061_250),
                Bucket(1_759_400_060, 1_759_400_120, 63, 40.0, 1_759_400_121_500),
                Bucket(1_759_400_120, 1_759_400_180, 0, 0.0, 1_759_400_181_000),
            ),
            buckets,
        )
    }
}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests '*.bridge.*' > $SP/t.log 2>&1; echo exit=$?; grep -E "error:|FAILED|Unresolved" $SP/t.log | head` (where `SP` is the scratchpad path)
Expected: `exit=1`, compilation errors `Unresolved reference: BridgeClient`.

- [ ] **Step 3: Implement**

`Bucket.kt`:

```kotlin
package io.github.jawello.treadmillsync.bridge

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** One final minute of treadmill walking, as served by the bridge's GET /api/v1/steps. */
@Serializable
data class Bucket(
    val start: Long,
    val end: Long,
    val steps: Long,
    @SerialName("distance_m") val distanceM: Double,
    val version: Long,
)

@Serializable
private data class StepsResponse(val buckets: List<Bucket>)

private val json = Json { ignoreUnknownKeys = true }

fun parseStepsResponse(body: String): List<Bucket> =
    try {
        json.decodeFromString<StepsResponse>(body).buckets
    } catch (e: IllegalArgumentException) { // SerializationException is one
        throw BridgeException.BadResponse(200)
    }
```

`BridgeApi.kt`:

```kotlin
package io.github.jawello.treadmillsync.bridge

import java.io.IOException

interface BridgeApi {
    suspend fun steps(since: Long, until: Long): List<Bucket>
    suspend fun ping()
}

sealed class BridgeException(message: String? = null, cause: Throwable? = null) : Exception(message, cause) {
    class Unreachable(cause: IOException) : BridgeException(cause.message, cause)
    class CleartextBlocked : BridgeException()
    class Unauthorized : BridgeException()
    class BadToken : BridgeException()
    class BadUrl : BridgeException()
    class BadResponse(val code: Int?) : BridgeException("HTTP $code")
}
```

`BridgeClient.kt`:

```kotlin
package io.github.jawello.treadmillsync.bridge

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.net.UnknownServiceException
import java.util.concurrent.TimeUnit

class BridgeClient(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient = defaultHttp(),
) : BridgeApi {

    override suspend fun steps(since: Long, until: Long): List<Bucket> {
        val url = endpoint("api/v1/steps").newBuilder()
            .addQueryParameter("since", since.toString())
            .addQueryParameter("until", until.toString())
            .build()
        return parseStepsResponse(get(url))
    }

    override suspend fun ping() {
        get(endpoint("api/v1/status"))
    }

    private fun endpoint(path: String): HttpUrl =
        "${baseUrl.trim().trimEnd('/')}/$path".toHttpUrlOrNull() ?: throw BridgeException.BadUrl()

    private suspend fun get(url: HttpUrl): String = withContext(Dispatchers.IO) {
        val request = try {
            Request.Builder().url(url).header("Authorization", "Bearer $token").build()
        } catch (e: IllegalArgumentException) { // OkHttp rejects non-ASCII or control characters
            throw BridgeException.BadToken()
        }
        try {
            http.newCall(request).execute().use { response ->
                when (response.code) {
                    200 -> response.body?.string() ?: throw BridgeException.BadResponse(200)
                    401 -> throw BridgeException.Unauthorized()
                    else -> throw BridgeException.BadResponse(response.code)
                }
            }
        } catch (e: UnknownServiceException) { // network security config forbids cleartext to this host
            throw BridgeException.CleartextBlocked()
        } catch (e: IOException) {
            throw BridgeException.Unreachable(e)
        }
    }

    companion object {
        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .callTimeout(10, TimeUnit.SECONDS)
            .build()
    }
}
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?; tail -5 $SP/t.log`
Expected: `exit=0`. If `nonAsciiTokenIsReportedNotThrown` fails because OkHttp accepts `ö`, the newline still has to be rejected. In that case change the test token to `"t\n"`, keep the `ö` case as a separate test asserting it does not throw `IllegalArgumentException`, and record a Ruling.

- [ ] **Step 5: Commit**

```bash
git add android/app/src
git commit -m "Add bridge client and contract test for the Android companion"
```

---

### Task 4: RecordMapper

**Files:**
- Create: `android/app/src/main/java/io/github/jawello/treadmillsync/health/RecordMapper.kt`
- Test: `android/app/src/test/java/io/github/jawello/treadmillsync/health/RecordMapperTest.kt`

**Interfaces:**
- Consumes: `Bucket` (Task 3).
- Produces: `object RecordMapper { fun toRecords(bucket: Bucket, zone: ZoneId): List<Record>; const val STEPS_PREFIX = "tmb-"; const val DISTANCE_PREFIX = "tmb-dist-" }`

- [ ] **Step 1: Write the failing tests**

```kotlin
package io.github.jawello.treadmillsync.health

import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.StepsRecord
import io.github.jawello.treadmillsync.bridge.Bucket
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class RecordMapperTest {
    private val riga = ZoneId.of("Europe/Riga")

    @Test fun stepsAndDistanceFromOneBucket() {
        val records = RecordMapper.toRecords(Bucket(1_759_400_000, 1_759_400_060, 105, 80.0, 1_759_400_061_250), riga)
        val steps = assertIs<StepsRecord>(records[0])
        val distance = assertIs<DistanceRecord>(records[1])
        assertEquals(105, steps.count)
        assertEquals(Instant.ofEpochSecond(1_759_400_000), steps.startTime)
        assertEquals(Instant.ofEpochSecond(1_759_400_060), steps.endTime)
        assertEquals("tmb-1759400000", steps.metadata.clientRecordId)
        assertEquals(1_759_400_061_250, steps.metadata.clientRecordVersion)
        assertEquals(80.0, distance.distance.inMeters)
        assertEquals("tmb-dist-1759400000", distance.metadata.clientRecordId)
        assertEquals(1_759_400_061_250, distance.metadata.clientRecordVersion)
        assertEquals(ZoneOffset.ofHours(3), steps.startZoneOffset) // EEST
    }

    @Test fun zeroValuesAreSkipped() {
        assertEquals(emptyList(), RecordMapper.toRecords(Bucket(1000, 1060, 0, 0.0, 1), riga))
        assertIs<StepsRecord>(RecordMapper.toRecords(Bucket(1000, 1060, 5, 0.0, 1), riga).single())
        assertIs<DistanceRecord>(RecordMapper.toRecords(Bucket(1000, 1060, 0, 10.0, 1), riga).single())
    }

    @Test fun offsetsAcrossTheAutumnDstChange() {
        // 2026-10-25 04:00 EEST (01:00 UTC) clocks go back to 03:00 EET.
        val start = Instant.parse("2026-10-25T00:59:30Z").epochSecond
        val steps = RecordMapper.toRecords(Bucket(start, start + 60, 10, 0.0, 1), riga).single() as StepsRecord
        assertEquals(ZoneOffset.ofHours(3), steps.startZoneOffset)
        assertEquals(ZoneOffset.ofHours(2), steps.endZoneOffset)
    }

    @Test fun invalidBucketYieldsNoRecords() {
        assertTrue(RecordMapper.toRecords(Bucket(1060, 1000, 10, 5.0, 1), riga).isEmpty())   // end before start
        assertTrue(RecordMapper.toRecords(Bucket(1000, 1060, 2_000_000, 5.0, 1), riga).isEmpty()) // steps over the HC limit
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests '*RecordMapperTest' > $SP/t.log 2>&1; echo exit=$?; grep -E "Unresolved|FAILED" $SP/t.log | head -3`
Expected: `exit=1`, `Unresolved reference: RecordMapper`.

- [ ] **Step 3: Implement**

```kotlin
package io.github.jawello.treadmillsync.health

import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Length
import io.github.jawello.treadmillsync.bridge.Bucket
import java.time.Instant
import java.time.ZoneId

/** Turns a bridge minute bucket into Health Connect records with stable ids for upserts. */
object RecordMapper {
    const val STEPS_PREFIX = "tmb-"
    const val DISTANCE_PREFIX = "tmb-dist-"

    private val treadmill = Device(type = Device.TYPE_UNKNOWN, manufacturer = "Kingsmith", model = "R1 Pro")

    fun toRecords(bucket: Bucket, zone: ZoneId): List<Record> {
        val start = Instant.ofEpochSecond(bucket.start)
        val end = Instant.ofEpochSecond(bucket.end)
        val startOffset = zone.rules.getOffset(start)
        val endOffset = zone.rules.getOffset(end)
        return try {
            buildList {
                if (bucket.steps > 0) {
                    add(StepsRecord(
                        startTime = start, startZoneOffset = startOffset,
                        endTime = end, endZoneOffset = endOffset,
                        count = bucket.steps,
                        metadata = Metadata.autoRecorded(treadmill, "$STEPS_PREFIX${bucket.start}", bucket.version),
                    ))
                }
                if (bucket.distanceM > 0) {
                    add(DistanceRecord(
                        startTime = start, startZoneOffset = startOffset,
                        endTime = end, endZoneOffset = endOffset,
                        distance = Length.meters(bucket.distanceM),
                        metadata = Metadata.autoRecorded(treadmill, "$DISTANCE_PREFIX${bucket.start}", bucket.version),
                    ))
                }
            }
        } catch (e: IllegalArgumentException) { // HC validates times and value ranges in constructors
            emptyList()
        }
    }
}
```

If `Metadata.autoRecorded(device, clientRecordId, clientRecordVersion)` has a different signature in the resolved `connect-client`, use that version's equivalent factory or constructor and record a Ruling. The test assertions stay the same.

- [ ] **Step 4: Run to verify it passes**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?; tail -3 $SP/t.log`
Expected: `exit=0`. If the tests fail with `Method ... not mocked` (the HC record classes touch the Android framework on the JVM), add `testImplementation("org.robolectric:robolectric:<latest>")` and `@RunWith(RobolectricTestRunner::class)` with `@Config(sdk = [34])` to the HC-touching test classes (this one and Task 7's), set `testOptions.unitTests.isIncludeAndroidResources = true`, and record a Ruling.

- [ ] **Step 5: Commit**

```bash
git add android/app/src
git commit -m "Map bridge buckets to Health Connect records"
```

---

### Task 5: Settings and NetworkGate

**Files:**
- Create: `.../settings/Settings.kt`, `.../net/NetworkGate.kt`
- Test: `.../settings/SettingsTest.kt`, `.../net/NetworkGateTest.kt`

**Interfaces:**
- Produces:
  - `const val DEFAULT_BRIDGE_URL = "http://192.168.31.250:8080"`
  - `data class Settings(val bridgeUrl: String = DEFAULT_BRIDGE_URL, val token: String = "", val homeSsid: String = "") { fun normalized(): Settings; val configured: Boolean }`
  - `enum class GateResult { OPEN, NOT_HOME, UNKNOWN }`
  - `fun interface SsidSource { suspend fun currentSsid(): String? }`
  - `class NetworkGate(source: SsidSource) { suspend fun check(homeSsid: String): GateResult }`
  - `fun normalizeSsid(raw: String?): String?`

- [ ] **Step 1: Write the failing tests**

`SettingsTest.kt`:

```kotlin
package io.github.jawello.treadmillsync.settings

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SettingsTest {
    @Test fun normalizedTrimsFields() {
        val s = Settings(" http://10.0.0.2:8080/ \n", " tok \n", " Home ").normalized()
        assertEquals(Settings("http://10.0.0.2:8080", "tok", "Home"), s)
    }

    @Test fun configuredNeedsUrlAndToken() {
        assertFalse(Settings(token = "").configured)
        assertFalse(Settings(bridgeUrl = " ", token = "t").configured)
        assertTrue(Settings(token = "t").configured)
        assertEquals("http://192.168.31.250:8080", Settings().bridgeUrl)
    }
}
```

`NetworkGateTest.kt`:

```kotlin
package io.github.jawello.treadmillsync.net

import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class NetworkGateTest {
    private var asked = 0
    private fun gate(ssid: String?) = NetworkGate { asked++; ssid }

    @Test fun emptyHomeSsidIsOpenWithoutAsking() = runTest {
        assertEquals(GateResult.OPEN, gate(null).check("  "))
        assertEquals(0, asked)
    }

    @Test fun matchingSsidIsOpen() = runTest { assertEquals(GateResult.OPEN, gate("jawello-wifi").check("jawello-wifi")) }
    @Test fun otherSsidIsNotHome() = runTest { assertEquals(GateResult.NOT_HOME, gate("cafe").check("jawello-wifi")) }
    @Test fun unknownSsidIsUnknown() = runTest { assertEquals(GateResult.UNKNOWN, gate(null).check("jawello-wifi")) }

    @Test fun normalizeSsidStripsQuotesAndUnknown() {
        assertEquals("jawello-wifi", normalizeSsid("\"jawello-wifi\""))
        assertNull(normalizeSsid("<unknown ssid>"))
        assertNull(normalizeSsid("\"\""))
        assertNull(normalizeSsid(null))
    }
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?; grep -E "Unresolved" $SP/t.log | head -3`
Expected: `exit=1`, unresolved `Settings` / `NetworkGate`.

- [ ] **Step 3: Implement**

`Settings.kt`:

```kotlin
package io.github.jawello.treadmillsync.settings

const val DEFAULT_BRIDGE_URL = "http://192.168.31.250:8080"

data class Settings(
    val bridgeUrl: String = DEFAULT_BRIDGE_URL,
    val token: String = "",
    val homeSsid: String = "",
) {
    fun normalized() = Settings(bridgeUrl.trim().trimEnd('/'), token.trim(), homeSsid.trim())

    val configured: Boolean get() = bridgeUrl.isNotBlank() && token.isNotBlank()
}
```

`NetworkGate.kt`:

```kotlin
package io.github.jawello.treadmillsync.net

enum class GateResult { OPEN, NOT_HOME, UNKNOWN }

fun interface SsidSource {
    /** The current Wi-Fi SSID without quotes, or null when Android hides or has none. */
    suspend fun currentSsid(): String?
}

/** Lets the token leave the phone only on the home network, when one is configured. */
class NetworkGate(private val source: SsidSource) {
    suspend fun check(homeSsid: String): GateResult {
        val home = homeSsid.trim()
        if (home.isEmpty()) return GateResult.OPEN
        val current = source.currentSsid() ?: return GateResult.UNKNOWN
        return if (current == home) GateResult.OPEN else GateResult.NOT_HOME
    }
}

private const val UNKNOWN_SSID = "<unknown ssid>" // WifiManager.UNKNOWN_SSID

fun normalizeSsid(raw: String?): String? {
    if (raw == null || raw == UNKNOWN_SSID) return null
    return raw.removeSurrounding("\"").ifEmpty { null }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?`
Expected: `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add android/app/src
git commit -m "Add settings model and home-network gate"
```

---

### Task 6: Sync state store

**Files:**
- Create: `.../sync/SyncState.kt`
- Test: `.../sync/SyncStateTest.kt`

**Interfaces:**
- Produces:
  - `data class SyncSnapshot(val watermark: Long? = null, val lastSuccessAt: Long? = null, val lastWritten: Int = 0, val lastAttemptAt: Long? = null, val lastOutcome: String? = null)`
  - `interface SyncStateStore { suspend fun read(): SyncSnapshot; suspend fun recordSuccess(watermark: Long, at: Long, written: Int); suspend fun recordFailure(at: Long, outcomeKey: String) }`
  - `class DataStoreSyncState(store: DataStore<Preferences>) : SyncStateStore`
  - `class MemorySyncState : SyncStateStore` (test double in `src/test`)

- [ ] **Step 1: Write the failing test**

```kotlin
package io.github.jawello.treadmillsync.sync

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import kotlin.test.Test
import kotlin.test.assertEquals

class SyncStateTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun successAndFailureAreKeptSeparately() = runTest(UnconfinedTestDispatcher()) {
        val file = tmp.root.resolve("s.preferences_pb")
        val state = DataStoreSyncState(PreferenceDataStoreFactory.create(scope = backgroundScope) { file })
        assertEquals(SyncSnapshot(), state.read())
        state.recordSuccess(watermark = 5000, at = 5060, written = 12)
        state.recordFailure(at = 6000, outcomeKey = "BridgeUnreachable")
        assertEquals(SyncSnapshot(5000, 5060, 12, 6000, "BridgeUnreachable"), state.read())
        state.recordSuccess(watermark = 7000, at = 7060, written = 0)
        assertEquals(SyncSnapshot(7000, 7060, 0, 7060, "Success"), state.read())
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests '*SyncStateTest' > $SP/t.log 2>&1; echo exit=$?`
Expected: `exit=1`, unresolved `DataStoreSyncState`.

- [ ] **Step 3: Implement**

`SyncState.kt`:

```kotlin
package io.github.jawello.treadmillsync.sync

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.first

data class SyncSnapshot(
    val watermark: Long? = null,
    val lastSuccessAt: Long? = null,
    val lastWritten: Int = 0,
    val lastAttemptAt: Long? = null,
    val lastOutcome: String? = null,
)

interface SyncStateStore {
    suspend fun read(): SyncSnapshot
    suspend fun recordSuccess(watermark: Long, at: Long, written: Int)
    suspend fun recordFailure(at: Long, outcomeKey: String)
}

class DataStoreSyncState(private val store: DataStore<Preferences>) : SyncStateStore {
    private val watermark = longPreferencesKey("watermark")
    private val lastSuccessAt = longPreferencesKey("last_success_at")
    private val lastWritten = intPreferencesKey("last_written")
    private val lastAttemptAt = longPreferencesKey("last_attempt_at")
    private val lastOutcome = stringPreferencesKey("last_outcome")

    override suspend fun read(): SyncSnapshot {
        val p = store.data.first()
        return SyncSnapshot(p[watermark], p[lastSuccessAt], p[lastWritten] ?: 0, p[lastAttemptAt], p[lastOutcome])
    }

    override suspend fun recordSuccess(watermark: Long, at: Long, written: Int) {
        store.edit {
            it[this.watermark] = watermark
            it[lastSuccessAt] = at
            it[lastWritten] = written
            it[lastAttemptAt] = at
            it[lastOutcome] = "Success"
        }
    }

    override suspend fun recordFailure(at: Long, outcomeKey: String) {
        store.edit {
            it[lastAttemptAt] = at
            it[lastOutcome] = outcomeKey
        }
    }
}
```

Test double `android/app/src/test/java/io/github/jawello/treadmillsync/sync/MemorySyncState.kt`:

```kotlin
package io.github.jawello.treadmillsync.sync

class MemorySyncState(var snapshot: SyncSnapshot = SyncSnapshot()) : SyncStateStore {
    override suspend fun read() = snapshot
    override suspend fun recordSuccess(watermark: Long, at: Long, written: Int) {
        snapshot = SyncSnapshot(watermark, at, written, at, "Success")
    }
    override suspend fun recordFailure(at: Long, outcomeKey: String) {
        snapshot = snapshot.copy(lastAttemptAt = at, lastOutcome = outcomeKey)
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?`
Expected: `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add android/app/src
git commit -m "Persist sync watermark and last result in DataStore"
```

---

### Task 7: HealthStore, outcomes and SyncEngine

**Files:**
- Create: `.../health/HealthStore.kt`, `.../sync/SyncOutcome.kt`, `.../sync/SyncEngine.kt`
- Test: `.../sync/SyncEngineTest.kt`

**Interfaces:**
- Consumes: `Bucket`, `BridgeApi`, `BridgeException` (Task 3); `RecordMapper` (Task 4); `Settings`, `NetworkGate`, `GateResult` (Task 5); `SyncStateStore`, `MemorySyncState` (Task 6).
- Produces:
  - `interface HealthStore { suspend fun hasWritePermissions(): Boolean; suspend fun insert(records: List<Record>) }`
  - `class HealthConnectStore(client: HealthConnectClient) : HealthStore` with `companion object { val PERMISSIONS: Set<String> }`
  - `class UnavailableHealthStore : HealthStore` (always throws `IllegalStateException`)
  - `sealed interface SyncOutcome { val key: String; val retry: Boolean }` with `Success(written: Int)`, `NotConfigured`, `NotHome`, `NetworkUnknown`, `BridgeUnreachable`, `CleartextBlocked`, `WrongToken`, `BridgeError(code: Int?)`, `PermissionsMissing`, `HealthConnectUnavailable`, `RateLimited`
  - `class SyncEngine(settings: suspend () -> Settings, gate: NetworkGate, bridge: (Settings) -> BridgeApi, health: HealthStore, state: SyncStateStore, clock: () -> Instant = Instant::now, zone: () -> ZoneId = ZoneId::systemDefault) { suspend fun sync(): SyncOutcome; companion object { fun window(now: Long, watermark: Long?): LongRange; const val BATCH = 1000 } }` (`window` returns `since..until`)

Ruling carried from the plan: `CleartextBlocked` is an extra outcome beyond the spec's error table (no retry); it surfaces a bridge URL whose host is outside the cleartext allow-list instead of a misleading "unreachable".

- [ ] **Step 1: Write the failing tests**

```kotlin
package io.github.jawello.treadmillsync.sync

import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.testing.FakeHealthConnectClient
import androidx.health.connect.client.testing.FakePermissionController
import androidx.health.connect.client.time.TimeRangeFilter
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeException
import io.github.jawello.treadmillsync.bridge.Bucket
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import java.io.IOException
import java.time.Instant
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

private const val NOW = 1_759_500_000L
private const val DAY = 86_400L

class FakeBridge(var buckets: List<Bucket> = emptyList(), var error: BridgeException? = null) : BridgeApi {
    val calls = mutableListOf<LongRange>()
    override suspend fun steps(since: Long, until: Long): List<Bucket> {
        calls += since..until
        error?.let { throw it }
        return buckets.filter { it.start >= since && it.end <= until }
    }
    override suspend fun ping() {}
}

/** Wraps a real store and fails the n-th insert (1-based). */
class FlakyHealth(private val inner: HealthStore, private val failOn: Int, private val error: Exception) : HealthStore {
    var inserts = 0
    override suspend fun hasWritePermissions() = inner.hasWritePermissions()
    override suspend fun insert(records: List<Record>) {
        inserts++
        if (inserts == failOn) throw error
        inner.insert(records)
    }
}

class SyncEngineTest {
    private val fakeClient = FakeHealthConnectClient()
    private val health = HealthConnectStore(fakeClient)
    private val state = MemorySyncState()
    private val bridge = FakeBridge()
    private var settings = Settings(token = "t")
    private var ssid: String? = "home"

    private fun engine(store: HealthStore = health, now: Long = NOW) = SyncEngine(
        settings = { settings }, gate = NetworkGate { ssid }, bridge = { bridge }, health = store, state = state,
        clock = { Instant.ofEpochSecond(now) }, zone = { ZoneId.of("Europe/Riga") },
    )

    private fun minutes(count: Int, from: Long = NOW - 3_600) =
        (0 until count).map { Bucket(from + it * 60L, from + it * 60L + 60, 100, 70.0, (from + it * 60L + 70) * 1000) }

    private suspend fun stepRecords() = fakeClient.readRecords(
        ReadRecordsRequest(StepsRecord::class, TimeRangeFilter.after(Instant.EPOCH), pageSize = 5000)).records
    private suspend fun distanceRecords() = fakeClient.readRecords(
        ReadRecordsRequest(DistanceRecord::class, TimeRangeFilter.after(Instant.EPOCH), pageSize = 5000)).records

    @Test fun windowRules() {
        assertEquals((NOW - 30 * DAY)..(NOW - 60), SyncEngine.window(NOW, null))
        assertEquals((NOW - 7_200 - 3_600)..(NOW - 60), SyncEngine.window(NOW, NOW - 7_200))
        assertEquals((NOW - 30 * DAY)..(NOW - 60), SyncEngine.window(NOW, NOW - 40 * DAY))
    }

    @Test fun watermarkInFutureIsClamped() {
        val w = SyncEngine.window(NOW, NOW + 10 * DAY)
        assertEquals((NOW - 60 - 3_600)..(NOW - 60), w)
    }

    @Test fun firstRunBackfillsAndWritesStepsAndDistance() = runTest {
        bridge.buckets = minutes(3)
        val outcome = engine().sync()
        assertEquals(SyncOutcome.Success(6), outcome)
        assertEquals(listOf((NOW - 30 * DAY)..(NOW - 60)), bridge.calls)
        assertEquals(3, stepRecords().size)
        assertEquals(3, distanceRecords().size)
        assertEquals(NOW - 60, state.snapshot.watermark)
    }

    @Test fun resyncWritesNoDuplicates() = runTest {
        bridge.buckets = minutes(3)
        engine().sync()
        engine(now = NOW + 600).sync()
        assertEquals(300L, stepRecords().sumOf { (it as StepsRecord).count })
        assertEquals(3, stepRecords().size)
        assertEquals((NOW - 60 - 3_600)..(NOW + 540), bridge.calls[1])
    }

    @Test fun batchesOfAtMostOneThousand() = runTest {
        bridge.buckets = minutes(600, from = NOW - 2 * DAY) // 1200 records
        val counting = FlakyHealth(health, failOn = -1, error = IOException())
        assertEquals(SyncOutcome.Success(1200), engine(counting).sync())
        assertEquals(2, counting.inserts)
    }

    @Test fun failureInTheMiddleKeepsWatermarkAndNextPassCompletes() = runTest {
        bridge.buckets = minutes(600, from = NOW - 2 * DAY)
        val flaky = FlakyHealth(health, failOn = 2, error = IOException("binder died"))
        assertEquals(SyncOutcome.HealthConnectUnavailable, engine(flaky).sync())
        assertEquals(null, state.snapshot.watermark)
        assertEquals("HealthConnectUnavailable", state.snapshot.lastOutcome)
        assertEquals(SyncOutcome.Success(1200), engine().sync())
        assertEquals(600, stepRecords().size)
    }

    @Test fun rateLimitIsRetried() = runTest {
        bridge.buckets = minutes(1)
        val limited = FlakyHealth(health, failOn = 1, error = IOException("Rate limit exceeded"))
        val outcome = engine(limited).sync()
        assertEquals(SyncOutcome.RateLimited, outcome)
        assertTrue(outcome.retry)
    }

    @Test fun securityExceptionMeansPermissions() = runTest {
        bridge.buckets = minutes(1)
        val denied = FlakyHealth(health, failOn = 1, error = SecurityException())
        assertEquals(SyncOutcome.PermissionsMissing, engine(denied).sync())
    }

    @Test fun missingPermissionsStopBeforeTheBridge() = runTest {
        val noPerms = FakeHealthConnectClient(permissionController = FakePermissionController(grantAll = false))
        assertEquals(SyncOutcome.PermissionsMissing, engine(HealthConnectStore(noPerms)).sync())
        assertTrue(bridge.calls.isEmpty())
    }

    @Test fun notConfiguredWhenTokenBlank() = runTest {
        settings = Settings(token = "  ")
        assertEquals(SyncOutcome.NotConfigured, engine().sync())
        assertTrue(bridge.calls.isEmpty())
    }

    @Test fun gateOutcomes() = runTest {
        settings = Settings(token = "t", homeSsid = "home")
        ssid = "cafe"
        assertEquals(SyncOutcome.NotHome, engine().sync())
        ssid = null
        assertEquals(SyncOutcome.NetworkUnknown, engine().sync())
        assertTrue(bridge.calls.isEmpty())
        ssid = "home"
        assertEquals(SyncOutcome.Success(0), engine().sync())
        settings = Settings(token = "t", homeSsid = "")
        ssid = null
        assertEquals(SyncOutcome.Success(0), engine().sync())
    }

    @Test fun bridgeErrorsMapToOutcomes() = runTest {
        val cases = mapOf(
            BridgeException.Unreachable(IOException()) to SyncOutcome.BridgeUnreachable,
            BridgeException.Unauthorized() to SyncOutcome.WrongToken,
            BridgeException.BadToken() to SyncOutcome.WrongToken,
            BridgeException.BadResponse(400) to SyncOutcome.BridgeError(400),
            BridgeException.BadUrl() to SyncOutcome.BridgeError(null),
            BridgeException.CleartextBlocked() to SyncOutcome.CleartextBlocked,
        )
        for ((error, expected) in cases) {
            bridge.error = error
            assertEquals(expected, engine().sync(), error::class.simpleName)
        }
        assertEquals(null, state.snapshot.watermark)
    }

    @Test fun retryOnlyForTransientOutcomes() {
        val retried = listOf(SyncOutcome.BridgeUnreachable, SyncOutcome.HealthConnectUnavailable, SyncOutcome.RateLimited)
        val all = retried + listOf(SyncOutcome.Success(1), SyncOutcome.NotConfigured, SyncOutcome.NotHome,
            SyncOutcome.NetworkUnknown, SyncOutcome.CleartextBlocked, SyncOutcome.WrongToken, SyncOutcome.BridgeError(400),
            SyncOutcome.PermissionsMissing)
        assertEquals(retried, all.filter { it.retry })
    }

    @Test fun concurrentPassesDoNotOverlap() = runTest {
        bridge.buckets = minutes(3)
        val a = async { engine().sync() }
        val b = async { engine().sync() }
        assertEquals(SyncOutcome.Success(6), a.await())
        assertEquals(SyncOutcome.Success(6), b.await())
        assertEquals(3, stepRecords().size)
    }
}
```

Note for `resyncWritesNoDuplicates`: if `FakeHealthConnectClient` does not upsert by `clientRecordId` (it shows 6 records), Health Connect's real behaviour is the documented upsert. In that case replace the duplicate assertion with an assertion that both passes produced identical `clientRecordId`/`clientRecordVersion` sets, and record a Ruling. Do not change production code to compensate.

- [ ] **Step 2: Run to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests '*SyncEngineTest' > $SP/t.log 2>&1; echo exit=$?; grep -E "Unresolved" $SP/t.log | head -3`
Expected: `exit=1`, unresolved `SyncEngine` / `HealthConnectStore`.

- [ ] **Step 3: Implement**

`HealthStore.kt`:

```kotlin
package io.github.jawello.treadmillsync.health

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord

interface HealthStore {
    suspend fun hasWritePermissions(): Boolean
    suspend fun insert(records: List<Record>)
}

class HealthConnectStore(private val client: HealthConnectClient) : HealthStore {
    override suspend fun hasWritePermissions() =
        client.permissionController.getGrantedPermissions().containsAll(PERMISSIONS)

    override suspend fun insert(records: List<Record>) {
        client.insertRecords(records)
    }

    companion object {
        val PERMISSIONS = setOf(
            HealthPermission.getWritePermission(StepsRecord::class),
            HealthPermission.getWritePermission(DistanceRecord::class),
        )
    }
}

/** Stands in when Health Connect is missing or needs an update on this phone. */
class UnavailableHealthStore : HealthStore {
    override suspend fun hasWritePermissions(): Boolean = throw IllegalStateException("Health Connect unavailable")
    override suspend fun insert(records: List<Record>) = throw IllegalStateException("Health Connect unavailable")
}
```

`SyncOutcome.kt`:

```kotlin
package io.github.jawello.treadmillsync.sync

sealed interface SyncOutcome {
    val key: String get() = this::class.simpleName!!
    val retry: Boolean get() = false

    data class Success(val written: Int) : SyncOutcome
    data object NotConfigured : SyncOutcome
    data object NotHome : SyncOutcome
    data object NetworkUnknown : SyncOutcome
    data object BridgeUnreachable : SyncOutcome { override val retry = true }
    data object CleartextBlocked : SyncOutcome
    data object WrongToken : SyncOutcome
    data class BridgeError(val code: Int?) : SyncOutcome { override val key = "BridgeError:${code ?: "url"}" }
    data object PermissionsMissing : SyncOutcome
    data object HealthConnectUnavailable : SyncOutcome { override val retry = true }
    data object RateLimited : SyncOutcome { override val retry = true }
}
```

`SyncEngine.kt`:

```kotlin
package io.github.jawello.treadmillsync.sync

import android.os.RemoteException
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeException
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.health.RecordMapper
import io.github.jawello.treadmillsync.net.GateResult
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.IOException
import java.time.Instant
import java.time.ZoneId

/** One sync pass: bridge minute buckets → Health Connect, idempotent and resumable. */
class SyncEngine(
    private val settings: suspend () -> Settings,
    private val gate: NetworkGate,
    private val bridge: (Settings) -> BridgeApi,
    private val health: HealthStore,
    private val state: SyncStateStore,
    private val clock: () -> Instant = Instant::now,
    private val zone: () -> ZoneId = ZoneId::systemDefault,
) {
    suspend fun sync(): SyncOutcome = LOCK.withLock {
        val now = clock().epochSecond
        val outcome = pass(now)
        if (outcome !is SyncOutcome.Success) state.recordFailure(now, outcome.key)
        outcome
    }

    private suspend fun pass(now: Long): SyncOutcome {
        val s = settings().normalized()
        if (!s.configured) return SyncOutcome.NotConfigured
        when (gate.check(s.homeSsid)) {
            GateResult.NOT_HOME -> return SyncOutcome.NotHome
            GateResult.UNKNOWN -> return SyncOutcome.NetworkUnknown
            GateResult.OPEN -> Unit
        }
        healthCall { if (!health.hasWritePermissions()) return SyncOutcome.PermissionsMissing }?.let { return it }

        val window = window(now, state.read().watermark)
        val buckets = try {
            bridge(s).steps(window.first, window.last)
        } catch (e: BridgeException) {
            return e.toOutcome()
        }
        val zoneId = zone()
        val records = buckets.flatMap { RecordMapper.toRecords(it, zoneId) }
        healthCall { records.chunked(BATCH).forEach { health.insert(it) } }?.let { return it }

        state.recordSuccess(watermark = window.last, at = now, written = records.size)
        return SyncOutcome.Success(records.size)
    }

    /** Runs a Health Connect call; returns the failure outcome, or null when it succeeded. */
    private inline fun healthCall(block: () -> Unit): SyncOutcome? = try {
        block()
        null
    } catch (e: CancellationException) {
        throw e // a CancellationException is an IllegalStateException: never map it to an outcome
    } catch (e: SecurityException) {
        SyncOutcome.PermissionsMissing
    } catch (e: Exception) {
        if (e !is IOException && e !is RemoteException && e !is IllegalStateException) throw e
        val message = e.message.orEmpty().lowercase()
        if ("rate limit" in message || "quota" in message) SyncOutcome.RateLimited else SyncOutcome.HealthConnectUnavailable
    }

    private fun BridgeException.toOutcome(): SyncOutcome = when (this) {
        is BridgeException.Unreachable -> SyncOutcome.BridgeUnreachable
        is BridgeException.CleartextBlocked -> SyncOutcome.CleartextBlocked
        is BridgeException.Unauthorized, is BridgeException.BadToken -> SyncOutcome.WrongToken
        is BridgeException.BadResponse -> SyncOutcome.BridgeError(code)
        is BridgeException.BadUrl -> SyncOutcome.BridgeError(null)
    }

    companion object {
        const val BATCH = 1000
        private const val OVERLAP_S = 3_600L
        private const val SETTLE_S = 60L
        private const val HISTORY_S = 30 * 86_400L
        private val LOCK = Mutex() // the worker and "Sync now" never run a pass at the same time

        fun window(now: Long, watermark: Long?): LongRange {
            val until = now - SETTLE_S
            val floor = now - HISTORY_S
            val since = if (watermark == null) floor else maxOf(minOf(watermark, until) - OVERLAP_S, floor)
            return since..until
        }
    }
}
```

`healthCall`'s early `return` inside the lambda returns from `pass` (the function is `inline`). This is intended: the permission check exits `pass` with `PermissionsMissing`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?; tail -5 $SP/t.log`
Expected: `exit=0`. If `FakePermissionController(grantAll = false)` has a different constructor in the resolved `connect-testing`, use its equivalent (e.g. `revokeAllPermissions()`) and record a Ruling.

- [ ] **Step 5: Commit**

```bash
git add android/app/src
git commit -m "Add sync engine writing bridge buckets to Health Connect"
```

---

### Task 8: Worker, scheduling and Android adapters

**Files:**
- Create: `.../sync/SyncWorker.kt`, `.../net/AndroidSsidSource.kt`, `.../settings/SettingsStore.kt`, `.../Graph.kt`, `.../TreadmillSyncApp.kt`
- Modify: `android/app/src/main/AndroidManifest.xml`
- Test: `.../sync/SyncWorkerTest.kt`

**Interfaces:**
- Consumes: everything from Tasks 3–7.
- Produces:
  - `fun workResult(outcome: SyncOutcome): ListenableWorker.Result`
  - `object SyncScheduler { fun schedule(context: Context) }` (unique periodic work `"bridge-sync"`)
  - `class SyncWorker(context, params) : CoroutineWorker`
  - `class AndroidSsidSource(context: Context) : SsidSource`
  - `class SettingsStore(context: Context) { fun load(): Settings; fun save(settings: Settings) }`
  - `object Graph { fun engine(context: Context): SyncEngine; fun settings(context: Context): SettingsStore; fun state(context: Context): SyncStateStore; fun bridge(settings: Settings): BridgeApi }`

- [ ] **Step 1: Write the failing test**

```kotlin
package io.github.jawello.treadmillsync.sync

import androidx.work.ListenableWorker.Result
import kotlin.test.Test
import kotlin.test.assertEquals

class SyncWorkerTest {
    @Test fun outcomesMapToWorkResults() {
        assertEquals(Result.success(), workResult(SyncOutcome.Success(3)))
        assertEquals(Result.retry(), workResult(SyncOutcome.BridgeUnreachable))
        assertEquals(Result.retry(), workResult(SyncOutcome.RateLimited))
        assertEquals(Result.failure(), workResult(SyncOutcome.WrongToken))
        assertEquals(Result.failure(), workResult(SyncOutcome.NotHome))
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests '*SyncWorkerTest' > $SP/t.log 2>&1; echo exit=$?`
Expected: `exit=1`, unresolved `workResult`.

- [ ] **Step 3: Implement**

`SyncWorker.kt`:

```kotlin
package io.github.jawello.treadmillsync.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ListenableWorker
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.jawello.treadmillsync.Graph
import java.util.concurrent.TimeUnit

fun workResult(outcome: SyncOutcome): ListenableWorker.Result = when {
    outcome is SyncOutcome.Success -> ListenableWorker.Result.success()
    outcome.retry -> ListenableWorker.Result.retry()
    else -> ListenableWorker.Result.failure() // the next period runs anyway
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = workResult(Graph.engine(applicationContext).sync())
}

object SyncScheduler {
    private const val NAME = "bridge-sync"

    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, request)
    }
}
```

`AndroidSsidSource.kt`:

```kotlin
package io.github.jawello.treadmillsync.net

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull

/** Reads the current Wi-Fi SSID; needs fine (and, in background, background) location. */
class AndroidSsidSource(private val context: Context) : SsidSource {
    override suspend fun currentSsid(): String? {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
        val result = CompletableDeferred<String?>()
        val callback = object : ConnectivityManager.NetworkCallback(FLAG_INCLUDE_LOCATION_INFO) {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                result.complete(normalizeSsid((caps.transportInfo as? WifiInfo)?.ssid))
            }
        }
        val request = NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build()
        cm.registerNetworkCallback(request, callback)
        return try {
            withTimeoutOrNull(2_000) { result.await() }
        } finally {
            cm.unregisterNetworkCallback(callback)
        }
    }
}
```

`SettingsStore.kt`:

```kotlin
package io.github.jawello.treadmillsync.settings

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Bridge URL, token and home SSID, encrypted at rest. */
class SettingsStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "settings",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun load() = Settings(
        bridgeUrl = prefs.getString(URL, null) ?: DEFAULT_BRIDGE_URL,
        token = prefs.getString(TOKEN, null).orEmpty(),
        homeSsid = prefs.getString(SSID, null).orEmpty(),
    )

    fun save(settings: Settings) {
        val s = settings.normalized()
        prefs.edit().putString(URL, s.bridgeUrl).putString(TOKEN, s.token).putString(SSID, s.homeSsid).apply()
    }

    private companion object {
        const val URL = "bridge_url"
        const val TOKEN = "token"
        const val SSID = "home_ssid"
    }
}
```

`Graph.kt`:

```kotlin
package io.github.jawello.treadmillsync

import android.content.Context
import androidx.datastore.preferences.preferencesDataStore
import androidx.health.connect.client.HealthConnectClient
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeClient
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.health.UnavailableHealthStore
import io.github.jawello.treadmillsync.net.AndroidSsidSource
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import io.github.jawello.treadmillsync.settings.SettingsStore
import io.github.jawello.treadmillsync.sync.DataStoreSyncState
import io.github.jawello.treadmillsync.sync.SyncEngine
import io.github.jawello.treadmillsync.sync.SyncStateStore

private val Context.syncStateStore by preferencesDataStore("sync_state")

/** Manual wiring of the app's collaborators. */
object Graph {
    fun settings(context: Context) = SettingsStore(context.applicationContext)

    fun state(context: Context): SyncStateStore = DataStoreSyncState(context.applicationContext.syncStateStore)

    fun bridge(settings: Settings): BridgeApi = BridgeClient(settings.bridgeUrl, settings.token)

    fun health(context: Context): HealthStore =
        if (HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectStore(HealthConnectClient.getOrCreate(context.applicationContext))
        } else {
            UnavailableHealthStore()
        }

    fun engine(context: Context): SyncEngine {
        val app = context.applicationContext
        val settings = settings(app)
        return SyncEngine(
            settings = { settings.load() },
            gate = NetworkGate(AndroidSsidSource(app)),
            bridge = ::bridge,
            health = health(app),
            state = state(app),
        )
    }
}
```

`TreadmillSyncApp.kt`:

```kotlin
package io.github.jawello.treadmillsync

import android.app.Application
import io.github.jawello.treadmillsync.sync.SyncScheduler

class TreadmillSyncApp : Application() {
    override fun onCreate() {
        super.onCreate()
        SyncScheduler.schedule(this)
    }
}
```

In `AndroidManifest.xml` add the permissions and the application class:

```xml
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION" />
    <uses-permission android:name="android.permission.health.WRITE_STEPS" />
    <uses-permission android:name="android.permission.health.WRITE_DISTANCE" />
```

and `android:name=".TreadmillSyncApp"` on `<application>`.

- [ ] **Step 4: Run tests, build and lint**

Run: `cd android && ./gradlew test lint assembleDebug > $SP/t.log 2>&1; echo exit=$?; grep -E "Error|error:" $SP/t.log | head -5`
Expected: `exit=0`. Lint errors are fixed in code. A lint warning about the deprecated `security-crypto` API is accepted: it is a warning, not an error. Record a Ruling if lint reports it as an error.

- [ ] **Step 5: Commit**

```bash
git add android/app/src
git commit -m "Schedule periodic sync and wire Android adapters"
```

---

### Task 9: Screen, strings and Health Connect integration

**Files:**
- Create: `.../ui/MainActivity.kt`, `.../ui/OutcomeText.kt`, `.../ui/PermissionsRationaleActivity.kt`
- Modify: `AndroidManifest.xml`, `res/values/strings.xml`, `res/values-ru/strings.xml`
- Test: `.../ui/OutcomeTextTest.kt`

**Interfaces:**
- Consumes: `Graph`, `SyncOutcome.key`, `SyncSnapshot`, `Settings`, `SettingsStore`, `HealthConnectStore.PERMISSIONS`, `AndroidSsidSource`, `BridgeException`.
- Produces: `fun outcomeTextRes(key: String?): Int` (string resource id; `0` for null).

- [ ] **Step 1: Write the failing test**

```kotlin
package io.github.jawello.treadmillsync.ui

import io.github.jawello.treadmillsync.R
import io.github.jawello.treadmillsync.sync.SyncOutcome
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class OutcomeTextTest {
    @Test fun everyOutcomeHasText() {
        val outcomes = listOf(SyncOutcome.Success(1), SyncOutcome.NotConfigured, SyncOutcome.NotHome, SyncOutcome.NetworkUnknown,
            SyncOutcome.BridgeUnreachable, SyncOutcome.CleartextBlocked, SyncOutcome.WrongToken, SyncOutcome.BridgeError(400),
            SyncOutcome.BridgeError(null), SyncOutcome.PermissionsMissing, SyncOutcome.HealthConnectUnavailable, SyncOutcome.RateLimited)
        for (o in outcomes) assertNotEquals(R.string.outcome_unknown, outcomeTextRes(o.key), o.key)
        assertEquals(R.string.outcome_bridge_error, outcomeTextRes("BridgeError:400"))
        assertEquals(0, outcomeTextRes(null))
        assertEquals(R.string.outcome_unknown, outcomeTextRes("Something"))
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests '*OutcomeTextTest' > $SP/t.log 2>&1; echo exit=$?`
Expected: `exit=1`, unresolved `outcomeTextRes`.

- [ ] **Step 3: Strings**

`res/values/strings.xml`:

```xml
<resources>
    <string name="app_name">Treadmill Sync</string>
    <string name="status_title">Status</string>
    <string name="status_never">Not synced yet</string>
    <string name="status_last_success">Last sync: %1$s, records written: %2$d</string>
    <string name="status_last_problem">Last attempt %1$s: %2$s</string>
    <string name="sync_now">Sync now</string>
    <string name="bridge_url">Bridge address</string>
    <string name="token">Token</string>
    <string name="save">Save</string>
    <string name="test_connection">Test connection</string>
    <string name="connection_ok">Bridge is reachable</string>
    <string name="home_ssid">Home network (SSID), optional</string>
    <string name="use_current_network">Use current network</string>
    <string name="home_ssid_hint">When set, the app talks to the bridge only on this network. Needs location access set to “Allow all the time”.</string>
    <string name="hc_permissions">Health Connect permissions</string>
    <string name="hc_priority_hint">In Health Connect → App permissions → data priority for Activity, move Treadmill Sync above Garmin Connect so treadmill minutes are not counted twice.</string>
    <string name="open_hc_settings">Open Health Connect settings</string>
    <string name="rationale">Treadmill Sync writes the steps and distance your Kingsmith treadmill recorded on the home bridge. It never reads your health data.</string>
    <string name="outcome_success">Synced</string>
    <string name="outcome_not_configured">Enter the bridge address and token</string>
    <string name="outcome_not_home">Not home network</string>
    <string name="outcome_network_unknown">Can\'t identify network: enable location / allow all the time</string>
    <string name="outcome_bridge_unreachable">Bridge unreachable</string>
    <string name="outcome_cleartext_blocked">Plain HTTP is not allowed for this address</string>
    <string name="outcome_wrong_token">Wrong token</string>
    <string name="outcome_bridge_error">Bridge response error</string>
    <string name="outcome_permissions">Health Connect permissions needed</string>
    <string name="outcome_hc_unavailable">Health Connect unavailable</string>
    <string name="outcome_rate_limited">Health Connect limit, retrying later</string>
    <string name="outcome_unknown">Unknown error</string>
</resources>
```

`res/values-ru/strings.xml`:

```xml
<resources>
    <string name="app_name">Treadmill Sync</string>
    <string name="status_title">Статус</string>
    <string name="status_never">Ещё не синхронизировалось</string>
    <string name="status_last_success">Последняя синхронизация: %1$s, записей: %2$d</string>
    <string name="status_last_problem">Последняя попытка %1$s: %2$s</string>
    <string name="sync_now">Синхронизировать сейчас</string>
    <string name="bridge_url">Адрес моста</string>
    <string name="token">Токен</string>
    <string name="save">Сохранить</string>
    <string name="test_connection">Проверить связь</string>
    <string name="connection_ok">Мост на связи</string>
    <string name="home_ssid">Домашняя сеть (SSID), необязательно</string>
    <string name="use_current_network">Подставить текущую сеть</string>
    <string name="home_ssid_hint">Если задано, приложение обращается к мосту только в этой сети. Нужен доступ к геолокации «Разрешить всегда».</string>
    <string name="hc_permissions">Разрешения Health Connect</string>
    <string name="hc_priority_hint">В Health Connect → Разрешения приложений → приоритет данных для «Активности» поставьте Treadmill Sync выше Garmin Connect, чтобы минуты на дорожке не считались дважды.</string>
    <string name="open_hc_settings">Открыть настройки Health Connect</string>
    <string name="rationale">Treadmill Sync записывает шаги и расстояние, которые дорожка Kingsmith передала домашнему мосту. Приложение не читает ваши данные о здоровье.</string>
    <string name="outcome_success">Синхронизировано</string>
    <string name="outcome_not_configured">Укажите адрес моста и токен</string>
    <string name="outcome_not_home">Не домашняя сеть</string>
    <string name="outcome_network_unknown">Не удалось определить сеть: включите геолокацию / разрешите доступ всегда</string>
    <string name="outcome_bridge_unreachable">Мост недоступен</string>
    <string name="outcome_cleartext_blocked">Для этого адреса HTTP без шифрования запрещён</string>
    <string name="outcome_wrong_token">Неверный токен</string>
    <string name="outcome_bridge_error">Ошибка ответа моста</string>
    <string name="outcome_permissions">Нужны разрешения Health Connect</string>
    <string name="outcome_hc_unavailable">Health Connect недоступен</string>
    <string name="outcome_rate_limited">Лимит Health Connect, повторю позже</string>
    <string name="outcome_unknown">Неизвестная ошибка</string>
</resources>
```

- [ ] **Step 4: `OutcomeText.kt`**

```kotlin
package io.github.jawello.treadmillsync.ui

import io.github.jawello.treadmillsync.R

fun outcomeTextRes(key: String?): Int = when {
    key == null -> 0
    key == "Success" -> R.string.outcome_success
    key == "NotConfigured" -> R.string.outcome_not_configured
    key == "NotHome" -> R.string.outcome_not_home
    key == "NetworkUnknown" -> R.string.outcome_network_unknown
    key == "BridgeUnreachable" -> R.string.outcome_bridge_unreachable
    key == "CleartextBlocked" -> R.string.outcome_cleartext_blocked
    key == "WrongToken" -> R.string.outcome_wrong_token
    key.startsWith("BridgeError") -> R.string.outcome_bridge_error
    key == "PermissionsMissing" -> R.string.outcome_permissions
    key == "HealthConnectUnavailable" -> R.string.outcome_hc_unavailable
    key == "RateLimited" -> R.string.outcome_rate_limited
    else -> R.string.outcome_unknown
}
```

`Success`'s `key` is `"Success"` because `Success` is a data class named `Success`.

- [ ] **Step 5: Run the test**

Run: `cd android && ./gradlew :app:testDebugUnitTest > $SP/t.log 2>&1; echo exit=$?`
Expected: `exit=0`.

- [ ] **Step 6: Screen and rationale activity**

`PermissionsRationaleActivity.kt`:

```kotlin
package io.github.jawello.treadmillsync.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.github.jawello.treadmillsync.R

/** Shown by Health Connect when the user asks why the app wants its permissions. */
class PermissionsRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { Text(stringResource(R.string.rationale), Modifier.padding(24.dp)) } }
    }
}
```

`MainActivity.kt`:

```kotlin
package io.github.jawello.treadmillsync.ui

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.text.format.DateUtils
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import io.github.jawello.treadmillsync.Graph
import io.github.jawello.treadmillsync.R
import io.github.jawello.treadmillsync.bridge.BridgeException
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.net.AndroidSsidSource
import io.github.jawello.treadmillsync.settings.Settings
import io.github.jawello.treadmillsync.sync.SyncScheduler
import io.github.jawello.treadmillsync.sync.SyncSnapshot
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val snapshot = mutableStateOf(SyncSnapshot())
    private val message = mutableStateOf("")

    private val healthPermissions =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { refresh() }
    private val backgroundLocation =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private var onFineLocation: () -> Unit = {}
    private val fineLocation =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) onFineLocation() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SyncScheduler.schedule(this)
        val store = Graph.settings(this)
        setContent { MaterialTheme { Screen(store.load(), store::save) } }
        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        lifecycleScope.launch { snapshot.value = Graph.state(this@MainActivity).read() }
    }

    private fun syncNow() {
        lifecycleScope.launch {
            Graph.engine(this@MainActivity).sync()
            refresh()
        }
    }

    private fun testConnection(settings: Settings) {
        lifecycleScope.launch {
            message.value = try {
                Graph.bridge(settings.normalized()).ping()
                getString(R.string.connection_ok)
            } catch (e: BridgeException) {
                "${getString(R.string.outcome_bridge_error)}: ${e::class.simpleName}"
            }
        }
    }

    private fun withCurrentSsid(use: (String) -> Unit) {
        onFineLocation = {
            lifecycleScope.launch {
                AndroidSsidSource(this@MainActivity).currentSsid()?.let(use)
                backgroundLocation.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            }
        }
        fineLocation.launch(Manifest.permission.ACCESS_FINE_LOCATION)
    }

    private fun time(epochSecond: Long?): String =
        epochSecond?.let { DateUtils.formatDateTime(this, it * 1000, DateUtils.FORMAT_SHOW_TIME or DateUtils.FORMAT_SHOW_DATE) } ?: "—"

    @Composable
    private fun Screen(initial: Settings, save: (Settings) -> Unit) {
        var url by remember { mutableStateOf(initial.bridgeUrl) }
        var token by remember { mutableStateOf(initial.token) }
        var ssid by remember { mutableStateOf(initial.homeSsid) }
        val scope = rememberCoroutineScope()
        val snap by snapshot
        val current = { Settings(url, token, ssid) }

        Column(
            Modifier.padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.status_title), style = MaterialTheme.typography.titleLarge)
            Text(
                if (snap.lastSuccessAt == null) stringResource(R.string.status_never)
                else stringResource(R.string.status_last_success, time(snap.lastSuccessAt), snap.lastWritten)
            )
            if (snap.lastOutcome != null && snap.lastOutcome != "Success") {
                Text(stringResource(R.string.status_last_problem, time(snap.lastAttemptAt), stringResource(outcomeTextRes(snap.lastOutcome))))
            }
            Button(onClick = { save(current()); syncNow() }, Modifier.fillMaxWidth()) { Text(stringResource(R.string.sync_now)) }

            OutlinedTextField(url, { url = it }, label = { Text(stringResource(R.string.bridge_url)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(token, { token = it }, label = { Text(stringResource(R.string.token)) }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(ssid, { ssid = it }, label = { Text(stringResource(R.string.home_ssid)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Text(stringResource(R.string.home_ssid_hint), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { withCurrentSsid { ssid = it } }) { Text(stringResource(R.string.use_current_network)) }
            Button(onClick = {
                save(current())
                if (current().normalized().homeSsid.isNotEmpty()) withCurrentSsid { }
            }) { Text(stringResource(R.string.save)) }
            OutlinedButton(onClick = { scope.launch { testConnection(current()) } }) { Text(stringResource(R.string.test_connection)) }
            if (message.value.isNotEmpty()) Text(message.value)

            Button(onClick = { healthPermissions.launch(HealthConnectStore.PERMISSIONS) }) { Text(stringResource(R.string.hc_permissions)) }
            Text(stringResource(R.string.hc_priority_hint), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { startActivity(Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)) }) {
                Text(stringResource(R.string.open_hc_settings))
            }
        }
    }
}
```

Manifest `<application>` children:

```xml
        <activity android:name=".ui.MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <activity android:name=".ui.PermissionsRationaleActivity" android:exported="true">
            <intent-filter>
                <action android:name="androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE" />
            </intent-filter>
        </activity>

        <activity-alias
            android:name="ViewPermissionUsageActivity"
            android:exported="true"
            android:targetActivity=".ui.PermissionsRationaleActivity"
            android:permission="android.permission.START_VIEW_PERMISSION_USAGE">
            <intent-filter>
                <action android:name="android.intent.action.VIEW_PERMISSION_USAGE" />
                <category android:name="android.intent.category.HEALTH_PERMISSIONS" />
            </intent-filter>
        </activity-alias>
```

and, as a direct child of `<manifest>`:

```xml
    <queries>
        <package android:name="com.google.android.apps.healthdata" />
    </queries>
```

Without the `VIEW_PERMISSION_USAGE` alias, Android 14+ silently refuses the Health Connect permission request. It must stay.

`lifecycle-runtime-ktx` comes transitively with `activity-compose`. If `lifecycleScope` is unresolved, add `androidx.lifecycle:lifecycle-runtime-ktx` to the catalog and record a Ruling.

- [ ] **Step 7: Full build**

Run: `cd android && ./gradlew test lint assembleDebug > $SP/t.log 2>&1; echo exit=$?; grep -E "error:|Error" $SP/t.log | head -5`
Expected: `exit=0`.

- [ ] **Step 8: Commit and push, check CI**

```bash
git add android/app/src
git commit -m "Add settings screen and Health Connect permission flow"
git push origin HEAD:main
gh run watch "$(gh run list --workflow android.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
```
Expected: CI green.

---

### Task 10: Signing, release workflow and docs

**Files:**
- Modify: `android/app/build.gradle.kts`, `README.md`, `.github/workflows/android.yml`
- Create: `.github/workflows/android-release.yml`, `android/README.md`

**Interfaces:**
- Consumes: the built app.
- Produces: GitHub secrets `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`; release `android-v0.1.0` with `treadmill-sync-0.1.0.apk`.

- [ ] **Step 1: Signing config read from the environment**

In `android/app/build.gradle.kts`, inside `android { … }` before `buildTypes`:

```kotlin
    val storeFilePath = System.getenv("SIGNING_STORE_FILE")
    signingConfigs {
        if (storeFilePath != null) {
            create("release") {
                storeFile = file(storeFilePath)
                storePassword = System.getenv("SIGNING_STORE_PASSWORD")
                keyAlias = System.getenv("SIGNING_KEY_ALIAS")
                keyPassword = System.getenv("SIGNING_KEY_PASSWORD")
            }
        }
    }
```

and in `buildTypes.release`:

```kotlin
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
```

The release build without secrets (local, PRs) gets the debug signature, so the CI artifact is installable for testing. The tagged release always uses the real key (Step 4 fails without it).

- [ ] **Step 2: Create the key and the secrets without printing them**

```bash
umask 077; mkdir -p ~/.config/treadmill-sync && cd ~/.config/treadmill-sync
[ -e release.jks ] && { echo "release.jks exists, not overwriting"; exit 1; }
PASS=$(openssl rand -base64 24 | tr -d '/+=')
printf 'SIGNING_STORE_PASSWORD=%s\nSIGNING_KEY_PASSWORD=%s\nSIGNING_KEY_ALIAS=treadmill-sync\n' "$PASS" "$PASS" > signing.env
keytool -genkeypair -keystore release.jks -alias treadmill-sync -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass "$PASS" -keypass "$PASS" -dname "CN=Treadmill Sync" >/dev/null 2>&1 && echo created
cd /home/akhadiev/Documents/personal/garmin-treadmill-field
base64 -w0 ~/.config/treadmill-sync/release.jks | gh secret set ANDROID_KEYSTORE_BASE64
printf '%s' "$PASS" | gh secret set ANDROID_KEYSTORE_PASSWORD
printf '%s' "$PASS" | gh secret set ANDROID_KEY_PASSWORD
printf '%s' treadmill-sync | gh secret set ANDROID_KEY_ALIAS
gh secret list | grep ANDROID_
```
Expected: `created`, then four `ANDROID_*` names (no values). Tell the user where the key lives (`~/.config/treadmill-sync/`). If the key is lost, future updates need an uninstall first.

- [ ] **Step 3: Release workflow**

`.github/workflows/android-release.yml`:

```yaml
name: android-release
on:
  push:
    tags: ["android-v*"]
permissions:
  contents: write
jobs:
  release:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: android
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "21"
      - uses: android-actions/setup-android@v3
      - uses: gradle/actions/setup-gradle@v4
      - name: Decode keystore
        env:
          KEYSTORE_B64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
        run: |
          test -n "$KEYSTORE_B64" || { echo "signing secrets missing"; exit 1; }
          echo "$KEYSTORE_B64" | base64 -d > "$RUNNER_TEMP/release.jks"
          echo "SIGNING_STORE_FILE=$RUNNER_TEMP/release.jks" >> "$GITHUB_ENV"
      - run: ./gradlew test lint assembleRelease
        env:
          SIGNING_STORE_PASSWORD: ${{ secrets.ANDROID_KEYSTORE_PASSWORD }}
          SIGNING_KEY_ALIAS: ${{ secrets.ANDROID_KEY_ALIAS }}
          SIGNING_KEY_PASSWORD: ${{ secrets.ANDROID_KEY_PASSWORD }}
      - name: Publish release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          VERSION="${GITHUB_REF_NAME#android-v}"
          cp app/build/outputs/apk/release/app-release.apk "treadmill-sync-$VERSION.apk"
          gh release create "$GITHUB_REF_NAME" "treadmill-sync-$VERSION.apk" --title "Treadmill Sync $VERSION" --notes "Android companion: bridge steps → Health Connect."
```

Add `.github/workflows/android-release.yml` to the `paths` of `android.yml`, so the workflow file is linted by a run.

- [ ] **Step 4: Setup guide**

`android/README.md`:

```markdown
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
```

In the root `README.md`, change the `android/` row to `| [`android/`](android/README.md) | Treadmill Sync: copies bridge step buckets into Health Connect |`. Change the status line to say the Android companion is implemented.

- [ ] **Step 5: Build locally with signing to prove the config works**

```bash
cd android && set -a && . ~/.config/treadmill-sync/signing.env && set +a && SIGNING_STORE_FILE=~/.config/treadmill-sync/release.jks ./gradlew assembleRelease > $SP/r.log 2>&1; echo exit=$?
$ANDROID_HOME/build-tools/*/apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk | grep -m1 "Signer #1 certificate DN"
```
Expected: `exit=0` and `CN=Treadmill Sync`. If `build-tools` is missing, `sdkmanager "build-tools;<API>.0.0"` first.

- [ ] **Step 6: Commit, push, tag, verify the release**

```bash
git add android .github/workflows README.md
git commit -m "Sign and release the Android companion APK"
git push origin HEAD:main
gh run watch "$(gh run list --workflow android.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
git tag android-v0.1.0 && git push origin android-v0.1.0
gh run watch "$(gh run list --workflow android-release.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
gh release view android-v0.1.0 --json assets -q '.assets[].name'
```
Expected: both runs green; the release lists `treadmill-sync-0.1.0.apk`.
