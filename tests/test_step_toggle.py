"""Adımı geçici kapatma, adım notu, adım kopyası."""

import pandas as pd
import pytest

from shiftflow.engine.session import Session

DF = pd.DataFrame({"A": [1, 2, 3, 4]})


def _s():
    s = Session()
    s.add_source("T", DF)
    s.add_step("T", "filter", {"conditions": [{"column": "A", "op": "gt", "value": "2"}]})
    s.add_step("T", "calc", {"name": "B", "formula": "[A] * 10"})
    return s


def test_disable_step_passes_data_through_and_undo():
    s = _s()
    assert len(s.result("T")) == 2
    s.set_step_enabled("T", 0, False)
    assert len(s.result("T")) == 4 and s.result("T")["B"].tolist() == [10, 20, 30, 40]
    st = s.step_statuses("T")[1]
    assert st.label.startswith("(kapalı)") and st.rows_before == st.rows_after == 4
    s.undo()
    assert len(s.result("T")) == 2


def test_disabling_needed_step_is_refused():
    s = _s()
    from shiftflow.engine.errors import ShiftFlowError
    s.add_step("T", "calc", {"name": "C", "formula": "[B] + 1"})
    with pytest.raises(ShiftFlowError):
        s.set_step_enabled("T", 1, False)  # B sütununu üreten adım kapatılırsa sonraki adım bozulur
    assert s.workflow.dataset("T").steps[1].enabled


def test_note_and_duplicate_and_json(tmp_path):
    s = _s()
    s.set_step_note("T", 0, "  WMS'teki küçük miktarları çıkarır ")
    s.set_step_enabled("T", 0, False)
    n = s.duplicate_step("T", 1)
    assert n == 2
    assert s.workflow.dataset("T").steps[2].params["name"] == "B (kopya)"
    p = tmp_path / "a.json"
    s.save_workflow(str(p))
    s2 = Session()
    wf = s2.load_workflow(str(p))
    st = wf.dataset("T").steps
    assert st[0].note == "WMS'teki küçük miktarları çıkarır" and st[0].enabled is False
    assert [x.op for x in st] == ["filter", "calc", "calc"] and st[1].id != st[2].id


def test_old_workflow_without_enabled_field_loads():
    from shiftflow.engine.workflow import Step
    assert Step(op="sort", params={}).enabled is True


def test_ui_checkbox_toggles_step(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)
    w = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(w)
    w.session = _s()
    w.session.library = w.library
    w.refresh_all("T")
    it = w.step_list.item(1)
    assert it.checkState() == Qt.Checked
    it.setCheckState(Qt.Unchecked)
    assert not w.session.workflow.dataset("T").steps[0].enabled
    assert "kapalı" in w.step_list.item(1).text()
    assert len(w.session.result("T")) == 4
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("İptalleri atar", True))
    w.step_note(1)
    assert "İptalleri atar" in w.step_list.item(1).text()
    w.duplicate_step(2)
    assert len(w.session.workflow.dataset("T").steps) == 3
