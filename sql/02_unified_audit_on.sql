-- =====================================================================
-- UNIFIED AUDITING (Oracle 12c ve üstü) - ÖNERİLEN
-- Pure unified mode şart değildir; mixed mode'da da unified politikalar çalışır.
-- SQL_TEXT ve SQL_BINDS kolonları ek ayar gerekmeden dolar.
-- =====================================================================

-- Siron kullanıcısının tüm SQL'lerini kaydeden politika
CREATE AUDIT POLICY siron_trace_pol ACTIONS ALL;

-- 19c+ ise PL/SQL içinden çalışan özyinelemeli SQL'leri dışarıda bırakmak için
-- yukarıdaki yerine (paket içindeki SQL'leri de görmek istiyorsanız KULLANMAYIN):
-- CREATE AUDIT POLICY siron_trace_pol ACTIONS ALL ONLY TOPLEVEL;

AUDIT POLICY siron_trace_pol BY SIRON;

-- ÖNEMLİ: Politika yalnızca YENİ açılan oturumlarda geçerlidir.
-- Siron uygulama sunucusundaki connection pool'u yeniden başlatın (veya Siron'u restart edin).

-- Kontrol
SELECT * FROM audit_unified_enabled_policies WHERE policy_name = 'SIRON_TRACE_POL';

-- Birkaç dakika sonra kayıt geliyor mu?
SELECT event_timestamp, action_name, object_name, SUBSTR(sql_text, 1, 100) sql_text, sql_binds
  FROM unified_audit_trail
 WHERE dbusername = 'SIRON'
 ORDER BY event_timestamp DESC
 FETCH FIRST 20 ROWS ONLY;
