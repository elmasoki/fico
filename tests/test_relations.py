from catalog_fixture import make

from siron_tracer.relations import (build_relations, build_select, find_join_tree, parse_relation_id,
                                    to_dot, to_mermaid)
from siron_tracer.sqlinsight import analyse_sql

CAT = make()
C, A, T, AL = ("SIRON", "CUSTOMER"), ("SIRON", "ACCOUNT"), ("SIRON", "TRANSACTION"), ("SIRON", "ALERT")
ALL = {C, A, T, AL}


def rels(insights=(), checks=None, **kw):
    return {(r.child[1], r.child_cols, r.parent[1], r.parent_cols): r
            for r in build_relations(CAT, ALL, insights=insights, checks=checks, **kw)}


def test_constraint_and_name_inference():
    r = rels()
    fk = r[("ACCOUNT", ("CUST_ID",), "CUSTOMER", ("ID",))]
    assert fk.confidence == 100 and "constraint" in fk.sources
    guess = r[("ALERT", ("CUST_NO",), "CUSTOMER", ("CUST_NO",))]
    assert guess.main_source == "name" and 50 <= guess.confidence <= 70
    # TRANSACTION.ACC_NO -> ACCOUNT.ACC_NO (unique key)
    assert ("TRANSACTION", ("ACC_NO",), "ACCOUNT", ("ACC_NO",)) in r


def test_sql_join_is_merged_and_oriented():
    ins = [("s1", analyse_sql("select 1 from customer c, account a where c.id = a.cust_id", CAT, "SIRON")),
           ("s2", analyse_sql("select 1 from transaction t join account a on a.acc_no = t.acc_no", CAT, "SIRON"))]
    r = rels(ins)
    fk = r[("ACCOUNT", ("CUST_ID",), "CUSTOMER", ("ID",))]
    assert set(fk.sources) == {"constraint", "sql"} and fk.sql_ids == {"s1"}
    tx = r[("TRANSACTION", ("ACC_NO",), "ACCOUNT", ("ACC_NO",))]
    assert tx.confidence == 90 and tx.directed


def test_data_check_changes_confidence():
    rid = "SIRON.ALERT(CUST_NO)>SIRON.CUSTOMER(CUST_NO)"
    assert rels(checks={rid: (99, 100)})[("ALERT", ("CUST_NO",), "CUSTOMER", ("CUST_NO",))].confidence == 85
    assert rels(checks={rid: (10, 100)})[("ALERT", ("CUST_NO",), "CUSTOMER", ("CUST_NO",))].confidence == 25
    assert parse_relation_id(rid) == (AL, ("CUST_NO",), C, ("CUST_NO",))


def test_scope_and_min_confidence():
    only = build_relations(CAT, {A}, other={C})
    assert [(r.child[1], r.parent[1]) for r in only] == [("ACCOUNT", "CUSTOMER")]
    assert all(r.confidence >= 90 for r in build_relations(CAT, ALL, min_confidence=90))


def test_join_tree_and_select():
    all_rels = build_relations(CAT, ALL)
    edges, unreachable = find_join_tree(all_rels, [C, T, AL])
    assert unreachable == []
    sql = build_select(C, edges, {C: ["CUST_NO"]})
    assert "FROM SIRON.CUSTOMER t1" in sql
    assert "LEFT JOIN SIRON.ACCOUNT t2 ON t2.CUST_ID = t1.ID" in sql      # intermediate table added
    assert "ON t3.ACC_NO = t2.ACC_NO" in sql and "t1.CUST_NO" in sql
    edges, unreachable = find_join_tree([], [C, A])
    assert unreachable == [A]
    assert "CROSS JOIN" in build_select(C, [], extra_tables=[A])


def test_exports():
    all_rels = build_relations(CAT, ALL)
    mmd = to_mermaid(ALL, all_rels, CAT)
    assert "CUSTOMER ||--o{ ACCOUNT" in mmd and "CUSTOMER ||..o{ ALERT" in mmd and "NUMBER ID PK" in mmd
    assert '"SIRON.ACCOUNT" -> "SIRON.CUSTOMER"' in to_dot(ALL, all_rels)
