from datetime import datetime, timedelta

import pytest

from siron_tracer import create_app
from siron_tracer.config import Settings
from siron_tracer.sqlutil import compute_sql_id
from siron_tracer.store import Store

T0 = datetime(2026, 10, 17, 9, 0, 0)

Q1 = "SELECT c.name, a.iban FROM customer c JOIN account a ON a.cust_id = c.id WHERE c.id = :1"
Q2 = "SELECT * FROM alert WHERE status = :B1 AND owner = :B2"
NOISE = "SELECT 1 FROM DUAL"


def rec(i, sql, binds=None, obj=None, action="SELECT", stmt=None):
    return {"ts": (T0 + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "db_user": "SIRON", "os_user": "app", "host": "APPSRV", "program": "JDBC",
            "session_id": "77", "entry_id": str(i), "statement_id": str(stmt or i),
            "action": action, "obj_schema": "SIRON" if obj else None, "obj_name": obj,
            "sql_text": sql, "sql_binds": binds, "return_code": "0", "client_id": None,
            "sql_id": compute_sql_id(sql) if sql else None}


class FakeOracle:
    def __init__(self):
        self.clock = T0
        self.records = []
        self.ran = []

    def now(self):
        self.clock += timedelta(minutes=1)
        return self.clock, self.clock + timedelta(hours=3)

    def local_to_utc(self, local):
        return local - timedelta(hours=3)

    def fetch_records(self, f, flush=False):
        return list(self.records)

    def load_objects(self, schemas):
        return [("SIRON", "CUSTOMER", "TABLE"), ("SIRON", "ACCOUNT", "TABLE"),
                ("SIRON", "ALERT", "VIEW")]

    def run_select(self, sql, max_rows=None):
        self.ran.append(sql)
        return ["NAME", "IBAN"], [("Ali", "TR01")], False

    def cursor_info(self, sql_id):
        return ["INST_ID"], [(1,)], []

    def diagnostics(self):
        return [("Bağlantı", True, "Oracle 19c")]


@pytest.fixture
def env():
    settings = Settings(oracle_dsn="x", oracle_user="u", siron_db_user="SIRON",
                        siron_schemas=["SIRON"], secret_key="t")
    oracle = FakeOracle()
    app = create_app(settings, oracle=oracle, store=Store(":memory:"))
    app.config["TESTING"] = True
    return app.test_client(), oracle, app.extensions["siron"]["store"]


def test_capture_flow(env):
    client, oracle, store = env
    assert client.get("/").status_code == 200
    r = client.post("/captures", data={"name": "Müşteri detay"})
    assert r.status_code == 302
    cid = store.list_captures()[0]["id"]
    assert "Kayıt sürüyor" in client.get("/captures/%d" % cid).get_data(as_text=True)

    oracle.records = [
        rec(1, Q1, " #1(3):123", obj="CUSTOMER", stmt=1),
        rec(2, Q1, " #1(3):123", obj="ACCOUNT", stmt=1),   # same execution, 2nd object
        rec(3, Q1, " #1(3):456", obj="CUSTOMER", stmt=3),
        rec(4, Q2, " #1(4):OPEN #2(5):AHMET", obj="ALERT"),
        rec(5, None, None, action="LOGON"),
    ]
    client.post("/captures/%d/stop" % cid)
    capture = store.get_capture(cid)
    assert capture["status"] == "done" and capture["record_count"] == 5

    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    for word in ("SIRON.CUSTOMER", "SIRON.ACCOUNT", "SIRON.ALERT", compute_sql_id(Q1)):
        assert word in html

    sid = compute_sql_id(Q1)
    html = client.get("/captures/%d/sql/%s" % (cid, sid)).get_data(as_text=True)
    assert "c.id = &#39;123&#39;" in html

    # change the bind and run
    r = client.post("/captures/%d/sql/%s" % (cid, sid),
                    data={"do": "run", "value_0": "999", "kind_0": "number",
                          "sql_override": "x", "literal_orig": "x"})
    assert r.status_code == 200
    assert oracle.ran[-1].endswith("c.id = 999")
    assert "TR01" in r.get_data(as_text=True)

    # a hand-edited textarea wins
    client.post("/captures/%d/sql/%s" % (cid, sid),
                data={"do": "run", "sql_override": "select 2 from dual", "literal_orig": "x"})
    assert oracle.ran[-1] == "select 2 from dual"

    assert client.get("/captures/%d/sql/%s?cursor=1" % (cid, sid)).status_code == 200
    csv_text = client.get("/captures/%d/statements.csv" % cid).get_data(as_text=True)
    assert sid in csv_text and "'456'" not in csv_text and "'123'" in csv_text


def test_noise_capture_hides_sql(env):
    client, oracle, store = env
    oracle.records = [rec(1, NOISE)]
    client.post("/captures", data={"name": "boşta"})
    noise_id = store.list_captures()[0]["id"]
    client.post("/captures/%d/stop" % noise_id)
    client.post("/captures/%d/update" % noise_id, data={"toggle_noise": "1"})
    assert store.get_capture(noise_id)["is_noise"] == 1

    oracle.records = [rec(1, NOISE), rec(2, Q2, " #1(1):A #2(1):B")]
    client.post("/captures", data={"name": "uyarılar"})
    cid = store.list_captures()[0]["id"]
    client.post("/captures/%d/stop" % cid)
    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert compute_sql_id(Q2) in html and compute_sql_id(NOISE) not in html
    assert compute_sql_id(NOISE) in client.get("/captures/%d?noise=0" % cid).get_data(as_text=True)


def test_objects_tables_range_and_misc(env):
    client, oracle, store = env
    client.post("/objects/refresh")
    assert len(store.objects()) == 3
    oracle.records = [rec(1, Q1, " #1(1):1")]
    r = client.post("/captures/range", data={"name": "geçmiş", "start": "2026-10-17T12:00",
                                             "end": "2026-10-17T12:05:30"})
    assert r.status_code == 302
    c = store.list_captures()[0]
    assert c["start_utc"].startswith("2026-10-17 09:00:00") and c["record_count"] == 1
    html = client.get("/tables").get_data(as_text=True)
    assert "SIRON.CUSTOMER" in html and "geçmiş" in html
    assert "SIRON.ACCOUNT" in client.get("/tables.csv").get_data(as_text=True)
    assert "Oracle 19c" in client.get("/check").get_data(as_text=True)
    r = client.post("/sql", data={"sql": "select 1 from dual"})
    assert "TR01" in r.get_data(as_text=True)
    client.post("/captures/%d/delete" % c["id"])
    assert store.get_capture(c["id"]) is None
