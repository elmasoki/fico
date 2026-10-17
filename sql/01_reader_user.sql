-- =====================================================================
-- Siron SQL Tracer'ın bağlanacağı OKUYUCU kullanıcı (DBA ile çalıştırın)
-- Siron kullanıcısının kendisiyle bağlanmayın: bu uygulamanın sorguları
-- da audit'e düşer ve sonuçları kirletir.
-- =====================================================================
DEFINE siron_owner = SIRON
DEFINE reader      = SIRON_TRACER

CREATE USER &reader IDENTIFIED BY "Degistir_123";
GRANT CREATE SESSION TO &reader;

-- Unified audit trail okuma (12c+)
GRANT AUDIT_VIEWER TO &reader;
-- (Opsiyonel) 12.1 queued-write modunda FLUSH_UNIFIED_AUDIT_TRAIL için:
-- GRANT AUDIT_ADMIN TO &reader;

-- DBA_AUDIT_TRAIL, DBA_OBJECTS, V$ görünümleri, AUDIT_UNIFIED_ENABLED_POLICIES vb.
GRANT SELECT_CATALOG_ROLE TO &reader;

-- Traditional audit tam SQL metni (audit_source = aud$) ve cursor cache
GRANT SELECT ON SYS.AUD$                 TO &reader;
GRANT SELECT ON SYS.AUDIT_ACTIONS        TO &reader;
GRANT SELECT ON SYS.GV_$SQL              TO &reader;
GRANT SELECT ON SYS.GV_$SQL_BIND_CAPTURE TO &reader;

-- Siron tablolarını okuyabilmek için (sorguları çalıştırıp sonucu görmek)
BEGIN
  FOR o IN (SELECT owner, object_name
              FROM dba_objects
             WHERE owner = '&siron_owner'
               AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')) LOOP
    BEGIN
      EXECUTE IMMEDIATE 'GRANT SELECT ON "' || o.owner || '"."' || o.object_name || '" TO &reader';
    EXCEPTION WHEN OTHERS THEN
      DBMS_OUTPUT.PUT_LINE('Atlandı: ' || o.object_name || ' - ' || SQLERRM);
    END;
  END LOOP;
END;
/
-- Test ortamında daha basit alternatif:
-- GRANT SELECT ANY TABLE TO &reader;
-- Sorgular Siron paket/fonksiyonlarını çağırıyorsa:
-- GRANT EXECUTE ON &siron_owner..<PAKET_ADI> TO &reader;
