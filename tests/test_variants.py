"""Aynı değerin farklı yazılışları: uyarı, sorma, düzeltme."""

import pandas as pd
import pytest

from shiftflow.engine import variants
from shiftflow.engine.session import Session

DF = pd.DataFrame({"Bölge": ["Ege", "Ege ", " ege", "Marmara", "Ege", "Soğuk  Oda", "soğuk oda"],
                   "N": [1, 2, 3, 4, 5, 6, 7]})


def test_find_variants_picks_most_frequent():
    v = variants.find_variants(DF["Bölge"])
    assert v["Ege"][0] == "Ege"
    assert set(v["Ege"]) == {"Ege", "Ege ", " ege"}
    assert any(set(g) == {"Soğuk  Oda", "soğuk oda"} for g in v.values())
    assert variants.find_variants(pd.Series([1, 2, 2])) == {}
    assert variants.find_variants(pd.Series(["A", "B", None])) == {}


def test_turkish_case_is_respected():
    # 'I' küçülünce 'ı', 'İ' küçülünce 'i' olur: 'IŞIK' ve 'ışık' aynı, 'işik' farklı
    v = variants.find_variants(pd.Series(["IŞIK", "ışık", "işik"]))
    assert len(v) == 1 and set(next(iter(v.values()))) == {"IŞIK", "ışık"}


def test_unify_changes_only_variants():
    new, n = variants.unify(DF["Bölge"])
    assert n == 3
    assert new.tolist().count("Ege") == 4 and "Marmara" in new.tolist()


@pytest.mark.parametrize("op,params", [
    ("filter", {"conditions": [{"column": "Bölge", "op": "eq", "value": "Ege"}]}),
    ("dedupe", {"columns": ["Bölge"]}),
    ("calc", {"name": "X", "formula": 'EĞER([Bölge] = "Ege"; 1; 0)'}),
    ("calc", {"name": "X", "formula": 'EĞERSAY("BU"; "Bölge"; [Bölge])'}),
])
def test_steps_warn_without_changing_values(op, params):
    s = Session()
    s.add_source("T", DF)
    before = s.result("T")
    s.add_step("T", op, params)
    st = s.step_statuses("T")[1]
    assert "Bölge" in st.variants
    assert any("farklı yazılış" in w for w in st.warnings)
    if op == "calc":
        assert s.result("T")["Bölge"].tolist() == before["Bölge"].tolist()  # sessizce değiştirilmez


def test_plain_concatenation_does_not_warn():
    s = Session()
    s.add_source("T", DF)
    s.add_step("T", "calc", {"name": "X", "formula": '[Bölge] & "-" & [N]'})
    assert s.variants_at("T", 0) == {}


def test_fix_before_step_and_merge():
    s = Session()
    s.add_source("T", DF)
    s.add_step("T", "filter", {"conditions": [{"column": "Bölge", "op": "eq", "value": "Ege"}]})
    assert len(s.result("T")) == 2
    s.fix_variants("T", 0, ["Bölge"])
    steps = s.workflow.dataset("T").steps
    assert [x.op for x in steps] == ["unify", "filter"]
    assert len(s.result("T")) == 4
    assert s.variants_at("T", 1) == {}
    s.fix_variants("T", 1, ["N"])  # önündeki birleştirme adımına eklenir
    assert [x.op for x in s.workflow.dataset("T").steps] == ["unify", "filter"]
    assert s.workflow.dataset("T").steps[0].params["columns"] == ["Bölge", "N"]


def test_fix_for_group_goes_to_input_and_undo():
    s = Session()
    s.add_source("T", DF)
    s.add_derived("G", "group", ["T"], {"by": ["Bölge"], "values": [{"column": "N", "func": "sum"}]})
    assert len(s.result("G")) == 6
    assert "Bölge" in s.variants_at("G", -1)
    s.fix_variants("G", -1, ["Bölge"])
    g = s.result("G")
    assert len(g) == 3 and g.loc[g["Bölge"] == "Ege", "N (Toplam)"].iloc[0] == 11
    s.undo()
    assert len(s.result("G")) == 6


def test_ignore_variants_silences_warning():
    s = Session()
    s.add_source("T", DF)
    s.add_step("T", "dedupe", {"columns": ["Bölge"]})
    s.ignore_variants("T", 0)
    assert s.variants_at("T", 0) == {}
    assert not any("farklı yazılış" in w for w in s.step_statuses("T")[1].warnings)


def test_unify_step_survives_workflow_roundtrip(tmp_path):
    s = Session()
    s.add_source("T", DF)
    s.add_step("T", "unify", {"columns": ["Bölge"]})
    p = tmp_path / "a.json"
    s.save_workflow(str(p))
    s2 = Session()
    wf = s2.load_workflow(str(p))
    assert wf.dataset("T").steps[0].op == "unify"


# ---------------------------------------------------------------- arayüz
@pytest.fixture
def no_modal(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)


def _window(qtbot, tmp_path):  # no_modal gerekir
    pytest.importorskip("PySide6")
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui.main_window import MainWindow
    win = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(win)
    win.session.add_source("T", DF)
    win.refresh_all("T")
    return win


@pytest.mark.parametrize("choice,ops,rows", [("fix", ["unify", "filter"], 4), ("later", ["filter"], 2),
                                             ("never", ["filter"], 2)])
def test_ui_asks_and_applies_choice(qtbot, tmp_path, monkeypatch, no_modal, choice, ops, rows):
    from shiftflow.ui.main_window import MainWindow
    asked = []
    monkeypatch.setattr(MainWindow, "ask_variant_fix", lambda self, lines, at: asked.append(lines) or choice)
    w = _window(qtbot, tmp_path)
    w.quick_step("filter", {"conditions": [{"column": "Bölge", "op": "eq", "value": "Ege"}]})
    assert asked and "Bölge" in asked[0][0]
    assert [s.op for s in w.session.workflow.dataset("T").steps] == ops
    assert len(w.session.result("T")) == rows
    if choice == "never":
        assert w.session.workflow.dataset("T").steps[0].params.get("ignore_variants")


def test_ui_group_fix_goes_to_input(qtbot, tmp_path, monkeypatch, no_modal):
    from PySide6.QtWidgets import QDialog
    from shiftflow.ui import dialogs as dlg
    from shiftflow.ui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "ask_variant_fix", lambda self, lines, at: "fix" if at else "later")
    monkeypatch.setattr(dlg.GroupDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(dlg.GroupDialog, "params",
                        lambda self: {"by": ["Bölge"], "values": [{"column": "N", "func": "sum"}]})
    w = _window(qtbot, tmp_path)
    w.add_derived("group")
    assert [s.op for s in w.session.workflow.dataset("T").steps] == ["unify"]
    g = [n for n in w.session.workflow.datasets if n != "T"][0]
    assert len(w.session.result(g)) == 3


def test_unify_dialog_preselects_columns(qtbot):
    pytest.importorskip("PySide6")
    from shiftflow.ui import dialogs as dlg
    d = dlg.UnifyDialog(DF)
    qtbot.addWidget(d)
    assert d.params() == {"columns": ["Bölge"]}
