"""The whole workflow through the Flask app against a real Oracle."""
import time

from conftest import oracledb, APP_PW, DSN
from siron_tracer import create_app
from siron_tracer.sqlutil import compute_sql_id

SQL = "SELECT c.full_name, a.iban FROM customer c JOIN account a ON a.cust_id = c.id WHERE c.cust_no = :1"


def test_capture_to_extract(settings, audit_policy, tmp_path):
    settings.sqlite_path = str(tmp_path / "e2e.db")
    settings.export_dir = str(tmp_path / "exports")
    app = create_app(settings, sync_jobs=True)
    app.config["TESTING"] = True
    store = app.extensions["siron"]["store"]
    client = app.test_client()

    client.post("/catalog/refresh")
    assert store.list_jobs(1)[0]["status"] == "done", store.list_jobs(1)[0]["message"]

    client.post("/captures", data={"name": "Müşteri Detay", "db_users": ["SIRON"], "schema": "SIRON"})
    cid = store.list_captures()[0]["id"]
    time.sleep(1)
    conn = oracledb.connect(user="siron", password=APP_PW, dsn=DSN)
    cur = conn.cursor()
    cur.execute(SQL, ["C0007"])
    cur.fetchall()
    cur.execute("SELECT pkg_risk.score(:p) FROM dual", p="C0007")
    cur.fetchall()
    conn.close()
    time.sleep(1.5)
    client.post("/captures/%d/stop" % cid)
    assert store.get_capture(cid)["record_count"] >= 2

    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert "SIRON.CUSTOMER" in html and "SIRON.ACCOUNT" in html and "SIRON.ALERT" in html  # ALERT via package
    html = client.get("/captures/%d/columns" % cid).get_data(as_text=True)
    assert "FULL_NAME" in html and "IBAN" in html

    r = client.post("/captures/%d/sql/%s" % (cid, compute_sql_id(SQL)), data={"do": "run"})
    assert "Müşteri 7" in r.get_data(as_text=True)
    r = client.post("/captures/%d/find" % cid, data={"value": "müşteri 7", "mode": "ci", "strategy": "results"})
    assert "SIRON.CUSTOMER.FULL_NAME" in r.get_data(as_text=True)

    client.post("/relations/check-all")
    assert store.list_jobs(1)[0]["status"] == "done"
    assert "(CUST_ID)" in client.get("/relations").get_data(as_text=True)

    client.post("/tables/bulk", data={"k": ["SIRON.CUSTOMER", "SIRON.ACCOUNT"], "action": "migrate"})
    client.post("/tables/bulk", data={"k": ["SIRON.CUSTOMER"], "action": "profile"})
    assert store.profiles(("SIRON", "CUSTOMER"))[("SIRON", "CUSTOMER", "RISK_CLASS")]["distinct"] == 3
    r = client.post("/migration/extract", data={"mode": "decided"})
    job = store.get_job(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert job["status"] == "done", job["message"]
    rows = {f["table"]: f["rows"] for f in job["result"]["files"]}
    assert rows == {"SIRON.CUSTOMER": 200, "SIRON.ACCOUNT": 400}
    assert client.get("/report.html").status_code == 200
