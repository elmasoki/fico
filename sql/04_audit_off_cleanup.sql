-- =====================================================================
-- İş bitince audit'i kapatın ve kayıtları temizleyin.
-- Uygulama kayıtları kendi SQLite dosyasına kopyaladığı için analiz kaybolmaz.
-- =====================================================================

-- ---------- Unified ----------
NOAUDIT POLICY siron_trace_pol BY SIRON;
DROP AUDIT POLICY siron_trace_pol;

-- Unified trail'deki TÜM kayıtları siler. Başka audit politikaları varsa
-- DBA ile birlikte karar verin / önce arşivleyin.
-- BEGIN
--   DBMS_AUDIT_MGMT.CLEAN_AUDIT_TRAIL(
--     audit_trail_type        => DBMS_AUDIT_MGMT.AUDIT_TRAIL_UNIFIED,
--     use_last_arch_timestamp => FALSE);
-- END;
-- /

-- ---------- Traditional ----------
NOAUDIT SELECT TABLE, INSERT TABLE, UPDATE TABLE, DELETE TABLE BY SIRON;
NOAUDIT EXECUTE PROCEDURE BY SIRON;
-- DELETE FROM sys.aud$ WHERE userid = 'SIRON';
-- COMMIT;
