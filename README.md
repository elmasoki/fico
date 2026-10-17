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
| Ekrandaki alan hangi kolondan geliyor? | **Kolon analizi** (gösterim / filtre-join / sıralama / yazma) ve **Ekrandaki değeri bul** — ekranın SQL'leri bindleriyle yeniden çalıştırılır, değer sonuçta bulunur ve `TABLO.KOLON`'a eşlenir |
| Paket / view arkasında ne var? | **Bağımlılık analizi** (`DBA_DEPENDENCIES`) — paket veya view üzerinden erişilen tablolar "dolaylı" olarak gösterilir |
| Tablolar nasıl bağlı? | **İlişki keşfi** — FK constraint'leri + Siron'un kendi SQL join'leri + kolon adı/tip tahmini; 0-100 güven puanı; tek tek veya toplu **veriyle doğrulama** |
| Model nasıl görünüyor? | **ER diyagramı** — sürüklenebilir, karar durumuna göre renkli; Mermaid / Graphviz / SVG dışa aktarma |
| Kolonda ne var? | **Veri profili** — doluluk, farklı değer, min/max, uzunluk, en sık değerler; "hep boş", "tek değer", "benzersiz" uyarıları |
| Neyi taşıyacağız? | **Eşleme kararları** — tablo/kolon başına Taşınacak / İncelenecek / Gereksiz, hedef alan, iş anlamı, çıkarma filtresi; toplu karar |
| Analistlerle nasıl çalışırız? | **Excel gidiş-dönüş** — biçimli çalışma kitabı (açılır listeler, sarı düzenlenebilir hücreler), geri yükleme, tek tıkla geri alma |
| Bir şeyi atladık mı? | **Ekran envanteri ve kapsam** — yakalanmayan ekranlar, hiçbir ekranda görünmeyen dolu tablolar, karar bekleyen kolonlar, doğrulanmamış ilişkiler |
| Veriyi nasıl çekeriz? | **Sorgu oluşturucu** (en güvenilir JOIN yolu) ve **Taşıma paketi** — ilişkilere göre yükleme sırası, PK ve ilişki kolonları otomatik dahil; SQL betikleri (.zip, SQL*Plus spool dahil) veya doğrudan CSV'ye **veri çıkarma** (satır sayısı + SHA-256 manifest) |
| Ekibe ne sunarız? | **Tek dosyalık HTML rapor** (yönetici özeti, veri sözlüğü, eşleme matrisi, ER, SQL'ler, sonuçlar), CSV/Excel çıktıları |
| KVKK / denetim? | **Hassas veri tespiti** (TCKN, IBAN, telefon, ad-soyad… otomatik, kolon bazında düzeltilebilir), dışa aktarımlarda **maskeleme** (hassas / tümü / yok), **etkinlik günlüğü** (kim, ne zaman, hangi sorgu, kaç satır) |

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
3. Siron'da hiçbir şey yapmadan kısa bir yakalama alıp **Gürültü olarak işaretleyin**.
4. Her ekran için yakalama alın (envanterden seçerek). Gece işleri için **Geçmiş aralık / batch**.
5. Ekranın **Kolonlar** sekmesi ve **Ekrandaki değeri bul** ile alanları kolonlara bağlayın.
6. **Tablolar**'da toplu karar verin, önemli tabloları **profilleyin**, tablo sayfasında kolon kararlarını,
   hedef alanları ve hassasiyeti girin — veya **Excel eşleme** ile analistlere dağıtın.
7. **İlişkiler** → **Tümünü veriyle doğrula**; **ER diyagramı** ile modeli gözden geçirin.
8. **Kapsam** sayfasında açık kalanları kapatın (yakalanmayan ekranlar, görünmeyen tablolar).
9. **Taşıma paketi**: filtreleri girin, paketi indirin veya veriyi çıkarın. **Raporlar**'dan dokümanı üretin.

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
| `analysis.py`, `jobs.py` | Ekran/proje analizi, arka plan işleri |
| `sources.py`, `oracle.py`, `store.py` | Audit kaynakları, Oracle erişimi, SQLite deposu |
| `views*.py`, `templates/`, `static/` | Arayüz ve raporlar |
