# Pyodide (depoda tutulan alt küme)

Tarayıcı demosu Python'u (Pyodide) ve pandas/numpy'ı **kendi adresinden** yükler; CDN'e
veya başka bir siteye istek atılmaz. Bu klasör, Pyodide 314.0.8 sürüm paketinden yalnız
demonun ihtiyaç duyduğu dosyaları içerir (yaklaşık 21 MB).

- Kaynak: https://github.com/pyodide/pyodide/releases/download/314.0.8/pyodide-314.0.8.tar.bz2
- Paketin SHA-256 değeri: `ce4ac9b450c22b1cee278ddda7c12ee5b83acb1f967d0675fff189be6739e574`
- Dosyaların SHA-256 değerleri: `SHA256SUMS`. Tekerleklerin (.whl) değerleri `pyodide-lock.json`
  içindekilerle aynıdır; `python web/build_web.py` her derlemede bunu denetler.

## Sürüm yükseltme

1. Yeni sürüm paketini indirip SHA-256 değerini sürüm sayfasındakiyle karşılaştırın.
2. Bu klasördeki dosyaları yeni paketteki aynı adlı dosyalarla değiştirin (tekerlek adları sürümle değişir).
3. `sha256sum * > SHA256SUMS` (README, lisans ve SHA256SUMS hariç).
4. `web/build_web.py` içindeki `PYODIDE_VERSION` ve `PYODIDE_PAKETLERI` listesini güncelleyin.
5. `python web/build_web.py && python web/e2e_pyodide.py` ile tarayıcıda deneyin.

## Lisanslar

- Pyodide: Mozilla Public License 2.0 (`LICENSE-pyodide.txt`). Dosyalar değiştirilmeden dağıtılır.
- numpy, pandas: BSD-3-Clause. python-dateutil: Apache-2.0 / BSD-3-Clause. pytz, six: MIT.
  Lisans metinleri her tekerleğin içindeki `*.dist-info/` klasöründedir.

Bu dosyalar ShiftFlow'un PolyForm Shield lisansına tabi değildir; kendi lisanslarıyla gelir.
