"""Tarayıcı demosu köprüsü (web/sfweb.py) ve yayın paketinin testleri. Sentetik veri."""

import json
import os
import subprocess
import sys
import zipfile

import pytest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
sys.path.insert(0, WEB)


@pytest.fixture()
def sf(tmp_path, monkeypatch):
    import sfweb
    monkeypatch.setattr(sfweb, "WORK_DIR", str(tmp_path))
    sfweb.reset()

    def call(name, args=None):
        return json.loads(sfweb.dispatch(name, json.dumps(args)))
    return call


def test_meta_and_unknown_command(sf):
    m = sf("meta")
    assert m["ok"] and m["version"] and "eq" in m["conditions"]
    bad = sf("yok_boyle")
    assert not bad["ok"] and "Bilinmeyen komut" in bad["error"]


def test_sample_is_synthetic_and_has_planted_problems():
    import sfweb
    data, staff = sfweb.sample_frames(0)
    assert {"A Blok ", "a blok"} <= set(data["Bölge"])
    assert not set(data["Personel ID"]) <= set(staff["Personel ID"])  # listede olmayan personel var
    d2, _ = sfweb.sample_frames(1)
    assert d2["Tarih"].min().day == 3  # ertesi gün


def test_demo_flow_variants_fix_and_export(sf, tmp_path):
    assert sf("build_demo_flow")["ok"]
    st = sf("state", {"dataset": "Bölge özeti"})
    assert "Bölge" in st["steps"][0]["variants"]
    names = [r[0] for r in st["preview"]["rows"]]
    assert "A Blok " in names and "a blok" in names
    assert sf("fix_variants", {"dataset": "Bölge özeti", "index": -1, "columns": ["Bölge"]})["ok"]
    st = sf("state", {"dataset": "Bölge özeti"})
    assert st["steps"][0]["variants"] == {}
    assert [r[0] for r in st["preview"]["rows"]] == ["A Blok", "B Blok", "Soğuk Oda", "Yüksek Raf", "Genel Toplam"]
    ex = sf("export")
    assert ex["ok"] and os.path.exists(ex["path"])
    import openpyxl
    assert "Bölge özeti" in openpyxl.load_workbook(ex["path"]).sheetnames


def test_bad_step_is_rejected_with_suggestion_and_not_added(sf):
    sf("load_sample")
    before = sf("state", {"dataset": "Vardiya verisi"})["steps"]
    r = sf("add_step", {"dataset": "Vardiya verisi", "op": "calc", "params": {"name": "X", "formula": "[Toplanan] * 2"}})
    assert not r["ok"] and "Toplanan Adet" in r["error"]
    assert len(sf("state", {"dataset": "Vardiya verisi"})["steps"]) == len(before)


def test_stop_validation_blocks_export_only(sf):
    sf("load_sample")
    r = sf("add_step", {"dataset": "Vardiya verisi", "op": "validate",
                        "params": {"checks": [{"check": "range", "column": "Hatalı Adet", "max": "1", "on_fail": "stop"}]}})
    assert r["ok"]  # düzenlerken yalnız uyarı
    st = sf("state", {"dataset": "Vardiya verisi"})
    assert any("⛔" in w for w in st["steps"][-1]["warnings"])
    ex = sf("export")
    assert not ex["ok"] and "durduruldu" in ex["error"]


def test_next_day_reruns_same_steps(sf):
    sf("build_demo_flow")
    n0 = sf("state", {"dataset": "Vardiya verisi"})
    r = sf("next_day")
    assert r["ok"] and r["date"] == "03.11.2026"
    n1 = sf("state", {"dataset": "Vardiya verisi"})
    assert len(n1["steps"]) == len(n0["steps"])
    assert n1["preview"]["rows"][0][0].startswith("03.11.2026")


def test_undo_toggle_move_delete(sf):
    sf("load_sample")
    d = "Vardiya verisi"
    sf("add_step", {"dataset": d, "op": "filter", "params": {"conditions": [{"column": "Vardiya", "op": "eq", "value": "Gece"}]}})
    total = lambda: sf("state", {"dataset": d})["preview"]["total"]
    night = total()
    sf("toggle_step", {"dataset": d, "index": 0})
    assert total() > night
    sf("toggle_step", {"dataset": d, "index": 0})
    sf("add_step", {"dataset": d, "op": "sort", "params": {"keys": [{"column": "Toplanan Adet", "ascending": False}]}})
    assert sf("move_step", {"dataset": d, "index": 1, "delta": -1})["ok"]
    assert sf("state", {"dataset": d})["steps"][1]["op"] == "sort"
    sf("delete_step", {"dataset": d, "index": 0})
    sf("undo")
    assert len(sf("state", {"dataset": d})["steps"]) == 3


def test_upload_csv_and_xlsx(sf, tmp_path):
    p = tmp_path / "test.csv"
    p.write_text("Ürün;Adet\nKalem;10\nDefter;5\n", encoding="utf-8")
    r = sf("load_file", {"path": str(p), "name": "test"})
    assert r["ok"] and r["focus"] == "test"
    assert sf("state", {"dataset": "test"})["preview"]["rows"] == [["Kalem", 10], ["Defter", 5]]
    sf("build_demo_flow")
    x = sf("export")["path"]
    assert len(sf("sheets", {"path": x})["sheets"]) == 4
    r = sf("load_file", {"path": x, "name": "rapor", "sheet": "Bölge özeti"})
    assert r["ok"]


def test_preview_cells_are_json_friendly():
    import numpy as np
    import pandas as pd
    import sfweb
    assert sfweb._cell(np.int64(3)) == 3 and sfweb._cell(3) == 3
    assert sfweb._cell(np.float64("nan")) is None and sfweb._cell(2.5) == 2.5
    assert sfweb._cell(pd.Timestamp("2026-11-10")) == "10.11.2026"
    assert sfweb._cell(pd.Timestamp("2026-11-10 07:05")) == "10.11.2026 07:05"


def test_build_package_imports_without_windows_modules(tmp_path):
    import build_web
    z = tmp_path / "e.zip"
    build_web.engine_zip(str(z))
    names = zipfile.ZipFile(z).namelist()
    assert "sfweb.py" in names and "shiftflow/engine/session.py" in names
    assert not any(n.endswith(("wms_probe.py", "excel_live.py", "mailer.py", "archive.py")) for n in names)
    assert not any("/ui/" in n for n in names)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import sfweb, json; "
            "r = json.loads(sfweb.dispatch('build_demo_flow')); assert r['ok'], r; print('ok')")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(z)], capture_output=True, text=True,
                         cwd=str(tmp_path), env={**os.environ, "SFWEB_DIR": str(tmp_path)})
    assert out.stdout.strip() == "ok", out.stderr
