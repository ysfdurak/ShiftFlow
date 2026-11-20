# ShiftFlow tarayıcı demosu — yayın kılavuzu

Bu klasör, ShiftFlow'un veri işleme motorunu **tarayıcıda** çalıştıran demo sayfasıdır. Portföy sitesinde (ysfdurak.com) yayınlanmak için hazırlandı.

- Sunucu gerekmez: yalnız statik dosyalar (HTML, CSS, JS, bir zip ve iki Python tekerleği).
- Python tarayıcının içinde Pyodide (WebAssembly) ile çalışır. Yüklenen dosya ve sonuçlar hiçbir sunucuya gönderilmez.
- Motor kodu masaüstü uygulamasıyla **aynıdır** (`shiftflow/engine`). Tarayıcıya özgü yalnız iki dosya vardır: `sfweb.py` (köprü) ve `app.js` (ekran).

## Dosyalar

| Dosya | Görevi |
|---|---|
| `index.html`, `style.css`, `app.js` | Sayfa ve arayüz. `app.js` motora yalnız `dispatch(komut, json)` ile konuşur |
| `sfweb.py` | Köprü: örnek (sentetik) veri, komutlar, hataları açıklamaya çevirme |
| `build_web.py` | Yayın klasörünü (`dist/`) üretir |
| `dev_server.py` | **Yalnız geliştirme/test.** Aynı köprüyü normal Python'la çalıştırır (`?dev=1`) |
| `e2e_test.py` | Chrome + Playwright ile uçtan uca test (geliştirme sunucusuyla) |
| `_headers` | Cloudflare Pages güvenlik başlıkları |

## Yayın klasörünü üretme

```
python web/build_web.py
```

Çıktı: `web/dist/` (yaklaşık 400 KB). İçinde `index.html`, `app.js`, `style.css`, `manifest.json`, `shiftflow_engine.zip`, `wheels/` ve `_headers` olur.

- `shiftflow_engine.zip`: motorun tarayıcıda kullanılan modülleri + `sfweb.py`. Windows'a özgü veya yerel disk isteyen modüller (WMS taraması, açık Excel, Outlook, kütüphane, arşiv, kurtarma) **dahil edilmez**.
- `wheels/`: openpyxl ve et_xmlfile (saf Python). Siteden yüklenir, PyPI'ye gidilmez.
- pandas ve numpy, Pyodide'nin kendi CDN'inden (cdn.jsdelivr.net) gelir. Sürüm `build_web.py` içindeki `PYODIDE_VERSION` ile sabittir.

Motor kodunu değiştirdiğinizde `build_web.py`'yi yeniden çalıştırıp `dist/` klasörünü yeniden yükleyin.

## Cloudflare Pages'e yükleme (sürükle-bırak)

1. Cloudflare panelinde **Workers & Pages → Create application → Pages → Upload assets** (Direct Upload).
2. Proje adı verin, örneğin `shiftflow-demo`. Adres `shiftflow-demo.pages.dev` olur.
3. `web/dist` klasörünü (veya içeriğinin zip'ini) sürükleyin → **Deploy site**.
4. Projede **Custom domains → Set up a custom domain** → örneğin `shiftflow.ysfdurak.com`. Alan adı Cloudflare'de olduğu için DNS kaydı kendiliğinden eklenir.
5. Güncellemede: projede **Create a new deployment** → yeni `dist` klasörünü yükleyin. Adres değişmez.

**Alt klasör seçeneği:** Siteniz de Cloudflare Pages'teyse `dist` içeriğini sitenin içinde `shiftflow/` klasörüne koyabilirsiniz (`ysfdurak.com/shiftflow/`). Sayfadaki tüm yollar göreli olduğu için iki yöntem de çalışır. Bu durumda `_headers` dosyasını sitenin kökündekiyle birleştirin.

Sınırlar: sürükle-bırakta en çok 1.000 dosya ve dosya başına 25 MB. Bu demo 9 dosya, en büyüğü yaklaşık 250 KB.

## Yerelde deneme

```
python web/dev_server.py 8765
```

Tarayıcıda `http://127.0.0.1:8765/?dev=1` açın. Bu mod Pyodide'yi **kullanmaz**; aynı `sfweb.py`'yi bilgisayarınızdaki Python'la çalıştırır. Arayüzü ve motoru hızlıca denemek içindir.

Gerçek tarayıcı modunu yerelde denemek için `dist/` klasörünü bir statik sunucuyla açın (`python -m http.server -d web/dist 8000`, sonra `http://127.0.0.1:8000/`). İnternet gerekir (Pyodide CDN'den gelir).

## Yayından sonra ilk deneme listesi

Bu kısım burada test edilemedi: test ortamından Pyodide'nin pandas paketlerine erişilemiyordu. İlk yayında şunları elle kontrol edin.

1. Sayfa açılıyor, "Hesaplama motoru yükleniyor" ekranı 10–40 saniyede kapanıyor mu? Başlıkta "motor sürümü 3.10.0" görünüyor mu?
2. **Örnek akışı kur** → Bölge özeti açılıyor ve "farklı yazılışlar" uyarısı çıkıyor mu? **Düzelt** sonrası A Blok tek satıra iniyor mu?
3. **Excel'e aktar** → `ShiftFlow_rapor.xlsx` iniyor, Excel'de 4 sayfa ve "Vardiya verisi" altında toplam satırı (ALTTOPLAM formülü) var mı?
4. **Kendi dosyanı yükle** ile Türkçe karakterli bir CSV ve çok sayfalı bir .xlsx yüklenebiliyor mu?
5. **Yeni günün verisiyle çalıştır** → tarih 03.11.2026 oluyor, adımlar aynı kalıyor mu?
6. Hatalı formül (`[Toplanan] * 2`) yazınca "Bunu mu demek istediniz: [Toplanan Adet]" önerisi çıkıyor ve adım eklenmiyor mu?
7. Tarayıcının geliştirici araçlarında **Ağ (Network)** sekmesi: dosya yükledikten ve Excel'e aktardıktan sonra yeni istek **olmamalı** (yalnız açılıştaki kod indirmeleri). Bu, "veri tarayıcıdan çıkmaz" iddiasının kanıtıdır.
8. Chrome, Edge ve Firefox'ta; telefonda sayfa okunabiliyor mu?

Bir adım başarısızsa tarayıcı konsolundaki (F12) hata mesajını kaydedin.

## Bilinen sınırlar

- Hesaplama sayfanın ana iş parçacığında yapılır. Büyük dosyalarda (100 bin satır üstü) sayfa birkaç saniye donabilir. Gerekirse sonraki adımda Web Worker'a taşınır.
- Adımlar düzenlenemez, yalnız eklenir, kapatılır, taşınır veya silinir.
- Arayüz Türkçedir. İngilizce sürüm henüz yok; motor mesajları da Türkçe.
- Masaüstüne özgü özellikler (açık Excel'den okuma, Outlook taslağı, zamanlama, arşiv, gösterge paneli) demoda yoktur; sayfanın "Hakkında" bölümünde belirtilir.
