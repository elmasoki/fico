from catalog_fixture import make

from siron_tracer.sqlinsight import analyse_sql, map_result_columns

CAT = make()
C = ("SIRON", "CUSTOMER")
A = ("SIRON", "ACCOUNT")
T = ("SIRON", "TRANSACTION")


def test_aliases_columns_and_usage():
    ins = analyse_sql("select c.cust_no, c.name nm, a.iban from customer c, account a "
                      "where a.cust_id = c.id and c.risk_class = :1 and balance > 0 order by a.acc_no", CAT, "SIRON")
    assert ins.tables == [C, A]
    assert ins.aliases["C"] == C and ins.aliases["A"] == A
    assert ins.columns[C + ("CUST_NO",)] == {"select"}
    assert ins.columns[C + ("RISK_CLASS",)] == {"filter"}
    assert ins.columns[A + ("BALANCE",)] == {"filter"}       # unqualified, resolved via catalogue
    assert ins.columns[A + ("ACC_NO",)] == {"order"}


def test_joins_ansi_oldstyle_and_outer():
    ins = analyse_sql("select 1 from account a join customer c on c.id = a.cust_id, transaction t "
                      "where t.acc_no(+) = a.acc_no", CAT, "SIRON")
    pairs = {(j.left[1:], j.right[1:]) for j in ins.joins}
    assert (("ACCOUNT", "CUST_ID"), ("CUSTOMER", "ID")) in pairs
    assert (("ACCOUNT", "ACC_NO"), ("TRANSACTION", "ACC_NO")) in pairs


def test_not_a_join():
    ins = analyse_sql("select 1 from account a, customer c where a.balance >= c.id and a.cust_id = :1 "
                      "and c.name = 'x = y'", CAT, "SIRON")
    assert ins.joins == []


def test_hibernate_style():
    sql = ("select customer0_.ID as ID1_0_, customer0_.NAME as NAME2_0_, accounts1_.IBAN as IBAN3_1_ "
           "from CUSTOMER customer0_ inner join ACCOUNT accounts1_ on customer0_.ID=accounts1_.CUST_ID "
           "where customer0_.CUST_NO=?")
    ins = analyse_sql(sql, CAT, "SIRON")
    assert len(ins.joins) == 1
    assert map_result_columns(ins, ["ID1_0_", "NAME2_0_", "IBAN3_1_"], CAT) == [
        C + ("ID",), C + ("NAME",), A + ("IBAN",)]


def test_star_and_mapping():
    ins = analyse_sql("select a.*, c.name from account a join customer c on c.id = a.cust_id", CAT, "SIRON")
    assert A in ins.star_tables
    cols = ["ID", "CUST_ID", "ACC_NO", "IBAN", "BALANCE", "NAME"]
    assert map_result_columns(ins, cols, CAT)[-1] == C + ("NAME",)
    assert map_result_columns(ins, cols, CAT)[3] == A + ("IBAN",)


def test_dml_and_cte():
    ins = analyse_sql("insert into alert (alert_id, cust_no, status) values (:1, :2, :3)", CAT, "SIRON")
    assert set(ins.columns) == {("SIRON", "ALERT", c) for c in ("ALERT_ID", "CUST_NO", "STATUS")}
    assert all(k == {"set"} for k in ins.columns.values())
    ins = analyse_sql("with x as (select cust_no from customer) select * from x", CAT, "SIRON")
    assert ins.tables == [C]


def test_without_catalogue_and_garbage():
    ins = analyse_sql("select a.x from t1 a join t2 b on b.id = a.t2_id")
    assert [j.left[1:] for j in ins.joins] + [j.right[1:] for j in ins.joins] == [("T1", "T2_ID"), ("T2", "ID")]
    assert analyse_sql("this is (not sql").tables == []
