"""Settings loaded from config.ini (path in SIRON_TRACER_CONFIG) with env overrides."""
from __future__ import annotations

import configparser
import os
import secrets
from dataclasses import dataclass, field
from typing import List, Optional

AUDIT_SOURCES = ("unified", "traditional", "aud$", "cursor_cache")


@dataclass
class Settings:
    # Oracle connection of the *reader* account (not the Siron account itself)
    oracle_dsn: str = ""
    oracle_user: str = ""
    oracle_password: str = ""
    oracle_client_lib_dir: Optional[str] = None  # set to use thick mode (Instant Client)

    # Siron
    siron_db_user: str = "SIRON"
    siron_schemas: List[str] = field(default_factory=list)

    # Behaviour
    audit_source: str = "unified"
    max_audit_rows: int = 20000
    max_result_rows: int = 500
    query_timeout_sec: int = 60
    flush_unified_on_stop: bool = True
    nls_date_format: Optional[str] = None
    nls_timestamp_format: Optional[str] = None

    # App
    sqlite_path: str = "data/siron_tracer.db"
    secret_key: str = ""
    host: str = "127.0.0.1"
    port: int = 5000

    @property
    def schemas(self) -> List[str]:
        return self.siron_schemas or [self.siron_db_user]

    @property
    def current_schema(self) -> str:
        return self.schemas[0]

    @property
    def oracle_configured(self) -> bool:
        return bool(self.oracle_dsn and self.oracle_user)


def _get(cp: configparser.ConfigParser, section: str, key: str, env: str, default=None):
    if os.environ.get(env):
        return os.environ[env]
    if cp.has_option(section, key):
        value = cp.get(section, key).strip()
        return value if value != "" else default
    return default


def load_settings(path: Optional[str] = None) -> Settings:
    path = path or os.environ.get("SIRON_TRACER_CONFIG", "config.ini")
    cp = configparser.ConfigParser(interpolation=None)
    if os.path.exists(path):
        cp.read(path, encoding="utf-8")

    s = Settings()
    s.oracle_dsn = _get(cp, "oracle", "dsn", "ORACLE_DSN", "")
    s.oracle_user = _get(cp, "oracle", "user", "ORACLE_USER", "")
    s.oracle_password = _get(cp, "oracle", "password", "ORACLE_PASSWORD", "")
    s.oracle_client_lib_dir = _get(cp, "oracle", "client_lib_dir", "ORACLE_CLIENT_LIB_DIR")

    s.siron_db_user = _get(cp, "siron", "db_user", "SIRON_DB_USER", "SIRON").upper()
    schemas = _get(cp, "siron", "schemas", "SIRON_SCHEMAS", "") or ""
    s.siron_schemas = [x.strip().upper() for x in schemas.split(",") if x.strip()] or [s.siron_db_user]

    s.audit_source = _get(cp, "app", "audit_source", "SIRON_AUDIT_SOURCE", "unified").lower()
    if s.audit_source not in AUDIT_SOURCES:
        raise ValueError("audit_source must be one of %s" % ", ".join(AUDIT_SOURCES))
    s.max_audit_rows = int(_get(cp, "app", "max_audit_rows", "SIRON_MAX_AUDIT_ROWS", 20000))
    s.max_result_rows = int(_get(cp, "app", "max_result_rows", "SIRON_MAX_RESULT_ROWS", 500))
    s.query_timeout_sec = int(_get(cp, "app", "query_timeout_sec", "SIRON_QUERY_TIMEOUT", 60))
    s.flush_unified_on_stop = str(_get(cp, "app", "flush_unified_on_stop", "SIRON_FLUSH", "true")).lower() in ("1", "true", "yes", "evet")
    s.nls_date_format = _get(cp, "app", "nls_date_format", "SIRON_NLS_DATE_FORMAT")
    s.nls_timestamp_format = _get(cp, "app", "nls_timestamp_format", "SIRON_NLS_TIMESTAMP_FORMAT")
    s.sqlite_path = _get(cp, "app", "sqlite_path", "SIRON_SQLITE_PATH", "data/siron_tracer.db")
    s.secret_key = _get(cp, "app", "secret_key", "SIRON_SECRET_KEY", "") or secrets.token_hex(16)
    s.host = _get(cp, "app", "host", "SIRON_HOST", "127.0.0.1")
    s.port = int(_get(cp, "app", "port", "SIRON_PORT", 5000))
    return s
