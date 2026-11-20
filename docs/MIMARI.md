# ShiftFlow Mimarisi — projeye hâkim olmak için

Bu belge kodu yazmamış birinin projeyi anlayıp soruları yanıtlayabilmesi ve yeni özellik ekleyebilmesi için yazıldı. Sonunda kendinizi sınamanız için sorular var.

## 1. Büyük resim

```
┌──────────────── shiftflow/ui (PySide6) ────────────────┐
│ MainWindow  ·  diyaloglar  ·  DataFrameModel (tablo)   │
│ Yalnızca Session'ı çağırır; pandas işlemi yapmaz.      │
└───────────────────────────┬────────────────────────────┘
                            │ add_step / result / undo / export ...
┌───────────────────────────▼────────────────────────────┐
│ engine/session.py  — Session                           │
│  · yüklenen veriler (data)  · iş akışı (workflow)      │
│  · hesaplama + önbellek     · geri al / yinele         │
├────────────────────────────────────────────────────────┤
│ engine/workflow.py — tanım + JSON (veri içermez)       │
│ engine/operations.py — işlemler (saf fonksiyonlar)     │
│ engine/expression.py — güvenli formül dili             │
│ engine/io.py — Excel/CSV/pano okuma, Excel yazma       │
│ engine/values.py — Türkçe sayı/tarih, tip tahmini      │
└────────────────────────────────────────────────────────┘
```

**Temel kural:** `engine` klasörü Qt'yi hiç import etmez. Böylece aynı motor ileride komut satırından, zamanlanmış görevden veya RPA robotundan arayüz olmadan çalıştırılabilir. Motor testleri de Qt olmadan çalışır.

## 2. Veri modeli: kaynak, veri kümesi, adım

```
Kaynak "Toplama" ──► Veri kümesi "Toplama":  [Filtre] → [Hesapla] → [Koşullu]
Kaynak "Personel" ─► Veri kümesi "Personel": [Sütun seç]
                                     │                │
                                     └──── Birleştir ─┘
                                             ▼
                          Veri kümesi "Detay" (başlangıç = join)
                              │                    │
                        Pivot ▼              Kopya ▼ + [Filtre]
                  "Vardiya x Bölge"          "Eşleşmeyenler"
```

- **Kaynak (`SourceSpec`):** Dosya yolu, sayfa, başlık ayarı, beklenen sütunlar ve tipleri, sütun eşleme tablosu. **Verinin kendisi saklanmaz.**
- **Veri kümesi (`Dataset`):** Bir **başlangıç** (`Origin`) ve **doğrusal adım listesi** (`steps`).
  - Başlangıç ya bir kaynaktır ya da birden çok girdi alan bir işlemdir: `join`, `append`, `group`, `pivot`, `copy`.
- **Adım (`Step`):** Tek girdili işlem (filtre, hesapla…). Kimliği (`id`), türü (`op`) ve parametreleri (`params`) vardır.

**Neden böyle?** Şartname doğrusal listeye bağımlı kalmamayı ve paralel kolları istiyor. Bu modelde DAG **veri kümeleri arasında** kurulur: bir veri kümesi başka veri kümelerini girdi olarak alır. Her veri kümesinin içi ise kullanıcı için basit bir listedir. Kullanıcı Excel'deki gibi "bu tabloya şunu yap" diye düşünür; DAG arka planda kalır.

**Önemli ayrıntı:** Girdiler adım kimliğine değil, **veri kümesi adına** bağlıdır. "Toplama"ya yeni filtre eklenirse "Detay" ve ona bağlı pivot bu filtreyi otomatik görür. Kimliğe bağlansaydı pivot eski adımda takılı kalırdı.

**Döngü koruması:** `Workflow.topo_order()` derinlik öncelikli gezinir. Bir düğüme "ziyaret ediliyor" durumundayken tekrar gelinirse döngü vardır; `A → B → A` biçiminde açıklayıcı hata verir. JSON yüklenirken ve her değişiklikte `validate()` bunu çağırır.

## 3. İşlemler (operations.py)

Her işlem bir `Operation` kaydıdır:

```python
Operation(key="filter", label="Filtre", run=_run_filter, describe=..., inputs="1", new_dataset=False)
```

- `run(inputs: list[DataFrame], params: dict, label: str) -> OpResult`
  - **Saf fonksiyondur:** Girdiyi değiştirmez, yeni tablo döner.
  - `OpResult` içinde tablo (`df`), bilgi mesajları (`messages`), uyarılar (`warnings`) ve istatistikler (`stats`, örn. birleştirme tanısı) bulunur.
- Hata durumunda `ShiftFlowError` alt sınıfı fırlatır. Mesaj Türkçedir ve kullanıcıya doğrudan gösterilir.
- `describe(params)` adım listesindeki okunur açıklamayı üretir.

### Yeni işlem türü eklemek (örnek: "Boşları doldur")

1. `operations.py` içine yazın:
   ```python
   def _run_fill(inputs, p, label):
       df = inputs[0]
       _need(df, [p["column"]], label)          # eksik sütunda açıklayıcı hata
       out = df.copy()
       n = int(is_empty(out[p["column"]]).sum())
       out[p["column"]] = out[p["column"]].where(~is_empty(out[p["column"]]), p["value"])
       return OpResult(out, messages=[f"{n} boş hücre dolduruldu."])

   register(Operation("fill", "Boşları doldur", _run_fill,
                      lambda p: f"Boşları doldur: {p['column']} = {p['value']}"))
   ```
2. `ui/dialogs.py` içine `OpDialog`'dan türeyen bir diyalog ekleyin (`build()` ve `params()` yeterlidir; önizleme ve hata gösterimi ortak sınıftan gelir) ve `STEP_DIALOGS`'a kaydedin.
3. `main_window.py` içindeki `step_acts` listesine bir satır ekleyin.
4. `tests/test_operations.py` dosyasına test yazın.

JSON biçimi değişmez; eski iş akışları açılmaya devam eder.

## 4. Hesaplama ve önbellek (session.py)

`Session._compute(ad, upto)` bir veri kümesini başlangıçtan istenen adıma kadar hesaplar.

**İmza (signature):** Her ara sonuç bir özetle (SHA-1) adlandırılır:

```
başlangıç imzası = özet("src", kaynak adı, veri sürüm numarası, sütun eşleme)
                   veya özet(işlem, parametreler, girdi veri kümelerinin son imzaları)
adım imzası      = özet(önceki imza, işlem türü, parametreler)
```

Sonuçlar bu imzayla LRU önbellekte tutulur (varsayılan 48 tablo). Sonuçları:
- Aynı adımı iki kez hesaplamaz.
- **Geri al** yalnızca iş akışı tanımını eski hâline döndürür; imzalar aynı olduğu için tablolar önbellekten gelir ve hesaplama gerekmez.
- Yeni veri bağlandığında (`bind_source`) kaynak sürüm numarası artar. Böylece o kaynaktan türeyen tüm imzalar değişir ve eski sonuçlar kendiliğinden geçersiz kalır. "Önbelleği temizle" diye ayrı bir mantık gerekmez.

**Bellek:** Her ara sonuç ayrı bir tablodur. Çok büyük verilerde `CACHE_SIZE` düşürülebilir.

## 5. Değişikliklerin güvenliği: `_commit`

Her değişiklik (adım ekleme, düzenleme, silme, taşıma, veri kümesi ekleme…) aynı yoldan geçer:

1. Mevcut tanım JSON olarak saklanır (geri alma noktası).
2. Değişiklik tanımın **kopyası** üzerinde yapılır ve `validate()` çalışır.
3. Değişen veri kümesi ve ona bağlı tüm veri kümeleri hesaplanır.
4. **Yeni** bir hata çıkarsa eski tanıma dönülür ve hata yükseltilir. Hata bağlı bir veri kümesindeyse mesaj o kümenin adını söyler: "Bu değişiklik 'Özet' veri kümesini bozuyor".
5. Daha önce zaten hatalı olan veri kümeleri kontrol dışı tutulur. Böylece eski bir sorun yeni bir düzeltmeyi engellemez.

Adım sırası değiştirmedeki bağımlılık kontrolü de bu yoldan gelir: taşıma denenir, sonuç bozuluyorsa reddedilir.

## 6. İş akışı JSON biçimi

```json
{
  "format": "shiftflow-workflow",
  "schema_version": 1,
  "name": "Günlük toplama raporu",
  "sources":  [{"name": "Toplama", "path": "veri/rapor.xlsx", "sheet": "Toplama", "header": true,
                "expected_columns": [{"name": "Toplanan Adet", "type": "number"}],
                "column_map": {"Toplanan Miktar": "Toplanan Adet"}}],
  "datasets": [{"name": "Toplama", "origin": {"type": "source", "source": "Toplama"},
                "steps": [{"id": "a1b2c3d4", "op": "filter", "params": {...}}]}],
  "outputs":  [{"dataset": "Detay", "sheet": "Detay"}]
}
```

- `schema_version` ileride biçim değişirse `MIGRATIONS` sözlüğüne dönüştürücü eklenir. Daha yeni sürümle kaydedilmiş dosya açılmaz ve "uygulamayı güncelleyin" uyarısı verilir.
- Göreli yollar JSON dosyasının klasörüne göre çözülür. İş akışı raporlarla birlikte başka bir klasöre taşınabilir.

## 7. Yeni raporla çalıştırma ve sütun eşleme

`check_source(ad, yeni_tablo)` beklenen sütunlarla yeni tabloyu karşılaştırır:
- **missing:** İş akışının beklediği ama gelmeyen sütunlar.
- **suggestions:** Büyük/küçük harf, boşluk ve alt çizgi farkını yok sayarak, gerekirse `difflib` benzerliğiyle önerilen karşılıklar.
- **type_changes:** Tipi değişen sütunlar.

Kullanıcının onayladığı eşleme `column_map` olarak kaynağa yazılır ve veri okunurken uygulanır. Adımlar eski sütun adını görmeye devam eder; hiçbir adımı değiştirmek gerekmez.

## 8. Birleştirme nasıl korunuyor

`join_diagnostics()` birleştirmeden önce şunları hesaplar: eşleşen/eşleşmeyen sayıları, tekrar eden anahtarlar, ilişki türü ve beklenen satır sayısı.

- Anahtarlar `normalize_key` ile metne çevrilir (1, 1.0 ve "1" eşit sayılır; boşluklar kırpılır).
- Boş anahtarlara satıra özel benzersiz bir değer verilir. Pandas normalde NaN ile NaN'ı eşleştirir; bu koruma olmasa boş anahtarlı satırlar birbiriyle eşleşip satırları çoğaltırdı.
- Çoktan-çoğa eşleşmede `JoinConfirmationRequired` fırlatılır. Arayüz kullanıcıya tanı bilgisini gösterip onay ister. Onay `allow_many_to_many: true` olarak parametreye yazılır, böylece akış yeniden çalıştırıldığında tekrar sorulmaz.

## 9. Formül dili (expression.py)

`eval` kullanılmaz. Küçük bir ayrıştırıcı yalnızca `[Sütun]`, sayı, `"metin"`, `+ - * / ( ) &` kabul eder. Kullanıcı formülü bu yüzden kod çalıştıramaz.

Hesaplama vektöreldir: Satır satır dönmez, sütunun tamamında tek seferde yapılır. Bu yüzden 500 bin satırda bile milisaniyeler sürer. Sıfıra bölme NaN (boş) üretir ve sayılır. Sayı olmayan değer, örnekleriyle birlikte `TypeMismatchError` verir.

## 10. Arayüz katmanı

- **`DataFrameModel`:** QTableView yalnızca ekranda görünen hücreleri ister. Model değeri o anda Türkçe biçimde (`1.234,5`, `31.12.2026`) üretir. Milyon satırlık tablo da bu yüzden anında açılır.
- **`OpDialog`:** Tüm işlem diyaloglarının atası. Her alan değişiminde 250 ms bekleyip işlemi önizler. Hata varsa "Uygula"yı kapatır. Diyaloglar veriyi değiştirmez, yalnızca `params()` sözlüğü üretir.
- **`MainWindow`:** Kullanıcı eylemlerini `Session` çağrılarına çevirir. Her çağrı `_apply()` ile sarılıdır: hata olursa mesaj kutusu gösterir, program çökmez.
- **Ara sonuç görünümü:** `view_step` değişkeni (None = son adım). Yeni adım `view_step + 1` konumuna eklenir.

## 11. Açık raporları tanıma ve "Rapor oluştur"

Yeni modüller (hepsi `engine` içinde; Qt kullanmaz):

| Modül | Görevi |
|---|---|
| `reports.py` | Rapor tanımı (`ReportDefinition`), başlık satırı bulma, tanıma puanı, sütun karşılaştırma, içerik özeti |
| `library.py` | SQLite kütüphane: tanımlar + çalıştırma geçmişi (`%LOCALAPPDATA%\ShiftFlow\shiftflow.db`) |
| `excel_live.py` | Açık Excel kitaplarını okuyan sağlayıcılar: `ComExcelProvider` (Windows COM), `FileWorkbookProvider`, `MultiProvider` |
| `autorun.py` | `ReportBuilder`: `plan()` → `build()` |

**Neden sütun başlıklarıyla tanıma?** WMS'in açtığı kaydedilmemiş kitabın adı her gün değişir (Kitap1, Kitap3…). Sayfa adı da genelde "Sheet1"dir. Değişmeyen tek şey raporun sütun başlıklarıdır.

**Tanıma puanı:** Açık her sayfanın ilk 30 satırı (`PREVIEW_ROWS`) okunur. Her satır için "tanımın anahtar sütunlarının yüzde kaçı bu satırda var?" hesaplanır; en yüksek oranlı satır başlık satırıdır. Bu, raporun üstündeki başlık ve tarih satırlarını da çözer. Oran ≥ 0,80 ise sayfa aday olur. Kitap/sayfa adı ipucu varsa uyunca +0,05, uymazsa −0,2 eklenir. İlk iki aday arasında 0,05'ten az fark varsa durum "birden çok uygun rapor" olur ve kullanıcı seçer; ShiftFlow tahmin yürütmez.

Karşılaştırmada büyük/küçük harf ve boşluk farkı yok sayılır (`norm`). Öneriler için ayrıca noktalama farkı da yok sayılır (`loose`) ve `difflib` benzerliği kullanılır.

**Değişiklik türleri** (`compare_columns`):
- Engelleyici: `missing`. İş akışı bu sütunu bekliyor ama gelmedi.
- Bilgi amaçlı: `extra` (yeni sütun), `type_changes`, `order_changed`, `auto_mapped` (yalnız yazım farkı).

**Öğrenilen eşlemeler:** Kullanıcı "Toplanan Miktar → Toplanan Adet" eşlemesini onaylayınca bu bilgi hem kaynağın `column_map`'ine hem **rapor tanımına** yazılır. Tanım tek bir yerde durduğu için aynı raporu kullanan bütün iş akışları bundan yararlanır.

**Bayat veri kontrolü:** Her başarılı çalıştırmada kaynakların içerik özeti (`fingerprint`, SHA-1) geçmişe yazılır. Bir sonraki çalıştırmada aynı özet gelirse durum "son çalıştırmayla aynı veri" olur. Bu, WMS'ten raporu yenilemeyi unutup dünkü veriyle rapor dağıtmayı engeller. Özetten veri geri elde edilemez.

**Hatalıysa yazma:** `build()` önce `run_all()` çalıştırır; tek bir veri kümesi bile hatalıysa dosya yazılmaz ve geçmişe "error" kaydı düşer.

**COM ayrıntıları** (`ComExcelProvider`):
- Windows'un çalışan nesneler tablosu (ROT) taranarak tüm Excel örnekleri bulunur. WMS raporu ayrı bir Excel penceresinde açtığında `GetActiveObject` yalnızca birini görebilir; ROT taraması bunu aşmak içindir. Hiçbiri bulunamazsa `GetActiveObject` kullanılır.
- Bir sayfa `UsedRange.Value` ile tek çağrıda okunur; hücre hücre okumak çok yavaş olurdu.
- Excel'in döndürdüğü saat dilimli tarihler sade tarihe çevrilir.
- Excel'de hücre düzenlenirken COM çağrıları reddedilir (`0x8001010A`); kullanıcıya "Excel meşgul" mesajı gösterilir.
- Testlerde gerçek Excel yerine `tests/fake_excel.py` içindeki sahte nesneler kullanılır. `apps_factory` parametresi tam olarak bunun için vardır.

**İş akışı biçimi 2:** `SourceSpec.report_id`, `Workflow.run_settings` (çıktı klasörü, dosya adı kalıbı) ve `Workflow.reports` (kullanılan tanımların kopyası) eklendi. `MIGRATIONS[1]` eski dosyaları otomatik dönüştürür. Tanım kopyası sayesinde iş akışı başka bir bilgisayarda açıldığında tanımlar oradaki kütüphaneye eklenir (`library.merge`; daha yeni olan kazanır).

## 12. Formüller, DÜŞEYARA, kurallar, referans tablolar, dönem, arşiv, çıktı, mail

| Modül | Görevi |
|---|---|
| `expression.py` | Formül dili: karşılaştırma, fonksiyonlar (`FUNCTIONS` sözlüğü, Türkçe + İngilizce adlar), tarih aritmetiği |
| `operations.py` | `lookup` (DÜŞEYARA), `rules` (kural tablosu), `period_filter` (dönem filtresi) |
| `library.py` | Referans tablolar (`ref_tables`), ayarlar (`settings`: vardiyalar), çalıştırma dönemleri |
| `periods.py` | Vardiya tanımı, dönem (`Period`), varsayılan dönemin hesabı, önceki vardiya |
| `archive.py` | Rapor arşivi (`archive.db`): dönem bazında yazma/değiştirme, aralık okuma |
| `excel_out.py` | Excel yazımı: sayı/tarih biçimleri, Excel grafikleri, şablona yazma |
| `mailer.py` | Mail taslağı (HTML tablo), Outlook COM, `.eml` yedeği |

**Fonksiyon eklemek:** `expression.FUNCTIONS` sözlüğüne `"AD": lambda ctx, args: ...` ekleyin. `args` sütunlar (Series) veya sabitlerdir. `ctx.series(x)` sabiti sütuna, `ctx.num(x)` sayıya, `ctx.boolean(x)` mantıksal değere çevirir. Arayüzde görünmesi için `FUNCTION_HELP` listesine bir satır ekleyin.

**Başka tabloya başvuran adım (DÜŞEYARA):** Adımlar normalde tek girdilidir. `Operation.refs(params)` başvurulan veri kümelerini döner.
- `Workflow.deps()` bu başvuruları bağımlılık grafiğine katar. Döngü kontrolü, silme koruması ve "bağlı veri kümelerini de kontrol et" kuralı bu sayede DÜŞEYARA için de çalışır.
- Önbellek imzasına başvurulan tabloların imzası eklenir; arama tablosu değişince sonuç yeniden hesaplanır.

**Bağlama ihtiyaç duyan adım (dönem filtresi):** `Operation.uses_context = True` olan adımlar, `Session.context`'i (seçili dönem) `params["__context__"]` olarak alır. Bağlam imzaya da eklenir: dönem değişince yalnızca bu adım ve sonrası yeniden hesaplanır. Dönem seçilmeden çalıştırılırsa açık bir hata verir; sessizce "bugün" varsaymaz.

**Varsayılan dönem** (`periods.auto_period`): Şu anki vardiya bulunur. Vardiya başlayalı `grace_minutes`'tan (varsayılan 120) az zaman geçtiyse önceki vardiya seçilir. Vardiyanın tarihi başladığı gündür. Kullanıcı her zaman değiştirebilir; otomatik değer yalnızca öneridir.

**Arşiv:**
- Her arşiv kümesi kendi SQLite tablosudur. Satırlara `_donem`, `_tarih`, `_vardiya` alanları eklenir.
- Aynı dönem yazılınca önce o dönemin satırları silinir; çift kayıt olmaz.
- Yeni sütun gelirse `ALTER TABLE ADD COLUMN` ile eklenir.
- Arşiv kaynakları (`SourceSpec.archive`) seçili döneme göre her hesaplamada `Archive.resolve` ile okunur. `Session._ensure_archive` (dönem, aralık, arşiv sürümü) üçlüsü değişmedikçe yeniden okumaz.

**"Aynı veri" (bayat rapor) kuralı** (`ReportBuilder._looks_stale`):
- Aynı içerik özeti **aynı dönem** için tekrar kullanılıyorsa sorun yoktur (yeniden oluşturma).
- **Başka bir gün** için kullanıldıysa raporun yenilenmediği düşünülür.
- **Aynı gün başka bir vardiya** için kullanıldıysa:
  - Kaynak dönem filtresiyle vardiyalara bölünüyorsa (günlük tek rapor) sorun yoktur.
  - Bölünmüyorsa her vardiyanın kendi raporu olmalıdır; aynı veri, yenilenmediği anlamına gelir.

**Excel grafikleri:** openpyxl ile gerçek Excel grafiği (`BarChart`, `LineChart`, `PieChart`) yazılır. Veri aralığı tablonun kendisini gösterir. "Genel Toplam" satırı ve sütunu dışarıda bırakılır.

**Şablon:** `openpyxl.load_workbook(şablon)` ile açılır. Biçimler, formüller, birleştirilmiş hücreler ve koşullu biçimlendirme korunur. openpyxl'in sınırı nedeniyle resimler, hazır grafikler, PivotTable'lar ve makrolar korunamaz; `template_warnings` bunları önceden bildirir. Şablon dosyası korunan yollar listesindedir, üzerine yazılamaz.

**Mail:**
- `build_draft` yalnızca taslak üretir.
- `OutlookMailer.send` arayüzde yalnızca "Gönder" + onay sonrası çağrılır. Kod tabanında başka hiçbir yerden çağrılmaz; testler bunu sahte Outlook ile doğrular.
- `.eml` yedeğinde `X-Unsent: 1` başlığı vardır; Outlook bu sayede dosyayı gönderilmemiş, düzenlenebilir taslak olarak açar.

**İş akışı biçimi 3:** `SourceSpec.reference_id` ve `SourceSpec.archive` alanları eklendi. Çıktı, arşiv, şablon ve mail ayarları `run_settings` sözlüğünde tutulur. `MIGRATIONS[2]` eski dosyaları dönüştürür.

## 13. Formülde tablo fonksiyonları, Excel çevirici, işlem arama

**Tablo fonksiyonları** (`expression.py`):
- DÜŞEYARA, ÇAPRAZARA, EĞERSAY ailesi ve TABLO* fonksiyonları, formülün içinden başka bir veri kümesini okur.
- `referenced_tables(formül)` formülü ayrıştırıp tablo bağımsız değişkeni olan tırnaklı adları bulur (`TABLE_ARG` sözlüğü hangi bağımsız değişkenin tablo olduğunu söyler).
- `calc`, `conditional` ve `rules` işlemlerinin `refs` alanı bu listeyi döner. Böylece DÜŞEYARA adımında olduğu gibi şunlar formüller için de geçerlidir: bağımlılık grafiği, döngü kontrolü, silme koruması ve önbellek imzası.
- `"BU"` içinde bulunulan tablodur ve bağımlılık sayılmaz.
- Yeniden adlandırmada `rename_table` formüldeki tırnaklı adı değiştirir.

**Vektörel hesap:**
- Arama, anahtar → değer sözlüğüyle tek geçişte yapılır.
- EĞERSAY/ETOPLA ailesi, satıra bağlı ölçütlerde arama tablosunu o sütunlara göre gruplar ve her satıra kendi grubunun sonucunu verir. Sabit ölçütlerde (`">15"`) tabloyu önce süzer.
- Bu sayede 500 bin satırda bile Excel'deki gibi satır başına tarama yapılmaz.

**Excel formülü çevirici** (`excel_formula.py`):
1. Excel formülü kendi ayrıştırıcısıyla ağaca çevrilir. Hücreler, aralıklar, sayfalı başvurular (`'Sayfa adı'!A:C`), `%`, Türkçe/İngilizce ayırıcı ve `_xlfn.` önekleri tanınır.
2. Ağaçtan ShiftFlow formülü üretilir:
   - Harf → sütun eşlemesi `letter_map` ile yapılır. Kaynak tablolarda önce raporun özgün sütunları, ardından ShiftFlow'da eklenen sütunlar sayılır; bu, Excel'deki "raporun yanına formüllü sütun" düzenine karşılık gelir.
   - "Geçerli satır", göreli tek hücre başvurularında en sık geçen satır numarasıdır. Başka satıra veya sabit hücreye başvuru tahminle çevrilmez, uyarı verilir.
   - Kalıp dönüşümleri `_special` içindedir (DÜŞEYARA → ÇAPRAZARA vb.). Çevrilemeyen bir kalıp `_Fallback` ile olduğu gibi bırakılır ve uyarılır.
3. Yeni bir Excel fonksiyonu eklemek için: ad farklıysa `NAME_MAP`'e, özel dönüşüm gerekiyorsa `_special`'a ekleyin.

**İşlem arama** (`ui/palette.py`):
- Komutlar başlık, açıklama ve anahtar kelimelerle (eş anlamlılar) tanımlanır. Arama tüm kelimelerin geçmesini ister; Türkçe karakterler katlanır (ş→s), böylece "dusey" yazınca "düşeyara" bulunur.
- Puanlama sırası: başlık başlangıcı > başlık içi > anahtar kelime. Seçili sütunun tipine uygun komutlar `boost` ile öne çıkar.
- Komut listesini `MainWindow.palette_commands()` her açılışta yeniden üretir; yeni bir işlem eklendiğinde buraya bir satır eklemek yeterlidir.

## 13a. Formül düzenleyici (formula_editor.py, expression.py)

- Belirteçler (`Tok`) başlangıç ve bitiş konumu taşır. Ayrıştırma hataları `exc.pos` ile döner; düzenleyici bu konuma dalgalı çizgi koyar.
- `check_parentheses`, değerlendirmeden önce çalışır. Kapanmamış parantezin sahibi olan fonksiyonu bulur; böylece mesaj formülün sonunu değil asıl yeri gösterir.
- `format_formula(expr, width)` okunaklı yazım üretir: sığan grup tek satırda kalır, sığmayan fonksiyonun bağımsız değişkenleri alt satırlara girintiyle iner. `one_line` geri birleştirir. Biçimleme yalnız boşlukları değiştirir; testler iki biçimin aynı sonucu verdiğini doğrular.
- `signature_at(expr, imleç)` imlecin içinde bulunduğu fonksiyonu ve kaçıncı bağımsız değişkende olduğunu verir; `SIGNATURES` tablosundan yazım metni üretilir.
- `FormulaEdit` (QPlainTextEdit) şu parçalardan oluşur: `FormulaHighlighter` (renk), `QCompleter` (fonksiyon ve sütun adları), parantez eşi vurgusu (`matching_paren`) ve hata işareti (extra selections). Motor Qt'den bağımsız kalır; Qt tarafı yalnız bu dosyadadır.

## 13b. Sürüm 3.5 eklemeleri

**Farklı yazılışlar (variants.py).** `concern_columns(op, params)` bir adımın karşılaştırdığı/grupladığı sütunları döndürür: filtre koşulları, gruplama ve pivot alanları, tekrar sütunları, karşılaştırma veya EĞERSAY ailesi içeren formüllerin sütunları. `Session._compute` her adımda girdi tablosunda `variants.check` çalıştırır. Bulunanlar `StepStatus.variants` alanına ve uyarılara yazılır; değerlere dokunulmaz. Arayüz (`MainWindow.offer_variant_fix`) adım eklenince/düzenlenince sorar. "Düzelt" `Session.fix_variants` ile adımın önüne `unify` adımı ekler. Önündeki adım zaten `unify` ise sütunlar ona eklenir. Gruplama/pivot gibi başlangıç işlemlerinde ekleme girdi tablosunun sonuna yapılır. "Bir daha sorma" adım parametresine `ignore_variants` yazar. Normalleştirme: baş/son boşluk, iç boşluklar teke, Türkçe küçük harf.

**Arka plan görevleri (ui/worker.py).** `run_task(parent, fn, text, session)` işi bir Python iş parçacığında çalıştırır. Ana iş parçacığı `processEvents` ile pencereyi canlı tutar; 0,4 sn'den uzun süren işlerde ilerleme penceresi açılır. Kurallar:
1. `fn` içinde Qt nesnesine dokunulmaz. Değerler (dialog alanları) önceden okunur. Bu yüzden `_apply(..., background=True)` yalnız denetlenmiş çağrılarda kullanılır.
2. Görev sırasında çöp toplayıcı kapatılır. Aksi hâlde eski Qt nesneleri iş parçacığında silinip belleği bozabilir.
3. Girdi olayları `_InputBlocker` ile yalnız ilerleme penceresine geçer; iş sürerken iş akışı başka yerden değiştirilemez.
4. Excel/Outlook (COM) çağrıları bu yolla çalıştırılmaz; COM nesneleri oluşturuldukları iş parçacığına bağlıdır.

İptal: `session.cancel_event` ayarlanır, `_tick` bir sonraki adım sınırında `Cancelled` yükseltir, `_commit` eski tanıma döner. Not: ilk denemede iç içe `QEventLoop.exec()` kullanıldı; testlerin sonunda bellek hatası görüldü. `processEvents` döngüsüne geçilince kayboldu.

**Otomatik yedek (engine/recovery.py).** `Recovery.save` iş akışı JSON'unu ve yeniden okunamayan kaynak verilerini (pickle) yerel klasöre atomik yazar. Veri yalnız kaynak sürüm numarası değişince yeniden yazılır. Pencere 5 sn'de bir `autosave` çağırır (görev sürerken ve pencere gizliyken beklenir). Kayıt, yeni çalışma veya temiz kapanışta klasör silinir. `app.main` açılışta `offer_recovery` çağırır.

**Adım aç/kapa, not.** `Step.enabled` (varsayılan True; eski dosyalar etkilenmez) ve `Step.note`. Kapalı adım `_compute` içinde atlanır ve imzaya "kapalı" girer.

**Excel'deki formüllü sütunlar.** `Provider.formula_rows` ilk ~40 satırın formüllerini verir (COM: `UsedRange.Formula`; dosya: openpyxl). Excel satır/sütun başlangıcı `FormulaGrid` içindedir. `excel_formula.find_formula_columns` başlık satırını sütun adlarıyla bulur. İlk veri satırında `=` ile başlayan hücreleri çevirir ve alt satırlarda aynı kalıbın sürdüğünü (satırdan bağımsız biçimle) kontrol eder. Diyalog her çeviriyi veri kümesindeki Excel değerleriyle karşılaştırır. `Session.add_formula_steps` adımları tek değişiklikte ekler ve bu sütunları kaynağın beklenen sütunlarından çıkarır.

**Excel'e bırak.** `to_template` formülü İngilizce ad ve ayırıcıya çevirir. Aynı tablonun göreli hücreleri `{Sütun}` / `{Sütun|-1}` olur. `excel_formula` adımı sütunu boş ekler. `Session.excel_formulas` dışa aktarırken şablonları toplar (yeniden adlandırmaları izler). `excel_out._write_formulas` her satıra çıktıdaki gerçek harflerle formül yazar.

**Satırlar arası fonksiyonlar.** ÖNCEKİ/SONRAKİ (`shift`), KÜMÜLATİF (`cumsum`), SIRA (`rank(method="min")`); isteğe bağlı grup sütunuyla `groupby`. Çevirici `D3-D2` → ÖNCEKİ, `TOPLA($D$2:D3)` → KÜMÜLATİF, `EĞERSAY($A$2:A3;A3)` → KÜMÜLATİF(1; …), `RANK` → SIRA kalıplarını tanır.

**Parametreler.** `run_settings["parameters"]` ve `run_settings["parameter_cells"]` (hücre → ad); şema sürümü değişmedi. Formül dili `{Ad}` belirtecini tanır. `Operation.uses_params` olan adımlara (hesapla, koşullu, kurallar) `__params__` verilir ve parametreler adım imzasına girer: değer değişince yalnız ilgili adımlar yeniden hesaplanır.

## 13c. Sürüm 3.6 eklemeleri

- **Dolu satırlar.** `calc` adımında `only_filled`: formüldeki sütunların hepsi boşsa sonuç None. `drop_empty_rows` adımı `ignore` dışındaki sütunların hepsi boş olan satırları atar. `add_formula_steps` kaynak tablonun başına bunu (formül sütunlarını yok sayarak) ekler. Böylece Excel'de aşağı çekilmiş formüllerin ürettiği "hayalet" satırlar gelmez; formül her gün verinin satır sayısı kadar uygulanır.
- **Şerit.** Üst çubuk (her zaman görünen işler) + `QTabWidget` içinde sekme başına bir `QToolBar`. Test, 1366 genişlikte her sekmenin sığdığını kontrol eder.
- **Tablo.** `FilterHeader(QHeaderView)` başlığa ▾ çizer, sağ kenardaki tıklamada `arrowClicked` yayınlar. Ctrl+F eşleşmeleri biçimlenmiş metin üzerinden bulunur (en fazla 20.000). Görünümde gizleme yalnız `setColumnHidden`; iş akışına girmez.
- **Yardım (ui/help.py).** Kılavuz markdown'u `QTextBrowser.setMarkdown` ile gösterilir; `SECTION_FOR` işlem anahtarını bölüm başlığına bağlar. PyInstaller paketine `docs` eklendi (`shiftflow.spec` datas). İlk açılış rehberi `QSettings("welcome_shown")`.
- **Pivot/grup seçenekleri.** `date_group` alanları gruplamadan önce etikete çevirir (`_date_group`). `show_as` yüzde hesabını Genel Toplam satır/sütununu ayırarak yapar. `_sort_top` gövdeyi sıralar, ilk N'i tutar ve toplam satırını en alta koyar (toplam/adet işlevlerinde yeniden hesaplar).
- **Doğrula (validate).** Veri değişmez. `on_fail="stop"` kontrolleri yalnız `session.strict()` bloğunda hata verir: `export` ve `ReportBuilder.build` içinde. Düzenlerken uyarıdır; böylece `_commit` doğrulaması adımı reddetmez. `strict` bayrağı adım imzasına girer, önbellek karışmaz.

## 13d. Sürüm 3.7 eklemeleri

- **Klasör kaynağı.** Kaynak yolu bir desen olabilir (`C:\Raporlar\toplama_*.xlsx`). `io.read_source` deseni görünce `read_folder` çağırır: dosyalar değiştirilme zamanına göre sıralanır, `~$` kilit dosyaları atlanır, sütunlar birleşimle alt alta eklenir, `Kaynak dosya` sütunu eklenir. Böylece bağlama, Rapor oluştur ve yükleme yollarının hepsi değişmeden klasörü destekler.
- **Rapor paketleri (engine/package.py).** Paket yalnız iş akışı yollarını (göreli) ve ayarları tutar. `run_package` her akışı ayrı `Session` ile açar ve `ReportBuilder.plan()` çağırır. Engelleyen kaynak varsa akışı atlar (tahminle geçmez). Sonra `build` eder. Açık Excel COM nesneleri ana iş parçacığına bağlı olduğu için paket arka plana alınmaz; ilerleme penceresi adım adım güncellenir. Birleşik mail `combined_draft` ile tüm çıktıları ekler.
- **Çıktı biçimi.** Sayfa seçeneklerinde `totals` (`SUBTOTAL(109,…)`, filtreye girmeyen satır) ve `rules` (openpyxl `CellIsRule`; tüm satır için `FormulaRule`). Kural değeri `{parametre}` olabilir; `Session._export` yazmadan önce çözer.
- **Excel'de aç.** Seçili veri kümesi `%TEMP%\ShiftFlow` altına yazılır ve `os.startfile` ile açılır.
- **Gösterge paneli (engine/dashboard.py, ui/dashboard_ui.py).** Kutucuk tanımı `run_settings["dashboard"]`. Hesap için `group` işlemi yeniden kullanılır (tarih gruplama, sıralama, ilk N). Grafikler ek kütüphane olmadan `QPainter` ile çizilir.
- **Sütun önerisi.** `MissingColumnError` en yakın sütunu `suggest_column` ile önerir: Türkçe küçük harf, baştaki kelime eşleşmesi, `difflib` benzerliği.

## 13e. Sürüm 3.8 eklemeleri

- **Çöp kutusu.** `library.trash` ve `archive.arc_trash` tabloları. Silme ve üzerine yazma (referans içeriği yenileme, arşivde aynı dönemi yeniden yazma) önce kaydın tam kopyasını JSON olarak çöp kutusuna koyar, sonra siler. Bu işlem aynı veritabanı işleminin (transaction) içinde yapılır. `restore` ad çakışmasında "(geri)" ekler. Arşivde geri yüklenen dönem şu an varsa önce o hâli çöp kutusuna taşınır. 30 günden eski kayıtlar açılışta `purge_trash` ile temizlenir.
- **Sütun dondurma.** Qt'nin "donmuş sütun" yöntemi: ana tablonun üstünde aynı modeli ve seçim modelini paylaşan ikinci bir `QTableView` yalnız ilk n sütunu gösterir. Dikey kaydırma iki yönlü bağlıdır, sütun genişlikleri izlenir.

## 13f. Sürüm 3.9: otomasyon

- **Komut satırı (shiftflow/cli.py).** `app.main` `--paket` veya `--akis` görünce Qt'yi hiç başlatmadan `cli.run` çağırır.
  - Dönem `--donem otomatik` ise ilk iş akışının vardiya tanımıyla `Session.auto_period` hesaplanır (bitimden sonraki 2 saatlik pay).
  - Rapor `run_package` ile oluşturulur.
  - Mail asla gönderilmez: `OutlookMailer.save_draft` (Taslaklar) veya `save_eml`.
  - Sorunlu akış varsa uyarı taslağı hazırlanır.
  - Kilit dosyası çakışan çalıştırmaları önler (3 saatten eskisi yok sayılır).
  - Günlük dosyası 2 MB'ı geçince döndürülür. Çıkış kodu 0/1/2.
- **Görev Zamanlayıcı.** `schtasks_commands` her vardiyanın bitiş saatine göre günlük `schtasks /Create` komutu üretir. Exe paketinde exe yolu, kaynak koddan çalışırken `pythonw.exe shiftflow_main.py` kullanılır (konsol açılmaz).
- **WMS teşhisi (engine/wms_probe.py).** pywinauto masaüstü nesnesi `desktop_factory` ile soyutlanır; testlerde sahte ağaç (tests/fake_desktop.py) kullanılır.
  - Tarama yığınla yapılır ve 3000 öğe / 25 derinlikle sınırlıdır.
  - Gizlilik kuralları: Win32'de pencere metni içerik olabileceği için yalnız düğme ve etiket adları yazılır. Giriş alanlarının değeri hiç yazılmaz. DataGrid/Table/List/Tree/Document içine girilmez.
  - Uygunluk ölçütü: adı okunan düğme/menü ≥ 5, giriş alanı ≥ 1 ve adsız oranı ≤ %50.
  - Teknoloji tahmini sınıf adlarından yapılır (WindowsForms10, HwndWrapper, SunAwt, TForm…).

## 13g. Sürüm 3.10: tarayıcı demosu (web/)

- **Neden mümkün:** Motor (`shiftflow/engine`) Qt'ye bağlı değildir ve Windows'a özgü kısımlar (COM, pywinauto) yalnız kullanıldıkları fonksiyonun içinde içe aktarılır. Bu yüzden aynı kod Pyodide ile tarayıcıda çalışır; motorda tek satır değişmedi.
- **Katmanlar:** `app.js` (ekran) → `sfweb.dispatch(komut, json)` (köprü) → `Session` (motor). Köprü her zaman JSON metin döner; hata `{"ok": false, "error", "detail"}` olur. Arayüz motorun iç yapısını bilmez.
- **İki arka uç:** `PyodideBackend` (yayın; Python tarayıcıda) ve `DevBackend` (`?dev=1`; aynı `sfweb.py` yerel test sunucusunda). İkisi aynı üç işlevi sunar: `call`, `putFile`, `getFile`. Bu sayede arayüz, Pyodide olmadan gerçek Chrome'da test edilebildi.
- **Dosyalar:** Yüklenen dosya Pyodide'nin sanal diskine (`/tmp/upload`) yazılır, motor oradan okur; Excel `/tmp/sfweb` altına yazılır ve tarayıcıya Blob olarak indirilir. Sanal disk bellektedir; sayfa kapanınca silinir.
- **Paketleme (`build_web.py`):** Motorun gerekli modülleri + `sfweb.py` tek zip; openpyxl/et_xmlfile tekerlekleri sitenin içinde; pandas/numpy Pyodide CDN'inden. `manifest.json` sürümleri sabitler.
- **Demoya özgü kararlar:** Örnek veri sentetiktir ve bilerek sorun içerir ('A Blok ' / 'a blok', listede olmayan iki personel, 0 adetli satırlar). "Yeni günün verisi" `bind_source` ile kaynağı değiştirir; adımlar aynı kalır. Excel'e aktarma katı doğrulamayla (`strict_validation`) yapılır.

## 14. Güvenlik ve gizlilik kararları

- Ağ erişimi yoktur; hiçbir modül internet kütüphanesi kullanmaz.
- Günlük dosyasına (`%LOCALAPPDATA%\ShiftFlow\shiftflow.log`) yalnızca hata türü ve kod konumu yazılır; hücre değerleri yazılmaz.
- JSON'da veri yoktur, yalnız tanım vardır. Ancak sütun adları ve filtre değerleri (örn. "Bölge = Marmara") tanımın parçası olduğu için JSON'da görünür.
- Açık Excel kitaplarına yalnızca okuma yapılır; hiçbir kitap değiştirilmez, kaydedilmez, kapatılmaz.
- Referans tablolar ve arşiv yalnızca bu bilgisayarda (`%LOCALAPPDATA%\ShiftFlow`) tutulur; iş akışı dosyasına veri yazılmaz.
- Mail yalnızca kullanıcının onayıyla gider; mail içeriğine hangi tablonun gireceğini kullanıcı seçer.
- Testler yalnız sentetik veri kullanır. `.gitignore` dosyası Excel ve CSV dosyalarının depoya girmesini engeller.

## 15. Kendinizi sınayın

1. Kullanıcı "Toplama" veri kümesine yeni filtre ekledi. Ona bağlı pivot neden kendiliğinden güncellenir? *(Girdiler veri kümesi adına bağlı; imza zinciri değişiyor.)*
2. Geri al neden yeniden hesaplama gerektirmez? *(Önbellek anahtarı imzadır; eski tanımın imzaları önbellekte duruyor.)*
3. Yeni gün raporu yüklenince eski sonuçlar nasıl geçersiz olur? *(Kaynak sürüm numarası artar → imzalar değişir.)*
4. Bir adım hata verirse kaynak dosyaya ne olur? *(Hiçbir şey. Dosya yalnızca okunur; değişiklik denemesi tanımın kopyası üzerinde yapılır ve geri alınır.)*
5. Neden NaN anahtarları elle benzersizleştiriyoruz? *(Pandas `merge` NaN'ları birbiriyle eşleştirir ve satır çoğaltır.)*
6. Yeni bir işlem türü eklemek için hangi dosyalara dokunulur? *(operations.py, dialogs.py, main_window.py, test dosyası.)*
7. `engine` neden Qt import etmez? *(Arayüzsüz çalıştırma, RPA ve test edilebilirlik için.)*
8. Formüle `__import__('os')` yazılırsa ne olur? *(Ayrıştırıcı tanımaz ve "Formül anlaşılamadı" der; kod çalışmaz.)*
9. WMS raporu "Kitap4" adıyla, üstünde 3 başlık satırıyla açıldı. ShiftFlow onu nasıl buluyor? *(Kitap adına bakmaz; ilk 30 satırda anahtar sütunların ≥ %80'inin bulunduğu satırı başlık kabul eder.)*
10. Dünkü rapor kapatılmadan bugünkü de açıldı. Ne olur? *(İki aday puanı neredeyse eşit → "birden çok uygun rapor"; kullanıcı seçer.)*
11. Kullanıcı raporu WMS'ten yenilemeyi unuttu. Nasıl yakalanır? *(İçerik özeti son başarılı çalıştırmayla aynı → "son çalıştırmayla aynı veri".)*
12. Bir pivot hata verirse çıktı dosyasının diğer sayfaları yine yazılır mı? *(Hayır. Hatalı veri kümesi varsa dosya hiç oluşturulmaz.)*
13. DÜŞEYARA'nın arama tablosuna yeni bir adım eklendi. DÜŞEYARA sonucu neden güncellenir? *(`refs` ile arama tablosunun imzası adım imzasına girer.)*
14. Saat 16:30'da varsayılan dönem neden Gündüz (08–16)? *(Akşam vardiyası başlayalı 120 dakikadan az zaman geçti; vardiya sonu raporu biten vardiya içindir.)*
15. Aynı vardiya iki kez oluşturulursa arşivde iki kayıt olur mu? *(Hayır. Önce o dönemin satırları silinir; kullanıcıya da sorulur.)*
16. Günlük tek WMS raporu Gece ve Gündüz için iki kez kullanıldı. Neden "aynı veri" uyarısı çıkmaz? *(Aynı gün ve kaynak dönem filtresiyle bölünüyor.)*
17. Mail kendiliğinden gönderilebilir mi? *(Hayır. `send` yalnızca önizlemede "Gönder" + onay ile çağrılır.)*
18. Şablondaki logo neden çıktıda yok? *(openpyxl resimleri koruyamaz; ShiftFlow şablon seçilirken uyarır.)*
19. Formülde `DÜŞEYARA([A]; "Personel"; 2; 0)` var. "Personel" tablosu neden silinemez? *(`referenced_tables` onu `calc` adımının `refs`'ine koyar; `dependents_of` bunu görür.)*
20. `=EĞERSAY(B:B;B2)` neden `EĞERSAY("BU"; ...)` olur? *(Aynı sayfadaki aralık, içinde bulunulan tablodur.)*
21. `=D2*$H$1` neden tam çevrilmez? *($H$1 sabit bir parametre hücresi; ShiftFlow tablosunda karşılığı yok, değer elle yazılmalı.)*
22. "Ege " içeren bir sütunla gruplama yapıldı. ShiftFlow değeri kendiliğinden düzeltir mi? *(Hayır. Uyarır ve sorar; onaylanırsa girdi tablosuna "Yazımı birleştir" adımı eklenir.)*
23. Arka plan görevinde neden `d.header.isChecked()` lambda içinde çağrılmamalı? *(Qt nesnesine başka iş parçacığından dokunmak tanımsız davranıştır; değer önceden okunur.)*
24. Kullanıcı uzun bir pivotta İptal'e bastı. İş akışı yarım mı kalır? *(Hayır. `Cancelled` bir sonraki adım sınırında yükselir, `_commit` eski tanıma döner.)*
25. Elektrik kesildi. Yapıştırılan veri de geri gelir mi? *(Evet. Yeniden okunamayan kaynakların verisi yerel yedeğe pickle olarak yazılır.)*
26. Excel'deki formüllü "Oran" sütunu adım olarak eklendi. Ertesi gün ham raporda "Oran" yok. Neden "sütun eksik" denmez? *(`add_formula_steps` onu kaynağın beklenen sütunlarından çıkarır.)*
27. "Excel'e bırak" sütunu sıralamadan sonra C'den A'ya taşındı. Formül doğru mu yazılır? *(Evet. Şablon sütun adıyla tutulur; harf dışa aktarırken çıktıdaki yere göre konur.)*
28. `ÖNCEKİ([Sayaç])` sonucu neden Sırala adımından etkilenir? *(Satırların o anki sırasına göre bir önceki satırı alır, Excel'deki gibi.)*
29. `{Hedef Oran}` 0,95'ten 0,90'a değişti. Neden bütün iş akışı yeniden hesaplanmaz? *(Parametreler yalnız `uses_params` adımlarının imzasına girer; diğer adımlar önbellekten gelir.)*
30. Kapalı bir adımın ürettiği sütunu sonraki adım kullanıyorsa ne olur? *(`_commit` doğrulamada hata görür ve kapatmayı reddeder.)*
31. Excel'de formüller 1000. satıra kadar çekilmiş, veri 300 satır. ShiftFlow kaç satır üretir? *(300. `drop_empty_rows` formül sütunlarını yok sayarak boş satırları atar.)*
32. "Raporu durdur" doğrulaması neden adım eklerken hata vermez? *(Yalnız `strict()` içinde, yani çıktı yazılırken hata olur; düzenlerken uyarıdır.)*
33. Pivotta "İlk 10" seçildi. Genel Toplam neyi gösterir? *(Toplam/adet işlevlerinde gösterilen 10 satırın toplamını; diğer işlevlerde toplam satırı gizlenir.)*
34. Görünümde gizlenen sütun Excel çıktısına yazılır mı? *(Evet. Gizleme yalnız tablonun görünümüdür, adım değildir.)*
35. Klasör kaynağına yarın yeni bir dosya eklenince iş akışında ne değiştirmek gerekir? *(Hiçbir şey; desen kayıtlı, her çalıştırmada klasör yeniden taranır.)*
36. Paketteki ikinci akışta sütun adı değişmiş. Paket ne yapar? *(O akışı "Atlandı" olarak bildirir, eşlemeyi tahmin etmez; diğerlerini çalıştırır.)*
37. Paket neden arka plan iş parçacığında çalışmaz? *(Açık Excel'e erişen COM nesneleri oluşturuldukları iş parçacığına bağlıdır.)*
38. Çıktıdaki toplam satırı Excel'de filtreleyince neden değişir? *(`SUBTOTAL(109,…)` yalnız görünen satırları toplar.)*
39. Referans tabloyu yeni içerikle yeniledim, eskisi yanlışmış. Geri dönülebilir mi? *(Evet; eski içerik "Referans tablo (eski içerik)" olarak çöp kutusundadır.)*
40. Arşivden geri yüklenen dönem şu anki dönemin üzerine yazarsa ne olur? *(Şu anki hâl de önce çöp kutusuna taşınır; ikisi arasında gidip gelinebilir.)*
41. Zamanlanmış çalıştırmada sütun adı değişmiş bir rapor gelirse ne olur? *(O akış atlanır, günlüğe ve "ShiftFlow uyarısı" taslağına yazılır; eşleme tahmin edilmez.)*
42. Komut satırı modu mail gönderebilir mi? *(Hayır. Yalnız Outlook taslağı veya .eml hazırlar.)*
43. WMS teşhisi neden win32 yönteminde giriş alanının adını yazmaz? *(Win32'de alanın "adı" içindeki metindir, yani veridir.)*
44. Tarayıcı demosu için motorda neden değişiklik gerekmedi? *(Motor Qt'den bağımsız; Windows'a özgü kütüphaneler yalnız kullanıldıkları fonksiyonun içinde içe aktarılıyor.)*
45. "Veri tarayıcıdan çıkmaz" iddiasını bir görüşmeciye nasıl kanıtlarsınız? *(Geliştirici araçlarının Ağ sekmesinde dosya yükleme ve Excel indirme sırasında hiç istek olmadığını gösteririm; hesaplama Pyodide ile tarayıcıda.)*
46. Arayüzü Pyodide olmadan nasıl test ettiniz? *(Arayüz yalnız `dispatch` ile konuşuyor; aynı `sfweb.py`'yi yerel test sunucusunda çalıştıran ikinci bir arka uçla Chrome'da uçtan uca test ettim.)*

