"""Oracle access for the reader account: pool, clock, catalogue, cursor info,
read-only query execution and setup diagnostics."""
from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import List, Optional, Tuple

from . import sources
from .config import Settings
from .sqlutil import is_select

try:
    import oracledb
except ImportError:  # allows running the offline parts / tests without the driver
    oracledb = None

_IDENT_RE = re.compile(r"^[A-Za-z][\w$#]*$")
# Marker added to statements this tool runs, so they can be told apart in V$SQL.
TOOL_MARKER = "/* siron-tracer */ "


class OracleError(Exception):
    pass


class Oracle:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pool = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ connection
    def _get_pool(self):
        if oracledb is None:
            raise OracleError("python-oracledb kurulu değil: pip install oracledb")
        if not self.settings.oracle_configured:
            raise OracleError("Oracle bağlantısı tanımlı değil (config.ini [oracle]).")
        with self._lock:
            if self._pool is None:
                if self.settings.oracle_client_lib_dir:
                    oracledb.init_oracle_client(lib_dir=self.settings.oracle_client_lib_dir)
                oracledb.defaults.fetch_lobs = False
                self._pool = oracledb.create_pool(
                    user=self.settings.oracle_user,
                    password=self.settings.oracle_password,
                    dsn=self.settings.oracle_dsn,
                    min=1, max=4, increment=1,
                )
        return self._pool

    def connect(self):
        conn = self._get_pool().acquire()
        conn.call_timeout = self.settings.query_timeout_sec * 1000
        return conn

    # ------------------------------------------------------------------ clock
    def now(self) -> Tuple[datetime, datetime]:
        """(UTC, DB-local) time from the database server, avoiding client clock skew."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT CAST(SYS_EXTRACT_UTC(SYSTIMESTAMP) AS TIMESTAMP), "
                        "CAST(SYSTIMESTAMP AS TIMESTAMP) FROM dual")
            return cur.fetchone()

    def local_to_utc(self, local: datetime) -> datetime:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT CAST(SYS_EXTRACT_UTC(FROM_TZ(TO_TIMESTAMP(:t, 'YYYY-MM-DD HH24:MI:SS'), "
                "TO_CHAR(SYSTIMESTAMP, 'TZR'))) AS TIMESTAMP) FROM dual",
                t=local.strftime("%Y-%m-%d %H:%M:%S"))
            return cur.fetchone()[0]

    # ------------------------------------------------------------------ audit
    def fetch_records(self, f: sources.AuditFilter, flush: bool = False) -> List[dict]:
        with self.connect() as conn:
            if flush and self.settings.audit_source == "unified":
                self.flush_unified(conn)
            return sources.fetch(conn, self.settings.audit_source, f)

    @staticmethod
    def flush_unified(conn) -> Optional[str]:
        """Write queued unified audit records (needed on 12.1 queued-write mode)."""
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN DBMS_AUDIT_MGMT.FLUSH_UNIFIED_AUDIT_TRAIL; END;")
            return None
        except Exception as exc:  # AUDIT_ADMIN missing etc. - not fatal
            return str(exc)

    # ------------------------------------------------------------------ catalogue
    def load_objects(self, schemas: List[str]) -> List[Tuple[str, str, str]]:
        """Siron objects; DBA_OBJECTS when readable (sees everything), else ALL_OBJECTS."""
        names = {"s%d" % i: s for i, s in enumerate(schemas)}
        sql = ("SELECT owner, object_name, object_type FROM %s WHERE owner IN (%s) "
               "AND object_type IN ('TABLE','VIEW','MATERIALIZED VIEW','SYNONYM','PACKAGE',"
               "'FUNCTION','PROCEDURE','SEQUENCE','TYPE')")
        marks = ",".join(":" + k for k in names)
        with self.connect() as conn, conn.cursor() as cur:
            try:
                cur.execute(sql % ("dba_objects", marks), names)
            except Exception:
                cur.execute(sql % ("all_objects", marks), names)
            return [tuple(r) for r in cur]

    # ------------------------------------------------------------------ cursor cache
    def cursor_info(self, sql_id: str) -> Tuple[List[str], List[tuple], List[tuple]]:
        """GV$SQL rows and captured binds for a SQL_ID."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT inst_id, child_number, plan_hash_value, executions, rows_processed, "
                "ROUND(elapsed_time/1e6, 3) elapsed_s, buffer_gets, module, action, "
                "TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') last_active "
                "FROM gv$sql WHERE sql_id = :sql_id ORDER BY inst_id, child_number",
                sql_id=sql_id)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            cur.execute(
                "SELECT inst_id, child_number, position, name, datatype_string, value_string, "
                "TO_CHAR(last_captured, 'YYYY-MM-DD HH24:MI:SS') "
                "FROM gv$sql_bind_capture WHERE sql_id = :sql_id "
                "ORDER BY inst_id, child_number, position", sql_id=sql_id)
            return cols, rows, cur.fetchall()

    # ------------------------------------------------------------------ run
    def run_select(self, sql: str, max_rows: Optional[int] = None):
        """Run a SELECT in a read-only transaction under the Siron schema.

        Returns (columns, rows, truncated).
        """
        sql = sql.strip().rstrip(";").strip()
        if not is_select(sql):
            raise OracleError("Yalnızca SELECT / WITH sorguları çalıştırılabilir.")
        schema = self.settings.current_schema
        if not _IDENT_RE.match(schema):
            raise OracleError("Geçersiz şema adı: %s" % schema)
        max_rows = max_rows or self.settings.max_result_rows
        with self.connect() as conn, conn.cursor() as cur:
            conn.rollback()
            cur.execute("ALTER SESSION SET CURRENT_SCHEMA = " + schema)
            if self.settings.nls_date_format:
                cur.execute("ALTER SESSION SET NLS_DATE_FORMAT = '%s'"
                            % self.settings.nls_date_format.replace("'", "''"))
            if self.settings.nls_timestamp_format:
                cur.execute("ALTER SESSION SET NLS_TIMESTAMP_FORMAT = '%s'"
                            % self.settings.nls_timestamp_format.replace("'", "''"))
            cur.execute("SET TRANSACTION READ ONLY")
            try:
                cur.execute(TOOL_MARKER + sql)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(max_rows + 1)
            finally:
                conn.rollback()
        truncated = len(rows) > max_rows
        return cols, [tuple(_display(v) for v in r) for r in rows[:max_rows]], truncated

    # ------------------------------------------------------------------ diagnostics
    def diagnostics(self) -> List[Tuple[str, bool, str]]:
        s = self.settings
        checks: List[Tuple[str, bool, str]] = []

        def check(title, sql, binds=None, fmt=lambda rows: ", ".join(" ".join(map(str, r)) for r in rows)):
            try:
                with self.connect() as conn, conn.cursor() as cur:
                    cur.execute(sql, binds or {})
                    rows = cur.fetchall()
                checks.append((title, True, fmt(rows) or "(boş)"))
            except Exception as exc:
                checks.append((title, False, str(exc)))

        check("Bağlantı / sürüm", "SELECT banner FROM v$version WHERE ROWNUM = 1")
        check("Unified Auditing (pure mode)",
              "SELECT value FROM v$option WHERE parameter = 'Unified Auditing'")
        # column names differ between 12c (USER_NAME) and 18c+ (ENTITY_NAME)
        check("Etkin unified audit politikaları", "SELECT * FROM audit_unified_enabled_policies")
        check("audit_trail parametresi (traditional)",
              "SELECT value FROM v$parameter WHERE name = 'audit_trail'")
        check("Son 1 saatte Siron audit kayıt sayısı (unified)",
              "SELECT COUNT(*) FROM unified_audit_trail WHERE dbusername = :u "
              "AND event_timestamp > SYSTIMESTAMP - INTERVAL '1' HOUR", {"u": s.siron_db_user})
        check("Son 1 saatte Siron audit kayıt sayısı (traditional)",
              "SELECT COUNT(*) FROM dba_audit_trail WHERE username = :u "
              "AND timestamp > SYSDATE - 1/24", {"u": s.siron_db_user})
        check("GV$SQL erişimi", "SELECT COUNT(*) FROM gv$sql WHERE ROWNUM <= 1")
        check("Siron şema nesneleri",
              "SELECT owner, COUNT(*) FROM all_objects WHERE owner = :u GROUP BY owner",
              {"u": s.current_schema})
        return checks


def _display(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S") if not value.microsecond \
            else value.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, (bytes, bytearray)):
        return value.hex().upper()
    return value
