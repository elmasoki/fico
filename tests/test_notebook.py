import re
from datetime import datetime

import catalog_fixture
from siron_tracer.notebook import (diff_html, evaluate, expectations_from_row, parse_binds, parse_expectations,
                                   run_case, values_equal)
from siron_tracer.relations import build_relations
from siron_tracer.trace import candidate_columns, path_sql, trace
from test_app import Q1, rec
from test_features import capture, env  # noqa: F401  (pytest fixture)
from siron_tracer.sqlutil import compute_sql_id

# --------------------------------------------------------------------------- record trace

DATA = {
    "CUSTOMER": [{"ID": 7, "CUST_NO": "C0007", "NAME": "Ali", "RISK_CLASS": "H"},
                 {"ID": 8, "CUST_NO": "C0008", "NAME": "Ayşe", "RISK_CLASS": "L"}],
    "ACCOUNT": [{"ID": 70, "CUST_ID": 7, "ACC_NO": "A70", "IBAN": "TR70", "BALANCE": 5},
                {"ID": 71, "CUST_ID": 7, "ACC_NO": "A71", "IBAN": "TR71", "BALANCE": 6},
                {"ID": 80, "CUST_ID": 8, "ACC_NO": "A80", "IBAN": "TR80", "BALANCE": 7}],
    "TRANSACTION": [{"TX_ID": 1, "ACC_NO": "A70", "AMOUNT": 10, "TX_DATE": None},
                    {"TX_ID": 2, "ACC_NO": "A80", "AMOUNT": 20, "TX_DATE": None}],
    "ALERT": [{"ALERT_ID": 1, "CUST_NO": "C0007", "STATUS": "OPEN"}],
}


def fake_db(sql, binds, n):
    """Just enough of Oracle for the SQL trace() writes: one table, one equality or IN filter."""
    table = re.search(r"FROM SIRON\.(\w+) WHERE", sql).group(1)
    col, op = re.search(r"WHERE (\w+) (=|IN)", sql).groups()
    wanted = {str(v) for v in binds.values()}
    rows = [r for r in DATA[table] if str(r[col]) in wanted]
    if sql.startswith("SELECT COUNT(*)"):
        return ["N"], [(len(rows),)]
    if sql.startswith("SELECT DISTINCT"):
        out = re.match(r"SELECT DISTINCT (\w+)", sql).group(1)
        return [out], sorted({(r[out],) for r in rows if r[out] is not None})
    cols = list(DATA[table][0])
    return cols, [tuple(r[c] for c in cols) for r in rows][:n]


def relations(catalog):
    return build_relations(catalog, list(catalog.tables), infer=True)


def test_candidate_columns_are_key_like_and_type_compatible():
    cat = catalog_fixture.make()
    cands, skipped = candidate_columns(cat, "C0007", big_rows=1000)
    names = {(k[1], c) for k, c in cands}
    assert ("CUSTOMER", "CUST_NO") in names and ("ALERT", "CUST_NO") in names
    assert ("CUSTOMER", "NAME") not in names and ("CUSTOMER", "ID") not in names    # not key-like / not a number
    cands, _ = candidate_columns(cat, "7", big_rows=1000)
    assert ("CUSTOMER", "ID") in {(k[1], c) for k, c in cands}
    cat.tables[("SIRON", "ALERT")].num_rows = 10 ** 7
    cands, skipped = candidate_columns(cat, "C0007", big_rows=1000)
    assert ("ALERT", "CUST_NO") not in {(k[1], c) for k, c in cands} and skipped
    cat.indexed[("SIRON", "ALERT")] = {"CUST_NO"}
    cands, _ = candidate_columns(cat, "C0007", big_rows=1000)
    assert ("ALERT", "CUST_NO") in {(k[1], c) for k, c in cands}                  # indexed: searched anyway


def test_trace_follows_relations_hop_by_hop():
    cat = catalog_fixture.make()
    seen = []
    result = trace(fake_db, cat, relations(cat), "C0007", depth=2, big_rows=10 ** 6, progress=lambda p, m: seen.append(p))
    hits = {h["name"]: h for h in result["hits"]}
    assert hits["CUSTOMER"]["depth"] == 0 and hits["CUSTOMER"]["count"] == 1
    assert hits["ALERT"]["depth"] == 0
    assert hits["ACCOUNT"]["depth"] == 1 and hits["ACCOUNT"]["count"] == 2                 # only customer 7's accounts
    assert hits["ACCOUNT"]["path"][0]["text"] == "CUSTOMER.ID → ACCOUNT.CUST_ID"
    assert hits["TRANSACTION"]["depth"] == 2 and hits["TRANSACTION"]["count"] == 1
    assert hits["TRANSACTION"]["seed_column"] == "CUST_NO" and hits["TRANSACTION"]["rows"]
    assert seen[-1] == 100 and not result["errors"]
    sql = path_sql(hits["TRANSACTION"])
    assert sql.splitlines()[0] == "SELECT t2.*" and "JOIN SIRON.ACCOUNT t1 ON t1.CUST_ID = t0.ID" in sql
    assert sql.endswith("WHERE t0.CUST_NO = :deger")
    assert "TRANSACTION" not in {h["name"] for h in trace(fake_db, cat, relations(cat), "C0007", depth=1,
                                                          big_rows=10 ** 6)["hits"]}


def test_trace_from_one_start_column_and_errors():
    cat = catalog_fixture.make()
    result = trace(fake_db, cat, relations(cat), "C0007", depth=0, big_rows=10 ** 6,
                   only=[(("SIRON", "ALERT"), "CUST_NO")])
    assert [h["name"] for h in result["hits"]] == ["ALERT"] and result["searched"] == 1

    def broken(sql, binds, n):
        raise RuntimeError("ORA-00942")
    assert trace(broken, cat, [], "C0007", depth=1, big_rows=10 ** 6)["errors"][0][1] == "ORA-00942"


def test_trace_page_and_result(env):
    client, oracle, store, _ = env
    assert "İzi başlat" in client.get("/trace").get_data(as_text=True)
    oracle.result = (["N"], [(1,)], False)
    r = client.post("/trace", data={"value": "C0007", "depth": "1"})
    job_id = int(r.headers["Location"].rsplit("/", 1)[1])
    job = store.get_job(job_id)
    assert job["status"] == "done" and job["kind"] == "trace", job["message"]
    page = client.get("/trace/%d" % job_id).get_data(as_text=True)
    assert "C0007" in page and "Sorgu defterinde başlat" in page
    assert client.post("/trace", data={"value": "x", "start": "NOPE.COL"}).status_code == 302


# --------------------------------------------------------------------------- notebook: expectations

def test_parse_binds_and_expectations():
    assert parse_binds(":musteri_no = 104233\n# not\nTARIH = 2026-09-01\n") == {"MUSTERI_NO": "104233",
                                                                               "TARIH": "2026-09-01"}
    exps, bad = parse_expectations("satır = 3\nFULL_NAME = AHMET YILMAZ\nIBAN ~ tr00\nRISK != H\nIBAN dolu\n"
                                   "tüm STATUS = OPEN\nbu satır okunmaz\n# not")
    assert [(e.column, e.op, e.value, e.every) for e in exps] == [
        ("SATIR", "=", "3", False), ("FULL_NAME", "=", "AHMET YILMAZ", False), ("IBAN", "~", "tr00", False),
        ("RISK", "!=", "H", False), ("IBAN", "dolu", "", False), ("STATUS", "=", "OPEN", True)]
    assert exps[0].is_rows and bad == ["bu satır okunmaz"]


def test_values_equal():
    assert values_equal(104233, "104233") and values_equal("5.0", "5") and values_equal(" Ali ", "Ali")
    assert values_equal(datetime(2026, 9, 1, 10, 0), "2026-09-01") and not values_equal("Ali", "ali")
    assert values_equal(None, "NULL") and not values_equal(None, "x")


def test_evaluate_reports_what_was_seen():
    cols = ["NAME", "STATUS", "IBAN", "AMOUNT"]
    rows = [("Ali", "OPEN", "TR001", 10), ("Ali", "CLOSED", None, 25)]
    exps, _ = parse_expectations("satır = 2\nNAME = Ali\nSTATUS = PENDING\ntüm STATUS = OPEN\nRISK = H\n"
                                 "IBAN boş\nAMOUNT >= 20\nSTATUS != X\nsatır = 1+")
    res = evaluate(cols, rows, exps)
    assert [r.ok for r in res] == [True, True, False, False, False, True, True, True, True]
    assert "CLOSED, OPEN" in res[2].detail and res[3].detail == "1 / 2 satır uyuyor" and "RISK" in res[4].detail


def test_run_case_passes_only_used_binds():
    calls = []

    def run(sql, binds):
        calls.append(binds)
        return ["NAME"], [("Ali",)]
    ok = run_case(run, "SELECT name FROM c WHERE no = :no", "no = 7\nfazla = 1", "satır = 1\nNAME = Ali", ["NO"])
    assert ok.status == "pass" and calls == [{"NO": "7"}] and ok.sample == [["Ali"]]
    assert run_case(run, "x", "", "satır = 1", ["NO"]).error == "Bind değeri eksik: :NO"
    assert run_case(run, "x", "", "", []).status == "error"
    assert run_case(run, "x", "", "okunmaz", []).status == "error"
    assert run_case(run, "x", "", "NAME = Veli", []).status == "fail"

    def boom(sql, binds):
        raise RuntimeError("ORA-00904: invalid identifier")
    assert run_case(boom, "x", "", "satır = 1", []).error.startswith("ORA-00904")


def test_expectation_suggestion_and_diff():
    text = expectations_from_row(["NAME", "RN", "IBAN", "X"], [("Ali", 1, None, "y" * 100)])
    assert text == "satır = 1\nNAME = Ali"
    assert diff_html("a\nb", "a\nc") == [(" ", "a"), ("-", "b"), ("+", "c")]


# --------------------------------------------------------------------------- notebook: pages

def test_notebook_flow(env):
    client, oracle, store, _ = env
    assert "Defter boş" in client.get("/notebook").get_data(as_text=True)
    r = client.post("/notebook/new", data={"name": "Müşteri ana kaydı", "target": "CUSTOMER",
                                           "sql": "SELECT name, risk_class FROM customer WHERE cust_no = :musteri_no;",
                                           "case_name": "C0007", "case_binds": "musteri_no = C0007",
                                           "case_expect": "satır = 1\nNAME = Ali"})
    qid = store.notebook_queries()[0]["id"]
    assert r.headers["Location"].endswith("/notebook/%d" % qid)
    q = store.get_notebook_query(qid)
    assert q["sql_text"].endswith(":musteri_no") and q["versions"] == 1 and q["cases"] == 1
    page = client.get("/notebook/%d" % qid).get_data(as_text=True)
    assert ":MUSTERI_NO" in page and "Çalıştırılmadı" in page

    oracle.result = (["NAME", "RISK_CLASS"], [("Ali", "H")], False)
    client.post("/notebook/%d" % qid, data={"do": "run_all"})
    case = store.notebook_cases(qid)[0]
    assert case["last_status"] == "pass" and oracle.ran[-1][1] == {"MUSTERI_NO": "C0007"}
    oracle.result = (["NAME", "RISK_CLASS"], [("Veli", "H")], False)
    client.post("/notebook/%d" % qid, data={"do": "case_run", "case_id": case["id"]})
    case = store.notebook_cases(qid)[0]
    assert case["last_status"] == "fail" and "Veli" in case["last_detail"]["checks"][1]["detail"]
    assert "Kaldı" in client.get("/notebook/%d" % qid).get_data(as_text=True)

    # editing the SQL keeps history; unchanged SQL does not add a version
    client.post("/notebook/%d" % qid, data={"do": "save", "name": "Müşteri", "sql": q["sql_text"]})
    assert len(store.notebook_versions(qid)) == 1
    client.post("/notebook/%d" % qid, data={"do": "save", "name": "Müşteri", "note": "risk eklendi",
                                            "sql": "SELECT name FROM customer\nWHERE cust_no = :musteri_no"})
    versions = store.notebook_versions(qid)
    assert len(versions) == 2 and versions[0]["note"] == "risk eklendi" and versions[0]["author"]
    page = client.get("/notebook/%d" % qid).get_data(as_text=True)
    assert "Önceki sürümle farkı" in page and "risk eklendi" in page
    client.post("/notebook/%d" % qid, data={"do": "restore", "version_id": versions[1]["id"]})
    assert store.get_notebook_query(qid)["sql_text"] == q["sql_text"] and len(store.notebook_versions(qid)) == 3

    # try-run with binds, new case, edit, delete
    oracle.result = (["NAME"], [("Ali",)], False)
    page = client.post("/notebook/%d" % qid, data={"do": "preview", "try_binds": "musteri_no = C0008"}).get_data(as_text=True)
    assert "Sonuç" in page and oracle.ran[-1][1] == {"MUSTERI_NO": "C0008"}
    assert "Bind değeri eksik" in client.post("/notebook/%d" % qid, data={"do": "preview"}).get_data(as_text=True)
    client.post("/notebook/%d" % qid, data={"do": "case_add", "case_name": "İkinci", "case_binds": "musteri_no = 8",
                                            "case_expect": "satır >= 1", "and_run": "1"})
    cases = store.notebook_cases(qid)
    assert len(cases) == 2 and cases[1]["last_status"] == "pass"
    client.post("/notebook/%d" % qid, data={"do": "case_save", "case_id": cases[1]["id"], "case_name": "2.",
                                            "case_binds": "musteri_no = 9", "case_expect": "satır = 0"})
    assert store.notebook_cases(qid)[1]["last_status"] is None and store.notebook_cases(qid)[1]["name"] == "2."
    client.post("/notebook/%d" % qid, data={"do": "case_delete", "case_id": cases[1]["id"]})
    assert len(store.notebook_cases(qid)) == 1

    # index, background run, report
    index = client.get("/notebook").get_data(as_text=True)
    assert "Müşteri" in index and "CUSTOMER" in index
    r = client.post("/notebook/run")
    job = store.get_job(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert job["status"] == "done" and job["result"] == {"passed": 1, "failed": 0, "errors": 0, "queries": 1}
    assert "senaryo geçti" in client.get("/jobs/%d" % job["id"]).get_data(as_text=True)
    rep = client.get("/notebook/report.html")
    html = rep.get_data(as_text=True)
    assert "attachment" in rep.headers["Content-Disposition"] and "Sorgu doğrulama raporu" in html
    assert "NAME = Ali" in html and "Geçti" in html

    client.post("/notebook/%d" % qid, data={"do": "delete"})
    assert store.notebook_queries() == [] and store.notebook_cases(qid) == [] and store.notebook_versions(qid) == []
    assert client.get("/notebook/%d" % qid).status_code == 404


def test_notebook_positional_binds_and_entry_points(env):
    client, oracle, store, _ = env
    client.post("/notebook/new", data={"title": "Konsoldan", "sql": "SELECT name FROM customer WHERE id = :1",
                                       "schema": "siron"})
    q = store.notebook_queries()[0]
    assert q["name"] == "Konsoldan" and q["schema_name"] == "SIRON"
    store.add_notebook_case(q["id"], "Bir", "1 = 7", "satır = 1")
    oracle.result = (["NAME"], [("Ali",)], False)
    client.post("/notebook/%d" % q["id"], data={"do": "run_all"})
    assert oracle.ran[-1][1] == ["7"] and oracle.last_schema == "SIRON"
    assert store.notebook_cases(q["id"])[0]["last_status"] == "pass"
    assert "Sorgu defterine ekle" in client.get("/sql").get_data(as_text=True)


def test_notebook_suggests_expectations_from_screen_sql(env):
    client, oracle, store, _ = env
    cid = capture(client, store, oracle, [rec(1, Q1, " #1(1):7")])
    client.post("/inventory/sql/bulk", data={"capture_id": cid, "sql": [compute_sql_id(Q1)],
                                             "new_screen": "Müşteri > Detay", "note": "Üst bilgi"})
    client.post("/notebook/new", data={"name": "Müşteri", "sql": "SELECT name FROM customer WHERE id = :id"})
    qid = store.notebook_queries()[0]["id"]
    page = client.get("/notebook/%d" % qid).get_data(as_text=True)
    assert "Müşteri › Detay · Üst bilgi" in page
    oracle.result = (["NAME", "IBAN"], [("Ali Veli", "TR01")], False)
    page = client.post("/notebook/%d" % qid, data={"do": "suggest", "ref": "%d:%s" % (cid, compute_sql_id(Q1))})
    html = page.get_data(as_text=True)
    assert "satır = 1\nNAME = Ali Veli\nIBAN = TR01" in html and ":1" not in oracle.ran[-1][0]
    assert "id = 7" in html                                                        # the single bind carried over
