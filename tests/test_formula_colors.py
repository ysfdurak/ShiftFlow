"""Formülde kullanılan sütunların renklendirilmesi ve Excel formülü yapıştırma."""

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from shiftflow.ui import dialogs as dlg  # noqa: E402
from shiftflow.ui import formula_dialogs as fd  # noqa: E402
from shiftflow.ui.formula_editor import FormulaEdit, column_colors, looks_like_excel  # noqa: E402

DF = pd.DataFrame({"Personel": ["P1", "P2"], "Toplanan": [10, 30], "Hedef": [20, 20]})


def test_colors_in_order_and_strings_ignored():
    c = column_colors('EĞER([Toplanan] > [Hedef]; "[Hedef]"; [Toplanan])')
    assert list(c) == ["Toplanan", "Hedef"] and len(set(c.values())) == 2


@pytest.mark.parametrize("text,yes", [("=B2*C2", True), ("=TOPLA(D:D)", True), ("=Personel!A2", True),
                                      ("=EĞER([A] > 1; 1; 0)", False), ('=[Bölge] & "A1"', False),
                                      ("B2*C2", False)])
def test_excel_detection(text, yes):
    assert looks_like_excel(text) is yes


def test_calc_dialog_colors_preview_header(qtbot):
    d = dlg.CalcDialog(DF, params={"name": "Oran", "formula": "[Toplanan] / [Hedef]"})
    qtbot.addWidget(d)
    d.refresh()
    m = d.preview.model_
    assert set(m._hcolors) == {"Toplanan", "Hedef"}
    assert m.headerData(1, Qt.Horizontal, Qt.ForegroundRole) is not None
    assert m.headerData(0, Qt.Horizontal, Qt.ForegroundRole) is None
    d.formula.setPlainText("[Personel]")
    assert set(m._hcolors) == {"Personel"}
    assert d.cols.item(0).font().bold() and not d.cols.item(1).font().bold()


def test_cursor_on_column_emits(qtbot):
    e = FormulaEdit(columns=DF.columns)
    qtbot.addWidget(e)
    got = []
    e.columnClicked.connect(got.append)
    e.setPlainText("[Toplanan] * 2")
    c = e.textCursor()
    c.setPosition(3)
    e.setTextCursor(c)
    assert got[-1] == "Toplanan"


def test_paste_excel_formula_opens_translator(qtbot, monkeypatch):
    seen = {}

    def fake_exec(self):
        seen["src"] = self.src.toPlainText()
        self.formula = "[Toplanan] * 2"
        return QDialog.Accepted
    monkeypatch.setattr(fd.FormulaImportDialog, "exec", fake_exec)
    d = dlg.CalcDialog(DF, params={"name": "X", "formula": ""})
    qtbot.addWidget(d)
    md = QMimeData()
    md.setText("=B2*2")
    d.formula.insertFromMimeData(md)
    assert seen["src"] == "=B2*2"
    assert d.formula.toPlainText() == "[Toplanan] * 2"
    # normal metin yapıştırma çevirici açmaz
    d.formula.moveCursor(d.formula.textCursor().MoveOperation.End)
    md2 = QMimeData()
    md2.setText(" + 1")
    d.formula.insertFromMimeData(md2)
    assert d.formula.toPlainText().endswith("+ 1")
