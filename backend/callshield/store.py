"""SQLite persistence: event metadata and evidence, plus the few key-frame screenshots taken
at high-risk moments (no audio is ever stored)."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from .contracts import Envelope

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_ms   INTEGER NOT NULL,
    ended_ms     INTEGER,
    settings     TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    source       TEXT NOT NULL,
    body         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, event_type, id);
CREATE TABLE IF NOT EXISTS key_frames (
    frame_id     TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    t_ms         INTEGER NOT NULL,
    reason       TEXT NOT NULL,
    risk_index   INTEGER,
    jpeg         BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS key_frames_session ON key_frames(session_id, t_ms);
CREATE TABLE IF NOT EXISTS summaries (
    session_id   TEXT PRIMARY KEY,
    n_events     INTEGER NOT NULL,
    body         TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            rows = cur.fetchall()
            self.conn.commit()
            return rows

    def upsert_session(self, session_id: str, created_ms: int, settings: dict) -> None:
        self.execute(
            "INSERT INTO sessions(session_id, created_ms, settings) VALUES (?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET settings=excluded.settings, ended_ms=NULL",
            (session_id, created_ms, json.dumps(settings)),
        )

    def end_session(self, session_id: str, ended_ms: int) -> None:
        self.execute("UPDATE sessions SET ended_ms=? WHERE session_id=?", (ended_ms, session_id))

    def sessions(self) -> list[dict[str, Any]]:
        rows = self.execute("SELECT * FROM sessions ORDER BY created_ms DESC LIMIT 50")
        return [dict(r) | {"settings": json.loads(r["settings"])} for r in rows]

    def add_event(self, env: Envelope) -> None:
        self.execute(
            "INSERT INTO events(event_id, session_id, event_type, timestamp_ms, source, body) "
            "VALUES (?,?,?,?,?,?)",
            (env.event_id, env.session_id, env.event_type, env.timestamp_ms, env.source,
             env.model_dump_json()),
        )

    def events(self, session_id: str, event_types: list[str] | None = None,
               limit: int = 1000) -> list[dict[str, Any]]:
        sql = "SELECT body FROM events WHERE session_id=?"
        params: list[Any] = [session_id]
        if event_types:
            sql += f" AND event_type IN ({','.join('?' * len(event_types))})"
            params += event_types
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.execute(sql, tuple(params))
        return [json.loads(r["body"]) for r in reversed(rows)]

    def add_frame(self, frame_id: str, session_id: str, t_ms: int, reason: str,
                  risk_index: int | None, jpeg: bytes) -> None:
        self.execute("INSERT INTO key_frames VALUES (?,?,?,?,?,?)",
                     (frame_id, session_id, t_ms, reason, risk_index, jpeg))

    def frames(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.execute("SELECT frame_id, t_ms, reason, risk_index FROM key_frames "
                            "WHERE session_id=? ORDER BY t_ms", (session_id,))
        return [dict(r) for r in rows]

    def frame_jpeg(self, session_id: str, frame_id: str) -> bytes | None:
        rows = self.execute("SELECT jpeg FROM key_frames WHERE session_id=? AND frame_id=?",
                            (session_id, frame_id))
        return rows[0]["jpeg"] if rows else None

    def summary(self, session_id: str) -> tuple[int, dict] | None:
        rows = self.execute("SELECT n_events, body FROM summaries WHERE session_id=?", (session_id,))
        return (rows[0]["n_events"], json.loads(rows[0]["body"])) if rows else None

    def save_summary(self, session_id: str, n_events: int, body: dict) -> None:
        self.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?)",
                     (session_id, n_events, json.dumps(body, ensure_ascii=False)))

    def close(self) -> None:
        with self._lock:
            self.conn.close()
