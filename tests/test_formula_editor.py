"""Formül düzenleyicisi: biçimlendirme, hata yeri, imza, parantez, tamamlama."""

import pandas as pd
import pytest

from shiftflow.engine import expression as ex
from shiftflow.engine.errors import ShiftFlowError

LONG = ('EĞER(EĞERHATA(DÜŞEYARA([Personel No]; "Personel"; 3; 0); "") = ""; "Tanımsız"; ÇOKEĞER([A] > -1; '
        'DÜŞEYARA([Personel No]; "Personel"; 2; 0) & " - " & [Bölge]; [A] <= 5; '
        'YUVARLA(EĞERHATA([Toplanan] / [Hedef]; 0) * 100; 1); DOĞRU; "Diğer"))')


def test_format_roundtrip_keeps_meaning():
    pretty = ex.format_formula(LONG)
    assert pretty.count("\n") >= 5 and "\n    " in pretty
    assert ex.one_line(pretty) == ex.one_line(LONG)
    df = pd.DataFrame({"Personel No": ["P1", "P9"], "A": [0, 3], "Bölge": ["E", "M"], "Toplanan": [5, 6], "Hedef": [10, 0]})
    per = pd.DataFrame({"Personel No": ["P1"], "Ad": ["Ali"], "Lider": ["Gül"]})
    a, _ = ex.evaluate(LONG, df, "", {"Personel": per})
    b, _ = ex.evaluate(pretty, df, "", {"Personel": per})
    assert a.tolist() == b.tolist() == ["Ali - E", "Tanımsız"]


def test_short_formula_stays_one_line_and_unary_minus():
    assert ex.format_formula("[A] * 2") == "[A] * 2"
    assert ex.one_line("EĞER([A]>-1;-2;3)") == "EĞER([A] > -1; -2; 3)"


@pytest.mark.parametrize("bad,pos", [
    ("EĞER([A] > 1; 2", 4), ("EĞER([A] > 1)); 2", 13), ("[A] [B]", 4), ('EĞER("abc; 1; 2)', 5),
    ("  =[A] * ", None),
])
def test_error_positions(bad, pos):
    df = pd.DataFrame({"A": [1], "B": [2]})
    with pytest.raises(ShiftFlowError) as e:
        ex.check_parentheses(bad)
        ex.evaluate(bad, df)
    if pos is not None:
        assert e.value.pos == pos


def test_signature_help():
    assert ex.signature_at("EĞER([A] > 1; ", 14) == ("EĞER", 1)
    assert "<b>doğruysa</b>" in ex.signature_text("EĞER", 1)
    f = 'EĞER(DÜŞEYARA([X]; "T(1)"; '
    assert ex.signature_at(f, len(f)) == ("DÜŞEYARA", 2)  # tırnak içindeki parantez sayılmaz
    assert "<b>…</b>" in ex.signature_text("VE", 5)
    assert ex.signature_at("[A] + 1", 7) is None


pytest.importorskip("PySide6")


def test_editor_widget(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from shiftflow.ui.formula_editor import FormulaEdit, matching_paren
    assert matching_paren('EĞER(")"; (1))', 4) == 13
    assert matching_paren("((1)", 0) is None
    e = FormulaEdit(columns=["Toplanan Adet", "Hedef Adet"])
    qtbot.addWidget(e)
    e.show()
    sigs = []
    e.signatureChanged.connect(sigs.append)
    qtbot.keyClicks(e, "[top")
    assert e._mode == "col" and e.completer.completionCount() == 1
    qtbot.keyClick(e, Qt.Key_Return)
    assert e.toPlainText() == "[Toplanan Adet]"
    e.setPlainText("")
    qtbot.keyClicks(e, "yuvar")
    assert e._mode == "func"
    qtbot.keyClick(e, Qt.Key_Tab)
    assert e.toPlainText() == "YUVARLA("
    qtbot.keyClicks(e, "[Hedef Adet]; ")
    assert any("<b>basamak</b>" in s for s in sigs)
    e.setPlainText(LONG)
    assert e.format() and "\n" in e.toPlainText()
    e.to_one_line()
    assert "\n" not in e.toPlainText()
    e.setPlainText("EĞER([A] > 1; 2")
    assert not e.format() and e._error == 4
    c = e.textCursor()
    c.setPosition(4)
    e.setTextCursor(c)
    assert len(e.extraSelections()) >= 2  # satır + eşsiz parantez + hata
    assert e.line_col(4) == (1, 5)


def test_calc_dialog_marks_error_and_tries_selection(qtbot):
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QDialogButtonBox
    from shiftflow.ui.dialogs import CalcDialog
    df = pd.DataFrame({"Toplanan": [10, 30], "Hedef": [20, 0]})
    d = CalcDialog(df)
    qtbot.addWidget(d)
    d.name.setText("Oran")
    d.formula.setPlainText("EĞER([Hedef] = 0; 0;\n  YUVARLA([Toplanan] / [Hedef] * 100; 1)")
    d.refresh()
    assert not d.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert "satır 1" in d.status.text() and d.formula._error == 4
    d.formula.setPlainText("EĞER([Hedef] = 0; 0; YUVARLA([Toplanan] / [Hedef] * 100; 1))")
    d.refresh()
    assert d.buttons.button(QDialogButtonBox.Ok).isEnabled()
    text = d.formula.toPlainText()
    start = text.index("YUVARLA")
    c = d.formula.textCursor()
    c.setPosition(start)
    c.setPosition(text.rindex(")"), QTextCursor.KeepAnchor)
    d.formula.setTextCursor(c)
    d._try_selection()
    assert "1. satır: <b>50</b>" in d.func_help.text() and "2. satır: <b>(boş)</b>" in d.func_help.text()
