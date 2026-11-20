"""Rapor paketleri: birden çok iş akışını aynı dönem için sırayla çalıştırma."""

import os

import pandas as pd
import pytest

from shiftflow.engine.package import ReportPackage, combined_draft, run_package
from shiftflow.engine.session import Session


def _workflow(tmp_path, name, df, out_dir, missing=False):
    src = tmp_path / f"{name}.xlsx"
    df.to_excel(src, index=False)
    s = Session()
    s.add_source("Veri", df, path=str(src))
    s.add_step("Veri", "calc", {"name": "İki", "formula": "[Adet] * 2"})
    s.set_run_settings({"output_dir": str(out_dir), "file_name": name, "open_after": False})
    s.workflow.name = name
    p = tmp_path / f"{name}.json"
    s.save_workflow(str(p))
    if missing:
        os.remove(src)
    return str(p)


@pytest.fixture
def pkg(tmp_path):
    out = tmp_path / "cikti"
    out.mkdir()
    df = pd.DataFrame({"Kod": ["a", "b"], "Adet": [1, 2]})
    wfs = [_workflow(tmp_path, "Toplama", df, out), _workflow(tmp_path, "Sevkiyat", df, out, missing=True),
           _workflow(tmp_path, "Stok", df, out)]
    return ReportPackage(name="Vardiya sonu", workflows=wfs), out


def test_save_load_relative(tmp_path, pkg):
    p, _ = pkg
    path = tmp_path / ("paket" + ".sfpaket.json")
    p.save(str(path))
    assert '"Toplama.json"' in path.read_text(encoding="utf-8")
    q = ReportPackage.load(str(path))
    assert q.workflows == p.workflows and q.name == "Vardiya sonu"


def test_run_skips_problem_and_continues(pkg):
    p, out = pkg
    seen = []
    res = run_package(p, None, None, None, None, progress=lambda i, n, t: seen.append((i, n, t)))
    assert [r.status for r in res] == ["ok", "skipped", "ok"]
    assert len(seen) == 3
    assert "Veri" in res[1].message
    assert all(os.path.exists(r.path) for r in res if r.status == "ok")
    assert sorted(os.listdir(out)) == sorted(os.path.basename(r.path) for r in res if r.status == "ok")


def test_stop_on_error(pkg):
    p, _ = pkg
    p.stop_on_error = True
    assert [r.status for r in run_package(p, None, None, None, None)] == ["ok", "skipped", "not_run"]


def test_combined_mail_has_all_attachments(pkg):
    p, _ = pkg
    p.mail = {"enabled": True, "to": "vardiya@ornek.com"}
    res = run_package(p, None, None, None, None)
    d = combined_draft(p, res)
    assert d.to == ["vardiya@ornek.com"] and len(d.attachments) == 2
    assert "Sevkiyat" in d.html and "Atlandı" in d.html
    assert all(r.draft is None for r in res)


def test_package_dialog_runs_and_shows_results(qtbot, tmp_path, pkg, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QDialog, QMessageBox
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui import package_dialogs as pd_
    from shiftflow.ui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    shown = {}
    monkeypatch.setattr(pd_.ResultsDialog, "exec", lambda self: shown.setdefault("r", self) and QDialog.Accepted)
    p, _ = pkg
    w = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(w)
    d = pd_.PackageDialog(w, w.settings)
    qtbot.addWidget(d)
    d.set_package(p)
    assert d.package().workflows == p.workflows
    d.run()
    r = shown["r"]
    assert [x.status for x in r.results] == ["ok", "skipped", "ok"]
    assert r.table.cellWidget(1, 3).text() == "Akışı aç"
