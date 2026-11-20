"""Tarayıcı demosunun yayın klasörünü (web/dist) hazırlar.

    python web/build_web.py

Çıktı yalnızca statik dosyalardır; sunucu gerekmez. Klasörün içeriği olduğu gibi
Cloudflare Pages'e (veya herhangi bir statik barındırmaya) yüklenir.

Yapılanlar:
1. index.html, style.css, app.js kopyalanır.
2. Motor (shiftflow/__init__.py + shiftflow/engine/*.py) ve sfweb.py tek bir
   zip'e konur. Windows'a özgü modüller (WMS taraması, açık Excel, e-posta)
   tarayıcıda kullanılmadığı için dahil edilmez.
3. openpyxl ve et_xmlfile tekerlekleri (saf Python) PyPI'den indirilip
   klasöre konur; tarayıcı bunları PyPI'ye gitmeden sitenizden yükler.
4. manifest.json: Pyodide sürümü + dosya adları.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(HERE, "dist")

# Pyodide sürümü: pandas/numpy bu sürümün CDN'inden gelir. Değiştirirseniz
# README_WEB.md'deki deneme listesini yeniden çalıştırın.
PYODIDE_VERSION = "314.0.7"
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


def wheels(target: str, offline_dir: str | None) -> list[str]:
    os.makedirs(target, exist_ok=True)
    if offline_dir:
        for f in glob.glob(os.path.join(offline_dir, "*.whl")):
            shutil.copy(f, target)
    else:
        subprocess.check_call([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                               "-d", target, *WHEELS])
    return sorted("wheels/" + os.path.basename(f) for f in glob.glob(os.path.join(target, "*.whl")))


def main(offline_dir: str | None = None):
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    for f in STATIC:
        src = os.path.join(HERE, f)
        if os.path.exists(src):
            shutil.copy(src, DIST)
    engine_zip(os.path.join(DIST, "shiftflow_engine.zip"))
    whl = wheels(os.path.join(DIST, "wheels"), offline_dir)
    if len(whl) != len(WHEELS):
        raise SystemExit(f"Beklenen {len(WHEELS)} tekerlek, bulunan {len(whl)}: {whl}")
    with open(os.path.join(DIST, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"pyodide": PYODIDE_VERSION, "engine": "shiftflow_engine.zip", "wheels": whl}, f, indent=2)
    total = sum(os.path.getsize(p) for p in glob.glob(os.path.join(DIST, "**", "*"), recursive=True) if os.path.isfile(p))
    print(f"Hazır: {DIST}  ({total / 1024:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
