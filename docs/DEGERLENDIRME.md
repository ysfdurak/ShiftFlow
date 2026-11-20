# ShiftFlow — Kullanılabilirlik ve işlevsellik değerlendirmesi

> **3.5.0'da kapatılanlar:** K2 (arka plan + İptal), K3 (otomatik yedek), Y3 (adım aç/kapa, not, kopya), F1 (aşağı doldur, böl, satırlara çevir, boşları doldur), F2 (ÖNCEKİ, KÜMÜLATİF, SIRA), F3 (parametreler) ve ayrıca: boşluk/harf farkı uyarısı, 24 yeni fonksiyon, formüllü sütunları tek seferde alma, yapıştırınca çeviri, eksik sayfayı tek tıkla yükleme, Excel'e bırak, renkli sütunlar.
>
> **3.6.0'da kapatılanlar:** Y1 (şerit), Y2 (Ctrl+F, ▾ filtre oku, görünümde gizleme; sütun dondurma yapılmadı), Y4 (F1 yardım, ilk açılış rehberi), Y5, Y6, F4 (tarih gruplama, yüzde, ilk N, sürükle-bırak), F5 (Doğrula), dolu satır kuralı.
>
> **3.7.0'da kapatılanlar:** O1 rapor paketleri, O2 klasörden çoklu dosya, O3 toplam satırı ve koşullu renk, O4 Excel'de aç (geçici dosya), O6 değer dağılımı, O7 sütun adı önerisi, program içi gösterge paneli.
>
> **3.8.0'da kapatılanlar:** O5 (çöp kutusu), sütun dondurma. Değerlendirme listesindeki tüm maddeler kapandı.
>
> **Kalan:** K1 (gerçek Windows testi) ve sonraki aşamalar: zamanlanmış çalıştırma, WMS RPA, çok kullanıcı (sunucu/VPS).

İlk değerlendirme: sürüm 3.4

**Tarih:** 10.11.2026

**Yöntem:**
- Uygulama tipik bir dizüstü ekranında (1366×768) ve geniş ekranda açılıp örnek senaryolar baştan sona yürütüldü; ekran görüntüleri incelendi.
- Kod, eksiklikler için tarandı.
- Proje şartnamesinin (bölüm 4–16) maddeleriyle karşılaştırıldı.

**Sınır:** Windows'ta gerçek kullanıcı testi yapılmadı. Aşağıdakiler bu bilgisayardaki gözlemler ve kod incelemesidir.

Efor: **S** = birkaç saat · **M** = bir-iki gün · **L** = birkaç gün ve üzeri.

## Güçlü yanlar (korunmalı)

- Her işlemde canlı önizleme; hatalı değişiklik uygulanmıyor, sebebi Türkçe ve anlaşılır.
- Kaynak dosya hiçbir zaman değişmiyor; hatalı veri kümesi varsa çıktı yazılmıyor.
- Excel alışkanlıkları korunuyor: formül dili, DÜŞEYARA/EĞERSAY, Excel formülü çevirici, Ctrl+C, seçimde toplam/ortalama.
- Değişiklik yakalama güçlü: sütun eşleme ve öğrenme, "yenilenmemiş rapor" kontrolü, birleştirme tanısı.
- Motor arayüzden bağımsız; 230'a yakın otomatik test var.

## Kritik — gerçek kullanıma geçmeden

| No | Eksik | Neden önemli | Öneri | Efor |
|---|---|---|---|---|
| K1 | **Windows'ta gerçek test yok** (Excel COM, Outlook COM, .exe, yüksek DPI, Türkçe dosya yolları) | En riskli kısımlar (açık Excel'i okuma, mail) hiç gerçek ortamda çalışmadı | Windows'ta kontrol listesiyle deneme (`TEST_DURUMU.md`). Bağlı bilgisayarda birlikte de denenebilir | M |
| K2 | **Uzun işlemlerde pencere donuyor** | Hesaplama ve dosya/Excel okuma arayüz iş parçacığında. Büyük bir WMS raporunda pencere "yanıt vermiyor" görünür; kullanıcı programın çöktüğünü sanıp kapatabilir | Okuma, Rapor oluştur ve dışa aktarma arka planda çalışsın; ilerleme çubuğu ve İptal düğmesi | M |
| K3 | **Otomatik kayıt / çökme sonrası kurtarma yok** | Kaydedilmemiş iş akışı (20 adımlık emek) bir çökmede kaybolur | Birkaç dakikada bir ve her değişiklikte gizli yedek; açılışta "kurtarılmış iş akışı var" önerisi | S |

## Yüksek — kullanım kolaylığı

| No | Eksik | Gözlem | Öneri | Efor |
|---|---|---|---|---|
| Y1 | **Araç çubukları dar ekrana sığmıyor** | 1366 genişlikte Referans tablolar, Arşiv, Geri al, Yinele, Alt alta ekle, Grupla ve Pivot görünmüyor. Toplam 30'a yakın yazı düğmesi var, simge yok | Excel gibi sekmeli şerit: **Giriş** (veri al, kaydet, geri al) · **Dönüştür** (filtre, sırala, sütunlar, temizle) · **Formül** (hesapla, koşullu, kurallar, DÜŞEYARA) · **Özet** (grupla, pivot, birleştir) · **Rapor** (rapor oluştur, dönem, arşiv, ayarlar). Simgelerle | M |
| Y2 | **Tabloda arama ve görünüm araçları eksik** | Ctrl+F yok. Sütun gizleme, dondurma ve genişlik hatırlama yok. Excel'deki başlık filtre oku yok (sağ tık var ama keşfedilmesi zor) | Ctrl+F ile değer bul ve sonraki/önceki; görünüm amaçlı sütun gizle/dondur (adım oluşturmadan); başlıkta küçük ▾ filtre düğmesi | M |
| Y3 | **Adım geçici olarak kapatılamıyor, not eklenemiyor** | Bir adımın etkisini görmek için silmek gerekiyor. Uzun iş akışlarında "bu adım neden var" bilgisi kayboluyor (modelde `note` alanı var, arayüzde yok) | Adım listesinde onay kutusu (devre dışı bırak); adıma not; adımı kopyala | S |
| Y4 | **Uygulama içi yardım yok** | Kılavuz yalnızca dosyada. İlk açılışta sadece kısa bir metin görünüyor | F1 ile ilgili kılavuz bölümü; ilk açılışta "örnek senaryoyu aç" ve 4 adımlık rehber; pencerelerde "?" | S |
| Y5 | **Uzun formül kutularının bazıları hâlâ tek satır** | Koşullu sütun (doğruysa/yanlışsa) ve kural değerlerinde formül tek satırlık kutuda | Bu kutulara da yeni düzenleyici ("…" ile büyük düzenleyiciyi aç) | S |
| Y6 | **Bazı bilgiler iki kez görünüyor** | "1.500 satır × 9 sütun" hem tablo altında hem durum çubuğunda; veri kümeleri listesi 2 tabloda bile yarım ekranı kaplıyor | Tekrarları kaldır; panel oranlarını içeriğe göre ayarla | S |

## Yüksek — işlevsellik

| No | Eksik | Neden önemli | Öneri | Efor |
|---|---|---|---|---|
| F1 | **Sık kullanılan dönüşümler eksik** | WMS raporlarında birleştirilmiş hücreler (üstteki değerle **aşağı doldur**), "A-01-03" gibi lokasyonları **sütunlara bölme**, yan yana tarih/vardiya sütunlarını **satırlara çevirme** (unpivot), boşları sabit değerle doldurma çok yaygın; şu an yok | Dört yeni adım: Aşağı doldur, Sütunlara böl (ayırıcı/konum), Sütunları satırlara çevir, Boşları doldur | M |
| F2 | **Satırlar arası hesap yok** | Excel'de `=D3-D2` (önceki satırla fark), kümülatif toplam, sıra (RANK) çok kullanılır; çevirici bunları "başka satıra başvuru" diye reddediyor | Formüle ÖNCEKİ([Sütun]), KÜMÜLATİF([Sütun]), SIRA([Sütun]) (isteğe bağlı gruba göre) | M |
| F3 | **Parametre yok** | Excel'deki `$H$1` gibi parametre hücreleri (hedef oranı, kur, mola süresi) çevrilemiyor; değeri formüle gömmek gerekiyor | İş akışı parametreleri: Rapor ayarlarında `Hedef Oran = 95`; formülde `{Hedef Oran}`; çevirici `$H$1`'i parametreye bağlamayı önersin | S |
| F4 | **Pivot sınırlı** | Vardiya raporlarında saatlik/günlük kırılım, toplam içindeki pay ve "en çok ilk 10" sık istenir; şu an yardımcı sütun gerekiyor | Pivotta tarih gruplama (saat/gün/hafta/ay), "değeri göster: toplamın %'si", değere göre sıralama ve ilk N | M |
| F5 | **Veri doğrulama adımı yok** (şartname bölüm 6) | Rapor dağıtılmadan önce "anahtar boş olmasın", "toplam X ile tutsun", "satır sayısı 100'den az olmasın" gibi kontroller | Doğrulama adımı: kural listesi; uyar veya raporu durdur | M |

## Orta

| No | Eksik | Öneri | Efor |
|---|---|---|---|
| O1 | **Rapor paketleri yok** (şartname bölüm 10): birden çok iş akışını sırayla çalıştırma | "Paket" = iş akışı listesi; tek F9 ile hepsi, tek özet ve isteğe bağlı tek mail | M |
| O2 | **Klasörden çoklu dosya** yok (klasördeki tüm günlük dosyaları alt alta alma) | Kaynak türü "klasör": desen (`toplama_*.xlsx`), tarih aralığı, dosya adı sütunu | M |
| O3 | **Excel çıktısında koşullu biçim yok** (hedef altı kırmızı, toplam satırı, sütun biçimleri) | Çıktı sayfası seçeneklerine koşullu renk kuralları ve toplam satırı | M |
| O4 | **Açık Excel'e geri yazma yok** (sonucu yeni Excel penceresine gönder) | "Excel'e gönder": dosya kaydetmeden yeni kitapta aç (COM) | S |
| O5 | **Geri al kütüphane ve arşiv işlemlerini kapsamıyor** | Rapor tanımı, referans tablo ve arşiv silmede çöp kutusu / geri alma | S |
| O6 | **Sütun bilgisi yüzeysel** | Sütun seçilince en sık 10 değer, en küçük/en büyük, küçük bir dağılım grafiği | S |
| O7 | **Formül düzenleyici: sütun adı yazım hatası önerisi yok** | `[Toplanan]` bulunamazsa "Bunu mu demek istediniz: [Toplanan Adet]?" | S |

## Sonraki aşamalar (şartnamede zaten ileriye bırakılanlar)

- Zamanlanmış çalıştırma.
- WMS RPA (pywinauto).
- Çok kullanıcılı yapı: ortak kütüphane ve arşiv için şirket sunucusu veya VPS üzerinde PostgreSQL.
- İş akışı sürüm geçmişi.
- Kurulum programı ve otomatik güncelleme.
- Tabloda hücreyi elle düzeltme: bilinçli olarak kapalı, çünkü yeni raporda hangi satıra uygulanacağı belirsiz.

## Önerilen sıra

1. **K2 + K3 + Y3:** Güvenle kullanım. Donmayan arayüz, kayıp olmayan emek, adımı kapatıp açabilme.
2. **F1 + F2 + F3:** Excel'den taşınamayan işlerin büyük kısmını kapatır.
3. **Y1 + Y2 + Y4:** Dar ekran ve yeni kullanıcı deneyimi.
4. **F4 + F5 + O1–O3:** Raporlama derinliği.

K1 (Windows testi) bunlarla paralel yürümeli. Gerçek kullanımda çıkacak sorunlar bu sırayı değiştirebilir.
