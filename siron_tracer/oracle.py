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
    def fetch_records(self, f: sources.AuditFilter, flush: bool = False,
                      source: Optional[str] = None) -> List[dict]:
        source = source or self.settings.audit_source
        with self.connect() as conn:
            if flush and source == "unified":
                self.flush_unified(conn)
            return sources.fetch(conn, source, f)

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
    def load_catalog(self, schemas: List[str]) -> dict:
        """Data dictionary of the Siron schemas: objects, tables, columns, comments,
        PK/UK/FK constraints. DBA_ views when readable, otherwise ALL_ views."""
        names = {"s%d" % i: s for i, s in enumerate(schemas)}
        owners = ",".join(":" + k for k in names)
        queries = {
            "objects": "SELECT owner, object_name, object_type FROM {p}_objects WHERE owner IN ({o}) "
                       "AND object_type IN ('TABLE','VIEW','MATERIALIZED VIEW','SYNONYM','PACKAGE',"
                       "'FUNCTION','PROCEDURE','SEQUENCE','TYPE') AND object_name NOT LIKE 'BIN$%'",
            "tables": "SELECT o.owner, o.object_name, o.object_type, t.num_rows, "
                      "TO_CHAR(t.last_analyzed, 'YYYY-MM-DD HH24:MI'), c.comments "
                      "FROM {p}_objects o "
                      "LEFT JOIN {p}_tables t ON t.owner = o.owner AND t.table_name = o.object_name "
                      "LEFT JOIN {p}_tab_comments c ON c.owner = o.owner AND c.table_name = o.object_name "
                      "WHERE o.owner IN ({o}) AND o.object_type IN ('TABLE','VIEW','MATERIALIZED VIEW') "
                      "AND o.object_name NOT LIKE 'BIN$%' ORDER BY o.object_type",
            "columns": "SELECT c.owner, c.table_name, c.column_name, c.column_id, c.data_type, "
                       "c.data_length, c.data_precision, c.data_scale, c.nullable, cc.comments "
                       "FROM {p}_tab_columns c LEFT JOIN {p}_col_comments cc ON cc.owner = c.owner "
                       "AND cc.table_name = c.table_name AND cc.column_name = c.column_name "
                       "WHERE c.owner IN ({o}) AND c.table_name NOT LIKE 'BIN$%'",
            "constraints": "SELECT owner, constraint_name, constraint_type, table_name, r_owner, "
                           "r_constraint_name FROM {p}_constraints "
                           "WHERE (owner IN ({o}) AND constraint_type IN ('P','U','R')) "
                           "OR (owner, constraint_name) IN (SELECT r_owner, r_constraint_name "
                           "FROM {p}_constraints WHERE owner IN ({o}) AND constraint_type = 'R')",
            "cons_columns": "SELECT cc.owner, cc.constraint_name, cc.column_name, cc.position "
                            "FROM {p}_cons_columns cc JOIN {p}_constraints c ON c.owner = cc.owner "
                            "AND c.constraint_name = cc.constraint_name "
                            "WHERE (c.owner IN ({o}) AND c.constraint_type IN ('P','U','R')) "
                            "OR (c.owner, c.constraint_name) IN (SELECT r_owner, r_constraint_name "
                            "FROM {p}_constraints WHERE owner IN ({o}) AND constraint_type = 'R')",
            # packages / procedures / views / triggers and what they reference
            "dependencies": "SELECT owner, name, type, referenced_owner, referenced_name, referenced_type "
                            "FROM {p}_dependencies WHERE owner IN ({o}) "
                            "AND referenced_type IN ('TABLE','VIEW','MATERIALIZED VIEW','PACKAGE','PROCEDURE',"
                            "'FUNCTION','SYNONYM','TYPE') "
                            "AND referenced_owner NOT IN ('SYS','SYSTEM','PUBLIC','XDB','MDSYS','CTXSYS','ORDSYS')",
        }
        out = {}
        with self.connect() as conn, conn.cursor() as cur:
            cur.arraysize = 5000
            prefix = "dba"
            try:
                cur.execute("SELECT 1 FROM dba_tab_columns WHERE ROWNUM = 1")
                cur.fetchall()
            except Exception:
                prefix = "all"
            for name, sql in queries.items():
                cur.execute(sql.format(p=prefix, o=owners), names)
                out[name] = [tuple(r) for r in cur]
        return out

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
    def _prepare_read_only(self, conn, cur, schema: Optional[str] = None):
        schema = schema or self.settings.current_schema
        if not _IDENT_RE.match(schema):
            raise OracleError("Geçersiz şema adı: %s" % schema)
        conn.rollback()
        cur.execute("ALTER SESSION SET CURRENT_SCHEMA = " + schema)
        if self.settings.nls_date_format:
            cur.execute("ALTER SESSION SET NLS_DATE_FORMAT = '%s'"
                        % self.settings.nls_date_format.replace("'", "''"))
        if self.settings.nls_timestamp_format:
            cur.execute("ALTER SESSION SET NLS_TIMESTAMP_FORMAT = '%s'"
                        % self.settings.nls_timestamp_format.replace("'", "''"))
        cur.execute("SET TRANSACTION READ ONLY")

    @staticmethod
    def _check_select(sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()
        if not is_select(sql):
            raise OracleError("Yalnızca SELECT / WITH sorguları çalıştırılabilir.")
        return sql

    def run_select(self, sql: str, max_rows: Optional[int] = None, binds: Optional[dict] = None,
                   timeout_sec: Optional[int] = None, schema: Optional[str] = None):
        """Run a SELECT in a read-only transaction under the Siron schema (or `schema`).

        Returns (columns, rows, truncated).
        """
        sql = self._check_select(sql)
        max_rows = max_rows or self.settings.max_result_rows
        with self.connect() as conn, conn.cursor() as cur:
            if timeout_sec:
                conn.call_timeout = timeout_sec * 1000
            self._prepare_read_only(conn, cur, schema)
            try:
                cur.execute(TOOL_MARKER + sql, binds or {})
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(max_rows + 1)
            finally:
                conn.rollback()
        truncated = len(rows) > max_rows
        return cols, [tuple(_display(v) for v in r) for r in rows[:max_rows]], truncated

    def stream_select(self, sql: str, max_rows: int, batch: int = 2000, schema: Optional[str] = None):
        """Yield the column names, then row batches (for full CSV exports)."""
        sql = self._check_select(sql)
        with self.connect() as conn, conn.cursor() as cur:
            conn.call_timeout = 0
            self._prepare_read_only(conn, cur, schema)
            cur.arraysize = batch
            try:
                cur.execute(TOOL_MARKER + sql)
                yield [d[0] for d in cur.description]
                sent = 0
                while sent < max_rows:
                    rows = cur.fetchmany(min(batch, max_rows - sent))
                    if not rows:
                        break
                    sent += len(rows)
                    yield [tuple(_display(v) for v in r) for r in rows]
            finally:
                conn.rollback()

    def check_relation(self, child, child_cols, parent, parent_cols, sample: int = 5000) -> Tuple[int, int]:
        """How many distinct child values (from a sample) exist in the parent: (matched, total)."""
        for name in (child[1], parent[1]) + tuple(child_cols) + tuple(parent_cols):
            if '"' in name:
                raise OracleError("Geçersiz ad: %s" % name)
        q = lambda key: '"%s"."%s"' % key if key[0] else '"%s"' % key[1]
        picks = ", ".join('c."%s" AS k%d' % (c, i) for i, c in enumerate(child_cols))
        keys = ", ".join("k%d" % i for i in range(len(child_cols)))
        not_null = " AND ".join('c."%s" IS NOT NULL' % c for c in child_cols)
        cond = " AND ".join('p."%s" = s.k%d' % (p, i) for i, p in enumerate(parent_cols))
        sql = ("WITH s AS (SELECT DISTINCT {keys} FROM (SELECT {picks} FROM {child} c "
               "WHERE {nn} AND ROWNUM <= :n)) "
               "SELECT (SELECT COUNT(*) FROM s), "
               "(SELECT COUNT(*) FROM s WHERE EXISTS (SELECT 1 FROM {parent} p WHERE {cond})) "
               "FROM dual").format(keys=keys, picks=picks, child=q(child), nn=not_null,
                                   parent=q(parent), cond=cond)
        _, rows, _ = self.run_select(sql, binds={"n": sample}, max_rows=1)
        total, matched = rows[0]
        return int(matched or 0), int(total or 0)

    def profile(self, key, table, sample_rows: int = 200000, columns=None, progress=None) -> dict:
        """Column statistics of a catalogue table (see profiling.py)."""
        from .profiling import profile_table
        run = lambda sql: self.run_select(sql, max_rows=100, timeout_sec=max(self.settings.query_timeout_sec, 300))
        return profile_table(run, key, table, sample_rows, columns, progress)

    # ------------------------------------------------------------------ diagnostics
    def diagnostics(self, users: Optional[List[str]] = None, schemas: Optional[List[str]] = None
                    ) -> List[Tuple[str, bool, str]]:
        s = self.settings
        users = users or [s.siron_db_user]
        schemas = schemas or s.schemas
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
        ubinds = {"u%d" % i: u for i, u in enumerate(users)}
        uin = ", ".join(":" + k for k in ubinds)
        check("Son 1 saatte audit kayıtları (unified) — %s" % ", ".join(users),
              "SELECT dbusername, COUNT(*) FROM unified_audit_trail WHERE dbusername IN (%s) "
              "AND event_timestamp > SYSTIMESTAMP - INTERVAL '1' HOUR GROUP BY dbusername" % uin, ubinds)
        if s.audit_source != "unified":
            check("Son 1 saatte audit kayıtları (traditional)",
                  "SELECT username, COUNT(*) FROM dba_audit_trail WHERE username IN (%s) "
                  "AND timestamp > SYSDATE - 1/24 GROUP BY username" % uin, ubinds)
        check("GV$SQL erişimi", "SELECT COUNT(*) FROM gv$sql WHERE ROWNUM <= 1")
        sbinds = {"s%d" % i: x for i, x in enumerate(schemas)}
        check("Şema nesneleri — %s" % ", ".join(schemas),
              "SELECT owner, COUNT(*) FROM all_objects WHERE owner IN (%s) GROUP BY owner"
              % ", ".join(":" + k for k in sbinds), sbinds)
        check("Bağımlılık görünümü (paket/view analizi)",
              "SELECT COUNT(*) FROM dba_dependencies WHERE owner IN (%s)" % ", ".join(":" + k for k in sbinds), sbinds)
        return checks


def _display(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S") if not value.microsecond \
            else value.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, (bytes, bytearray)):
        return value.hex().upper()
    return value
