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

**GitHub üzerinden otomatik paket:** Proje bir GitHub deposuna gönderildiğinde `.github/workflows/windows.yml` devreye girer. Testleri gerçek bir Windows makinesinde çalıştırır, .exe'yi üretir ve açılış testini yapar. Paket, Actions sayfasının "Artifacts" bölümünden indirilir.

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
