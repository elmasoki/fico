-- =====================================================================
-- AUDIT'İ AÇMA (Oracle 19c, unified auditing)
-- SQL_TEXT ve SQL_BINDS kolonları ek ayar gerekmeden dolar.
-- ÖRNEKTİR: politika adı ve kullanıcılar ortamınıza göre değişir.
-- Siron SQL Tracer, UNIFIED_AUDIT_TRAIL'i yalnızca config.ini'deki
-- [siron] db_user'a göre okur; politika adı / diğer kullanıcılar önemli değildir.
-- Tek şart: Siron'un bağlandığı DB kullanıcısı audit kapsamında olmalı.
-- =====================================================================

CREATE AUDIT POLICY sorgu_pol
  ACTIONS SELECT, INSERT, UPDATE, DELETE, MERGE;

-- sadece belirli kullanıcılar için (Siron'un bağlandığı kullanıcı listede olmalı)
-- <kullanici1>, <kullanici2> yerine kendi kullanıcılarınızı yazın
AUDIT POLICY sorgu_pol BY <kullanici1>, <kullanici2>;

-- ya da herkes, batch kullanıcısı hariç
-- (Siron SQL Tracer'ın okuyucu kullanıcısını da hariç tutmak hacmi azaltır)
-- AUDIT POLICY sorgu_pol EXCEPT <batch_kullanicisi>;

-- ÖNEMLİ: Audit yalnızca YENİ açılan oturumlarda geçerlidir.
-- Siron uygulama sunucusundaki connection pool'u yeniden başlatın.

-- Kontrol
SELECT * FROM audit_unified_enabled_policies WHERE policy_name = 'SORGU_POL';

-- Birkaç dakika sonra kayıt geliyor mu? ('SIRON' yerine Siron'un DB kullanıcısı)
SELECT event_timestamp, action_name, object_name, SUBSTR(sql_text, 1, 100) sql_text, sql_binds
  FROM unified_audit_trail
 WHERE dbusername = 'SIRON'
 ORDER BY event_timestamp DESC
 FETCH FIRST 20 ROWS ONLY;
