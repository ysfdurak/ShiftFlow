"""Gerçek Excel'de (Windows) bulunan COM hatalarının Linux'ta da yakalanması."""
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from fake_excel import FakeApp, FakeWorkbook  # noqa: E402

from shiftflow.engine.excel_live import ComExcelProvider  # noqa: E402

ROWS = [["Tarih", "Personel", "Adet"]] + [[f"0{i}.11.2026", f"P{i}", i * 10] for i in range(1, 6)]


def test_preview_is_full_table_not_single_cell():
    # pywin32'de Resize(a, b) tek hücre döndürür; önizleme ilk hücrede kalmamalı.
    p = ComExcelProvider(lambda: [FakeApp([FakeWorkbook("Rapor", {"S": ROWS})])])
    wb = p.list_workbooks()[0]
    sh = wb.sheets[0]
    assert (sh.n_rows, sh.n_cols) == (6, 3)
    assert len(sh.preview) == 6 and sh.preview[0] == ["Tarih", "Personel", "Adet"]


class _PVW:
    def __init__(self, wb):
        self.Workbook = wb


def test_protected_view_workbooks_are_listed():
    normal = FakeWorkbook("Acik", {"S": ROWS}, path="C:\\x")
    guarded = FakeWorkbook("Ekten", {"S": ROWS})
    app = FakeApp([normal])
    app.ProtectedViewWindows = [_PVW(guarded)]
    books = ComExcelProvider(lambda: [app]).list_workbooks()
    assert [b.name for b in books] == ["Acik", "Ekten"]
    assert books[1].note == "Korumalı Görünüm" and books[0].note == ""
    assert len(books[1].sheets[0].preview) == 6
