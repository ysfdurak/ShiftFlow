# ShiftFlow Data Studio 3.10

> **Tarayıcı demosu:** Motorun kurulum gerektirmeyen, tarayıcıda çalışan sürümü `web/` klasöründedir. Yayın adımları: [web/README_WEB.md](web/README_WEB.md).

Excel'de her gün elle yapılan rapor hazırlama işlemlerini (temizleme, filtre, hesaplama, birleştirme, pivot, çıktı) **bir kez tanımlayıp** sonraki raporlarda **tek tıkla tekrar çalıştıran** Windows masaüstü uygulaması.

```
Veriyi al → tabloda incele → işlem ekle → iş akışını kaydet → yeni raporla çalıştır → Excel çıktısı
```

**Günlük kullanım:** WMS raporlarını Excel'de açın (kaydetmeniz gerekmez) → ShiftFlow'da iş akışını açın → dönemi (tarih + vardiya) kontrol edin → **▶ Rapor oluştur** (F9).
- Raporlar sütun başlıklarından tanınır; biçim değişikliği, eksik rapor veya yenilenmemiş rapor yakalanır.
- Sonuç Excel'e (grafikli, isterseniz kendi şablonunuza) yazılır ve dönemiyle arşivlenir.
- Vardiya maili önizlemeyle hazırlanır; onayınız olmadan gönderilmez.

**Birden çok rapor:** Rapor paketiyle Toplama, Sevkiyat, Stok gibi iş akışları tek tıkla sırayla oluşturulur; klasördeki tüm günlük dosyalar tek kaynak olarak alınabilir. Gösterge paneli sonuçları ve arşivden eğilimi gösterir.

**Excel'den taşıma:** Raporun yanına Excel'de eklediğiniz formüllü sütunlar (DÜŞEYARA, EĞER, BİRLEŞTİR, EĞERSAY, önceki satırla fark, yürüyen toplam…) tek seferde okunur, ShiftFlow formülüne çevrilir ve Excel'in değerleriyle karşılaştırılır. Karşılığı olmayan formüller çıktıya Excel formülü olarak bırakılabilir.

Veriler yalnızca bu bilgisayarda işlenir. Hiçbir veri dış servise gönderilmez. Kaynak dosyalar asla değiştirilmez. Kaydedilmemiş çalışma birkaç saniyede bir yerel olarak yedeklenir.

## Hızlı başlangıç (Windows)

**Kaynak koddan çalıştırma:** Python 3.10 veya üstü kurulu olmalı ([python.org](https://www.python.org/downloads/), kurulumda "Add to PATH" işaretli olsun).

1. Klasörü açın, `calistir.bat` dosyasına çift tıklayın.
2. İlk açılışta gerekli paketler kurulur (internet gerekir, birkaç dakika sürer). Sonraki açılışlar hızlıdır.

**.exe paketi oluşturma:** `exe_olustur.bat` dosyasına çift tıklayın. Bu dosya önce testleri çalıştırır, sonra `dist\ShiftFlow\ShiftFlow.exe` dosyasını üretir. `dist\ShiftFlow` klasörü Python kurulu olmayan başka bir bilgisayara kopyalanıp kullanılabilir.

**Hazır paket:** [Sürümler (Releases)](https://github.com/ysfdurak/ShiftFlow/releases) sayfasından `ShiftFlow-windows-<sürüm>.zip` dosyasını indirip açın ve `ShiftFlow.exe`'yi çalıştırın; Python kurmak gerekmez.

**GitHub üzerinden otomatik paket:** Her gönderimde `.github/workflows/windows.yml` devreye girer. Testleri gerçek bir Windows makinesinde çalıştırır, .exe'yi üretir ve açılış testini yapar. Paket, Actions sayfasının "Artifacts" bölümünden indirilir. `v3.11.1` gibi bir sürüm etiketi gönderildiğinde ya da GitHub'da bu etiketle sürüm yayımlandığında aynı paket zip olarak Sürümler sayfasına da eklenir.

## Deneme verisi

```
python ornekler\ornek_veri_olustur.py                    (1. gün raporu + personel listesi)
python ornekler\ornek_veri_olustur.py --gun 2            (2. gün, aynı biçim)
python ornekler\ornek_veri_olustur.py --gun 3 --bicim-degisik   (sütun adı değişmiş rapor)
python ornekler\ornek_akis_olustur.py                    (iki hazır örnek iş akışı)
```

Ardından uygulamada **Akış aç** ile şunlardan birini açın:
- `ornekler\ornek_is_akisi.json`: günlük rapor.
- `ornekler\ornek_vardiya_akisi.json`: vardiya sonu raporu; dönem filtresi, DÜŞEYARA, kural tablosu, grafik, arşiv ve mail içerir. Dönemi 01.11.2026 seçin.

Tüm veriler sentetiktir.

## Klasör yapısı

| Yol | İçerik |
|---|---|
| `shiftflow/engine/` | Veri işleme motoru (arayüzden bağımsız, Qt kullanmaz) |
| `shiftflow/ui/` | PySide6 arayüzü |
| `tests/` | Otomatik testler (yalnız sentetik veri) |
| `ornekler/` | Sentetik veri ve örnek iş akışı üreticileri |
| `docs/KULLANIM_KILAVUZU.md` | Kullanıcı kılavuzu |
| `docs/MIMARI.md` | Kodun nasıl çalıştığı, nasıl genişletileceği |
| `docs/TEST_DURUMU.md` | Neyin nerede test edildiği, bilinen sınırlar |
| `docs/DEGERLENDIRME.md` | Kullanılabilirlik ve işlevsellik değerlendirmesi, öncelikli eksik listesi |

## Testler

```
pip install -r requirements-dev.txt
python -m pytest -q
```

Testler motoru (işlemler, birleştirme, pivot, iş akışı, JSON, hata durumları) ve arayüzü (ekransız Qt ile gerçek diyaloglar ve pencere akışları) kapsar.

## Lisans

Bu proje [PolyForm Shield 1.0.0](LICENSE.md) lisansıyla yayınlanır. Kaynak kodu açıktır, ancak resmi anlamda bir "açık kaynak" lisansı değildir.

- **Serbest:** Kişiler, okullar ve şirketler kendi işlerinde ücretsiz kullanabilir, değiştirebilir ve kendi bilgisayarlarına ya da sunucularına kurabilir. İzin almak gerekmez.
- **Yazılı izin gerekir:** Yazılımı satmak, adını değiştirip ürün gibi sunmak ya da bununla (ücretsiz olsa bile) rakip bir ürün veya hizmet sunmak.
- **Garanti yok:** Yazılım olduğu gibi sunulur. Bağlayıcı olan İngilizce lisans metnidir.
- Üçüncü taraf bileşenler kendi lisanslarına tabidir.

Kurumunuzda kullanıyorsanız haber verirseniz sevinirim: kurulumda yardımcı olabilir, kurumunuza özel ihtiyaçları birlikte değerlendirebiliriz. İletişim: iletisim@ysfdurak.com

### License (English)

Released under [PolyForm Shield 1.0.0](LICENSE.md). The source is available, but this is not an OSI "open source" licence.

- **Free:** individuals, schools and companies may use it in their own work, change it and run it on their own computers or servers. No permission needed.
- **Needs written permission:** selling it, rebranding it as a product, or providing a product or service that competes with it (even free of charge).
- **No warranty:** provided as is. The English licence text is binding.
- Third-party components keep their own licences.

Using it in your organisation? I'd be glad to hear from you: I can help with setup and look at your organisation's needs together. Contact: contact@ysfdurak.com
