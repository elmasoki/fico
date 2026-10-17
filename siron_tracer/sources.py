"""Queries that read Siron's SQL activity from Oracle.

Every source returns rows with the columns in RECORD_FIELDS so that the rest
of the application does not care where a record came from.

Time windows are passed in UTC (audit trails) and in DB-local time
(V$SQL.LAST_ACTIVE_TIME is a DATE in the server's time zone).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from .sqlutil import compute_sql_id, format_audit_binds

RECORD_FIELDS = [
    "ts", "db_user", "os_user", "host", "program", "session_id", "entry_id",
    "statement_id", "action", "obj_schema", "obj_name", "sql_text", "sql_binds",
    "return_code", "client_id", "sql_id",
]

TS_FMT = "%Y-%m-%d %H:%M:%S.%f"
ORA_TS_FMT = "YYYY-MM-DD HH24:MI:SS.FF6"


@dataclass
class AuditFilter:
    db_user: str
    start_utc: datetime
    end_utc: datetime
    start_local: datetime
    end_local: datetime
    os_user: Optional[str] = None
    host: Optional[str] = None
    program: Optional[str] = None
    client_id: Optional[str] = None
    max_rows: int = 20000


def _ts(value: datetime) -> str:
    return value.strftime(TS_FMT)


def _optional_filters(f: AuditFilter, columns: Dict[str, Optional[str]], binds: dict) -> str:
    """LIKE filters (case-insensitive, % allowed) for the columns a source has."""
    sql = []
    for key in ("os_user", "host", "program", "client_id"):
        value, column = getattr(f, key), columns.get(key)
        if value and column:
            sql.append(" AND UPPER(%s) LIKE UPPER(:%s)" % (column, key))
            binds[key] = value
    return "".join(sql)


def _limit(sql: str) -> str:
    return "SELECT * FROM (%s) WHERE ROWNUM <= :max_rows" % sql


def _rows(cursor) -> List[dict]:
    out = []
    for row in cursor:
        rec = dict(zip(RECORD_FIELDS, row))
        if isinstance(rec["ts"], datetime):
            rec["ts"] = _ts(rec["ts"])
        for key in ("session_id", "entry_id", "statement_id", "return_code"):
            if rec[key] is not None:
                rec[key] = str(rec[key])
        if rec["sql_text"] and not rec["sql_id"]:
            rec["sql_id"] = compute_sql_id(rec["sql_text"])
        out.append(rec)
    return out


# --------------------------------------------------------------------------- unified

_unified_ts_column: Dict[str, str] = {}


def unified_ts_column(conn) -> str:
    """EVENT_TIMESTAMP_UTC exists from 18c; on 12c EVENT_TIMESTAMP is already UTC."""
    key = conn.dsn if hasattr(conn, "dsn") else "default"
    if key not in _unified_ts_column:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT event_timestamp_utc FROM unified_audit_trail WHERE 1 = 0")
            _unified_ts_column[key] = "event_timestamp_utc"
        except Exception:
            _unified_ts_column[key] = "event_timestamp"
    return _unified_ts_column[key]


def fetch_unified(conn, f: AuditFilter) -> List[dict]:
    ts = unified_ts_column(conn)
    binds = {"db_user": f.db_user, "start_ts": _ts(f.start_utc), "end_ts": _ts(f.end_utc),
             "max_rows": f.max_rows}
    extra = _optional_filters(f, {"os_user": "os_username", "host": "userhost",
                                  "program": "client_program_name",
                                  "client_id": "client_identifier"}, binds)
    sql = f"""
        SELECT {ts}, dbusername, os_username, userhost, client_program_name,
               sessionid, entry_id, statement_id, action_name, object_schema,
               object_name, sql_text, sql_binds, return_code, client_identifier,
               CAST(NULL AS VARCHAR2(13))
          FROM unified_audit_trail
         WHERE {ts} >= TO_TIMESTAMP(:start_ts, '{ORA_TS_FMT}')
           AND {ts} <  TO_TIMESTAMP(:end_ts, '{ORA_TS_FMT}')
           AND dbusername = :db_user{extra}
         ORDER BY {ts}, sessionid, entry_id"""
    with conn.cursor() as cur:
        cur.execute(_limit(sql), binds)
        return _rows(cur)


# --------------------------------------------------------------------------- traditional

def fetch_traditional(conn, f: AuditFilter) -> List[dict]:
    """DBA_AUDIT_TRAIL (AUDIT_TRAIL=DB,EXTENDED). SQL_TEXT is cut at 2000 chars here."""
    binds = {"db_user": f.db_user, "start_ts": _ts(f.start_utc), "end_ts": _ts(f.end_utc),
             "max_rows": f.max_rows}
    extra = _optional_filters(f, {"os_user": "os_username", "host": "userhost",
                                  "client_id": "client_id"}, binds)
    sql = f"""
        SELECT CAST(SYS_EXTRACT_UTC(extended_timestamp) AS TIMESTAMP), username,
               os_username, userhost, terminal, sessionid, entryid, statementid,
               action_name, owner, obj_name, TO_CHAR(sql_text), TO_CHAR(sql_bind),
               returncode, client_id, CAST(NULL AS VARCHAR2(13))
          FROM dba_audit_trail
         WHERE extended_timestamp >= FROM_TZ(TO_TIMESTAMP(:start_ts, '{ORA_TS_FMT}'), 'UTC')
           AND extended_timestamp <  FROM_TZ(TO_TIMESTAMP(:end_ts, '{ORA_TS_FMT}'), 'UTC')
           AND username = :db_user{extra}
         ORDER BY extended_timestamp, sessionid, entryid"""
    with conn.cursor() as cur:
        cur.execute(_limit(sql), binds)
        return _rows(cur)


def fetch_aud(conn, f: AuditFilter) -> List[dict]:
    """SYS.AUD$ directly: same data as DBA_AUDIT_TRAIL but SQLTEXT is a full CLOB."""
    binds = {"db_user": f.db_user, "start_ts": _ts(f.start_utc), "end_ts": _ts(f.end_utc),
             "max_rows": f.max_rows}
    extra = _optional_filters(f, {"os_user": "a.spare1", "host": "a.userhost",
                                  "client_id": "a.clientid"}, binds)
    sql = f"""
        SELECT a.ntimestamp#, a.userid, a.spare1, a.userhost, a.terminal,
               a.sessionid, a.entryid, a.statement, aa.name, a.obj$creator,
               a.obj$name, a.sqltext, a.sqlbind, a.returncode, a.clientid,
               CAST(NULL AS VARCHAR2(13))
          FROM sys.aud$ a
          LEFT JOIN sys.audit_actions aa ON aa.action = a.action#
         WHERE a.ntimestamp# >= TO_TIMESTAMP(:start_ts, '{ORA_TS_FMT}')
           AND a.ntimestamp# <  TO_TIMESTAMP(:end_ts, '{ORA_TS_FMT}')
           AND a.userid = :db_user{extra}
         ORDER BY a.ntimestamp#, a.sessionid, a.entryid"""
    with conn.cursor() as cur:
        cur.execute(_limit(sql), binds)
        return _rows(cur)


# --------------------------------------------------------------------------- cursor cache

_CURSOR_FILTER = f"""
         s.parsing_user_id = (SELECT user_id FROM all_users WHERE username = :db_user)
     AND s.last_active_time >= TO_TIMESTAMP(:start_ts, '{ORA_TS_FMT}')
     AND s.last_active_time <= TO_TIMESTAMP(:end_ts, '{ORA_TS_FMT}')"""


def fetch_cursor_cache(conn, f: AuditFilter) -> List[dict]:
    """GV$SQL + GV$SQL_BIND_CAPTURE: no auditing needed, but binds are sampled
    (roughly every 15 minutes) and only one row per cursor is available."""
    binds = {"db_user": f.db_user, "start_ts": _ts(f.start_local), "end_ts": _ts(f.end_local)}
    extra = _optional_filters(f, {"program": "s.module"}, binds)
    sql = f"""
        SELECT s.last_active_time, :db_user, NULL, NULL,
               s.module || NVL2(s.action, ' / ' || s.action, NULL), s.inst_id,
               s.child_number, NULL,
               DECODE(s.command_type, 2, 'INSERT', 3, 'SELECT', 6, 'UPDATE',
                      7, 'DELETE', 47, 'PL/SQL EXECUTE', 189, 'MERGE',
                      TO_CHAR(s.command_type)),
               NULL, NULL, s.sql_fulltext, NULL, NULL, NULL, s.sql_id
          FROM gv$sql s
         WHERE {_CURSOR_FILTER}{extra}
         ORDER BY s.last_active_time"""
    with conn.cursor() as cur:
        cur.execute(_limit(sql), dict(binds, max_rows=f.max_rows))
        rows = _rows(cur)

    bind_sql = f"""
        SELECT b.inst_id, b.sql_id, b.child_number, b.position, b.value_string
          FROM gv$sql_bind_capture b
          JOIN gv$sql s ON s.inst_id = b.inst_id AND s.sql_id = b.sql_id
                       AND s.child_number = b.child_number
         WHERE {_CURSOR_FILTER}{extra}
         ORDER BY b.inst_id, b.sql_id, b.child_number, b.position"""
    captured: Dict[tuple, Dict[int, Optional[str]]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(bind_sql, binds)
            for inst_id, sql_id, child, position, value in cur:
                captured.setdefault((str(inst_id), sql_id, str(child)), {})[position] = value
    except Exception:
        captured = {}
    for rec in rows:
        values = captured.get((rec["session_id"], rec["sql_id"], rec["entry_id"]))
        if values:
            rec["sql_binds"] = format_audit_binds(values.get(i) for i in range(1, max(values) + 1))
    return rows


FETCHERS = {
    "unified": fetch_unified,
    "traditional": fetch_traditional,
    "aud$": fetch_aud,
    "cursor_cache": fetch_cursor_cache,
}


def fetch(conn, source: str, f: AuditFilter) -> List[dict]:
    return FETCHERS[source](conn, f)
