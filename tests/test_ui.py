"""Arayüz testleri (ekransız Qt). Gerçek diyaloglar oluşturulur, alanları
doldurulur ve ana pencerenin akışları uçtan uca çalıştırılır. Modal
pencereler `exec` yerine otomatik onaylanır."""

import os

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QMessageBox  # noqa: E402

from shiftflow.engine import io as sio  # noqa: E402
from shiftflow.ui import dialogs as dlg  # noqa: E402
from shiftflow.ui import main_window as mw  # noqa: E402
from shiftflow.ui import source_dialogs as sd  # noqa: E402
from shiftflow.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    """Bilgi/soru kutuları testte beklemesin."""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)


@pytest.fixture
def win(qtbot, picking, staff):
    w = MainWindow()
    qtbot.addWidget(w)
    w.session.add_source("Toplama", picking, path="toplama.xlsx")
    w.session.add_source("Personel", staff, path="personel.xlsx")
    w.refresh_all("Toplama")
    w.show()
    return w


def accept_with(monkeypatch, cls, setup):
    """`cls` diyaloğu açıldığında `setup(dialog)` çalıştırılıp onaylanır."""
    def fake_exec(self):
        setup(self)
        self.refresh()
        assert self.buttons.button(QDialogButtonBox.Ok).isEnabled(), self.status.text()
        return QDialog.Accepted
    monkeypatch.setattr(cls, "exec", fake_exec)


def test_table_shows_data(win):
    assert win.table.model().rowCount() == 6
    assert win.table.model().columnCount() == 5
    assert win.ds_list.count() == 2
    assert "6 satır" in win.size_label.text()
    # sayılar Türkçe biçimde, sağa hizalı
    m = win.table.model()
    assert m.data(m.index(0, 2)) == "120"
    assert m.data(m.index(0, 4)) == "01.11.2026"


def test_filter_dialog_live_preview(qtbot, picking):
    d = dlg.FilterDialog(picking, preset="Toplanan")
    qtbot.addWidget(d)
    row = d.editor.rows[0]
    row.op.setCurrentIndex(row.op.findData("gt"))
    row.value.setText("60")
    d.refresh()
    assert "3 satır" in d.status.text()
    assert d.preview.model().rowCount() == 3
    row.value.setText("abc")
    d.refresh()
    assert not d.buttons.button(QDialogButtonBox.Ok).isEnabled()


def test_filter_value_list_tab(qtbot, picking):
    d = dlg.FilterDialog(picking, preset="Bölge")
    qtbot.addWidget(d)
    d.tabs.setCurrentIndex(1)
    d._set_all(False)
    for i in range(d.v_list.count()):
        if d.v_list.item(i).data(Qt.UserRole) == "Ege":
            d.v_list.item(i).setCheckState(Qt.Checked)
    p = d.params()
    assert p["conditions"][0] == {"column": "Bölge", "op": "in_list", "value": ["Ege"]}


def test_add_calc_step_via_window(win, monkeypatch):
    def setup(d):
        d.name.setText("Oran")
        d.formula.setPlainText("[Toplanan] / [Hedef] * 100")
    accept_with(monkeypatch, dlg.CalcDialog, setup)
    win.add_step("calc")
    assert "Oran" in win.table.model_.frame().columns
    assert win.step_list.count() == 2
    assert "⚠" in win.step_list.item(1).text()  # sıfıra bölme uyarısı


def test_header_quick_actions(win):
    win.quick_step("sort", {"keys": [{"column": "Toplanan", "ascending": False}]})
    assert win.table.model_.frame()["Toplanan"].iloc[0] == 120
    win.quick_step("filter", {"conditions": [{"column": "Bölge", "op": "not_empty"}], "mode": "and"})
    assert win.table.model().rowCount() == 5
    win.undo()
    assert win.table.model().rowCount() == 6
    win.redo()
    assert win.table.model().rowCount() == 5


def test_intermediate_view_and_insert(win):
    win.quick_step("filter", {"conditions": [{"column": "Toplanan", "op": "gt", "value": "50"}], "mode": "and"})
    win.quick_step("sort", {"keys": [{"column": "Toplanan"}]})
    win.step_list.setCurrentRow(0)  # başlangıç
    assert win.table.model().rowCount() == 6
    assert win.banner.isVisible() or not win.isVisible()
    win.quick_step("filter", {"conditions": [{"column": "Bölge", "op": "not_empty"}], "mode": "and"})
    steps = win.session.workflow.dataset("Toplama").steps
    assert steps[0].params["conditions"][0]["op"] == "not_empty"  # başa eklendi


def test_join_dialog_and_window(win, monkeypatch):
    def setup(d):
        d.how.setCurrentIndex(d.how.findData("left"))
        d.match_col.setChecked(True)
        assert d.key_rows[0][1].currentText() == "Personel No"
    accept_with(monkeypatch, dlg.JoinDialog, setup)
    win.add_join()
    assert win.current == "Birleşik"
    df = win.table.model_.frame()
    assert len(df) == 6 and "Ad Soyad" in df.columns
    assert "Eşleşme" in win.messages.text() or "eşleşen" in win.messages.text()


def test_join_many_to_many_confirmation(win, monkeypatch):
    dup = pd.DataFrame({"Personel No": ["P01", "P01"], "Not": ["a", "b"]})
    win.session.add_source("Notlar", dup)
    asked = []
    monkeypatch.setattr(mw, "ask", lambda parent, text, title="": asked.append(text) or True)

    def setup(d):
        d.right.setCurrentText("Notlar")
    accept_with(monkeypatch, dlg.JoinDialog, setup)
    win.current = "Toplama"
    win.add_join()
    assert asked and "Çoktan-çoğa" in asked[0]
    assert len(win.session.result(win.current)) == 8


def test_pivot_dialog(qtbot, picking):
    d = dlg.PivotDialog(picking, name="P")
    qtbot.addWidget(d)
    d.rows.add("Bölge")
    d.cols.add("Tarih")
    d.vals.add({"column": "Hedef", "func": "mean"})
    d.refresh()
    assert d.buttons.button(QDialogButtonBox.Ok).isEnabled(), d.status.text()
    cols = list(d.preview.model_.frame().columns)
    assert any(c.startswith("Hedef (Ortalama) |") for c in cols)


def test_group_via_window_and_edit_origin(win, monkeypatch):
    def setup(d):
        d.by.list.item(1).setCheckState(Qt.Checked)  # Bölge
    accept_with(monkeypatch, dlg.GroupDialog, setup)
    win.add_derived("group")
    name = win.current
    assert win.session.workflow.dataset(name).origin.type == "group"

    def setup2(d):
        d.vals.add({"column": "Hedef", "func": "max"})
    accept_with(monkeypatch, dlg.GroupDialog, setup2)
    win.step_list.setCurrentRow(0)
    win.edit_step()
    assert "Hedef (Maks)" in win.session.result(name).columns


def test_all_step_dialogs_build(qtbot, picking):
    from shiftflow.engine import Session
    from shiftflow.engine import periods as pr
    from datetime import datetime
    s = Session()
    s.add_source("T", picking)
    s.add_source("Ref", picking)
    ctx = pr.auto_period(datetime(2026, 11, 2, 12), pr.DEFAULT_SHIFTS).context()
    for key, cls in dlg.STEP_DIALOGS.items():
        d = cls(picking, preset="Bölge", session=s, dataset="T", context=ctx)
        qtbot.addWidget(d)
        d.refresh()  # çökmeden açılmalı ve önizlemeyi denemeli


def test_edit_existing_step_prefills(qtbot, picking):
    p = {"name": "X", "formula": "[Toplanan] * 2", "replace": False}
    d = dlg.CalcDialog(picking, params=p)
    qtbot.addWidget(d)
    assert d.params() == p


def test_import_dialog_and_paste(qtbot, make_xlsx, picking, staff):
    path = make_xlsx("r.xlsx", {"Toplama": picking, "Personel": staff})
    d = sd.ImportDialog(path=path)
    qtbot.addWidget(d)
    d.load()
    assert len(d.df) == 6
    d.sheet.setCurrentText("Personel")
    assert len(d.df) == 4
    d2 = sd.ImportDialog(text="A\tB\n1\t2\n")
    qtbot.addWidget(d2)
    d2.load()
    assert list(d2.df.columns) == ["A", "B"]


def test_copy_selection(win, qtbot):
    from PySide6.QtGui import QGuiApplication
    win.table.selectColumn(2)
    win.table.copy_selection(with_header=True)
    text = QGuiApplication.clipboard().text().split("\n")
    assert text[0] == "Toplanan" and text[1] == "120"


def test_selection_stats(win):
    got = []
    win.table.selectionStats.connect(got.append)
    win.table.selectColumn(2)
    assert any("Toplam: 365" in g for g in got)


def test_full_cycle_save_reload_rerun_export(qtbot, tmp_path, make_xlsx, picking, staff, monkeypatch):
    src1 = make_xlsx("t1.xlsx", {"Toplama": picking})
    src2 = make_xlsx("p.xlsx", {"Personel": staff})
    w = MainWindow()
    qtbot.addWidget(w)
    w.session.add_source("Toplama", sio.read_source(src1), path=src1, sheet="Toplama")
    w.session.add_source("Personel", sio.read_source(src2), path=src2, sheet="Personel")
    w.session.add_step("Toplama", "calc", {"name": "Fark", "formula": "[Toplanan] - [Hedef]"})
    w.session.add_derived("Birleşik", "join", ["Toplama", "Personel"],
                          {"how": "left", "left_keys": ["Personel No"], "right_keys": ["Personel No"]})
    w.session.add_derived("Özet", "pivot", ["Birleşik"],
                          {"rows": ["Vardiya"], "values": [{"column": "Fark", "func": "sum"}]})
    w.refresh_all()
    wf = tmp_path / "akis.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(wf), ""))
    w.save_workflow()
    assert wf.exists() and not w.session.dirty

    # Yeni gün: aynı yolda güncellenmiş rapor (WMS aynı dosyanın üzerine yazar)
    make_xlsx("t1.xlsx", {"Toplama": pd.concat([picking, picking])})
    w2 = MainWindow()
    qtbot.addWidget(w2)
    monkeypatch.setattr(sd.BindSourcesDialog, "exec", lambda self: (self.load_saved(), QDialog.Accepted)[1])
    out = tmp_path / "rapor.xlsx"
    monkeypatch.setattr(sd.ExportDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    w2.open_workflow(str(wf))
    assert len(w2.session.result("Toplama")) == 12
    w2.current = "Birleşik"
    w2.export()
    assert set(pd.ExcelFile(out).sheet_names) >= {"Birleşik", "Özet"}


def test_rerun_with_changed_format_asks_mapping(qtbot, tmp_path, make_xlsx, picking, monkeypatch):
    src = make_xlsx("t.xlsx", {"Toplama": picking})
    w = MainWindow()
    qtbot.addWidget(w)
    w.session.add_source("Toplama", sio.read_source(src), path=src, sheet="Toplama")
    w.session.add_step("Toplama", "filter", {"conditions": [{"column": "Toplanan", "op": "gt", "value": "0"}]})
    make_xlsx("t.xlsx", {"Toplama": picking.rename(columns={"Toplanan": "Toplanan Adet"})})
    seen = {}

    def map_exec(self):
        seen["missing"] = list(self.combos)
        return QDialog.Accepted
    monkeypatch.setattr(sd.ColumnMapDialog, "exec", map_exec)
    d = sd.BindSourcesDialog(w.session, w.settings, w)
    qtbot.addWidget(d)
    d.load_saved()
    assert seen["missing"] == ["Toplanan"]
    assert w.session.run_all() == {}


def test_screenshot(win, tmp_path, monkeypatch):
    """Görsel kontrol için ekran görüntüsü (CI'da artefakt olarak saklanır)."""
    win.resize(1400, 820)
    win.quick_step("calc", {"name": "Oran %", "formula": "[Toplanan] / [Hedef] * 100"})
    out = os.environ.get("SHIFTFLOW_SCREENSHOT_DIR")
    if out:
        os.makedirs(out, exist_ok=True)
        win.grab().save(os.path.join(out, "ana_pencere.png"))


def test_na_values_everywhere(qtbot):
    df = pd.DataFrame({"A": pd.Series(["x", pd.NA, "y"], dtype="string"),
                       "N": pd.Series([1, pd.NA, 3], dtype="Int64"),
                       "T": pd.to_datetime(["2026-01-01", None, "2026-01-03"])})
    w = MainWindow()
    qtbot.addWidget(w)
    w.session.add_source("S", df)
    w.refresh_all("S")
    got = []
    w.table.selectionStats.connect(got.append)
    w.table.selectAll()
    w.table.copy_selection(True)
    assert any("Toplam: 4" in g for g in got)
    for key, cls in dlg.STEP_DIALOGS.items():
        d = cls(df, preset="A", session=w.session, dataset="S", context=w.session.context)
        qtbot.addWidget(d)
        d.refresh()
    w.quick_step("filter", {"conditions": [{"column": "A", "op": "empty"}], "mode": "and"})
    assert w.table.model().rowCount() == 1
    w.quick_step("sort", {"keys": [{"column": "N"}]})
