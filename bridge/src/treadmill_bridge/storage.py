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
