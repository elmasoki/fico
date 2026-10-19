# Siron SQL Tracer

Siron AML'den yeni sisteme geçiş için **veri keşif ve eşleme stüdyosu**. Siron'un Oracle'da her ekranda
hangi tablo ve kolonları kullandığını audit kayıtlarından çıkarır, tablolar arası ilişkileri bulur,
eşleme kararlarını yönetir ve taşınacak veriyi paketler.

- Sadece Python gerekir; Oracle Client kurulumu gerekmez (`python-oracledb` thin mode).
- İnternetsiz çalışır (CDN yok), açık/koyu tema.
- Oracle'a **salt-okunur** bağlanır; yalnızca `SELECT`/`WITH` çalıştırır, her çalıştırmayı günlüğe yazar.
- Gerçek Oracle 23ai Free üzerinde entegrasyon testleriyle doğrulanır (unified audit dahil).

![Genel bakış](docs/screenshots/01_genel_bakis.png)

## Ne yapar?

| İhtiyaç | Özellik |
|---|---|
| Bu ekran hangi tabloları kullanıyor? | **Ekran yakalama** — Başlat → Siron'da ekranı kullan → Durdur. Birden çok DB kullanıcısı ve yakalamaya özel şema seçilebilir. Canlı akış izlenir. |
| Gece çalışan işler ne yapıyor? | **Batch yakalama** — geçmiş zaman aralığı; yalnız batch'te görülen tablolar ayrıca raporlanır |
| Yakaladığım SQL'leri tüm kayıtlar için nasıl çekerim? | **Taşıma sorgusu üretme** — SQL detay sayfasında "Tüm kayıtlar için sorgu üret" (veya ekran sayfasında bağlı SQL'lerin hepsi için tek tıkla): bind değerine bağlı filtreler ve sayfalama (ROWNUM, FETCH FIRST) kaldırılır, join'ler, kolonlar ve sabit filtreler (`HISTBIS = '9999'`) korunur. Kaldırılan/korunan koşullar listelenir; satır sayısı, önizleme, CSV ve taşıma paketine ekleme (kendi şemasıyla, SQL*Plus betiği dahil) |
| Kayıt sırasında ne yaptığımı nasıl not ederim? | **Kayıt işaretleri** — kayıt ekranında "Ara'ya basıyorum" yazıp Enter (veya hazır düğmeler); işaret veritabanı saatiyle kaydedilir, zaman akışında o andan sonraki SQL'ler bu başlıkla ayrı bir adım olur ve ekrana bağlarken not olarak gelir. Sonradan da her adıma ad verilebilir |
| Yakalamama başkasının SQL'i karıştı mı? | **Kaynak kontrolü** — her yakalamada SQL'leri çalıştıran OS kullanıcısı / makine / program / client id dökümü; birden fazla kaynak varsa uyarı, sizin olmayan kaynakları analizden çıkarma; kayıt sırasında canlı uyarı; kayıttan önce "Şu an Siron'u kullanan var mı?" kontrolü (son 5 dakika) |
| Hangi tıklama hangi SQL'i çalıştırdı? | **Zaman akışı** — yakalamadaki SQL'ler çalışma sırasıyla, duraklamalara göre **adımlara** bölünür (eşik ayarlanabilir); her adımın süresi, tabloları ve bind değerleri görünür. **Yakalama karşılaştırma** — iki yakalamada ortak ve yalnız birinde görülen tablolar, SQL kalıpları, kolonlar ("Detay" düğmesine basınca ne değişti?) |
| Ekranda gördüğüm değer hangi sorguya gitti? | **Bind değerinde arama** — genel arama ve "Ekrandaki değeri bul", değeri audit'teki bind'lerde de arar: arama kriteri olarak girilen müşteri no'nun hangi SQL'e parametre olarak gittiği bulunur |
| Bu müşterinin verisi başka hangi tablolarda var? | **Kayıt izi** — bildiğiniz bir değerle başlayın (ör. ekranda gördüğünüz müşteri no): değer şemadaki anahtar adayı kolonlarda (PK/UK/FK, indeksli, kimlik adlı; büyük tablolarda yalnız indeksli olanlar) aranır, bulunan satırların anahtarlarıyla ilişkili tablolara adım adım geçilir (müşteri → hesaplar → hareketler). Her tablo için yol (`CUSTOMER.ID → ACCOUNT.CUST_ID · FK`), satır sayısı, örnek satırlar ve o tabloya giden hazır JOIN sorgusu; **hiçbir ekran yakalamasında görünmeyen** tablolar ayrıca işaretlenir. Arka plan işi, salt-okunur |
| Elle yazdığımız taşıma sorgusu doğru mu? | **Sorgu defteri** — taşıma sorgularının ortak defteri: her değişiklik yazan kişi ve notuyla **sürüm** olarak saklanır (fark görünümü, geri yükleme). Her sorguya **doğrulama senaryoları** eklenir: Siron ekranındaki bir kaydın bind değerleri ve ekranda görünen değerler, düz metin kurallarla (`satır = 3`, `FULL_NAME = AHMET YILMAZ`, `IBAN ~ TR00`, `RISK != H`, `IBAN dolu`, `tüm STATUS = OPEN`). Senaryolar tek tek, sorgu bazında veya tüm defter için arka planda çalıştırılır; kalan satırlar sonuçtaki gerçek değerleri gösterir. Beklentiler envantere bağlı ekran SQL'inden önerilebilir (Siron'un kaydettiği bind ile yeniden çalıştırılır). İş birimi için tek dosyalık **doğrulama raporu**. Kayıt izi sonucundan, taşıma sorgusu sayfasından ve SQL konsolundan deftere tek tıkla aktarılır |
| Bu ekranın verisi hangi sorgudan geliyor? | **Ekran envanterine SQL bağlama** — SQL detayından veya zaman akışında toplu seçimle bir SQL'i ekrana bağlayın ve "ne getiriyor" notu düşün; envanterde ve **ekran sayfasında** SQL_ID, yakalama adı ve yakalama tarihiyle listelenir, Excel'e de çıkar. Bindleri yerleştirilmiş SQL'de değerler **vurgulanır** ve bind satırıyla eşleşir |
| Yakalamadaki SQL'leri tek tek çalıştırmak zahmetli | **Sıradaki SQL** — SQL sayfasında Çalıştır'dan sonra sonucun altında **Sonraki SQL'i çalıştır** / **Önceki** çubuğu: yakalama özetindeki listeyi aynı sırayla (kaynak filtresi, gürültü ve gruplama ayarlarıyla) dolaşır, her SELECT'i kendi yakalanan bind değerleriyle çalıştırır; UPDATE/INSERT gibi çalıştırılamayanlar atlanır |
| Ekrandaki alan hangi kolondan geliyor? | **Kolon analizi** (gösterim / filtre-join / sıralama / yazma) ve **Ekrandaki değeri bul** — ekranın SQL'leri bindleriyle yeniden çalıştırılır, değer sonuçta bulunur ve `TABLO.KOLON`'a eşlenir |
| Paket / view arkasında ne var? | **Bağımlılık analizi** (`DBA_DEPENDENCIES`) — paket veya view üzerinden erişilen tablolar "dolaylı" olarak gösterilir |
| Tablolar nasıl bağlı? | **İlişki keşfi** — FK constraint'leri + Siron'un kendi SQL join'leri + kolon adı/tip tahmini; 0-100 güven puanı; tek tek veya toplu **veriyle doğrulama** |
| Model nasıl görünüyor? | **ER diyagramı** — sürüklenebilir, karar durumuna göre renkli; Mermaid / Graphviz / SVG dışa aktarma |
| Kolonda ne var? | **Veri profili** — doluluk, farklı değer, min/max, uzunluk, en sık değerler; "hep boş", "tek değer", "benzersiz" uyarıları |
| Neyi taşıyacağız? | **Eşleme kararları** — tablo/kolon başına Taşınacak / İncelenecek / Gereksiz, hedef alan, iş anlamı, çıkarma filtresi; toplu karar |
| Analistlerle nasıl çalışırız? | **Excel gidiş-dönüş** — biçimli çalışma kitabı (açılır listeler, sarı düzenlenebilir hücreler), geri yükleme, tek tıkla geri alma |
| Bu tablo ne işe yarıyor? | **Araştırma** — Siron tabloları üzerine yapılan açık kaynak araştırması uygulamanın içinde: tablolar önek ailelerine göre 15 Siron modülüne (AML, KYC, Embargo, TCR/FATCA, ACM, Tonbeller platformu, MASAK köprüsü…) ayrılır; her modülde şemanızda kaç tablo var, kaçı ekranlarda görüldü. 136 tabloluk sözlük (anlam, Almanca açılım, güven derecesi), Almanca kolon adı çözümleyici (KUNDNR, HISTBIS…), seçilen şemaya uyarlanmış doğrulama sorguları ve belgenin tam metni. Tablo sayfasında ve raporda araştırma notu |
| Bir şeyi atladık mı? | **Ekran envanteri ve kapsam** — yakalanmayan ekranlar, hiçbir ekranda görünmeyen dolu tablolar, karar bekleyen kolonlar, doğrulanmamış ilişkiler |
| Veriyi nasıl çekeriz? | **Sorgu oluşturucu** (en güvenilir JOIN yolu) ve **Taşıma paketi** — ilişkilere göre yükleme sırası, PK ve ilişki kolonları otomatik dahil; SQL betikleri (.zip, SQL*Plus spool dahil) veya doğrudan CSV'ye **veri çıkarma** (satır sayısı + SHA-256 manifest) |
| Ekibe ne sunarız? | **Tek dosyalık HTML rapor** (yönetici özeti, veri sözlüğü, eşleme matrisi, ER, SQL'ler, sonuçlar), CSV/Excel çıktıları |
| KVKK / denetim? | **Hassas veri tespiti** (TCKN, IBAN, telefon, ad-soyad… otomatik, kolon bazında düzeltilebilir), dışa aktarımlarda **maskeleme** (hassas / tümü / yok), **etkinlik günlüğü** (kim, ne zaman, hangi sorgu, kaç satır) |

**Renk teması:** üst çubuktaki palet düğmesiyle **Siron (mavi)** ve **Odeabank (siyah · altın)** temaları arasında
geçilir; açık/koyu mod her ikisinde de çalışır. Seçim tarayıcıda saklanır; herkes için varsayılan tema `config.ini`'de
`[app] ui_theme = odea` ile belirlenir.

Ayrıca: literal farkıyla çoğalan SQL'lerin gruplanması (bind kullanmayan uygulamalar için), SQL biçimlendirme,
global arama (`/` kısayolu), uzun işlemler için ilerleme gösteren arka plan işleri.

## Kurulum (Windows)

1. Python 3.9+ kurulu olsun (`python --version`).
2. Proje klasöründe **`kurulum.bat`** dosyasını çalıştırın: sanal ortamı kurar, paketleri yükler, `config.ini`'yi
   oluşturup Not Defteri'nde açar. Doldurmanız gerekenler:
   ```ini
   [oracle]
   dsn = dbsunucu:1521/SERVIS_ADI
   user = KULLANICI_ADINIZ      ; DBA kullanıcınız olabilir, Siron kullanıcısı OLMAMALI
   [siron]
   db_user = SIRON              ; Siron'un bağlandığı kullanıcı
   schemas = SIRON              ; Siron tablolarının şeması
   ```
3. Şifre için en güvenli yol: `.venv\Scripts\python run.py --save-password` (Windows Kimlik Yöneticisi'ne kaydeder).
   Ya da `config.ini`'ye yazın / `ORACLE_PASSWORD` ortam değişkenini kullanın / boş bırakın, açılışta sorulur.
4. **`baslat.bat`** — uygulama Waitress sunucusuyla açılır ve tarayıcıda `http://127.0.0.1:5000` gelir.
5. İlk iş: **Bağlantı kontrolü** sayfası, ardından genel bakıştan **Veri sözlüğünü yükle**.

- **İnternetsiz makine:** internete erişimi olan aynı Python sürümlü bir Windows makinede
  `scripts\cevrimdisi_paket.bat` çalıştırın, oluşan `wheels` klasörüyle birlikte projeyi kopyalayın;
  `kurulum.bat` paketleri oradan kurar.
- **Windows servisi:** `scripts\servis_kur.bat` (NSSM ile). Loglar `data\logs` altında döner.
- **Güncelleme:** kodu yenisiyle değiştirin; `config.ini` ve `data` klasörüne dokunmayın. Yerel veritabanı otomatik yükseltilir.

Linux/macOS: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python run.py --open`

## Oracle tarafı

Audit'i kendi yönteminizle açın (19c unified auditing). Uygulama politikanın adından bağımsızdır;
`UNIFIED_AUDIT_TRAIL`'i yakalamada seçtiğiniz DB kullanıcılarına ve zaman aralığına göre okur.

- Bağlanan kullanıcı `UNIFIED_AUDIT_TRAIL`'i okuyamıyorsa: `GRANT AUDIT_VIEWER TO <kullanıcı>;`
- Audit **yeni oturumlarda** devreye girer: açtıktan sonra Siron'un connection pool'unu yenileyin.
- PL/SQL paketlerinin içindeki SQL'ler de audit'e düşer (`ONLY TOPLEVEL` kullanmayın); paket çağrısının
  kendisini de görmek isterseniz politikaya `EXECUTE` ekleyin.

## Önerilen çalışma akışı

1. **Bağlantı kontrolü** → **Veri sözlüğünü yükle**.
2. **Ekran envanteri**'ne Siron ekranlarını toplu girin (`Modül > Ekran`, Excel'den yapıştırılabilir).
3. Siron'da hiçbir şey yapmadan kısa bir yakalama alıp **Gürültü olarak işaretleyin**. Hatalı veya deneme yakalamalarını
   listeden tek tek ya da toplu silebilirsiniz (eşleme kararları silinmez).
4. Her ekran için yakalama alın (envanterden seçerek). Başlatmadan önce **Şu an Siron'u kullanan var mı?** ile ortamın
   boş olduğunu kontrol edin; kayıt sırasında her tıklamadan önce bir **işaret** koyun ("Ara", "Hesaplar sekmesi"). Ekrana gelene kadar başka yerlerde gezindiyseniz kayıt
   sırasında **Sıfırla**'ya basın: o ana kadar yakalananlar atılır, kayıt devam eder. Gece işleri için **Geçmiş aralık / batch**.
5. Yakalanan tabloların ne olduğunu **Araştırma** bölümünden ve tablo sayfasındaki araştırma notundan okuyun; hipotezleri
   **Doğrulama sorguları** ile kendi veritabanınızda test edin.
6. Yakalamanın **Zaman akışı** sekmesinde adımları Siron'daki tıklamalarınızla eşleştirin; ekranın verisini getiren
   SQL'leri seçip **ekrana bağlayın** (envanterde SQL_ID, yakalama adı ve tarihiyle görünür). Ekranda gördüğünüz bir
   numarayı genel aramaya yazarak hangi SQL'e bind olarak gittiğini bulun. Yakalama özetinde **Kaynaklar** uyarı
   veriyorsa sizin olmayan kaynakları ayıklayın.
7. Ekranın **Kolonlar** sekmesi ve **Ekrandaki değeri bul** ile alanları kolonlara bağlayın.
8. **Tablolar**'da toplu karar verin, önemli tabloları **profilleyin**, tablo sayfasında kolon kararlarını,
   hedef alanları ve hassasiyeti girin — veya **Excel eşleme** ile analistlere dağıtın.
9. **İlişkiler** → **Tümünü veriyle doğrula**; **ER diyagramı** ile modeli gözden geçirin.
10. **Kapsam** sayfasında açık kalanları kapatın (yakalanmayan ekranlar, görünmeyen tablolar).
11. Bir test müşterisinin numarasıyla **Kayıt izi** çalıştırın: verisinin bulunduğu tüm tabloları, özellikle hiçbir ekranda
    görünmeyenleri kontrol edin.
12. Ekranın verisini getiren SQL'lerden **taşıma sorgusu** üretin (ekran sayfasında tek tıkla); **Taşıma paketi**: filtreleri girin, paketi indirin veya veriyi çıkarın.
13. Taşımayı yapacak sorguları **Sorgu defteri**'nde toplayın; her biri için Siron ekranından birkaç kayıt seçip
    **doğrulama senaryosu** yazın, sorgu her değiştiğinde senaryoları yeniden çalıştırın. **Doğrulama raporu**nu ve
    **Raporlar**'daki dokümanı iş birimiyle paylaşın.

## Ekranlar

(Görüntüler, test veritabanında Siron benzeri bir şema üzerinde uygulamanın gerçek çalışmasından alınmıştır.)

| | |
|---|---|
| ![Yakalamalar](docs/screenshots/02_yakalamalar.png) | ![Ekran özeti](docs/screenshots/03_ekran_ozet.png) |
| ![Ekranın kolonları](docs/screenshots/04_ekran_kolonlar.png) | ![Ekrandaki değeri bul](docs/screenshots/05_deger_bul.png) |
| ![Tablo detayı ve eşleme](docs/screenshots/06_tablo_detay.png) | ![Tablolar](docs/screenshots/07_tablolar.png) |
| ![Kolon eşleme](docs/screenshots/08_kolon_esleme.png) | ![İlişkiler](docs/screenshots/09_iliskiler.png) |
| ![ER diyagramı](docs/screenshots/10_er.png) | ![SQL detayı](docs/screenshots/11_sql_detay.png) |
| ![Kapsam](docs/screenshots/12_kapsam.png) | ![Taşıma paketi](docs/screenshots/13_tasima.png) |
| ![Ekran envanteri](docs/screenshots/14_envanter.png) | ![Arka plan işleri](docs/screenshots/15_isler.png) |
| ![Etkinlik günlüğü](docs/screenshots/16_etkinlik.png) | ![Excel eşleme](docs/screenshots/17_excel.png) |
| ![Sorgu oluşturucu](docs/screenshots/18_sorgu_olusturucu.png) | ![HTML rapor](docs/screenshots/19_rapor.png) |
| ![Koyu tema](docs/screenshots/20_genel_bakis_koyu.png) | ![ER koyu tema](docs/screenshots/21_er_koyu.png) |
| ![Araştırma: modüller](docs/screenshots/22_arastirma.png) | ![Araştırma: modül detayı](docs/screenshots/23_arastirma_modul.png) |
| ![Tablo sözlüğü](docs/screenshots/24_tablo_sozlugu.png) | ![Doğrulama sorguları](docs/screenshots/25_dogrulama_sorgulari.png) |
| ![Tablo sayfasında araştırma notu](docs/screenshots/26_tablo_arastirma_notu.png) | ![Bind değerleri vurgulu SQL](docs/screenshots/27_bind_vurgulama.png) |
| ![Zaman akışı](docs/screenshots/28_zaman_akisi.png) | ![Ekran sayfası](docs/screenshots/29_ekran_sayfasi.png) |
| ![Envanterde bağlı SQL'ler](docs/screenshots/30_envanter_sql.png) | ![Yakalama karşılaştırma](docs/screenshots/31_karsilastirma.png) |
| ![Bind değerinde arama](docs/screenshots/32_bind_arama.png) | ![Kayıt işaretleri ve canlı kaynak uyarısı](docs/screenshots/33_kayit_isaretleri.png) |
| ![Kaynak karışması ve ayıklama](docs/screenshots/34_kaynak_karismasi.png) | ![İşaretli zaman akışı](docs/screenshots/35_zaman_akisi_isaretli.png) |
| ![Taşıma sorgusu üretme](docs/screenshots/36_tasima_sorgusu.png) | ![Taşıma paketinde ekran sorguları](docs/screenshots/37_tasima_ekran_sorgulari.png) |
| ![Kayıt izi](docs/screenshots/38_kayit_izi.png) | ![Kayıt izi sonucu](docs/screenshots/39_kayit_izi_sonuc.png) |
| ![Sorgu defteri](docs/screenshots/40_sorgu_defteri.png) | ![Sorgu, sürümler ve doğrulama senaryoları](docs/screenshots/41_sorgu_defteri_sorgu.png) |
| ![Doğrulama raporu](docs/screenshots/42_dogrulama_raporu.png) | ![Odeabank teması](docs/screenshots/43_tema_odeabank.png) |
| ![Odeabank teması, koyu](docs/screenshots/44_tema_odeabank_koyu.png) | |

## Araştırma bölümü

Siron'un tablo dokümantasyonu vendor tarafından verilmediği için, tabloların anlamına dair yapılmış açık kaynak araştırma
(`siron_tracer/knowledge/siron_aml_arastirma.md`) uygulamaya gömülüdür ve iş birimi doğrudan uygulamadan okuyabilir:

- **Modüller:** şemanızdaki her tablo, adının önekine göre bir Siron modülüne ayrılır (GWG* → AML çekirdeği, TB* → Tonbeller
  platformu, TBQ* → KYC anket, SL_* → yaptırım listeleri, FAR*/TAX* → FATCA/CRS, PARAM_*/MASAK_* → yerel MASAK köprüsü…).
  Kart başına şemadaki tablo, ekranlarda görülen ve karar verilen sayıları; araştırmada karşılığı olmayan (bankaya özgü) tablolar ayrıca listelenir.
- **Güven dereceleri:** *Doğrulanmış* (gerçek Siron SQL'inde görüldü: KYCCUST, PRESULT, TBRLEINT…), *Olası*, *Tahmin*, *Çözülmemiş*.
  Tablo düzeyindeki anlamların çoğu hipotezdir; yakalamalarla teyit edip tablo sayfasındaki "İş anlamı / not" alanına yazın.
- **Almanca terimler:** KUNDNR, HISTBIS, BUCHUNGSDATUM gibi adlar parçalarına ayrılıp Türkçeye çevrilir; tablo sayfasında her kolonun altında görünür.
- **Doğrulama sorguları:** araştırmadaki 27 sorgu seçtiğiniz şemaya uyarlanır; SELECT olanlar uygulamada salt-okunur çalışır, PL/SQL olanlar kopyalanır.
- **Belge:** içindekiler tablosuyla tam metin; yeni bir araştırma sürümü geldiğinde **Yeni sürüm yükle** ile `.md` dosyası yüklenir, istenirse orijinale dönülür.
- Tablolar listesinde **Modül** sütunu ve filtresi, genel aramada araştırma sonuçları, HTML raporda (isteğe bağlı) modül özeti ve tablo başına araştırma notu.

## Audit kaynakları

Varsayılan `config.ini → audit_source`; yakalama formunun gelişmiş bölümünden yakalama başına da seçilebilir.

| Değer | Ne okur | Not |
|---|---|---|
| `unified` | `UNIFIED_AUDIT_TRAIL` | 19c/23ai. SQL metni ve bindler tam. Önerilen |
| `traditional` | `DBA_AUDIT_TRAIL` | SQL metni 2000 karakterde kesilir |
| `aud$` | `SYS.AUD$` | Traditional, tam SQL metni |
| `cursor_cache` | `GV$SQL` + `GV$SQL_BIND_CAPTURE` | Audit gerektirmez; ön keşif için. Bindler örneklenmiş |

## Teknik notlar

- **SQL_ID**, `MD5(sql_text || CHR(0))` ile hesaplanır ve V$SQL ile birebir eşleşir (gerçek Oracle'da test edilir).
  Unified audit'in `SQL_TEXT` sonuna eklediği NUL karakteri temizlenir.
- **Bindler** audit'in `#1(4):1001` biçiminden uzunluk bilgisiyle ayrıştırılır; çok baytlı Türkçe karakterler desteklenir.
- **SQL analizi** token tabanlıdır: ORM alias'ları, ANSI ve `(+)` join'ler, alt sorgular, CTE'ler, `SELECT *`.
  Tanımadığı yapıda hata vermez, daha az bulgu üretir.
- **İlişki doğrulama** alt tablodan en fazla 5.000 dolu satır örnekler; %95+ eşleşme güveni ≥85'e çıkarır, %50 altı 25'e indirir.
- **Profil** büyük tablolarda `SAMPLE` kullanır (`profile_sample_rows`); kesin `COUNT(DISTINCT)` hesaplar.
- **Taşıma sırası** ilişkilere göre topolojik sıralanır; döngüsel bağımlılıklar işaretlenir. PK ve taşınan
  tablolar arası ilişki kolonları, açıkça "Gereksiz" denmedikçe her zaman pakete girer.
- **Kayıt izi** her adımda en fazla 200 farklı anahtar değeri taşır, satır sayılarını 10.000'de keser ve yalnız tek kolonlu
  ilişkileri izler (güven ≥50). İndeks bilgisi veri sözlüğüyle yüklenir (`DBA_IND_COLUMNS`, ilk kolon); indekssiz büyük
  tablolar istenmedikçe taranmaz.
- **Sorgu defteri** senaryoları en fazla 1.000 satır getirir; yalnız SQL'de geçen bind'ler gönderilir (`:1, :2` sıralı,
  adlı bind'ler büyük/küçük harf duyarsız). Sonuçlar senaryonun son çalıştırmasıdır; SQL değişince yeniden çalıştırın.
- **Yerel depo** `data/siron_tracer.db` (SQLite, WAL). Audit temizlense de analiz kaybolmaz; yedeklemek için dosyayı kopyalayın.
- **Güvenlik:** varsayılan olarak yalnız `127.0.0.1`; form isteklerinde CSRF koruması; oturum çerezi `SameSite=Strict`.
  Kimlik doğrulaması yoktur — ağa açmayın.

## Geliştirme ve test

```bash
pip install -r requirements-dev.txt
python -m pytest tests --ignore=tests/integration          # birim testleri

# gerçek Oracle ile (Docker):
docker run -d -p 1521:1521 -e ORACLE_PASSWORD=Test1234 gvenzl/oracle-free:23-slim-faststart
SIRON_IT_DSN=localhost:1521/FREEPDB1 SIRON_IT_SYS_PASSWORD=Test1234 python -m pytest tests/integration
```

GitHub Actions her push'ta birim testlerini (Python 3.9 ve 3.12) ve Oracle 23ai Free konteynerine karşı
entegrasyon testlerini çalıştırır (`.github/workflows/ci.yml`).

| Modül | İçerik |
|---|---|
| `sqlutil.py` | SQL_ID, bind ayrıştırma/yerleştirme, tablo referansları, biçimlendirme, literal imzası |
| `sqlinsight.py` | Alias, kolon kullanımı, JOIN koşulları, SELECT listesi → kaynak kolon |
| `catalog.py` | Veri sözlüğü: tablo, kolon, PK/UK/FK, paket/view bağımlılıkları |
| `relations.py` | İlişki keşfi, JOIN yolu, SELECT üretimi, Mermaid/DOT |
| `profiling.py`, `finder.py`, `privacy.py` | Veri profili, değer arama, hassas veri ve maskeleme |
| `coverage.py`, `migration.py`, `excel.py` | Kapsam, taşıma paketi ve veri çıkarma, Excel gidiş-dönüş |
| `knowledge/`, `mdrender.py` | Siron araştırması: modüller, önek aileleri, tablo ve terim sözlüğü, doğrulama sorguları, belge (Markdown) |
| `analysis.py`, `jobs.py`, `timeline.py` | Ekran/proje analizi, arka plan işleri, yakalama zaman akışı (adımlar, işaretler) |
| `generalize.py`, `sessions.py` | Ekran SQL'inden taşıma sorgusu üretme, yakalamadaki kaynak (kullanıcı/makine/program) analizi |
| `sources.py`, `oracle.py`, `store.py` | Audit kaynakları, Oracle erişimi, SQLite deposu |
| `views*.py`, `templates/`, `static/` | Arayüz ve raporlar |
