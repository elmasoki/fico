# Siron SQL Tracer

Siron AML'in Oracle'da hangi ekranda hangi tabloları kullandığını, Siron DB
kullanıcısının **audit kayıtlarından** bulan küçük bir Python + Flask uygulaması.

- Bir ekran için "Başlat → Siron'da ekranı kullan → Durdur" ile o aralıktaki tüm SQL'leri toplar
- Her SQL için **SQL_ID**'yi hesaplar (Oracle'ın V$SQL'deki değeriyle birebir aynı algoritma)
- Audit'teki **bind değerlerini** ayrıştırıp sorguda yerine koyar
- Bindli sorguyu **salt-okunur** çalıştırıp sonucunu gösterir (bind değerleri değiştirilebilir)
- Kullanılan tablo / view / paketleri çıkarır; ekran → tablo ve tablo → ekran haritası, CSV
- Toplanan kayıtları yerel SQLite'a kopyalar; audit temizlense de analiz kaybolmaz

Sadece Python gerekir. `python-oracledb` **thin mode** ile Oracle Client kurmadan bağlanır.

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux: source .venv/bin/activate
pip install -r requirements.txt
copy config.example.ini config.ini   # Linux: cp
# config.ini'yi düzenleyin
python run.py                   # http://127.0.0.1:5000
```

Makinede internet yoksa paketleri başka bir makinede indirip taşıyın:
`pip download -r requirements.txt -d wheels` → hedefte `pip install --no-index --find-links wheels -r requirements.txt`
(iki makinenin Python sürümü / işletim sistemi aynı olmalı).

## Oracle tarafı (DBA)

| Adım | Betik |
|---|---|
| Okuyucu kullanıcı ve yetkiler | `sql/01_reader_user.sql` |
| Audit aç — 12c+ (önerilen) | `sql/02_unified_audit_on.sql` |
| Audit aç — 11g / traditional | `sql/03_traditional_audit_on.sql` |
| İş bitince kapat / temizle | `sql/04_audit_off_cleanup.sql` |

Önemli noktalar:

1. **Uygulama ayrı bir kullanıcıyla bağlanmalı** (örn. `SIRON_TRACER`). Siron kullanıcısıyla bağlanırsanız
   bu uygulamanın sorguları da audit'e düşer. Sorgular çalıştırılırken
   `ALTER SESSION SET CURRENT_SCHEMA = SIRON` yapılır, böylece Siron'un şemasız yazdığı SQL'ler çalışır.
2. **Audit politikası yeni oturumlarda devreye girer.** Politikayı açtıktan sonra Siron'un connection
   pool'unu / uygulama sunucusunu yeniden başlatın.
3. Mümkünse **test ortamında ve tek başınıza** çalışın. Siron bir uygulama sunucusundan tek DB kullanıcısıyla
   bağlandığı için başka kullanıcıların ve arka plan işlerinin SQL'leri de aynı aralığa düşer.
   Bunu azaltmak için:
   - Filtreler: OS kullanıcısı, host, program/module, client identifier
   - **Gürültü yakalaması:** Siron'da hiçbir şey yapmadan 1-2 dakikalık bir yakalama alıp
     "Gürültü olarak işaretle" deyin; o SQL_ID'ler diğer yakalamalarda otomatik gizlenir.
4. `ACTIONS ALL` audit'i hacimli olabilir; yalnızca keşif süresince açık tutun ve sonra kapatın.

## Kullanım

1. **Kurulum kontrolü** sayfasında bağlantı, audit politikası ve yetkileri doğrulayın.
2. Ana sayfada **Kataloğu yenile**: Siron şemasındaki nesneler yüklenir; tablo tespiti SQL içindeki
   gerçek nesne adlarına göre yapılır (paket/fonksiyon çağrıları dahil).
3. **Yeni ekran yakalaması** → ad verin (örn. "Vaka Detay – İşlemler sekmesi") → **Başlat**.
   Siron'da ekranı açın / işlemi yapın. Kayıt sayfasındaki canlı önizlemede audit kayıtlarının
   geldiğini görürsünüz. **Durdur** deyin.
4. Yakalama sayfasında: kullanılan tablolar ve SQL listesi (SQL_ID, çalışma sayısı, farklı bind seti).
5. Bir SQL_ID'ye tıklayın: orijinal SQL, bind setleri, bindleri yerleştirilmiş SQL. Değerleri / tipleri
   değiştirip **Çalıştır** ile sonucu görün. "Cursor cache bilgisini getir" ile hesaplanan SQL_ID'nin
   GV$SQL'de karşılığını ve `GV$SQL_BIND_CAPTURE` değerlerini görebilirsiniz.
6. **Tablo haritası**: tüm ekranlarda hangi tablonun nerede kullanıldığı (CSV ile dışa aktarılabilir).

Geçmiş bir zaman aralığı için de (DB sunucu saatiyle) yakalama oluşturulabilir.

## Audit kaynakları (`config.ini` → `audit_source`)

| Değer | Ne okur | Not |
|---|---|---|
| `unified` | `UNIFIED_AUDIT_TRAIL` | 12c+. SQL_TEXT tam, SQL_BINDS dolu. Önerilen |
| `traditional` | `DBA_AUDIT_TRAIL` | `AUDIT_TRAIL=DB,EXTENDED` gerekir; SQL metni 2000 karakterde kesilir |
| `aud$` | `SYS.AUD$` | Traditional ama tam SQL metni |
| `cursor_cache` | `GV$SQL` + `GV$SQL_BIND_CAPTURE` | Audit gerektirmez, hızlı ön keşif için. Bind'ler ~15 dk'da bir örneklenir, her SQL için tek satır |

## Teknik notlar

- **SQL_ID:** `MD5(sql_text || CHR(0))` özetinin son 8 baytı base32 ile kodlanır. Audit'teki metin
  uygulamanın gönderdiğiyle aynı olduğu için hesaplanan değer V$SQL'deki SQL_ID ile eşleşir.
- **Bind formatı:** audit `#1(4):1001 #2(5):AHMET` şeklinde yazar (`#sıra(uzunluk):değer`). Değer içinde
  boşluk olsa bile uzunluk bilgisiyle doğru ayrıştırılır; çok baytlı karakterler (Ç, Ğ, Ş…) de desteklenir.
- **Eşleştirme:** `:1`, `:B1`, `:isim` ve `?` yer tutucuları (string ve yorum içindekiler hariç) bulunur.
  Aynı isimli bind birden fazla yerde geçiyorsa ve değer sayısı farklı isim sayısına eşitse isimle,
  aksi halde sırayla eşleştirilir.
- **Yerleştirme tipleri:** varsayılan metin (`'değer'`; NUMBER kolonlarda da örtük dönüşümle çalışır).
  Gerekirse satır bazında *Sayı*, *NULL* veya *Ham ifade* (örn. `TO_DATE('17.10.2026','DD.MM.YYYY')`)
  seçilebilir. Tarih bindleri için `nls_date_format` ayarı da kullanılabilir.
- **Güvenlik:** yalnızca `SELECT`/`WITH` çalıştırılır, `SET TRANSACTION READ ONLY` içinde, satır ve süre
  sınırıyla. Uygulama varsayılan olarak yalnızca `127.0.0.1`'den erişilebilir; kimlik doğrulaması yoktur,
  ağa açmayın.
- **Oracle 11g veya Native Network Encryption** zorunluysa thin mode bağlanamayabilir;
  `client_lib_dir` ile Instant Client göstererek thick mode kullanın.

## Geliştirme

```bash
pip install pytest
python -m pytest
```

`siron_tracer/sqlutil.py` veritabanı gerektirmeyen tüm SQL işlemlerini (SQL_ID, bind ayrıştırma,
yerleştirme, tablo çıkarma) içerir; testler sahte bir Oracle ile tüm ekran akışını da dener.
