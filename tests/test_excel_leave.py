"""'Excel'e bırak': ShiftFlow'da karşılığı olmayan formül çıktıya Excel formülü olarak yazılır."""

import pandas as pd
import pytest
from openpyxl import load_workbook

from shiftflow.engine import excel_formula as xf
from shiftflow.engine.session import Session

COLS = xf.letter_map(["Kod", "Miktar", "Fiyat"], "A")


@pytest.mark.parametrize("src,tpl", [
    ("=TOPLA.ÇARPIM(B2;C2)*$H$1", "=SUMPRODUCT({Miktar},{Fiyat})*$H$1"),
    ('=DOLAYLI("A"&SATIR())', '=INDIRECT("A"&ROW())'),
    ("=B2-B1", "={Miktar}-{Miktar|-1}"),
    ('=EĞER(B2>1,5;"x";"y")', '=IF({Miktar}>1.5,"x","y")'),
    ('=IF(B2>1,"a,b",C2)', '=IF({Miktar}>1,"a,b",{Fiyat})'),
])
def test_template(src, tpl):
    assert xf.to_template(src, COLS, 2)[0] == tpl


def test_render_keeps_strings_and_offsets():
    letters = {"Miktar": "E", "Fiyat": "F"}
    assert xf.render_template('={Miktar}&"{Miktar}"', letters, 7) == '=E7&"{Miktar}"'
    assert xf.render_template("={Miktar}-{Miktar|-1}", letters, 7) == "=E7-E6"
    assert xf.render_template("={Yok}", letters, 7) == "=#REF!"


def test_export_writes_formula_per_row_after_sort_and_move(tmp_path):
    s = Session()
    s.add_source("T", pd.DataFrame({"Kod": ["a", "b"], "Miktar": [2, 3], "Fiyat": [10, 20]}))
    s.add_step("T", "excel_formula", {"name": "Tutar", "template": "=SUMPRODUCT({Miktar},{Fiyat})"})
    s.add_step("T", "sort", {"keys": [{"column": "Miktar", "ascending": False}]})
    s.add_step("T", "select", {"columns": ["Tutar", "Fiyat", "Miktar", "Kod"]})
    assert s.result("T")["Tutar"].isna().all()
    p = tmp_path / "o.xlsx"
    s.export(str(p), [("T", "S")])
    ws = load_workbook(p)["S"]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert rows[0] == ["Tutar", "Fiyat", "Miktar", "Kod"]
    assert rows[1][0] == "=SUMPRODUCT(C2,B2)" and rows[2][0] == "=SUMPRODUCT(C3,B3)"


def test_disabled_step_writes_no_formula(tmp_path):
    s = Session()
    s.add_source("T", pd.DataFrame({"A": [1]}))
    s.add_step("T", "excel_formula", {"name": "B", "template": "={A}*2"})
    s.set_step_enabled("T", 0, False)
    assert s.excel_formulas("T", s.result("T")) == {}


def test_import_dialog_leave_to_excel(qtbot):
    pytest.importorskip("PySide6")
    from shiftflow.ui.formula_dialogs import FormulaImportDialog
    s = Session()
    s.add_source("T", pd.DataFrame({"Kod": ["a"], "Miktar": [2], "Fiyat": [3]}))
    d = FormulaImportDialog(s, "T", s.result("T"), mode="step", text='=DOLAYLI("B"&SATIR())*C2')
    qtbot.addWidget(d)
    d.translate()
    assert d.b_excel.isVisibleTo(d)
    d.name.setText("X")
    d._accept_excel()
    assert d.op == "excel_formula" and d.params["template"] == '=INDIRECT("B"&ROW())*{Fiyat}'
