"""Excel'deki formüllü sütunları tek seferde alma (dosya ve sahte açık Excel ile)."""

import pandas as pd
import pytest
from openpyxl import Workbook

from shiftflow.engine import excel_formula as xf
from shiftflow.engine.excel_live import ComExcelProvider, FileWorkbookProvider, FormulaGrid
from shiftflow.engine.session import Session


def _book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Toplama"
    ws.append(["TOPLAMA RAPORU"])
    ws.append([])
    ws.append(["Personel No", "Toplanan", "Hedef", "Oran", "Ad", "Durum"])
    for i, (p, t, h) in enumerate([("P1", 120, 100), ("P2", 80, 100), ("P9", 50, 50)], start=4):
        ws.append([p, t, h, f"=B{i}/C{i}", f'=IFERROR(VLOOKUP(A{i},Personel!A:B,2,0),"Tanımsız")',
                   f'=IF(D{i}>=1,"Hedefte","Altı")'])
    ps = wb.create_sheet("Personel")
    ps.append(["No", "Ad Soyad"])
    ps.append(["P1", "Ali"])
    ps.append(["P2", "Ayşe"])
    wb.save(path)
    return str(path)


def test_find_columns_from_file(tmp_path):
    path = _book(tmp_path / "r.xlsx")
    g = FileWorkbookProvider([path]).formula_rows(path, "Toplama")
    hdr, cols = xf.find_formula_columns(g, ["Personel No", "Toplanan", "Hedef"], {
        "Personel": ("Personel", {"A": "No", "B": "Ad Soyad"})}, "Toplama")
    assert hdr == 3
    assert [c.name for c in cols] == ["Oran", "Ad", "Durum"]
    assert cols[0].formula == "[Toplanan] / [Hedef]"
    assert 'ÇAPRAZARA([Personel No]; "Personel"; "No"; "Ad Soyad")' in cols[1].formula
    assert cols[2].formula.startswith("EĞER([Oran] >= 1")
    assert all(c.same_in_next_rows for c in cols)


def test_pattern_change_is_flagged():
    g = FormulaGrid(1, 1, [["A", "B"], [1, "=A2*2"], [2, "=A3*2"], [3, "=A4*3"]])
    _, cols = xf.find_formula_columns(g, ["A", "B"])
    assert not cols[0].same_in_next_rows and any("farklı" in w for w in cols[0].warnings)


def test_com_provider_reads_formulas():
    import sys
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from fake_excel import FakeApp, FakeWorkbook

    class R:
        def __init__(self, rows):
            self.rows, self.Row, self.Column = rows, 2, 3

            class C:
                Count = 0
            self.Rows, self.Columns = type("x", (), {"Count": len(rows)})(), type("y", (), {"Count": 2})()

        def GetResize(self, nr, nc):
            return R(self.rows[:nr])

        def Resize(self, nr, nc):  # pywin32 geç bağlama tuzağı: tek hücre
            return R(self.rows[:1])

        @property
        def Formula(self):
            return tuple(tuple(x) for x in self.rows)
    wb = FakeWorkbook("Kitap1", {"S": [["A", "B"], [1, "=C3*2"]]})
    wb._sheets[0].UsedRange = R([["A", "B"], [1, "=C3*2"]])
    p = ComExcelProvider(lambda: [FakeApp([wb])])
    p.list_workbooks()
    g = p.formula_rows("0:Kitap1", "S")
    assert (g.first_row, g.first_col) == (2, 3)
    _, cols = xf.find_formula_columns(g, ["A", "B"])
    assert cols[0].formula == "[A] * 2"  # tablo C sütunundan başlıyor: C → A


def test_session_adds_steps_and_drops_expected(tmp_path):
    s = Session()
    df = pd.DataFrame({"Toplanan": [10, 20], "Hedef": [5, 10], "Oran": [2.0, 2.0]})
    s.add_source("T", df)
    s.add_formula_steps("T", [{"name": "Oran", "formula": "[Toplanan] / [Hedef]", "replace": True}])
    assert [c["name"] for c in s.workflow.sources["T"].expected_columns] == ["Toplanan", "Hedef"]
    # ertesi gün ham rapor: formüllü sütun yok → eksik sütun uyarısı yok, sütun hesaplanır
    raw = pd.DataFrame({"Toplanan": [9], "Hedef": [3]})
    assert not s.check_source("T", raw).get("missing")
    s.bind_source("T", raw)
    assert s.result("T")["Oran"].tolist() == [3.0]


# ---------------------------------------------------------------- arayüz
def test_dialog_checks_against_excel_values_and_loads_missing_sheet(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui.formula_dialogs import FormulaColumnsDialog
    from shiftflow.ui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)
    path = _book(tmp_path / "r.xlsx")
    w = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(w)
    # Excel'in hesapladığı değerlerle birlikte yüklenmiş rapor
    df = pd.DataFrame({"Personel No": ["P1", "P2", "P9"], "Toplanan": [120, 80, 50], "Hedef": [100, 100, 50],
                       "Oran": [1.2, 0.8, 1.0], "Ad": ["Ali", "Ayşe", "Tanımsız"], "Durum": ["Hedefte", "Altı", "Hedefte"]})
    w.session.add_source("Toplama", df, path=path, sheet="Toplama")
    w.refresh_all("Toplama")
    prov, pairs = w._workbook_choices(w.session.workflow.sources["Toplama"])
    wb = [p for p in pairs if p[1].name == "Toplama"][0][0]
    d = FormulaColumnsDialog(w.session, "Toplama", prov, wb.id, "Toplama", w,
                             load_sheet=lambda n, ref: w._load_workbook_sheet(prov, wb, n, ref))
    qtbot.addWidget(d)
    assert d.missing == ["Personel"]
    assert d.table.item(1, 0).checkState() == Qt.Unchecked  # Ad: sayfa yüklü değil
    d._load_missing()
    assert d.missing == [] and "Personel" in w.session.workflow.datasets
    assert w.session.workflow.sources["Personel"].reference_id  # referans tablo olarak
    texts = [d.table.item(i, 3).text() for i in range(3)]
    assert all(t.startswith("3 / 3") for t in texts), texts
    assert all(d.table.item(i, 0).checkState() == Qt.Checked for i in range(3))
    d._accept()
    w.session.add_formula_steps("Toplama", d.steps)
    out = w.session.result("Toplama")
    assert out["Ad"].tolist() == ["Ali", "Ayşe", "Tanımsız"]


def test_formulas_only_for_filled_rows():
    # Excel'de formül 6 satıra çekilmiş, veri 3 satır: fazla satırlar atılır
    df = pd.DataFrame({"P": ["P1", "P2", "P3", None, None, None], "T": [10, 20, 30, None, None, None],
                       "Ad": ["x10", "x20", "x30", "x", "x", "x"]})
    s = Session()
    s.add_source("R", df)
    s.add_formula_steps("R", [{"name": "Ad", "formula": '"x" & [T]', "replace": True, "only_filled": True}])
    assert s.result("R")["Ad"].tolist() == ["x10", "x20", "x30"]
    assert s.workflow.dataset("R").steps[0].op == "drop_empty_rows"
    # ertesi gün: 2 satırlık ham rapor
    s.bind_source("R", pd.DataFrame({"P": ["P7", "P8"], "T": [1, 2]}))
    assert s.result("R")["Ad"].tolist() == ["x1", "x2"]


def test_calc_only_filled_rows():
    s = Session()
    s.add_source("R", pd.DataFrame({"T": [1, None, 3]}))
    s.add_step("R", "calc", {"name": "X", "formula": '"x" & [T]', "only_filled": True})
    out = s.result("R")["X"].tolist()
    assert out[0] == "x1" and pd.isna(out[1]) and out[2] == "x3"
    s.add_step("R", "calc", {"name": "Y", "formula": '"x" & [T]'})  # eski davranış: hepsine uygulanır
    assert s.result("R")["Y"].tolist() == ["x1", "x", "x3"]
