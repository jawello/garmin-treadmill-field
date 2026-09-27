# Treadmill Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python/Bumble daemon on the Raspberry Pi that owns the Kingsmith R1 Pro link, serves a Garmin foot pod and an FE00 bridge for the watch field, records minute step buckets, and exposes them over HTTP — plus the monorepo move of the watch field.

**Architecture:** One asyncio process. `TreadmillClient` (radio A, central) publishes parsed status to `StatusHub`; `FootPod` (radio A, peripheral) and `CiqLink` (radio B, peripheral) serve the watch; `Bridge` switches their advertising on/off with the treadmill link; `Odometer` + `SessionRecorder` + `Store` turn status into minute buckets; `api` serves them. Every BLE component takes an injected Bumble `Device`, so tests run the full flow on Bumble virtual controllers.

**Tech Stack:** Python 3.13, uv, Bumble 0.0.235, aiohttp, sqlite3, pytest + pytest-asyncio, systemd on Raspberry Pi OS Trixie.

**Spec:** `docs/superpowers/specs/2026-09-28-treadmill-bridge-design.md`

## Global Constraints

- Python `>=3.13`; dependencies via `uv` with `uv.lock` committed; Bumble pinned `bumble==0.0.235`.
- FE00 UUIDs: service `0000FE00-0000-1000-8000-00805F9B34FB`, notify `0000FE01-…`, write `0000FE02-…`.
- Commands: query `f7 a2 00 00 a2 fd`, start `f7 a2 04 01 a7 fd`, stop `f7 a2 01 00 a3 fd`. Only these three may ever be written to the treadmill.
- Belt states: `0` stopped, `1` running, `3` stopping, `6..9` countdown.
- Poll 1 s; ≥ 0.4 s between treadmill writes; link recreated after 5 s without a valid status; reconnect backoff 1 → 2 → 5 → 10 s then every 10 s.
- Watch-facing advertising only while the treadmill link is up; 30 s grace after the link drops, then disconnect watch links (never the treadmill link) and stop advertising.
- Foot pod advert: Flags `0x06`, complete 16-bit UUIDs `0x1814`, Appearance `0x0442`, scan-response name "Treadmill Pod", 100 ms; RSC Feature `0x0002`; Measurement flags `0x02`; speed ×256 m/s; cadence = steps/min ÷ 2; distance in 0.1 m; Battery 100; DIS manufacturer "treadmill-bridge".
- `hold_speed_during_start` default `false`: countdown or < 8 s after a start → report 1.0 km/h instead of 0.
- Field bridge advert: Flags `0x06`, UUID `FE00`, name "TM-Bridge"; query answered with the cached raw packet only if ≤ 3 s old.
- Pairing: Just Works + bonding (NoInputNoOutput) on both radios; keys `/var/lib/treadmill-bridge/keys.json`.
- Buckets: UTC minute, `start`, `end = start + 60`, `steps`, `distance_m`, `active_seconds`, `version`; nothing recorded until the clock is synchronised; sessions split by > 120 s idle; 90-day retention.
- API: port 8080, `Authorization: Bearer <token>`, `/api/v1/status`, `/api/v1/steps?since&until` (closed buckets only), `/api/v1/sessions?since`.
- Radios mapped by bus: UART = radio A, USB = radio B; no radio B → run without the field bridge and report it.
- Service user `treadmill`, `AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW`, `Restart=always`, `bluetoothd` disabled.
- Watch field: moves to `watch-field/`; `controlBelt` default `true`; no other field logic changes.
- Commits: short English imperative subject, no ticket ID.

## Review Focus

1. The treadmill resets its counters mid-walk (belt stopped and restarted from the remote) → totals keep growing, no drop or jump. → Task 3 `test_counter_reset_continues_totals`.
2. The Pi boots without network time → no buckets dated 1970; recording starts once the clock is synced. → Task 4 `test_nothing_recorded_until_time_synced`.
3. No USB adapter (today's reality) → the daemon still runs treadmill + foot pod and reports the field bridge as absent. → Task 10 `test_runs_without_radio_b`.
4. Treadmill drops while the watch holds the foot pod → after 30 s only watch links are closed; the treadmill central link on the same radio is never touched. → Task 8 `test_grace_then_stop_only_watch_links`.
5. API called with a missing/wrong token or a non-numeric `since` → 401 / 400, never a 500. → Task 9 `test_rejects_bad_token_and_bad_params`.

## File Structure

```
watch-field/                       (moved from repo root: manifest.xml, monkey.jungle, Makefile,
                                    source/, test/, resources*/, tools/mtp_send.py, README.md)
bridge/
├── pyproject.toml                 package, deps, console script, pytest config
├── uv.lock
├── Makefile                       test, deploy
├── README.md                      install, operate, acceptance checklist
├── deploy/
│   ├── treadmill-bridge.service   systemd unit
│   ├── prepare-radios.sh          power controllers down for Bumble
│   ├── install.sh                 idempotent installer, runs on the Pi as root
│   └── config.example.toml
├── src/treadmill_bridge/
│   ├── __init__.py
│   ├── protocol.py                FE00 commands, Status, parsing
│   ├── hub.py                     StatusHub
│   ├── odometer.py                monotonic totals, smoothing, cadence
│   ├── storage.py                 SQLite Store
│   ├── sessions.py                SessionRecorder
│   ├── ble.py                     shared Bumble helpers
│   ├── footpod.py                 RSC foot pod
│   ├── treadmill.py               TreadmillClient
│   ├── ciq_link.py                FE00 server for the field
│   ├── bridge.py                  advertising lifecycle
│   ├── api.py                     aiohttp app
│   ├── radios.py                  controller discovery by bus
│   ├── config.py                  Config + State
│   ├── app.py                     component wiring (shared by main and tests)
│   └── main.py                    entry point
└── tests/
    ├── conftest.py                pytest-asyncio mode, virtual device factory
    ├── fixtures.py                captured treadmill packets
    ├── fakes.py                   FakeTreadmill, FakeWatch
    └── test_*.py
.github/workflows/bridge.yml       CI: pytest for bridge/
README.md                          system overview
```

Interface summary (all later tasks rely on these exact names):

- `protocol`: `SERVICE_UUID`, `NOTIFY_UUID`, `WRITE_UUID`, `QUERY`, `START`, `STOP`, `BELT_STOPPED`, `BELT_RUNNING`, `BELT_STOPPING`, `is_countdown(state) -> bool`, `Status(state, speed_tenths, time_s, dist_tens, steps, raw)` with `.running`, `.speed_mps`, `parse_status(data) -> Status | None`, `build_status(state, speed_tenths, time_s, dist_tens, steps) -> bytes`, `command_kind(data) -> "query" | "start" | "stop" | None`.
- `hub.StatusHub(clock)`: `.latest`, `.latest_at`, `.link_up`, `.link_changed_at`, `.last_start_at`, `on_status(cb)`, `on_link(cb)`, `publish(status)`, `set_link(up)`, `note_start()`, `fresh_status(max_age) -> Status | None`.
- `odometer.Odometer()`: `.steps_total`, `.distance_m`, `update(status, now) -> (steps_delta, distance_delta_m)`, `smoothed_distance_m(now)`, `cadence_spm(now)`, `stall()`.
- `storage.Store(path)`: `add_to_bucket(start, steps, distance_m, active_seconds, version)`, `buckets(since, until) -> list[dict]`, `save_session(start, end, steps, distance_m)`, `sessions(since) -> list[dict]`, `purge(before)`, `close()`.
- `sessions.SessionRecorder(store, time_synced, idle_gap_s=120)`: `record(status, steps_delta, distance_delta_m, wall_now)`, `flush(wall_now)`.
- `ble`: `peripheral_connections(device)`, `enable_just_works(device)`, `advertising_payload(entries) -> bytes`.
- `footpod`: `rsc_measurement(speed_mps, cadence_strides, distance_m) -> bytes`, `pod_speed_mps(status, now, last_start_at, hold) -> float`, `FootPod(device, hub, odometer, own_address_type, hold_speed_during_start=False, clock=time.monotonic, name="Treadmill Pod")` with `install()`, `start()`, `stop()`, `tick(now)`, `.advertising`.
- `treadmill.TreadmillClient(device, hub, address, own_address_type, on_address=None, clock=time.monotonic, poll_interval=1.0, write_gap=0.4, stale_after=5.0, backoff=(1.0, 2.0, 5.0, 10.0), scan_timeout=10.0, connect_timeout=10.0)` with `run()`, `send_command(cmd)`; `parse_address(text) -> Address`.
- `ciq_link.CiqLink(device, hub, send_command, own_address_type, clock=time.monotonic, fresh_s=3.0, name="TM-Bridge")` with `install()`, `start()`, `stop()`, `.advertising`.
- `bridge.Bridge(hub, footpod, ciq, clock=time.monotonic, grace_s=30.0)` with `tick()`.
- `api.make_app(store, status_snapshot, token, wall_clock=time.time) -> web.Application`.
- `radios.find_controllers(sys_root) -> dict[str, int]`.
- `config.Config`, `config.load_config(path)`, `config.State(path)` with `.treadmill_address`, `save_address(addr)`.
- `app.Components` and `app.build(dev_a, dev_b, config, store, state, own_address_type, time_synced, timings) -> Components`.

---

### Task 1: Monorepo layout, field default, bridge skeleton and CI

**Files:**
- Move: repo-root watch field files → `watch-field/`
- Modify: `watch-field/resources/properties.xml`, `watch-field/Makefile` (tools path unchanged, relative)
- Create: `README.md` (root), `bridge/pyproject.toml`, `bridge/src/treadmill_bridge/__init__.py`, `bridge/tests/conftest.py`, `bridge/tests/test_smoke.py`, `.github/workflows/bridge.yml`, `.gitignore` (root, merged)

**Interfaces:** Produces the `bridge/` package root and test runner used by every later task.

- [ ] **Step 1: Move the watch field**

```bash
cd /home/akhadiev/Documents/personal/garmin-treadmill-field
mkdir -p watch-field
git mv manifest.xml monkey.jungle Makefile source test resources resources-rus tools README.md watch-field/
git mv .gitignore watch-field/.gitignore
```

- [ ] **Step 2: Default `controlBelt` to true**

In `watch-field/resources/properties.xml` change the property to:
```xml
    <property id="controlBelt" type="boolean">true</property>
```

- [ ] **Step 3: Verify the field still builds and tests pass**

Run: `make -C watch-field build && make -C watch-field test` (simulator must be running: `make -C watch-field sim`)
Expected: `BUILD SUCCESSFUL`, `PASSED (passed=40, failed=0, errors=0)`.

- [ ] **Step 4: Root README and .gitignore**

`README.md`:
```markdown
# Kingsmith R1 Pro ↔ Garmin Instinct 3

Walk on a Kingsmith R1 Pro treadmill and get accurate data in Garmin and Health Connect
with minimal manual steps.

| Part | What it does |
|---|---|
| [`watch-field/`](watch-field/README.md) | Connect IQ data field: treadmill speed, distance, steps on the watch, FIT fields, belt start/stop with the activity timer |
| [`bridge/`](bridge/README.md) | Raspberry Pi daemon: owns the treadmill link, acts as a Garmin foot pod, bridges FE00 for the field, records minute step buckets, HTTP API |
| `android/` | planned: syncs step buckets from the bridge into Health Connect |

Design documents: [`docs/superpowers/specs/`](docs/superpowers/specs/).
```

`.gitignore` (root):
```
bin/
*.der
*.pem
__pycache__/
.venv/
.pytest_cache/
*.db
```

- [ ] **Step 5: Bridge package skeleton**

`bridge/pyproject.toml`:
```toml
[project]
name = "treadmill-bridge"
version = "0.1.0"
description = "Kingsmith R1 Pro to Garmin bridge (foot pod, FE00 relay, step buckets)"
requires-python = ">=3.13"
dependencies = [
    "bumble==0.0.235",
    "aiohttp>=3.10",
]

[project.scripts]
treadmill-bridge = "treadmill_bridge.main:cli"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/treadmill_bridge"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
```

`bridge/src/treadmill_bridge/__init__.py`:
```python
"""Kingsmith R1 Pro to Garmin bridge."""
```

`bridge/tests/conftest.py`:
```python
import logging

logging.getLogger("bumble").setLevel(logging.WARNING)
```

`bridge/tests/test_smoke.py`:
```python
import treadmill_bridge


def test_package_imports():
    assert treadmill_bridge.__doc__
```

- [ ] **Step 6: Lock and run**

Run: `cd bridge && uv lock && uv run pytest -q`
Expected: `1 passed`.

- [ ] **Step 7: CI workflow**

`.github/workflows/bridge.yml`:
```yaml
name: bridge
on:
  push:
    paths: ["bridge/**", ".github/workflows/bridge.yml"]
  pull_request:
    paths: ["bridge/**", ".github/workflows/bridge.yml"]
jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: bridge
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - run: uv run pytest -q
```

- [ ] **Step 8: Commit and push, check CI**

```bash
git add -A
git commit -m "Move the watch field into watch-field/ and add the bridge skeleton"
git push
gh run watch --exit-status $(gh run list --workflow bridge.yml --limit 1 --json databaseId -q '.[0].databaseId')
```
Expected: CI job `test` succeeds.

---

### Task 2: FE00 protocol

**Files:**
- Create: `bridge/src/treadmill_bridge/protocol.py`, `bridge/tests/fixtures.py`, `bridge/tests/test_protocol.py`

**Interfaces:** Produces everything listed under `protocol` in the interface summary.

- [ ] **Step 1: Fixtures (real packets captured from the R1 Pro)**

`bridge/tests/fixtures.py`:
```python
"""Status packets captured from the user's R1 Pro on 2026-09-25."""

STOPPED = bytes.fromhex("f8a200000100000000000000000000000000a3fd")
WALKING = bytes.fromhex("f8a2012d01000082000010000000e60000000049fd")  # 4.5 km/h, 130 s, 160 m, 230 steps
BUTTON = bytes.fromhex("f8a201320100002a000004000045000002004bfd")  # remote button byte set
COUNTDOWN = bytes.fromhex("f8a2090001000000000000000000000003" "00affd")
STOPPING = bytes.fromhex("f8a20307010000" "0e" "000000" "00000e" "00000000" "c9fd")
```

- [ ] **Step 2: Failing tests**

`bridge/tests/test_protocol.py`:
```python
from treadmill_bridge import protocol as p
from tests import fixtures as f


def test_fixture_lengths():
    for pkt in (f.STOPPED, f.WALKING, f.BUTTON, f.COUNTDOWN, f.STOPPING):
        assert len(pkt) == 20


def test_commands():
    assert p.QUERY.hex() == "f7a20000a2fd"
    assert p.START.hex() == "f7a20401a7fd"
    assert p.STOP.hex() == "f7a20100a3fd"
    assert p.command_kind(p.QUERY) == "query"
    assert p.command_kind(p.START) == "start"
    assert p.command_kind(p.STOP) == "stop"
    assert p.command_kind(bytes.fromhex("f7a20102a5fd")) is None


def test_parses_walking():
    s = p.parse_status(f.WALKING)
    assert (s.state, s.speed_tenths, s.time_s, s.dist_tens, s.steps) == (1, 45, 130, 16, 230)
    assert s.running and abs(s.speed_mps - 1.25) < 1e-9
    assert s.raw == f.WALKING


def test_parses_other_states():
    assert p.parse_status(f.STOPPED).state == p.BELT_STOPPED
    b = p.parse_status(f.BUTTON)
    assert (b.speed_tenths, b.time_s, b.dist_tens, b.steps) == (50, 42, 4, 69)
    c = p.parse_status(f.COUNTDOWN)
    assert c.state == 9 and p.is_countdown(c.state) and c.speed_mps == 0.0
    s = p.parse_status(f.STOPPING)
    assert (s.state, s.speed_tenths, s.steps) == (p.BELT_STOPPING, 7, 14)
    assert s.speed_mps == 0.0


def test_countdown_range():
    assert [p.is_countdown(x) for x in (5, 6, 9, 10, 1)] == [False, True, True, False, False]


def test_rejects_malformed():
    bad = bytearray(f.WALKING)
    bad[18] ^= 1
    assert p.parse_status(bytes(bad)) is None
    wrong_type = bytearray(f.WALKING)
    wrong_type[1] = 0xA7
    assert p.parse_status(bytes(wrong_type)) is None
    assert p.parse_status(f.WALKING[:10]) is None
    assert p.parse_status(b"") is None
    no_footer = bytearray(f.WALKING)
    no_footer[-1] = 0
    assert p.parse_status(bytes(no_footer)) is None


def test_build_round_trip_and_large_counters():
    assert p.build_status(1, 45, 130, 16, 230) == f.WALKING
    s = p.parse_status(p.build_status(1, 45, 0x010000, 0x00ABCD, 0x012345))
    assert (s.time_s, s.dist_tens, s.steps) == (65536, 43981, 74565)
```

`bridge/tests/__init__.py`: empty file (so `from tests import fixtures` works).

- [ ] **Step 3: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_protocol.py -q`
Expected: FAIL — `ImportError: cannot import name 'protocol'`.

- [ ] **Step 4: Implement**

`bridge/src/treadmill_bridge/protocol.py`:
```python
"""Kingsmith/WalkingPad FE00 protocol, verified on an R1 Pro."""

from __future__ import annotations

from dataclasses import dataclass

SERVICE_UUID = "0000FE00-0000-1000-8000-00805F9B34FB"
NOTIFY_UUID = "0000FE01-0000-1000-8000-00805F9B34FB"
WRITE_UUID = "0000FE02-0000-1000-8000-00805F9B34FB"

QUERY = bytes.fromhex("f7a20000a2fd")
START = bytes.fromhex("f7a20401a7fd")
STOP = bytes.fromhex("f7a20100a3fd")

BELT_STOPPED = 0
BELT_RUNNING = 1
BELT_STOPPING = 3
MIN_STATUS_LENGTH = 19

_COMMANDS = {QUERY: "query", START: "start", STOP: "stop"}


@dataclass(frozen=True)
class Status:
    state: int
    speed_tenths: int
    time_s: int
    dist_tens: int
    steps: int
    raw: bytes

    @property
    def running(self) -> bool:
        return self.state == BELT_RUNNING

    @property
    def speed_mps(self) -> float:
        return self.speed_tenths / 36.0 if self.running else 0.0


def is_countdown(state: int) -> bool:
    return 6 <= state <= 9


def command_kind(data: bytes) -> str | None:
    return _COMMANDS.get(bytes(data))


def _u24(b: bytes, i: int) -> int:
    return (b[i] << 16) | (b[i + 1] << 8) | b[i + 2]


def parse_status(data: bytes) -> Status | None:
    b = bytes(data)
    n = len(b)
    if n < MIN_STATUS_LENGTH or b[0] != 0xF8 or b[1] != 0xA2 or b[-1] != 0xFD:
        return None
    if sum(b[1 : n - 2]) & 0xFF != b[n - 2]:
        return None
    return Status(b[2], b[3], _u24(b, 5), _u24(b, 8), _u24(b, 11), b)


def build_status(state: int, speed_tenths: int, time_s: int, dist_tens: int, steps: int) -> bytes:
    b = bytearray(20)
    b[0], b[1], b[2], b[3], b[4] = 0xF8, 0xA2, state, speed_tenths, 0x01
    for offset, value in ((5, time_s), (8, dist_tens), (11, steps)):
        b[offset : offset + 3] = (value & 0xFFFFFF).to_bytes(3, "big")
    b[18] = sum(b[1:18]) & 0xFF
    b[19] = 0xFD
    return bytes(b)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass (8 tests).

- [ ] **Step 6: Commit**

```bash
git add bridge
git commit -m "Add FE00 protocol parser and commands to the bridge"
```

---

### Task 3: StatusHub and Odometer

**Files:**
- Create: `bridge/src/treadmill_bridge/hub.py`, `bridge/src/treadmill_bridge/odometer.py`, `bridge/tests/test_hub.py`, `bridge/tests/test_odometer.py`

**Interfaces:** Consumes `protocol.Status`. Produces `hub.StatusHub`, `odometer.Odometer` (see summary).

- [ ] **Step 1: Failing tests**

`bridge/tests/test_hub.py`:
```python
from treadmill_bridge import protocol as p
from treadmill_bridge.hub import StatusHub
from tests import fixtures as f


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_publish_and_freshness():
    clock = Clock()
    hub = StatusHub(clock)
    seen = []
    hub.on_status(seen.append)
    status = p.parse_status(f.WALKING)
    hub.publish(status)
    assert seen == [status] and hub.latest is status and hub.latest_at == 100.0
    clock.t = 103.0
    assert hub.fresh_status(3.0) is status
    clock.t = 103.1
    assert hub.fresh_status(3.0) is None


def test_link_changes_notify_once():
    clock = Clock()
    hub = StatusHub(clock)
    changes = []
    hub.on_link(changes.append)
    hub.set_link(True)
    hub.set_link(True)
    clock.t = 110.0
    hub.set_link(False)
    assert changes == [True, False]
    assert hub.link_changed_at == 110.0


def test_note_start():
    clock = Clock()
    hub = StatusHub(clock)
    assert hub.last_start_at is None
    hub.note_start()
    assert hub.last_start_at == 100.0
```

`bridge/tests/test_odometer.py`:
```python
from treadmill_bridge import protocol as p
from treadmill_bridge.odometer import Odometer


def st(state, speed, dist_tens, steps):
    return p.parse_status(p.build_status(state, speed, 0, dist_tens, steps))


def test_first_packet_is_baseline():
    o = Odometer()
    assert o.update(st(1, 45, 16, 230), 0.0) == (0, 0.0)
    assert (o.steps_total, o.distance_m) == (0, 0.0)


def test_deltas_accumulate():
    o = Odometer()
    o.update(st(1, 45, 10, 100), 0.0)
    assert o.update(st(1, 45, 12, 130), 1.0) == (30, 20.0)
    assert (o.steps_total, o.distance_m) == (30, 20.0)


def test_counter_reset_continues_totals():
    o = Odometer()
    o.update(st(1, 45, 10, 100), 0.0)
    o.update(st(1, 45, 16, 230), 1.0)
    o.update(st(0, 0, 16, 230), 2.0)
    assert o.update(st(1, 45, 1, 5), 3.0) == (5, 10.0)
    assert (o.steps_total, o.distance_m) == (135, 70.0)


def test_smoothed_distance_capped_and_monotonic():
    o = Odometer()
    o.update(st(1, 45, 0, 0), 0.0)
    assert abs(o.smoothed_distance_m(4.0) - 5.0) < 1e-6
    assert abs(o.smoothed_distance_m(20.0) - 10.0) < 1e-6
    o.update(st(1, 45, 1, 0), 20.5)
    assert abs(o.smoothed_distance_m(20.5) - 10.0) < 1e-6
    assert abs(o.smoothed_distance_m(22.5) - 12.5) < 1e-6


def test_no_smoothing_when_stopped_or_stalled():
    o = Odometer()
    o.update(st(0, 0, 0, 0), 0.0)
    assert o.smoothed_distance_m(5.0) == 0.0
    o.update(st(1, 45, 0, 0), 5.0)
    o.stall()
    assert o.smoothed_distance_m(10.0) == 0.0


def test_cadence_over_window():
    o = Odometer()
    o.update(st(1, 45, 0, 0), 0.0)
    for i in range(1, 11):
        o.update(st(1, 45, 0, i * 2), float(i))  # 2 steps/s
    assert o.cadence_spm(10.0) == 120
    o.update(st(0, 0, 0, 20), 11.0)
    assert o.cadence_spm(11.0) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_hub.py tests/test_odometer.py -q`
Expected: FAIL — `ModuleNotFoundError: treadmill_bridge.hub`.

- [ ] **Step 3: Implement**

`bridge/src/treadmill_bridge/hub.py`:
```python
"""Latest treadmill status and link state, with listeners."""

from __future__ import annotations

import time
from collections.abc import Callable

from .protocol import Status


class StatusHub:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.latest: Status | None = None
        self.latest_at: float | None = None
        self.link_up = False
        self.link_changed_at = clock()
        self.last_start_at: float | None = None
        self._status_listeners: list[Callable[[Status], None]] = []
        self._link_listeners: list[Callable[[bool], None]] = []

    def on_status(self, listener: Callable[[Status], None]) -> None:
        self._status_listeners.append(listener)

    def on_link(self, listener: Callable[[bool], None]) -> None:
        self._link_listeners.append(listener)

    def publish(self, status: Status) -> None:
        self.latest = status
        self.latest_at = self._clock()
        for listener in self._status_listeners:
            listener(status)

    def set_link(self, up: bool) -> None:
        if up == self.link_up:
            return
        self.link_up = up
        self.link_changed_at = self._clock()
        for listener in self._link_listeners:
            listener(up)

    def note_start(self) -> None:
        self.last_start_at = self._clock()

    def fresh_status(self, max_age: float) -> Status | None:
        if self.latest is None or self.latest_at is None:
            return None
        return self.latest if self._clock() - self.latest_at <= max_age else None
```

`bridge/src/treadmill_bridge/odometer.py`:
```python
"""Monotonic treadmill totals that survive counter resets."""

from __future__ import annotations

from collections import deque

from .protocol import Status

SMOOTH_CAP_M = 10.0
CADENCE_WINDOW_S = 10.0
DIST_UNIT_M = 10.0


def _delta(raw: int, last: int) -> int:
    # A counter that went down means the treadmill started a new session from zero.
    return raw - last if raw >= last else raw


class Odometer:
    def __init__(self) -> None:
        self.steps_total = 0
        self.distance_m = 0.0
        self._last_steps: int | None = None
        self._last_dist: int | None = None
        self._speed_mps = 0.0
        self._running = False
        self._display_m = 0.0
        self._display_at: float | None = None
        self._history: deque[tuple[float, int]] = deque()

    def update(self, status: Status, now: float) -> tuple[int, float]:
        if self._last_steps is None or self._last_dist is None:
            steps, dist = 0, 0.0
        else:
            steps = _delta(status.steps, self._last_steps)
            dist = _delta(status.dist_tens, self._last_dist) * DIST_UNIT_M
        self._last_steps, self._last_dist = status.steps, status.dist_tens
        self._advance_display(now)
        self.steps_total += steps
        self.distance_m += dist
        self._display_m = max(self._display_m, self.distance_m)
        self._speed_mps = status.speed_mps
        self._running = status.running
        self._history.append((now, self.steps_total))
        while len(self._history) > 1 and self._history[1][0] <= now - CADENCE_WINDOW_S:
            self._history.popleft()
        return steps, dist

    def smoothed_distance_m(self, now: float) -> float:
        self._advance_display(now)
        return self._display_m

    def cadence_spm(self, now: float) -> int:
        if not self._running or len(self._history) < 2:
            return 0
        (t0, s0), (t1, s1) = self._history[0], self._history[-1]
        if t1 <= t0:
            return 0
        return round((s1 - s0) * 60 / (t1 - t0))

    def stall(self) -> None:
        self._running = False
        self._speed_mps = 0.0

    def _advance_display(self, now: float) -> None:
        if self._display_at is not None and self._running:
            grown = self._display_m + self._speed_mps * (now - self._display_at)
            cap = self.distance_m + SMOOTH_CAP_M
            self._display_m = max(self._display_m, min(grown, cap))
        self._display_at = now
```

- [ ] **Step 4: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge
git commit -m "Add status hub and odometer to the bridge"
```

---

### Task 4: Store and SessionRecorder

**Files:**
- Create: `bridge/src/treadmill_bridge/storage.py`, `bridge/src/treadmill_bridge/sessions.py`, `bridge/tests/test_storage.py`, `bridge/tests/test_sessions.py`

**Interfaces:** Consumes `protocol.Status`. Produces `storage.Store`, `sessions.SessionRecorder`.

- [ ] **Step 1: Failing tests**

`bridge/tests/test_storage.py`:
```python
from treadmill_bridge.storage import Store


def test_bucket_upsert_and_closed_only(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    s.add_to_bucket(600, 10, 12.5, 8.0, 601.0)
    s.add_to_bucket(600, 5, 2.5, 2.0, 650.0)
    s.add_to_bucket(660, 7, 0.0, 3.0, 665.0)
    assert s.buckets(0, 660) == [
        {"start": 600, "end": 660, "steps": 15, "distance_m": 15.0, "active_seconds": 10.0, "version": 650.0}
    ]
    assert len(s.buckets(0, 720)) == 2
    assert s.buckets(660, 720)[0]["start"] == 660


def test_sessions_and_purge(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    s.save_session(1000, 1500, 400, 300.0)
    s.save_session(1000, 1600, 500, 350.0)
    s.save_session(5000, 5100, 50, 40.0)
    assert s.sessions(0) == [
        {"start": 1000, "end": 1600, "steps": 500, "distance_m": 350.0},
        {"start": 5000, "end": 5100, "steps": 50, "distance_m": 40.0},
    ]
    assert [x["start"] for x in s.sessions(2000)] == [5000]
    s.add_to_bucket(600, 1, 1.0, 1.0, 1.0)
    s.purge(4000)
    assert s.sessions(0)[0]["start"] == 5000 and s.buckets(0, 10_000) == []
```

`bridge/tests/test_sessions.py`:
```python
from treadmill_bridge import protocol as p
from treadmill_bridge.sessions import SessionRecorder
from treadmill_bridge.storage import Store

RUN = p.parse_status(p.build_status(1, 45, 0, 0, 0))
STOP = p.parse_status(p.build_status(0, 0, 0, 0, 0))


def make(tmp_path, synced=True):
    store = Store(str(tmp_path / "s.db"))
    flag = {"synced": synced}
    return store, SessionRecorder(store, lambda: flag["synced"]), flag


def test_minute_buckets_and_rollover(tmp_path):
    store, rec, _ = make(tmp_path)
    base = 1_790_000_040.0  # 40 s into a minute
    for i in range(30):
        rec.record(RUN, 2, 1.25, base + i)
    rec.flush(base + 30)
    buckets = store.buckets(0, 2_000_000_000)
    assert [b["steps"] for b in buckets] == [40, 20]
    assert abs(sum(b["distance_m"] for b in buckets) - 37.5) < 1e-9
    first = int(base // 60) * 60
    assert buckets[0]["start"] == first and buckets[1]["start"] == first + 60


def test_nothing_recorded_until_time_synced(tmp_path):
    store, rec, flag = make(tmp_path, synced=False)
    rec.record(RUN, 5, 3.0, 50.0)  # 1970: clock not synced yet
    rec.flush(51.0)
    assert store.buckets(0, 10**10) == [] and store.sessions(0) == []
    flag["synced"] = True
    rec.record(RUN, 5, 3.0, 1_790_000_000.0)
    rec.flush(1_790_000_001.0)
    assert store.buckets(0, 10**10)[0]["steps"] == 5


def test_sessions_split_by_idle_gap(tmp_path):
    store, rec, _ = make(tmp_path)
    t = 1_790_000_000.0
    rec.record(RUN, 10, 5.0, t)
    rec.record(RUN, 10, 5.0, t + 60)
    rec.record(STOP, 0, 0.0, t + 100)
    rec.record(RUN, 10, 5.0, t + 150)  # 90 s pause: same session
    rec.record(RUN, 10, 5.0, t + 400)  # 250 s gap: new session
    rec.flush(t + 401)
    sessions = store.sessions(0)
    assert [(s["start"], s["end"], s["steps"]) for s in sessions] == [
        (int(t), int(t + 150), 30),
        (int(t + 400), int(t + 400), 10),
    ]


def test_idle_packets_do_not_create_buckets(tmp_path):
    store, rec, _ = make(tmp_path)
    for i in range(5):
        rec.record(STOP, 0, 0.0, 1_790_000_000.0 + i)
    rec.flush(1_790_000_010.0)
    assert store.buckets(0, 10**10) == [] and store.sessions(0) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_storage.py tests/test_sessions.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`bridge/src/treadmill_bridge/storage.py`:
```python
"""SQLite storage for minute step buckets and walking sessions."""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS step_buckets (
    start INTEGER PRIMARY KEY,
    steps INTEGER NOT NULL,
    distance_m REAL NOT NULL,
    active_seconds REAL NOT NULL,
    version REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    start INTEGER PRIMARY KEY,
    end INTEGER NOT NULL,
    steps INTEGER NOT NULL,
    distance_m REAL NOT NULL
);
"""

BUCKET_SECONDS = 60


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def add_to_bucket(self, start: int, steps: int, distance_m: float, active_seconds: float, version: float) -> None:
        self._db.execute(
            """INSERT INTO step_buckets (start, steps, distance_m, active_seconds, version)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(start) DO UPDATE SET
                 steps = steps + excluded.steps,
                 distance_m = distance_m + excluded.distance_m,
                 active_seconds = active_seconds + excluded.active_seconds,
                 version = excluded.version""",
            (start, steps, distance_m, active_seconds, version),
        )
        self._db.commit()

    def buckets(self, since: int, until: int) -> list[dict]:
        rows = self._db.execute(
            """SELECT start, start + ? AS end, steps, distance_m, active_seconds, version
               FROM step_buckets WHERE start >= ? AND start + ? <= ? ORDER BY start""",
            (BUCKET_SECONDS, since, BUCKET_SECONDS, until),
        )
        return [dict(r) for r in rows]

    def save_session(self, start: int, end: int, steps: int, distance_m: float) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO sessions (start, end, steps, distance_m) VALUES (?, ?, ?, ?)",
            (start, end, steps, distance_m),
        )
        self._db.commit()

    def sessions(self, since: int) -> list[dict]:
        rows = self._db.execute(
            "SELECT start, end, steps, distance_m FROM sessions WHERE end >= ? ORDER BY start", (since,)
        )
        return [dict(r) for r in rows]

    def purge(self, before: int) -> None:
        self._db.execute("DELETE FROM step_buckets WHERE start < ?", (before,))
        self._db.execute("DELETE FROM sessions WHERE end < ?", (before,))
        self._db.commit()

    def close(self) -> None:
        self._db.close()
```

`bridge/src/treadmill_bridge/sessions.py`:
```python
"""Walking sessions and per-minute step buckets."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .protocol import Status
from .storage import BUCKET_SECONDS, Store

log = logging.getLogger(__name__)
MAX_ACTIVE_STEP_S = 5.0


class SessionRecorder:
    def __init__(self, store: Store, time_synced: Callable[[], bool], idle_gap_s: float = 120.0) -> None:
        self._store = store
        self._time_synced = time_synced
        self._idle_gap_s = idle_gap_s
        self._pending: dict[int, list[float]] = {}
        self._session: dict | None = None
        self._last_wall: float | None = None
        self._warned = False

    def record(self, status: Status, steps_delta: int, distance_delta_m: float, wall_now: float) -> None:
        if not self._time_synced():
            if not self._warned:
                log.warning("clock not synchronised yet; not recording steps")
                self._warned = True
            return
        previous = self._last_wall
        self._last_wall = wall_now
        if steps_delta <= 0 and distance_delta_m <= 0:
            return
        active = 0.0
        if status.running and previous is not None:
            active = min(wall_now - previous, MAX_ACTIVE_STEP_S)
        start = int(wall_now // BUCKET_SECONDS) * BUCKET_SECONDS
        bucket = self._pending.setdefault(start, [0, 0.0, 0.0])
        bucket[0] += steps_delta
        bucket[1] += distance_delta_m
        bucket[2] += active
        session = self._session
        if session is None or wall_now - session["end"] > self._idle_gap_s:
            session = {"start": int(wall_now), "end": int(wall_now), "steps": 0, "distance_m": 0.0}
            self._session = session
        session["end"] = int(wall_now)
        session["steps"] += steps_delta
        session["distance_m"] += distance_delta_m

    def flush(self, wall_now: float) -> None:
        for start, (steps, distance, active) in self._pending.items():
            self._store.add_to_bucket(start, int(steps), distance, active, wall_now)
        self._pending.clear()
        if self._session is not None:
            self._store.save_session(**self._session)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge
git commit -m "Add minute step buckets and walking sessions to the bridge"
```

---

### Task 5: BLE helpers, test fakes and the foot pod

**Files:**
- Create: `bridge/src/treadmill_bridge/ble.py`, `bridge/src/treadmill_bridge/footpod.py`, `bridge/tests/fakes.py`, `bridge/tests/test_footpod.py`
- Modify: `bridge/tests/conftest.py`

**Interfaces:**
- Consumes: `StatusHub`, `Odometer`, `protocol`.
- Produces: `ble.peripheral_connections`, `ble.enable_just_works`, `ble.advertising_payload`; `footpod.*` per summary; test helpers `fakes.virtual_device(link, name) -> Device`, `fakes.FakeWatch`.

Note: on a Bumble `LocalLink`, devices are routed by their **random** address, so tests use `OwnAddressType.RANDOM`; production uses `PUBLIC` (stable bond identity).

- [ ] **Step 1: Test fakes and fixtures**

`bridge/tests/fakes.py`:
```python
"""Virtual BLE participants for tests (Bumble LocalLink)."""

from __future__ import annotations

import asyncio
import itertools

from bumble.controller import Controller
from bumble.core import UUID
from bumble.device import Device, Peer
from bumble.hci import Address, OwnAddressType
from bumble.host import Host
from bumble.link import LocalLink
from bumble.transport.common import AsyncPipeSink

_counter = itertools.count(1)


def virtual_device(link: LocalLink, name: str) -> Device:
    n = next(_counter)
    public = f"F0:00:00:00:00:{n:02X}"
    controller = Controller(name, link=link, public_address=public)
    return Device(name=name, address=Address(f"C0:00:00:00:00:{n:02X}"), host=Host(controller, AsyncPipeSink(controller)))


class FakeWatch:
    """A central that connects to a peripheral, subscribes and collects notifications."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self.connections = {}

    async def connect(self, address: Address):
        return await self.device.connect(address, own_address_type=OwnAddressType.RANDOM, timeout=5)

    async def subscribe(self, connection, service_uuid: str, char_uuid: str) -> asyncio.Queue:
        peer = Peer(connection)
        service = (await peer.discover_service(UUID(service_uuid)))[0]
        chars = await peer.discover_characteristics(service=service)
        target = next(c for c in chars if c.uuid == UUID(char_uuid))
        queue: asyncio.Queue = asyncio.Queue()
        await peer.subscribe(target, lambda value: queue.put_nowait(bytes(value)))
        return queue

    async def write(self, connection, service_uuid: str, char_uuid: str, value: bytes) -> None:
        peer = Peer(connection)
        service = (await peer.discover_service(UUID(service_uuid)))[0]
        chars = await peer.discover_characteristics(service=service)
        target = next(c for c in chars if c.uuid == UUID(char_uuid))
        await target.write_value(value, with_response=False)
```

`bridge/tests/conftest.py`:
```python
import logging

import pytest
from bumble.link import LocalLink

logging.getLogger("bumble").setLevel(logging.WARNING)


@pytest.fixture
def link():
    return LocalLink()
```

- [ ] **Step 2: Failing tests**

`bridge/tests/test_footpod.py`:
```python
import asyncio
import struct

from bumble.hci import OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.footpod import FootPod, pod_speed_mps, rsc_measurement
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.odometer import Odometer
from tests.fakes import FakeWatch, virtual_device


def test_rsc_measurement_bytes():
    # 4.5 km/h, 105 steps/min -> 52 strides/min, 123.4 m
    assert rsc_measurement(1.25, 52, 123.4) == struct.pack("<BHBI", 0x02, 320, 52, 1234)
    assert rsc_measurement(-1, -5, -3) == struct.pack("<BHBI", 0x02, 0, 0, 0)
    assert rsc_measurement(1000, 999, 1e9) == struct.pack("<BHBI", 0x02, 0xFFFF, 0xFF, 0xFFFFFFFF)


def test_pod_speed_hold_during_start():
    run = p.parse_status(p.build_status(1, 45, 0, 0, 0))
    countdown = p.parse_status(p.build_status(8, 0, 0, 0, 0))
    stopped = p.parse_status(p.build_status(0, 0, 0, 0, 0))
    assert pod_speed_mps(run, 10.0, None, hold=True) == 1.25
    assert pod_speed_mps(countdown, 10.0, None, hold=False) == 0.0
    assert abs(pod_speed_mps(countdown, 10.0, None, hold=True) - 1.0 / 3.6) < 1e-9
    assert abs(pod_speed_mps(stopped, 10.0, 5.0, hold=True) - 1.0 / 3.6) < 1e-9  # 5 s after start
    assert pod_speed_mps(stopped, 20.0, 5.0, hold=True) == 0.0  # 15 s after start
    assert pod_speed_mps(None, 10.0, 9.0, hold=True) == 0.0  # no data at all


async def test_watch_pairs_and_receives_measurement(link):
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    hub, odo = StatusHub(), Odometer()
    pod = FootPod(pod_dev, hub, odo, OwnAddressType.RANDOM)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    status = p.parse_status(p.build_status(1, 45, 0, 0, 0))
    hub.publish(status)
    odo.update(status, 0.0)
    await pod.start()
    assert pod.advertising
    watch = FakeWatch(watch_dev)
    conn = await watch.connect(pod_dev.random_address)
    await conn.pair()
    assert conn.is_encrypted
    queue = await watch.subscribe(conn, "1814", "2A53")
    await pod.tick(0.0)
    data = await asyncio.wait_for(queue.get(), 2)
    flags, speed, cadence, dist = struct.unpack("<BHBI", data)
    assert (flags, speed, cadence) == (0x02, 320, 0)


async def test_stop_disconnects_watch_and_stops_advertising(link):
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    pod = FootPod(pod_dev, StatusHub(), Odometer(), OwnAddressType.RANDOM)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    await pod.start()
    await FakeWatch(watch_dev).connect(pod_dev.random_address)
    await asyncio.sleep(0.1)
    await pod.stop()
    await asyncio.sleep(0.1)
    assert not pod.advertising and not pod_dev.connections
```

- [ ] **Step 3: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_footpod.py -q`
Expected: FAIL — `ModuleNotFoundError: treadmill_bridge.footpod`.

- [ ] **Step 4: Implement**

`bridge/src/treadmill_bridge/ble.py`:
```python
"""Small Bumble helpers shared by the peripherals."""

from __future__ import annotations

from bumble.core import AdvertisingData
from bumble.device import Connection, Device
from bumble.hci import Role
from bumble.pairing import PairingConfig, PairingDelegate


def peripheral_connections(device: Device) -> list[Connection]:
    """Links where this device is the peripheral (the watch), never our own central links."""
    return [c for c in device.connections.values() if c.role == Role.PERIPHERAL]


def enable_just_works(device: Device) -> None:
    device.pairing_config_factory = lambda _connection: PairingConfig(
        sc=True,
        mitm=False,
        bonding=True,
        delegate=PairingDelegate(PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT),
    )


def advertising_payload(entries: list[tuple[int, bytes]]) -> bytes:
    return bytes(AdvertisingData(entries))
```

`bridge/src/treadmill_bridge/footpod.py`:
```python
"""Garmin foot pod (BLE Running Speed and Cadence) fed by the treadmill."""

from __future__ import annotations

import logging
import struct
import time
from collections.abc import Callable

from bumble.core import AdvertisingData
from bumble.device import Device
from bumble.gatt import Characteristic, Service
from bumble.hci import OwnAddressType

from .ble import advertising_payload, enable_just_works, peripheral_connections
from .hub import StatusHub
from .odometer import Odometer
from .protocol import Status, is_countdown

log = logging.getLogger(__name__)

RSC_SERVICE = "1814"
RSC_MEASUREMENT = "2A53"
RSC_FEATURE = "2A54"
BATTERY_SERVICE = "180F"
BATTERY_LEVEL = "2A19"
DEVICE_INFORMATION = "180A"
MANUFACTURER_NAME = "2A29"
APPEARANCE_ON_SHOE = 0x0442
FLAGS_GENERAL_DISCOVERABLE_LE_ONLY = 0x06
MEASUREMENT_FLAGS = 0x02  # total distance present, walking
FEATURE_TOTAL_DISTANCE = 0x0002
HOLD_SPEED_MPS = 1.0 / 3.6
HOLD_AFTER_START_S = 8.0
STATUS_FRESH_S = 3.0


def rsc_measurement(speed_mps: float, cadence_strides: int, distance_m: float) -> bytes:
    speed = max(0, min(0xFFFF, round(speed_mps * 256)))
    cadence = max(0, min(0xFF, int(cadence_strides)))
    distance = max(0, min(0xFFFFFFFF, int(distance_m * 10)))
    return struct.pack("<BHBI", MEASUREMENT_FLAGS, speed, cadence, distance)


def pod_speed_mps(status: Status | None, now: float, last_start_at: float | None, hold: bool) -> float:
    if status is None:
        return 0.0
    speed = status.speed_mps
    if hold and speed == 0.0:
        starting = is_countdown(status.state) or (
            last_start_at is not None and now - last_start_at < HOLD_AFTER_START_S
        )
        if starting:
            return HOLD_SPEED_MPS
    return speed


class FootPod:
    def __init__(
        self,
        device: Device,
        hub: StatusHub,
        odometer: Odometer,
        own_address_type: OwnAddressType,
        hold_speed_during_start: bool = False,
        clock: Callable[[], float] = time.monotonic,
        name: str = "Treadmill Pod",
    ) -> None:
        self._device = device
        self._hub = hub
        self._odometer = odometer
        self._own_address_type = own_address_type
        self._hold = hold_speed_during_start
        self._clock = clock
        self._name = name
        self.advertising = False
        self.measurement = Characteristic(
            RSC_MEASUREMENT, Characteristic.Properties.NOTIFY, Characteristic.READABLE, bytes(8)
        )

    def install(self) -> None:
        self._device.add_services(
            [
                Service(
                    RSC_SERVICE,
                    [
                        self.measurement,
                        Characteristic(
                            RSC_FEATURE,
                            Characteristic.Properties.READ,
                            Characteristic.READABLE,
                            struct.pack("<H", FEATURE_TOTAL_DISTANCE),
                        ),
                    ],
                ),
                Service(
                    BATTERY_SERVICE,
                    [
                        Characteristic(
                            BATTERY_LEVEL,
                            Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
                            Characteristic.READABLE,
                            bytes([100]),
                        )
                    ],
                ),
                Service(
                    DEVICE_INFORMATION,
                    [
                        Characteristic(
                            MANUFACTURER_NAME,
                            Characteristic.Properties.READ,
                            Characteristic.READABLE,
                            b"treadmill-bridge",
                        )
                    ],
                ),
            ]
        )
        enable_just_works(self._device)

    async def start(self) -> None:
        if self.advertising:
            return
        await self._device.start_advertising(
            own_address_type=self._own_address_type,
            advertising_data=advertising_payload(
                [
                    (AdvertisingData.FLAGS, bytes([FLAGS_GENERAL_DISCOVERABLE_LE_ONLY])),
                    (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, struct.pack("<H", 0x1814)),
                    (AdvertisingData.APPEARANCE, struct.pack("<H", APPEARANCE_ON_SHOE)),
                ]
            ),
            scan_response_data=advertising_payload(
                [(AdvertisingData.COMPLETE_LOCAL_NAME, self._name.encode())]
            ),
            advertising_interval_min=100.0,
            advertising_interval_max=100.0,
            auto_restart=True,
        )
        self.advertising = True
        log.info("foot pod advertising")

    async def stop(self) -> None:
        if self.advertising:
            await self._device.stop_advertising()
            self.advertising = False
            log.info("foot pod stopped advertising")
        for connection in peripheral_connections(self._device):
            await connection.disconnect()

    def payload(self, now: float) -> bytes:
        status = self._hub.fresh_status(STATUS_FRESH_S)
        speed = pod_speed_mps(status, now, self._hub.last_start_at, self._hold)
        strides = self._odometer.cadence_spm(now) // 2 if status is not None else 0
        return rsc_measurement(speed, strides, self._odometer.smoothed_distance_m(now))

    async def tick(self, now: float) -> None:
        await self._device.notify_subscribers(self.measurement, self.payload(now))
```

- [ ] **Step 5: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass. If `connection.role` or `Role.PERIPHERAL` differ in Bumble 0.0.235, inspect `bumble.device.Connection.__init__` and adjust `ble.peripheral_connections`, then record a ruling.

- [ ] **Step 6: Commit**

```bash
git add bridge
git commit -m "Add the RSC foot pod peripheral to the bridge"
```

---

### Task 6: TreadmillClient

**Files:**
- Create: `bridge/src/treadmill_bridge/treadmill.py`, `bridge/tests/test_treadmill.py`
- Modify: `bridge/tests/fakes.py` (add `FakeTreadmill`)

**Interfaces:**
- Consumes: `protocol`, `StatusHub`.
- Produces: `TreadmillClient`, `parse_address` per summary; `fakes.FakeTreadmill(device)` with `.writes: list[bytes]`, `.running: bool`, `install()`, `start()`, `drop()`.

- [ ] **Step 1: FakeTreadmill**

Append to `bridge/tests/fakes.py`:
```python
import struct

from bumble.core import AdvertisingData
from bumble.gatt import Characteristic, CharacteristicValue, Service

from treadmill_bridge import protocol as p


class FakeTreadmill:
    """FE00 server that behaves like the R1 Pro: answers queries, obeys start/stop."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self.writes: list[bytes] = []
        self.running = True
        self.steps = 0
        self.notify = Characteristic(
            p.NOTIFY_UUID,
            Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
            Characteristic.READABLE,
            bytes(20),
        )
        self.write = Characteristic(
            p.WRITE_UUID,
            Characteristic.Properties.WRITE_WITHOUT_RESPONSE | Characteristic.Properties.WRITE,
            Characteristic.WRITEABLE,
            CharacteristicValue(write=self._on_write),
        )

    def install(self) -> None:
        self.device.add_service(Service(p.SERVICE_UUID, [self.notify, self.write]))

    async def start(self) -> None:
        await self.device.power_on()
        await self.device.start_advertising(
            own_address_type=OwnAddressType.RANDOM,
            advertising_data=bytes(
                AdvertisingData(
                    [(AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, struct.pack("<H", 0xFE00))]
                )
            ),
            auto_restart=True,
        )

    async def drop(self) -> None:
        for connection in list(self.device.connections.values()):
            await connection.disconnect()

    def _on_write(self, connection, value) -> None:
        data = bytes(value)
        self.writes.append(data)
        if data == p.START:
            self.running = True
        elif data == p.STOP:
            self.running = False
        if self.running:
            self.steps += 2
        packet = p.build_status(1 if self.running else 0, 45 if self.running else 0, 0, self.steps // 10, self.steps)
        asyncio.ensure_future(self.device.notify_subscriber(connection, self.notify, packet))
```

- [ ] **Step 2: Failing tests**

`bridge/tests/test_treadmill.py`:
```python
import asyncio

from bumble.hci import Address, OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.treadmill import TreadmillClient, parse_address
from tests.fakes import FakeTreadmill, virtual_device

FAST = dict(poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,), scan_timeout=2.0, connect_timeout=2.0)


async def setup(link, address_known=True):
    tm = FakeTreadmill(virtual_device(link, "treadmill"))
    tm.install()
    await tm.start()
    radio = virtual_device(link, "bridge-a")
    await radio.power_on()
    hub = StatusHub()
    found = []
    client = TreadmillClient(
        radio,
        hub,
        str(tm.device.random_address) if address_known else None,
        OwnAddressType.RANDOM,
        on_address=found.append,
        **FAST,
    )
    task = asyncio.create_task(client.run())
    return tm, hub, client, task, found


async def wait_for(predicate, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


def test_parse_address():
    public = parse_address("57:4C:4D:2F:0C:93/P")
    assert public.address_type == Address.PUBLIC_DEVICE_ADDRESS
    assert str(public).startswith("57:4C:4D:2F:0C:93")
    assert parse_address("C0:00:00:00:00:01").address_type == Address.RANDOM_DEVICE_ADDRESS


async def test_connects_polls_and_publishes(link):
    tm, hub, _, task, _ = await setup(link)
    try:
        await wait_for(lambda: hub.link_up and hub.latest is not None)
        await wait_for(lambda: tm.writes.count(p.QUERY) >= 3)
        assert set(tm.writes) == {p.QUERY}
    finally:
        task.cancel()


async def test_discovers_address_by_scanning(link):
    tm, hub, _, task, found = await setup(link, address_known=False)
    try:
        await wait_for(lambda: hub.link_up)
        assert found and found[0].startswith(str(tm.device.random_address)[:17])
    finally:
        task.cancel()


async def test_stop_replaces_pending_start_and_goes_first(link):
    tm, hub, client, task, _ = await setup(link)
    try:
        await wait_for(lambda: hub.link_up)
        client.send_command(p.START)
        client.send_command(p.STOP)
        await wait_for(lambda: p.STOP in tm.writes)
        assert p.START not in tm.writes
        client.send_command(p.START)
        await wait_for(lambda: p.START in tm.writes)
        assert hub.last_start_at is not None
    finally:
        task.cancel()


async def test_reconnects_after_drop(link):
    tm, hub, _, task, _ = await setup(link)
    try:
        await wait_for(lambda: hub.link_up)
        changes = []
        hub.on_link(changes.append)
        await tm.drop()
        await wait_for(lambda: changes[:2] == [False, True])
    finally:
        task.cancel()
```

- [ ] **Step 3: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_treadmill.py -q`
Expected: FAIL — `ModuleNotFoundError: treadmill_bridge.treadmill`.

- [ ] **Step 4: Implement**

`bridge/src/treadmill_bridge/treadmill.py`:
```python
"""The single BLE link to the treadmill: find, connect, poll, send belt commands."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

from bumble.core import UUID, AdvertisingData
from bumble.device import Device, Peer
from bumble.hci import Address, OwnAddressType

from .hub import StatusHub
from .protocol import NOTIFY_UUID, QUERY, SERVICE_UUID, START, STOP, WRITE_UUID, parse_status

log = logging.getLogger(__name__)
_UUID_LISTS = (
    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
    AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
)


class LinkError(Exception):
    pass


def parse_address(text: str) -> Address:
    if text.endswith("/P"):
        return Address(text[:-2], Address.PUBLIC_DEVICE_ADDRESS)
    return Address(text, Address.RANDOM_DEVICE_ADDRESS)


def format_address(address: Address) -> str:
    raw = address.to_string(with_type_qualifier=False)
    return f"{raw}/P" if address.address_type == Address.PUBLIC_DEVICE_ADDRESS else raw


class TreadmillClient:
    def __init__(
        self,
        device: Device,
        hub: StatusHub,
        address: str | None,
        own_address_type: OwnAddressType,
        on_address: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        poll_interval: float = 1.0,
        write_gap: float = 0.4,
        stale_after: float = 5.0,
        backoff: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0),
        scan_timeout: float = 10.0,
        connect_timeout: float = 10.0,
    ) -> None:
        self._device = device
        self._hub = hub
        self._address = address
        self._own_address_type = own_address_type
        self._on_address = on_address
        self._clock = clock
        self._poll_interval = poll_interval
        self._write_gap = write_gap
        self._stale_after = stale_after
        self._backoff = backoff
        self._scan_timeout = scan_timeout
        self._connect_timeout = connect_timeout
        self._pending: list[bytes] = []
        self._attempt = 0

    def send_command(self, command: bytes) -> None:
        if command == STOP:
            self._pending = [STOP]
        elif command == START:
            self._pending = [c for c in self._pending if c != START] + [START]
        else:
            raise ValueError(f"not a belt command: {command.hex()}")

    async def run(self) -> None:
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # every failure ends in a reconnect
                log.warning("treadmill link lost: %s", error)
            self._hub.set_link(False)
            delay = self._backoff[min(self._attempt, len(self._backoff) - 1)]
            self._attempt += 1
            await asyncio.sleep(delay)

    async def _session(self) -> None:
        address = await self._resolve_address()
        connection = await self._device.connect(
            address, own_address_type=self._own_address_type, timeout=self._connect_timeout
        )
        lost = asyncio.Event()
        connection.on("disconnection", lambda *_: lost.set())
        log.info("treadmill connected %s", format_address(address))
        try:
            peer = Peer(connection)
            services = await peer.discover_service(UUID(SERVICE_UUID))
            if not services:
                raise LinkError("FE00 service not found")
            chars = {c.uuid: c for c in await peer.discover_characteristics(service=services[0])}
            notify, write = chars.get(UUID(NOTIFY_UUID)), chars.get(UUID(WRITE_UUID))
            if notify is None or write is None:
                raise LinkError("FE01/FE02 not found")
            last_valid = [self._clock()]

            def on_notify(value: bytes) -> None:
                status = parse_status(bytes(value))
                if status is None:
                    return
                last_valid[0] = self._clock()
                self._attempt = 0
                self._hub.set_link(True)
                self._hub.publish(status)

            await peer.subscribe(notify, on_notify)
            while not lost.is_set():
                command = self._pending.pop(0) if self._pending else QUERY
                await write.write_value(command, with_response=False)
                if command == START:
                    self._hub.note_start()
                if command != QUERY:
                    log.info("sent %s to treadmill", "start" if command == START else "stop")
                if self._clock() - last_valid[0] > self._stale_after:
                    raise LinkError("no valid status")
                await asyncio.sleep(self._write_gap if self._pending else self._poll_interval)
            raise LinkError("disconnected")
        finally:
            if not lost.is_set():
                with contextlib.suppress(Exception):
                    await connection.disconnect()

    async def _resolve_address(self) -> Address:
        if self._address:
            return parse_address(self._address)
        found: asyncio.Future[Address] = asyncio.get_running_loop().create_future()
        service = UUID(SERVICE_UUID)

        def on_advertisement(advertisement) -> None:
            for kind in _UUID_LISTS:
                if service in (advertisement.data.get(kind) or []) and not found.done():
                    found.set_result(advertisement.address)

        self._device.on("advertisement", on_advertisement)
        try:
            await self._device.start_scanning(legacy=True, active=True, filter_duplicates=True)
            address = await asyncio.wait_for(found, self._scan_timeout)
        finally:
            self._device.remove_listener("advertisement", on_advertisement)
            with contextlib.suppress(Exception):
                await self._device.stop_scanning()
        self._address = format_address(address)
        log.info("treadmill found at %s", self._address)
        if self._on_address:
            self._on_address(self._address)
        return address
```

- [ ] **Step 5: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass. If `Address.to_string` has a different signature in 0.0.235, use `str(address).removesuffix("/P")` and record a ruling.

- [ ] **Step 6: Commit**

```bash
git add bridge
git commit -m "Add the treadmill client with polling, commands and reconnects"
```

---

### Task 7: CiqLink (FE00 server for the field)

**Files:**
- Create: `bridge/src/treadmill_bridge/ciq_link.py`, `bridge/tests/test_ciq_link.py`

**Interfaces:**
- Consumes: `protocol`, `StatusHub`, `ble`.
- Produces: `CiqLink` per summary.

- [ ] **Step 1: Failing tests**

`bridge/tests/test_ciq_link.py`:
```python
import asyncio

from bumble.hci import OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.ciq_link import CiqLink
from treadmill_bridge.hub import StatusHub
from tests import fixtures as f
from tests.fakes import FakeWatch, virtual_device


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def setup(link):
    clock = Clock()
    hub = StatusHub(clock)
    commands = []
    radio, watch_dev = virtual_device(link, "bridge-b"), virtual_device(link, "watch")
    ciq = CiqLink(radio, hub, commands.append, OwnAddressType.RANDOM, clock=clock)
    ciq.install()
    await radio.power_on()
    await watch_dev.power_on()
    await ciq.start()
    watch = FakeWatch(watch_dev)
    conn = await watch.connect(radio.random_address)
    queue = await watch.subscribe(conn, p.SERVICE_UUID, p.NOTIFY_UUID)
    return clock, hub, commands, watch, conn, queue, ciq


async def test_query_answered_with_cached_raw_packet(link):
    clock, hub, _, watch, conn, queue, _ = await setup(link)
    hub.publish(p.parse_status(f.WALKING))
    clock.t = 2.9
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.QUERY)
    assert await asyncio.wait_for(queue.get(), 2) == f.WALKING


async def test_stale_cache_gets_no_answer(link):
    clock, hub, _, watch, conn, queue, _ = await setup(link)
    hub.publish(p.parse_status(f.WALKING))
    clock.t = 3.5
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.QUERY)
    await asyncio.sleep(0.2)
    assert queue.empty()


async def test_commands_forwarded_and_unknown_dropped(link):
    _, _, commands, watch, conn, _, _ = await setup(link)
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.START)
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, bytes.fromhex("f7a20102a5fd"))  # set speed: not allowed
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.STOP)
    await asyncio.sleep(0.2)
    assert commands == [p.START, p.STOP]


async def test_stop_disconnects_watch(link):
    _, _, _, _, _, _, ciq = await setup(link)
    await ciq.stop()
    await asyncio.sleep(0.1)
    assert not ciq.advertising and not ciq._device.connections
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_ciq_link.py -q`
Expected: FAIL — `ModuleNotFoundError: treadmill_bridge.ciq_link`.

- [ ] **Step 3: Implement**

`bridge/src/treadmill_bridge/ciq_link.py`:
```python
"""FE00 server for the Connect IQ data field (radio B)."""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections.abc import Callable

from bumble.core import AdvertisingData
from bumble.device import Device
from bumble.gatt import Characteristic, CharacteristicValue, Service
from bumble.hci import OwnAddressType

from .ble import advertising_payload, enable_just_works, peripheral_connections
from .hub import StatusHub
from .protocol import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID, command_kind

log = logging.getLogger(__name__)
FLAGS_GENERAL_DISCOVERABLE_LE_ONLY = 0x06


class CiqLink:
    def __init__(
        self,
        device: Device,
        hub: StatusHub,
        send_command: Callable[[bytes], None],
        own_address_type: OwnAddressType,
        clock: Callable[[], float] = time.monotonic,
        fresh_s: float = 3.0,
        name: str = "TM-Bridge",
    ) -> None:
        self._device = device
        self._hub = hub
        self._send_command = send_command
        self._own_address_type = own_address_type
        self._clock = clock
        self._fresh_s = fresh_s
        self._name = name
        self._tasks: set[asyncio.Task] = set()
        self.advertising = False
        self.notify = Characteristic(
            NOTIFY_UUID,
            Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
            Characteristic.READABLE,
            bytes(20),
        )
        self.write = Characteristic(
            WRITE_UUID,
            Characteristic.Properties.WRITE_WITHOUT_RESPONSE | Characteristic.Properties.WRITE,
            Characteristic.WRITEABLE,
            CharacteristicValue(write=self._on_write),
        )

    def install(self) -> None:
        self._device.add_service(Service(SERVICE_UUID, [self.notify, self.write]))
        enable_just_works(self._device)

    async def start(self) -> None:
        if self.advertising:
            return
        await self._device.start_advertising(
            own_address_type=self._own_address_type,
            advertising_data=advertising_payload(
                [
                    (AdvertisingData.FLAGS, bytes([FLAGS_GENERAL_DISCOVERABLE_LE_ONLY])),
                    (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, struct.pack("<H", 0xFE00)),
                ]
            ),
            scan_response_data=advertising_payload(
                [(AdvertisingData.COMPLETE_LOCAL_NAME, self._name.encode())]
            ),
            advertising_interval_min=100.0,
            advertising_interval_max=100.0,
            auto_restart=True,
        )
        self.advertising = True
        log.info("field bridge advertising")

    async def stop(self) -> None:
        if self.advertising:
            await self._device.stop_advertising()
            self.advertising = False
            log.info("field bridge stopped advertising")
        for connection in peripheral_connections(self._device):
            await connection.disconnect()

    def _on_write(self, connection, value) -> None:
        data = bytes(value)
        kind = command_kind(data)
        if kind == "query":
            status = self._hub.fresh_status(self._fresh_s)
            if status is not None:
                task = asyncio.ensure_future(self._device.notify_subscriber(connection, self.notify, status.raw))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        elif kind in ("start", "stop"):
            log.info("field asked to %s the belt", kind)
            self._send_command(data)
        else:
            log.warning("dropped unknown field write %s", data.hex())
```

- [ ] **Step 4: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge
git commit -m "Add the FE00 bridge for the watch field"
```

---

### Task 8: Bridge advertising lifecycle

**Files:**
- Create: `bridge/src/treadmill_bridge/bridge.py`, `bridge/tests/test_bridge.py`

**Interfaces:**
- Consumes: `StatusHub`, `FootPod`, `CiqLink`, `TreadmillClient` (in the integration test).
- Produces: `Bridge(hub, footpod, ciq, clock, grace_s)` with `async tick()`.

- [ ] **Step 1: Failing tests**

`bridge/tests/test_bridge.py`:
```python
import asyncio

from bumble.hci import OwnAddressType

from treadmill_bridge.bridge import Bridge
from treadmill_bridge.footpod import FootPod
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.odometer import Odometer
from treadmill_bridge.treadmill import TreadmillClient
from tests.fakes import FakeTreadmill, FakeWatch, virtual_device


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePeripheral:
    def __init__(self):
        self.advertising = False
        self.calls = []

    async def start(self):
        self.advertising = True
        self.calls.append("start")

    async def stop(self):
        self.advertising = False
        self.calls.append("stop")

    async def tick(self, now):
        self.calls.append("tick")


async def test_advertise_only_with_link_and_grace():
    clock = Clock()
    hub = StatusHub(clock)
    pod, ciq = FakePeripheral(), FakePeripheral()
    bridge = Bridge(hub, pod, ciq, clock=clock, grace_s=30.0)
    await bridge.tick()
    assert not pod.advertising and not ciq.advertising
    hub.set_link(True)
    await bridge.tick()
    assert pod.advertising and ciq.advertising
    clock.t = 100.0
    hub.set_link(False)
    clock.t = 129.0
    await bridge.tick()
    assert pod.advertising
    clock.t = 130.0
    await bridge.tick()
    assert not pod.advertising and not ciq.advertising


async def test_runs_without_ciq():
    hub = StatusHub()
    pod = FakePeripheral()
    bridge = Bridge(hub, pod, None)
    hub.set_link(True)
    await bridge.tick()
    assert pod.advertising


async def test_grace_then_stop_only_watch_links(link):
    tm = FakeTreadmill(virtual_device(link, "treadmill"))
    tm.install()
    await tm.start()
    radio = virtual_device(link, "bridge-a")
    watch_dev = virtual_device(link, "watch")
    await radio.power_on()
    await watch_dev.power_on()
    hub = StatusHub()
    pod = FootPod(radio, hub, Odometer(), OwnAddressType.RANDOM)
    pod.install()
    client = TreadmillClient(
        radio, hub, str(tm.device.random_address), OwnAddressType.RANDOM,
        poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,),
    )
    task = asyncio.create_task(client.run())
    bridge = Bridge(hub, pod, None, grace_s=0.0)
    try:
        for _ in range(100):
            await bridge.tick()
            if hub.link_up and pod.advertising:
                break
            await asyncio.sleep(0.02)
        await FakeWatch(watch_dev).connect(radio.random_address)
        await asyncio.sleep(0.1)
        assert len(radio.connections) == 2  # treadmill (central) + watch (peripheral)
        hub.set_link(False)  # simulate the treadmill link going down in the hub only
        await bridge.tick()
        await asyncio.sleep(0.1)
        roles = [c.role for c in radio.connections.values()]
        assert len(roles) == 1  # watch dropped, treadmill link kept
    finally:
        task.cancel()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_bridge.py -q`
Expected: FAIL — `ModuleNotFoundError: treadmill_bridge.bridge`.

- [ ] **Step 3: Implement**

`bridge/src/treadmill_bridge/bridge.py`:
```python
"""Watch-facing services exist only while the treadmill link is up."""

from __future__ import annotations

import time
from collections.abc import Callable

from .hub import StatusHub


class Bridge:
    def __init__(self, hub: StatusHub, footpod, ciq, clock: Callable[[], float] = time.monotonic, grace_s: float = 30.0) -> None:
        self._hub = hub
        self._footpod = footpod
        self._ciq = ciq
        self._clock = clock
        self._grace_s = grace_s

    async def tick(self) -> None:
        now = self._clock()
        if self._hub.link_up:
            await self._footpod.start()
            if self._ciq is not None:
                await self._ciq.start()
        elif now - self._hub.link_changed_at >= self._grace_s:
            await self._footpod.stop()
            if self._ciq is not None:
                await self._ciq.stop()
        await self._footpod.tick(now)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass. `FootPod.stop()` is called on every idle tick after the grace period; it must be cheap and idempotent (it is: no advertising → only iterates peripheral connections).

- [ ] **Step 5: Commit**

```bash
git add bridge
git commit -m "Tie foot pod and field advertising to the treadmill link"
```

---

### Task 9: HTTP API

**Files:**
- Create: `bridge/src/treadmill_bridge/api.py`, `bridge/tests/test_api.py`

**Interfaces:**
- Consumes: `Store`.
- Produces: `make_app(store, status_snapshot, token, wall_clock=time.time)`.

- [ ] **Step 1: Failing tests**

`bridge/tests/test_api.py`:
```python
from aiohttp.test_utils import TestClient, TestServer

from treadmill_bridge.api import make_app
from treadmill_bridge.storage import Store

TOKEN = "secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def client_for(tmp_path, now=10_000.0):
    store = Store(str(tmp_path / "a.db"))
    store.add_to_bucket(9_900, 50, 40.0, 30.0, 9_950.0)
    store.add_to_bucket(9_960, 10, 8.0, 6.0, 9_990.0)  # still open at now=10_000
    store.save_session(9_900, 9_990, 60, 48.0)
    app = make_app(store, lambda: {"treadmill": "up"}, TOKEN, wall_clock=lambda: now)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_status_steps_sessions(tmp_path):
    client = await client_for(tmp_path)
    try:
        r = await client.get("/api/v1/status", headers=AUTH)
        assert r.status == 200 and (await r.json()) == {"treadmill": "up"}
        r = await client.get("/api/v1/steps?since=0", headers=AUTH)
        body = await r.json()
        assert [b["start"] for b in body["buckets"]] == [9_900]
        assert body["buckets"][0] == {
            "start": 9_900, "end": 9_960, "steps": 50, "distance_m": 40.0, "active_seconds": 30.0, "version": 9_950.0,
        }
        r = await client.get("/api/v1/sessions?since=0", headers=AUTH)
        assert (await r.json())["sessions"][0]["steps"] == 60
    finally:
        await client.close()


async def test_rejects_bad_token_and_bad_params(tmp_path):
    client = await client_for(tmp_path)
    try:
        assert (await client.get("/api/v1/status")).status == 401
        assert (await client.get("/api/v1/status", headers={"Authorization": "Bearer nope"})).status == 401
        assert (await client.get("/api/v1/steps?since=abc", headers=AUTH)).status == 400
        assert (await client.get("/api/v1/sessions?since=1.5x", headers=AUTH)).status == 400
    finally:
        await client.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_api.py -q`
Expected: FAIL — `ModuleNotFoundError: treadmill_bridge.api`.

- [ ] **Step 3: Implement**

`bridge/src/treadmill_bridge/api.py`:
```python
"""HTTP API for the Android companion (LAN only, bearer token)."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable

from aiohttp import web

from .storage import Store


def _int_param(request: web.Request, name: str, default: int) -> int:
    raw = request.query.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise web.HTTPBadRequest(text=f"{name} must be an integer unix time") from error


def make_app(
    store: Store,
    status_snapshot: Callable[[], dict],
    token: str,
    wall_clock: Callable[[], float] = time.time,
) -> web.Application:
    expected = f"Bearer {token}"

    @web.middleware
    async def auth(request: web.Request, handler):
        if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(status_snapshot())

    async def steps(request: web.Request) -> web.Response:
        now = int(wall_clock())
        since = _int_param(request, "since", 0)
        until = min(_int_param(request, "until", now), now)
        return web.json_response({"buckets": store.buckets(since, until)})

    async def sessions(request: web.Request) -> web.Response:
        return web.json_response({"sessions": store.sessions(_int_param(request, "since", 0))})

    app = web.Application(middlewares=[auth])
    app.router.add_get("/api/v1/status", status)
    app.router.add_get("/api/v1/steps", steps)
    app.router.add_get("/api/v1/sessions", sessions)
    return app
```

- [ ] **Step 4: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge
git commit -m "Add the bridge HTTP API"
```

---

### Task 10: Config, radios, wiring, entry point and end-to-end test

**Files:**
- Create: `bridge/src/treadmill_bridge/config.py`, `bridge/src/treadmill_bridge/radios.py`, `bridge/src/treadmill_bridge/app.py`, `bridge/src/treadmill_bridge/main.py`, `bridge/tests/test_config.py`, `bridge/tests/test_radios.py`, `bridge/tests/test_app.py`

**Interfaces:**
- Consumes: every earlier module.
- Produces: `Config`, `load_config(path)`, `State(path)`; `find_controllers(sys_root)`; `Timings`, `Components`, `build(...)`, `status_snapshot(components)`; `main.cli()`.

- [ ] **Step 1: Failing tests**

`bridge/tests/test_config.py`:
```python
import pytest

from treadmill_bridge.config import Config, State, load_config


def test_load_defaults_and_values(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('api_token = "abc"\nhold_speed_during_start = true\n')
    config = load_config(str(path))
    assert config == Config(api_token="abc", hold_speed_during_start=True)
    assert config.api_port == 8080 and config.treadmill_address is None


def test_rejects_unknown_keys_and_missing_token(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('api_token = "x"\ntypo = 1\n')
    with pytest.raises(ValueError, match="typo"):
        load_config(str(bad))
    empty = tmp_path / "empty.toml"
    empty.write_text("")
    with pytest.raises(ValueError, match="api_token"):
        load_config(str(empty))


def test_state_persists_address(tmp_path):
    state = State(str(tmp_path / "state.json"))
    assert state.treadmill_address is None
    state.save_address("57:4C:4D:2F:0C:93/P")
    assert State(str(tmp_path / "state.json")).treadmill_address == "57:4C:4D:2F:0C:93/P"
```

`bridge/tests/test_radios.py`:
```python
import os

from treadmill_bridge.radios import find_controllers


def make_hci(root, name, target):
    device_dir = root / "devices" / target
    device_dir.mkdir(parents=True)
    hci = root / "class" / name
    hci.mkdir(parents=True)
    os.symlink(device_dir, hci / "device")


def test_maps_uart_and_usb(tmp_path):
    make_hci(tmp_path, "hci0", "platform/soc/serial0/serial0-0")
    make_hci(tmp_path, "hci1", "platform/soc/usb1/1-1/1-1.2/1-1.2:1.0")
    assert find_controllers(str(tmp_path / "class")) == {"uart": 0, "usb": 1}


def test_missing_root_or_usb(tmp_path):
    assert find_controllers(str(tmp_path / "none")) == {}
    make_hci(tmp_path, "hci0", "platform/soc/serial0/serial0-0")
    assert find_controllers(str(tmp_path / "class")) == {"uart": 0}
```

`bridge/tests/test_app.py`:
```python
import asyncio
import struct

from bumble.hci import OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.app import Timings, build, status_snapshot
from treadmill_bridge.config import Config, State
from treadmill_bridge.storage import Store
from tests.fakes import FakeTreadmill, FakeWatch, virtual_device

FAST = Timings(poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,), grace_s=0.3, tick_s=0.05, flush_s=0.2)


async def start_system(link, tmp_path, with_b=True):
    tm = FakeTreadmill(virtual_device(link, "treadmill"))
    tm.install()
    await tm.start()
    dev_a = virtual_device(link, "radio-a")
    dev_b = virtual_device(link, "radio-b") if with_b else None
    config = Config(api_token="t", treadmill_address=str(tm.device.random_address))
    components = build(
        dev_a, dev_b, config, Store(str(tmp_path / "e.db")), State(str(tmp_path / "s.json")),
        OwnAddressType.RANDOM, time_synced=lambda: True, timings=FAST,
    )
    await dev_a.power_on()
    if dev_b:
        await dev_b.power_on()
    task = asyncio.create_task(components.run_ble())
    for _ in range(150):
        if components.hub.link_up and components.footpod.advertising:
            break
        await asyncio.sleep(0.02)
    return tm, components, task


async def test_end_to_end_footpod_field_and_belt(link, tmp_path):
    tm, c, task = await start_system(link, tmp_path)
    try:
        watch_dev = virtual_device(link, "watch")
        await watch_dev.power_on()
        watch = FakeWatch(watch_dev)
        pod_conn = await watch.connect(c.dev_a.random_address)
        await pod_conn.pair()
        rsc = await watch.subscribe(pod_conn, "1814", "2A53")
        _, speed, _, _ = struct.unpack("<BHBI", await asyncio.wait_for(rsc.get(), 2))
        assert speed == 320
        field_conn = await watch.connect(c.dev_b.random_address)
        fe01 = await watch.subscribe(field_conn, p.SERVICE_UUID, p.NOTIFY_UUID)
        await watch.write(field_conn, p.SERVICE_UUID, p.WRITE_UUID, p.QUERY)
        assert p.parse_status(await asyncio.wait_for(fe01.get(), 2)) is not None
        await watch.write(field_conn, p.SERVICE_UUID, p.WRITE_UUID, p.STOP)
        for _ in range(100):
            if p.STOP in tm.writes:
                break
            await asyncio.sleep(0.02)
        assert p.STOP in tm.writes
        await asyncio.sleep(0.4)
        snapshot = status_snapshot(c)
        assert snapshot["treadmill"]["link_up"] and snapshot["field_bridge"]["present"]
        assert any(b["steps"] > 0 for b in c.store.buckets(0, 10**10))
    finally:
        task.cancel()


async def test_runs_without_radio_b(link, tmp_path):
    _, c, task = await start_system(link, tmp_path, with_b=False)
    try:
        assert c.hub.link_up and c.footpod.advertising and c.ciq is None
        assert status_snapshot(c)["field_bridge"] == {"present": False, "advertising": False}
    finally:
        task.cancel()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bridge && uv run pytest tests/test_config.py tests/test_radios.py tests/test_app.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement config and radios**

`bridge/src/treadmill_bridge/config.py`:
```python
"""TOML configuration and the small persisted runtime state."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Config:
    api_token: str = ""
    treadmill_address: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    hold_speed_during_start: bool = False
    log_level: str = "INFO"
    state_dir: str = "/var/lib/treadmill-bridge"


def load_config(path: str) -> Config:
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    known = {f.name for f in fields(Config)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(unknown)}")
    config = Config(**data)
    if not config.api_token:
        raise ValueError("api_token must be set")
    return config


class State:
    def __init__(self, path: str) -> None:
        self._path = path
        self.treadmill_address: str | None = None
        if os.path.exists(path):
            with open(path) as handle:
                self.treadmill_address = json.load(handle).get("treadmill_address")

    def save_address(self, address: str) -> None:
        self.treadmill_address = address
        tmp = f"{self._path}.tmp"
        with open(tmp, "w") as handle:
            json.dump({"treadmill_address": address}, handle)
        os.replace(tmp, self._path)
```

`bridge/src/treadmill_bridge/radios.py`:
```python
"""Find the built-in (UART) and USB Bluetooth controllers, whatever their hci index."""

from __future__ import annotations

import os
import re


def find_controllers(sys_root: str = "/sys/class/bluetooth") -> dict[str, int]:
    if not os.path.isdir(sys_root):
        return {}
    found: dict[str, int] = {}
    for entry in sorted(os.listdir(sys_root)):
        match = re.fullmatch(r"hci(\d+)", entry)
        if not match:
            continue
        target = os.path.realpath(os.path.join(sys_root, entry, "device"))
        bus = "usb" if "/usb" in target else "uart"
        found.setdefault(bus, int(match.group(1)))
    return found
```

- [ ] **Step 4: Implement wiring and entry point**

`bridge/src/treadmill_bridge/app.py`:
```python
"""Component wiring shared by the service entry point and the end-to-end tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from bumble.device import Device
from bumble.hci import OwnAddressType

from .bridge import Bridge
from .ciq_link import CiqLink
from .config import Config, State
from .footpod import FootPod
from .hub import StatusHub
from .odometer import Odometer
from .sessions import SessionRecorder
from .storage import Store
from .treadmill import TreadmillClient

RETENTION_S = 90 * 86400
STARTED = time.monotonic()


@dataclass(frozen=True)
class Timings:
    poll_interval: float = 1.0
    write_gap: float = 0.4
    stale_after: float = 5.0
    backoff: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)
    grace_s: float = 30.0
    tick_s: float = 1.0
    flush_s: float = 10.0


@dataclass
class Components:
    dev_a: Device
    dev_b: Device | None
    hub: StatusHub
    odometer: Odometer
    store: Store
    recorder: SessionRecorder
    treadmill: TreadmillClient
    footpod: FootPod
    ciq: CiqLink | None
    bridge: Bridge
    timings: Timings

    async def run_ble(self) -> None:
        async def ticker() -> None:
            last_flush = time.monotonic()
            while True:
                await self.bridge.tick()
                if time.monotonic() - last_flush >= self.timings.flush_s:
                    self.recorder.flush(time.time())
                    self.store.purge(int(time.time()) - RETENTION_S)
                    last_flush = time.monotonic()
                await asyncio.sleep(self.timings.tick_s)

        await asyncio.gather(self.treadmill.run(), ticker())


def build(
    dev_a: Device,
    dev_b: Device | None,
    config: Config,
    store: Store,
    state: State,
    own_address_type: OwnAddressType,
    time_synced: Callable[[], bool],
    timings: Timings = Timings(),
) -> Components:
    hub = StatusHub()
    odometer = Odometer()
    recorder = SessionRecorder(store, time_synced)

    def on_status(status) -> None:
        steps, distance = odometer.update(status, time.monotonic())
        recorder.record(status, steps, distance, time.time())

    hub.on_status(on_status)
    hub.on_link(lambda up: None if up else odometer.stall())
    treadmill = TreadmillClient(
        dev_a,
        hub,
        config.treadmill_address or state.treadmill_address,
        own_address_type,
        on_address=state.save_address,
        poll_interval=timings.poll_interval,
        write_gap=timings.write_gap,
        stale_after=timings.stale_after,
        backoff=timings.backoff,
    )
    footpod = FootPod(dev_a, hub, odometer, own_address_type, config.hold_speed_during_start)
    footpod.install()
    ciq = None
    if dev_b is not None:
        ciq = CiqLink(dev_b, hub, treadmill.send_command, own_address_type)
        ciq.install()
    bridge = Bridge(hub, footpod, ciq, grace_s=timings.grace_s)
    return Components(dev_a, dev_b, hub, odometer, store, recorder, treadmill, footpod, ciq, bridge, timings)


def status_snapshot(c: Components) -> dict:
    latest = c.hub.latest
    return {
        "treadmill": {
            "link_up": c.hub.link_up,
            "belt_state": latest.state if latest else None,
            "speed_kmh": latest.speed_tenths / 10 if latest else None,
            "steps_counter": latest.steps if latest else None,
        },
        "foot_pod": {"advertising": c.footpod.advertising},
        "field_bridge": {"present": c.ciq is not None, "advertising": bool(c.ciq and c.ciq.advertising)},
        "totals": {"steps": c.odometer.steps_total, "distance_m": c.odometer.distance_m},
        "uptime_s": round(time.monotonic() - STARTED),
    }
```

`bridge/src/treadmill_bridge/main.py`:
```python
"""Service entry point: open the radios, wire components, serve the API."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

from aiohttp import web
from bumble.device import Device, DeviceConfiguration
from bumble.hci import OwnAddressType
from bumble.transport import open_transport

from .api import make_app
from .app import build, status_snapshot
from .config import State, load_config
from .radios import find_controllers
from .storage import Store

log = logging.getLogger("treadmill_bridge")
TIME_SYNCED_FLAG = "/run/systemd/timesync/synchronized"


async def open_device(index: int, name: str, keystore: str) -> tuple[Device, object]:
    transport = await open_transport(f"hci-socket:{index}")
    config = DeviceConfiguration(name=name, keystore=f"JsonKeyStore:{keystore}")
    device = Device.from_config_with_hci(config, transport.source, transport.sink)
    return device, transport


async def serve(config_path: str) -> None:
    config = load_config(config_path)
    logging.basicConfig(level=config.log_level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("bumble").setLevel(logging.WARNING)
    os.makedirs(config.state_dir, exist_ok=True)
    radios = find_controllers()
    if "uart" not in radios:
        raise SystemExit("built-in Bluetooth controller not found")
    keystore = os.path.join(config.state_dir, "keys.json")
    dev_a, transport_a = await open_device(radios["uart"], "treadmill-bridge-a", keystore)
    dev_b = transport_b = None
    if "usb" in radios:
        dev_b, transport_b = await open_device(radios["usb"], "treadmill-bridge-b", keystore)
    else:
        log.warning("no USB Bluetooth adapter: running without the field bridge")
    store = Store(os.path.join(config.state_dir, "bridge.db"))
    state = State(os.path.join(config.state_dir, "state.json"))
    components = build(
        dev_a, dev_b, config, store, state, OwnAddressType.PUBLIC,
        time_synced=lambda: os.path.exists(TIME_SYNCED_FLAG),
    )
    await dev_a.power_on()
    if dev_b is not None:
        await dev_b.power_on()
    log.info("radio A %s, radio B %s", dev_a.public_address, dev_b.public_address if dev_b else "absent")
    runner = web.AppRunner(make_app(store, lambda: status_snapshot(components), config.api_token))
    await runner.setup()
    await web.TCPSite(runner, config.api_host, config.api_port).start()
    try:
        await components.run_ble()
    finally:
        components.recorder.flush(time.time())
        await runner.cleanup()
        for transport in (transport_a, transport_b):
            if transport is not None:
                await transport.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Kingsmith R1 Pro to Garmin bridge")
    parser.add_argument("--config", default="/etc/treadmill-bridge/config.toml")
    args = parser.parse_args()
    asyncio.run(serve(args.config))
```

- [ ] **Step 5: Run to verify pass**

Run: `cd bridge && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit and push (CI)**

```bash
git add bridge
git commit -m "Wire the bridge together with config, radio discovery and the service entry point"
git push
gh run watch --exit-status $(gh run list --workflow bridge.yml --limit 1 --json databaseId -q '.[0].databaseId')
```
Expected: CI green.

---

### Task 11: Deployment to the Pi and hardware gate 1

**Files:**
- Create: `bridge/deploy/treadmill-bridge.service`, `bridge/deploy/prepare-radios.sh`, `bridge/deploy/install.sh`, `bridge/deploy/config.example.toml`, `bridge/Makefile`

**Interfaces:** Consumes `treadmill-bridge` console script.

- [ ] **Step 1: Deployment files**

`bridge/deploy/treadmill-bridge.service`:
```ini
[Unit]
Description=Kingsmith R1 Pro to Garmin bridge
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
User=treadmill
Group=treadmill
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW
ExecStartPre=+/opt/treadmill-bridge/bridge/deploy/prepare-radios.sh
ExecStart=/opt/treadmill-bridge/bridge/.venv/bin/treadmill-bridge --config /etc/treadmill-bridge/config.toml
Restart=always
RestartSec=5
StateDirectory=treadmill-bridge

[Install]
WantedBy=multi-user.target
```

`bridge/deploy/prepare-radios.sh`:
```bash
#!/bin/sh
# Bumble needs the controllers down (HCI user channel); bluetoothd must not own them.
for dev in /sys/class/bluetooth/hci*; do
    [ -e "$dev" ] || continue
    /usr/bin/hciconfig "$(basename "$dev")" down || true
done
```

`bridge/deploy/config.example.toml`:
```toml
# /etc/treadmill-bridge/config.toml
api_token = "CHANGE_ME"
# treadmill_address = "57:4C:4D:2F:0C:93/P"   # discovered and remembered automatically
api_port = 8080
hold_speed_during_start = false
log_level = "INFO"
```

`bridge/deploy/install.sh`:
```bash
#!/bin/sh
# Idempotent installer; run on the Pi as root from /opt/treadmill-bridge/bridge.
set -eu
cd "$(dirname "$0")/.."
id treadmill >/dev/null 2>&1 || useradd --system --home /var/lib/treadmill-bridge --shell /usr/sbin/nologin treadmill
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
UV_PYTHON_PREFERENCE=only-system uv sync --frozen --no-dev
install -d -m 0750 -o root -g treadmill /etc/treadmill-bridge
if [ ! -f /etc/treadmill-bridge/config.toml ]; then
    token=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
    sed "s/CHANGE_ME/$token/" deploy/config.example.toml > /etc/treadmill-bridge/config.toml
    chown root:treadmill /etc/treadmill-bridge/config.toml
    chmod 0640 /etc/treadmill-bridge/config.toml
fi
install -d -m 0750 -o treadmill -g treadmill /var/lib/treadmill-bridge
chmod 0755 deploy/prepare-radios.sh
systemctl disable --now bluetooth.service 2>/dev/null || true
install -m 0644 deploy/treadmill-bridge.service /etc/systemd/system/treadmill-bridge.service
systemctl daemon-reload
systemctl enable treadmill-bridge.service
systemctl restart treadmill-bridge.service
```

`bridge/Makefile` (recipe lines start with a TAB):
```make
PI ?= akhadiev@192.168.31.250
REMOTE_SRC ?= /tmp/treadmill-bridge-src

.PHONY: test deploy logs status

test:
	uv run pytest -q

deploy:
	rsync -a --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache ./ $(PI):$(REMOTE_SRC)/
	ssh $(PI) 'sudo install -d /opt/treadmill-bridge && sudo rsync -a --delete --exclude .venv $(REMOTE_SRC)/ /opt/treadmill-bridge/bridge/ && sudo sh /opt/treadmill-bridge/bridge/deploy/install.sh'

logs:
	ssh $(PI) 'journalctl -u treadmill-bridge -n 100 --no-pager'

status:
	ssh $(PI) 'systemctl is-active treadmill-bridge; TOKEN=$$(sudo grep api_token /etc/treadmill-bridge/config.toml | cut -d\" -f2); curl -s -H "Authorization: Bearer $$TOKEN" http://localhost:8080/api/v1/status'
```

- [ ] **Step 2: Stop spike leftovers on the Pi and carry over the watch bond**

```bash
ssh akhadiev@192.168.31.250 'pkill -f "^.venv/bin/python" || true; sudo systemctl stop dual 2>/dev/null || true'
```
After the first deploy (Step 3), copy the spike keystore so the watch's existing "Treadmill Pod" bond keeps working (same namespace `B8:27:EB:47:61:30/P`):
```bash
ssh akhadiev@192.168.31.250 'sudo systemctl stop treadmill-bridge && sudo install -m 0600 -o treadmill -g treadmill ~/spike/keys.json /var/lib/treadmill-bridge/keys.json && sudo systemctl start treadmill-bridge'
```

- [ ] **Step 3: Deploy**

Run: `make -C bridge deploy`
Expected: install completes; `systemctl is-active treadmill-bridge` → `active`.

- [ ] **Step 4: Hardware gate 1 — Bumble central to the real treadmill**

Run: `make -C bridge logs` and `make -C bridge status`
Expected (treadmill awake): logs contain `treadmill found at 57:4C:4D:2F:0C:93/P` and `treadmill connected`, status shows `"link_up": true`, `"field_bridge": {"present": false, ...}`, `"foot_pod": {"advertising": true}`.
If the treadmill is asleep the log shows `treadmill link lost: …` retries — this is not a failure; ask the user to wake it and re-check. **If Bumble cannot connect to an awake treadmill, STOP and report to the user.**

- [ ] **Step 5: Reboot resilience**

Run: `ssh akhadiev@192.168.31.250 'sudo reboot'`, wait for ping, then `make -C bridge status` and `ssh akhadiev@192.168.31.250 'nmcli -t -f 802-11-wireless.band con show netplan-wlan0-jawello-wifi; timedatectl show -p NTPSynchronized'`
Expected: service active, band `a`, `NTPSynchronized=yes`. If the band reverted, persist it in `/etc/netplan` (Raspberry Pi OS netplan file for wlan0: add `band: 5GHz` under the access point) and record a ruling.

- [ ] **Step 6: Commit and push**

```bash
git add bridge/deploy bridge/Makefile
git commit -m "Add Pi deployment: systemd unit, installer and make targets"
git push
```

---

### Task 12: Documentation

**Files:**
- Create: `bridge/README.md`
- Modify: `watch-field/README.md` (bridge note in "Known issue"), root `README.md` (status line)

- [ ] **Step 1: `bridge/README.md`**

```markdown
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
```

- [ ] **Step 2: Cross-links**

In `watch-field/README.md`, append to the "Known issue" section:
```markdown

**Workaround:** the [bridge](../bridge/README.md) on a Raspberry Pi holds the treadmill
link and re-publishes FE00 for this field (and a foot pod for native Garmin fields).
```
In root `README.md`, add under the table:
```markdown
Status: the watch field is done; the bridge runs on the Pi with radio A (treadmill +
foot pod); the field bridge waits for the USB adapter; the Android companion is next.
```

- [ ] **Step 3: Commit and push**

```bash
git add README.md bridge/README.md watch-field/README.md
git commit -m "Document the bridge and link the monorepo parts"
git push
```

---

### Task 13 (deferred — needs the USB adapter and the user): hardware gate 2 and acceptance

Not executed in this run. When the UB500 arrives:
1. Plug it in; `make status` must show `"field_bridge": {"present": true, ...}` after a service restart.
2. With the treadmill on and the watch in "Treadmill Walk": the watch holds the foot pod (radio A) and the field (radio B) at the same time (native speed AND field values, no flapping for 2 minutes). **If not, stop and report.**
3. Walk the acceptance checklist in `bridge/README.md` with the user.
