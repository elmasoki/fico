"""Local SQLite store: captures (one per Siron screen/action), the audit records
copied for each capture and a cache of the Siron object catalogue.

Records are copied so the analysis keeps working after the Oracle audit
trail has been purged."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Set, Tuple

from .catalog import Catalog, Column, Constraint, Table
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
CREATE TABLE IF NOT EXISTS cat_tables (
    owner TEXT NOT NULL, name TEXT NOT NULL, type TEXT, num_rows INTEGER,
    last_analyzed TEXT, comments TEXT,
    PRIMARY KEY (owner, name)
);
CREATE TABLE IF NOT EXISTS cat_columns (
    owner TEXT NOT NULL, table_name TEXT NOT NULL, name TEXT NOT NULL, position INTEGER,
    data_type TEXT, length INTEGER, precision INTEGER, scale INTEGER, nullable TEXT, comments TEXT,
    PRIMARY KEY (owner, table_name, name)
);
CREATE TABLE IF NOT EXISTS cat_constraints (
    owner TEXT NOT NULL, name TEXT NOT NULL, type TEXT, table_name TEXT,
    r_owner TEXT, r_name TEXT, columns TEXT,
    PRIMARY KEY (owner, name)
);
CREATE TABLE IF NOT EXISTS annotations (
    owner TEXT NOT NULL, table_name TEXT NOT NULL, column_name TEXT NOT NULL DEFAULT '',
    status TEXT, note TEXT, target TEXT, updated_at TEXT,
    PRIMARY KEY (owner, table_name, column_name)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER, sql_id TEXT, title TEXT NOT NULL, note TEXT,
    sql_text TEXT NOT NULL, columns TEXT NOT NULL, rows TEXT NOT NULL,
    sources TEXT, truncated INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relation_checks (
    relation_id TEXT PRIMARY KEY, matched INTEGER, total INTEGER, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
""" % ",\n    ".join("%s TEXT" % f for f in RECORD_FIELDS)

TS_FMT = "%Y-%m-%d %H:%M:%S.%f"


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(value, TS_FMT) if value else None


def fmt_ts(value: datetime) -> str:
    return value.strftime(TS_FMT)


class Store:
    def __init__(self, path: str):
        self.path = path
        self._catalog: Optional[Catalog] = None
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

    def search_sql(self, text: str, limit: int = 100) -> List[dict]:
        with self._conn() as db:
            rows = db.execute(
                "SELECT r.capture_id, c.name AS capture_name, r.sql_id, MIN(r.sql_text) AS sql_text, "
                "COUNT(*) AS n FROM records r JOIN captures c ON c.id = r.capture_id "
                "WHERE r.sql_text LIKE ? GROUP BY r.capture_id, c.name, r.sql_id LIMIT ?",
                ("%" + text + "%", limit)).fetchall()
            return [dict(r) for r in rows]

    def noise_sql_ids(self) -> Set[str]:
        with self._conn() as db:
            rows = db.execute(
                "SELECT DISTINCT r.sql_id FROM records r JOIN captures c ON c.id = r.capture_id "
                "WHERE c.is_noise = 1 AND r.sql_id IS NOT NULL").fetchall()
            return {r[0] for r in rows}

    # ------------------------------------------------------------------ objects
    def objects(self) -> dict:
        """{(owner, name): type}"""
        with self._conn() as db:
            return {(r["owner"], r["name"]): r["type"]
                    for r in db.execute("SELECT owner, name, type FROM objects")}

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as db:
            row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def set_meta(self, key: str, value: str):
        with self._conn() as db:
            db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # ------------------------------------------------------------------ catalogue
    def replace_catalog(self, data: dict):
        """data: objects, tables, columns, constraints, cons_columns (lists of tuples)."""
        cols_by_cons = {}
        for owner, cname, column, position in sorted(data.get("cons_columns", []), key=lambda r: (r[0], r[1], r[3] or 0)):
            cols_by_cons.setdefault((owner, cname), []).append(column)
        with self._conn() as db:
            for table in ("objects", "cat_tables", "cat_columns", "cat_constraints"):
                db.execute("DELETE FROM %s" % table)
            db.executemany("INSERT OR IGNORE INTO objects (owner, name, type) VALUES (?,?,?)",
                           data.get("objects", []))
            db.executemany("INSERT OR IGNORE INTO cat_tables VALUES (?,?,?,?,?,?)", data.get("tables", []))
            db.executemany("INSERT OR IGNORE INTO cat_columns VALUES (?,?,?,?,?,?,?,?,?,?)",
                           data.get("columns", []))
            db.executemany(
                "INSERT OR IGNORE INTO cat_constraints VALUES (?,?,?,?,?,?,?)",
                [tuple(c[:6]) + (",".join(cols_by_cons.get((c[0], c[1]), [])),)
                 for c in data.get("constraints", [])])
        self.set_meta("catalog_version", fmt_ts(datetime.now()))
        self._catalog = None

    def catalog(self) -> Catalog:
        version = self.get_meta("catalog_version", "")
        if self._catalog is not None and self._catalog.version == version:
            return self._catalog
        with self._conn() as db:
            columns = {}
            for r in db.execute("SELECT * FROM cat_columns ORDER BY owner, table_name, position"):
                columns.setdefault((r["owner"], r["table_name"]), []).append(Column(
                    r["owner"], r["table_name"], r["name"], r["position"], r["data_type"], r["length"],
                    r["precision"], r["scale"], r["nullable"] != "N", r["comments"]))
            tables = [Table(r["owner"], r["name"], r["type"], r["num_rows"], r["last_analyzed"],
                            r["comments"], columns.get((r["owner"], r["name"]), []))
                      for r in db.execute("SELECT * FROM cat_tables")]
            objects = {(r["owner"], r["name"]): r["type"] for r in db.execute("SELECT * FROM objects")}
            constraints = [Constraint(r["owner"], r["name"], r["type"], r["table_name"], r["r_owner"],
                                      r["r_name"], tuple(c for c in (r["columns"] or "").split(",") if c))
                           for r in db.execute("SELECT * FROM cat_constraints")]
        self._catalog = Catalog(tables, objects, constraints, version)
        return self._catalog

    # ------------------------------------------------------------------ annotations
    def annotations(self) -> dict:
        """{(owner, table, column or ''): row}"""
        with self._conn() as db:
            return {(r["owner"], r["table_name"], r["column_name"]): dict(r)
                    for r in db.execute("SELECT * FROM annotations")}

    def save_annotation(self, owner, table, column, status, note, target=None):
        owner, column = owner or "", column or ""
        with self._conn() as db:
            if not (status or note or target):
                db.execute("DELETE FROM annotations WHERE owner = ? AND table_name = ? AND column_name = ?",
                           (owner, table, column))
            else:
                db.execute("INSERT OR REPLACE INTO annotations VALUES (?,?,?,?,?,?,?)",
                           (owner, table, column, status or None, note or None, target or None,
                            fmt_ts(datetime.now())))

    # ------------------------------------------------------------------ snapshots
    def add_snapshot(self, title, sql_text, columns, rows, truncated=False, capture_id=None,
                     sql_id=None, note=None, sources=None) -> int:
        with self._conn() as db:
            cur = db.execute(
                "INSERT INTO snapshots (capture_id, sql_id, title, note, sql_text, columns, rows, sources, "
                "truncated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (capture_id, sql_id, title, note, sql_text, json.dumps(list(columns)),
                 json.dumps([list(r) for r in rows], default=str), json.dumps(sources or []),
                 1 if truncated else 0, fmt_ts(datetime.now())))
            return cur.lastrowid

    def snapshots(self, capture_id: Optional[int] = None) -> List[dict]:
        sql = "SELECT * FROM snapshots"
        args: tuple = ()
        if capture_id is not None:
            sql += " WHERE capture_id = ?"
            args = (capture_id,)
        with self._conn() as db:
            out = []
            for r in db.execute(sql + " ORDER BY id", args):
                d = dict(r)
                d["columns"] = json.loads(d["columns"])
                d["rows"] = [tuple(x) for x in json.loads(d["rows"])]
                d["sources"] = json.loads(d["sources"] or "[]")
                out.append(d)
            return out

    def delete_snapshot(self, snapshot_id: int):
        with self._conn() as db:
            db.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))

    # ------------------------------------------------------------------ relation checks
    def relation_checks(self) -> dict:
        with self._conn() as db:
            return {r[0]: (r[1], r[2]) for r in db.execute("SELECT relation_id, matched, total FROM relation_checks")}

    def save_relation_check(self, relation_id: str, matched: int, total: int):
        with self._conn() as db:
            db.execute("INSERT OR REPLACE INTO relation_checks VALUES (?,?,?,?)",
                       (relation_id, matched, total, fmt_ts(datetime.now())))
