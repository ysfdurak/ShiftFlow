# Değişiklik günlüğü

## 3.11.2 — 2026-11-23

Denetim bulguları (D12, D16).

- 16 ve daha uzun haneli kodlar (barkod, seri no) CSV'den ve açık Excel'den metin olarak okunur. Önceden sayıya çevriliyor, son hanesi farklı kodlar aynı değere düşüyordu.
- "1.2.34,56" gibi bozuk binlik gruplama artık 1.234,56 sayılmaz; sütun metin kalır, kaynak değer olduğu gibi görünür. Düzgün "1.234,56", "1,234.56", "1.234.567,89" eskisi gibi sayıdır.

## 3.11.1 — 2026-11-22

GitHub deposu açıldı; Windows CI'ın ilk çalışmasında çıkanlar düzeltildi.

- **Örnekle dene** temiz kurulumda da çalışır: sentetik örnek veri artık depoda. Örnek dosyalar eksikse hata kutusu yerine bilgi verilir.
- Outlook kurulu değilse **Outlook'ta taslak aç** ve **Gönder** kapalı gelir; mail .eml olarak kaydedilebilir.
- Kılavuzdaki ekran görüntüleri exe paketinde de var (`tools/ekran_goruntuleri.py` ile yeniden üretilir).
- Excel çıktısında sütun genişliği kalın başlığı, filtre okunu ve binlik ayırıcılı sayıları hesaba katar (gerçek Excel'de "Toplanan", "Hatalı" başlıkları kesiliyordu).
- Gerçek Windows + Excel denemesi: açık Excel'den iki kaynak okundu, rapor 3 sayfa ve grafikle üretildi ve Excel'de açıldı.
- Dönem etiketinde gece yarısı 24:00 olarak yazılır (mail ve dosyada "Tüm gün (00:00–00:00)" görünüyordu).
- pandas 4 için eskiyen çağrılar değiştirildi (`day_of_week`, `read_excel`).
- Testler: takılan test 120 sn'de düşer, beklenmeyen ileti kutusu testi kilitlemez, ayarlar kayıt defterine değil geçici dosyaya yazılır, Windows'ta testler üretilen dosyaları gerçek uygulamada açmaz.
- Lisans: PolyForm Shield 1.0.0. `v*` etiketiyle sürüm paketi (zip + SHA-256) Sürümler sayfasına eklenir.

## 3.11.0 — 2026-11-20

Gerçek Windows bilgisayarda uçtan uca denemeden çıkan düzeltmeler ve sade düzen.

**Düzeltmeler**
- Açık Excel: pywin32'de `Range.Resize(a, b)` tek hücre döndürüyordu; önizleme, rapor tanıma, ▶ Rapor oluştur, paketler, zamanlanmış görev ve formüllü sütun okuma ilk hücrede kalıyordu. `GetResize` kullanılıyor; test sahte Excel'i aynı tuzağı taşıyor.
- Korumalı Görünüm'de açık (e-postadan/internetten gelen) kitaplar listede görünür ("Korumalı Görünüm" notuyla).
- Excel'den gelen tam sayılar tam sayı (1001, 1001.0 değil).
- Dondurulmuş sütun varken tablo yatay kaydırılınca başlık sağ tık menüsü yanlış sütunu açıyordu.
- Excel çıktısında grafik eksenleri görünür (openpyxl eksenleri "silinmiş" yazıyordu).
- Toplam satırı yüzde/oran/ortalama ve kimlik (No, ID, Kod) sütunlarını toplamaz (önceden "Gerçekleşme %" toplamı 385,50 çıkıyordu).
- Personel listesi gibi tarihsiz ana veriler için "son çalıştırmayla aynı veri" uyarısı verilmez.
- Outlook'ta hesap yoksa Outlook açılmaz (kurulum sihirbazında takılıyordu); zamanlanmış çalıştırma .eml'e geçer.
- `calistir.bat`: kurulum hatası ve SSL sorunu (Anaconda) yakalanır, ne yapılacağı yazılır; yarım kurulum sonraki açılışta tamamlanır.
- Qt'nin kendi düğmeleri Türkçe (Tamam, İptal…); açılır listede seçili öğe görünür; tarih alanına klavyeyle yazılabilir.
- Tarih sütunu bölünürken ekrandaki biçim (01.11.2026) kullanılır; mail tablosunda ondalıklar sütun içinde tutarlı; yollar Windows biçiminde; WMS penceresinde biçim etiketleri metin olarak görünmüyor; şeritten açılan adım seçili sütunla gelir; birleştirmede iki tarafta aynı küme seçilemez; çöp kutusundan geri yüklemede onay ve açık sonuç; dosya adı örneği seçili dönemle.

**Sade düzen ve rehber**
- Ayrı üst araç çubuğu kaldırıldı: ▶ Rapor oluştur, dönem, İşlem ara, Geri al/Yinele şerit satırında. Tablonun üstünde iki satır kalır.
- Sütun bilgisi paneli başlangıçta kapalı (Görünüm menüsü veya başlık sağ tık ile açılır).
- Adımlar kısa adla (formül ipucunda); veri kümelerinde uzun rapor adı ipucunda.
- Dönem: "(otomatik)" yazısı ve Otomatik düğmesi yerine yalnız elle değiştirilince çıkan ↺.
- Otomasyon sekmesi başlangıçta gizli (Görünüm → Otomasyon sekmesi).
- Yeni: **Ekran rehberi** (7 adım, ilgili bölüm vurgulanır; ? düğmesi), **Örnekle dene** (sentetik veri + hazır akış, kendi dosyalara dokunmaz), karşılama penceresinde başlangıç seçenekleri, boş ekranda tıklanabilir başlangıç bağlantıları.
- Kılavuza "İlk raporunu 10 dakikada kur" bölümü.

## 3.10.0 — 2026-11-10

- Tarayıcı demosu (`web/`): aynı motor Pyodide ile tarayıcıda çalışır; sunucu gerekmez, veri tarayıcıdan çıkmaz.
  - Örnek akışı tek tıkla kurma (sentetik vardiya verisi + personel listesi), kendi CSV/XLSX dosyasını yükleme.
  - Adım ekleme (filtre, sırala, metin temizle, yazımı birleştir, sütun kaldır, tekrarları kaldır, hesapla, EĞER, DÜŞEYARA, doğrula, grupla, pivot), adımda önizleme, aç/kapa, taşı, sil, geri al/yinele.
  - Farklı yazılış uyarısı ve düzeltme; hatalı adımın reddedilip önerinin gösterilmesi; "Raporu durdur" doğrulaması.
  - "Yeni günün verisiyle çalıştır": aynı adımlar ertesi günün verisiyle.
  - Biçimli Excel indirme (toplam satırı), akış tanımını JSON indirme.
- `web/build_web.py` yayın klasörünü üretir; `web/README_WEB.md` Cloudflare Pages yayın kılavuzu ve ilk deneme listesi.
- Önizlemede baştaki/sondaki boşluklar görünür işaretlenir.

## 3.9.0 — 2026-11-10

- Komut satırı modu: `--paket` / `--akis`, `--donem otomatik|tarih:vardiya`, `--mail outlook|eml|yok`; pencere açmadan çalışır, günlük dosyası, çakışma kilidi, sorun olursa uyarı taslağı. Mail asla gönderilmez.
- Zamanlanmış görev penceresi: vardiya bitişlerine göre Windows Görev Zamanlayıcı komutları, "Şimdi bir kez dene", görevleri oluşturma.
- WMS ekran teşhisi: masaüstü WMS penceresinin ekran otomasyonuna uygunluğunu ölçer (yalnız okur, alan içeriği ve tablo verisi kaydedilmez).
- Outlook taslağını Taslaklar klasörüne kaydetme.
- Yeni "Otomasyon" sekmesi.

## 3.8.0 — 2026-11-10

- Çöp kutusu (30 gün): silinen rapor tanımları, referans tablolar, arşiv dönemleri/kümeleri ve üzerine yazılan kayıtlar (eski referans içeriği, yeniden oluşturulan dönemin eski hâli) geri yüklenebilir.
- Sütun dondurma: soldaki sütunlar yatay kaydırmada sabit kalır.

## 3.7.0 — 2026-11-10

- Rapor paketleri: birden çok iş akışını aynı dönem için sırayla çalıştırma; sorunlu akış atlanır ve özette yazılır; isteğe bağlı tek mail (tüm çıktılar ekte).
- Klasörden çoklu dosya: desene uyan tüm dosyalar alt alta, "Kaynak dosya" sütunuyla; her çalıştırmada klasör yeniden taranır.
- Excel çıktısında toplam satırı (ALTTOPLAM) ve koşullu renk (Excel'in kendi koşullu biçimi; parametreyle).
- Excel'de aç: seçili tabloyu kaydetmeden geçici dosyayla Excel'de açma.
- Gösterge paneli: sayı, sütun/çubuk/çizgi grafiği ve tablo kutucukları; iş akışıyla kaydedilir; PNG olarak kaydetme.
- Değer dağılımı: sütunun en sık değerleri ve özeti; değere çift tıklayarak filtre.
- "Sütun bulunamadı" mesajında en yakın sütun önerisi.

## 3.6.0 — 2026-11-10

- Formüller yalnız dolu satırlara uygulanır: Excel'de aşağı çekilmiş formüllerin ürettiği boş satırlar atılır ("Boş satırları kaldır" adımı); Hesapla'da "Yalnız dolu satırlar" seçeneği.
- Excel gibi sekmeli şerit: Giriş, Dönüştür, Temizle, Formül, Özet ve birleştir, Rapor; dar ekranda (1366) hiçbir düğme gizlenmez.
- Tabloda Ctrl+F ile bul; başlıkta ▾ filtre oku; sütunu yalnız görünümde gizleme.
- Uygulama içi kılavuz (F1, işleme göre bölüm, arama) ve ilk açılış rehberi.
- Koşullu sütun ve kural değerlerinde büyük formül düzenleyici (…).
- Pivot ve Grupla: tarihleri saat/gün/hafta/ay/yıl/haftanın günü olarak gruplama, yüzde gösterimi, değere göre sıralama, ilk N; pivotta alanları sürükle-bırak.
- Doğrula adımı: boş, tekrar, satır sayısı, aralık ve formül kontrolleri; "Uyar" veya "Raporu durdur".
- Durum çubuğundaki satır/sütun bilgisi tablo altında tekrar edilmiyor.

## 3.5.0 — 2026-11-10

**Güvenli kullanım**
- Uzun işlemler arka planda: pencere donmaz, ilerleme penceresi ve İptal (yarım değişiklik geri alınır).
- Otomatik yedek ve çökme sonrası kurtarma (veriler dahil, yalnız bu bilgisayarda).
- Adımı silmeden geçici kapatma (onay kutusu), adım notu, adım kopyası.

**Veri doğruluğu**
- Aynı değerin boşluk/harf farkıyla farklı yazılışları (filtre, gruplama, pivot, tekrar, karşılaştırma) uyarılır ve düzeltme sorulur; "Yazımı birleştir" adımı.

**Excel'den taşıma**
- Excel'deki formüllü sütunları tek seferde alma (açık Excel veya .xlsx), Excel değerleriyle karşılaştırma, yüklenmemiş sayfayı aynı kitaptan tek tıkla yükleme.
- Formül kutusuna Excel formülü yapıştırınca otomatik çeviri.
- "Excel'e bırak": karşılığı olmayan formül çıktıya Excel formülü olarak yazılır.
- Formülde kullanılan sütunlar renkli (formülde, önizleme başlığında, sütun listesinde).
- 24 yeni fonksiyon: ÇOKEĞERORTALAMA, MAKEĞER, MİNEĞER, BUL, MBUL, DEĞİŞTİR, YİNELE, METİNBİRLEŞTİR, ÖZDEŞ, ESAYIYSA, EMETİNSE, SEÇ, KAREKÖK, ÇARPIM, ORTANCA, BAĞ_DEĞ_SAY, BAĞ_DEĞ_DOLU_SAY, ZAMAN, SERİTARİH, SERİAY, İŞGÜNÜ, TAMİŞGÜNÜ, ETARİHLİ, TARİHSAYISI.
- Satırlar arası hesap: ÖNCEKİ, SONRAKİ, KÜMÜLATİF, SIRA (grup içinde de); çevirici `D3-D2`, `TOPLA($D$2:D2)`, `EĞERSAY($A$2:A2;A2)`, `RANK` kalıplarını tanır.
- İş akışı parametreleri (`{Hedef Oran}`); Excel'deki `$H$1` sabit hücreleri parametreye bağlama.

**Yeni adımlar**
- Aşağı doldur, Boşları doldur, Sütunlara böl, Sütunları satırlara çevir.

**Düzeltmeler**
- Formül önerilerinde IF/EĞER gibi adların iki kez görünmesi.
- SOLDAN/SAĞDAN/PARÇAAL satıra göre değişen karakter sayısıyla çalışıyor.
- Tarih + ZAMAN toplamında nanosaniye kayması.

## 3.4.0 — 2026-11-10

- Formül düzenleyici: çok satırlı kutu, renklendirme, parantez eşi vurgusu, fonksiyon ve sütun önerileri, imleçteki fonksiyonun yazımı.
- Düzenle (Ctrl+Shift+F) / Tek satır: iç içe formülleri girintili gösterir; uzun Excel formülleri yapıştırılınca otomatik düzenlenir.
- Seçimi dene: formülün seçili parçasının sonucu önizlenir.
- Hatanın yeri işaretlenir (satır, karakter); kapanmamış parantezde ilgili fonksiyon adı söylenir.
- Hesapla penceresi yeniden düzenlendi (formül tam genişlikte, sütun ve fonksiyon listeleri altta).
- `docs/DEGERLENDIRME.md`: kullanılabilirlik ve işlevsellik değerlendirmesi, öncelikli eksik listesi.

## 3.3.0 — 2026-11-10

- Formülde tablo fonksiyonları: DÜŞEYARA, ÇAPRAZARA, EĞERSAY, ÇOKEĞERSAY, ETOPLA, ÇOKETOPLA, ORTALAMAEĞER, TABLOTOPLA/SAY/ORT/MAK/MİN; ayrıca ÇOKEĞER, METNEÇEVİR, EĞERYOKSA. Tek formülde iç içe kullanılabilir; başvurulan tablolar bağımlılık olarak izlenir.
- Excel formülü çevirici: hücre/sayfa başvurularını sütun/tablo adlarına çevirir; DÜŞEYARA, İNDİS+KAÇINCI, ÇAPRAZARA, EĞERSAY/ETOPLA aileleri, TOPLA(D:D), TOPLA(D2:F2) kalıpları; Türkçe ve İngilizce Excel; çevrilemeyenleri uyarır.
- İşlem ara (Ctrl+K): yazdıkça işlemleri süzen liste; eş anlamlılar, Türkçe karaktersiz arama, seçili sütuna uygun hazır formüller.
- Tablo yeniden adlandırılınca formüllerdeki tablo adı da güncellenir.

## 3.2.0 — 2026-11-10

**Excel alışkanlıkları**
- Formül fonksiyonları (Türkçe/İngilizce): EĞER, VE, YADA, DEĞİL, EĞERHATA, EBOŞSA, YUVARLA, YUKARIYUVARLA, AŞAĞIYUVARLA, MUTLAK, TAMSAYI, MOD, MAK, MİN, TOPLA, ORTALAMA, SOLDAN, SAĞDAN, PARÇAAL, UZUNLUK, KIRP, BÜYÜKHARF, KÜÇÜKHARF, YAZIMDÜZENİ, BİRLEŞTİR, YERİNEKOY, SAYIYAÇEVİR, YIL, AY, GÜN, SAAT, DAKİKA, HAFTANINGÜNÜ, HAFTASAY, BUGÜN, ŞİMDİ, TARİH; karşılaştırma işleçleri, `^`, tarih farkı.
- Eşleştir (DÜŞEYARA) adımı: satır sayısı değişmez, harf duyarsız, eksik/tekrar raporu.
- Kural tablosu adımı; koşullarda sütunla sütun karşılaştırma (`[Hedef]`).
- Referans tablolar: bir kez kaydedilen sabit tablolar, her çalıştırmada otomatik kullanılır.

**Vardiya ve geçmiş**
- Vardiya tanımları; araç çubuğunda dönem seçimi (varsayılan saatten otomatik, elle değiştirilebilir).
- Dönem filtresi adımı.
- Rapor arşivi: dönem bazında yazma/değiştirme; arşivden önceki vardiya, dünün aynı vardiyası, önceki N gün, bu ay, tarih aralığı.
- "Aynı veri" kuralı dönemleri dikkate alıyor (günlük tek rapor + vardiya filtresi yanlış alarm vermez).

**Çıktı ve mail**
- Excel çıktısına gerçek Excel grafikleri; sayı/tarih biçimleri.
- Kendi Excel şablonuna yazma (biçim ve formüller korunur), şablon hücrelerine dönem bilgisi.
- Vardiya maili: çoklu alıcı, vardiyaya göre ek alıcı, mail içinde özet tablo, Excel eki; Outlook taslağı veya onaylı gönderim; .eml yedeği.
- Dosya adında {vardiya}; {tarih} artık seçili dönemin tarihi.
- İş akışı biçimi 3 (eski dosyalar otomatik dönüştürülür).

## 3.1.0 — 2026-11-10

**Açık raporları tanıma ve tek tıkla rapor oluşturma**
- Rapor tanımları: rapor bir kez tanımlanır ve yerel kütüphanede (SQLite) saklanır. Tanıma sütun başlıklarıyla yapılır; kitap/sayfa adı ipucu isteğe bağlıdır.
- Açık Excel kitaplarını listeleme (kaydedilmemişler dahil, Windows COM), başlık satırını otomatik bulma (üstteki başlık satırları atlanır).
- ▶ Rapor oluştur (F9): açık raporları bul → kontrol et → çalıştır → çıktı klasörüne tarihli dosya yaz. Sorun yoksa ek pencere açılmaz.
- Değişiklik yakalama: eksik/yeni/yazımı farklı/tipi değişen sütun, sütun sırası, iki uygun rapor, rapor bulunamadı, son çalıştırmayla aynı veri.
- Sütun eşlemeleri rapor tanımına öğretilir; aynı raporu kullanan tüm iş akışları yararlanır.
- Hatalı veri kümesi varsa çıktı yazılmaz. Çalıştırma geçmişi tutulur.
- İş akışı biçimi 2: rapor bağlantısı, çıktı ayarları, gömülü tanımlar (başka bilgisayara taşınabilir). Biçim 1 dosyaları otomatik dönüştürülür.

**Düzeltmeler**
- `01.11.2026` gibi metin tarihler kod sanılıp metin kalıyordu; artık tarih olarak tanınıyor. Çok noktalı değerler yalnızca 3'lü binlik gruplarıysa sayı sayılıyor.
- Yalnızca veri yenilendiğinde iş akışı "değişti" olarak işaretlenmiyor.

## 3.0.0 — 2026-11-10

Önceki V1/V2 prototipleri ve Excel Asistanı tek ürün olarak ShiftFlow altında toplandı. Kod sıfırdan yazıldı; V1/V2 kapsamı korunup genişletildi.

**Mimari**
- Arayüzden bağımsız motor (`shiftflow/engine`), Qt olmadan test edilebilir.
- Veri kümeleri arasında DAG, veri kümesi içinde doğrusal adımlar; döngü kontrolü.
- İmza tabanlı önbellek; geri al/yinele yeniden hesaplama gerektirmez.
- Her değişiklik önce denenir; yeni hata çıkarsa (bağlı veri kümeleri dahil) geri alınır.
- Sürümlü JSON biçimi (`schema_version`), sürüm geçiş altyapısı.

**Yeni**
- Sanal tablo modeli (milyon satır), Türkçe sayı/tarih gösterimi, seçimde Toplam/Ortalama.
- Sütun başlığı ve hücre sağ tık menüleri; Excel benzeri değer listesi filtresi.
- Tüm işlemlerde canlı önizleme.
- Adım düzenleme, silme, sıra değiştirme (bağımlılık kontrolüyle); ara sonuç görüntüleme ve araya adım ekleme.
- Formül dili: `[Sütun]`, `+ - * / ( )`, `&` metin birleştirme; koşullu sütun (EĞER).
- Tip dönüştürme, metin temizleme (Türkçe i/İ), bul-değiştir, tekrar kaldırma.
- Birleştirmede tanı bilgisi, çoktan-çoğa onayı, boş ve tipi farklı anahtar koruması, eşleşme durumu sütunu, çok anahtar.
- Çok alanlı ve çok değerli pivot, genel toplam, "(Boş)" grubu.
- Yeni raporla çalıştırma: kayıtlı yollardan yükleme, sütun eşleme önerisi, tip değişikliği uyarısı.
- Kayıtlı çıktı listesi (çok sayfalı Excel); kaynak dosyanın üzerine yazma koruması.
- calamine ile hızlı Excel okuma; PySide6-Essentials ile daha küçük paket.
- Windows için GitHub Actions: test, .exe, açılış kontrolü.
