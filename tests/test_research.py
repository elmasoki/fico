import io
import re

import pytest

from siron_tracer import create_app, knowledge as kb
from siron_tracer.config import Settings
from siron_tracer.mdrender import render
from siron_tracer.store import Store
from test_app import FakeOracle, rec

KYC_SQL = "SELECT k.kyc_nachname, p.risiko FROM kyccust k JOIN presult p ON p.kundnr = k.kundnr WHERE k.kundnr = :1"


def siron_catalog():
    tables = [("SIRON", "KYCCUST", 1200, "KUNDNR KYC_NACHNAME KYC_SP_04 HISTBIS"),
              ("SIRON", "PRESULT", 1200, "KUNDNR RISIKO ERFASSER HISTBIS"),
              ("SIRON", "TBRLEINT", 80, "RL_KUERZEL BEZ KOMMENTAR HISTBIS"),
              ("SIRON", "GWGKUNDE", 5000, "KUNDNR NACHNAME GEBURTSORT"),
              ("SIRON", "GWGXYZ", 3, "WERT"),
              ("SIRON", "LOCAL_EXTRA", 10, "ID")]
    cols = []
    for owner, t, _, names in tables:
        cols += [(owner, t, c, i, "VARCHAR2", 30, None, None, "Y", None) for i, c in enumerate(names.split(), 1)]
    return {"objects": [(o, t, "TABLE") for o, t, _, _ in tables],
            "tables": [(o, t, "TABLE", n, None, None) for o, t, n, _ in tables],
            "columns": cols, "constraints": [], "cons_columns": [], "dependencies": []}


@pytest.fixture
def env(tmp_path):
    settings = Settings(oracle_dsn="x", oracle_user="u", siron_db_user="SIRON", siron_schemas=["SIRON"],
                        secret_key="t", export_dir=str(tmp_path / "exports"))
    oracle = FakeOracle()
    catalog = siron_catalog()
    oracle.load_catalog = lambda schemas: catalog
    app = create_app(settings, oracle=oracle, store=Store(":memory:"), sync_jobs=True)
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/catalog/refresh")
    return client, oracle, app.extensions["siron"]["store"]


# --------------------------------------------------------------------------- knowledge base

def test_classify_and_consistency():
    assert kb.classify("KYCCUST").known.confidence == "verified"
    assert kb.classify("gwgtrans").module.id == "aml"
    c = kb.classify("GWGNEWTABLE")
    assert c.module.id == "aml" and c.known is None and c.basis == "Önek eşleşmesi"
    assert kb.classify("KSTATFA").module.id == "tcr"           # FA suffix wins over generic K*
    assert kb.classify("CASEFLAG2").module.id == "tcr"          # before ACM CASE*
    assert kb.classify("CASE_HEADER").module.id == "acm"
    assert kb.classify("TBQFORMS").module.id == "questionnaire"  # before TB*
    assert kb.classify("CUSTOMER") is None and kb.classify("COUNTRY") is None
    names = [t.name for t in kb.KNOWN_TABLES]
    assert len(names) == len(set(names))
    for t in kb.KNOWN_TABLES:
        assert t.module in kb.MODULE_BY_ID and t.confidence in kb.CONFIDENCE
        family = next((f for f in kb.FAMILIES if f.regex.search(t.name)), None)
        if family:                                               # known tables and prefix rules must agree
            assert family.module == t.module, t.name
    for f in kb.FAMILIES:
        assert f.module in kb.MODULE_BY_ID and f.confidence in kb.CONFIDENCE


def test_explain_german_names():
    assert kb.explain_text("KUNDNR") == "Müşteri numarası"
    assert "güncel kayıt" in kb.explain_text("HISTBIS")
    assert kb.explain_text("BUCHUNGSDATUM") == "BUCHUNG = kayıt / muhasebe · DATUM = tarih"
    assert "KUNDE = müşteri" in kb.explain_text("GWGKUNDE")
    assert "serbest alan" in kb.explain_text("KYC_SP_04")
    assert kb.explain_text("CUST_ID") == ""
    assert kb.explain_text("RISIKO_KZ") == "RISIKO = risk · KZ = işaret / bayrak"


def test_queries_follow_schema():
    for q in kb.QUERIES:
        assert q.category in kb.QUERY_CATEGORIES, q.id
        sql = q.for_schema("A0001")
        assert "{schema}" not in sql
        if q.runnable:
            assert re.match(r"\s*(SELECT|WITH)\b", sql, re.I), q.id
    assert "owner = 'A0001'" in kb.QUERY_BY_ID["historised"].for_schema("A0001")


def test_markdown_renderer_is_safe():
    html, toc = render("# T\n\n## Bölüm *1*\n\na <script>x</script> **b** `c<d>` [l](https://e.com/?a=1&b=2) "
                       "[bad](javascript:alert(1)) GWG\\*\n\n| A | B |\n|---|---|\n| 1 | **2** |\n\n```sql\nSELECT '<x>'\n```\n\n- i1\n- i2")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<strong>b</strong>" in html and "<code>c&lt;d&gt;</code>" in html
    assert 'href="https://e.com/?a=1&amp;b=2"' in html and "javascript:" not in html.split("[bad]")[0][-200:]
    assert 'href="javascript' not in html
    assert "GWG*" in html and "<table>" in html and "<td><strong>2</strong></td>" in html
    assert "SELECT &#x27;&lt;x&gt;&#x27;" in html or "SELECT '&lt;x&gt;'" in html
    assert "<ul><li>i1</li><li>i2</li></ul>" in html
    assert toc == [(2, "bolum-1", "Bölüm *1*")]
    full, full_toc = render(kb.load_document())
    assert len(full_toc) >= 8 and "<script" not in full.lower()


# --------------------------------------------------------------------------- pages

def test_research_pages(env):
    client, oracle, store = env
    for url in ["/research", "/research/module/kyc", "/research/module/unknown", "/research/tables",
                "/research/tables?module=platform&conf=verified&where=found", "/research/tables?where=missing&q=gwg",
                "/research/terms", "/research/terms?name=BUCHUNGSDATUM", "/research/queries?schema=A0001",
                "/research/document"]:
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Traceback" not in r.get_data(as_text=True)
    assert client.get("/research/module/nope").status_code == 404

    html = client.get("/research").get_data(as_text=True)
    assert "KYC: müşteri kabul" in html and "LOCAL_EXTRA" in html          # unclassified tables listed
    html = client.get("/research/module/kyc").get_data(as_text=True)
    assert "KYCCUST" in html and "Siron KYC müşteri ana tablosu" in html and "KSLMAIN" in html  # missing known
    html = client.get("/research/tables?module=platform&conf=verified&where=found").get_data(as_text=True)
    assert "/table/SIRON/TBRLEINT" in html and "TBRLIST" not in html
    html = client.get("/research/terms?name=BUCHUNGSDATUM").get_data(as_text=True)
    assert "kayıt / muhasebe" in html
    html = client.get("/research/queries?schema=A0001").get_data(as_text=True)
    assert "owner = &#39;A0001&#39;" in html and "PL/SQL" in html


def test_research_on_existing_pages(env):
    client, oracle, store = env
    oracle.records = [rec(1, KYC_SQL, " #1(4):1001", obj="KYCCUST")]
    client.post("/captures", data={"name": "KYC müşteri"})
    cid = store.list_captures()[0]["id"]
    client.post("/captures/%d/stop" % cid)

    html = client.get("/table/SIRON/KYCCUST").get_data(as_text=True)
    assert "Araştırma" in html and "Siron KYC müşteri ana tablosu" in html and "Doğrulanmış" in html
    assert "Müşteri numarası" in html                                        # column hint for KUNDNR
    html = client.get("/table/SIRON/GWGXYZ").get_data(as_text=True)
    assert "önek ailesine göre" in html
    assert "Araştırma</b>" not in client.get("/table/SIRON/LOCAL_EXTRA").get_data(as_text=True)

    html = client.get("/tables?all=1&module=kyc").get_data(as_text=True)
    assert "KYCCUST" in html and "GWGKUNDE" not in html
    html = client.get("/tables?all=1&module=none").get_data(as_text=True)
    assert "LOCAL_EXTRA" in html and "KYCCUST" not in html
    assert "Referenzlisten" in client.get("/search?q=tbrl").get_data(as_text=True)

    report = client.get("/report.html").get_data(as_text=True)
    assert "Siron modülleri (araştırma)" in report and "KYC müşteri ana tablosu" in report
    report = client.get("/report.html?research=0").get_data(as_text=True)
    assert "Siron modülleri (araştırma)" not in report


def test_upload_research_document(env):
    client, oracle, store = env
    data = {"file": (io.BytesIO("# Yeni araştırma\n\n## Bulgular\n\nGWGKUNDE doğrulandı.".encode("utf-8")), "v2.md")}
    client.post("/research/document", data=data, content_type="multipart/form-data")
    html = client.get("/research/document").get_data(as_text=True)
    assert "Yeni araştırma" in html and "v2.md" in html and "Orijinale dön" in html
    assert any(a["action"] == "research" for a in store.activity())
    client.post("/research/document", data={"file": (io.BytesIO(b"\xff\xfe\x00bad"), "x.md")},
                content_type="multipart/form-data")
    assert "Yeni araştırma" in client.get("/research/document").get_data(as_text=True)   # bad file rejected
    client.post("/research/document", data={"action": "reset"})
    html = client.get("/research/document").get_data(as_text=True)
    assert "Yeni araştırma" not in html and "IMTF" in html
