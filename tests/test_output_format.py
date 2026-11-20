"""Excel çıktısı: toplam satırı ve koşullu renk; 'Excel'de aç'."""

import os

import pandas as pd
import pytest
from openpyxl import load_workbook

from shiftflow.engine.session import Session

DF = pd.DataFrame({"Ad": ["a", "b", "c"], "Oran": [0.8, 1.1, 0.95], "Adet": [10, 20, 30]})


def test_totals_and_rules(tmp_path):
    s = Session()
    s.add_source("T", DF)
    s.set_parameters({"Hedef": 0.9})
    p = tmp_path / "o.xlsx"
    s.export(str(p), [("T", "S", {"totals": True, "rules": [
        {"column": "Oran", "op": "<", "value": "{Hedef}", "color": "red"},
        {"column": "Ad", "op": "=", "value": "b", "color": "green", "whole_row": True},
        {"column": "Yok", "op": ">", "value": "1"}]})])
    ws = load_workbook(p)["S"]
    # "Oran" toplanmaz (oranların toplamı anlamsız), "Adet" toplanır
    assert [c.value for c in ws[5]] == ["Toplam", None, "=SUBTOTAL(109,C2:C4)"]
    assert ws.auto_filter.ref == "A1:C4"  # toplam satırı filtreye girmez
    rules = {str(r.sqref): [(x.type, x.operator, x.formula) for x in r.rules] for r in ws.conditional_formatting}
    assert rules["B2:B4"] == [("cellIs", "lessThan", ["0.9"])]
    assert rules["A2:C4"] == [("expression", None, ['$A2="b"'])]


def test_export_dialog_keeps_format(qtbot):
    pytest.importorskip("PySide6")
    from shiftflow.ui.source_dialogs import ExportDialog
    s = Session()
    s.add_source("T", DF)
    s.set_outputs([{"dataset": "T", "sheet": "S", "totals": True,
                    "rules": [{"column": "Oran", "op": "<", "value": "0,9", "color": "yellow"}]}])
    d = ExportDialog(s)
    qtbot.addWidget(d)
    (name, sheet, opts), = d.items()
    assert opts["totals"] and opts["rules"][0]["color"] == "yellow"
    assert "toplam" in d.table.cellWidget(0, 5).text()


def test_output_format_dialog_spec(qtbot):
    pytest.importorskip("PySide6")
    from shiftflow.ui.stage_dialogs import OutputFormatDialog
    d = OutputFormatDialog(DF, {"rules": [{"column": "Adet", "op": ">=", "value": "20", "color": "green"}]})
    qtbot.addWidget(d)
    d._add({"column": "Ad", "value": ""})  # boş değerli kural yok sayılır
    assert d.spec() == {"rules": [{"column": "Adet", "op": ">=", "value": "20", "color": "green",
                                   "whole_row": False}]}


def test_open_in_excel_writes_temp(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    import tempfile
    from PySide6.QtWidgets import QMessageBox
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui import main_window as mw
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    msgs = []
    monkeypatch.setattr(mw, "info", lambda parent, text, *a: msgs.append(text))
    opened = []
    monkeypatch.setattr(mw.os, "startfile", lambda p: opened.append(p), raising=False)
    w = mw.MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(w)
    w.session.add_source("Toplama/Gece", DF)
    w.refresh_all("Toplama/Gece")
    w.open_in_excel()
    files = os.listdir(tmp_path / "ShiftFlow")
    assert len(files) == 1 and files[0].startswith("Toplama_Gece") and opened


def test_totals_skip_percent_and_id_columns_and_chart_axes_visible(tmp_path):
    df = pd.DataFrame({"Personel": ["a", "b"], "Sipariş No": [101, 102], "Gerçekleşme %": [95.5, 110.0],
                       "Toplanan Adet": [40, 60]})
    s = Session()
    s.add_source("T", df)
    p = tmp_path / "g.xlsx"
    s.export(str(p), [("T", "S", {"totals": True, "chart": {"type": "col", "category": "Personel",
                                                             "values": ["Toplanan Adet"]}})])
    ws = load_workbook(p)["S"]
    assert [c.value for c in ws[4]] == ["Toplam", None, None, "=SUBTOTAL(109,D2:D3)"]
    import zipfile
    xml = zipfile.ZipFile(p).read("xl/charts/chart1.xml").decode()
    assert 'delete val="1"' not in xml and xml.count('delete val="0"') == 2
