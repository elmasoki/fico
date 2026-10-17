"""Local SQLite store.

Holds everything the tool learns so the analysis keeps working after the
Oracle audit trail has been purged: captures and their audit records, the
data dictionary, annotations (mapping decisions), column profiles, the screen
inventory, background jobs, saved result snapshots and an activity log.

Older database files are upgraded in place (missing columns are added)."""
from __future__ import annotations

import getpass
import json
import os
import socket
import sqlite3
import threading
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .catalog import Catalog, Column, Constraint, Dependency, Table
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
    owner TEXT NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS cat_dependencies (
    owner TEXT NOT NULL, name TEXT NOT NULL, type TEXT,
    ref_owner TEXT, ref_name TEXT NOT NULL, ref_type TEXT
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
CREATE TABLE IF NOT EXISTS screens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT, name TEXT NOT NULL, description TEXT, priority TEXT,
    status TEXT NOT NULL DEFAULT 'todo', notes TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    owner TEXT NOT NULL, table_name TEXT NOT NULL, column_name TEXT NOT NULL,
    data TEXT NOT NULL, profiled_at TEXT NOT NULL,
    PRIMARY KEY (owner, table_name, column_name)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, title TEXT NOT NULL, params TEXT,
    status TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
    message TEXT, result TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, os_user TEXT, host TEXT, action TEXT NOT NULL,
    detail TEXT, sql_text TEXT, rows INTEGER
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS capture_markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER NOT NULL, ts TEXT NOT NULL, label TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extract_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, screen_id INTEGER, capture_id INTEGER, sql_id TEXT,
    sql_text TEXT NOT NULL, removed TEXT, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screen_sqls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_id INTEGER NOT NULL, capture_id INTEGER NOT NULL, sql_id TEXT NOT NULL,
    note TEXT, created_at TEXT NOT NULL,
    UNIQUE (screen_id, capture_id, sql_id)
);
""" % ",\n    ".join("%s TEXT" % f for f in RECORD_FIELDS)

# columns added after the first release: (table, column, definition)
MIGRATIONS = [
    ("captures", "db_users", "TEXT"),
    ("captures", "schema_name", "TEXT"),
    ("captures", "kind", "TEXT NOT NULL DEFAULT 'screen'"),
    ("captures", "screen_id", "INTEGER"),
    ("annotations", "sensitive", "INTEGER"),
    ("annotations", "extract_filter", "TEXT"),
    ("captures", "excluded_sources", "TEXT"),
]

TS_FMT = "%Y-%m-%d %H:%M:%S.%f"
_KEEP = object()


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(value, TS_FMT) if value else None


def fmt_ts(value: datetime) -> str:
    return value.strftime(TS_FMT)


def now() -> str:
    return fmt_ts(datetime.now())


class Store:
    def __init__(self, path: str):
        self.path = path
        self._catalog: Optional[Catalog] = None
        self._lock = threading.RLock()
        self.data_version = 0    # bumped on every change that affects the analysis
        self.checks_version = 0  # bumped when a relation data check is stored
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if path == ":memory:" else None
        with self._conn() as db:
            db.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                existing = {r[1] for r in db.execute("PRAGMA table_info(%s)" % table)}
                if column not in existing:
                    db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))
            if self._memory is None:
                db.execute("PRAGMA journal_mode = WAL")

    def _conn(self) -> sqlite3.Connection:
        db = self._memory or sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _bump(self):
        self.data_version += 1

    # ------------------------------------------------------------------ captures
    def create_capture(self, name, source, db_users, start_utc, start_local, notes=None,
                       os_user=None, host=None, program=None, client_id=None,
                       end_utc=None, end_local=None, status="recording", schema=None,
                       kind="screen", screen_id=None) -> int:
        if isinstance(db_users, str):
            db_users = [db_users]
        db_users = [u.strip().upper() for u in db_users if u and u.strip()]
        with self._lock, self._conn() as db:
            cur = db.execute(
                "INSERT INTO captures (name, notes, source, db_user, db_users, schema_name, kind, screen_id, "
                "os_user, host, program, client_id, start_utc, end_utc, start_local, end_local, status, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, notes, source, db_users[0] if db_users else "", ",".join(db_users),
                 (schema or "").upper() or None, kind or "screen", screen_id or None,
                 os_user or None, host or None, program or None, client_id or None,
                 fmt_ts(start_utc), end_utc and fmt_ts(end_utc), fmt_ts(start_local),
                 end_local and fmt_ts(end_local), status, now()))
            self._bump()
            return cur.lastrowid

    def get_capture(self, capture_id: int) -> Optional[dict]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            return _capture(row) if row else None

    def list_captures(self) -> List[dict]:
        with self._conn() as db:
            return [_capture(r) for r in db.execute("SELECT * FROM captures ORDER BY id DESC")]

    def finish_capture(self, capture_id: int, end_utc: datetime, end_local: datetime):
        with self._lock, self._conn() as db:
            db.execute("UPDATE captures SET end_utc = ?, end_local = ?, status = 'done' WHERE id = ?",
                       (fmt_ts(end_utc), fmt_ts(end_local), capture_id))
            self._bump()

    def reset_capture(self, capture_id: int, start_utc: datetime, start_local: datetime):
        """Restart a running capture's window at the given time, dropping anything captured before it."""
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM records WHERE capture_id = ?", (capture_id,))
            db.execute("UPDATE captures SET start_utc = ?, start_local = ?, record_count = 0 WHERE id = ?",
                       (fmt_ts(start_utc), fmt_ts(start_local), capture_id))
            self._bump()

    def update_capture(self, capture_id: int, **fields):
        allowed = {"name", "notes", "is_noise", "message", "kind", "screen_id", "schema_name", "excluded_sources"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        with self._lock, self._conn() as db:
            db.execute("UPDATE captures SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                       [fields[c] for c in cols] + [capture_id])
            self._bump()

    def delete_capture(self, capture_id: int):
        self.delete_captures([capture_id])

    def delete_captures(self, capture_ids: Iterable[int]) -> int:
        """Delete captures with their records; saved result snapshots are kept (unlinked)."""
        ids = [(int(i),) for i in capture_ids]
        if not ids:
            return 0
        with self._lock, self._conn() as db:
            db.executemany("DELETE FROM records WHERE capture_id = ?", ids)
            db.executemany("UPDATE snapshots SET capture_id = NULL WHERE capture_id = ?", ids)
            db.executemany("DELETE FROM screen_sqls WHERE capture_id = ?", ids)
            db.executemany("DELETE FROM capture_markers WHERE capture_id = ?", ids)
            db.executemany("UPDATE extract_queries SET capture_id = NULL WHERE capture_id = ?", ids)
            deleted = sum(db.execute("DELETE FROM captures WHERE id = ?", i).rowcount for i in ids)
            self._bump()
        return deleted

    # ------------------------------------------------------------------ records
    def replace_records(self, capture_id: int, records: Iterable[dict]):
        records = list(records)
        cols = ", ".join(RECORD_FIELDS)
        marks = ", ".join("?" for _ in RECORD_FIELDS)
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM records WHERE capture_id = ?", (capture_id,))
            db.executemany(
                "INSERT INTO records (capture_id, %s) VALUES (?, %s)" % (cols, marks),
                [[capture_id] + [r.get(f) for f in RECORD_FIELDS] for r in records])
            db.execute("UPDATE captures SET record_count = ? WHERE id = ?", (len(records), capture_id))
            self._bump()

    def records(self, capture_id: int) -> List[dict]:
        with self._conn() as db:
            rows = db.execute("SELECT * FROM records WHERE capture_id = ? ORDER BY ts, id",
                              (capture_id,)).fetchall()
            return [dict(r) for r in rows]

    def search_sql(self, text: str, limit: int = 100) -> List[dict]:
        with self._conn() as db:
            rows = db.execute(
                "SELECT r.capture_id, c.name AS capture_name, r.sql_id, MIN(r.sql_text) AS sql_text, "
                "COUNT(*) AS n FROM records r JOIN captures c ON c.id = r.capture_id "
                "WHERE r.sql_text LIKE ? GROUP BY r.capture_id, c.name, r.sql_id LIMIT ?",
                ("%" + text + "%", limit)).fetchall()
            return [dict(r) for r in rows]

    def search_binds(self, value: str, capture_id: Optional[int] = None, limit: int = 2000) -> List[dict]:
        """Records whose raw audit binds contain `value` (case-insensitive); callers check the parsed values."""
        sql = ("SELECT r.id, r.capture_id, c.name AS capture_name, c.start_local AS capture_start, r.sql_id, "
               "r.sql_text, r.sql_binds, r.ts FROM records r JOIN captures c ON c.id = r.capture_id "
               "WHERE r.sql_binds IS NOT NULL AND UPPER(r.sql_binds) LIKE UPPER(?)")
        args: list = ["%" + value + "%"]
        if capture_id is not None:
            sql += " AND r.capture_id = ?"
            args.append(capture_id)
        sql += " ORDER BY c.start_local DESC, r.ts LIMIT ?"
        args.append(limit)
        with self._conn() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def noise_sql_ids(self) -> Set[str]:
        with self._conn() as db:
            rows = db.execute(
                "SELECT DISTINCT r.sql_id FROM records r JOIN captures c ON c.id = r.capture_id "
                "WHERE c.is_noise = 1 AND r.sql_id IS NOT NULL").fetchall()
            return {r[0] for r in rows}

    # ------------------------------------------------------------------ meta / settings
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as db:
            row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def set_meta(self, key: str, value: str):
        with self._lock, self._conn() as db:
            db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def get_list(self, key: str) -> List[str]:
        return json.loads(self.get_meta("list:" + key, "[]"))

    def set_list(self, key: str, values: Iterable[str]):
        clean = list(dict.fromkeys(v.strip().upper() for v in values if v and v.strip()))
        self.set_meta("list:" + key, json.dumps(clean))

    # ------------------------------------------------------------------ catalogue
    def replace_catalog(self, data: dict):
        """data: objects, tables, columns, constraints, cons_columns, dependencies (tuples)."""
        cols_by_cons = {}
        for owner, cname, column, position in sorted(data.get("cons_columns", []),
                                                     key=lambda r: (r[0], r[1], r[3] or 0)):
            cols_by_cons.setdefault((owner, cname), []).append(column)
        with self._lock, self._conn() as db:
            for table in ("objects", "cat_tables", "cat_columns", "cat_constraints", "cat_dependencies"):
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
            db.executemany("INSERT INTO cat_dependencies VALUES (?,?,?,?,?,?)", data.get("dependencies", []))
        self.set_meta("catalog_version", now())
        self._catalog = None
        self._bump()

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
            deps = [Dependency(r["owner"], r["name"], r["type"], r["ref_owner"], r["ref_name"], r["ref_type"])
                    for r in db.execute("SELECT * FROM cat_dependencies")]
        self._catalog = Catalog(tables, objects, constraints, version, deps)
        return self._catalog

    # ------------------------------------------------------------------ annotations
    def annotations(self) -> dict:
        """{(owner, table, column or ''): row}"""
        with self._conn() as db:
            return {(r["owner"], r["table_name"], r["column_name"]): dict(r)
                    for r in db.execute("SELECT * FROM annotations")}

    def save_annotation(self, owner, table, column, status=_KEEP, note=_KEEP, target=_KEEP,
                        sensitive=_KEEP, extract_filter=_KEEP):
        """Upsert; fields left at their default keep their stored value."""
        owner, column = owner or "", column or ""
        key = (owner, table, column)
        with self._lock, self._conn() as db:
            row = db.execute("SELECT * FROM annotations WHERE owner = ? AND table_name = ? AND column_name = ?",
                             key).fetchone()
            cur = dict(row) if row else {}
            values = {}
            for name, value in (("status", status), ("note", note), ("target", target),
                                ("sensitive", sensitive), ("extract_filter", extract_filter)):
                values[name] = cur.get(name) if value is _KEEP else value
            for name in ("status", "note", "target", "extract_filter"):
                values[name] = (values[name] or "").strip() or None
            if values["sensitive"] in ("", None):
                values["sensitive"] = None
            else:
                values["sensitive"] = 1 if str(values["sensitive"]) in ("1", "True", "true") else 0
            if all(v is None for v in values.values()):
                db.execute("DELETE FROM annotations WHERE owner = ? AND table_name = ? AND column_name = ?", key)
                return
            db.execute("INSERT OR REPLACE INTO annotations (owner, table_name, column_name, status, note, target, "
                       "updated_at, sensitive, extract_filter) VALUES (?,?,?,?,?,?,?,?,?)",
                       key + (values["status"], values["note"], values["target"], now(),
                              values["sensitive"], values["extract_filter"]))

    def replace_annotations(self, rows: List[dict]):
        """Restore a full annotation backup (used to undo an Excel import)."""
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM annotations")
            for r in rows:
                db.execute("INSERT INTO annotations (owner, table_name, column_name, status, note, target, "
                           "updated_at, sensitive, extract_filter) VALUES (?,?,?,?,?,?,?,?,?)",
                           (r["owner"], r["table_name"], r["column_name"], r.get("status"), r.get("note"),
                            r.get("target"), r.get("updated_at"), r.get("sensitive"), r.get("extract_filter")))

    # ------------------------------------------------------------------ screen inventory
    def list_screens(self) -> List[dict]:
        with self._conn() as db:
            return [dict(r) for r in db.execute("SELECT * FROM screens ORDER BY module, name")]

    def get_screen(self, screen_id: int) -> Optional[dict]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM screens WHERE id = ?", (screen_id,)).fetchone()
            return dict(row) if row else None

    def add_screen(self, name, module=None, description=None, priority=None, status="todo", notes=None) -> int:
        with self._lock, self._conn() as db:
            existing = db.execute("SELECT id FROM screens WHERE IFNULL(module,'') = ? AND name = ?",
                                  (module or "", name)).fetchone()
            if existing:
                return existing[0]
            cur = db.execute("INSERT INTO screens (module, name, description, priority, status, notes, created_at) "
                             "VALUES (?,?,?,?,?,?,?)", (module or None, name, description or None,
                                                         priority or None, status or "todo", notes or None, now()))
            return cur.lastrowid

    def update_screen(self, screen_id: int, **fields):
        allowed = {"module", "name", "description", "priority", "status", "notes"}
        cols = [k for k in fields if k in allowed]
        if cols:
            with self._lock, self._conn() as db:
                db.execute("UPDATE screens SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                           [fields[c] or None for c in cols] + [screen_id])

    def delete_screen(self, screen_id: int):
        with self._lock, self._conn() as db:
            db.execute("UPDATE captures SET screen_id = NULL WHERE screen_id = ?", (screen_id,))
            db.execute("DELETE FROM screen_sqls WHERE screen_id = ?", (screen_id,))
            db.execute("UPDATE extract_queries SET screen_id = NULL WHERE screen_id = ?", (screen_id,))
            db.execute("DELETE FROM screens WHERE id = ?", (screen_id,))
            self._bump()

    # ------------------------------------------------------------------ recording markers
    def add_marker(self, capture_id: int, ts: str, label: str) -> int:
        with self._lock, self._conn() as db:
            return db.execute("INSERT INTO capture_markers (capture_id, ts, label, created_at) VALUES (?,?,?,?)",
                              (capture_id, ts, label, now())).lastrowid

    def markers(self, capture_id: int) -> List[dict]:
        with self._conn() as db:
            return [dict(r) for r in db.execute("SELECT * FROM capture_markers WHERE capture_id = ? ORDER BY ts, id",
                                                (capture_id,)).fetchall()]

    def get_marker(self, marker_id: int) -> Optional[dict]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM capture_markers WHERE id = ?", (marker_id,)).fetchone()
            return dict(row) if row else None

    def update_marker(self, marker_id: int, label: str):
        with self._lock, self._conn() as db:
            db.execute("UPDATE capture_markers SET label = ? WHERE id = ?", (label, marker_id))

    def delete_marker(self, marker_id: int):
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM capture_markers WHERE id = ?", (marker_id,))

    # ------------------------------------------------------------------ extraction queries
    def add_extract_query(self, name: str, sql_text: str, screen_id: Optional[int] = None,
                          capture_id: Optional[int] = None, sql_id: Optional[str] = None,
                          removed: Optional[List[str]] = None, note: Optional[str] = None) -> int:
        """Save a generalised screen query; the same capture + SQL_ID + screen is updated, not duplicated."""
        with self._lock, self._conn() as db:
            row = None
            if sql_id:
                row = db.execute("SELECT id FROM extract_queries WHERE sql_id = ? AND IFNULL(capture_id, 0) = ? "
                                 "AND IFNULL(screen_id, 0) = ?", (sql_id, capture_id or 0, screen_id or 0)).fetchone()
            payload = (name, screen_id, capture_id, sql_id, sql_text, json.dumps(removed or [], ensure_ascii=False),
                       note or None)
            if row:
                db.execute("UPDATE extract_queries SET name = ?, screen_id = ?, capture_id = ?, sql_id = ?, "
                           "sql_text = ?, removed = ?, note = ? WHERE id = ?", payload + (row[0],))
                return row[0]
            return db.execute("INSERT INTO extract_queries (name, screen_id, capture_id, sql_id, sql_text, removed, "
                              "note, created_at) VALUES (?,?,?,?,?,?,?,?)", payload + (now(),)).lastrowid

    def extract_queries(self, screen_id: Optional[int] = None) -> List[dict]:
        sql = ("SELECT q.*, s.name AS screen_name, s.module AS screen_module, c.name AS capture_name, "
               "c.start_local AS capture_start FROM extract_queries q "
               "LEFT JOIN screens s ON s.id = q.screen_id LEFT JOIN captures c ON c.id = q.capture_id")
        args: list = []
        if screen_id is not None:
            sql += " WHERE q.screen_id = ?"
            args.append(screen_id)
        sql += " ORDER BY s.module, s.name, q.id"
        with self._conn() as db:
            out = []
            for r in db.execute(sql, args).fetchall():
                d = dict(r)
                d["removed"] = json.loads(d["removed"] or "[]")
                out.append(d)
            return out

    def get_extract_query(self, query_id: int) -> Optional[dict]:
        return next((q for q in self.extract_queries() if q["id"] == query_id), None)

    def update_extract_query(self, query_id: int, name: str, sql_text: str, note: Optional[str] = None):
        with self._lock, self._conn() as db:
            db.execute("UPDATE extract_queries SET name = ?, sql_text = ?, note = ? WHERE id = ?",
                       (name, sql_text, note or None, query_id))

    def delete_extract_query(self, query_id: int):
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM extract_queries WHERE id = ?", (query_id,))

    # ------------------------------------------------------------------ screen <-> SQL links
    def link_sql(self, screen_id: int, capture_id: int, sql_id: str, note: Optional[str] = None) -> int:
        """Attach a captured SQL to an inventory screen; linking again only updates the note."""
        with self._lock, self._conn() as db:
            db.execute("INSERT INTO screen_sqls (screen_id, capture_id, sql_id, note, created_at) VALUES (?,?,?,?,?) "
                       "ON CONFLICT (screen_id, capture_id, sql_id) DO UPDATE SET note = excluded.note",
                       (screen_id, capture_id, sql_id, note or None, now()))
            return db.execute("SELECT id FROM screen_sqls WHERE screen_id = ? AND capture_id = ? AND sql_id = ?",
                              (screen_id, capture_id, sql_id)).fetchone()[0]

    def unlink_sql(self, link_id: int):
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM screen_sqls WHERE id = ?", (link_id,))

    def screen_sqls(self, screen_id: Optional[int] = None, capture_id: Optional[int] = None,
                    sql_id: Optional[str] = None) -> List[dict]:
        """Links with the capture (name, time) and the SQL (text, action, first run) they point to."""
        where, args = [], []
        for col, val in (("l.screen_id", screen_id), ("l.capture_id", capture_id), ("l.sql_id", sql_id)):
            if val is not None:
                where.append("%s = ?" % col)
                args.append(val)
        sql = ("SELECT l.*, c.name AS capture_name, c.start_local AS capture_start, c.kind AS capture_kind, "
               "s.name AS screen_name, s.module AS screen_module, "
               "(SELECT r.sql_text FROM records r WHERE r.capture_id = l.capture_id AND r.sql_id = l.sql_id "
               " ORDER BY r.ts LIMIT 1) AS sql_text, "
               "(SELECT r.action FROM records r WHERE r.capture_id = l.capture_id AND r.sql_id = l.sql_id "
               " ORDER BY r.ts LIMIT 1) AS action, "
               "(SELECT MIN(r.ts) FROM records r WHERE r.capture_id = l.capture_id AND r.sql_id = l.sql_id) AS first_ts "
               "FROM screen_sqls l JOIN captures c ON c.id = l.capture_id JOIN screens s ON s.id = l.screen_id")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.module, s.name, c.start_local, l.id"
        with self._conn() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    # ------------------------------------------------------------------ profiles
    def save_profile(self, owner: str, table: str, column: str, data: dict):
        with self._lock, self._conn() as db:
            db.execute("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?)",
                       (owner or "", table, column, json.dumps(data, default=str), now()))

    def profiles(self, key: Optional[Tuple[Optional[str], str]] = None) -> Dict[Tuple, dict]:
        """{(owner, table, column): data (+ 'profiled_at')}"""
        sql, args = "SELECT * FROM profiles", ()
        if key:
            sql, args = sql + " WHERE owner = ? AND table_name = ?", (key[0] or "", key[1])
        with self._conn() as db:
            out = {}
            for r in db.execute(sql, args):
                d = json.loads(r["data"])
                d["profiled_at"] = r["profiled_at"]
                out[(r["owner"] or None, r["table_name"], r["column_name"])] = d
            return out

    # ------------------------------------------------------------------ snapshots
    def add_snapshot(self, title, sql_text, columns, rows, truncated=False, capture_id=None,
                     sql_id=None, note=None, sources=None) -> int:
        with self._lock, self._conn() as db:
            cur = db.execute(
                "INSERT INTO snapshots (capture_id, sql_id, title, note, sql_text, columns, rows, sources, "
                "truncated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (capture_id, sql_id, title, note, sql_text, json.dumps(list(columns)),
                 json.dumps([list(r) for r in rows], default=str), json.dumps(sources or []),
                 1 if truncated else 0, now()))
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
        with self._lock, self._conn() as db:
            db.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))

    # ------------------------------------------------------------------ relation checks
    def relation_checks(self) -> dict:
        with self._conn() as db:
            return {r[0]: (r[1], r[2]) for r in db.execute("SELECT relation_id, matched, total FROM relation_checks")}

    def save_relation_check(self, relation_id: str, matched: int, total: int):
        with self._lock, self._conn() as db:
            db.execute("INSERT OR REPLACE INTO relation_checks VALUES (?,?,?,?)",
                       (relation_id, matched, total, now()))
            self.checks_version += 1

    # ------------------------------------------------------------------ jobs
    def create_job(self, kind: str, title: str, params: Optional[dict] = None) -> int:
        with self._lock, self._conn() as db:
            cur = db.execute("INSERT INTO jobs (kind, title, params, created_at) VALUES (?,?,?,?)",
                             (kind, title, json.dumps(params or {}, default=str), now()))
            return cur.lastrowid

    def update_job(self, job_id: int, **fields):
        allowed = {"status", "progress", "message", "result", "started_at", "finished_at"}
        if "result" in fields and not isinstance(fields["result"], str):
            fields["result"] = json.dumps(fields["result"], default=str)
        cols = [k for k in fields if k in allowed]
        with self._lock, self._conn() as db:
            db.execute("UPDATE jobs SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                       [fields[c] for c in cols] + [job_id])

    def get_job(self, job_id: int) -> Optional[dict]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _job(row) if row else None

    def list_jobs(self, limit: int = 100, kind: Optional[str] = None) -> List[dict]:
        sql, args = "SELECT * FROM jobs", []
        if kind:
            sql += " WHERE kind = ?"
            args.append(kind)
        with self._conn() as db:
            return [_job(r) for r in db.execute(sql + " ORDER BY id DESC LIMIT ?", args + [limit])]

    def fail_stale_jobs(self):
        """Jobs left running by a previous process cannot finish any more."""
        with self._lock, self._conn() as db:
            db.execute("UPDATE jobs SET status = 'failed', message = 'Uygulama yeniden başlatıldı' "
                       "WHERE status IN ('queued', 'running')")

    # ------------------------------------------------------------------ activity log
    def log(self, action: str, detail: str = "", sql_text: Optional[str] = None, rows: Optional[int] = None):
        try:
            user = getpass.getuser()
        except Exception:
            user = None
        with self._lock, self._conn() as db:
            db.execute("INSERT INTO activity (ts, os_user, host, action, detail, sql_text, rows) VALUES (?,?,?,?,?,?,?)",
                       (now(), user, socket.gethostname(), action, detail, sql_text, rows))

    def activity(self, limit: int = 500, action: Optional[str] = None) -> List[dict]:
        sql, args = "SELECT * FROM activity", []
        if action:
            sql += " WHERE action = ?"
            args.append(action)
        with self._conn() as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY id DESC LIMIT ?", args + [limit])]


def _capture(row) -> dict:
    d = dict(row)
    d["db_users"] = [u for u in (d.get("db_users") or d.get("db_user") or "").split(",") if u]
    d["kind"] = d.get("kind") or "screen"
    d["excluded_sources"] = json.loads(d.get("excluded_sources") or "[]")
    return d


def _job(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d["params"] or "{}")
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    return d
