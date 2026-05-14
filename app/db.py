"""SQLite layer: config singleton, passes, events.

All timestamps stored as ISO-8601 UTC strings ('2026-05-14T20:13:45+00:00').
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS passes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    rise_ts           TEXT NOT NULL,
    culminate_ts      TEXT NOT NULL,
    set_ts            TEXT NOT NULL,
    max_elevation     REAL NOT NULL,
    azimuth_rise      REAL NOT NULL,
    azimuth_set       REAL NOT NULL,
    triggered_prewarn INTEGER NOT NULL DEFAULT 0,
    triggered_start   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(rise_ts)
);

CREATE INDEX IF NOT EXISTS idx_passes_rise ON passes(rise_ts);

CREATE TABLE IF NOT EXISTS events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def _db_path() -> Path:
    raw = os.environ.get("DATA_DIR", "data")
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p / "hue-iss.sqlite"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


# --------------------------------------------------------------------- config

def get_config(key: str, default: Optional[str] = None) -> Optional[str]:
    with connect() as c:
        row = c.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_config(key: str, value: Optional[str]) -> None:
    with connect() as c:
        if value is None:
            c.execute("DELETE FROM config WHERE key = ?", (key,))
        else:
            c.execute(
                "INSERT INTO config(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def get_all_config() -> dict[str, str]:
    with connect() as c:
        rows = c.execute("SELECT key, value FROM config").fetchall()
        return {r["key"]: r["value"] for r in rows}


# --------------------------------------------------------------------- passes

def upsert_pass(
    rise_ts: datetime,
    culminate_ts: datetime,
    set_ts: datetime,
    max_elevation: float,
    azimuth_rise: float,
    azimuth_set: float,
) -> int:
    with connect() as c:
        c.execute(
            """INSERT INTO passes
               (rise_ts, culminate_ts, set_ts, max_elevation, azimuth_rise, azimuth_set)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(rise_ts) DO UPDATE SET
                 culminate_ts = excluded.culminate_ts,
                 set_ts = excluded.set_ts,
                 max_elevation = excluded.max_elevation,
                 azimuth_rise = excluded.azimuth_rise,
                 azimuth_set = excluded.azimuth_set""",
            (
                _iso(rise_ts),
                _iso(culminate_ts),
                _iso(set_ts),
                max_elevation,
                azimuth_rise,
                azimuth_set,
            ),
        )
        row = c.execute(
            "SELECT id FROM passes WHERE rise_ts = ?", (_iso(rise_ts),)
        ).fetchone()
        return int(row["id"])


def list_upcoming_passes(now: datetime, limit: int = 10) -> list[sqlite3.Row]:
    with connect() as c:
        return list(
            c.execute(
                "SELECT * FROM passes WHERE rise_ts > ? ORDER BY rise_ts ASC LIMIT ?",
                (_iso(now), limit),
            ).fetchall()
        )


def list_recent_passes(now: datetime, limit: int = 10) -> list[sqlite3.Row]:
    with connect() as c:
        return list(
            c.execute(
                "SELECT * FROM passes WHERE rise_ts <= ? ORDER BY rise_ts DESC LIMIT ?",
                (_iso(now), limit),
            ).fetchall()
        )


def mark_pass_triggered(pass_id: int, *, prewarn: bool = False, start: bool = False) -> None:
    sets = []
    if prewarn:
        sets.append("triggered_prewarn = 1")
    if start:
        sets.append("triggered_start = 1")
    if not sets:
        return
    with connect() as c:
        c.execute(f"UPDATE passes SET {', '.join(sets)} WHERE id = ?", (pass_id,))


def delete_passes_before(cutoff: datetime) -> int:
    with connect() as c:
        cur = c.execute("DELETE FROM passes WHERE set_ts < ?", (_iso(cutoff),))
        return cur.rowcount


def delete_future_untriggered_passes() -> int:
    """Used before recomputing passes from a fresh TLE."""
    now_iso = _iso(datetime.now(timezone.utc))
    with connect() as c:
        cur = c.execute(
            "DELETE FROM passes WHERE rise_ts > ? AND triggered_prewarn = 0 AND triggered_start = 0",
            (now_iso,),
        )
        return cur.rowcount


# --------------------------------------------------------------------- events

def append_event(kind: str, payload: dict[str, Any] | None = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO events(ts, kind, payload_json) VALUES (?, ?, ?)",
            (_iso(datetime.now(timezone.utc)), kind, json.dumps(payload) if payload else None),
        )


def recent_events(limit: int = 50) -> list[sqlite3.Row]:
    with connect() as c:
        return list(
            c.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        )


# --------------------------------------------------------------------- helpers

def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)
