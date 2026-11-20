"""Satırlar arası hesap (ÖNCEKİ, KÜMÜLATİF, SIRA) ve iş akışı parametreleri."""

import pandas as pd
import pytest
from openpyxl import Workbook

from shiftflow.engine import excel_formula as xf
from shiftflow.engine import expression as E
from shiftflow.engine.errors import ShiftFlowError
from shiftflow.engine.session import Session

DF = pd.DataFrame({"P": ["a", "b", "a", "a", "b"], "V": [10, 5, 7, 3, 8]})


@pytest.mark.parametrize("f,exp", [
    ("ÖNCEKİ([V]; 1; [P])", [None, None, 10, 7, 5]),
    ("SONRAKİ([V])", [5, 7, 3, 8, None]),
    ("KÜMÜLATİF([V]; [P])", [10, 5, 17, 20, 13]),
    ("KÜMÜLATİF(1; [P])", [1, 1, 2, 3, 2]),
    ("SIRA([V])", [1, 4, 3, 5, 2]),
    ("SIRA([V]; 1; [P])", [3, 1, 2, 1, 2]),
])
def test_row_functions(f, exp):
    got = [None if pd.isna(x) else x for x in E.evaluate(f, DF, "t")[0]]
    assert got == exp


def test_row_functions_follow_sort_step():
    s = Session()
    s.add_source("T", DF)
    s.add_step("T", "sort", {"keys": [{"column": "V", "ascending": True}]})
    s.add_step("T", "calc", {"name": "Fark", "formula": "[V] - ÖNCEKİ([V])"})
    assert s.result("T")["Fark"].tolist()[1:] == [2, 2, 1, 2]  # 3, 5, 7, 8, 10


@pytest.mark.parametrize("xl,sf", [
    ("=C3-C2", "[Sayaç] - ÖNCEKİ([Sayaç])"),
    ("=C3-C1", "[Sayaç] - ÖNCEKİ([Sayaç]; 2)"),
    ("=TOPLA($D$2:D3)", "KÜMÜLATİF([Adet])"),
    ("=EĞERSAY($A$2:A3;A3)", "KÜMÜLATİF(1; [Personel])"),
    ("=RANK(D3,D:D)", "SIRA([Adet]; 0)"),
])
def test_translator_row_patterns(xl, sf):
    cols = xf.letter_map(["Personel", "Saat", "Sayaç", "Adet"], "A")
    assert xf.translate(xl, cols, {}, None, 3).formula == sf


def test_parameters_in_formula_and_recalc():
    s = Session()
    s.add_source("T", pd.DataFrame({"A": [1, 2]}))
    s.set_parameters({"Hedef Oran": "0,95", "Bölge": "Ege"})
    assert s.parameters == {"Hedef Oran": 0.95, "Bölge": "Ege"}
    s.add_step("T", "calc", {"name": "B", "formula": "[A] * {hedef oran}"})
    s.add_step("T", "conditional", {"name": "C", "conditions": [{"column": "A", "op": "gt", "value": "1"}],
                                    "then": "{Bölge}", "else": '"-"'})
    assert s.result("T")["B"].tolist() == [0.95, 1.9] and s.result("T")["C"].tolist() == ["-", "Ege"]
    s.set_parameters({"Hedef Oran": "2", "Bölge": "Ege"})
    assert s.result("T")["B"].tolist() == [2, 4]  # önbellek parametre değişince yenilenir
    with pytest.raises(ShiftFlowError, match="tanımlı değil"):
        s.set_parameters({"Bölge": "x"})  # kullanılan parametre silinemez
    with pytest.raises(ShiftFlowError):
        s.set_parameters({"a{b": 1})


def test_fixed_cell_becomes_parameter(tmp_path):
    cols = xf.letter_map(["Toplanan", "Hedef"], "A")
    t = xf.translate("=A2/B2>=$H$1", cols, {}, None, 2)
    assert t.fixed_cells == ["H1"] and "[?$H$1]" in t.formula
    t2 = xf.translate("=A2/B2>=$H$1", cols, {}, None, 2, params={"H1": "Hedef Oran"})
    assert t2.formula == "[Toplanan] / [Hedef] >= {Hedef Oran}" and not t2.fixed_cells


def test_parameters_roundtrip(tmp_path):
    s = Session()
    s.add_source("T", pd.DataFrame({"A": [1]}))
    s.define_parameters_from_cells({"$H$1": "Hedef"}, {"Hedef": "95"})
    p = tmp_path / "a.json"
    s.save_workflow(str(p))
    s2 = Session()
    s2.load_workflow(str(p))
    assert s2.parameters == {"Hedef": 95} and s2.parameter_cells == {"H1": "Hedef"}


def test_formula_columns_dialog_offers_parameter(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from shiftflow.engine.excel_live import FileWorkbookProvider
    from shiftflow.ui.formula_dialogs import FormulaColumnsDialog
    wb = Workbook()
    ws = wb.active
    ws.title = "R"
    ws.append(["Toplanan", "Hedef", "Durum", None, None, None, "Hedef oran:", 0.9])
    ws.append([95, 100, '=IF(A2/B2>=$H$1,"Tamam","Altı")'])
    ws.append([80, 100, '=IF(A3/B3>=$H$1,"Tamam","Altı")'])
    path = str(tmp_path / "r.xlsx")
    wb.save(path)
    s = Session()
    s.add_source("R", pd.DataFrame({"Toplanan": [95, 80], "Hedef": [100, 100], "Durum": ["Tamam", "Altı"]}),
                 path=path, sheet="R")
    d = FormulaColumnsDialog(s, "R", FileWorkbookProvider([path]), path, "R")
    qtbot.addWidget(d)
    assert d._fixed_props == {"H1": ("Hedef oran", 0.9)}
    assert d.table.item(0, 0).checkState() == Qt.Unchecked
    d._make_params()
    assert s.parameters == {"Hedef oran": 0.9}
    assert d.cols[0].formula == 'EĞER([Toplanan] / [Hedef] >= {Hedef oran}; "Tamam"; "Altı")'
    assert d.table.item(0, 3).text().startswith("2 / 2")
