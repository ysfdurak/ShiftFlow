# Test durumu (sürüm 3.10.0)

Bu belge neyin nerede ve nasıl test edildiğini dürüstçe gösterir. Gerçek Windows kullanıcı testi henüz yapılmadı. Açık Excel'den formül okuma (COM `Range.Formula`) ve Excel'e bırakılan formüllerin gerçek Excel'de hesaplanması da Windows'ta denenmeli.

## Yapılanlar

| Alan | Ortam | Sonuç |
|---|---|---|
| Motor testleri (işlemler, birleştirme, pivot, iş akışı, JSON, okuma/yazma) | Linux, Python 3.13, pandas 3.0 | Tüm takım: 395 test geçti |
| Aynı motor testleri | Linux, pandas 2.2 | 238 motor testi geçti |
| Arayüz testleri (gerçek diyaloglar ve pencere akışları, ekransız Qt) | Linux, PySide6 6.12 | (331 içinde) geçti |
| Ekran görüntüleriyle görsel kontrol | Linux, ekransız Qt | Ana pencere, ara sonuç, birleştirme, pivot ve filtre ekranları incelendi |
| Uçtan uca örnek: 1. gün → kaydet → 3. gün (sütun adı değişmiş) → eşleme → çıktı | Linux | Hatasız; 4 sayfalı Excel üretildi |
| Performans: 500 bin satırda hesapla, filtre, birleştir, pivot | Linux | Her adım < 0,2 sn; arayüz yenileme 0,06 sn; ~380 MB bellek |
| Okuma: 200 bin satırlık .xlsx | Linux (calamine) | 2,8 sn |
| Yapıştırma: 300 bin satır | Linux | 1,6 sn |
| Açık rapor tanıma ve Rapor oluştur: başlık satırı bulma, kaydedilmemiş kitap, iki aday, rapor yok, sütun adı değişmiş + eşlemeyi öğrenme, bayat veri, hatada dosya yazmama, dosyaya geri dönüş, başka PC'de tanım aktarımı | Linux, **sahte Excel nesneleriyle** | 21 motor + 10 arayüz testi geçti |
| Örnek iş akışıyla (gömülü tanımlar) açılış → açık raporlardan yükleme → tek tıkla 4 sayfalı çıktı | Linux, sahte Excel | Hatasız |
| Formül fonksiyonları, DÜŞEYARA, kural tablosu, referans tablolar (motor + arayüz) | Linux | Geçti |
| Vardiya/dönem hesabı (gece yarısını geçen vardiya dahil), dönem filtresi, arşiv (yazma, değiştirme, aralıklar), önceki vardiya karşılaştırması, "aynı veri" kuralı | Linux | Geçti |
| Excel grafiği (XML'de seri ve aralık kontrolü, LibreOffice ile görsel kontrol), şablona yazma (biçim ve formül korunuyor) | Linux | Geçti |
| Mail taslağı, .eml (X-Unsent), Outlook taslak/gönder (**sahte Outlook nesnesiyle**), onaysız gönderim olmaması | Linux | Geçti |
| İkinci örnek (vardiya sonu raporu): Gece ve Gündüz için çalıştırma, arşiv, mail taslağı | Linux, dosya sağlayıcısı | Hatasız |
| Formülde DÜŞEYARA, ÇAPRAZARA, EĞERSAY/ETOPLA aileleri, TABLO* fonksiyonları, iç içe kullanım, bağımlılık ve yeniden adlandırma | Linux | Geçti |
| Excel formülü çevirici: 10 örnek kalıp (TR/EN yazım, sayfa adları, İNDİS+KAÇINCI, ÇOKETOPLA, satır aralığı, yüzde) ve uyarı durumları; çevrilen formülün uçtan uca çalışması | Linux | Geçti |
| İşlem arama (Ctrl+K): eş anlamlılar, Türkçe karaktersiz arama, sütuna göre öneriler, klavye | Linux | Geçti |
| Formül düzenleyici: konumlu hata, kapanmamış parantez sahibi, biçimle/tek satır (sonuç değişmiyor), imleçteki fonksiyon yazımı, öneri listesi, seçimi dene | Linux, ekransız Qt | Geçti |
| Farklı yazılış (boşluk/harf) uyarısı ve düzeltme: filtre, tekrar, gruplama, formül; "düzelt / şimdi değil / sorma" seçenekleri; geri al | Linux, ekransız Qt | Geçti |
| Arka plan görevi: olay döngüsü işliyor, ilerleme penceresi adım adını gösteriyor, İptal'e tıklama değişikliği geri alıyor, dışarıdaki tıklamalar engelleniyor | Linux, ekransız Qt | Geçti; tam test takımı art arda 6 kez çökmesiz |
| Otomatik yedek: yazma, değişmeyen verinin yeniden yazılmaması, bozuk yedek, pencereden geri yükleme, kaydedince silinme | Linux | Geçti |
| Adım aç/kapa, not, kopya (JSON'da korunuyor; gerekli adımı kapatma reddediliyor) | Linux | Geçti |
| 24 yeni fonksiyon, satırlar arası fonksiyonlar, parametreler; çevirici kalıpları (`D3-D2`, `TOPLA($D$2:D2)`, `RANK`, MAXIFS, FIND…) | Linux | Geçti |
| Excel'deki formüllü sütunlar: .xlsx dosyasından ve **sahte COM nesnesiyle** okuma, başlık bulma, kalıp değişikliği uyarısı, Excel değerleriyle karşılaştırma, eksik sayfayı yükleme, parametre önerisi | Linux | Geçti |
| Excel'e bırak: şablon, sıralama ve sütun taşımadan sonra doğru adres, kapalı adım; formüllerin LibreOffice'te hesaplandığı görsel kontrol | Linux | Geçti |
| Aşağı doldur, boşları doldur, sütunlara böl, satırlara çevir | Linux | Geçti |
| Dolu satır kuralı (aşağı çekilmiş formüller, ertesi gün farklı satır sayısı), Doğrula (5 kontrol, durdurma yalnız çıktıda), pivot tarih gruplama / yüzde / ilk N, sürükle-bırak benzetimi, şerit 1366'da sığıyor, Ctrl+F, görünümde gizleme, yardım bölümleri | Linux, ekransız Qt | Geçti |
| Klasör kaynağı (birleşim, kilit dosyaları, yeni dosyanın gelmesi, Rapor oluştur), rapor paketi (atlanan akış, durdurma, birleşik mail, pencere), toplam satırı ve koşullu renk (LibreOffice'te hesaplama kontrolü), Excel'de aç, gösterge paneli (hesap, kayıt, pencere), değer dağılımı, sütun önerisi | Linux, ekransız Qt | Geçti |
| Çöp kutusu (rapor tanımı, referans tablo ve eski içeriği, arşiv dönemi/kümesi/değiştirilen dönem; ad çakışması; temizleme; pencereden geri yükleme), sütun dondurma | Linux, ekransız Qt | Geçti |
| Komut satırı (tek akış, paket, otomatik dönem, Outlook taslağı — **sahte Outlook ile**, asla gönderim yok, hatalı girdiler, kilit), Görev Zamanlayıcı komutları, WMS teşhisi — **sahte pencere ağaçlarıyla** (.NET benzeri uygun, Java adsız uygun değil, veri değerlerinin rapora girmemesi) | Linux | Geçti |
| Tarayıcı demosu köprüsü (`web/sfweb.py`): örnek akış, farklı yazılış düzeltme, hatalı adımın reddi, durdurma doğrulaması, ertesi gün, geri al, CSV/XLSX yükleme, Excel çıktısı, Windows modülleri olmadan yayın zip'inden içe aktarma | Linux, Python 3.13 | 10 test geçti |
| Tarayıcı demosu arayüzü uçtan uca: giriş, örnek akış, uyarı ve düzeltme, adım önizleme, hatalı formül, sütun çipleri, filtre, geri al, aç/kapa, ertesi gün, grupla, durdurma, Excel indirme, dosya yükleme, çok sayfalı XLSX, telefon görünümü | Gerçek Chrome + Playwright, **geliştirme sunucusuyla** (Pyodide yerine aynı köprü normal Python'da) | Geçti; konsolda hata yok |
| Tarayıcı demosu, **gerçek Pyodide 314.0.8** (yayın klasörü, `_headers` ve sıkı CSP ile): açılış (~7 sn), örnek akış, düzeltme, hatalı formül, filtre, geri al, ertesi gün, grupla, durdurma, Excel indirme (5 sayfa, ALTTOPLAM), Türkçe CSV, çok sayfalı XLSX (sayfa seçimi), telefon görünümü; dış adrese istek yok, yükleme/aktarma sırasında ağ isteği yok | Chrome + Playwright (`e2e_test.py --pyodide`), her PR'da GitHub Actions | Geçti; konsol hatası ve CSP ihlali yok |
| PyInstaller paketi | Linux | Paket oluştu ve açıldı (Windows paketi değil) |

Testi yapılan özel durumlar: eksik sütun, tekrar eden anahtar, çoktan-çoğa onayı, boş anahtar, anahtar tipi farkı (1 / "1"), hiç eşleşmeme, aynı adlı sütun çakışması, sıfıra bölme, boş tablo, tip uyuşmazlığı, Türkçe sayı biçimi, cp1254 ve `;` ayırıcılı CSV, başında sıfır olan kodlar, tekrar eden veya boş başlıklar, pandas NA değerleri, kaynak dosyanın değişmediği (dosya özeti karşılaştırması), kaynak dosyanın üzerine yazmayı reddetme, döngüsel bağımlılık, bozuk veya yabancı JSON, daha yeni sürümlü JSON.

## Yapılmayanlar

- **Gerçek Excel'e bağlantı (COM):** `ComExcelProvider` gerçek Excel ile hiç çalıştırılmadı. Kodun Windows'a özgü olmayan kısmı sahte nesnelerle test edildi. Windows'ta özellikle doğrulanması gerekenler:
  1. Kaydedilmemiş kitapların listelenmesi.
  2. WMS'in **ayrı bir Excel penceresinde** açtığı kitabın bulunması (ROT taraması).
  3. Tarih hücrelerinin doğru gelmesi.
  4. Excel meşgulken verilen mesaj.
  5. Büyük sayfaların okunma süresi.

  GitHub'ın Windows makinelerinde Excel kurulu olmadığı için bu kısım otomatik testle de doğrulanamaz.
- **Gerçek Outlook (COM):** `OutlookMailer` gerçek Outlook ile hiç çalıştırılmadı. Doğrulanması gerekenler: taslağın açılması, HTML tablonun Outlook'ta görünümü, ekin eklenmesi, "Gönder"in kurumsal güvenlik uyarısına takılıp takılmadığı. Bazı şirketlerde Outlook, programın mail göndermesine izin vermeden önce uyarı gösterir; bu durumda "taslak olarak aç" yolu kullanılmalı.
- **Şablon:** Gerçek bir kurumsal şablonla denenmedi.

- **Windows'ta gerçek kullanım:** Uygulama Windows'ta açılıp elle denenmedi. Yazı tipi, ölçekleme (yüksek DPI), dosya diyalogları ve Türkçe karakterli dosya yolları Windows'ta doğrulanmalı.
- **Windows .exe:** Burada üretilemedi. `exe_olustur.bat` veya GitHub Actions ile üretilecek. Actions akışı testleri Windows'ta çalıştırır ve .exe'nin açılıp çökmediğini kontrol eder; bu da elle kullanım testinin yerini tutmaz.
- **Gerçek WMS raporları:** Yalnız sentetik raporlarla denendi. Birleştirilmiş hücreli, üstte başlık bloğu olan veya birden çok tablolu sayfalar henüz desteklenmiyor.
- **.xls (eski Excel):** Kod destekliyor ancak test edilmedi.
- **Tarayıcı demosu Firefox/Safari'de ve gerçek telefonda:** Otomatik test yalnız Chrome'da; diğer tarayıcılarda elle bakılmalı.

## Bilinen sınırlar

- Hesaplamalar arayüz iş parçacığında çalışır. Çok büyük dosyalarda pencere kısa süre "yanıt vermiyor" görünebilir (bekleme imleci gösterilir).
- Raporun altında "Toplam" gibi özet satırları varsa veri satırı olarak okunur. Filtreyle çıkarılmalıdır (örn. "Personel No boş değildir").
- Bir sayfada birden çok tablo varsa yalnızca başlığı bulunan tablo ve altı okunur.
- Rapor oluşturma, WMS'ten raporu **almaz**; raporların açık olması gerekir (RPA sonraki aşamada).
- Tabloda hücre elle düzenlenemez (bilinçli karar; bkz. açık sorular).
- Tek seferde yalnızca bir iş akışı açık olabilir; rapor paketleri sonraki aşamada.
- Ara sonuç seçiliyken eklenen pivot/gruplama, ara sonucu değil veri kümesinin son sonucunu kullanır (kullanıcıya bildirilir).

## Windows'ta ilk deneme için önerilen kontrol listesi

1. `calistir.bat` ile açılıyor mu?
2. `ornekler\ornek_veri_olustur.py` ile veri üretip **Dosya aç** ile alın; Türkçe karakterler ve sayılar doğru görünüyor mu?
3. Excel'den 10-20 satır kopyalayıp Ctrl+V ile yapıştırın.
4. Sütun başlığına sağ tıklayıp filtre, sıralama ve yeniden adlandırma deneyin; Ctrl+Z ile geri alın.
5. İki kaynağı birleştirin, pivot oluşturun, Excel'e aktarın; çıktıyı Excel'de açın.
6. Akışı kaydedin, uygulamayı kapatın, akışı açıp **Kayıtlı yollardan yükle** ile çalıştırın.
7. `--gun 3 --bicim-degisik` raporu ile sütun eşleme penceresini deneyin.
8. **Açık Excel:** Örnek raporu Excel'de açın (veya kopyalayıp yeni bir kitaba yapıştırıp kaydetmeden bırakın). **Açık Excel'den al** listesinde görünüyor mu? "(kaydedilmemiş)" etiketi doğru mu?
9. **Rapor oluştur:** `ornekler\ornek_is_akisi.json` dosyasını açın; iki örnek raporu Excel'de açık tutun. **▶ Rapor oluştur** (F9) → çıktı ayarlarını girin → dosya oluşup açılıyor mu?
10. Aynı raporlarla tekrar F9 → "son çalıştırmayla aynı veri" uyarısı geliyor mu? Excel'de `Toplanan Adet` başlığını değiştirip F9 → sütun eşleme ekranı geliyor mu?
11. WMS'ten gerçek bir raporu açıp **Rapor olarak tanımla…**; ertesi gün F9 ile tanınıyor mu?
12. **Vardiya senaryosu:** `ornekler\ornek_vardiya_akisi.json` dosyasını açın. Örnek raporlar Excel'de açık olsun. Dönemi **01.11.2026 · Gece** seçip F9; çıktıda grafik var mı, mail önizlemesi açılıyor mu, "Outlook'ta taslak olarak aç" çalışıyor mu? Sonra **Gündüz** seçip tekrar F9; **Arşiv** penceresinde iki dönem görünüyor mu?
13. **Referans tablo ve DÜŞEYARA:** Kendi lokasyon veya ürün listenizi referans tablo olarak kaydedip bir raporla eşleştirin.
14. **Excel formülü:** Kendi raporunuzdan en uzun formülü kopyalayıp **Excel formülünden sütun…** penceresine yapıştırın; çeviri ve önizleme Excel'deki sonuçla aynı mı?
15. **Ctrl+K:** Bir sütun seçip Ctrl+K ile "pay", "boş", "düşeyara" arayın.
16. **Formüllü sütunlar (3.5):** Formüllü sütunları olan bir raporu Excel'de açık tutun, kaynak tabloyu seçip **İşlemler → Excel'deki formüllü sütunları al…**. Bulunan sütunlar ve "Excel ile uyum" oranı doğru mu? Başka sayfaya DÜŞEYARA yapan formülde **Bu kitaptan yükle** çalışıyor mu?
17. **Excel'e bırak:** DOLAYLI veya TOPLA.ÇARPIM içeren bir formülü "Excel'e bırak" ile ekleyip çıktıyı Excel'de açın; formüller hesaplanıyor mu?
18. **Uzun işlem ve İptal:** 200 bin satırlık bir raporda pivot veya birleştirme ekleyin; ilerleme penceresi çıkıyor mu, İptal çalışıyor mu?
19. **Şerit ve yardım (3.6):** 1366 genişlikte tüm sekmeler sığıyor mu? F1 kılavuzu açıyor mu (exe paketinde de)?
20. **Kurtarma:** Bir iş akışında birkaç adım ekleyin, kaydetmeden Görev Yöneticisi'nden ShiftFlow'u kapatın, yeniden açın: "Kurtarılmış iş akışı" önerisi geliyor mu?
21. **Paket ve panel (3.7):** İki iş akışını pakete ekleyip F9 yerine paketi çalıştırın; çıktılar ve tek mail doğru mu? Gösterge panelini arşiv aralığıyla deneyin. Çıktıdaki koşullu renk gerçek Excel'de görünüyor mu?
22. **WMS teşhisi (3.9):** WMS'te rapor filtre penceresini açıp Otomasyon → WMS ekranını incele. Sonuç ve özet (Özeti kopyala) paylaşılırsa ekran otomasyonu planlanır.
23. **Zamanlanmış görev (3.9):** Bir paket için 'Şimdi bir kez dene', sonra 'Görevleri oluştur'; vardiya bitiminden sonra çıktı ve Outlook taslağı oluşuyor mu? Günlük dosyasını kontrol edin.
24. Kendi gerçek raporunuzu deneyin (veri bilgisayarınızdan çıkmaz) ve sorunları not edin.
