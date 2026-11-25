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
| `_headers` | Cloudflare güvenlik başlıkları (CSP dahil) |
| `static_server.py` | Yayın klasörünü `_headers` ile yerelde sunar (deneme ve e2e) |
| `vendor/` | Pyodide alt kümesi ve openpyxl tekerlekleri (SHA-256 listeli) |

## Yayın klasörünü üretme

```
python web/build_web.py
```

Çıktı: `web/dist/` (yaklaşık 400 KB). İçinde `index.html`, `app.js`, `style.css`, `manifest.json`, `shiftflow_engine.zip`, `wheels/` ve `_headers` olur.

- `shiftflow_engine.zip`: motorun tarayıcıda kullanılan modülleri + `sfweb.py`. Windows'a özgü veya yerel disk isteyen modüller (WMS taraması, açık Excel, Outlook, kütüphane, arşiv, kurtarma) **dahil edilmez**.
- `wheels/`: openpyxl ve et_xmlfile (saf Python). Siteden yüklenir, PyPI'ye gidilmez.
- `pyodide/`: Python (Pyodide 314.0.8) ve pandas, numpy, python-dateutil, pytz, six. Depodaki `web/vendor/pyodide` klasöründen kopyalanır; sayfa hiçbir dış adrese (CDN dahil) istek atmaz. Sürüm yükseltme: `web/vendor/pyodide/README.md`.

Motor kodunu değiştirdiğinizde `build_web.py`'yi yeniden çalıştırıp `dist/` klasörünü yeniden yükleyin.

## Yayın: Cloudflare Workers (shiftflow.ysfdurak.com)

Canlı adres: **https://shiftflow.ysfdurak.com/**. Depo Cloudflare Workers'a bağlıdır; `main` dalına her
birleştirmede Cloudflare `python3 web/build_web.py` çalıştırıp `web/dist` klasörünü yayınlar
(`wrangler.jsonc`). Diğer dallar önizleme adresine gider.

İlk bağlantı (23 Kasım 2026'da yapıldı; yeniden kurmak gerekirse): Cloudflare panelinde **Workers & Pages → Create → Import a repository →
ysfdurak/ShiftFlow**; proje adı `shiftflow`, derleme komutu `python3 web/build_web.py`, dağıtım
komutu varsayılan (`npx wrangler deploy`). Alan adı `wrangler.jsonc` içindeki `routes` ile kendiliğinden bağlanır.

**Yayın gelmiyorsa:** Cloudflare'in GitHub uygulamasının (Cloudflare Workers and Pages) bu depoya erişimi olmalı. 25 Kasım 2026'da canonical değişikliği birleştiği hâlde yayın gelmedi: uygulama yalnız seçili depolara yetkiliydi. GitHub → Settings → Applications → Cloudflare Workers and Pages → *All repositories* ile düzeltildi. Yetki sonradan verilirse kaçırılan gönderim kendiliğinden derlenmez; yeni bir birleştirme ya da panelde elle yeniden dağıtım gerekir. Belirti: PR'larda "Workers Builds" denetimi hiç görünmez.

Derleme ağ gerektirmez: Pyodide, pandas/numpy (`web/vendor/pyodide`) ve openpyxl (`web/vendor/wheels`)
depodadır ve her derlemede SHA-256 ile denetlenir.

## Yerelde deneme

```
python web/dev_server.py 8765
```

Tarayıcıda `http://127.0.0.1:8765/?dev=1` açın. Bu mod Pyodide'yi **kullanmaz**; aynı `sfweb.py`'yi bilgisayarınızdaki Python'la çalıştırır. Arayüzü ve motoru hızlıca denemek içindir.

Gerçek tarayıcı modunu yerelde denemek için `python web/static_server.py 8000` (yayındaki `_headers` başlıklarıyla) ve `http://127.0.0.1:8000/`. İnternet gerekmez.

Gerçek Pyodide ile otomatik uçtan uca test: `python web/build_web.py && python web/e2e_test.py --pyodide`. Aynı test her PR'da GitHub Actions'ta (Tarayıcı demosu) çalışır; dış adrese istek, işlem sırasında ağ isteği, CSP ihlali veya konsol hatası olursa düşer.

## Yayından sonra ilk deneme listesi

Bu listenin 1–7. maddeleri `e2e_test.py --pyodide` ile otomatik denenir (Chrome). Firefox, Safari ve gerçek telefonda elle bakılması iyi olur.

1. Sayfa açılıyor, "Hesaplama motoru yükleniyor" ekranı 10–40 saniyede kapanıyor mu? Başlıkta "motor sürümü" ve güncel sürüm görünüyor mu?
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

## İçerik güvenlik politikası (CSP)

`_headers` içindeki CSP yalnız sitenin kendisini açar: `script-src 'self' 'wasm-unsafe-eval'`, `connect-src 'self'`, `form-action 'none'`.
Veri dışarı gönderilemez; Pyodide de dahil her şey aynı adresten gelir. `'wasm-unsafe-eval'` Python yorumlayıcısının
WebAssembly olarak derlenmesi için gerekir; `'unsafe-eval'` gerekmez (gerçek Pyodide ile denendi). Pyodide sürümü
değişirse `e2e_test.py --pyodide` CSP ihlallerini de yakalar.
