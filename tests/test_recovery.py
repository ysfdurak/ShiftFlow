"""Otomatik yedek ve çökme sonrası kurtarma."""

import os

import pandas as pd
import pytest

from shiftflow.engine.recovery import Recovery
from shiftflow.engine.session import Session

DF = pd.DataFrame({"Kod": ["001", "002"], "Miktar": [5, 7]})


def _session():
    s = Session()
    s.add_source("Yapıştırılan", DF, kind="paste")
    s.add_step("Yapıştırılan", "calc", {"name": "İki kat", "formula": "[Miktar] * 2"})
    return s


def test_save_restore_roundtrip(tmp_path):
    r = Recovery(str(tmp_path / "k"))
    s = _session()
    assert r.save(s, "C:/akis.json")
    assert not r.save(s, "C:/akis.json")  # değişiklik yoksa yeniden yazmaz
    meta = r.pending()
    assert meta["datasets"] == 1 and meta["workflow_path"] == "C:/akis.json"
    s2 = Session()
    missing = Recovery(str(tmp_path / "k")).restore(s2)
    assert missing == []
    out = s2.result("Yapıştırılan")
    assert out["İki kat"].tolist() == [10, 14]
    assert out["Kod"].tolist() == ["001", "002"]  # baştaki sıfırlar korunur
    assert s2.dirty


def test_data_rewritten_only_when_changed(tmp_path):
    r = Recovery(str(tmp_path / "k"))
    s = _session()
    r.save(s)
    pkl = [f for f in os.listdir(r.folder) if f.endswith(".pkl")][0]
    t0 = os.path.getmtime(os.path.join(r.folder, pkl))
    os.utime(os.path.join(r.folder, pkl), (t0 - 100, t0 - 100))
    s.add_step("Yapıştırılan", "sort", {"keys": [{"column": "Miktar", "ascending": False}]})
    assert r.save(s)
    assert os.path.getmtime(os.path.join(r.folder, pkl)) == pytest.approx(t0 - 100)


def test_clear_and_corrupt(tmp_path):
    r = Recovery(str(tmp_path / "k"))
    r.save(_session())
    r.clear()
    assert r.pending() is None
    os.makedirs(r.folder)
    with open(r.meta_path, "w") as fh:
        fh.write("{bozuk")
    assert r.pending() is None


# ---------------------------------------------------------------- arayüz
@pytest.fixture
def no_modal(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)


def test_window_autosaves_and_offers_recovery(qtbot, tmp_path, no_modal):
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui.main_window import MainWindow
    rec = Recovery(str(tmp_path / "k"))
    w = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")), recovery=rec)
    qtbot.addWidget(w)
    w.session.add_source("T", DF)
    w.refresh_all("T")
    w.show()
    w.autosave()
    assert rec.pending() is not None
    # "çökme": pencere kapanmadan yeni pencere açılır
    w2 = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")), recovery=Recovery(str(tmp_path / "k")))
    qtbot.addWidget(w2)
    assert w2.offer_recovery()
    assert "T" in w2.session.workflow.datasets and len(w2.session.result("T")) == 2
    # kaydedince yedek silinir
    w2.workflow_path = str(tmp_path / "a.json")
    w2.save_workflow()
    assert w2.recovery.pending() is None
