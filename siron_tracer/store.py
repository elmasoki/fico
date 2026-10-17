"""Local SQLite store: captures (one per Siron screen/action), the audit records
copied for each capture and a cache of the Siron object catalogue.

Records are copied so the analysis keeps working after the Oracle audit
trail has been purged."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Set, Tuple

from .sources import RECORD_FIELDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    notes        TEXT,
    source       TEXT NOT NULL,
    db_user      TEXT NOT NULL,
    os_user      TEXT,
    host         TEXT,
    program      TEXT,
    client_id    TEXT,
    start_utc    TEXT NOT NULL,
    end_utc      TEXT,
    start_local  TEXT NOT NULL,
    end_local    TEXT,
    status       TEXT NOT NULL DEFAULT 'recording',
    is_noise     INTEGER NOT NULL DEFAULT 0,
    record_count INTEGER NOT NULL DEFAULT 0,
    message      TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id   INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    %s
);
CREATE INDEX IF NOT EXISTS records_capture ON records(capture_id, sql_id);
CREATE TABLE IF NOT EXISTS objects (
    owner TEXT NOT NULL,
    name  TEXT NOT NULL,
    type  TEXT NOT NULL,
    PRIMARY KEY (owner, name, type)
);
""" % ",\n    ".join("%s TEXT" % f for f in RECORD_FIELDS)

TS_FMT = "%Y-%m-%d %H:%M:%S.%f"


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(value, TS_FMT) if value else None


def fmt_ts(value: datetime) -> str:
    return value.strftime(TS_FMT)


class Store:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if path == ":memory:" else None
        with self._conn() as db:
            db.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        db = self._memory or sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # ------------------------------------------------------------------ captures
    def create_capture(self, name, source, db_user, start_utc, start_local, notes=None,
                       os_user=None, host=None, program=None, client_id=None,
                       end_utc=None, end_local=None, status="recording") -> int:
        with self._conn() as db:
            cur = db.execute(
                "INSERT INTO captures (name, notes, source, db_user, os_user, host, program, "
                "client_id, start_utc, end_utc, start_local, end_local, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, notes, source, db_user, os_user or None, host or None, program or None,
                 client_id or None, fmt_ts(start_utc), end_utc and fmt_ts(end_utc),
                 fmt_ts(start_local), end_local and fmt_ts(end_local), status,
                 fmt_ts(datetime.now())))
            return cur.lastrowid

    def get_capture(self, capture_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as db:
            return db.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()

    def list_captures(self) -> List[sqlite3.Row]:
        with self._conn() as db:
            return db.execute("SELECT * FROM captures ORDER BY id DESC").fetchall()

    def finish_capture(self, capture_id: int, end_utc: datetime, end_local: datetime):
        with self._conn() as db:
            db.execute("UPDATE captures SET end_utc = ?, end_local = ?, status = 'done' WHERE id = ?",
                       (fmt_ts(end_utc), fmt_ts(end_local), capture_id))

    def update_capture(self, capture_id: int, **fields):
        allowed = {"name", "notes", "is_noise", "message"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        with self._conn() as db:
            db.execute("UPDATE captures SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                       [fields[c] for c in cols] + [capture_id])

    def delete_capture(self, capture_id: int):
        with self._conn() as db:
            db.execute("DELETE FROM records WHERE capture_id = ?", (capture_id,))
            db.execute("DELETE FROM captures WHERE id = ?", (capture_id,))

    # ------------------------------------------------------------------ records
    def replace_records(self, capture_id: int, records: Iterable[dict]):
        records = list(records)
        cols = ", ".join(RECORD_FIELDS)
        marks = ", ".join("?" for _ in RECORD_FIELDS)
        with self._conn() as db:
            db.execute("DELETE FROM records WHERE capture_id = ?", (capture_id,))
            db.executemany(
                "INSERT INTO records (capture_id, %s) VALUES (?, %s)" % (cols, marks),
                [[capture_id] + [r.get(f) for f in RECORD_FIELDS] for r in records])
            db.execute("UPDATE captures SET record_count = ? WHERE id = ?", (len(records), capture_id))

    def records(self, capture_id: int) -> List[dict]:
        with self._conn() as db:
            rows = db.execute("SELECT * FROM records WHERE capture_id = ? ORDER BY ts, id",
                              (capture_id,)).fetchall()
            return [dict(r) for r in rows]

    def record(self, record_id: int) -> Optional[dict]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
            return dict(row) if row else None

    def noise_sql_ids(self) -> Set[str]:
        with self._conn() as db:
            rows = db.execute(
                "SELECT DISTINCT r.sql_id FROM records r JOIN captures c ON c.id = r.capture_id "
                "WHERE c.is_noise = 1 AND r.sql_id IS NOT NULL").fetchall()
            return {r[0] for r in rows}

    # ------------------------------------------------------------------ objects
    def replace_objects(self, objects: Iterable[Tuple[str, str, str]]):
        with self._conn() as db:
            db.execute("DELETE FROM objects")
            db.executemany("INSERT OR IGNORE INTO objects (owner, name, type) VALUES (?,?,?)", objects)

    def objects(self) -> dict:
        """{(owner, name): type}"""
        with self._conn() as db:
            return {(r["owner"], r["name"]): r["type"]
                    for r in db.execute("SELECT owner, name, type FROM objects")}
