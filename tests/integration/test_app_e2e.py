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
    html = client.get("/captures/%d/sql/%s" % (cid, compute_sql_id(SQL))).get_data(as_text=True)
    assert "&#39;C0007&#39;<sup>1</sup>" in html                         # audited bind highlighted in the SQL
    assert "Adım 1" in client.get("/captures/%d/timeline" % cid).get_data(as_text=True)
    assert compute_sql_id(SQL) in client.get("/search?q=c0007").get_data(as_text=True).split("Bind değerlerinde")[1]
    client.post("/inventory/sql", data={"capture_id": cid, "sql_id": compute_sql_id(SQL), "new_screen": "Müşteri > Detay",
                                        "note": "Ad ve IBAN"})
    assert "Ad ve IBAN" in client.get("/inventory").get_data(as_text=True)
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


def test_reset_drops_earlier_sql(settings, audit_policy, tmp_path):
    settings.sqlite_path = str(tmp_path / "reset.db")
    app = create_app(settings, sync_jobs=True)
    app.config["TESTING"] = True
    store = app.extensions["siron"]["store"]
    client = app.test_client()

    def run(sql):
        conn = oracledb.connect(user="siron", password=APP_PW, dsn=DSN)
        cur = conn.cursor()
        cur.execute(sql)
        cur.fetchall()
        conn.close()

    client.post("/captures", data={"name": "Reset", "db_users": ["SIRON"], "schema": "SIRON"})
    cid = store.list_captures()[0]["id"]
    time.sleep(1)
    run("SELECT country_name FROM country WHERE country_code = 'TR'")      # navigation before the screen
    time.sleep(1.5)
    assert client.get("/captures/%d/live" % cid).get_json()["count"] >= 1
    client.post("/captures/%d/reset" % cid)
    assert client.get("/captures/%d/live" % cid).get_json()["count"] == 0
    time.sleep(1)
    run("SELECT status, score FROM alert WHERE alert_id = 1")
    time.sleep(1.5)
    client.post("/captures/%d/stop" % cid)

    texts = " ".join(r["sql_text"] or "" for r in store.records(cid))
    assert "alert" in texts and "country" not in texts
    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert "SIRON.ALERT" in html and "SIRON.COUNTRY" not in html


def test_markers_sources_and_extract_queries_on_oracle(settings, audit_policy, tmp_path):
    settings.sqlite_path = str(tmp_path / "tools.db")
    settings.export_dir = str(tmp_path / "exports")
    app = create_app(settings, sync_jobs=True)
    app.config["TESTING"] = True
    store = app.extensions["siron"]["store"]
    client = app.test_client()
    client.post("/catalog/refresh")

    paged = ("SELECT * FROM (SELECT x.*, ROWNUM rn FROM (SELECT a.acc_no, a.balance, c.full_name FROM account a "
             "JOIN customer c ON c.id = a.cust_id WHERE c.cust_no = :cno AND a.balance > :minb ORDER BY a.acc_no) x "
             "WHERE ROWNUM <= :hi) WHERE rn > :lo")
    client.post("/captures", data={"name": "Hesaplar", "db_users": ["SIRON"], "schema": "SIRON"})
    cid = store.list_captures()[0]["id"]
    time.sleep(1)
    conn = oracledb.connect(user="siron", password=APP_PW, dsn=DSN)
    cur = conn.cursor()
    cur.execute(SQL, ["C0007"])
    cur.fetchall()
    time.sleep(1.5)
    r = client.post("/captures/%d/markers" % cid, data={"label": "Hesaplar sekmesi"},
                    headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200, r.get_data(as_text=True)
    time.sleep(1)
    cur.execute(paged, cno="C0007", minb=0, hi=10, lo=0)
    cur.fetchall()
    conn.close()
    other = oracledb.connect(user="siron", password=APP_PW, dsn=DSN, program="SQLDeveloper", machine="PC-42")
    other.cursor().execute("SELECT country_name FROM country WHERE country_code = 'DE'").fetchall()
    other.close()
    time.sleep(1.5)
    client.post("/captures/%d/stop" % cid)

    # the marker splits the timeline on the DB clock: the paged query comes after it
    html = client.get("/captures/%d/timeline?gap=60" % cid).get_data(as_text=True)
    assert "Hesaplar sekmesi" in html
    after = html.split("Hesaplar sekmesi", 1)[1]
    assert compute_sql_id(paged) in after and compute_sql_id(SQL) not in after

    # the second program shows up as another source and can be dropped
    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert "başka kaynaklardan SQL karışmış" in html and "SQLDeveloper" in html
    from siron_tracer.sessions import breakdown
    keep = [s.key for s in breakdown(store.records(cid)) if "SQLDeveloper" not in s.program]
    client.post("/captures/%d/sources" % cid, data={"keep": keep})
    assert "SIRON.COUNTRY" not in client.get("/captures/%d" % cid).get_data(as_text=True).split('id="sources"')[0]

    # the paged one-customer query becomes a valid all-records query with the same joins
    page = client.get("/captures/%d/sql/%s/extract" % (cid, compute_sql_id(paged))).get_data(as_text=True)
    gen_sql = page.split('name="sql"')[1].split(">", 1)[1].split("</textarea>")[0]
    import html as _html
    gen_sql = _html.unescape(gen_sql)
    assert ":cno" not in gen_sql and "ROWNUM <=" not in gen_sql and "JOIN customer" in gen_sql
    page = client.post("/captures/%d/sql/%s/extract" % (cid, compute_sql_id(paged)),
                       data={"do": "count", "sql": gen_sql}).get_data(as_text=True)
    assert "400</b>" in page                                               # every account, not one customer's page
    client.post("/captures/%d/sql/%s/extract" % (cid, compute_sql_id(paged)),
                data={"do": "save", "sql": gen_sql, "name": "Hesaplar listesi"})
    r = client.post("/migration/extract", data={"mode": "decided"})
    job = store.get_job(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert job["status"] == "done", job["message"]
    files = {f["table"]: f["rows"] for f in job["result"]["files"]}
    assert files["Ekran sorgusu: Hesaplar listesi"] == 400


def test_record_trace_and_notebook_on_oracle(settings, audit_policy, tmp_path):
    settings.sqlite_path = str(tmp_path / "trace.db")
    app = create_app(settings, sync_jobs=True)
    app.config["TESTING"] = True
    store = app.extensions["siron"]["store"]
    client = app.test_client()
    client.post("/catalog/refresh")
    assert store.catalog().indexed.get(("SIRON", "CUSTOMER")) >= {"ID", "CUST_NO"}     # PK / UNIQUE indexes loaded

    # record trace: customer C0007 -> its row, its alert, then its 2 accounts through the FK
    r = client.post("/trace", data={"value": "C0007", "depth": "2"})
    job = store.get_job(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert job["status"] == "done", job["message"]
    hits = {h["name"]: h for h in job["result"]["hits"]}
    assert hits["CUSTOMER"]["depth"] == 0 and hits["CUSTOMER"]["count"] == 1
    assert hits["ALERT"]["depth"] == 0 and hits["ALERT"]["count"] == 1
    assert hits["ACCOUNT"]["depth"] == 1 and hits["ACCOUNT"]["count"] == 2 and not job["result"]["errors"]
    page = client.get("/trace/%d" % job["id"]).get_data(as_text=True)
    assert 'CUSTOMER.ID</span>' in page and 'ACCOUNT.CUST_ID</span><span class="badge ok">FK' in page

    # the trace's path query goes to the notebook with a ready case, and passes on real data
    from siron_tracer.trace import path_sql
    client.post("/notebook/new", data={"name": "Hesaplar", "sql": path_sql(hits["ACCOUNT"]), "case_name": "C0007",
                                       "case_binds": "deger = C0007", "case_expect": "satır = 2\nACC_NO ~ A0"})
    qid = store.notebook_queries()[0]["id"]
    client.post("/notebook/%d" % qid, data={"do": "run_all"})
    case = store.notebook_cases(qid)[0]
    assert case["last_status"] == "pass", case["last_detail"]

    # named binds in any case, positional binds, a failing expectation and an Oracle error
    client.post("/notebook/new", data={"name": "Müşteri", "schema": "SIRON",
                                       "sql": "SELECT cust_no, full_name, risk_class, birth_date FROM customer "
                                              "WHERE cust_no = :Musteri_No"})
    q2 = store.notebook_queries()[0]["id"] if store.notebook_queries()[0]["name"] == "Müşteri" else \
        store.notebook_queries()[1]["id"]
    store.add_notebook_case(q2, "Doğru", "musteri_no = C0007", "satır = 1\nFULL_NAME = Müşteri 7\nRISK_CLASS dolu")
    store.add_notebook_case(q2, "Yanlış", "musteri_no = C0007", "FULL_NAME = Müşteri 8")
    client.post("/notebook/new", data={"name": "Konum", "sql": "SELECT full_name FROM customer WHERE id = :1 OR id = :2"})
    q3 = next(q["id"] for q in store.notebook_queries() if q["name"] == "Konum")
    store.add_notebook_case(q3, "İki müşteri", "1 = 7\n2 = 8", "satır = 2\nFULL_NAME = Müşteri 8")
    client.post("/notebook/new", data={"name": "Bozuk", "sql": "SELECT olmayan_kolon FROM customer"})
    q4 = next(q["id"] for q in store.notebook_queries() if q["name"] == "Bozuk")
    store.add_notebook_case(q4, "Hata", "", "satır >= 1")
    r = client.post("/notebook/run")
    job = store.get_job(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert job["status"] == "done", job["message"]
    assert job["result"] == {"passed": 3, "failed": 1, "errors": 1, "queries": 4}, \
        [(c["name"], c["last_detail"]) for q in store.notebook_queries() for c in store.notebook_cases(q["id"])]
    bad = next(c for c in store.notebook_cases(q4))
    assert "ORA-00904" in bad["last_detail"]["error"]
    assert "Müşteri 7" in next(c for c in store.notebook_cases(q2) if c["name"] == "Yanlış")["last_detail"]["checks"][0]["detail"]
    html = client.get("/notebook/report.html").get_data(as_text=True)
    assert "ORA-00904" in html and "FULL_NAME = Müşteri 8" in html

    # expectations suggested from what the screen SQL returned for its recorded bind
    client.post("/captures", data={"name": "Müşteri kartı", "db_users": ["SIRON"], "schema": "SIRON"})
    cid = store.list_captures()[0]["id"]
    time.sleep(1)
    conn = oracledb.connect(user="siron", password=APP_PW, dsn=DSN)
    conn.cursor().execute(SQL, ["C0007"]).fetchall()
    conn.close()
    time.sleep(1.5)
    client.post("/captures/%d/stop" % cid)
    client.post("/inventory/sql", data={"capture_id": cid, "sql_id": compute_sql_id(SQL), "new_screen": "Müşteri > Kart"})
    html = client.post("/notebook/%d" % q2, data={"do": "suggest", "ref": "%d:%s" % (cid, compute_sql_id(SQL))}
                       ).get_data(as_text=True)
    assert "satır = 2\nFULL_NAME = Müşteri 7\nIBAN = TR" in html
