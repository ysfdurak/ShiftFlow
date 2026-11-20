"""İşlem arama listesi (Ctrl+K) ve Excel formülü penceresi."""

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox  # noqa: E402

from shiftflow.engine.library import ReportLibrary  # noqa: E402
from shiftflow.ui import dialogs as dlg  # noqa: E402
from shiftflow.ui import formula_dialogs as fd  # noqa: E402
from shiftflow.ui import palette as pl  # noqa: E402
from shiftflow.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)


T = pd.DataFrame({"Tarih": ["01.11.2026"] * 4, "Personel No": ["P1", "P2", "P3", "P1"], "Bölge": ["Ege", "Ege", "X", None],
                  "Toplanan": [10, 30, 5, 20], "Hedef": [20, 20, 0, 10]})
PER = pd.DataFrame({"Personel No": ["P1", "P2"], "Ad Soyad": ["Ali", "Ayşe"], "Ekip Lideri": ["Gül", "Okan"]})


@pytest.fixture
def w(qtbot, tmp_path):
    win = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(win)
    win.session.add_source("Toplama", T)
    win.session.add_source("Personel", PER)
    win.refresh_all("Toplama")
    win.show()
    return win


def titles(cmds, q):
    return [c.title for c in pl.filter_commands(cmds, q)]


def test_palette_search_with_synonyms_and_without_turkish_chars(w):
    cmds = w.palette_commands()
    assert titles(cmds, "düşeyara")[0].startswith("Eşleştir")
    assert titles(cmds, "vlookup")[0].startswith("Eşleştir")
    assert titles(cmds, "dusey")[0].startswith("Eşleştir")  # Türkçe karakter yazılmadan
    assert "Tekrarları kaldır" in titles(cmds, "mükerrer")[0]
    assert any(t.startswith("Dönem filtresi") for t in titles(cmds, "vardiya")[:3])
    assert titles(cmds, "excel formül")[0] == "Excel formülünden sütun"
    assert titles(cmds, "xyzqw") == []


def test_palette_column_context(w):
    w.table.selectColumn(3)  # Toplanan
    assert w.selected_column() == "Toplanan"
    cmds = w.palette_commands()
    t = titles(cmds, "pay")
    assert t[0] == "Toplam içindeki pay %: Toplanan"
    first = titles(cmds, "")[:8]
    assert any("Toplanan" in x for x in first)  # seçili sütuna uygun komutlar öne çıkar


def test_palette_runs_quick_action_and_formula(w, monkeypatch):
    w.table.selectColumn(3)
    cmds = w.palette_commands()
    sort = next(c for c in cmds if c.title == "Z → A sırala: Toplanan")
    sort.run()
    assert w.table.model_.frame()["Toplanan"].tolist() == [30, 20, 10, 5]
    seen = {}

    def calc_exec(d):
        seen["formula"] = d.formula.toPlainText()
        d.refresh()
        assert d.buttons.button(QDialogButtonBox.Ok).isEnabled(), d.status.text()
        return QDialog.Accepted
    monkeypatch.setattr(dlg.CalcDialog, "exec", calc_exec)
    w.table.selectColumn(3)
    pay = next(c for c in w.palette_commands() if c.title.startswith("Toplam içindeki pay"))
    pay.run()
    assert 'TABLOTOPLA("BU"; "Toplanan")' in seen["formula"]
    assert "Toplanan - Toplam içindeki pay %" in w.table.model_.frame().columns


def test_palette_dialog_keyboard(qtbot):
    ran = []
    cmds = [pl.Command("Birinci", "a", lambda: ran.append(1)), pl.Command("İkinci iş", "b", lambda: ran.append(2))]
    d = pl.CommandPalette(cmds)
    qtbot.addWidget(d)
    d.search.setText("ikinci")
    assert d.list.count() == 1
    qtbot.keyClick(d.search, Qt.Key_Return)
    assert d.chosen.title == "İkinci iş"
    d.chosen.run()
    assert ran == [2]


def test_disabled_commands_are_not_run(qtbot):
    d = pl.CommandPalette([pl.Command("Kapalı", "x", lambda: None, enabled=False)])
    qtbot.addWidget(d)
    d.run_current()
    assert d.chosen is None


def test_formula_import_dialog(w, qtbot):
    d = fd.FormulaImportDialog(w.session, "Toplama", w.session.result("Toplama"), w)
    qtbot.addWidget(d)
    d.src.setPlainText('=EĞER(EĞERHATA(DÜŞEYARA(B2;Personel!A:C;3;0);"")="";"Tanımsız";DÜŞEYARA(B2;Personel!A:C;2;0)&" - "&C2)')
    d.translate()
    assert d.sheet_box.isVisibleTo(d) and d.sheets.cellWidget(0, 1).currentData() == "Personel"
    from shiftflow.engine.expression import one_line
    assert "\n" in d.out.toPlainText()  # uzun çeviri girintili gösterilir
    assert one_line(d.out.toPlainText()).startswith("EĞER(EĞERHATA(ÇAPRAZARA([Personel No]; \"Personel\"")
    d.name.setText("Kişi")
    d.preview_result()
    assert d.ok.isEnabled(), d.status.text()
    assert d.preview.model_.frame()["Kişi"].tolist() == ["Ali - Ege", "Ayşe - Ege", "Tanımsız", "Ali - "]
    d._accept()
    assert d.params["formula"] == d.out.toPlainText().strip()


def test_formula_import_via_window_and_calc_button(w, monkeypatch):
    def run(d):
        d.src.setPlainText("=EĞERSAY(B:B;B2)")
        d.translate()
        d.name.setText("Tekrar")
        d._accept()
        return QDialog.Accepted
    monkeypatch.setattr(fd.FormulaImportDialog, "exec", run)
    w.formula_from_excel()
    assert w.table.model_.frame()["Tekrar"].tolist() == [2, 1, 1, 2]
    c = dlg.CalcDialog(w.session.result("Toplama"), session=w.session, dataset="Toplama")

    def ins(d):
        d.src.setPlainText("=D2/E2")
        d.translate()
        d._accept()
        return QDialog.Accepted
    monkeypatch.setattr(fd.FormulaImportDialog, "exec", ins)
    c._from_excel()
    assert c.formula.toPlainText() == "[Toplanan] / [Hedef]"


def test_calc_dialog_preview_with_table_function(w, qtbot):
    d = dlg.CalcDialog(w.session.result("Toplama"), session=w.session, dataset="Toplama")
    qtbot.addWidget(d)
    d.name.setText("Lider")
    d.formula.setPlainText('ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ekip Lideri"; "-")')
    d.refresh()
    assert d.buttons.button(QDialogButtonBox.Ok).isEnabled(), d.status.text()
    assert d.preview.model_.frame()["Lider"].tolist() == ["Gül", "Okan", "-", "Gül"]
    d.formula.setPlainText('DÜŞEYARA([Personel No]; "Yok"; 2; 0)')
    d.refresh()
    assert not d.buttons.button(QDialogButtonBox.Ok).isEnabled()
