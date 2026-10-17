# Siron veri sözlüğü: IMTF'den isteyin, Oracle'dan yeniden kurun

Siron AML'de "hangi tablo ne işe yarar" sorusunu yanıtlayan, herkese açık ya da Oracle kataloğunda hazır duran bir "tablolar tablosu" **yoktur**: bu araştırmada ~40 ayırt edici tablo adının (GWGKUNDE, GWATRHIT, TBDOMVAL, KSLMAIN, SIBFORM, FARCUSTOMER, TBQWKFLTREE…) hiçbiri açık web'de ve GitHub kod aramasında geçmedi; tek istisna, bir T24 entegrasyon deposunda gerçek Siron SQL'iyle görülen **KYCCUST, PRESULT ve TBRLEINT** oldu (ayrıntı ve sütun adları hemen aşağıdaki "Ek tarama" bölümünde). **Kod değerlerinin anlamını veren tablo bulundu: TBRLEINT** (Referenzlisten-Einträge; `RL_KUERZEL` liste kodu, `BEZ` kod, `KOMMENTAR` açıklama, `HISTBIS`='9999' güncel kayıt) ile başlık tablosu TBRLIST. IMTF, ürün dokümantasyonunun yalnızca destek portalı üzerinden verildiğini açıkça yazıyor ([IMTF Customer Support](https://imtf.com/customer-support/)). Resmi veri modeli ve arayüz dokümanlarının tek meşru kaynağı bu nedenle **IMTF Customer Portal (imtf.atlassian.net, Jira Service Management)**, Bensheim'daki eski Tonbeller mühendislik ekibi (**IMTF Siron GmbH, Almanya destek hattı +49 6251 8262697**) ve bankanın ilk kurulumunu yapan uygulayıcıdır; Türkiye için IMTF'nin listelediği tek teslimat ortağı **Holicy Consulting (İstanbul)**'dır ([IMTF Partners](https://imtf.com/imtf-partners/)). Veritabanının içinde iki katman aranmalıdır: Oracle'ın kendi `ALL_TAB_COMMENTS`/`ALL_COL_COMMENTS` görünümleri (DB2/Oracle/SQL Server'da aynı anda çalışan Siron 4GL mirası nedeniyle büyük olasılıkla boş; bu bir beklentidir, bulgu değil) ve Tonbeller platform tablolarının içinde saklanan olası bir uygulama seviyesi sözlük: **TBDEF, TBBO, TBFELDZ, TBINFO, TBDOMAIN/TBDOMVAL, TBMUSS, TBLNG, TBRESSOURCE** ile içe aktarım tarafında **TDIREPOS**. Bunların hepsi ad temelli hipotezdir ve raporda verilen SQL ile doğrulanmalıdır. Önekler modül düzeyinde güvenle okunabiliyor (GWG = Geldwäschegesetz, ürünün ilk adı "Siron GwG"; TB = TonBeller platformu; SL_/KSL/PSL = yaptırım listeleri; E/EMB = Embargo; FAR/TAX = TCR, yani FATCA/CRS; CACM/CASE/WORKFLOW = Alert & Case Manager), ancak **tek bir tablo adı bile kamuya açık bir belgede görülmediği için tablo düzeyindeki hiçbir anlam "doğrulanmış" sayılamaz**. Dokümantasyon gelene kadar en hızlı yol, Oracle kataloğunu (FK grafı, PK yapısı, satır sayıları, DML sayaçları), paylaşılan havuzdaki gerçek SQL'i (`V$SQL`/`V$SQL_PLAN`), hedefli unified audit kayıtlarını ve SchemaSpy/SQL Developer Data Modeler çıktısını birleştirip sözlüğü yeniden üretmek, bulguları da `COMMENT ON TABLE` ile kataloğa yazmaktır. PARAM_*, MASAK_2_SIRON_FIELD_MAP ve BANK_2_MASAK_CODE vendor şemasının parçası değil, bankanın MASAK ŞİB kod listelerine kurduğu köprüdür; SIBFORM/LOCKEDSIBFORMS için "Şüpheli İşlem Bildirimi formu" okuması güçlü ama kanıtsız bir hipotezdir.

## Ek tarama (GitHub kod araması + Wayback Machine, tarayıcıdan): üç tablo ve kod listesi tablosu gerçek SQL'de görüldü

Rapor yazıldıktan sonra araştırma ortamının açamadığı iki kanal kullanıcının tarayıcısından tarandı. Sonuçlar, yukarıdaki hipotezlerin bir kısmını **doğrulanmış** düzeye çıkarıyor; bu bölüm raporun geri kalanından daha güncel sayılmalıdır.

**1. GitHub'da gerçek Siron SQL'i: KYCCUST, PRESULT, TBRLEINT.** Bir Temenos T24 ↔ Siron KYC entegrasyon aracı ([ahmedrhuma/SironKYC-TemenosT24-middleware, Customer.java](https://raw.githubusercontent.com/ahmedrhuma/SironKYC-TemenosT24-middleware/master/src/com/tonebeller/middleware/Customer.java); [config.json](https://raw.githubusercontent.com/ahmedrhuma/SironKYC-TemenosT24-middleware/master/config.json)) doğrudan Siron veritabanına (SQL Server, veritabanı adı `AMLDATEN`) SQL atıyor ve şu yapıyı açığa çıkarıyor:

- **Şema düzeni:** enstitüye özel şema `A0001` ("client schema", `INSTITUTSNR`=0001) ve paylaşılan `GLOBAL` şeması ("global schema"). Siron, kurum verisini `A<enstitü no>` şemasında, ortak referans verisini `GLOBAL`'de tutuyor. Oracle'da `SELECT DISTINCT owner FROM all_tables` ile aynı ayrımın (ör. `A0001`/`GLOBAL` ya da tek şema) kontrol edilmesi gerekir.
- **KYCCUST** sütunları: `INSTITUTSNR`, `KUNDNR` (müşteri no), `HISTBIS`, `KYC_VORNAME` (ad), `KYC_NACHNAME` (soyad), `KYC_SP_01 … KYC_SP_32` (kuruma göre eşlenen serbest alanlar: bu kurulumda SP_01=cinsiyet, SP_02=dil, SP_03=sektör, SP_04=unvan, SP_06=kısa ad, SP_07=adlar, SP_32=şube kodu), `RISIKO` (risk). → KYCCUST = Siron KYC müşteri ana tablosu (**doğrulanmış**).
- **PRESULT** sütunları: `INSTITUTSNR`, `KUNDNR`, `HISTBIS`, `ERFASSER` (kaydı giren kullanıcı), `RISIKO` (risk sınıfı). → PRESULT = KYC risk sınıflandırma/skorlama **sonucu** (**doğrulanmış**); raporun "P* = PEP" okuması en azından PRESULT için düzeltilmelidir: P* ailesi KYC'nin skorlama/profil sonuç katmanıdır (PRESULT_ARCHIVE arşivi, PRESULT1706 geçiş kopyası).
- **TBRLEINT** (GLOBAL şemasında) sütunları: `RL_KUERZEL` (Referenzliste kısaltması = liste kodu), `BEZ` (Bezeichnung = kod değeri), `KOMMENTAR` (açıklama metni), `HISTBIS`. Sorgu `KYC_SP_04` gibi kod alanlarını `TBRLEINT.KOMMENTAR` ile açıklamaya çeviriyor. → **TBRLEINT = Referenzlisten-Einträge = kod listesi girdileri; TBRLIST = liste başlıkları; TBRLISTFIELD/TBRLEINTFIELD = alan tanımları.** Bu, aranan "kodların anlamını veren tablo"dur (**doğrulanmış**). IMTF 25.2 sürüm notundaki "Reference Lists" bileşeni de budur.
- **Tarihçeleme kalıbı:** `HISTBIS = '9999'` güncel kaydı işaretler (`HISTVON`/`HISTBIS` = geçerlilik başlangıç/bitiş). Siron tablolarının çoğunda aynı kalıp beklenir; `ALL_TAB_COLUMNS`'ta `HISTBIS` içeren tabloları listelemek "tarihçeli ana veri" tablolarını tek sorguda ayırır.
- Aynı aracın okuduğu müşteri numarası dosyası `gwnkunde.txt`, KYC servis hesabı ise `demo/gwg` — GwG adlandırması uygulama katmanında da sürüyor.

```sql
-- Tarayıcı bulgularını kendi şemanızda doğrulayın
SELECT DISTINCT owner FROM all_tables WHERE table_name IN ('KYCCUST','PRESULT','TBRLEINT','TBRLIST');
SELECT table_name, column_name, data_type, data_length FROM all_tab_columns
WHERE  table_name IN ('KYCCUST','PRESULT','TBRLEINT','TBRLIST','TBRLISTFIELD','TBRLEINTFIELD') ORDER BY table_name, column_id;
-- Kod listesi sözlüğü: hangi liste (RL_KUERZEL) hangi kodları (BEZ) hangi açıklamayla (KOMMENTAR) tutuyor?
SELECT rl_kuerzel, COUNT(*) kod_sayisi, MIN(bez) ornek_kod, MIN(kommentar) ornek_aciklama
FROM   tbrleint WHERE histbis = '9999' GROUP BY rl_kuerzel ORDER BY rl_kuerzel;
-- Tarihçeli tablolar
SELECT table_name FROM all_tab_columns WHERE column_name = 'HISTBIS' ORDER BY table_name;
```

**2. Tonbeller'in resmi Siron KYC web servisi (WSDL) tablo adlarını açıklıyor.** Bir entegrasyon deposunda Tonbeller'in `KYCService01` SOAP servisinin WSDL'i duruyor (ad alanları `server/db/data.ws.sironkyc.tonbeller.com`; [rosamedgroup/SmartTool, KYCService01.wsdl](https://raw.githubusercontent.com/rosamedgroup/SmartTool/main/src/main/webapp/wsdl/SironKYC/KYCService01.wsdl)). İşlemler: `kycScore`, `kycGetResults`, `kycGetDetailResults`, `kycGetCustIdState`, `kycGetPdfProtocol`, `kycGetCustomerInformation`, `kycGetWorkFlowStatus`, `kycRenameCustId`, `kycDeleteCustomer`, `taxActScore`, `getFatcaStatus`, `addChangeOfCircumstances`, `addFATCADocument`, `getDocumentTypes`. Veri tipleri tablo ailelerine birebir oturuyor:

| WSDL tipi / alanı | Karşılık gelen tablo(lar) | Sonuç |
|---|---|---|
| `PersonData`: personID, firstName, lastName, gender, birthDate/City/Country, natCountry, HCountry, passNo, street, zipCode, city, branch, custType, **cusy**, csMNo, riskClass, customFields(key/value) | KYCCUST (+ KYC_SP_xx = customFields), **GWGKUSY = KuSy** | KuSy ("Kundensystematik") 2003 whitepaper'da da müşteri alanı olarak geçiyor → GWGKUSY **olası→doğrulanmış kavram** |
| `BoData`: boKundnr, kundnr, relType, share, f1–f3 | CRELAT / CRELART (ilişki ve türü), KSL*RELATIONS | Gerçek faydalanıcı (beneficial owner) ilişkisi |
| `KycRisk`: riskAbbrev, riskClass, riskDesc | **TBRIKLAS** (Risikoklasse) | Risk sınıfı tablosu |
| `KycActions`: shortText, longText, rang | **KHANDANW** (Handlungsanweisung) | İşlem talimatları, sıralı |
| `DetailListMatch`: slId, slInstitutsId, slListName, score, hits[fieldId, matchedWord, searchedWord] | **SL_\*** (slListName), KSYNONYMHIT / PHIT | "sl" = screening list öneki API'de de kullanılıyor |
| `BusinessRuleResult`: brId, brAction, brDescription, brPrePost | **KBRFA** (KYC Business Rules FATCA) | "BR" = business rule |
| `TaxActResult01`: caseFlags, caseStatus, casePersonStatus*, scoringCocCounter, scoringDetail[indicationName, instructionText] | **TAXACTCASE**, CASEFLAG*, FARCASEFLAG*, **KSTATFA** | TaxAct = FATCA (Foreign Account **Tax** Compliance **Act**) vakası |
| `ChangeOfCircumstances`: cocType, cocText, cocHash, histVon, histBis | **KCOCFA** (Change of Circumstances FATCA) | "FA" soneki = FATCA (**doğrulanmış kalıp**: KBRFA, KCOCFA, KSTATFA) |
| `DocumentData`: documentTypeNo, geprueftJN, expirationDate, followUpDate, mimeType; `DocumentTypeData01`: typeNr, name, followUpLeadDays | **DOCUMENTTYPE**, ATTACHMENT, PDOC | Belge türleri ve belgeler |
| `WorkFlowStatus01`: existsOpenWorkFlowSteps | **TBQWKFLOPENSTEPS** | Anket iş akışı açık adımları |
| `CustIdState01`: questionaryEntryExist, scoringResultExist | TBQ\* (anket), PRESULT (skor sonucu) | |
| `kycGetPdfProtocol` | **KCKPROT** (Check-Protokoll) | KYC kontrol protokolü PDF'i |

**3. Wayback Machine (tonbeller.com arşivi) TDI ve TB ailesini yerine oturtuyor.** `Siron®TDI` Tonbeller'in web tabanlı OLAP/raporlama ön yüzüdür ("Reporting and Analyses for Specialists"; veri ambarı yapısı değişince navigatör otomatik güncellenir, [arşiv 2011](https://web.archive.org/web/20110201132704/http://www.tonbeller.com/products/bi/sirontdi)) → **TDIREPOS / TDIPKGEN / TDILOCK = Siron TDI raporlama katmanının kendi deposu** (içe aktarım arayüzü değil). `Siron®Kern`, "Siron-Sprache"si, Report-Designer'ı ve kendi yetki sistemiyle BI-Suite'in temel modülüdür; OS/390, BS2000, AS/400, Unix, Windows üzerinde DL/I, DB2, Sesam, Oracle, Informix, SQL Server, mySQL ile çalışır ([arşiv 2006](https://web.archive.org/web/20060519133007/http://www.tonbeller.com/produkte/bitools/kern/)) — TB* platform tablolarının bu çekirdeğe ait olduğu okuması güçleniyor. Tonbeller aynı dönemde açık kaynak JPivot/WCF/tbutils kütüphanelerinin (`com.tonbeller.*`) yazarıdır; TDI bu OLAP teknolojisi üzerine kuruludur. 2003 tarihli **Siron GwG White Paper** ([arşiv](https://web.archive.org/web/20040903202614/http://www.tonbeller.com/PDF/SironGwG_WhitePaper_deu.pdf)) veri akışını "Datenversorgung (Batch) → Kunde/Konto, Transaktionen, Statistik → Scoring (Batch) → §25a Data Mart (snowflake şeması) → Monitoring früherer Auffälligkeiten → XML Online-Dialog" olarak çizer; 30 standart "Indiz"in her birinin tabanını **Kunde / Konto / Kto-Statistik / Transaktion** olarak verir (GWGIND, GB_/RB_ "STM/IND/KAT" tablolarının aday anlamı: istatistik/gösterge/kategori); DataMart içeriğini sayar (Kundennummer, Kundenname, **KuSy**, Kundenbetreuer, Kundenprofil, Anschrift, Nationalität, Freistellungsauftrag, Verbindungen; Konto: Geschäftsart, Eröffnung/Schließung, Summe/Anzahl Umsätze; Transaktion: Buchungs-/Valutadatum, Textschlüssel, Primanota, Währung, Betrag, Geschäftsstelle, Empfängerland, Gegenkonto, Bar/Unbar-Kennzeichen, Verwendungszweck); ve Siron GwG 3.1'in KPMG tarafından IDW PS 880'e göre **"Verfahrensdokumentation"** dahil sertifikalandığını belirtir — yani vendor'un resmi süreç/sistem dokümantasyonu en az 2003'ten beri vardır ve talep edilebilir. FICO TONBELLER Academy'nin 5 günlük "Siron AML Basic Training"i "Architecture and technical requirements, Business rules, Case management, Risk ranking, Administration, Technical details and options" başlıklarını kapsar ([arşiv 2017](https://web.archive.org/web/20170210151929/http://www.tonbeller.com/en/services/academy/product-trainings)).

**4. Negatif sonuçlar artık GitHub'ı da kapsıyor.** GitHub kod aramasında büyük/küçük harfe duyarlı tam sözcük regex'iyle GWGKUNDE, GWGKONTO, GWGTRANS, GWATRHIT, GWGIND, GWGKAT, TBDOMVAL, TBDOMAIN, TBFELDZ, TBRLIST, KSLMAIN, SIBFORM, FARCUSTOMER, TBQFORMS, CKUNDE, CVFAAUFF, PRESULT_ARCHIVE, TDIREPOS için sıfır sonuç çıktı; yalnızca yukarıdaki iki depo (KYCCUST, PRESULT, TBRLEINT, HISTBIS, RL_KUERZEL) Siron'a ait gerçek tanımlayıcı içeriyor. Bu, kamuya sızmış bir Siron DDL'i olmadığını güçlendirir; raporun geri kalanındaki tablo düzeyi okumalar hipotez olarak kalır.

## "Tablolar tablosu" sorusunun üç katmanlı yanıtı: açık web'de sıfır iz, vendor'da portal, veritabanında TB* adayları

Açık katmanda sonuç nettir. Tam tablo adlarıyla yapılan İngilizce, Almanca ve Türkçe aramaların hepsi ilgisiz sonuç döndürdü: `GWGKUNDE GWGKONTO GWGTRANS` yalnızca Almanca "GWG" kısaltmasının (Geringwertige Wirtschaftsgüter / Geldwäschegesetz) sözlük ve muhasebe sayfalarını, `TBDOMAIN TBDOMVAL` ise bakteri proteini "TonB" için RCSB sayfalarını getirdi ([Wikipedia GWG](https://en.wikipedia.org/wiki/GWG); [RCSB 1QXX](https://www.rcsb.org/annotations/1QXX)). GWATRHITANA, TBQWKFLTREE veya EMBDWHPE_DATA gibi başka hiçbir sözcükle çakışamayacak tanımlayıcılar bile sıfır sonuç verdi; bu, Siron DDL'sinin veya veri sözlüğünün indekslenmiş biçimde hiç yayımlanmadığını gösterir. Önemli bir sınırlama var: GitHub code search (API 403), grep.app, searchcode, Sourcegraph, Stack Overflow, Scribd, docplayer ve Wayback Machine bu ortamın çıkış vekil sunucusu tarafından engellendi; dolayısıyla "bulunamadı" ifadesi "genel web indeksinde ve erişilebilen sayfalarda bulunamadı" anlamına gelir, "GitHub/Scribd/Wayback'te yokluğu doğrulandı" anlamına gelmez.

Vendor katmanında belge seti vardır ama kilitlidir. IMTF'nin destek sayfası Global Support Center (imtf.atlassian.net/servicedesk), müşteri portalı (imtf.atlassian.net/servicedesk/customer/portals), vaka açılamadığında support@imtf.com adresini ve ülke bazlı hatları verir; aynı sayfa **"Product documentation is available through the support portal"** der ([IMTF Customer Support](https://imtf.com/customer-support/)). Portal anonim erişimde yalnızca Atlassian özellik bayrağı metaverisi döndürür; belge kütüphanesi ve talep tipleri müşteri hesabı olmadan görünmez ([IMTF Customer Portal](https://imtf.atlassian.net/servicedesk/customer/portals)). imtf.com gezinmesinde herkese açık dokümantasyon, bilgi tabanı veya API portalı bağlantısı yoktur; Downloads sayfası yalnızca pazarlama materyali (Factsheet Alert and Case Manager, Factsheet Sanctions Screening, Siron®One broşürü, beyaz kitaplar) içerir ([IMTF Downloads](https://imtf.com/insights/download/)). FICO'nun eski ürün sayfası ise Siron'un IMTF'ye devredildiğini belirtip kullanıcıyı IMTF'ye yönlendirir; FICO Community ve devcloud artık bir kanal değildir ([FICO devcloud Siron](https://devcloud.fico.com/en/products/siron-anti-financial-crime-solutions)). 2003 tarihli İsviçre incelemesi SironAML için Almanca ve İngilizce indirilebilir belgeler bağlamıştı, ancak bunlar 2003 dönemine ait bağlantılardır ve getirilemedi ([Moneycab 2003](https://www.moneycab.com/news/umfassend-guenstig-und-schnell-eingefuehrt-die-sironaml-suite-von-imtf-3/amp/)).

Veritabanı katmanında asıl soru, Siron'un kendi tanımlarını Oracle kataloğuna mı yoksa kendi tablolarına mı yazdığıdır. Kanıtlar ikincisini işaret eder. Siron, Ton Beller'in 1987'den beri pazarladığı tescilli bir 4GL'dir ("das 4GL-Produkt 'Siron' von Ton Beller", [Computerwoche 1987](https://www.computerwoche.de/article/2812173/adv-orga-buhlt-um-potente-hardware-partner.html)); FICO dönemi ürün profili programlama dili ve API olarak hâlâ **"JAVA, C++ and Siron®4GL"** yazar ve veritabanı olarak MS SQL Server, Oracle, DB2'yi listeler ([financialit.net](https://financialit.net/products/security-compliance/ficorsironr-anti-financial-crime-solutions)); 2003'te de SironAML "DB2, Oracle, SQL-Server und weitere" üzerinde çalışıyordu ([Moneycab 2003](https://www.moneycab.com/news/umfassend-guenstig-und-schnell-eingefuehrt-die-sironaml-suite-von-imtf-3/)). Üç DBMS'de aynı uygulamayı çalıştıran bir 4GL, DDL'yi tipik olarak kendi taşınabilir sözlüğünden üretir ve `COMMENT ON TABLE` gibi DBMS'e özgü özelliklere dayanmaz; bu yüzden `ALL_TAB_COMMENTS`'in boş çıkması **beklenmelidir** (kanıt değil, çıkarım). Klasik SIRON'un zaten dosya/kayıt/alan tanımlarını kendi "Kataloge"sinde tuttuğu 1997 tarihli bir diploma tezinden biliniyor: tezin anahtar kelime bulutu "FELD NAME FELD-ADR", "Segmentlaenge", "Satzadresse", "Schlüsselfeld", "SIRON-Dokumentation" gibi kayıt yerleşimi terimleri içerir ve özet "zentralen Zugriffsverwaltung (verteilte Zugriffe, Kataloge, Anwendungen/Abfragen)" der ([Google Books, Wildensee 1997](https://books.google.de/books/about/Entwicklung_eines_Leitfadens_zur_systema.html?hl=de&id=udt-AQAAQBAJ); [diplom.de](https://m.diplom.de/document/216193)). Bu gelenek sürdüyse, modern Siron'un tablo/alan/domain tanımları veritabanında yaşayan platform tablolarında durur ve en doğal aday **TB*** ailesidir.

Ad temelli okuma şu adayları öne çıkarır (hepsi tahmin düzeyinde): **TBDEF** (Definition), **TBBO** (Business Object), **TBFELDZ** (Feldzuordnung = alan atama/eşleme), **TBINFO** (açıklama metinleri), **TBDOMAIN/TBDOMVAL/TBDOMHST** (Domäne = kod listesi, değerleri ve tarihçesi), **TBMUSS** (Mussfelder = zorunlu alanlar), **TBLNG** ve **TBRESSOURCE** (dil ve arayüz metin kaynakları; IMTF ürünlerinin "40 dil" desteği buna ihtiyaç duyar, [IMTF About](https://imtf.com/about-us/)), AML modülü içinde **GWGFELD/GWGFTEXT** (Feld/Feldtext = alan tanımı ve etiketi), içe aktarım tarafında **TDIREPOS** (muhtemelen "Repository"; TDI açılımı bulunamadı). Doğrulama üç adımla yapılır ve bir öğle arasına sığar: önce kataloğun boş olup olmadığına bakılır, sonra adayların sütun yapısı incelenir, sonra adaylar başka tabloların adını veri olarak içeriyor mu diye taranır.

```sql
-- 1) Oracle kataloğunda vendor yorumu var mı? (SIRON yerine gerçek şema sahibini yazın)
SELECT SUM(CASE WHEN comments IS NOT NULL THEN 1 ELSE 0 END) AS yorumlu_tablo, COUNT(*) AS toplam_tablo
FROM   all_tab_comments WHERE owner = 'SIRON' AND table_type = 'TABLE';
SELECT SUM(CASE WHEN comments IS NOT NULL THEN 1 ELSE 0 END) AS yorumlu_sutun, COUNT(*) AS toplam_sutun
FROM   all_col_comments WHERE owner = 'SIRON';

-- 2) Uygulama seviyesi sözlük adaylarının sütunları ve satır sayıları
SELECT c.table_name, c.column_id, c.column_name, c.data_type, c.data_length, t.num_rows
FROM   all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name
WHERE  c.owner = 'SIRON'
  AND  c.table_name IN ('TBDEF','TBBO','TBFELDZ','TBINFO','TBDOMAIN','TBDOMVAL','TBDOMHST','TBMUSS',
                        'TBLNG','TBRESSOURCE','TBAPPCONFIG','TBPARA','GWGFELD','GWGFTEXT','GWGPARA','TDIREPOS')
ORDER  BY c.table_name, c.column_id;

-- 3) Hangi tablo başka tabloların ADINI veri olarak saklıyor? (küçük tabloların tüm metin sütunlarını tarar;
--    genel Oracle pratiği, dokümandan alınmış hazır sorgu değil; büyük işlem tablolarını atlar)
SET SERVEROUTPUT ON SIZE UNLIMITED
DECLARE
  v_cnt NUMBER;
BEGIN
  FOR c IN (SELECT c.table_name, c.column_name
            FROM   all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name
            WHERE  c.owner = 'SIRON'
              AND  c.data_type IN ('VARCHAR2','CHAR','NVARCHAR2')
              AND  c.data_length >= 6
              AND  NVL(t.num_rows, 1) < 200000
            ORDER  BY c.table_name, c.column_id)
  LOOP
    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM SIRON."' || c.table_name || '" WHERE UPPER("' || c.column_name ||
                      '") IN (''GWGKUNDE'',''GWGKONTO'',''GWGTRANS'',''CKUNDE'',''GWATRHIT'',''KSLMAIN'')' INTO v_cnt;
    IF v_cnt > 0 THEN
      DBMS_OUTPUT.PUT_LINE(c.table_name || '.' || c.column_name || ' -> ' || v_cnt || ' satir tablo adi iceriyor');
    END IF;
  END LOOP;
END;
/
-- Pozitif çıkan tabloyu örnekleyin:  SELECT * FROM SIRON.<aday> WHERE ROWNUM <= 50;
```

Sorgu 3 bir veya daha fazla TB* tablosunda pozitif sonuç verirse, o tablo uygulamanın kendi veri sözlüğüdür ve `ALL_TAB_COLUMNS` ile anahtar üzerinden birleştirilip her sütuna etiket üretilebilir (yöntem 5. bölümde). Hiçbir tablo pozitif çıkmazsa Siron'un tanımları Java tarafında (ör. ORM eşlemeleri, XML/properties kaynakları) veya 4GL kaynak dosyalarında duruyordur ve veri sözlüğü yalnızca katalog arkeolojisi ve çalışma zamanı yakalamasıyla yeniden kurulabilir. Her iki durumda da IMTF'den resmi belgeyi istemek paralel yürütülmelidir, çünkü Siron "özelleştirilmez, konfigüre edilir" ("FICO does not recommend customization. Siron is configured instead", [2017 APAC Vendor Landscape](https://www.temenos.com/wp-content/uploads/2020/06/2017-APAC-Vendor-Landscape-AML-Solutions.pdf)) ve bu yüzden bankanın ~400 tablosu vendor'un standart şemasına çok yakın olmalıdır: generic bir "Datenbankbeschreibung" bankanın şemasını büyük oranda bire bir karşılar.

## Önekler modül düzeyinde okunabiliyor, tablo düzeyinde hâlâ hipotez

Önek çözümlemesinin dayanağı ürün soy ağacıdır; tablo adları değil. Ürün 2003'e kadar literal olarak Alman Kara Para Aklama Yasası'nın adını taşıyordu: İsviçre basını "Aus Siron GwG wird die Siron AML Suite" başlığıyla "Siron GwG wird neu als Siron AML (Anti Money Laundering) Suite angeboten" yazdı ([Moneycab, 6 Kasım 2003](https://www.moneycab.com/?p=1318207)). Aynı dönemde SironAML "Kernkomponente zur Überwachung der Kunden, Konten und Transaktionen" (müşteri, hesap, işlem izleme çekirdeği), SironProfile "Bildung von Kundenkategorien" (müşteri kategorileri), SironEmbargo "Überwachung des Zahlungsverkehrs (SWIFT), Transaktions-Stop" ve SironEmbargo/N "Online Namensüberprüfung" olarak tanımlanıyordu ([Moneycab, 26 Ağustos 2003](https://www.moneycab.com/?p=1318377)). SironKYC Şubat 2011'de "easy to create and flexible questionnaires for customer acceptance", "automated matching with PEP and embargo lists" ve "specific instructions for account managers" özellikleriyle eklendi ([PR Newswire 2011](https://www.prnewswire.co.uk/news-releases/tonbeller-ag-extends-solution-portfolio-with-siron-know-your-customer-to-fight-financial-crime-and-the-financing-of-terrorism-156143775.html)). FICO devrinde (satın alma 13 Ocak 2015, nakit 59,64 milyon USD, [SEC EDGAR](https://www.sec.gov/Archives/edgar/data/814547/000081454715000010/R30.htm)) modül seti RAS (Business Risk Assessment), KYC, AML, Embargo, **TCR (Tax Compliance and Reporting: AEOI, FATCA, CRS)**, Alert and Case Management ve RCC (Risk and Compliance Cockpit) olarak sabitlendi ([FICO devcloud](https://devcloud.fico.com/en/products/siron-anti-financial-crime-solutions)); FICO 15 Kasım 2022'de "AML, KYC, EMBARGO and TCR with associated case management and reporting" setini IMTF'ye devretti ([Business Wire](https://www.businesswire.com/news/home/20221115005365/en/FICO-Transitions-Siron-Compliance-Solutions-to-Partner-IMTF)) ve işlem 1 Aralık 2022'de kapandı ([BIIA](https://www.biia.com/swiss-imtf-group-becomes-a-global-leader-in-banking-compliance-solutions/)). Belgazprombank örneği Embargo ve KYC'nin "one database" ve aynı listeleri paylaştığını gösterir ([PR Newswire 2018](https://www.prnewswire.co.uk/news-releases/belgazprombank-fights-financial-crime-with-fico-tonbeller-sanctions-screening-694882821.html)); CTBC Bank kurulumu "AML, KYC, ACM, eRCC, Embargo" modüllerini "Java-based stack with Oracle and SQL databases" üzerinde çalıştırır ([AppsRunTheWorld](https://www.appsruntheworld.com/customers-database/products/view/fico-siron)).

Şemanın kendisi de tarih anlatır. Almanca kısaltmalı 8 karakterlik adlar (GWG*, GWA*, C*, K*, TB*, MM*, GB_/RB_) 1990'lar-2000'ler DB2/Oracle çağının adlandırma sınırlarını taşır; karışık adlar (TBQ*, SL_*, E*, P*) 2008-2013 modüllerine, tamamen İngilizce uzun adlar (FAR*, CACM*, CASE*, WORKFLOW*, PROCESSSTEP*, NOINDICIACUSTOMER, USERAUTH) ise KYC (2011), FATCA/TCR (2013-2016) ve ACM (~2018) katmanlarına denk düşer. Bu katmanlaşma, C*/GWG*/GWA* üçlüsünün en eski AML çekirdeği olduğu okumasını destekler. Aşağıdaki tabloda güven dereceleri şöyle tanımlanır: **doğrulanmış** = tablo adının kendisi kamuya açık bir kaynakta görülmüş (bu araştırmada hiçbir satır bu düzeye ulaşmadı); **olası** = Almanca/İngilizce açılım tutarlı ve modül bağlamı kaynaklı bir ürün tanımına oturuyor; **tahmin** = yalnızca makul açılım; **çözülmemiş** = savunulabilir okuma yok.

| Önek / aile | Olası modül | Açılım ve anlam | Güven |
|---|---|---|---|
| **GWG\*** (GWGKUNDE, GWGKONTO, GWGTRANS, GWGLAND, GWGWAE, GWGPARA, GWGBENUT, GWGROLLE, GWGIND, GWGINKL/GWGEXKL, GWGSCORS, GWGKAT, GWGFELD, GWGSETUP, GWGGENKEY) | Siron AML (eski adı Siron GwG): konfigürasyon, ana veri ve kural katmanı | GwG = Geldwäschegesetz. Kunde = müşteri, Konto = hesap, Transaktion = işlem, Land = ülke, Währung = para birimi, Parameter, Benutzer = kullanıcı, Rolle = rol, Indiz = gösterge (AML tespit kuralı; Almanca AML jargonunda "Indizien und Schwellenwerte"), Inklusion/Exklusion = izlemeye dahil/hariç listeleri, Scores = puanlama, Kategorie = müşteri kategorisi (SironProfile mirası), Feld = alan, generated key | Modül: **olası**. Tekil tablolar: olası (KUNDE/KONTO/TRANS/LAND/WAE/PARA/BENUT/ROLLE/IND/INKL/EXKL/KAT/FELD/GENKEY); GWGNCCT = FATF "Non-Cooperative Countries and Territories" **olası**; GWGMRISK, GWGCCKU, GWGGL*, GWGBUTAA, GWGKUSY, GWGPRCKU **çözülmemiş** |
| **GWA\*** (GWAKUNDE, GWASCORE, GWAVSCOR, GWATRHIT, GWATRHITANA, GWAZEIT, GWAREPP, GWAEVKTH/GWAEVKDH, GWALGHIT, GWARCSV) | Siron AML: analiz/sonuç katmanı | "A" = Analyse/Auswertung (**tahmin**). TRHIT = Transaktions-Treffer (işlem isabeti/alarm; "Treffer" bir Siron müşterisinin kullandığı terim), ANA = analiz, ZEIT = dönem, SCORE = hesaplanan puan, EV…H = olay isabeti / tarihçe, RCSV = CSV rapor | Modül: **olası**; "A"nın açılımı **tahmin** |
| **C\*** (CKUNDE, CKONTO, CTRANS, CADDR, CRELAT/CRELART, CAUSWEIS/CAUSWART, CCITIZ, CBLZ, CRECHTF, CBERUFTYP, CVORFALL, CVORTAT, CVFA*, CANZEIGE/CANZKUND/CANZKONT/CANZTRAN, CBRIEF/CSBRIEF, CTXTBAU, CDRKFORM) | AML çekirdeğinin ortak ana veri + şüpheli vaka (SAR) katmanı; **Siron KYC değil** | Ausweis = kimlik belgesi, Rechtsform = hukuki şekil, Berufstyp = meslek tipi, BLZ = banka kodu, Vorfall = vaka/olay, Vortat = öncül suç, VFA = Verdachtsfall (şüpheli vaka), Anzeige = (şüpheli işlem) bildirimi, Brief/Serienbrief = mektup, Textbaustein = metin şablonu, Druckformular = baskı formu. "C"nin açılımı (Common/Core/Compliance) bilinmiyor | Modül: **olası**; "C"nin anlamı ve C*↔GWG* katmanlaması (hangisi staging, hangisi çalışma tablosu) **tahmin** |
| **SL_\*** (SL_MAIN, SL_NAMES, SL_ADDR, SL_BIRTH, SL_PASS, SL_CITIZ, SL_RELATIONS, SL_LISTINFO, SL_WLDATE) | Ortak yaptırım/izleme listesi deposu (Embargo/KYC/PEP) | SL = Sanctions/Screening List; WLDATE = watch-list sürüm tarihi. Embargo ve KYC'nin aynı listeleri paylaştığı belgeli | **Olası** |
| **K\* / KSL\*** (KSLMAIN…KSLRELATIONS, KSYNONYM/KSYNONYMHIT, KRESULT, KHITTYPE, KHANDANW, KCKPROT, KYCCUST) | Siron KYC: müşteri adı taraması ve risk sınıflandırma | KSL = KYC'nin liste kopyası, Synonym = ad varyantı, Handlungsanweisung = işlem talimatı (2011 bülteninde "instructions for account managers"), Check-Protokoll = kontrol günlüğü | Modül: **olası**; KHANDANW **olası**, diğer açılımlar **tahmin** |
| **E\* / EMB\*** (EMBINST, EMBLOCK, EDECTAB, EWLDATE, EPAYSYSR, EMBDWHPE_DATA, ESW, EPRPE/EBRPE) | Siron Embargo (SWIFT/SEPA ödeme taraması) | DECTAB = karar tablosu, WLDATE = liste tarihi, PAYSYSR = ödeme sistemi kuralı, SW = stop words (Embargo'nun "stop-word lists" özelliği belgeli) | Modül: **olası**; EMBDWHPE_DATA, EPRPE, EBRPE **çözülmemiş** |
| **P\*** (PEPPARAM, PHIT, PRESULT, PRESULT_ARCHIVE, PRESULT1706, PSLSET, PSLW, PDOC, PFLD, PERSSTAT) | KYC skorlama/profil sonuç katmanı + PEP/ad tarama (KYC ve Embargo/N'nin paylaştığı); bağımsız "Siron PEP" ürünü doğrulanamadı | **PRESULT = müşteri başına KYC risk sonucu (INSTITUTSNR, KUNDNR, HISTBIS, ERFASSER, RISIKO) — GitHub'daki gerçek SQL ile doğrulandı** ("Ek tarama"). PHIT = isabet, PSL = screening list set, PERSSTAT = kişi durumu. **PRESULT1706** = büyük olasılıkla 1706 (Haziran 2017) sürüm geçişinde alınan yedek; financialit.net "Version 1606 / July 2016" YYMM kalıbını doğrular | PRESULT: **doğrulanmış**; diğerleri **olası**; PRESULT1706 yorumu **olası** |
| **TB\*** (TBLOGIN/TBLOGINH, TBPARA, TBLNG, TBDOMAIN/TBDOMVAL/TBDOMHST, TBMUSS, TBDEF, TBBO, TBFELDZ, TBINFO, TBREPORT, TBRLIST/TBRLEINT, TBFILIAL, TBAUDIT, TBPATCH, TBAPPCONFIG, TBDATRECHT, TBSYNC, TBRESSOURCE, TBRIKLAS) | Tonbeller platform/çerçeve tabloları (tüm modüllerin ortak altyapısı) | TB = TonBeller (**tahmin**, şirket adıyla güçlü örtüşme). Domäne = kod listesi, Muss = zorunlu alan, Filiale = şube, Datenrecht = veri erişim yetkisi (ACM'nin "data-level security" iddiasıyla uyumlu), Patch = uygulanan yama geçmişi, Risikoklasse = risk sınıfı, Ressource = arayüz metinleri | Modül: **tahmin/olası**; **veri sözlüğü taşıyıcısı olma iddiası yalnızca hipotez** |
| **TBQ\*** (TBQFORMS, TBQQUEST, TBQANSW/TBQANSWH, TBQBO, TBQREF, TBQWKFLTREE, TBQBUTTONS) | KYC anket (questionnaire) çerçevesi | Q = Questionnaire; forms/questions/answers/business objects/workflow tree. 2011 "flexible questionnaires" ve 2016 "dynamic questionnaires" ifadeleriyle uyumlu | **Olası** |
| **FAR\* / TAX\*** (FARCUSTOMER, FARACCOUNT, FARPAYMENT, FARREPORT*, FARTEMPLATE, FARTRANSPORT, FARCLASSIFICATION, FARCOUNTRY, TAXACTCASE, NOINDICIACUSTOMER) | Siron TCR (FATCA/CRS/AEOI vergi raporlaması) | FAR = büyük olasılıkla "FATCA (Account) Reporting" (**tahmin**, açılım bulunamadı). "Indicia" FATCA jargonu; TCR'nin "classifies customer and account data by CRS/FATCA relevance" tanımıyla örtüşür | Modül: **olası**; FAR açılımı **tahmin** |
| **CACM\* / CASE\* / WORKFLOW\* / PROCESSSTEP\* / ACTIVITYENTRY / USERAUTH / USRSTTNG** | Siron ACM (Alert & Case Manager) | İngilizce adlar ACM'nin "configurable workflows", "n-level approval", "audit trail of user actions" özellikleriyle uyumlu | **Olası** |
| **SIBFORM / LOCKEDSIBFORMS** | ACM içinde yerel uyarlama? | "SIB" = Şüpheli İşlem Bildirimi (MASAK ŞİB formu) okuması Türk kurulumu için çok çekici, ama hiçbir kaynak desteklemiyor; alternatif açılımlar (Siron Investigation Base vb.) de kanıtsız | **Tahmin / çözülmemiş** |
| **GB_\* / RB_\*** (GB_STM, GB_IND, GB_KAT, GB_ASUM, GB_AIND; RB_INM, RB_STM, RB_BWZ, RB_SP_*) | Siron RAS (Gefährdungsanalyse = kurum risk analizi) ve/veya RCC | GB = Gefährdungsbeurteilung/-analyse?, RB = Risikobewertung?; STM = Stamm (ana veri), IND = Indikator, KAT = Kategorie, BWZ = Bewertungszahl?, A* = aggregat. Alternatif: GB = Geschäftsbereich, RB = Risikobereich (risk matrisi eksenleri) | **Tahmin** |
| **TDI\*** (TDIREPOS, TDIPKGEN, TDILOCK) | **Siron®TDI** = Tonbeller'in web tabanlı OLAP/raporlama ön yüzü (tonbeller.com arşivi, "Ek tarama") | REPOS = TDI'nin rapor/navigatör deposu (veri ambarı yapı tanımlarını otomatik güncelleyen navigatör → tablo/alan metaverisi içerebilir), PKGEN = paket üretici, LOCK = çalıştırma kilidi | Modül: **doğrulanmış**; tablo anlamları **olası** |
| **MM\*** (MMNACHR, MMNACHRZ) | Belirsiz | Nachricht = mesaj (**olası**); "MM" = Marktmissbrauch (piyasa suistimali modülü) mü, Message Manager mı bilinmiyor | **Çözülmemiş** |
| **WS\*** (WSSTATUS, WSLOCK) | Web servis durum/kilit? | **Tahmin** | **Tahmin** |

Üç nokta pratik olarak önemlidir. Birincisi, KYC'ye ait sanılabilecek C* ailesi aslında Almanca SAR işleme sözlüğü taşır (Vorfall, Vortat, Anzeige, Brief, Textbaustein); KYC'ye özgü kavramlar (anket, risk sınıfı) TBQ*/K*/TBRIKLAS'ta durur. İkincisi, "Siron PEP" adlı ayrı bir ürün hiçbir kaynakta geçmez; PEP taraması SironKYC/SironEmbargo/N'nin bir işlevi olarak belgelenmiştir, dolayısıyla P* tabloları paylaşılan ad tarama motoruna aittir. Üçüncüsü, FICO 2021 civarında "Siron® Anti-Financial Crime Solutions Release 19" pazarlıyordu ([BrightTALK](https://www.brighttalk.com/webcast/15921/509203)) ve Printec 2023'te "Version 22"den söz eder ([Printec](https://www.printecgroup.com/?p=944)); 1606/1706 biçimindeki dört haneli etiket yalnızca financialit.net profilinde görülür, bu nedenle PRESULT1706 = Haziran 2017 eşlemesi tutarlı ama tek kaynaklıdır. TBPATCH tablosu (yama geçmişi ise) bankanın gerçek sürüm tarihçesini kesin olarak verir ve bu okumayı doğrulamanın en ucuz yoludur.

## Resmi veri sözlüğü için üç kapı: IMTF portalı, Bensheim ekibi ve Türkiye ortağı

Birinci ve tek resmi kapı IMTF'nin müşteri portalıdır. Destek sayfası aktif bakım sözleşmesi olan müşterilere 7/24 destek sunar, "All severity 1 and severity 2 issues ... must be submitted by telephone" der ve ülke bazlı hatları listeler: İsviçre +41 43 883 93 40, **Almanya +49 6251 8262697**, ABD +1 213 886 8382, İngiltere +44 20 3059 1564, Singapur +65 6967 6360, Avustralya +612 85226 5286 ([IMTF Customer Support](https://imtf.com/customer-support/)). Portala bankanın adlandırılmış Siron destek kişisi giriş yapar; bankanın henüz hesabı yoksa support@imtf.com ve Bensheim hattı başlangıç noktasıdır. Siron şemasını yazan mühendislik ekibi Bensheim'da oturur: IMTF, Fair Isaac Germany GmbH'yi (eski Tonbeller AG) satın aldı ve bu birim "the new IMTF entity in Germany" oldu ([IMTF news](https://imtf.com/news/imtf-completes-the-acquisition-of-the-siron-compliance-aml-business-from-fico/)); IMTF iletişim sayfası **IMTF Siron GmbH, Stubenwald-Allee 19, 64625 Bensheim, +49 6251 8262790** adresini verir ve Türkiye ofisi yoktur ([IMTF Contact](https://imtf.com/about-us/contact/)). Veri modeli sorusunun Almanca destek hattına yönlendirilmesi, doğru kişilere ulaşma olasılığını en yüksek tutar.

Talebin dili önemlidir çünkü manuel başlıkları kamuya açık hiçbir yerde doğrulanamadı; "Administration Guide", "Technical Documentation", "Interface Description", "Schnittstellenbeschreibung", "Datenmodell", "Datenbankbeschreibung", "Benutzerhandbuch", "Installationshandbuch", "Release Notes" aramaları hiçbir Siron belgesi döndürmedi. Bu yüzden talep başlık tahmin etmek yerine içerik tanımlamalıdır: kurulu sürüm için (TBPATCH veya GWGDB'den okunacak sürüm numarasıyla) **veri modeli / tablo ve sütun açıklamaları (Datenbankbeschreibung), içe aktarım arayüz tanımı (Schnittstellenbeschreibung: Kunde/Konto/Transaktion/Relation/Adresse kayıt yerleşimleri), kurulum ve yönetim kılavuzları, sürüm notları** ve varsa Siron GUI'den ekran-alan-sütun tanımı dışa aktarma yolu. msg Rethink Compliance'ın servis kataloğu bu artefaktların müşteri bazında teslim edildiğini doğrular: "Definition von Migrationspaketen mit vordefinierten Mapping- und Übergangsskripts" ve "Erweiterungen der Schnittstelle" ([msg Servicekatalog Siron](https://info.msg-compliance.com/hubfs/pdf/msg-rethink-compliance_Servicekatalog-Siron.pdf?hsLang=de)).

İkinci kapı eğitimdir. IMTF Campus (campus.imtf.com) ücretsiz "Basic" katmanda geçmiş webinar kayıtlarını, ücretli yıllık abonelikte ise "Siron One courses, both functional and technical" ile "downloadable documents" ve sınav sonrası kişisel sertifika sunar; fiyat için hesap yöneticisine yönlendirir ([IMTF Campus plans](https://campus.imtf.com/additional-info)). Ücretsiz katmandaki CRS/FATCA webinarı TAX*/FAR* tablolarının iş anlamını kavramak için doğrudan yararlıdır; kurs kataloğunda "Administration/Database" dersi olup olmadığı girişsiz görülemedi. Tonbeller döneminde partner danışmanlara SironAML/SironKYC/SironEmbargo sertifikaları verildiği bir Net.Bit mimarının profilinden biliniyor ([LinkedIn, Veninov](https://mk.linkedin.com/in/veninov)); bu, veri modeli içeren lisanslı eğitim materyalinin partner tarafında da bulunduğunu gösterir. Yıllık Siron® User Group Conference (2026: 24-25 Eylül, Renaissance Zurich Tower Hotel, kayıt lp.imtf.com, geç talepler marketing@imtf.com) bankanın uyum BT yöneticisi için eş müşterilerden şema bilgisi edinme kanalıdır; bildiriler yayımlanmaz ([IMTF event page](https://imtf.com/events/sironuser-group-2026/)).

Üçüncü kapı ortaklardır. IMTF'nin "Delivery and Implementation Partners" listesinde Türkiye için tek ad **Holicy Consulting**'dir; blurb "over 20 years of expertise in financial crime detection and prevention" der ([IMTF Partners](https://imtf.com/imtf-partners/)). Holicy'nin kendi sitesi (Esentepe Mah., Büyükdere Cad., FERKO Signature No. 175/2, Şişli; tüzel ad "Holicy Bilişim Teknolojileri Danışmanlık ve Ticaret Limited Şirketi"; hizmetler Business Consulting, Model Management, Technical Consulting, Training) IMTF veya Siron'u anmaz ve müşteri referansı listelemez ([Holicy Consulting](https://www.holicyconsulting.com/)); ilişki yalnızca IMTF sayfasıyla doğrulanır, rolü (satış, uygulama, destek) belirsizdir. Bölgesel kapsama Printec (Güney/Orta/Doğu Avrupa, 2026 Siron User Group'a katıldı), Confero Technologies (Baltık ve Rusya/Belarus hariç BDT) ve Net.Bit (Kuzey Makedonya) ile FICO döneminden msg (EMEA bayi, "managed services for Siron solutions", [FICO/msg 2021](https://devcloud.fico.com/en/newsroom/fico-and-msg-partner-help-european-african-and-middle-east-businesses-meet-changing)) tarafından sağlanır. Türk sistem entegratörlerinden hiçbiri (Cybersoft, Intertech, Fineksus, Veripark, Commencis) IMTF/FICO partner sayfalarında geçmez ve Siron'u anan hiçbir Türk banka bülteni, ihale veya iş ilanı bulunamadı; bankanın kendi tedarik/proje arşivi, ilk Tonbeller/FICO kurulumunu kimin yaptığını söyleyen tek kaynaktır ve o uygulayıcının proje teslimatları (eşleme tabloları, arayüz spesifikasyonu) muhtemelen bankanın içinde zaten vardır.

## Oracle kataloğu, paylaşılan havuz ve audit izi sözlüğün yüzde 60-80'ini kurar

Vendor belgesi gelmeden önce bile ~400 tablonun büyük kısmı sınıflandırılabilir, çünkü gereken her şey `ALL_`/`DBA_` statik görünümlerinde ve `DBMS_METADATA`'da durur: `ALL_TAB_COMMENTS` ve `ALL_COL_COMMENTS` (OWNER, TABLE_NAME, COMMENTS VARCHAR2(4000)), `ALL_TAB_COLUMNS` (DATA_TYPE, NULLABLE, NUM_DISTINCT, NUM_NULLS, LAST_ANALYZED), `ALL_CONSTRAINTS` + `ALL_CONS_COLUMNS` (CONSTRAINT_TYPE P/U/R/C, R_CONSTRAINT_NAME, SEARCH_CONDITION_VC), `ALL_TABLES`/`ALL_TAB_STATISTICS` (NUM_ROWS yalnızca DBMS_STATS ile dolar), `ALL_TAB_MODIFICATIONS` (son istatistikten bu yana INSERTS/UPDATES/DELETES ve TIMESTAMP), `ALL_VIEWS`, `ALL_DEPENDENCIES`, `ALL_SOURCE`, `ALL_TRIGGERS`, `ALL_OBJECTS` (CREATED, LAST_DDL_TIME) ([Oracle 19c Reference: ALL_TAB_COMMENTS](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_TAB_COMMENTS.html); [ALL_CONSTRAINTS](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_CONSTRAINTS.html); [ALL_TAB_MODIFICATIONS](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_TAB_MODIFICATIONS.html); [ALL_DEPENDENCIES](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_DEPENDENCIES.html)). Aşağıdaki SQL bu referans tanımlarından yazıldı; bu ortamda Oracle örneği olmadığı için "referans okunarak sentaks kontrol edildi", "çalıştırılıp test edildi" değil. `SIRON` yerine gerçek şema sahibini yazın, `SELECT_CATALOG_ROLE` ile veya şema sahibi olarak çalıştırın, DBA erişiminiz varsa `ALL_` yerine `DBA_` kullanın.

Mantık şudur: en çok FK ile referans alınan "hub" tablo müşteri/taraf tablosudur; PK'sı (tarih, sayaç) olan veya `ALL_TAB_MODIFICATIONS`'ta INSERTS ≫ UPDATES gösteren tablolar işlem/log/alarm tablolarıdır; az satırlı, CODE+TEXT çifti taşıyan ve çok referans alan tablolar kod listeleridir. Java/Hibernate çağı uygulamalarında FK'lar sıklıkla veritabanında tanımlanmaz; o zaman paylaşılan sütun adları (8. sorgu) ilişki çıkarımının yedek yoludur.

```sql
-- 0. Şemadaki nesne türleri
SELECT object_type, COUNT(*) cnt FROM all_objects WHERE owner = 'SIRON'
GROUP BY object_type ORDER BY cnt DESC;

-- 1. Önek ailesine göre tablo envanteri: yorum, istatistik, son DML, oluşturma/DDL zamanı
--    Önce (ANALYZE ANY veya DBA gerekir):  EXEC DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO;
SELECT t.table_name,
       REGEXP_SUBSTR(t.table_name, '^[A-Z]+_?')          AS prefix,
       tc.comments                                        AS table_comment,
       t.num_rows, t.last_analyzed, t.temporary, t.partitioned,
       m.inserts, m.updates, m.deletes, m.timestamp       AS last_dml_since_stats,
       o.created, o.last_ddl_time
FROM   all_tables t
LEFT   JOIN all_tab_comments      tc ON tc.owner = t.owner AND tc.table_name = t.table_name
LEFT   JOIN all_tab_modifications m  ON m.table_owner = t.owner AND m.table_name = t.table_name
                                    AND m.partition_name IS NULL
LEFT   JOIN all_objects           o  ON o.owner = t.owner AND o.object_name = t.table_name
                                    AND o.object_type = 'TABLE'
WHERE  t.owner = 'SIRON'
ORDER  BY prefix, t.table_name;

-- 2. Önek başına tablo sayısı (GWG, GWA, C, SL_, KSL, EMB, TB, TBQ, FAR, TAX, CASE, ACM, GB_, RB_, TDI, MM, WS ...)
SELECT REGEXP_SUBSTR(table_name, '^[A-Z]+_?') AS prefix, COUNT(*) AS tables
FROM   all_tables WHERE owner = 'SIRON'
GROUP  BY REGEXP_SUBSTR(table_name, '^[A-Z]+_?') ORDER BY tables DESC;

-- 3. Tam sütun sözlüğü (sütun yorumlarıyla)
SELECT c.table_name, c.column_id, c.column_name, c.data_type,
       CASE WHEN c.data_type IN ('VARCHAR2','CHAR','NVARCHAR2','NCHAR','RAW') THEN c.data_length
            WHEN c.data_type = 'NUMBER' THEN c.data_precision END AS len_or_prec,
       c.data_scale, c.nullable, c.num_distinct, c.num_nulls, cc.comments AS column_comment
FROM   all_tab_columns c
LEFT   JOIN all_col_comments cc ON cc.owner = c.owner AND cc.table_name = c.table_name
                               AND cc.column_name = c.column_name
WHERE  c.owner = 'SIRON' ORDER BY c.table_name, c.column_id;

-- 4. Birincil / tekil anahtarlar (satırı ne tanımlıyor -> varlık tipi ipucu)
SELECT c.table_name, c.constraint_name, c.constraint_type,
       LISTAGG(cc.column_name, ', ') WITHIN GROUP (ORDER BY cc.position) AS key_columns
FROM   all_constraints c
JOIN   all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name
WHERE  c.owner = 'SIRON' AND c.constraint_type IN ('P','U')
GROUP  BY c.table_name, c.constraint_name, c.constraint_type ORDER BY c.table_name;

-- 5. FK grafı: çocuk tablo/sütunlar -> ebeveyn tablo/sütunlar
SELECT fk.table_name AS child_table,
       LISTAGG(fc.column_name, ', ') WITHIN GROUP (ORDER BY fc.position) AS child_cols,
       pk.table_name AS parent_table,
       LISTAGG(pc.column_name, ', ') WITHIN GROUP (ORDER BY pc.position) AS parent_cols,
       fk.constraint_name, fk.delete_rule, fk.status
FROM   all_constraints  fk
JOIN   all_constraints  pk ON pk.owner = fk.r_owner AND pk.constraint_name = fk.r_constraint_name
JOIN   all_cons_columns fc ON fc.owner = fk.owner AND fc.constraint_name = fk.constraint_name
JOIN   all_cons_columns pc ON pc.owner = pk.owner AND pc.constraint_name = pk.constraint_name
                          AND pc.position = fc.position
WHERE  fk.owner = 'SIRON' AND fk.constraint_type = 'R'
GROUP  BY fk.table_name, pk.table_name, fk.constraint_name, fk.delete_rule, fk.status
ORDER  BY parent_table, child_table;

-- 6. "Hub" tablolar = en çok referans alan ebeveynler (müşteri, hesap, vaka, kullanıcı, kod tabloları)
SELECT pk.table_name AS parent_table, COUNT(*) AS referencing_fks
FROM   all_constraints fk
JOIN   all_constraints pk ON pk.owner = fk.r_owner AND pk.constraint_name = fk.r_constraint_name
WHERE  fk.owner = 'SIRON' AND fk.constraint_type = 'R'
GROUP  BY pk.table_name ORDER BY referencing_fks DESC;

-- 7. Check kısıtları = izin verilen kod kümeleri (SEARCH_CONDITION_VC 12c+)
SELECT table_name, constraint_name, search_condition_vc
FROM   all_constraints
WHERE  owner = 'SIRON' AND constraint_type = 'C' AND generated = 'USER NAME' ORDER BY table_name;

-- 8. FK tanımlanmamışsa: paylaşılan sütun adlarından ilişki çıkarımı
SELECT a.table_name, a.column_name, COUNT(*) OVER (PARTITION BY a.column_name) AS tables_sharing_col
FROM   all_tab_columns a
WHERE  a.owner = 'SIRON'
  AND  a.column_name IN (SELECT column_name FROM all_tab_columns
                         WHERE owner = 'SIRON' GROUP BY column_name HAVING COUNT(*) > 1)
  AND  (a.column_name LIKE '%ID' OR a.column_name LIKE '%NR' OR a.column_name LIKE '%KEY%'
        OR a.column_name LIKE '%NO' OR a.column_name LIKE '%CODE')
ORDER  BY tables_sharing_col DESC, a.column_name, a.table_name;

-- 9. İndeksler (uygulama hangi sütunlardan arıyor)
SELECT i.table_name, i.index_name, i.uniqueness, i.status,
       LISTAGG(ic.column_name, ', ') WITHIN GROUP (ORDER BY ic.column_position) AS idx_cols
FROM   all_indexes i JOIN all_ind_columns ic ON ic.index_owner = i.owner AND ic.index_name = i.index_name
WHERE  i.table_owner = 'SIRON'
GROUP  BY i.table_name, i.index_name, i.uniqueness, i.status ORDER BY i.table_name;

-- 10. Görünümler ve okudukları tablolar (vendor'un kendi "iş görünümleri" en iyi anlam ipuçlarıdır)
SELECT view_name, text_length, text_vc FROM all_views WHERE owner = 'SIRON' ORDER BY view_name;
SELECT d.name AS view_name, d.referenced_name AS base_table
FROM   all_dependencies d
WHERE  d.owner = 'SIRON' AND d.type = 'VIEW' AND d.referenced_type IN ('TABLE','VIEW')
ORDER  BY d.name, d.referenced_name;

-- 11. Her tabloya dokunan PL/SQL birimleri ve tablolara YAZAN kaynak satırları
SELECT d.referenced_name AS table_name,
       LISTAGG(d.type || ':' || d.name, '; ') WITHIN GROUP (ORDER BY d.type, d.name) AS used_by
FROM   all_dependencies d
WHERE  d.referenced_owner = 'SIRON' AND d.referenced_type = 'TABLE'
  AND  d.type IN ('PACKAGE','PACKAGE BODY','PROCEDURE','FUNCTION','TRIGGER','TYPE BODY')
GROUP  BY d.referenced_name ORDER BY d.referenced_name;
SELECT s.type, s.name, s.line, TRIM(s.text) AS src
FROM   all_source s
WHERE  s.owner = 'SIRON'
  AND  REGEXP_LIKE(s.text, '(INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)\s+("?SIRON"?\.)?"?(GWG|GWA|C|TB)[A-Z0-9_]*', 'i')
ORDER  BY s.name, s.line;

-- 12. Tetikleyiciler (audit/tarihçe/denormalizasyon mantığı anlamı açık eder)
SELECT table_name, trigger_name, trigger_type, triggering_event, status, description
FROM   all_triggers WHERE table_owner = 'SIRON' ORDER BY table_name, trigger_name;

-- 13. Hangi DB hesabı hangi tabloda DML yetkisine sahip (modül şemaları, batch ve rapor kullanıcıları ayrışır)
SELECT grantee, table_name, LISTAGG(privilege, ',') WITHIN GROUP (ORDER BY privilege) AS privs
FROM   all_tab_privs WHERE table_schema = 'SIRON'
GROUP  BY grantee, table_name ORDER BY grantee, table_name;

-- 14. Kesin satır sayıları (mesai dışı; 400 tabloda tam tarama). Yaygın DBA deyimi, Oracle dokümanından değil.
SELECT t.table_name,
       TO_NUMBER(EXTRACTVALUE(XMLTYPE(DBMS_XMLGEN.GETXML(
         'SELECT COUNT(*) c FROM "' || t.owner || '"."' || t.table_name || '"')), '/ROWSET/ROW/C')) AS exact_rows
FROM   all_tables t WHERE t.owner = 'SIRON' ORDER BY exact_rows DESC;

-- 15. Tüm DDL dışa aktarımı (modelleme aracına beslemek veya başka ortamla diff almak için)
SET LONG 2000000 PAGESIZE 0 LINESIZE 32767 TRIMSPOOL ON
EXEC DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'STORAGE',false);
EXEC DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'SEGMENT_ATTRIBUTES',false);
SPOOL siron_schema_ddl.sql
SELECT DBMS_METADATA.GET_DDL('TABLE', table_name, owner) FROM all_tables WHERE owner = 'SIRON';
SELECT DBMS_METADATA.GET_DDL('REF_CONSTRAINT', constraint_name, owner) FROM all_constraints
WHERE  owner = 'SIRON' AND constraint_type = 'R';
SPOOL OFF

-- 16. Bulguları kataloğa geri yazın; her araç bunları gösterir (sahibi değilseniz COMMENT ANY TABLE gerekir)
COMMENT ON TABLE  SIRON.GWGKUNDE IS 'AML (GwG) müşteri ana tablosu – çıkarım: GWGKONTO''nun KUNDENNR üzerinden ebeveyni; PKG_IMPORT_KUNDE yazar';
COMMENT ON COLUMN SIRON.GWGKUNDE.KUNDENNR IS 'Müşteri numarası (PK); 14 tablodan FK hedefi';
```

`COMMENT ON` sözdizimi ve yetki kuralı Oracle SQL Reference'ta belgelidir: `COMMENT ON TABLE [schema.]table IS 'string'`, başka şemanın nesnesi için `COMMENT ANY TABLE` gerekir, boş dize yorumu siler ([Oracle SQL Reference: COMMENT](https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/COMMENT.html)). 16. adım, bir şema dökümünü veri sözlüğüne dönüştüren adımdır, çünkü SchemaSpy, SQL Developer ve Data Modeler hepsi katalog yorumlarını okur.

### Uygulamanın gerçekten çalıştırdığı SQL, bir tablonun en güvenilir tanımıdır

CTBC kaydının işaret ettiği gibi Siron Java tabanlı bir yığında çalışıyorsa DML'nin büyük kısmı JDBC'den gelir, `ALL_DEPENDENCIES` neredeyse boş kalır ve anlam kanıtı paylaşılan havuzdan alınmalıdır. `V$SQL` SQL_ID, SQL_FULLTEXT, MODULE/ACTION (DBMS_APPLICATION_INFO ile ayarlanır), PARSING_SCHEMA_NAME, EXECUTIONS ve LAST_ACTIVE_TIME taşır; `V$SQL_PLAN` ise her planın dokunduğu OBJECT_OWNER/OBJECT_NAME'i verir ([V$SQL](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/V-SQL.html); [V$SQL_PLAN](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/V-SQL_PLAN.html)). DBMS_APPLICATION_INFO çağırmayan bir JDBC uygulaması MODULE olarak "JDBC Thin Client" gösterir; o zaman servis veya oturum düzeyinde 10046 izi (DBMS_MONITOR, ek lisans gerekmez) ve bir GUI kullanıcısının her Siron ekranını (KYC müşteri görünümü, AML alarm listesi, Embargo isabet incelemesi, ACM vakası, TCR/FATCA anketi, PEP araması) sırayla açtığı senaryolu bir gezinti, her ekranı arkasındaki tablolara bire bir eşler ([DBMS_MONITOR](https://docs.oracle.com/en/database/oracle/oracle-database/19/arpls/DBMS_MONITOR.html)).

Lisans sınırı dikkat ister. Oracle lisans belgesi "All data dictionary views beginning with the prefix DBA_HIST_ are part of this pack" der ve yalnızca DBA_HIST_SNAPSHOT, DBA_HIST_DATABASE_INSTANCE, DBA_HIST_SNAP_ERROR, **DBA_HIST_SEG_STAT, DBA_HIST_SEG_STAT_OBJ** ve DBA_HIST_UNDOSTAT'ı istisna tutar; V$ACTIVE_SESSION_HISTORY da pakete dahildir ve "direct access to the underlying data" bile lisans gerektirir ([Oracle 19c Licensing Information](https://docs.oracle.com/en/database/oracle/oracle-database/19/dblic/Licensing-Information.html)). Dolayısıyla AWR sorguları (E) yalnızca Diagnostics Pack lisansı varsa çalıştırılmalı, lisanssız EE'de segment aktivite tarihçesi (F) kullanılmalıdır. Unified audit politikası ise yazma semantiğini (tam SQL metni ve bind değerleri) lisans gerektirmeden kayda alır ve sınıflandırılamayan tablolara daraltılarak bir iş günü + bir batch döngüsü boyunca açık tutulup kaldırılmalıdır ([CREATE AUDIT POLICY](https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/CREATE-AUDIT-POLICY-Unified-Auditing.html); [UNIFIED_AUDIT_TRAIL](https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/UNIFIED_AUDIT_TRAIL.html)).

```sql
-- A. Siron şemasına kim bağlanıyor, uygulama MODULE/ACTION etiketliyor mu? (kullanıcılar ve batch aktifken)
SELECT username, osuser, machine, program, module, action, client_identifier, service_name, COUNT(*) sessions
FROM   v$session WHERE username IS NOT NULL
GROUP  BY username, osuser, machine, program, module, action, client_identifier, service_name
ORDER  BY sessions DESC;

-- B. Paylaşılan havuzdan: her tabloya dokunan her ifade, hangi modülden geldiği, kaç kez çalıştığı
SELECT p.object_name AS table_name, s.module, s.action, s.parsing_schema_name,
       SUM(s.executions) AS execs, MAX(s.last_active_time) AS last_seen, COUNT(DISTINCT s.sql_id) AS distinct_sql
FROM   v$sql s JOIN v$sql_plan p ON p.sql_id = s.sql_id AND p.child_number = s.child_number
WHERE  p.object_owner = 'SIRON' AND p.object_type LIKE 'TABLE%'
GROUP  BY p.object_name, s.module, s.action, s.parsing_schema_name ORDER BY table_name, execs DESC;

-- C. Tek tablo için gerçek ifadeler (COMMAND_TYPE kodları: AUDIT_ACTIONS görünümünden doğrulayın)
SELECT DISTINCT p.object_name, s.command_type, s.module, s.sql_id, s.sql_fulltext
FROM   v$sql s JOIN v$sql_plan p ON p.sql_id = s.sql_id AND p.child_number = s.child_number
WHERE  p.object_owner = 'SIRON' AND p.object_name = 'GWGKUNDE' ORDER BY s.command_type;

-- D. Havuzdaki SQL'in PL/SQL kaynağı (PROGRAM_ID -> ALL_OBJECTS.OBJECT_ID; standart DBA pratiği)
SELECT o.object_type, o.object_name, s.program_line#, s.sql_text
FROM   v$sql s JOIN all_objects o ON o.object_id = s.program_id
WHERE  s.parsing_schema_name = 'SIRON' AND s.program_id > 0 ORDER BY o.object_name, s.program_line#;

-- E. AWR tarihçesi (Diagnostics Pack LİSANSI GEREKİR): haftalar boyunca tablo x modül kullanımı
SELECT hp.object_name, hs.module, hs.action, SUM(hs.executions_delta) execs, COUNT(DISTINCT hs.sql_id) stmts
FROM   dba_hist_sqlstat hs
JOIN   dba_hist_sql_plan hp ON hp.sql_id = hs.sql_id AND hp.plan_hash_value = hs.plan_hash_value AND hp.dbid = hs.dbid
WHERE  hp.object_owner = 'SIRON' AND hp.object_type LIKE 'TABLE%'
GROUP  BY hp.object_name, hs.module, hs.action ORDER BY hp.object_name, execs DESC;

-- F. Lisanssız segment aktivitesi (DBA_HIST_SEG_STAT ve _OBJ pakete dahil değil):
--    okuma ağırlıklı (referans/kod) ve yazma ağırlıklı (işlem/alarm/log) tabloları ayırır
SELECT o.object_name, o.object_type,
       SUM(s.logical_reads_delta) reads, SUM(s.db_block_changes_delta) block_changes,
       SUM(s.physical_writes_delta) phys_writes, SUM(s.table_scans_delta) full_scans
FROM   dba_hist_seg_stat s
JOIN   dba_hist_seg_stat_obj o ON o.dbid = s.dbid AND o.ts# = s.ts# AND o.obj# = s.obj# AND o.dataobj# = s.dataobj#
WHERE  o.owner = 'SIRON'
GROUP  BY o.object_name, o.object_type ORDER BY block_changes DESC;

-- G. Bir GUI kullanıcısının veya gece batch'inin 10046 izi (ek lisans yok; diag trace dizinine yazar)
EXEC DBMS_MONITOR.SESSION_TRACE_ENABLE(session_id => :sid, serial_num => :serial, waits => TRUE, binds => TRUE);
--    ... kullanıcı ekranları gezer / iş çalışır ...
EXEC DBMS_MONITOR.SESSION_TRACE_DISABLE(session_id => :sid, serial_num => :serial);
--    servis/modül bazında alternatif:
EXEC DBMS_MONITOR.SERV_MOD_ACT_TRACE_ENABLE(service_name => 'SIRONSVC', module_name => 'JDBC Thin Client', binds => TRUE);
EXEC DBMS_MONITOR.SERV_MOD_ACT_TRACE_DISABLE(service_name => 'SIRONSVC', module_name => 'JDBC Thin Client');
--    DB sunucusunda:  trcsess output=siron.trc service=SIRONSVC *.trc
--                     tkprof siron.trc siron.txt sort=exeela sys=no

-- H. Sınıflandırılamayan tablolara daraltılmış unified audit (tam SQL + bind kaydeder)
CREATE AUDIT POLICY siron_dd_pol
  ACTIONS ALL ON SIRON.GB_STM, ALL ON SIRON.RB_INM, ALL ON SIRON.TDIREPOS,
          ALL ON SIRON.MMNACHR, ALL ON SIRON.WSSTATUS, ALL ON SIRON.SIBFORM;
AUDIT POLICY siron_dd_pol BY siron_app, siron_batch;   -- A sorgusundaki uygulama hesapları
-- bir iş günü + bir batch döngüsü sonra:
SELECT object_name, action_name, dbusername, client_program_name,
       COUNT(*) events, MIN(event_timestamp) first_seen, MAX(event_timestamp) last_seen
FROM   unified_audit_trail WHERE unified_audit_policies LIKE '%SIRON_DD_POL%'
GROUP  BY object_name, action_name, dbusername, client_program_name ORDER BY object_name, action_name;
SELECT DISTINCT object_name, action_name, DBMS_LOB.SUBSTR(sql_text, 4000, 1) sql_text
FROM   unified_audit_trail WHERE unified_audit_policies LIKE '%SIRON_DD_POL%';
NOAUDIT POLICY siron_dd_pol BY siron_app, siron_batch;  DROP AUDIT POLICY siron_dd_pol;

-- I. Siron'un kendi etiket/kod listesi/sözlük tablolarını keşfet (adlar DOĞRULANMAMIŞ hipotezdir)
SELECT c.table_name, LISTAGG(c.column_name, ', ') WITHIN GROUP (ORDER BY c.column_id) cols, t.num_rows
FROM   all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name
WHERE  c.owner = 'SIRON'
  AND  REGEXP_LIKE(c.column_name, '(LANG|LNG|SPRACHE|TEXT|TXT|LABEL|DESCR|BESCHR|BEZ|CAPTION|TABNAME|TABLE_NAME|TABELLE|COLNAME|COLUMN|FELD|FIELD|ATTRIB|DOMAIN|DOMVAL|CODE)')
GROUP  BY c.table_name, t.num_rows HAVING COUNT(*) >= 2 ORDER BY t.num_rows DESC;
SELECT DISTINCT c.table_name, c.column_name FROM all_tab_columns c
WHERE  c.owner = 'SIRON' AND REGEXP_LIKE(c.column_name, '(TAB(LE|ELLE)?_?NAME|TABNAME|ENTITY|OBJEKT|OBJECT_NAME)');

-- J. KEY/VALUE ya da PARAM/WERT çiftli küçük konfigürasyon tabloları (modül sınırlarını gösterir)
SELECT c.table_name, t.num_rows FROM all_tab_columns c JOIN all_tables t ON t.owner=c.owner AND t.table_name=c.table_name
WHERE  c.owner='SIRON' AND REGEXP_LIKE(c.column_name,'(PARAM|PARA|KEY|SCHLUESSEL|WERT|VALUE|CONFIG|SETTING)')
GROUP  BY c.table_name, t.num_rows HAVING COUNT(*) >= 2 ORDER BY t.num_rows;
```

I sorgusu bir alan anahtarını etikete eşleyen tabloyu bulduğunda (ör. TBLNG veya TBRESSOURCE'ta `(dil, anahtar, metin)` yapısı), anahtar sütun adlarıyla örtüştüğü her yerde `ALL_TAB_COLUMNS`'a birleştirilir ve sonuç `COMMENT ON COLUMN` ile geri yazılır; 40 dilde yerelleşmiş, kullanıcı tanımlı kurallar, listeler, iş akışları ve anketler (TBQ*) taşıyan bir ürünün GUI etiketlerini ve kod listesi değerlerini `(language, key)` ile anahtarlanmış tablolarda tutması neredeyse kesindir, ancak bu tabloların adı ve yapısı hiçbir kamu kaynağında doğrulanmadı.

### Ücretsiz araçlar: SchemaSpy ve SQL Developer Data Modeler katalog yorumlarını ERD'ye çevirir

Önerilen boru hattı üç adımdır. Önce yukarıdaki SQL ile çıkarılan anlamlar `COMMENT ON TABLE/COLUMN` olarak kataloğa yazılır. Sonra SchemaSpy, FK ile gezilebilir ER diyagramlı tıklanabilir bir HTML site üretir: genel komut `java -jar schemaspy.jar -t dbType -dp <jdbc.jar> -db dbName -host server -port 1521 -s schema -u user -p password -o outputDir`; Oracle tipleri `ora` (OCI8 istemci gerekir) ve `orathin` (yalnızca ojdbc jar); 6.1.0 ve üstü `-vizjs` ile Graphviz'siz diyagram çizer ([SchemaSpy Getting Started](https://schemaspy.readthedocs.io/en/latest/started.html); [SchemaSpy Installation](https://schemaspy.readthedocs.io/en/latest/installation.html); [schemaspy.sourceforge.net](https://schemaspy.sourceforge.net/)). Michigan Üniversitesi'nin çalışan Oracle örneği şöyledir: `java -jar schemaspy-6.2.4.jar -dp "...\jdbc\lib\ojdbc10.jar" -t ora -desc "<açıklama>" -o "<çıktı>" -ahic -norows -lq -nologo -db <database> -s <schema> -cat <schema> -host <sunucu> -port 1521 -u <kullanıcı> -p "<şifre>"`; sürücüler `-dbhelp` ile doğrulanır ([UMich SchemaSpy KB](https://teamdynamix.umich.edu/TDClient/210/DepressionCenter/KB/Article/11889/How-to-use-SchemaSpy-to-document-research-datasets)). Bankanın ~400 tablosu için makul çağrı `-t orathin -dp ojdbc8.jar -s SIRON -u <salt_okunur> -pfp -o ./siron_dd -vizjs` biçimindedir; servis adıyla thin bağlantı dizgesi `-dbhelp` çıktısından kontrol edilmelidir çünkü getirilen SchemaSpy sayfaları Oracle servis adı örneği göstermiyor. FK'lar veritabanında tanımlı değilse diyagramlar bağlantısız kutular olarak çıkar; SchemaSpy metafile ile örtük ilişkiler ve yorumlar eklenebilir.

Üçüncü adım sürdürülebilir modeldir. Oracle SQL Developer'da bağlantıya sağ tıklayıp **Generate DB Doc** seçmek Javadoc benzeri HTML üretir ([SQL Developer 23.1 User's Guide](https://docs.oracle.com/en/database/oracle/sql-developer/23.1/rptug/sql-developer-concepts-usage.html)); SQL Developer Data Modeler'da **File → Import → Data Dictionary** sihirbazı (bağlantı → şema → nesneler → Finish) ilişkisel modeli kurar, birden fazla şema seçilirse her şema için alt görünüm oluşturur, **File → Reports** HTML rapor üretir ve "Comments in RDBMS" seçeneği katalog yorumlarını diyagramda gösterir ([Data Modeler 23.1 User's Guide](https://docs.oracle.com/en/database/oracle/sql-developer-data-modeler/23.1/dmdug/data-modeler-concepts-usage.html); [Oracle OBE: Data Modeler import](https://www.oracle.com/webfolder/technetwork/tutorials/obe/db/apex/r51/dm4.1/index.html)). Data Modeler'da her önek ailesi (GWG, GWA, C, TB, FAR, CASE…) için bir alt görünüm açmak ve veritabanına dokunmadan modelde FK eklemek, vendor belgesi geldiğinde diff almayı kolaylaştırır. DBeaver Community şema diyagramı çizip PNG/GIF/BMP/GraphML dışa aktarır ama dokümantasyon üretmez ([DBeaver ER Diagrams](https://dbeaver.com/docs/dbeaver/ER-Diagrams/)); DbSchema'nın HTML5/PDF dokümantasyon dışa aktarımı yalnızca Pro sürümündedir ([DbSchema blog](https://dbschema.com/blog/design/best-tools-for-database-documentation)); Toad for Oracle'ın Database → Report → "Html Schema Doc Generator" aracı ticaridir ([Dataedo: Toad](https://dataedo.com/kb/tools/toad-oracle/how-to-generate-database-documentation)).

## Yerel PARAM_*, MASAK_2_SIRON_FIELD_MAP ve BANK_2_MASAK_CODE vendor şeması değil, MASAK köprüsüdür

Bu tablolar Siron'un standart adlandırma kalıplarının (Almanca 8 karakter veya İngilizce modül öneki) hiçbirine uymaz ve Türkçe/İngilizce karışık adlar taşır; dolayısıyla bankanın veya uygulayıcının Siron ile MASAK raporlaması arasına kurduğu yerel katmandır. Bu okuma vendor belgesine değil MASAK form yapısına dayanır. MASAK Şüpheli İşlem Bildirim Rehberi ŞİB formunu A-H bölümlerine ayırır: A yükümlü bilgileri (Yükümlü Unvanı, VKN, TCKN), B bildirim bilgileri (Referans No, Yeni/Ek, Aciliyet: Normal/İvedi/Çok İvedi/İşlemin Ertelenmesi Talepli, Bildirim Kategorisi), C gerçek kişiler (İşlem ile Bağlantısı, Ad, Soyad, TCKN/YKN, VKN, Uyruk, Anne/Baba Adı, Adres, Doğum Tarihi/Yeri, Kimlik Belge No, Telefon, E-posta, **İş ve Meslek**), D tüzel kişiler (Kuruluş Nev'i, Unvan, VKN, Sicil/MERSİS No, **Ülke**, İl/İlçe, Adres, Faaliyet Konusu), E işlemler (İşlem Durumu, Tarih, Para Birimi, Tutar, Tutar TP, **İşlem Türü kodu**, Yer, Açıklama), F hesaplar (Kuruluş, Şube, Hesap No, IBAN), G şüphe kategori kodları (**SK-01 … SK-27**), H serbest metin ([MASAK ŞİB Rehberi, sigorta sürümü](https://orientsigorta.com.tr/Upload/Masak/Supheli-islem-Bildirim-Rehberi.pdf)). SMMM sektörü rehberi (2025) aynı yapıyı, Şüpheli İşlem Tipleri kodlarını (T-018-x.y) ve elektronik dosyalama için "MASAK.Online"ı anar ([alomaliye.com SMMM rehberi](https://www.alomaliye.com/wp-content/uploads/2025/09/supheli-islem-rehberi-smmm.pdf)).

Bu yapı tablo adlarını neredeyse kendiliğinden açıklar: **MASAK_2_SIRON_FIELD_MAP** = ŞİB form alanlarının Siron sütunlarına eşlemesi (büyük olasılıkla CKUNDE/CKONTO/CTRANS veya GWG* sütunları; hangisi olduğu ancak tablonun içeriği okununca anlaşılır), **BANK_2_MASAK_CODE** = bankanın iç kodlarının (işlem türü, meslek, ülke, hukuki şekil) MASAK kod listelerine çevirisi, **PARAM_MESLEK** ve **PARAM_ULKEKODU** = bu çeviriyi besleyen yerel meslek ve ülke kod parametreleri (Siron tarafında CBERUFTYP = Berufstyp = meslek tipi ve GWGLAND = ülke tablolarına karşılık gelir). Rehberlerde "İş ve Meslek" ve ülke serbest metindir; banka MASAK.Online elektronik şemasının kod listelerini kullanıyor olabilir, bu şema getirilen rehberlerde yoktur. SIBFORM/LOCKEDSIBFORMS ise ACM'nin İngilizce adlı ailesi içinde durur; "SIB" = Şüpheli İşlem Bildirimi okuması Türk kurulumu için güçlü bir hipotezdir ama iki gerçek onu zayıflatır: tablo adı vendor'un İngilizce adlandırma kalıbına uyar ("SIB" + "FORM", "LOCKED" + "SIBFORMS") ve ACM'nin goAML standardında SAR/STR/CTR şablonları ürettiği belgelidir ([IMTF ACM factsheet](https://a.storyblok.com/f/110673/x/9e3d8632f7/rz_siron_acm_en.pdf)); yani SIBFORM, ACM'nin genel bildirim formu altyapısının Türkçe kısaltmalı bir uyarlaması da, tamamen başka bir açılımın (ör. "Siron Investigation Base") tablosu da olabilir. Doğrulamanın yolu yalın: `SELECT * FROM SIRON.SIBFORM WHERE ROWNUM <= 20` ve sütun adlarında SK-xx, VKN/TCKN, İşlem Türü gibi MASAK alanlarının izi.

Bu yerel tablolar için vendor dokümantasyonu beklenmemelidir; onların "veri sözlüğü" bankanın uyum birimi ve ilk uygulayıcıdır. Pratik öneri, bu tablolara `COMMENT ON` ile hemen açıklama yazmak ve MASAK_2_SIRON_FIELD_MAP içeriğini vendor şemasının ters mühendisliğinde kaldıraç olarak kullanmaktır: bu tablo zaten "hangi Siron sütunu hangi iş kavramına karşılık gelir" bilgisini, ŞİB formunun kapsadığı alanlar için, bankanın kendi elinde tutuyor demektir.

## Bulunamayanlar ve neden: engellenen kanallar, kilitli belgeler, tek kaynaklı tarihler

Araştırma ortamının çıkış vekil sunucusu Wayback Machine'i, GitHub code search'ü, grep.app, searchcode.com, Sourcegraph, Stack Overflow, Scribd, docplayer, Google Books API ve LinkedIn/Xing profillerini engelledi. **GitHub kod araması ve Wayback Machine sonradan kullanıcının tarayıcısından tarandı** (sonuçlar "Ek tarama" bölümünde): sızmış bir Siron DDL'i yok, ancak KYCCUST/PRESULT/TBRLEINT sütunları, Siron KYC WSDL'i ve tonbeller.com arşivindeki TDI/Kern/GwG belgeleri bulundu. Hâlâ taranmayan kanallar: grep.app/searchcode/Sourcegraph (GitHub dışı kod), Scribd/docplayer PDF'leri, FICO Community'nin eski Siron alanı (yalnızca yüklenme kabuğu döndürdü), Xing/freelancermap CV'leri, Alman üniversite OPUS depoları, DPMA/Google Patents (Tonbeller AG), Chartis/Celent vendor profilleri ve FICO World oturum katalogları; tonbeller.com arşivinde de `DemoTDI.pdf`, `Factsheet_SironGwG.pdf`, `Informationen_Siron.pdf`, Siron DWH-Builder factsheet'i ve 2001/2003 sürüm duyuruları okunmadı.

İçerik boşlukları da nettir. Hiçbir Siron içe aktarım dosyası yerleşimi (Kunde/Konto/Transaktion kayıt tipleri, alan adları, uzunluklar, zorunluluk bayrakları) hiçbir dilde bulunamadı; C* ve GWG* ailelerinden hangisinin staging/arayüz katmanı olduğu doğrulanamadı. "Siron Designer", "Siron Administrator", "Siron Workbench" veya "Repository Browser" adlı araçların varlığına dair kanıt yoktur; var olan "Siron Enterprise Cockpit Designer" (2011) bir BI gösterge paneli tasarımcısıdır, şema aracı değil ([it-zoom 2011](https://www.it-zoom.de/dv-dialog/e/siron-enterprise-cockpit-designer-387/)). Yönetici arayüzüne dair tek sözlük, 2013 Tonbeller eğitim gündemindeki "Das Research-System Siron®AML", "Indizien und Schwellenwerte definieren", "Kunden-Kategorien einrichten", "Administration" maddeleridir ([Akademie SFG Saar](https://www.akademie-sfg-saar.de/seminar/pdf/seminar/396)) ve IMTF 25.2 sürüm notundaki konfigürasyon bileşenleri "Comparison Objects, Reference Lists, Risk Classes, Stopwords, Variables, Customer Categories, and Scenarios"tır ([IMTF 25.2 release](https://imtf.com/news/sironone-25-2-release-smarter-faster-fully-integrated/)); bunların tablolara eşlemesi (Vergleichsobjekte/Referenzlisten → GWGINKL/GWGEXKL, SL_*; Indizien → GWGIND; Domänen → TBDOMAIN/TBDOMVAL) tahmindir. GB_/RB_, TDI, MM, WS, SIB, GWA'daki "A" ve C'nin açılımı ile GWGCCKU, GWGGL*, GWGBUTAA, GWGKUSY, GWGMRISK, CZVF, CVST, CEKRIT, CARINST, EPRPE/EBRPE, EMBDWHPE_DATA tabloları çözülmemiş kaldı; bir Net.Bit danışmanının listelediği "MCA" modül kısaltması da hiçbir yerde açılmıyor.

Tarihsel ayrıntılarda tek kaynaklılık uyarısı gerekir. YYMM sürüm etiketi ("Version 1606 / July 2016") yalnızca financialit.net profilinde geçer; FICO veya IMTF'nin "1606/1706/1806" yazan hiçbir sürüm notu bulunamadı. Siron 4GL'nin modern bir "Repository/Katalog/Datenlexikon" taşıdığı iddiası, 1997 tezinin anahtar kelime bulutuna ve çok-DBMS mimariye dayanan bir çıkarımdır; tezin 165 sayfalık metni (ISBN 9783832402488, diplom.de/GRIN'den satın alınabilir) klasik SIRON/E'nin katalog mekaniğini anlatan tek kamuya açık teknik belgedir ve okunmadı. Siron'un Oracle tablo yorumlarını doldurup doldurmadığına dair iki yönde de kamu kanıtı yoktur; bu yalnızca veritabanında kontrol edilebilir. Son olarak, görev tanımındaki "IMTF Siron 2025" tarihi kaynaklarla uyuşmaz: devir Kasım 2022'de anlaşıldı, 1 Aralık 2022'de kapandı; 2024-2026, Siron®One pazarlaması ve AWS Marketplace listelemesi dönemidir ([IMTF AWS Marketplace news](https://imtf.com/news/imtf-announces-sironone-availability-in-aws-marketplace/)).

## Sonuç

Bu araştırmanın asıl dersi, Siron için "veri sözlüğü" kavramının yer değiştirmesidir: aranan şey Oracle kataloğunda bir yorum sütunu değil, 1980'lerden gelen bir 4GL'nin kendi tablolarında sakladığı ve yalnızca vendor'un portalında belgelenen bir meta-katmandır. Bankanın elindeki en güçlü iki kaldıraç da kendi içindedir: TB* ailesinin sözlük adaylarını yarım günde test eden üç sorgu ve bankanın MASAK köprü tablolarının zaten içerdiği sütun-kavram eşlemesi. Vendor belgesi istenirken bu iç çalışma bekletilmemelidir, çünkü IMTF'den gelecek generic "Datenbankbeschreibung" ancak bankanın kendi FK grafı, kullanım sayaçları ve uygulama SQL'iyle birleştirildiğinde "bu kurulumda bu tablo gerçekten ne yapıyor" sorusunu yanıtlar; 400 tablonun bir kısmı (PRESULT1706 gibi yedekler, kullanılmayan modüllerin boş tabloları, yerel PARAM_*) hiçbir vendor belgesinde yer almayacaktır.

Beklenti yönetimi de önemlidir. Tablo adlarının açık web'de hiç geçmemesi, bu raporun önek düzeyindeki okumalarını yanlışlamaz ama tablo düzeyindeki her satırı hipotez konumunda tutar; bu hipotezlerin doğrulanması, sırayla, kataloğun kendisi, çalışma zamanı SQL'i, Bensheim'daki mühendislik ekibi ve engelsiz bir ortamdan yeniden koşulacak GitHub/Wayback taramalarıyla yapılmalıdır. Bu sırayla ilerleyen bir DBA, resmi belge gelmeden önce bile şemanın büyük bölümünü güvenle etiketleyebilir ve belge geldiğinde onu doğrulanmış bir modele diff'leyerek bankaya özgü sapmaları (yerel tablolar, kullanılmayan modüller, geçiş yedekleri) görünür kılar.

## Kaynaklar

Vendor, destek ve ortaklar:
- https://imtf.com/customer-support/
- https://imtf.atlassian.net/servicedesk/customer/portals
- https://imtf.com/about-us/contact/
- https://imtf.com/about-us/
- https://imtf.com/imtf-partners/
- https://imtf.com/insights/download/
- https://imtf.com/siron-one-financial-crime-compliance-software/siron-services/
- https://imtf.com/news/imtf-completes-the-acquisition-of-the-siron-compliance-aml-business-from-fico/
- https://imtf.com/news/sironone-25-2-release-smarter-faster-fully-integrated/
- https://imtf.com/news/imtf-announces-sironone-availability-in-aws-marketplace/
- https://imtf.com/events/sironuser-group-2026/
- https://campus.imtf.com/additional-info
- https://a.storyblok.com/f/110673/x/9e3d8632f7/rz_siron_acm_en.pdf
- https://www.holicyconsulting.com/
- https://info.msg-compliance.com/hubfs/pdf/msg-rethink-compliance_Servicekatalog-Siron.pdf?hsLang=de
- https://devcloud.fico.com/en/products/siron-anti-financial-crime-solutions
- https://devcloud.fico.com/en/newsroom/fico-and-msg-partner-help-european-african-and-middle-east-businesses-meet-changing
- https://www.businesswire.com/news/home/20221115005365/en/FICO-Transitions-Siron-Compliance-Solutions-to-Partner-IMTF
- https://www.biia.com/swiss-imtf-group-becomes-a-global-leader-in-banking-compliance-solutions/
- https://www.sec.gov/Archives/edgar/data/814547/000081454715000010/R30.htm
- https://mk.linkedin.com/in/veninov

Ürün tarihi, modüller ve mimari:
- https://www.moneycab.com/?p=1318207
- https://www.moneycab.com/?p=1318377
- https://www.moneycab.com/news/umfassend-guenstig-und-schnell-eingefuehrt-die-sironaml-suite-von-imtf-3/
- https://www.prnewswire.co.uk/news-releases/tonbeller-ag-extends-solution-portfolio-with-siron-know-your-customer-to-fight-financial-crime-and-the-financing-of-terrorism-156143775.html
- https://www.prnewswire.co.uk/news-releases/belgazprombank-fights-financial-crime-with-fico-tonbeller-sanctions-screening-694882821.html
- https://www.appsruntheworld.com/customers-database/products/view/fico-siron
- https://financialit.net/products/security-compliance/ficorsironr-anti-financial-crime-solutions
- https://www.temenos.com/wp-content/uploads/2020/06/2017-APAC-Vendor-Landscape-AML-Solutions.pdf
- https://www.computerwoche.de/article/2812173/adv-orga-buhlt-um-potente-hardware-partner.html
- https://books.google.de/books/about/Entwicklung_eines_Leitfadens_zur_systema.html?hl=de&id=udt-AQAAQBAJ
- https://m.diplom.de/document/216193
- https://www.akademie-sfg-saar.de/seminar/pdf/seminar/396
- https://www.it-zoom.de/dv-dialog/e/siron-enterprise-cockpit-designer-387/
- https://www.brighttalk.com/webcast/15921/509203
- https://www.printecgroup.com/?p=944

Tablo adı aramaları (negatif sonuçlar):
- https://en.wikipedia.org/wiki/GWG
- https://www.rcsb.org/annotations/1QXX

Ek tarama (GitHub ve Wayback Machine, tarayıcıdan):
- https://github.com/ahmedrhuma/SironKYC-TemenosT24-middleware (Customer.java, config.json: KYCCUST, PRESULT, TBRLEINT SQL'i)
- https://raw.githubusercontent.com/rosamedgroup/SmartTool/main/src/main/webapp/wsdl/SironKYC/KYCService01.wsdl (Tonbeller Siron KYC SOAP WSDL)
- https://web.archive.org/web/20110201132704/http://www.tonbeller.com/products/bi/sirontdi (Siron TDI)
- https://web.archive.org/web/20060519133007/http://www.tonbeller.com/produkte/bitools/kern/ (Siron Kern)
- https://web.archive.org/web/20040903202614/http://www.tonbeller.com/PDF/SironGwG_WhitePaper_deu.pdf (Siron GwG White Paper, 27.10.2003)
- https://web.archive.org/web/20170210151929/http://www.tonbeller.com/en/services/academy/product-trainings (Siron AML Basic Training içeriği)
- https://web.archive.org/web/20040826194208/http://www.tonbeller.com/Presse_aktuelles/Freigabe_der_Siron_Version_2003.html (Siron BI Suite 2003 sürümü)
- https://web.archive.org/cdx/search/cdx?url=tonbeller.com/* (arşivlenmiş tonbeller.com URL listesi; DemoTDI.pdf, Factsheet_SironGwG.pdf, Informationen_Siron.pdf gibi okunmamış belgeler burada)
- GitHub code search, sıfır sonuç veren tam sözcük sorguları: /\bGWGKUNDE\b/, /\bGWATRHIT\b/, /\bTBDOMVAL\b/ ve (?-i)\b(KSLMAIN|SIBFORM|FARCUSTOMER|TBQFORMS|GWGTRANS|CKUNDE|PRESULT_ARCHIVE|TDIREPOS|GWGKONTO|TBFELDZ|TBRLIST|GWGIND|GWGKAT|CVFAAUFF|TBDOMAIN)\b

MASAK:
- https://orientsigorta.com.tr/Upload/Masak/Supheli-islem-Bildirim-Rehberi.pdf
- https://www.alomaliye.com/wp-content/uploads/2025/09/supheli-islem-rehberi-smmm.pdf

Oracle dokümantasyonu:
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_TAB_COMMENTS.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_CONSTRAINTS.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_TAB_MODIFICATIONS.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/ALL_DEPENDENCIES.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/COMMENT.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/V-SQL.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/V-SQL_PLAN.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/arpls/DBMS_MONITOR.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/dblic/Licensing-Information.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/CREATE-AUDIT-POLICY-Unified-Auditing.html
- https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/UNIFIED_AUDIT_TRAIL.html
- https://docs.oracle.com/en/database/oracle/sql-developer/23.1/rptug/sql-developer-concepts-usage.html
- https://docs.oracle.com/en/database/oracle/sql-developer-data-modeler/23.1/dmdug/data-modeler-concepts-usage.html
- https://www.oracle.com/webfolder/technetwork/tutorials/obe/db/apex/r51/dm4.1/index.html

Araçlar:
- https://schemaspy.readthedocs.io/en/latest/started.html
- https://schemaspy.readthedocs.io/en/latest/installation.html
- https://schemaspy.sourceforge.net/
- https://teamdynamix.umich.edu/TDClient/210/DepressionCenter/KB/Article/11889/How-to-use-SchemaSpy-to-document-research-datasets
- https://dbeaver.com/docs/dbeaver/ER-Diagrams/
- https://dbschema.com/blog/design/best-tools-for-database-documentation
- https://dataedo.com/kb/tools/toad-oracle/how-to-generate-database-documentation

Bu ortamdan erişilemeyen kanallar (engelsiz ortamdan yeniden denenmeli): web.archive.org (tonbeller.com 1998-2014 arşivleri), GitHub code search, grep.app, searchcode.com, Sourcegraph, Stack Overflow, Scribd, docplayer, Google Books API, LinkedIn/Xing profilleri, community.fico.com, netbit.mk, bateleur.co.za, bfsoftco.com, yumpu Tonbeller factsheet'leri (boş gövde döndürdü).
