# Treadmill Data Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Connect IQ data field for Garmin Instinct 3 Solar 45mm that reads speed, distance and steps from a Kingsmith R1 Pro treadmill over BLE, shows them, records them to FIT, and optionally starts/stops the belt with the activity timer.

**Architecture:** One data field app. Pure, unit-tested logic (`WalkingPadProtocol`, `SessionAccumulator`, `Fmt`, `BeltController`) sits under a hardware adapter (`TreadmillLink`, BLE) and a view (`TreadmillView`) that owns the timer events, rendering and FIT fields. A `(:debug)`-only `DemoLink` replaces the BLE link in the simulator.

**Tech Stack:** Monkey C, Connect IQ SDK (latest, API ≥ 5.0.0), `Toybox.BluetoothLowEnergy`, `Toybox.FitContributor`, Connect IQ unit tests (`(:test)`, `monkeydo -t`), GNU make.

**Spec:** `docs/superpowers/specs/2026-09-25-treadmill-datafield-design.md`

## Global Constraints

- Product ID `instinct3solar45mm` (confirmed or corrected in Task 1; if corrected, use the corrected ID everywhere).
- App type `datafield`, `minApiLevel="5.0.0"`, languages `eng` (default) and `rus`.
- Permissions: exactly `BluetoothLowEnergy` and `FitContributor`.
- Colors: only `Graphics.COLOR_BLACK` / `Graphics.COLOR_WHITE` (plus `COLOR_TRANSPARENT` as text background). All text via `dc.drawText`.
- BLE UUIDs: service `0000fe00-0000-1000-8000-00805f9b34fb`, notify `0000fe01-0000-1000-8000-00805f9b34fb`, write `0000fe02-0000-1000-8000-00805f9b34fb`.
- Commands (verified on device): query `f7 a2 00 00 a2 fd`, start `f7 a2 04 01 a7 fd`, stop `f7 a2 01 00 a3 fd`.
- Belt states: `0` stopped, `1` running, `3` stopping, `6..9` countdown.
- Timing: stale/no-data 5000 ms, error hold 3000 ms, "Connected" banner 3000 ms, stop retry once after 3000 ms, smoothing cap 10 m.
- Setting `controlBelt`, boolean, default `false`. The belt is started only at the moment of a timer start/resume event, only when connected and belt state is `0`.
- FIT fields are always metric (`km/h`, `km`, `steps`) because Connect IQ FIT unit labels are static resources; the screen follows device units.
- No `TODO`/stub code in delivered files (explicit user requirement).
- Developer key lives outside the repo at `~/.config/garmin/developer_key.der`; never commit keys.
- Commits: short English imperative subject, no ticket ID.

## Review Focus

1. Workout timer started before the treadmill connects, treadmill connects mid-workout: pre-workout treadmill counters must not be added, and the belt must not start late. → Task 3 `accFirstPacketMidWorkoutIsBaseline`, Task 5 `beltNoStartWhenNotConnectedAndNoLateStart`.
2. Pause stops the belt, resume restarts it and the treadmill resets its counters to 0: the total must continue, not drop or jump. → Task 3 `accResetDuringPauseThenResume`.
3. Stop requested while belt state is unknown (stale data): no blind command. → Task 5 `beltNoStopWhenStateUnknown`.
4. Foreign/empty notifications on `FE01`: silently ignored. → Task 2 `protocolRejectsMalformed`.
5. Long workouts where 24-bit counters exceed 16 bits (> 65 535 steps or 655 km): parsed correctly. → Task 2 `protocolParsesLargeCounters`.

## File Structure

```
garmin-treadmill-field/
├── .gitignore
├── Makefile                         build/test/demo commands
├── README.md                        build, sideload, on-watch checklist
├── manifest.xml
├── monkey.jungle
├── resources/
│   ├── drawables/drawables.xml, launcher_icon.png
│   ├── strings/strings.xml          English strings (default)
│   ├── properties.xml               controlBelt property
│   ├── settings.xml                 controlBelt setting UI
│   └── fit_contributions.xml        FIT field labels for Garmin Connect
├── resources-rus/strings/strings.xml
├── source/
│   ├── TreadmillApp.mc              AppBase entry
│   ├── TreadmillView.mc             DataField: compute, timer events, render, FIT
│   ├── LinkState.mc                 SEARCHING / CONNECTED / ERROR constants
│   ├── WalkingPadProtocol.mc        commands + packet parser
│   ├── SessionAccumulator.mc        totals, smoothing, staleness
│   ├── Fmt.mc                       unit conversion + string formatting
│   ├── BeltController.mc            start/stop decisions + stop retry
│   ├── TreadmillLink.mc             BLE adapter
│   └── DemoLink.mc                  (:debug) simulator replay
└── test/
    ├── TestUtil.mc, Fixtures.mc, FakeLink.mc   (:debug) helpers
    └── *Test.mc                     (:test) unit tests
```

Link interface, shared by `TreadmillLink` and `DemoLink` (duck-typed):
`initialize(onStatus as Method)`, `start() as Void`, `tick(nowMs as Number) as Void`, `getState() as Number`, `sendStart() as Void`, `sendStop() as Void`.
`onStatus` receives the Dictionary returned by `WalkingPadProtocol.parseStatus`.

---

### Task 1: Toolchain, skeleton and BLE build gate

**Files:**
- Create: `.gitignore`, `Makefile`, `manifest.xml`, `monkey.jungle`, `resources/strings/strings.xml`, `resources-rus/strings/strings.xml`, `resources/drawables/drawables.xml`, `resources/drawables/launcher_icon.png`, `source/TreadmillApp.mc`, `source/TreadmillView.mc` (gate version), `source/GateScanner.mc`

**Interfaces:**
- Produces: `TreadmillApp`, `TreadmillView extends WatchUi.DataField` (replaced in Task 7), Makefile targets `build`, `debug`, `test`, `sim`, `demo`, `clean`.

- [ ] **Step 1: Install the Connect IQ SDK (user action)**

Java 21 is already installed (`java -version` → openjdk 21). Ask the user to:
1. Download the SDK Manager for Linux from https://developer.garmin.com/connect-iq/sdk/ and unzip it to `~/connectiq-sdk-manager`.
2. Run `~/connectiq-sdk-manager/bin/sdkmanager`, sign in with the Garmin account, install the latest SDK, set it as current, and on the Devices tab download **Instinct 3 Solar 45mm**.

- [ ] **Step 2: Verify SDK and device ID**

Run:
```bash
cat ~/.Garmin/ConnectIQ/current-sdk.cfg
ls "$(cat ~/.Garmin/ConnectIQ/current-sdk.cfg)/bin" | grep -E '^(monkeyc|monkeydo|connectiq)$'
ls ~/.Garmin/ConnectIQ/Devices | grep -i instinct3
python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(d.get('connectIQVersion') or d.get('partNumbers'));print([ (a.get('type'),a.get('memoryLimit')) for a in d.get('appTypes',[]) ])" ~/.Garmin/ConnectIQ/Devices/instinct3solar45mm/compiler.json
```
Expected: an SDK path; `connectiq`, `monkeyc`, `monkeydo`; a directory named like `instinct3solar45mm`; a `datafield` entry with its memory limit. If the device directory name differs, use that name as the product ID in `manifest.xml` and `Makefile` and note it in the commit message. If the device's Connect IQ version is below 5.0, set `minApiLevel` to the device's version.

- [ ] **Step 3: Generate the developer key (outside the repo)**

```bash
mkdir -p ~/.config/garmin
openssl genrsa -out ~/.config/garmin/developer_key.pem 4096
openssl pkcs8 -topk8 -inform PEM -outform DER -in ~/.config/garmin/developer_key.pem -out ~/.config/garmin/developer_key.der -nocrypt
chmod 600 ~/.config/garmin/developer_key.*
```

- [ ] **Step 4: Create project files**

`.gitignore`:
```
bin/
*.der
*.pem
```

`Makefile` (recipe lines start with a TAB):
```make
SDK_HOME ?= $(shell cat $(HOME)/.Garmin/ConnectIQ/current-sdk.cfg 2>/dev/null)
SDK_BIN := $(SDK_HOME)/bin
KEY ?= $(HOME)/.config/garmin/developer_key.der
DEVICE ?= instinct3solar45mm
MONKEYC := $(SDK_BIN)/monkeyc -f monkey.jungle -d $(DEVICE) -y $(KEY)

.PHONY: build debug test sim demo clean

build:
	mkdir -p bin && $(MONKEYC) -r -o bin/TreadmillField.prg

debug:
	mkdir -p bin && $(MONKEYC) -o bin/TreadmillField-debug.prg

test:
	mkdir -p bin && $(MONKEYC) -t -o bin/test.prg
	$(SDK_BIN)/monkeydo bin/test.prg $(DEVICE) -t

sim:
	$(SDK_BIN)/connectiq &

demo: debug
	$(SDK_BIN)/monkeydo bin/TreadmillField-debug.prg $(DEVICE)

clean:
	rm -rf bin
```

`manifest.xml`:
```xml
<?xml version="1.0"?>
<iq:manifest version="3" xmlns:iq="http://www.garmin.com/xml/connectiq">
    <iq:application id="fc405d17fb8c4e98ac7a5b19e2275462" type="datafield" name="@Strings.AppName"
        entry="TreadmillApp" launcherIcon="@Drawables.LauncherIcon" minApiLevel="5.0.0">
        <iq:products>
            <iq:product id="instinct3solar45mm"/>
        </iq:products>
        <iq:permissions>
            <iq:uses-permission id="BluetoothLowEnergy"/>
            <iq:uses-permission id="FitContributor"/>
        </iq:permissions>
        <iq:languages>
            <iq:language>eng</iq:language>
            <iq:language>rus</iq:language>
        </iq:languages>
        <iq:barrels/>
    </iq:application>
</iq:manifest>
```

`monkey.jungle`:
```
project.manifest = manifest.xml
```

`resources/strings/strings.xml`:
```xml
<strings>
    <string id="AppName">Treadmill</string>
</strings>
```

`resources-rus/strings/strings.xml`:
```xml
<strings>
    <string id="AppName">Дорожка</string>
</strings>
```

`resources/drawables/drawables.xml`:
```xml
<drawables>
    <bitmap id="LauncherIcon" filename="launcher_icon.png"/>
</drawables>
```

Generate the icon (black treadmill glyph on white, 40×40):
```bash
uv run --quiet --with pillow python - <<'EOF'
from PIL import Image, ImageDraw
img = Image.new("RGB", (40, 40), "white")
d = ImageDraw.Draw(img)
d.rounded_rectangle([3, 26, 37, 33], radius=3, outline="black", width=2)
d.line([30, 26, 34, 8], fill="black", width=2)
d.line([30, 8, 38, 8], fill="black", width=2)
d.ellipse([14, 4, 20, 10], fill="black")
d.line([17, 10, 17, 19], fill="black", width=2)
d.line([17, 19, 12, 25], fill="black", width=2)
d.line([17, 19, 22, 25], fill="black", width=2)
img.save("resources/drawables/launcher_icon.png")
EOF
```

`source/TreadmillApp.mc`:
```monkeyc
import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

class TreadmillApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() {
        return [new TreadmillView()];
    }
}
```

`source/GateScanner.mc` (temporary, deleted in Task 7):
```monkeyc
import Toybox.BluetoothLowEnergy;
import Toybox.Lang;
import Toybox.WatchUi;

class GateScanner extends BluetoothLowEnergy.BleDelegate {
    var found as Boolean = false;
    hidden var _service as BluetoothLowEnergy.Uuid;

    function initialize() {
        BleDelegate.initialize();
        _service = BluetoothLowEnergy.stringToUuid("0000fe00-0000-1000-8000-00805f9b34fb");
    }

    function start() as Void {
        BluetoothLowEnergy.setDelegate(self);
        BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_SCANNING);
    }

    function onScanResults(scanResults as BluetoothLowEnergy.Iterator) as Void {
        for (var r = scanResults.next(); r != null; r = scanResults.next()) {
            var uuids = (r as BluetoothLowEnergy.ScanResult).getServiceUuids();
            for (var u = uuids.next(); u != null; u = uuids.next()) {
                if ((u as BluetoothLowEnergy.Uuid).equals(_service)) {
                    found = true;
                    WatchUi.requestUpdate();
                }
            }
        }
    }
}
```

`source/TreadmillView.mc` (gate version):
```monkeyc
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

class TreadmillView extends WatchUi.DataField {
    hidden var _gate as GateScanner;

    function initialize() {
        DataField.initialize();
        _gate = new GateScanner();
        _gate.start();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var bg = getBackgroundColor();
        var fg = bg == Graphics.COLOR_BLACK ? Graphics.COLOR_WHITE : Graphics.COLOR_BLACK;
        dc.setColor(fg, bg);
        dc.clear();
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(dc.getWidth() / 2, dc.getHeight() / 2, Graphics.FONT_SMALL,
            _gate.found ? "FOUND FE00" : "SCANNING",
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
```

- [ ] **Step 5: Run the build gate**

Run: `make build`
Expected: `BUILD SUCCESSFUL` and `bin/TreadmillField.prg` exists.
**Gate:** if the compiler reports that `BluetoothLowEnergy` (or the permission) is not available for a `datafield` on this device, STOP. Do not continue with Task 2; report the exact compiler message to the user and revisit the architecture (custom activity app) with them.

- [ ] **Step 6: On-watch BLE gate (user action)**

Ask the user to: connect the watch by USB, copy `bin/TreadmillField.prg` to `GARMIN/APPS/` on the watch (MTP; e.g. the file manager), disconnect, open "Treadmill Walk", add the Connect IQ field "Treadmill" to a data screen, wake the treadmill with the phone's Bluetooth off.
Expected: the field shows `FOUND FE00` within ~15 s. If it stays `SCANNING` or shows an error/IQ! icon, STOP and report to the user before continuing.

- [ ] **Step 7: Commit**

```bash
git add .gitignore Makefile manifest.xml monkey.jungle resources resources-rus source
git commit -m "Add project skeleton and BLE build gate"
```

---

### Task 2: WalkingPadProtocol

**Files:**
- Create: `source/WalkingPadProtocol.mc`, `test/TestUtil.mc`, `test/Fixtures.mc`, `test/WalkingPadProtocolTest.mc`
- Modify: `monkey.jungle`

**Interfaces:**
- Produces:
  - `WalkingPadProtocol.BELT_STOPPED = 0`, `BELT_RUNNING = 1`, `BELT_STOPPING = 3`
  - `WalkingPadProtocol.statusQuery() as ByteArray`, `startCommand() as ByteArray`, `stopCommand() as ByteArray`
  - `WalkingPadProtocol.isCountdown(state as Number) as Boolean`
  - `WalkingPadProtocol.parseStatus(bytes as ByteArray?) as Dictionary?` → keys `:state, :speedTenths, :timeS, :distTens, :steps` (all `Number`)
  - `(:debug) WalkingPadProtocol.buildStatusPacket(state, speedTenths, timeS, distTens, steps) as ByteArray`
  - `(:debug) TestUtil.bytesEqual(a, b) as Boolean`, `TestUtil.near(a, b) as Boolean`

- [ ] **Step 1: Add the test source path**

`monkey.jungle`:
```
project.manifest = manifest.xml
base.sourcePath = source;test
```

- [ ] **Step 2: Write test helpers and fixtures**

`test/TestUtil.mc`:
```monkeyc
import Toybox.Lang;

(:debug)
module TestUtil {
    function bytesEqual(a as ByteArray, b as ByteArray) as Boolean {
        if (a.size() != b.size()) {
            return false;
        }
        for (var i = 0; i < a.size(); i++) {
            if (a[i] != b[i]) {
                return false;
            }
        }
        return true;
    }

    function near(a as Numeric, b as Numeric) as Boolean {
        return (a - b).abs() < 0.001;
    }
}
```

`test/Fixtures.mc` (packets captured from the user's R1 Pro on 2026-09-25; `countdown` and `stopping` are rebuilt from logged fields):
```monkeyc
import Toybox.Lang;

(:debug)
module Fixtures {
    function stopped() as ByteArray {
        return [0xF8, 0xA2, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xA3, 0xFD]b;
    }

    // 4.5 km/h, 130 s, 160 m, 230 steps.
    function walking() as ByteArray {
        return [0xF8, 0xA2, 0x01, 0x2D, 0x01, 0x00, 0x00, 0x82, 0x00, 0x00, 0x10, 0x00, 0x00, 0xE6, 0x00, 0x00, 0x00, 0x00, 0x49, 0xFD]b;
    }

    // Remote button event in byte 16; 5.0 km/h, 42 s, 40 m, 69 steps.
    function buttonPress() as ByteArray {
        return [0xF8, 0xA2, 0x01, 0x32, 0x01, 0x00, 0x00, 0x2A, 0x00, 0x00, 0x04, 0x00, 0x00, 0x45, 0x00, 0x00, 0x02, 0x00, 0x4B, 0xFD]b;
    }

    function countdown() as ByteArray {
        return [0xF8, 0xA2, 0x09, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0xAF, 0xFD]b;
    }

    // Decelerating: 0.7 km/h, 14 s, 0 m, 14 steps.
    function stopping() as ByteArray {
        return [0xF8, 0xA2, 0x03, 0x07, 0x01, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x00, 0x00, 0xC9, 0xFD]b;
    }
}
```

- [ ] **Step 3: Write the failing tests**

`test/WalkingPadProtocolTest.mc`:
```monkeyc
import Toybox.Lang;
import Toybox.Test;

(:test)
function protocolCommandBytes(logger as Logger) as Boolean {
    Test.assert(TestUtil.bytesEqual(WalkingPadProtocol.statusQuery(), [0xF7, 0xA2, 0x00, 0x00, 0xA2, 0xFD]b));
    Test.assert(TestUtil.bytesEqual(WalkingPadProtocol.startCommand(), [0xF7, 0xA2, 0x04, 0x01, 0xA7, 0xFD]b));
    Test.assert(TestUtil.bytesEqual(WalkingPadProtocol.stopCommand(), [0xF7, 0xA2, 0x01, 0x00, 0xA3, 0xFD]b));
    return true;
}

(:test)
function protocolParsesStopped(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(Fixtures.stopped());
    Test.assert(s != null);
    Test.assertEqual(s[:state], 0);
    Test.assertEqual(s[:speedTenths], 0);
    Test.assertEqual(s[:timeS], 0);
    Test.assertEqual(s[:distTens], 0);
    Test.assertEqual(s[:steps], 0);
    return true;
}

(:test)
function protocolParsesWalking(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(Fixtures.walking());
    Test.assert(s != null);
    Test.assertEqual(s[:state], 1);
    Test.assertEqual(s[:speedTenths], 45);
    Test.assertEqual(s[:timeS], 130);
    Test.assertEqual(s[:distTens], 16);
    Test.assertEqual(s[:steps], 230);
    return true;
}

(:test)
function protocolParsesButtonPress(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(Fixtures.buttonPress());
    Test.assert(s != null);
    Test.assertEqual(s[:speedTenths], 50);
    Test.assertEqual(s[:timeS], 42);
    Test.assertEqual(s[:distTens], 4);
    Test.assertEqual(s[:steps], 69);
    return true;
}

(:test)
function protocolParsesCountdownAndStopping(logger as Logger) as Boolean {
    var c = WalkingPadProtocol.parseStatus(Fixtures.countdown());
    Test.assert(c != null);
    Test.assertEqual(c[:state], 9);
    var s = WalkingPadProtocol.parseStatus(Fixtures.stopping());
    Test.assert(s != null);
    Test.assertEqual(s[:state], WalkingPadProtocol.BELT_STOPPING);
    Test.assertEqual(s[:speedTenths], 7);
    Test.assertEqual(s[:steps], 14);
    return true;
}

(:test)
function protocolCountdownRange(logger as Logger) as Boolean {
    Test.assert(!WalkingPadProtocol.isCountdown(5));
    Test.assert(WalkingPadProtocol.isCountdown(6));
    Test.assert(WalkingPadProtocol.isCountdown(9));
    Test.assert(!WalkingPadProtocol.isCountdown(10));
    Test.assert(!WalkingPadProtocol.isCountdown(1));
    return true;
}

(:test)
function protocolRejectsMalformed(logger as Logger) as Boolean {
    var badChecksum = Fixtures.walking();
    badChecksum[18] = 0x48;
    Test.assert(WalkingPadProtocol.parseStatus(badChecksum) == null);

    var wrongType = Fixtures.walking();
    wrongType[1] = 0xA7;
    Test.assert(WalkingPadProtocol.parseStatus(wrongType) == null);

    var wrongHeader = Fixtures.walking();
    wrongHeader[0] = 0xF7;
    Test.assert(WalkingPadProtocol.parseStatus(wrongHeader) == null);

    var noFooter = Fixtures.walking();
    noFooter[19] = 0x00;
    Test.assert(WalkingPadProtocol.parseStatus(noFooter) == null);

    Test.assert(WalkingPadProtocol.parseStatus(Fixtures.walking().slice(0, 10)) == null);
    Test.assert(WalkingPadProtocol.parseStatus([]b) == null);
    Test.assert(WalkingPadProtocol.parseStatus(null) == null);
    return true;
}

(:test)
function protocolParsesLargeCounters(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(
        WalkingPadProtocol.buildStatusPacket(1, 45, 0x010000, 0x00ABCD, 0x012345));
    Test.assert(s != null);
    Test.assertEqual(s[:timeS], 65536);
    Test.assertEqual(s[:distTens], 43981);
    Test.assertEqual(s[:steps], 74565);
    return true;
}

(:test)
function protocolBuilderMatchesCapture(logger as Logger) as Boolean {
    Test.assert(TestUtil.bytesEqual(
        WalkingPadProtocol.buildStatusPacket(1, 45, 130, 16, 230), Fixtures.walking()));
    return true;
}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `make sim` (once per session; wait for the simulator window), then `make test`
Expected: compile FAIL, undefined symbol `WalkingPadProtocol`.

- [ ] **Step 5: Implement**

`source/WalkingPadProtocol.mc`:
```monkeyc
import Toybox.Lang;

// Kingsmith/WalkingPad FE00 protocol, verified on an R1 Pro.
module WalkingPadProtocol {
    const BELT_STOPPED = 0;
    const BELT_RUNNING = 1;
    const BELT_STOPPING = 3;
    const MIN_STATUS_LENGTH = 19;

    function statusQuery() as ByteArray {
        return [0xF7, 0xA2, 0x00, 0x00, 0xA2, 0xFD]b;
    }

    function startCommand() as ByteArray {
        return [0xF7, 0xA2, 0x04, 0x01, 0xA7, 0xFD]b;
    }

    function stopCommand() as ByteArray {
        return [0xF7, 0xA2, 0x01, 0x00, 0xA3, 0xFD]b;
    }

    // States 9..6 are the pre-start countdown.
    function isCountdown(state as Number) as Boolean {
        return state >= 6 && state <= 9;
    }

    // Returns {:state, :speedTenths, :timeS, :distTens, :steps} or null for anything
    // that is not a valid status packet.
    function parseStatus(bytes as ByteArray?) as Dictionary? {
        if (bytes == null) {
            return null;
        }
        var n = bytes.size();
        if (n < MIN_STATUS_LENGTH) {
            return null;
        }
        if (bytes[0] != 0xF8 || bytes[1] != 0xA2 || bytes[n - 1] != 0xFD) {
            return null;
        }
        var sum = 0;
        for (var i = 1; i <= n - 3; i++) {
            sum += bytes[i];
        }
        if ((sum & 0xFF) != bytes[n - 2]) {
            return null;
        }
        return {
            :state => bytes[2],
            :speedTenths => bytes[3],
            :timeS => readU24(bytes, 5),
            :distTens => readU24(bytes, 8),
            :steps => readU24(bytes, 11)
        };
    }

    function readU24(bytes as ByteArray, offset as Number) as Number {
        return (bytes[offset] << 16) | (bytes[offset + 1] << 8) | bytes[offset + 2];
    }

    (:debug)
    function buildStatusPacket(state as Number, speedTenths as Number, timeS as Number,
            distTens as Number, steps as Number) as ByteArray {
        var b = new [20]b;
        b[0] = 0xF8;
        b[1] = 0xA2;
        b[2] = state;
        b[3] = speedTenths;
        b[4] = 0x01;
        writeU24(b, 5, timeS);
        writeU24(b, 8, distTens);
        writeU24(b, 11, steps);
        var sum = 0;
        for (var i = 1; i <= 17; i++) {
            sum += b[i];
        }
        b[18] = sum & 0xFF;
        b[19] = 0xFD;
        return b;
    }

    (:debug)
    function writeU24(b as ByteArray, offset as Number, value as Number) as Void {
        b[offset] = (value >> 16) & 0xFF;
        b[offset + 1] = (value >> 8) & 0xFF;
        b[offset + 2] = value & 0xFF;
    }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `make test`
Expected: all 9 protocol tests PASS, 0 failures. Also run `make build` → BUILD SUCCESSFUL (release excludes `(:debug)`/`(:test)` code).

- [ ] **Step 7: Commit**

```bash
git add monkey.jungle source/WalkingPadProtocol.mc test
git commit -m "Add WalkingPad protocol parser and commands"
```

---

### Task 3: SessionAccumulator

**Files:**
- Create: `source/SessionAccumulator.mc`, `test/SessionAccumulatorTest.mc`

**Interfaces:**
- Consumes: status Dictionary from `WalkingPadProtocol.parseStatus` (`:state, :speedTenths, :timeS, :distTens, :steps`), `WalkingPadProtocol.BELT_RUNNING`.
- Produces `class SessionAccumulator`:
  - `setTimerRunning(running as Boolean) as Void`
  - `onStatus(status as Dictionary, nowMs as Number) as Void`
  - `tick(nowMs as Number) as Void`
  - `reset() as Void`
  - `hasData() as Boolean`
  - `getTotalDistM() as Float`, `getDisplayDistM() as Float`, `getTotalSteps() as Number`
  - `getSpeedMps(nowMs as Number) as Float?` (null when stale)
  - `getBeltState(nowMs as Number) as Number?` (null when stale)

- [ ] **Step 1: Write the failing tests**

`test/SessionAccumulatorTest.mc`:
```monkeyc
import Toybox.Lang;
import Toybox.Test;

(:debug)
function st(state as Number, speedTenths as Number, distTens as Number, steps as Number) as Dictionary {
    return {:state => state, :speedTenths => speedTenths, :timeS => 0, :distTens => distTens, :steps => steps};
}

(:test)
function accFirstPacketMidWorkoutIsBaseline(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    Test.assert(!a.hasData());
    a.onStatus(st(1, 45, 16, 230), 1000);
    Test.assert(a.hasData());
    Test.assert(TestUtil.near(a.getTotalDistM(), 0.0));
    Test.assertEqual(a.getTotalSteps(), 0);
    return true;
}

(:test)
function accAddsDeltasWhileRunning(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 12, 130), 1000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 20.0));
    Test.assertEqual(a.getTotalSteps(), 30);
    return true;
}

(:test)
function accPauseExcludesWalking(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.setTimerRunning(false);
    a.onStatus(st(1, 45, 12, 130), 1000);
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 13, 140), 2000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assertEqual(a.getTotalSteps(), 10);
    return true;
}

(:test)
function accTreadmillResetCountsRawValue(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 16, 230), 0);
    a.onStatus(st(1, 45, 1, 5), 1000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assertEqual(a.getTotalSteps(), 5);
    a.onStatus(st(1, 45, 2, 8), 2000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 20.0));
    Test.assertEqual(a.getTotalSteps(), 8);
    return true;
}

(:test)
function accResetDuringPauseThenResume(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 16, 230), 1000);
    a.setTimerRunning(false);
    a.onStatus(st(0, 0, 16, 230), 2000);
    a.onStatus(st(9, 0, 0, 0), 3000);
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 1, 3), 4000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 70.0));
    Test.assertEqual(a.getTotalSteps(), 133);
    return true;
}

(:test)
function accReconnectGapIsCounted(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 14, 150), 30000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 40.0));
    Test.assertEqual(a.getTotalSteps(), 50);
    return true;
}

(:test)
function accSpeedFollowsBeltState(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.onStatus(st(1, 45, 0, 0), 0);
    Test.assert(TestUtil.near(a.getSpeedMps(0) as Float, 1.25));
    Test.assertEqual(a.getBeltState(0), 1);
    a.onStatus(st(3, 7, 0, 0), 1000);
    Test.assert(TestUtil.near(a.getSpeedMps(1000) as Float, 0.0));
    Test.assertEqual(a.getBeltState(1000), 3);
    a.onStatus(st(9, 0, 0, 0), 2000);
    Test.assert(TestUtil.near(a.getSpeedMps(2000) as Float, 0.0));
    return true;
}

(:test)
function accStaleAfterFiveSeconds(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    Test.assert(a.getSpeedMps(0) == null);
    Test.assert(a.getBeltState(0) == null);
    a.onStatus(st(1, 45, 0, 0), 1000);
    Test.assert(a.getSpeedMps(6000) != null);
    Test.assert(a.getSpeedMps(6001) == null);
    Test.assert(a.getBeltState(6001) == null);
    return true;
}

(:test)
function accSmoothsDistanceWithCap(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 0, 0), 0);
    a.tick(0);
    a.tick(4000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 5.0));
    a.onStatus(st(1, 45, 0, 0), 4000);
    a.onStatus(st(1, 45, 0, 0), 8000);
    a.tick(12000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 10.0));
    a.onStatus(st(1, 45, 1, 0), 12500);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assert(TestUtil.near(a.getDisplayDistM(), 10.0));
    a.tick(14500);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 13.125));
    return true;
}

(:test)
function accDisplayNeverDecreases(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 0, 0), 0);
    a.tick(0);
    a.tick(4000);
    var before = a.getDisplayDistM();
    a.onStatus(st(1, 45, 0, 0), 4000);
    Test.assert(a.getDisplayDistM() >= before);
    return true;
}

(:test)
function accNoSmoothingWhenPausedOrStale(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.onStatus(st(1, 45, 0, 0), 0);
    a.tick(0);
    a.tick(2000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 0.0));
    a.setTimerRunning(true);
    a.tick(20000);
    a.tick(22000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 0.0));
    return true;
}

(:test)
function accResetKeepsBaseline(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 12, 130), 1000);
    a.reset();
    Test.assert(TestUtil.near(a.getTotalDistM(), 0.0));
    Test.assert(TestUtil.near(a.getDisplayDistM(), 0.0));
    Test.assertEqual(a.getTotalSteps(), 0);
    a.onStatus(st(1, 45, 13, 135), 2000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assertEqual(a.getTotalSteps(), 5);
    return true;
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: compile FAIL, undefined symbol `SessionAccumulator`.

- [ ] **Step 3: Implement**

`source/SessionAccumulator.mc`:
```monkeyc
import Toybox.Lang;

// Turns the treadmill's own counters into workout totals.
class SessionAccumulator {
    const STALE_MS = 5000;
    const SMOOTH_CAP_M = 10.0;
    const DIST_UNIT_M = 10;

    hidden var _totalDistM as Float = 0.0;
    hidden var _displayDistM as Float = 0.0;
    hidden var _totalSteps as Number = 0;
    hidden var _lastRawDist as Number? = null;
    hidden var _lastRawSteps as Number? = null;
    hidden var _timerRunning as Boolean = false;
    hidden var _speedMps as Float = 0.0;
    hidden var _beltState as Number? = null;
    hidden var _lastPacketMs as Number? = null;
    hidden var _lastTickMs as Number? = null;

    function initialize() {
    }

    function setTimerRunning(running as Boolean) as Void {
        _timerRunning = running;
    }

    function onStatus(status as Dictionary, nowMs as Number) as Void {
        var rawDist = status[:distTens] as Number;
        var rawSteps = status[:steps] as Number;
        if (_lastRawDist != null && _timerRunning) {
            _totalDistM += (counterDelta(rawDist, _lastRawDist) * DIST_UNIT_M).toFloat();
            _totalSteps += counterDelta(rawSteps, _lastRawSteps as Number);
        }
        _lastRawDist = rawDist;
        _lastRawSteps = rawSteps;
        _beltState = status[:state] as Number;
        _speedMps = _beltState == WalkingPadProtocol.BELT_RUNNING
            ? (status[:speedTenths] as Number) / 36.0
            : 0.0;
        _lastPacketMs = nowMs;
        if (_displayDistM < _totalDistM) {
            _displayDistM = _totalDistM;
        }
    }

    // Grows the displayed distance between 10 m packets, never past total + 10 m.
    function tick(nowMs as Number) as Void {
        if (_lastTickMs != null && _timerRunning && !isStale(nowMs)) {
            var grown = _displayDistM + _speedMps * (nowMs - _lastTickMs) / 1000.0;
            var cap = _totalDistM + SMOOTH_CAP_M;
            var next = grown < cap ? grown : cap;
            if (next > _displayDistM) {
                _displayDistM = next;
            }
        }
        _lastTickMs = nowMs;
    }

    // New workout: zero the totals, keep the treadmill baseline.
    function reset() as Void {
        _totalDistM = 0.0;
        _displayDistM = 0.0;
        _totalSteps = 0;
    }

    function hasData() as Boolean {
        return _lastRawDist != null;
    }

    function getTotalDistM() as Float {
        return _totalDistM;
    }

    function getDisplayDistM() as Float {
        return _displayDistM;
    }

    function getTotalSteps() as Number {
        return _totalSteps;
    }

    function getSpeedMps(nowMs as Number) as Float? {
        return isStale(nowMs) ? null : _speedMps;
    }

    function getBeltState(nowMs as Number) as Number? {
        return isStale(nowMs) ? null : _beltState;
    }

    hidden function isStale(nowMs as Number) as Boolean {
        return _lastPacketMs == null || nowMs - _lastPacketMs > STALE_MS;
    }

    // A counter that went down means the treadmill started a new session from zero.
    hidden function counterDelta(raw as Number, last as Number) as Number {
        return raw >= last ? raw - last : raw;
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: all protocol and accumulator tests PASS, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add source/SessionAccumulator.mc test/SessionAccumulatorTest.mc
git commit -m "Add session accumulator for treadmill counters"
```

---

### Task 4: Fmt (units and formatting)

**Files:**
- Create: `source/Fmt.mc`, `test/FmtTest.mc`

**Interfaces:**
- Produces: `Fmt.speed(mps as Float?, metric as Boolean) as String` (`"--"` for null), `Fmt.distance(meters as Float, metric as Boolean) as String`, `Fmt.speedUnit(metric) as String` (`"km/h"`/`"mph"`), `Fmt.distanceUnit(metric) as String` (`"km"`/`"mi"`).

- [ ] **Step 1: Write the failing tests**

`test/FmtTest.mc`:
```monkeyc
import Toybox.Lang;
import Toybox.Test;

(:test)
function fmtSpeed(logger as Logger) as Boolean {
    Test.assertEqual(Fmt.speed(1.25, true), "4.5");
    Test.assertEqual(Fmt.speed(1.25, false), "2.8");
    Test.assertEqual(Fmt.speed(0.0, true), "0.0");
    Test.assertEqual(Fmt.speed(null, true), "--");
    return true;
}

(:test)
function fmtDistance(logger as Logger) as Boolean {
    Test.assertEqual(Fmt.distance(160.0, true), "0.16");
    Test.assertEqual(Fmt.distance(1340.0, true), "1.34");
    Test.assertEqual(Fmt.distance(1609.344, false), "1.00");
    Test.assertEqual(Fmt.distance(0.0, false), "0.00");
    return true;
}

(:test)
function fmtUnits(logger as Logger) as Boolean {
    Test.assertEqual(Fmt.speedUnit(true), "km/h");
    Test.assertEqual(Fmt.speedUnit(false), "mph");
    Test.assertEqual(Fmt.distanceUnit(true), "km");
    Test.assertEqual(Fmt.distanceUnit(false), "mi");
    return true;
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: compile FAIL, undefined symbol `Fmt`.

- [ ] **Step 3: Implement**

`source/Fmt.mc`:
```monkeyc
import Toybox.Lang;

module Fmt {
    const KMH_PER_MPS = 3.6;
    const MPH_PER_MPS = 2.2369363;
    const M_PER_KM = 1000.0;
    const M_PER_MILE = 1609.344;

    function speed(mps as Float?, metric as Boolean) as String {
        if (mps == null) {
            return "--";
        }
        return (mps * (metric ? KMH_PER_MPS : MPH_PER_MPS)).format("%.1f");
    }

    function distance(meters as Float, metric as Boolean) as String {
        return (meters / (metric ? M_PER_KM : M_PER_MILE)).format("%.2f");
    }

    function speedUnit(metric as Boolean) as String {
        return metric ? "km/h" : "mph";
    }

    function distanceUnit(metric as Boolean) as String {
        return metric ? "km" : "mi";
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: all tests PASS, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add source/Fmt.mc test/FmtTest.mc
git commit -m "Add unit conversion and formatting"
```

---

### Task 5: LinkState and BeltController

**Files:**
- Create: `source/LinkState.mc`, `source/BeltController.mc`, `test/FakeLink.mc`, `test/BeltControllerTest.mc`

**Interfaces:**
- Consumes: `WalkingPadProtocol.BELT_STOPPED`, `BELT_RUNNING`, `isCountdown`; link object with `sendStart()`, `sendStop()`.
- Produces:
  - `LinkState.SEARCHING = 0`, `LinkState.CONNECTED = 1`, `LinkState.ERROR = 2`
  - `class BeltController`: `initialize(link)`, `onRun(enabled as Boolean, linkState as Number, beltState as Number?) as Void`, `onHalt(enabled as Boolean, linkState as Number, beltState as Number?, nowMs as Number) as Void`, `tick(linkState as Number, beltState as Number?, nowMs as Number) as Void`
  - `(:debug) class FakeLink` with public `starts as Number`, `stops as Number`

- [ ] **Step 1: Write the fake and failing tests**

`test/FakeLink.mc`:
```monkeyc
import Toybox.Lang;

(:debug)
class FakeLink {
    var starts as Number = 0;
    var stops as Number = 0;

    function initialize() {
    }

    function sendStart() as Void {
        starts += 1;
    }

    function sendStop() as Void {
        stops += 1;
    }
}
```

`test/BeltControllerTest.mc`:
```monkeyc
import Toybox.Lang;
import Toybox.Test;

(:test)
function beltStartsWhenEnabledConnectedStopped(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 0);
    Test.assertEqual(link.starts, 1);
    return true;
}

(:test)
function beltNoStartWhenDisabled(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(false, LinkState.CONNECTED, 0);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltNoStartWhenNotConnectedAndNoLateStart(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.SEARCHING, null);
    belt.onRun(true, LinkState.ERROR, 0);
    belt.tick(LinkState.CONNECTED, 0, 10000);
    belt.tick(LinkState.CONNECTED, 0, 20000);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltNoStartWhenRunningOrUnknown(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 1);
    belt.onRun(true, LinkState.CONNECTED, 3);
    belt.onRun(true, LinkState.CONNECTED, 8);
    belt.onRun(true, LinkState.CONNECTED, null);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltStopsWhenRunningOrCountdown(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.onHalt(true, LinkState.CONNECTED, 7, 100);
    Test.assertEqual(link.stops, 2);
    return true;
}

(:test)
function beltNoStopWhenStoppedOrDisabled(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 0, 0);
    belt.onHalt(true, LinkState.CONNECTED, 3, 0);
    belt.onHalt(false, LinkState.CONNECTED, 1, 0);
    belt.onHalt(true, LinkState.SEARCHING, 1, 0);
    Test.assertEqual(link.stops, 0);
    return true;
}

(:test)
function beltNoStopWhenStateUnknown(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, null, 0);
    belt.tick(LinkState.CONNECTED, 1, 5000);
    Test.assertEqual(link.stops, 0);
    return true;
}

(:test)
function beltRetriesStopOnceAfterThreeSeconds(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.tick(LinkState.CONNECTED, 1, 2999);
    Test.assertEqual(link.stops, 1);
    belt.tick(LinkState.CONNECTED, 1, 3000);
    Test.assertEqual(link.stops, 2);
    belt.tick(LinkState.CONNECTED, 1, 6000);
    belt.tick(LinkState.CONNECTED, 1, 9000);
    Test.assertEqual(link.stops, 2);
    return true;
}

(:test)
function beltNoRetryWhenStopping(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.tick(LinkState.CONNECTED, 3, 3000);
    Test.assertEqual(link.stops, 1);
    return true;
}

(:test)
function beltResumeCancelsPendingRetry(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.onRun(true, LinkState.CONNECTED, 3);
    belt.tick(LinkState.CONNECTED, 1, 3000);
    Test.assertEqual(link.stops, 1);
    Test.assertEqual(link.starts, 0);
    return true;
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: compile FAIL, undefined symbols `BeltController` / `LinkState`.

- [ ] **Step 3: Implement**

`source/LinkState.mc`:
```monkeyc
module LinkState {
    const SEARCHING = 0;
    const CONNECTED = 1;
    const ERROR = 2;
}
```

`source/BeltController.mc`:
```monkeyc
import Toybox.Lang;

// Decides when the activity timer may start or stop the belt.
class BeltController {
    const STOP_RETRY_MS = 3000;

    hidden var _link;
    hidden var _stopSentMs as Number? = null;

    function initialize(link) {
        _link = link;
    }

    // Timer start/resume: start only now, only from a known stopped state.
    function onRun(enabled as Boolean, linkState as Number, beltState as Number?) as Void {
        _stopSentMs = null;
        if (enabled && linkState == LinkState.CONNECTED && beltState == WalkingPadProtocol.BELT_STOPPED) {
            _link.sendStart();
        }
    }

    // Timer pause/stop.
    function onHalt(enabled as Boolean, linkState as Number, beltState as Number?, nowMs as Number) as Void {
        if (!enabled || linkState != LinkState.CONNECTED || beltState == null) {
            return;
        }
        if (beltState == WalkingPadProtocol.BELT_RUNNING || WalkingPadProtocol.isCountdown(beltState)) {
            _link.sendStop();
            _stopSentMs = nowMs;
        }
    }

    // Resends the stop once if the belt is still running 3 s later.
    function tick(linkState as Number, beltState as Number?, nowMs as Number) as Void {
        if (_stopSentMs == null || nowMs - _stopSentMs < STOP_RETRY_MS) {
            return;
        }
        _stopSentMs = null;
        if (linkState == LinkState.CONNECTED && beltState == WalkingPadProtocol.BELT_RUNNING) {
            _link.sendStop();
        }
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: all tests PASS, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add source/LinkState.mc source/BeltController.mc test/FakeLink.mc test/BeltControllerTest.mc
git commit -m "Add belt start/stop controller"
```

---

### Task 6: TreadmillLink (BLE adapter)

**Files:**
- Create: `source/TreadmillLink.mc`

**Interfaces:**
- Consumes: `WalkingPadProtocol.statusQuery/startCommand/stopCommand/parseStatus`, `LinkState.*`.
- Produces: `class TreadmillLink extends BluetoothLowEnergy.BleDelegate` implementing the link interface: `initialize(onStatus as Method)`, `start()`, `tick(nowMs)`, `getState() as Number`, `sendStart()`, `sendStop()`.

BLE needs real hardware, so this task has no unit tests; its checks are the SDK doc lookup, a clean release build, and the on-watch test in Task 9.

- [ ] **Step 1: Confirm the write type for write-without-response**

Run:
```bash
SDK="$(cat ~/.Garmin/ConnectIQ/current-sdk.cfg)"
grep -rhoE 'WRITE_TYPE_[A-Z_]+[^<]{0,200}' "$SDK/doc/Toybox/BluetoothLowEnergy.html" | sort -u
```
Expected: the description of each `WRITE_TYPE_*` constant. `FE02` only supports write-without-response. Use the constant documented as "write without response" (expected: `WRITE_TYPE_DEFAULT`) in `_writeOptions` below; if the docs say `WRITE_TYPE_DEFAULT` is *with* response, use the other constant and note that in the commit message. Also note whether `onCharacteristicWrite` is documented to fire for writes without response; the busy timeout below covers the case where it does not.

- [ ] **Step 2: Implement**

`source/TreadmillLink.mc`:
```monkeyc
import Toybox.BluetoothLowEnergy;
import Toybox.Lang;
import Toybox.System;

// Scans for the treadmill, keeps one connection, polls status once per tick and
// sends belt commands. Only one GATT operation is outstanding at a time.
class TreadmillLink extends BluetoothLowEnergy.BleDelegate {
    const ERROR_HOLD_MS = 3000;
    const NO_DATA_TIMEOUT_MS = 5000;
    const CONNECT_TIMEOUT_MS = 15000;
    const BUSY_TIMEOUT_MS = 2000;

    hidden var _onStatus as Method;
    hidden var _serviceUuid as BluetoothLowEnergy.Uuid;
    hidden var _notifyUuid as BluetoothLowEnergy.Uuid;
    hidden var _writeUuid as BluetoothLowEnergy.Uuid;
    hidden var _writeOptions as Dictionary;
    hidden var _state as Number = LinkState.SEARCHING;
    hidden var _device as BluetoothLowEnergy.Device? = null;
    hidden var _writeChar as BluetoothLowEnergy.Characteristic? = null;
    hidden var _ready as Boolean = false;
    hidden var _busySinceMs as Number? = null;
    hidden var _pending as Array<ByteArray> = [];
    hidden var _phaseStartMs as Number? = null;
    hidden var _lastPacketMs as Number? = null;
    hidden var _errorSinceMs as Number = 0;

    function initialize(onStatus as Method) {
        BleDelegate.initialize();
        _onStatus = onStatus;
        _serviceUuid = BluetoothLowEnergy.stringToUuid("0000fe00-0000-1000-8000-00805f9b34fb");
        _notifyUuid = BluetoothLowEnergy.stringToUuid("0000fe01-0000-1000-8000-00805f9b34fb");
        _writeUuid = BluetoothLowEnergy.stringToUuid("0000fe02-0000-1000-8000-00805f9b34fb");
        _writeOptions = {:writeType => BluetoothLowEnergy.WRITE_TYPE_DEFAULT};
    }

    function start() as Void {
        BluetoothLowEnergy.setDelegate(self);
        try {
            BluetoothLowEnergy.registerProfile({
                :uuid => _serviceUuid,
                :characteristics => [
                    {:uuid => _notifyUuid, :descriptors => [BluetoothLowEnergy.cccdUuid()]},
                    {:uuid => _writeUuid}
                ]
            });
        } catch (e) {
            // Registered by an earlier instance of the field in this session.
            startScan();
        }
    }

    function getState() as Number {
        return _state;
    }

    function sendStart() as Void {
        if (!_ready) {
            return;
        }
        _pending.add(WalkingPadProtocol.startCommand());
        flush(System.getTimer());
    }

    // A stop replaces anything still queued.
    function sendStop() as Void {
        if (!_ready) {
            return;
        }
        _pending = [WalkingPadProtocol.stopCommand()];
        flush(System.getTimer());
    }

    function tick(nowMs as Number) as Void {
        if (_state == LinkState.ERROR) {
            if (nowMs - _errorSinceMs >= ERROR_HOLD_MS) {
                startScan();
            }
            return;
        }
        if (_device == null) {
            return;
        }
        if (!_ready) {
            if (_phaseStartMs != null && nowMs - _phaseStartMs > CONNECT_TIMEOUT_MS) {
                enterError(nowMs);
            }
            return;
        }
        var lastData = _lastPacketMs != null ? _lastPacketMs : _phaseStartMs;
        if (lastData != null && nowMs - lastData > NO_DATA_TIMEOUT_MS) {
            enterError(nowMs);
            return;
        }
        if (_busySinceMs != null && nowMs - _busySinceMs >= BUSY_TIMEOUT_MS) {
            _busySinceMs = null;
        }
        if (_pending.size() == 0) {
            _pending.add(WalkingPadProtocol.statusQuery());
        }
        flush(nowMs);
    }

    function onProfileRegister(uuid as BluetoothLowEnergy.Uuid, status as BluetoothLowEnergy.Status) as Void {
        if (status == BluetoothLowEnergy.STATUS_SUCCESS) {
            startScan();
        } else {
            enterError(System.getTimer());
        }
    }

    function onScanResults(scanResults as BluetoothLowEnergy.Iterator) as Void {
        if (_device != null || _state != LinkState.SEARCHING) {
            return;
        }
        for (var r = scanResults.next(); r != null; r = scanResults.next()) {
            var result = r as BluetoothLowEnergy.ScanResult;
            if (advertisesTreadmill(result)) {
                BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_OFF);
                try {
                    _device = BluetoothLowEnergy.pairDevice(result);
                    _phaseStartMs = System.getTimer();
                } catch (e) {
                    enterError(System.getTimer());
                }
                return;
            }
        }
    }

    function onConnectedStateChanged(device as BluetoothLowEnergy.Device,
            state as BluetoothLowEnergy.ConnectionState) as Void {
        var now = System.getTimer();
        if (state != BluetoothLowEnergy.CONNECTION_STATE_CONNECTED) {
            enterError(now);
            return;
        }
        var service = device.getService(_serviceUuid);
        if (service == null) {
            enterError(now);
            return;
        }
        var notifyChar = service.getCharacteristic(_notifyUuid);
        _writeChar = service.getCharacteristic(_writeUuid);
        var cccd = notifyChar != null ? notifyChar.getDescriptor(BluetoothLowEnergy.cccdUuid()) : null;
        if (cccd == null || _writeChar == null) {
            enterError(now);
            return;
        }
        _phaseStartMs = now;
        try {
            cccd.requestWrite([0x01, 0x00]b);
            _busySinceMs = now;
        } catch (e) {
            enterError(now);
        }
    }

    function onDescriptorWrite(descriptor as BluetoothLowEnergy.Descriptor,
            status as BluetoothLowEnergy.Status) as Void {
        _busySinceMs = null;
        if (status == BluetoothLowEnergy.STATUS_SUCCESS) {
            _ready = true;
            _phaseStartMs = System.getTimer();
        } else {
            enterError(System.getTimer());
        }
    }

    function onCharacteristicWrite(characteristic as BluetoothLowEnergy.Characteristic,
            status as BluetoothLowEnergy.Status) as Void {
        _busySinceMs = null;
    }

    function onCharacteristicChanged(characteristic as BluetoothLowEnergy.Characteristic,
            value as ByteArray) as Void {
        if (_state == LinkState.ERROR || !characteristic.getUuid().equals(_notifyUuid)) {
            return;
        }
        var status = WalkingPadProtocol.parseStatus(value);
        if (status == null) {
            return;
        }
        _state = LinkState.CONNECTED;
        _lastPacketMs = System.getTimer();
        _onStatus.invoke(status);
    }

    hidden function flush(nowMs as Number) as Void {
        if (_busySinceMs != null || _pending.size() == 0 || _writeChar == null) {
            return;
        }
        var bytes = _pending[0];
        _pending = _pending.slice(1, null);
        try {
            _writeChar.requestWrite(bytes, _writeOptions);
            _busySinceMs = nowMs;
        } catch (e) {
            enterError(nowMs);
        }
    }

    hidden function advertisesTreadmill(result as BluetoothLowEnergy.ScanResult) as Boolean {
        var uuids = result.getServiceUuids();
        for (var u = uuids.next(); u != null; u = uuids.next()) {
            if ((u as BluetoothLowEnergy.Uuid).equals(_serviceUuid)) {
                return true;
            }
        }
        return false;
    }

    hidden function startScan() as Void {
        _state = LinkState.SEARCHING;
        _device = null;
        _writeChar = null;
        _ready = false;
        _busySinceMs = null;
        _pending = [];
        _phaseStartMs = null;
        _lastPacketMs = null;
        BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_SCANNING);
    }

    // Idempotent: unpairing below triggers a disconnect callback that lands here again.
    hidden function enterError(nowMs as Number) as Void {
        if (_state == LinkState.ERROR) {
            return;
        }
        _state = LinkState.ERROR;
        _errorSinceMs = nowMs;
        _ready = false;
        _busySinceMs = null;
        _pending = [];
        _writeChar = null;
        BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_OFF);
        var device = _device;
        _device = null;
        if (device != null) {
            try {
                BluetoothLowEnergy.unpairDevice(device);
            } catch (e) {
                // Already gone; nothing else to release.
            }
        }
    }
}
```

If Step 1 selected a different write-type constant, change the `_writeOptions` line accordingly.

- [ ] **Step 3: Build**

Run: `make build && make test`
Expected: release BUILD SUCCESSFUL (the class compiles even though the gate view does not use it yet); all unit tests still PASS. Fix any type-checker errors with explicit casts (`as Type`), not by lowering the type-check level.

- [ ] **Step 4: Commit**

```bash
git add source/TreadmillLink.mc
git commit -m "Add BLE link to the treadmill"
```

---

### Task 7: TreadmillView, DemoLink and resources

**Files:**
- Create: `source/DemoLink.mc`, `resources/properties.xml`, `resources/settings.xml`, `resources/fit_contributions.xml`
- Modify: `source/TreadmillView.mc` (full replacement), `resources/strings/strings.xml`, `resources-rus/strings/strings.xml`
- Delete: `source/GateScanner.mc`

**Interfaces:**
- Consumes: everything above.
- Produces: final `TreadmillView`; `DemoLink` implementing the link interface.

- [ ] **Step 1: Strings, properties, settings, FIT resources**

`resources/strings/strings.xml`:
```xml
<strings>
    <string id="AppName">Treadmill</string>
    <string id="StatusSearching">Searching...</string>
    <string id="StatusConnected">Connected</string>
    <string id="StatusError">Link error</string>
    <string id="StepsLabel">steps</string>
    <string id="ControlBeltTitle">Start/stop the belt with the activity timer</string>
    <string id="FitSpeedLabel">Treadmill speed</string>
    <string id="FitSpeedUnits">km/h</string>
    <string id="FitDistLabel">Treadmill distance</string>
    <string id="FitDistUnits">km</string>
    <string id="FitStepsLabel">Treadmill steps</string>
    <string id="FitStepsUnits">steps</string>
</strings>
```

`resources-rus/strings/strings.xml`:
```xml
<strings>
    <string id="AppName">Дорожка</string>
    <string id="StatusSearching">Поиск дорожки...</string>
    <string id="StatusConnected">Подключено</string>
    <string id="StatusError">Ошибка связи</string>
    <string id="StepsLabel">шаг.</string>
    <string id="ControlBeltTitle">Запуск/остановка ленты вместе с таймером</string>
    <string id="FitSpeedLabel">Скорость дорожки</string>
    <string id="FitSpeedUnits">км/ч</string>
    <string id="FitDistLabel">Дистанция дорожки</string>
    <string id="FitDistUnits">км</string>
    <string id="FitStepsLabel">Шаги дорожки</string>
    <string id="FitStepsUnits">шаги</string>
</strings>
```

`resources/properties.xml`:
```xml
<properties>
    <property id="controlBelt" type="boolean">false</property>
</properties>
```

`resources/settings.xml`:
```xml
<settings>
    <setting propertyKey="@Properties.controlBelt" title="@Strings.ControlBeltTitle">
        <settingConfig type="boolean"/>
    </setting>
</settings>
```

`resources/fit_contributions.xml`:
```xml
<fitContributions>
    <fitField id="0" displayInChart="true" displayInActivityLaps="false" displayInActivitySummary="false"
        sortOrder="0" precision="1" chartTitle="@Strings.FitSpeedLabel" dataLabel="@Strings.FitSpeedLabel"
        unitLabel="@Strings.FitSpeedUnits" fillColor="#000000"/>
    <fitField id="1" displayInChart="false" displayInActivityLaps="false" displayInActivitySummary="true"
        sortOrder="1" precision="2" dataLabel="@Strings.FitDistLabel" unitLabel="@Strings.FitDistUnits"/>
    <fitField id="2" displayInChart="false" displayInActivityLaps="false" displayInActivitySummary="true"
        sortOrder="2" precision="0" dataLabel="@Strings.FitStepsLabel" unitLabel="@Strings.FitStepsUnits"/>
</fitContributions>
```

- [ ] **Step 2: DemoLink**

`source/DemoLink.mc`:
```monkeyc
import Toybox.Lang;
import Toybox.System;

// Simulator stand-in for TreadmillLink: a 70 s loop of 5 s searching,
// 55 s connected at 4.5 km/h, 10 s link error. The treadmill keeps
// counting during the error, like the real one does.
(:debug)
class DemoLink {
    const CYCLE_S = 70;
    const SEARCH_END_S = 5;
    const CONNECTED_END_S = 60;
    const SPEED_TENTHS = 45;
    const STEPS_PER_S = 1.8;

    hidden var _onStatus as Method;
    hidden var _state as Number = LinkState.SEARCHING;
    hidden var _belt as Number = WalkingPadProtocol.BELT_RUNNING;
    hidden var _startMs as Number? = null;
    hidden var _lastMs as Number? = null;
    hidden var _timeS as Float = 0.0;
    hidden var _distM as Float = 0.0;
    hidden var _steps as Float = 0.0;

    function initialize(onStatus as Method) {
        _onStatus = onStatus;
    }

    function start() as Void {
    }

    function getState() as Number {
        return _state;
    }

    function sendStart() as Void {
        System.println("demo: start belt");
        _belt = WalkingPadProtocol.BELT_RUNNING;
    }

    function sendStop() as Void {
        System.println("demo: stop belt");
        _belt = WalkingPadProtocol.BELT_STOPPED;
    }

    function tick(nowMs as Number) as Void {
        if (_startMs == null) {
            _startMs = nowMs;
        }
        if (_lastMs != null && _belt == WalkingPadProtocol.BELT_RUNNING) {
            var dt = (nowMs - _lastMs) / 1000.0;
            _timeS += dt;
            _distM += SPEED_TENTHS / 36.0 * dt;
            _steps += STEPS_PER_S * dt;
        }
        _lastMs = nowMs;

        var phase = ((nowMs - _startMs) / 1000) % CYCLE_S;
        if (phase < SEARCH_END_S) {
            _state = LinkState.SEARCHING;
        } else if (phase < CONNECTED_END_S) {
            _state = LinkState.CONNECTED;
            var speed = _belt == WalkingPadProtocol.BELT_RUNNING ? SPEED_TENTHS : 0;
            var packet = WalkingPadProtocol.buildStatusPacket(_belt, speed,
                _timeS.toNumber(), (_distM / 10).toNumber(), _steps.toNumber());
            var status = WalkingPadProtocol.parseStatus(packet);
            if (status != null) {
                _onStatus.invoke(status);
            }
        } else {
            _state = LinkState.ERROR;
        }
    }
}
```

- [ ] **Step 3: Final TreadmillView; delete the gate scanner**

Run: `git rm source/GateScanner.mc`

`source/TreadmillView.mc`:
```monkeyc
import Toybox.Activity;
import Toybox.Application;
import Toybox.FitContributor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

class TreadmillView extends WatchUi.DataField {
    const CONNECTED_BANNER_MS = 3000;
    const TALL_MIN_HEIGHT = 90;
    const JUSTIFY = Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER;

    hidden var _acc as SessionAccumulator;
    hidden var _link;
    hidden var _belt as BeltController;
    hidden var _speedField as FitContributor.Field;
    hidden var _distField as FitContributor.Field;
    hidden var _stepsField as FitContributor.Field;
    hidden var _prevLinkState as Number = LinkState.SEARCHING;
    hidden var _connectedSinceMs as Number? = null;
    hidden var _txtSearching as String;
    hidden var _txtConnected as String;
    hidden var _txtError as String;
    hidden var _txtSteps as String;

    function initialize() {
        DataField.initialize();
        _acc = new SessionAccumulator();
        _link = makeLink();
        _belt = new BeltController(_link);
        _speedField = createField("treadmill_speed", 0, FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "km/h"});
        _distField = createField("treadmill_distance", 1, FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_SESSION, :units => "km"});
        _stepsField = createField("treadmill_steps", 2, FitContributor.DATA_TYPE_UINT32,
            {:mesgType => FitContributor.MESG_TYPE_SESSION, :units => "steps"});
        _txtSearching = WatchUi.loadResource(Rez.Strings.StatusSearching) as String;
        _txtConnected = WatchUi.loadResource(Rez.Strings.StatusConnected) as String;
        _txtError = WatchUi.loadResource(Rez.Strings.StatusError) as String;
        _txtSteps = WatchUi.loadResource(Rez.Strings.StepsLabel) as String;
        _link.start();
    }

    (:debug)
    hidden function makeLink() {
        return new DemoLink(method(:onStatus));
    }

    (:release)
    hidden function makeLink() {
        return new TreadmillLink(method(:onStatus));
    }

    function onStatus(status as Dictionary) as Void {
        _acc.onStatus(status, System.getTimer());
    }

    function compute(info as Activity.Info) as Numeric or Duration or String or Null {
        var now = System.getTimer();
        _link.tick(now);
        _acc.tick(now);
        var linkState = _link.getState() as Number;
        if (linkState == LinkState.CONNECTED && _prevLinkState != LinkState.CONNECTED) {
            _connectedSinceMs = now;
        }
        _prevLinkState = linkState;
        _belt.tick(linkState, _acc.getBeltState(now), now);

        var speed = _acc.getSpeedMps(now);
        _speedField.setData(speed == null ? 0.0 : speed * Fmt.KMH_PER_MPS);
        _distField.setData(_acc.getTotalDistM() / Fmt.M_PER_KM);
        _stepsField.setData(_acc.getTotalSteps());
        return null;
    }

    function onTimerStart() as Void {
        handleRun();
    }

    function onTimerResume() as Void {
        handleRun();
    }

    function onTimerPause() as Void {
        handleHalt();
    }

    function onTimerStop() as Void {
        handleHalt();
    }

    function onTimerReset() as Void {
        _acc.reset();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var bg = getBackgroundColor();
        var fg = bg == Graphics.COLOR_BLACK ? Graphics.COLOR_WHITE : Graphics.COLOR_BLACK;
        dc.setColor(fg, bg);
        dc.clear();
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);

        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var tall = h >= TALL_MIN_HEIGHT;
        var now = System.getTimer();
        var metric = System.getDeviceSettings().distanceUnits == System.UNIT_METRIC;
        var dist = Fmt.distance(_acc.getDisplayDistM(), metric);
        var totals = dist + " | " + _acc.getTotalSteps().toString();

        var status = statusText(now);
        if (status != null) {
            if (tall && _acc.hasData()) {
                drawLine(dc, cx, h * 0.38, w, Graphics.FONT_SMALL, status);
                drawLine(dc, cx, h * 0.68, w, Graphics.FONT_TINY, totals);
            } else {
                drawLine(dc, cx, h / 2, w, tall ? Graphics.FONT_SMALL : Graphics.FONT_TINY, status);
            }
            return;
        }

        var speed = Fmt.speed(_acc.getSpeedMps(now), metric) + " " + Fmt.speedUnit(metric);
        if (tall) {
            drawLine(dc, cx, h * 0.24, w, Graphics.FONT_MEDIUM, speed);
            drawLine(dc, cx, h * 0.52, w, Graphics.FONT_SMALL, dist + " " + Fmt.distanceUnit(metric));
            drawLine(dc, cx, h * 0.78, w, Graphics.FONT_SMALL, _acc.getTotalSteps().toString() + " " + _txtSteps);
        } else {
            drawLine(dc, cx, h * 0.3, w, Graphics.FONT_TINY, speed);
            drawLine(dc, cx, h * 0.72, w, Graphics.FONT_TINY, totals);
        }
    }

    hidden function handleRun() as Void {
        var now = System.getTimer();
        _acc.setTimerRunning(true);
        _belt.onRun(controlBelt(), _link.getState() as Number, _acc.getBeltState(now));
    }

    hidden function handleHalt() as Void {
        var now = System.getTimer();
        _acc.setTimerRunning(false);
        _belt.onHalt(controlBelt(), _link.getState() as Number, _acc.getBeltState(now), now);
    }

    hidden function controlBelt() as Boolean {
        return Application.Properties.getValue("controlBelt") == true;
    }

    hidden function statusText(nowMs as Number) as String? {
        var state = _link.getState() as Number;
        if (state == LinkState.ERROR) {
            return _txtError;
        }
        if (state == LinkState.SEARCHING) {
            return _txtSearching;
        }
        if (_connectedSinceMs != null && nowMs - _connectedSinceMs < CONNECTED_BANNER_MS) {
            return _txtConnected;
        }
        return null;
    }

    // Draws centered text, stepping the font down until it fits the field width.
    hidden function drawLine(dc as Graphics.Dc, x as Numeric, y as Numeric, maxWidth as Number,
            font as Graphics.FontDefinition, text as String) as Void {
        var fonts = [Graphics.FONT_MEDIUM, Graphics.FONT_SMALL, Graphics.FONT_TINY, Graphics.FONT_XTINY];
        var i = fonts.indexOf(font);
        while (i < fonts.size() - 1 && dc.getTextWidthInPixels(text, fonts[i]) > maxWidth - 4) {
            i += 1;
        }
        dc.drawText(x, y, fonts[i], text, JUSTIFY);
    }
}
```

- [ ] **Step 4: Build and test**

Run: `make build && make test`
Expected: release BUILD SUCCESSFUL, all unit tests PASS.

- [ ] **Step 5: Simulator demo check**

Run: `make demo` (simulator already running).
In the simulator: start the activity timer (Simulation → Timer / Activity Data controls), switch the data field layout through the full-screen, half and third sizes, and let the 70 s demo cycle run. Check:
- "Searching..." for 5 s, "Connected" for 3 s, then speed `4.5 km/h`, distance growing smoothly, steps growing ~1.8/s;
- at 60 s "Link error" with the last totals below it (tall layouts), totals continue after reconnect;
- white-on-black and black-on-white both readable (toggle the device background/theme if available);
- set `controlBelt=true` (File → Edit Application.Properties / settings editor), pause the timer → console prints `demo: stop belt`, speed shows `0.0`; resume → `demo: start belt`;
- set the device language to Russian → «Поиск дорожки...», «Подключено», «Ошибка связи», «шаг.» render without missing glyphs;
- memory viewer: peak memory well below the data field limit from Task 1 Step 2.
Fix any layout overlap by adjusting the `h * …` factors in `onUpdate` only.

- [ ] **Step 6: Commit**

```bash
git add -A source resources resources-rus
git commit -m "Add data field view, FIT fields, settings and simulator demo"
```

---

### Task 8: README and release

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

`README.md`:
````markdown
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
```

Only the release build (`make build`) talks to the real treadmill; debug builds
use the simulated one.

## Install

1. Connect the watch by USB and copy `bin/TreadmillField.prg` to `GARMIN/APPS/`.
2. On the watch: Treadmill Walk → settings → data screens → add the Connect IQ
   field "Treadmill".
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
````

- [ ] **Step 2: Final build and tests**

Run: `make clean && make build && make test`
Expected: BUILD SUCCESSFUL, all tests PASS.

- [ ] **Step 3: Commit and push**

```bash
git add README.md
git commit -m "Add README with build, install and on-watch checklist"
git push
```

---

### Task 9: On-watch acceptance (with the user)

**Files:** fixes only where a check fails.

- [ ] **Step 1: Sideload the release build (user action)**

User copies `bin/TreadmillField.prg` to `GARMIN/APPS/`, adds the field to "Treadmill Walk".

- [ ] **Step 2: Walk the README on-watch checklist with the user**

Record the result of each of the 5 checks. For any failure, reproduce it (where possible with the laptop BLE scripts in the scratchpad), fix with a failing unit test first when the fault is in pure logic, rebuild, and repeat the failed check.

- [ ] **Step 3: Commit fixes and push**

```bash
git add -A
git commit -m "Fix <what failed on the watch>"
git push
```
