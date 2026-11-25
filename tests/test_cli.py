"""Komut satırı modu: pencere açmadan paket / iş akışı çalıştırma."""

import os
from datetime import datetime

import pandas as pd
import pytest

from shiftflow import cli
from shiftflow.engine.package import ReportPackage
from shiftflow.engine.session import Session


class FakeOutlook:
    def __init__(self):
        self.saved, self.sent = [], []

    def save_draft(self, d):
        self.saved.append(d)

    def send(self, d):  # komut satırı asla göndermemeli
        self.sent.append(d)


def _wf(tmp_path, name, missing=False, mail=None):
    out = tmp_path / "cikti"
    out.mkdir(exist_ok=True)
    src = tmp_path / f"{name}.xlsx"
    df = pd.DataFrame({"Kod": ["a", "b"], "Adet": [1, 2]})
    df.to_excel(src, index=False)
    s = Session()
    s.add_source("Veri", df, path=str(src))
    rs = {"output_dir": str(out), "file_name": "{akis} {tarih} {vardiya}", "open_after": False}
    if mail:
        rs["mail"] = mail
    s.set_run_settings(rs)
    s.workflow.name = name
    p = tmp_path / f"{name}.json"
    s.save_workflow(str(p))
    if missing:
        os.remove(src)
    return str(p)


def test_single_workflow_eml(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    p = _wf(tmp_path, "Toplama", mail={"enabled": True, "to": "a@b.com"})
    rc = cli.run(["--akis", p, "--donem", "2026-11-10:Gece", "--mail", "eml"], provider=None, library=None)
    assert rc == 0
    files = sorted(os.listdir(tmp_path / "cikti"))
    assert any(f.endswith(".xlsx") and "Gece" in f for f in files) and any(f.endswith(".eml") for f in files)
    log = open(cli.log_path(), encoding="utf-8").read()
    assert "Dönem: 10.11.2026" in log and "Oluşturuldu" in log


def test_package_auto_period_outlook_never_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    pkg = ReportPackage(name="Paket", workflows=[_wf(tmp_path, "A"), _wf(tmp_path, "B", missing=True)],
                        mail={"enabled": True, "to": "vardiya@ornek.com"})
    path = tmp_path / "p.sfpaket.json"
    pkg.save(str(path))
    ol = FakeOutlook()
    rc = cli.run(["--paket", str(path), "--mail", "outlook"], outlook=ol, now=datetime(2026, 11, 10, 8, 15))
    assert rc == 1  # biri atlandı
    assert ol.sent == []
    subjects = [d.subject for d in ol.saved]
    assert any("uyarısı" in x for x in subjects) and len(ol.saved) == 2  # birleşik + uyarı
    log = open(cli.log_path(), encoding="utf-8").read()
    assert "Gece" in log and "Atlandı" in log  # 08:15'te biten vardiya: Gece


def test_bad_inputs_and_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    assert cli.run(["--akis", str(tmp_path / "yok.json")]) == 2
    p = _wf(tmp_path, "T")
    assert cli.run(["--akis", p, "--donem", "2026-11-10:Öğle"]) == 2
    with cli._Lock():
        assert cli.run(["--akis", p, "--donem", "2026-11-10"]) == 1  # başka çalıştırma sürüyor
    assert cli.wants_cli(["--paket", "x"]) and not cli.wants_cli(["a.json"])


def test_app_main_routes_to_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    from shiftflow import app
    called = {}
    monkeypatch.setattr(cli, "run", lambda args: called.setdefault("args", args) and 0)
    assert app.main(["ShiftFlow", "--akis", "x.json"]) == 0
    assert called["args"] == ["--akis", "x.json"]


def test_parse_period_formats():
    s = Session()
    assert cli.parse_period("10.11.2026:Akşam", s).label.startswith("10.11.2026")
    assert cli.parse_period("2026-11-10", s).shift is None
    with pytest.raises(ValueError):
        cli.parse_period("dün", s)


def test_schtasks_commands_and_dialog(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from shiftflow.ui import automation_dialogs as ad
    cmds = ad.schtasks_commands("C:\\Rapor\\Vardiya sonu.sfpaket.json", "paket",
                                [{"name": "Gece", "start": "00:00", "end": "08:00"},
                                 {"name": "Akşam", "start": "16:00", "end": "00:00"}], 15, "outlook", "Vardiya sonu")
    assert '/ST 08:15' in cmds[0] and '/ST 00:15' in cmds[1]
    assert '/TN "ShiftFlow - Vardiya sonu - Gece"' in cmds[0]
    assert '--paket \\"C:\\Rapor\\Vardiya sonu.sfpaket.json\\" --donem otomatik --mail outlook' in cmds[0]
    # Kabuk yok: tehlikeli karakterli vardiya/dosya adı tek argüman olarak kalır, komut olarak yorumlanmaz.
    kotu = ad.schtasks_args("C:\\R\\a.json", "akis", [{"name": 'G" & calc & "', "start": "00:00", "end": "08:00"}],
                            0, "outlook & calc", 'x" | del')
    assert kotu[0][:7] == ["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", 'ShiftFlow - x" | del - G" & calc & "']
    assert len(kotu[0]) == 11 and kotu[0][-1].endswith("--mail yok")
    from PySide6.QtWidgets import QMessageBox
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui.main_window import MainWindow
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    w = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(w)
    p = _wf(tmp_path, "Toplama")
    d = ad.ScheduleDialog(w, w.settings)
    qtbot.addWidget(d)
    d.target.setText(p)
    assert len(d.cmds.toPlainText().splitlines()) == 3 and "--akis" in d.cmds.toPlainText()
    d.try_now()
    assert "Oluşturuldu" in d.status.text()


def test_probe_dialog_with_fake_desktop(qtbot):
    pytest.importorskip("PySide6")
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from fake_desktop import winforms_wms
    from shiftflow.ui.automation_dialogs import WmsProbeDialog
    d = WmsProbeDialog(desktop_factory=winforms_wms)
    qtbot.addWidget(d)
    assert d.windows.count() == 1
    d.run()
    assert d.result.verdict == "uygun" and "UYGUN" in d.status.text() and "Listele" in d.text.toPlainText()
