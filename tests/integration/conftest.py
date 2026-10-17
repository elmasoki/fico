"""Integration tests against a real Oracle (e.g. the gvenzl/oracle-free container).

Enabled when SIRON_IT_DSN is set:
  SIRON_IT_DSN=localhost:1521/FREEPDB1  SIRON_IT_SYS_PASSWORD=...  (SYS / SYSTEM password)
  SIRON_IT_APP_PASSWORD=...  (password of the SIRON schema user, created if missing)
"""
import os
import time

import pytest

oracledb = pytest.importorskip("oracledb")

DSN = os.environ.get("SIRON_IT_DSN")
SYS_PW = os.environ.get("SIRON_IT_SYS_PASSWORD", "")
APP_PW = os.environ.get("SIRON_IT_APP_PASSWORD", "Siron123")

pytestmark = pytest.mark.skipif(not DSN, reason="SIRON_IT_DSN not set")

SCHEMA_SQL = [
    "CREATE TABLE customer (id NUMBER PRIMARY KEY, cust_no VARCHAR2(20) NOT NULL UNIQUE, "
    "full_name VARCHAR2(100), risk_class VARCHAR2(1), country_code VARCHAR2(2), birth_date DATE)",
    "COMMENT ON TABLE customer IS 'Müşteri ana kaydı'",
    "COMMENT ON COLUMN customer.cust_no IS 'Müşteri numarası'",
    "CREATE TABLE account (id NUMBER PRIMARY KEY, cust_id NUMBER NOT NULL REFERENCES customer(id), "
    "acc_no VARCHAR2(20) UNIQUE, iban VARCHAR2(34), balance NUMBER(15,2))",
    "CREATE TABLE alert (alert_id NUMBER PRIMARY KEY, cust_no VARCHAR2(20), status VARCHAR2(10), score NUMBER)",
    "CREATE TABLE country (country_code VARCHAR2(2) PRIMARY KEY, country_name VARCHAR2(50))",
    "CREATE VIEW v_customer_accounts AS SELECT c.cust_no, c.full_name, a.acc_no, a.balance "
    "FROM customer c JOIN account a ON a.cust_id = c.id",
    """CREATE OR REPLACE PACKAGE pkg_risk AS FUNCTION score(p_cust_no VARCHAR2) RETURN NUMBER; END;""",
    """CREATE OR REPLACE PACKAGE BODY pkg_risk AS
         FUNCTION score(p_cust_no VARCHAR2) RETURN NUMBER IS v NUMBER;
         BEGIN SELECT NVL(MAX(score), 0) INTO v FROM alert WHERE cust_no = p_cust_no; RETURN v; END;
       END;""",
]


def _run_all(cur, statements):
    for sql in statements:
        cur.execute(sql)


@pytest.fixture(scope="session")
def sysdba():
    conn = oracledb.connect(user="sys", password=SYS_PW, dsn=DSN, mode=oracledb.AUTH_MODE_SYSDBA)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def siron_schema(sysdba):
    cur = sysdba.cursor()
    cur.execute("SELECT COUNT(*) FROM dba_users WHERE username = 'SIRON'")
    if cur.fetchone()[0]:
        cur.execute("DROP USER siron CASCADE")
    _run_all(cur, ["CREATE USER siron IDENTIFIED BY \"%s\" QUOTA UNLIMITED ON users" % APP_PW,
                   "GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE PROCEDURE TO siron",
                   "GRANT AUDIT_VIEWER, AUDIT_ADMIN TO system"])
    app = oracledb.connect(user="siron", password=APP_PW, dsn=DSN)
    c = app.cursor()
    _run_all(c, SCHEMA_SQL)
    c.executemany("INSERT INTO country VALUES (:1, :2)", [("TR", "Türkiye"), ("DE", "Almanya")])
    c.executemany("INSERT INTO customer VALUES (:1, :2, :3, :4, :5, SYSDATE - :6)",
                  [(i, "C%04d" % i, "Müşteri %d" % i, "LMH"[i % 3], "TR" if i % 4 else "DE", 10000 + i)
                   for i in range(1, 201)])
    c.executemany("INSERT INTO account VALUES (:1, :2, :3, :4, :5)",
                  [(i, (i % 200) + 1, "A%05d" % i, "TR%024d" % i, i * 10.5) for i in range(1, 401)])
    # 3 alerts point to customers that do not exist
    c.executemany("INSERT INTO alert VALUES (:1, :2, :3, :4)",
                  [(i, "C%04d" % (i if i <= 47 else 9000 + i), "OPEN" if i % 2 else "CLOSED", i) for i in range(1, 51)])
    app.commit()
    c.execute("BEGIN DBMS_STATS.GATHER_SCHEMA_STATS('SIRON'); END;")
    app.close()
    yield "SIRON"


@pytest.fixture(scope="session")
def audit_policy(sysdba, siron_schema):
    cur = sysdba.cursor()
    cur.execute("SELECT COUNT(*) FROM audit_unified_policies WHERE policy_name = 'SIRON_IT_POL'")
    if cur.fetchone()[0]:
        try:
            cur.execute("NOAUDIT POLICY siron_it_pol BY siron")
        except oracledb.DatabaseError:
            pass
        cur.execute("DROP AUDIT POLICY siron_it_pol")
    cur.execute("CREATE AUDIT POLICY siron_it_pol ACTIONS SELECT, INSERT, UPDATE, DELETE, MERGE, EXECUTE")
    cur.execute("AUDIT POLICY siron_it_pol BY siron")
    yield
    cur.execute("NOAUDIT POLICY siron_it_pol BY siron")
    cur.execute("DROP AUDIT POLICY siron_it_pol")


@pytest.fixture()
def siron_conn(siron_schema):
    conn = oracledb.connect(user="siron", password=APP_PW, dsn=DSN)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def settings(tmp_path_factory, siron_schema):
    from siron_tracer.config import Settings
    tmp = tmp_path_factory.mktemp("it")
    return Settings(oracle_dsn=DSN, oracle_user="system", oracle_password=SYS_PW, siron_db_user="SIRON",
                    siron_schemas=["SIRON"], sqlite_path=str(tmp / "it.db"), export_dir=str(tmp / "exports"),
                    secret_key="it")


@pytest.fixture(scope="session")
def oracle(settings):
    from siron_tracer.oracle import Oracle
    return Oracle(settings)


def wait_for(fn, timeout=20):
    end = time.time() + timeout
    while True:
        value = fn()
        if value or time.time() > end:
            return value
        time.sleep(1)
