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
