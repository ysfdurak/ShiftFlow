"""Şerit sekmeleri, Ctrl+F, görünümde gizleme, başlıktaki filtre oku."""

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog, QMessageBox  # noqa: E402

from shiftflow.engine.library import ReportLibrary  # noqa: E402
from shiftflow.ui import dialogs as dlg  # noqa: E402
from shiftflow.ui.main_window import MainWindow  # noqa: E402

DF = pd.DataFrame({"Kod": ["A1", "B2", "a1x", "C3"], "Bölge": ["Ege", "Marmara", "Ege", "İç Anadolu"],
                   "Adet": [1, 2, 3, 4]})


@pytest.fixture
def w(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    win = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(win)
    win.resize(1366, 728)
    win.session.add_source("T", DF)
    win.refresh_all("T")
    win.show()
    return win


def test_ribbon_has_all_step_actions(w):
    in_ribbon = {a for bar in w.ribbon_bars.values() for a in bar.actions()}
    for a in list(w.step_actions.values()) + list(w.extra_step_actions.values()) + [w.a_group, w.a_pivot,
                                                                                    w.a_join, w.a_xl_columns]:
        assert a in in_ribbon, a.text()
    # dar ekranda (1366 px, %100 ölçek) her sekme sığmalı (gizli düğme kalmasın).
    # Ekransız Windows'ta yazı tipi piksel boyu farklı çıkabildiği için ölçü yazı yüksekliğine göre ölçeklenir
    # (9 pt Segoe UI / DejaVu, 96 dpi'de ~16 px).
    fm_h = w.fontMetrics().height()
    scale = max(1.0, fm_h / 16)
    for title, bar in w.ribbon_bars.items():
        w.ribbon.setCurrentWidget(bar)
        need = sum(bar.widgetForAction(a).sizeHint().width() for a in bar.actions() if bar.widgetForAction(a))
        assert need < 1366 * scale, f"{title}: {need} px, yazı yüksekliği {fm_h}, dpi {w.logicalDpiX()}"


def test_find_next_and_prev(w):
    w.open_find()
    w.find_edit.setText("a1")  # harf duyarsız: A1, a1x
    assert w.find_info.text() == "1 / 2"
    assert w.table.currentIndex().row() == 0
    w.find_next(1)
    assert w.table.currentIndex().row() == 2 and w.find_info.text() == "2 / 2"
    w.find_next(1)
    assert w.find_info.text() == "1 / 2"
    w.find_edit.setText("yok")
    assert w.find_info.text() == "bulunamadı"
    w.close_find()
    assert not w.find_bar.isVisible()


def test_hide_column_is_view_only(w):
    w.hide_column("Bölge")
    assert w.table.isColumnHidden(1)
    assert w.session.workflow.dataset("T").steps == []
    w.refresh_all("T")
    assert w.table.isColumnHidden(1)  # yenilemede korunur
    w.open_find()
    w.find_edit.setText("Ege")
    assert w.find_info.text() == "bulunamadı"  # gizli sütunda aranmaz
    w.show_all_columns()
    assert not w.table.isColumnHidden(1)


def test_header_arrow_opens_filter_for_column(w, monkeypatch):
    seen = {}

    def fake_exec(self):
        seen["preset"] = self.preset
        return QDialog.Rejected
    monkeypatch.setattr(dlg.FilterDialog, "exec", fake_exec)
    w.table.horizontalHeader().arrowClicked.emit(1)
    assert seen["preset"] == "Bölge"


def test_freeze_columns(w):
    w.table.freeze(2)
    fv = w.table._frozen
    assert fv.isVisible() and not fv.isColumnHidden(1) and fv.isColumnHidden(2)
    assert fv.width() == w.table.columnWidth(0) + w.table.columnWidth(1)
    w.table.horizontalScrollBar().setValue(w.table.horizontalScrollBar().maximum())
    w.refresh_all("T")  # yenilemede korunur
    assert w.table.frozen_count() == 2 and w.table._frozen.isVisible()
    w.table.setColumnWidth(0, 150)
    assert w.table._frozen.columnWidth(0) == 150
    w.table.freeze(0)
    assert not fv.isVisible()


def test_trash_restore_from_dialog(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    from datetime import date
    from shiftflow.engine import periods as pr
    from shiftflow.engine.archive import Archive
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui.stage_dialogs import TrashDialog
    lib = ReportLibrary(str(tmp_path / "t.db"))
    arc = Archive(str(tmp_path / "a.db"))
    m = lib.save_reference("Personel", pd.DataFrame({"No": ["1"]}))
    lib.delete_reference(m["id"])
    arc.write("Toplama", pd.DataFrame({"A": [1, 2]}), pr.make_period(date(2026, 11, 10), "Gece", pr.DEFAULT_SHIFTS))
    arc.delete_set("Toplama")
    d = TrashDialog(lib, arc)
    qtbot.addWidget(d)
    assert d.table.rowCount() == 2
    for _ in range(2):
        d.table.selectRow(0)
        d.restore()
    assert d.table.rowCount() == 0
    assert lib.list_references()[0]["name"] == "Personel" and arc.read("Toplama")["A"].tolist() == [1, 2]
