"""WMS ekran teşhisi (sahte pencere ağaçlarıyla)."""

import os

from fake_desktop import java_wms, winforms_wms

from shiftflow.engine import wms_probe as wp


def test_list_windows_skips_untitled():
    wins = wp.list_windows(winforms_wms)
    assert [w["title"] for w in wins] == ["WMS — Toplama Raporu"] and wins[0]["handle"] == 42


def test_good_wms_is_suitable_and_no_data_recorded(tmp_path):
    win = wp.list_windows(winforms_wms)[0]
    p = wp.probe(win, winforms_wms)
    assert p.verdict == "uygun" and p.best_backend == "uia" and p.framework == ".NET WinForms"
    r = p.results["uia"]
    assert r.menus == 3 and r.inputs == 3
    text = p.report_text()
    assert "Başlangıç tarihi" in text and "Listele" in text
    assert "10.11.2026 00:00" not in text  # alan değeri okunmaz (win32'de de)
    assert "Ali Yılmaz" not in text and "içerik okunmadı" in text  # tablo verisi okunmaz
    path = wp.save_report(p, str(tmp_path))
    assert os.path.exists(path) and open(path, encoding="utf-8").read().startswith("ShiftFlow")


def test_java_without_accessibility_is_not_suitable():
    win = wp.list_windows(java_wms)[0]
    p = wp.probe(win, java_wms)
    assert p.verdict == "uygun_degil" and p.framework.startswith("Java")
    assert "Java Access Bridge" in p.framework_hint


def test_missing_window_reported():
    p = wp.probe({"title": "Yok", "handle": 999}, winforms_wms)
    assert all(r.error for r in p.results.values()) and p.verdict == "uygun_degil"


def test_available_message_on_linux():
    ok, msg = wp.available()
    assert ok or "Windows" in msg or "pywinauto" in msg
