-- =====================================================================
-- İş bitince audit'i kapatın. Uygulama kayıtları kendi SQLite dosyasına
-- kopyaladığı için analiz kaybolmaz.
-- =====================================================================

-- ÖRNEKTİR: açarken kullandığınız politika adı ve kullanıcılarla değiştirin.
NOAUDIT POLICY sorgu_pol BY <kullanici1>, <kullanici2>;
-- NOAUDIT POLICY sorgu_pol;          -- EXCEPT ile açtıysanız

DROP AUDIT POLICY sorgu_pol;

-- Unified trail'deki TÜM kayıtları siler. Başka audit ayarları varsa
-- DBA ile birlikte karar verin / önce arşivleyin.
-- BEGIN
--   DBMS_AUDIT_MGMT.CLEAN_AUDIT_TRAIL(
--     audit_trail_type        => DBMS_AUDIT_MGMT.AUDIT_TRAIL_UNIFIED,
--     use_last_arch_timestamp => FALSE);
-- END;
-- /
