from siron_tracer.catalog import Catalog, Table, Column, Constraint
def col(t, n, i, typ="NUMBER"):
    return Column("SIRON", t, n, i, typ, 22 if typ != "NUMBER" else None, None, None, True, None)
def make():
    tabs = {
      "CUSTOMER": [("ID","NUMBER"),("CUST_NO","VARCHAR2"),("NAME","VARCHAR2"),("RISK_CLASS","VARCHAR2")],
      "ACCOUNT": [("ID","NUMBER"),("CUST_ID","NUMBER"),("ACC_NO","VARCHAR2"),("IBAN","VARCHAR2"),("BALANCE","NUMBER")],
      "TRANSACTION": [("TX_ID","NUMBER"),("ACC_NO","VARCHAR2"),("AMOUNT","NUMBER"),("TX_DATE","DATE")],
      "ALERT": [("ALERT_ID","NUMBER"),("CUST_NO","VARCHAR2"),("STATUS","VARCHAR2")],
    }
    tables = [Table("SIRON", t, "TABLE", 100, None, None, [col(t, n, i, ty) for i,(n,ty) in enumerate(cs,1)]) for t, cs in tabs.items()]
    cons = [Constraint("SIRON","CUSTOMER_PK","P","CUSTOMER",None,None,("ID",)),
            Constraint("SIRON","CUSTOMER_UK","U","CUSTOMER",None,None,("CUST_NO",)),
            Constraint("SIRON","ACCOUNT_PK","P","ACCOUNT",None,None,("ID",)),
            Constraint("SIRON","ACCOUNT_UK","U","ACCOUNT",None,None,("ACC_NO",)),
            Constraint("SIRON","ALERT_PK","P","ALERT",None,None,("ALERT_ID",)),
            Constraint("SIRON","ACC_CUST_FK","R","ACCOUNT","SIRON","CUSTOMER_PK",("CUST_ID",))]
    return Catalog(tables, {("SIRON","PKG_RISK"):"PACKAGE"}, cons, "v1")
