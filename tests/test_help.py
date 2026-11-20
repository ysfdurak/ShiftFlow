"""Uygulama içi yardım ve tek satırlık kutular için formül düzenleyici."""

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog, QLineEdit  # noqa: E402

from shiftflow.ui import help as hp  # noqa: E402


def test_guide_found_and_sections_exist(qtbot):
    md = hp.load_guide()
    titles = [t for _, t in hp.headings(md)]
    assert any(t.startswith("4.1 Formüller") for t in titles)
    d = hp.HelpDialog(section="4.2 Eşleştir")
    qtbot.addWidget(d)
    assert d.toc.count() == len(titles)
    for key, sec in hp.SECTION_FOR.items():
        assert d.go(sec), (key, sec)


def test_op_dialog_help_button(qtbot, monkeypatch):
    from shiftflow.ui import dialogs as dlg
    seen = []
    monkeypatch.setattr(hp, "show_help", lambda parent, key=None: seen.append(key))
    d = dlg.CalcDialog(pd.DataFrame({"A": [1]}))
    qtbot.addWidget(d)
    d.show_help()
    assert seen == ["calc"]


def test_editor_button_writes_one_line(qtbot, monkeypatch):
    from shiftflow.ui import formula_editor as fe
    le = QLineEdit("EĞER([A] > 1; 1; 0)")
    w = fe.attach_editor_button(le, ["A"])
    qtbot.addWidget(w)
    monkeypatch.setattr(fe.FormulaEditDialog, "edit", staticmethod(lambda parent, text, cols, title="":
                                                                   "EĞER([A] > 2; 1; 0)"))
    w.editor_button.click()
    assert le.text() == "EĞER([A] > 2; 1; 0)"


def test_conditional_has_editor_buttons(qtbot):
    from shiftflow.ui import dialogs as dlg
    d = dlg.ConditionalDialog(pd.DataFrame({"A": [1]}))
    qtbot.addWidget(d)
    assert d.then.parent() is not None and hasattr(d.then.parent(), "editor_button")
    assert QDialog is not None
