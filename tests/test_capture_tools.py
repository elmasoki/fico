import io
import zipfile

from siron_tracer.generalize import generalize
from siron_tracer.migration import QueryStep, package_zip
from siron_tracer.sessions import assess, breakdown, filter_records, is_mixed
from siron_tracer.sqlutil import compute_sql_id
from test_app import Q1, Q2, rec
from test_features import capture, env  # noqa: F401  (pytest fixture)

S1, S2 = compute_sql_id(Q1), compute_sql_id(Q2)


def other(i, sql, binds=None, obj=None):
    r = rec(i, sql, binds, obj)
    r.update(os_user="ahmet", host="PC-42", program="SQL Developer", session_id="901")
    return r


# --------------------------------------------------------------------------- generalize

def test_generalize_drops_bind_filters_and_keeps_joins():
    g = generalize("SELECT k.ad, p.risiko FROM kyccust k JOIN presult p ON p.kundnr = k.kundnr AND p.dil = :2 "
                   "WHERE k.kundnr = :1 AND k.histbis = '9999'")
    assert g.sql == ("SELECT k.ad, p.risiko FROM kyccust k JOIN presult p ON p.kundnr = k.kundnr "
                     "WHERE k.histbis = '9999'")
    assert g.removed == ["p.dil = :2", "k.kundnr = :1"] and "k.histbis = '9999'" in g.kept and not g.error


def test_generalize_paging_wrappers_between_case_and_subqueries():
    g = generalize("SELECT * FROM (SELECT a.*, ROWNUM rn FROM (SELECT h.kundennr FROM gwatrhit h WHERE h.status = :1 "
                   "AND h.datum BETWEEN :2 AND :3 ORDER BY h.datum) a WHERE ROWNUM <= :4) WHERE rn > :5")
    assert g.sql == "SELECT * FROM (SELECT a.*, ROWNUM rn FROM (SELECT h.kundennr FROM gwatrhit h ORDER BY h.datum) a)"
    assert set(g.removed) == {"rn > :5", "ROWNUM <= :4", "h.status = :1", "h.datum BETWEEN :2 AND :3"}
    g = generalize("SELECT x FROM t WHERE (a = :1 OR b = :2) AND c IN (SELECT y FROM u WHERE u.k = :3 AND u.f = 'A') "
                   "AND CASE WHEN d = 1 AND e = 2 THEN 1 END = 1")
    assert "a = NULL" not in g.sql and "(a = :1 OR b = :2)" in g.removed           # never kept as x = NULL
    assert "c IN (SELECT y FROM u WHERE u.f = 'A')" in g.sql and "CASE WHEN d = 1 AND e = 2 THEN 1 END = 1" in g.sql


def test_generalize_other_clauses_and_guards():
    g = generalize("SELECT a, NVL(:1, 'z') q FROM t LEFT JOIN u ON u.lang = :lang WHERE t.x = 1 "
                   "GROUP BY a HAVING COUNT(*) > :2 ORDER BY a FETCH FIRST 50 ROWS ONLY")
    assert "ON 1 = 1" in g.sql and "HAVING" not in g.sql and "FETCH" not in g.sql and "NVL(NULL, 'z')" in g.sql
    assert g.nulled == [":1"] and "FETCH FIRST 50 ROWS ONLY" in g.removed
    assert generalize("SELECT id FROM tree START WITH id = :1 CONNECT BY PRIOR id = parent").sql == \
        "SELECT id FROM tree CONNECT BY PRIOR id = parent"
    assert generalize("WITH c AS (SELECT * FROM cust WHERE id = :1) SELECT * FROM c").sql == \
        "WITH c AS (SELECT * FROM cust) SELECT * FROM c"
    assert generalize("SELECT a FROM t WHERE a = ':1' AND b = ?").sql == "SELECT a FROM t WHERE a = ':1'"
    assert generalize("UPDATE t SET a = :1").error
    unchanged = generalize("SELECT a FROM t WHERE a = 1")
    assert unchanged.sql == "SELECT a FROM t WHERE a = 1" and not unchanged.changed


def test_query_step_in_package():
    step = QueryStep(3, "Müşteri Detay · Hesaplar", "SELECT a FROM t;", schema="SIRON_KYC")
    assert step.file_stem == "E03_Musteri_Detay_Hesaplar" and step.count_sql() == "SELECT COUNT(*) FROM (SELECT a FROM t)"
    z = zipfile.ZipFile(io.BytesIO(package_zip([step], None, "", "now")))
    assert "ALTER SESSION SET CURRENT_SCHEMA = SIRON_KYC;" in z.read("sql/E03_Musteri_Detay_Hesaplar.sql").decode()
    assert "ALTER SESSION SET CURRENT_SCHEMA = SIRON_KYC;" in z.read("extract_sqlplus.sql").decode()


# --------------------------------------------------------------------------- sessions

def test_source_breakdown():
    records = [dict(rec(1, Q1, " #1(1):1"), id=1), dict(rec(2, Q1, " #1(1):2"), id=2), dict(other(3, Q2), id=3)]
    sources = breakdown(records)
    assert [s.records for s in sources] == [2, 1] and sources[0].os_user == "app" and is_mixed(sources)
    assert any("farklı kullanıcı" in w for w in assess(sources))
    assert not is_mixed(breakdown(records, [sources[1].key]))
    assert [r["id"] for r in filter_records(records, [sources[1].key])] == [1, 2]
    pooled = [dict(rec(i, Q1), id=i, session_id=str(i)) for i in range(3)]
    assert "bağlantı havuzu" in assess(breakdown(pooled))[0]


def test_mixed_capture_warning_and_exclusion(env):
    client, oracle, store, _ = env
    cid = capture(client, store, oracle, [rec(1, Q1, " #1(1):1"), other(2, Q2, " #1(1):A #2(1):B")])
    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert "başka kaynaklardan SQL karışmış" in html and "SQL Developer" in html and "karışık" in html
    assert "SIRON.ALERT" in html
    keep = next(src.key for src in breakdown(store.records(cid)) if src.os_user == "app")
    client.post("/captures/%d/sources" % cid, data={"keep": [keep]})
    capt = store.get_capture(cid)
    assert len(capt["excluded_sources"]) == 1
    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert "başka kaynaklardan" not in html and "kaynak analiz dışında" in html and "SIRON.ALERT" not in html.split("Kaynaklar")[0]
    assert S2 not in client.get("/captures/%d/timeline" % cid).get_data(as_text=True).split("tl-step")[1]
    r = client.post("/captures/%d/sources" % cid, data={})                     # cannot drop everything
    assert r.status_code == 302 and len(store.get_capture(cid)["excluded_sources"]) == 1


def test_live_feed_and_activity_check(env):
    client, oracle, store, _ = env
    oracle.records = [rec(1, Q1, " #1(1):1"), other(2, Q2)]
    client.post("/captures", data={"name": "Canlı"})
    cid = store.list_captures()[0]["id"]
    live = client.get("/captures/%d/live" % cid).get_json()
    assert live["mixed"] and len(live["sources"]) == 2
    d = client.get("/captures/activity?users=SIRON,RAPOR&minutes=5").get_json()
    assert d["records"] == 2 and d["users"] == ["SIRON", "RAPOR"] and len(d["sources"]) == 2
    assert oracle.last_filter.db_users == ["SIRON", "RAPOR"]
    assert (oracle.last_filter.end_utc - oracle.last_filter.start_utc).total_seconds() == 300
    oracle.records = []
    assert client.get("/captures/activity").get_json()["records"] == 0


# --------------------------------------------------------------------------- markers

def test_markers_live_and_on_timeline(env):
    client, oracle, store, _ = env
    oracle.records = [rec(1, Q1, " #1(1):1"), rec(2, Q2, " #1(1):A #2(1):B"), rec(3, Q1, " #1(1):2")]
    client.post("/captures", data={"name": "İşaretli"})
    cid = store.list_captures()[0]["id"]
    page = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert "İşaret koy" in page
    r = client.post("/captures/%d/markers" % cid, data={"label": "Ekran açıldı"}, headers={"X-Requested-With": "fetch"})
    assert r.get_json()["label"] == "Ekran açıldı" and r.get_json()["time"]
    assert client.post("/captures/%d/markers" % cid, data={"label": " "},
                       headers={"X-Requested-With": "fetch"}).status_code == 400
    client.post("/captures/%d/stop" % cid)
    records = sorted(store.records(cid), key=lambda x: x["ts"])
    client.post("/captures/%d/markers" % cid, data={"label": "Ara'ya bastım", "before": records[1]["ts"]})
    html = client.get("/captures/%d/timeline?gap=30" % cid).get_data(as_text=True)
    assert "Ara&#39;ya bastım" in html and "Adım 2" in html                   # marker splits despite no pause
    assert "Ekran açıldı" in html and "bu işaretten sonra SQL gelmedi" in html   # live marker came after the SQL
    assert 'data-label="Ara&#39;ya bastım"' in html
    marks = store.markers(cid)
    client.post("/captures/markers/%d" % marks[0]["id"], data={"label": "Ara butonu"})
    assert store.get_marker(marks[0]["id"])["label"] == "Ara butonu"
    client.post("/captures/markers/%d" % marks[0]["id"], data={"action": "delete"})
    assert len(store.markers(cid)) == 1
    assert "1</b><span>işaret" in client.get("/captures/%d" % cid).get_data(as_text=True)
    client.post("/captures/%d/delete" % cid)
    assert store.markers(cid) == []


# --------------------------------------------------------------------------- extraction queries

def test_extract_query_flow(env):
    client, oracle, store, _ = env
    cid = capture(client, store, oracle, [rec(1, Q1, " #1(1):7"), rec(2, Q2, " #1(4):OPEN #2(5):C0042")],
                  schema="SIRON")
    html = client.get("/captures/%d/sql/%s" % (cid, S1)).get_data(as_text=True)
    assert "Tüm kayıtlar için sorgu üret" in html
    page = client.get("/captures/%d/sql/%s/extract" % (cid, S1)).get_data(as_text=True)
    assert "c.id = :1" in page and "a.cust_id = c.id" in page and "Taşıma paketine ekle" in page
    gen_sql = page.split('name="sql"')[1].split(">", 1)[1].split("</textarea>")[0]
    assert ":1" not in gen_sql and "JOIN account" in gen_sql

    oracle.result = (["SATIR"], [(1234,)], False)
    page = client.post("/captures/%d/sql/%s/extract" % (cid, S1), data={"do": "count", "sql": "SELECT 1 FROM t"})
    assert "1.234" in page.get_data(as_text=True) and oracle.ran[-1][0] == "SELECT COUNT(*) AS satir FROM (SELECT 1 FROM t)"
    assert oracle.last_schema == "SIRON"
    oracle.result = (["NAME", "IBAN"], [("Ali Veli", "TR01")], False)
    assert "Önizleme" in client.post("/captures/%d/sql/%s/extract" % (cid, S1),
                                     data={"do": "preview", "sql": "SELECT 1 FROM t"}).get_data(as_text=True)
    csv = client.post("/captures/%d/sql/%s/extract" % (cid, S1), data={"do": "csv", "sql": "SELECT 1 FROM t", "name": "a b"})
    assert csv.headers["Content-Disposition"].endswith('a_b.csv"') or "a_b.csv" in csv.headers["Content-Disposition"]

    r = client.post("/captures/%d/sql/%s/extract" % (cid, S1),
                    data={"do": "save", "sql": gen_sql, "name": "Müşteri Detay · Üst bilgi", "note": "üst"})
    qid = store.extract_queries()[0]["id"]
    assert r.headers["Location"].endswith("/migration/queries/%d" % qid)
    assert store.extract_queries()[0]["removed"] == ["c.id = :1"]
    client.post("/captures/%d/sql/%s/extract" % (cid, S1), data={"do": "save", "sql": gen_sql, "name": "Tekrar"})
    assert len(store.extract_queries()) == 1 and store.extract_queries()[0]["name"] == "Tekrar"   # same SQL updates

    mig = client.get("/migration").get_data(as_text=True)
    assert "Ekran sorguları" in mig and "Tekrar" in mig and "1</b><span>ekran sorgusu" in mig
    z = zipfile.ZipFile(io.BytesIO(client.get("/migration.zip").data))
    names = z.namelist()
    qfile = next(n for n in names if n.startswith("sql/E"))
    assert "ALTER SESSION SET CURRENT_SCHEMA = SIRON;" in z.read(qfile).decode() and "JOIN account" in z.read(qfile).decode()
    r = client.post("/migration/extract", data={"mode": "decided"})
    job = store.get_job(int(r.headers["Location"].rsplit("/", 1)[1]))
    assert job["status"] == "done", job["message"]
    assert any(f["table"].startswith("Ekran sorgusu: Tekrar") for f in job["result"]["files"])

    page = client.get("/migration/queries/%d" % qid).get_data(as_text=True)
    assert "Paketten çıkar" in page and "c.id = :1" in page
    client.post("/migration/queries/%d" % qid, data={"do": "save", "sql": "SELECT 2 FROM dual", "name": "Yeni ad"})
    q = store.get_extract_query(qid)
    assert q["name"] == "Yeni ad" and q["sql_text"] == "SELECT 2 FROM dual"
    client.post("/migration/queries/%d" % qid, data={"do": "delete"})
    assert store.extract_queries() == []
    assert client.get("/migration/queries/%d" % qid).status_code == 404


def test_screen_extract_all(env):
    client, oracle, store, _ = env
    cid = capture(client, store, oracle, [rec(1, Q1, " #1(1):7"), rec(2, Q2, " #1(4):OPEN #2(5):C0042"),
                                          rec(3, "UPDATE alert SET status = :1 WHERE alert_id = :2", " #1(1):X #2(1):1",
                                              action="UPDATE")])
    client.post("/inventory/sql/bulk", data={"capture_id": cid, "sql": [S1, S2, compute_sql_id(
        "UPDATE alert SET status = :1 WHERE alert_id = :2")], "new_screen": "Müşteri > Detay", "note": "Liste"})
    sid = store.list_screens()[0]["id"]
    assert "lerden üret" in client.get("/inventory/%d" % sid).get_data(as_text=True)
    client.post("/inventory/%d/extract" % sid)
    queries = store.extract_queries(sid)
    assert len(queries) == 2 and all(":B" not in q["sql_text"] and ":1" not in q["sql_text"] for q in queries)
    html = client.get("/inventory/%d" % sid).get_data(as_text=True)
    assert "Detay · Liste" in html and "Taşıma sorguları" in html
    client.post("/inventory", data={"action": "delete", "id": sid})
    assert all(q["screen_id"] is None for q in store.extract_queries())      # queries survive, unlinked
