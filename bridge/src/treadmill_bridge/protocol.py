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
