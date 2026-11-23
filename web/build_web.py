"""Tarayıcı demosunun yayın klasörünü (web/dist) hazırlar.

    python web/build_web.py

Çıktı yalnızca statik dosyalardır; sunucu gerekmez. Klasörün içeriği olduğu gibi
Cloudflare Pages'e (veya herhangi bir statik barındırmaya) yüklenir.

Yapılanlar:
1. index.html, style.css, app.js kopyalanır.
2. Motor (shiftflow/__init__.py + shiftflow/engine/*.py) ve sfweb.py tek bir
   zip'e konur. Windows'a özgü modüller (WMS taraması, açık Excel, e-posta)
   tarayıcıda kullanılmadığı için dahil edilmez.
3. openpyxl ve et_xmlfile tekerlekleri (saf Python) web/vendor/wheels'ten
   (SHA-256 denetimiyle) kopyalanır; derleme ağ gerektirmez, yalnız Python 3.
4. Pyodide ve pandas/numpy, depodaki web/vendor/pyodide klasöründen pyodide/
   altına kopyalanır (SHA-256 denetimiyle). Sayfa hiçbir dış adrese istek atmaz.
5. manifest.json: Pyodide sürümü + dosya adları.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(HERE, "dist")

# Pyodide sürümü ve kullanılan paketleri: dosyalar web/vendor/pyodide klasöründedir
# (yükseltme adımları oradaki README.md'de).
PYODIDE_VERSION = "314.0.8"
PYODIDE_PAKETLERI = ["numpy", "pandas", "python-dateutil", "pytz", "six"]
PYODIDE_CEKIRDEK = ["pyodide.js", "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm",
                    "python_stdlib.zip", "pyodide-lock.json"]
VENDOR = os.path.join(HERE, "vendor", "pyodide")
WHEELS = ["openpyxl==3.1.5", "et_xmlfile==2.0.0"]
# Tarayıcıda kullanılmayan modüller: Windows'a özgü (WMS, açık Excel, Outlook)
# veya yerel disk/SQLite isteyen (kütüphane, arşiv, kurtarma, paket, otomatik çalıştırma).
SKIP = {"wms_probe.py", "excel_live.py", "mailer.py", "library.py", "archive.py", "recovery.py",
        "autorun.py", "package.py"}
STATIC = ["index.html", "style.css", "app.js", "_headers"]


def engine_zip(path: str):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(ROOT, "shiftflow", "__init__.py"), "shiftflow/__init__.py")
        for f in sorted(glob.glob(os.path.join(ROOT, "shiftflow", "engine", "*.py"))):
            if os.path.basename(f) not in SKIP:
                z.write(f, "shiftflow/engine/" + os.path.basename(f))
        z.write(os.path.join(HERE, "sfweb.py"), "sfweb.py")


def _sha_listesi(klasor: str) -> dict[str, str]:
    sonuc = {}
    with open(os.path.join(klasor, "SHA256SUMS"), encoding="utf-8") as f:
        for satir in f:
            if satir.strip():
                h, ad = satir.split(maxsplit=1)
                sonuc[ad.strip().lstrip("*")] = h
    return sonuc


def wheels(target: str, offline_dir: str | None) -> list[str]:
    """Tekerlekleri kopyalar. Varsayılan kaynak depodaki web/vendor/wheels (SHA-256 denetimli)."""
    os.makedirs(target, exist_ok=True)
    kaynak = offline_dir or os.path.join(HERE, "vendor", "wheels")
    beklenen = _sha_listesi(kaynak) if offline_dir is None else {}
    for spec in WHEELS:
        ad, surum = spec.split("==")
        bul = glob.glob(os.path.join(kaynak, f"{ad}-{surum}-*.whl"))
        if len(bul) != 1:
            raise SystemExit(f"{spec} tekerleği bulunamadı: {kaynak}")
        if beklenen and _sha256(bul[0]) != beklenen.get(os.path.basename(bul[0])):
            raise SystemExit(f"Tekerlek doğrulanamadı: {os.path.basename(bul[0])}")
        shutil.copy(bul[0], target)
    return sorted("wheels/" + os.path.basename(f) for f in glob.glob(os.path.join(target, "*.whl")))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def pyodide(target: str):
    """Depodaki Pyodide alt kümesini SHA-256 denetimiyle yayın klasörüne kopyalar."""
    beklenen = _sha_listesi(VENDOR)
    with open(os.path.join(VENDOR, "pyodide-lock.json"), encoding="utf-8") as f:
        lock = json.load(f)
    if lock.get("info", {}).get("version") not in (None, PYODIDE_VERSION):
        raise SystemExit(f"pyodide-lock.json sürümü {lock['info']['version']}, beklenen {PYODIDE_VERSION}")
    dosyalar = list(PYODIDE_CEKIRDEK)
    for ad in PYODIDE_PAKETLERI:
        paket = lock["packages"][ad]
        dosyalar.append(paket["file_name"])
        beklenen.setdefault(paket["file_name"], paket["sha256"])
        if beklenen[paket["file_name"]] != paket["sha256"]:
            raise SystemExit(f"{paket['file_name']}: SHA256SUMS ile pyodide-lock.json uyuşmuyor")
    os.makedirs(target, exist_ok=True)
    for ad in dosyalar:
        src = os.path.join(VENDOR, ad)
        if ad not in beklenen or _sha256(src) != beklenen[ad]:
            raise SystemExit(f"Pyodide dosyası doğrulanamadı: {ad}")
        shutil.copy(src, target)


def main(offline_dir: str | None = None):
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    for f in STATIC:
        src = os.path.join(HERE, f)
        if os.path.exists(src):
            shutil.copy(src, DIST)
    engine_zip(os.path.join(DIST, "shiftflow_engine.zip"))
    pyodide(os.path.join(DIST, "pyodide"))
    whl = wheels(os.path.join(DIST, "wheels"), offline_dir)
    if len(whl) != len(WHEELS):
        raise SystemExit(f"Beklenen {len(WHEELS)} tekerlek, bulunan {len(whl)}: {whl}")
    with open(os.path.join(DIST, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"pyodide": PYODIDE_VERSION, "packages": PYODIDE_PAKETLERI, "engine": "shiftflow_engine.zip", "wheels": whl}, f, indent=2)
    total = sum(os.path.getsize(p) for p in glob.glob(os.path.join(DIST, "**", "*"), recursive=True) if os.path.isfile(p))
    print(f"Hazır: {DIST}  ({total / 1024:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
