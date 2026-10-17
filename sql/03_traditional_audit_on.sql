-- =====================================================================
-- TRADITIONAL AUDITING (11g veya unified kullanılamıyorsa)
-- SQL metni ve bindler için AUDIT_TRAIL = DB,EXTENDED gerekir (RESTART ister).
-- =====================================================================
SHOW PARAMETER audit_trail

ALTER SYSTEM SET audit_trail = DB, EXTENDED SCOPE = SPFILE;
-- >>> Veritabanını yeniden başlatın <<<

AUDIT SELECT TABLE, INSERT TABLE, UPDATE TABLE, DELETE TABLE BY SIRON BY ACCESS;
AUDIT EXECUTE PROCEDURE BY SIRON BY ACCESS;
-- Statement audit seçenekleri de yeni oturumlarda geçerli olur: Siron connection pool'unu yenileyin.

-- Kontrol
SELECT * FROM dba_stmt_audit_opts WHERE user_name = 'SIRON';

-- Not: DBA_AUDIT_TRAIL.SQL_TEXT 2000 karakterde kesilir. Uzun sorgular için
-- config.ini'de audit_source = aud$ kullanın (SYS.AUD$.SQLTEXT tam CLOB'dur).
