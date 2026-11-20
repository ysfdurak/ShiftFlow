"""Açık raporlar ve 'Rapor oluştur' arayüz akışları (sahte Excel ile)."""

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox  # noqa: E402

from shiftflow.engine import reports as rp  # noqa: E402
from shiftflow.engine.excel_live import ComExcelProvider  # noqa: E402
from shiftflow.engine.library import ReportLibrary  # noqa: E402
from shiftflow.ui import main_window as mw  # noqa: E402
from shiftflow.ui import report_dialogs as rd  # noqa: E402
from shiftflow.ui import source_dialogs as sd  # noqa: E402
from shiftflow.ui.main_window import MainWindow  # noqa: E402

from fake_excel import FakeApp, FakeWorkbook, df_rows, wms_title  # noqa: E402


class Excel:
    """Testte 'açık' kitapları değiştirilebilen sahte Excel."""

    def __init__(self):
        self.books = []

    def provider(self):
        return ComExcelProvider(apps_factory=lambda: [FakeApp(list(self.books))])


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)
    return shown


@pytest.fixture
def env(qtbot, tmp_path, picking, staff):
    xl = Excel()
    xl.books = [FakeWorkbook("Kitap1", {"Sheet1": df_rows(picking, wms_title())}),
                FakeWorkbook("Personel.xlsx", {"Liste": df_rows(staff)}, path="C:\\ik")]
    lib = ReportLibrary(str(tmp_path / "lib.db"))
    w = MainWindow(library=lib, provider=xl.provider())
    qtbot.addWidget(w)
    w.show()
    return w, xl, lib


def test_open_reports_dialog_lists_unsaved_and_finds_header(env, qtbot):
    w, xl, lib = env
    d = rd.OpenReportsDialog(w.provider, lib, w)
    qtbot.addWidget(d)
    top = d.tree.topLevelItem(0)
    assert "kaydedilmemiş" in top.text(0)
    d.tree.setCurrentItem(top.child(0))
    assert d.header_row.value() == 4  # 3 başlık satırının altında
    assert "Personel No" in d.cols_label.text()


def test_define_then_recognized(env, qtbot, monkeypatch):
    w, xl, lib = env
    d = rd.OpenReportsDialog(w.provider, lib, w, define_only=True)
    qtbot.addWidget(d)
    d.tree.setCurrentItem(d.tree.topLevelItem(0).child(0))

    def fake_exec(dlg):
        dlg.name.setText("WMS Toplama")
        dlg._save()
        return QDialog.Accepted
    monkeypatch.setattr(rd.DefineReportDialog, "exec", fake_exec)
    d.define()
    assert lib.by_name("WMS Toplama") is not None
    d.refresh()
    assert d.tree.topLevelItem(0).child(0).text(1) == "✓ WMS Toplama"


def test_define_requires_two_keys(qtbot, picking, tmp_path):
    lib = ReportLibrary(str(tmp_path / "l.db"))
    dlg = rd.DefineReportDialog(picking, "Kitap1", "Sheet1", lib)
    qtbot.addWidget(dlg)
    assert dlg.name.text() == ""  # 'Kitap1' anlamsız ad önerilmez
    dlg.name.setText("X")
    dlg.keys._set_all(False)
    dlg.keys.list.item(0).setCheckState(Qt.Checked)
    dlg._save()
    assert dlg.definition is None and "iki sütun" in dlg.status.text()


def _take(w, monkeypatch, index, name):
    """Açık raporlardan al: belirli sayfayı seç, gerekirse tanımla."""
    def fake_exec(d):
        d.tree.setCurrentItem(d.tree.topLevelItem(index).child(0))
        d.take()
        return QDialog.Accepted if d.result_df is not None else QDialog.Rejected

    def define_exec(dlg):
        dlg.name.setText(name)
        dlg._save()
        return QDialog.Accepted
    monkeypatch.setattr(rd.OpenReportsDialog, "exec", fake_exec)
    monkeypatch.setattr(rd.DefineReportDialog, "exec", define_exec)
    w.open_from_excel()


def build_flow(w, monkeypatch, tmp_path):
    _take(w, monkeypatch, 0, "Toplama Raporu")
    _take(w, monkeypatch, 1, "Personel Listesi")
    s = w.session
    s.add_step("Toplama Raporu", "filter", {"conditions": [{"column": "Toplanan", "op": "gt", "value": "0"}]})
    s.add_derived("Detay", "join", ["Toplama Raporu", "Personel Listesi"],
                  {"how": "left", "left_keys": ["Personel No"], "right_keys": ["Personel No"]})
    s.set_run_settings({"output_dir": str(tmp_path / "cikti"), "file_name": "{akis} {tarih}", "open_after": False})
    s.set_outputs([{"dataset": "Detay", "sheet": "Detay"}])
    w.refresh_all()


def test_take_from_open_excel_links_definition(env, monkeypatch, tmp_path):
    w, xl, lib = env
    build_flow(w, monkeypatch, tmp_path)
    src = w.session.workflow.sources["Toplama Raporu"]
    assert src.report_id == lib.by_name("Toplama Raporu").id and src.kind == "report"
    # kaynak ayrıntısı listede kısa tutulur, ipucunda yazar
    assert any("Rapor: Toplama Raporu" in w.ds_list.item(i).toolTip() for i in range(w.ds_list.count()))


def test_one_click_build_and_next_day(env, monkeypatch, tmp_path, picking, staff, no_modal):
    w, xl, lib = env
    build_flow(w, monkeypatch, tmp_path)
    plan_opened = []
    monkeypatch.setattr(rd.RunPlanDialog, "exec", lambda self: plan_opened.append(1) or QDialog.Rejected)
    w.build_report()
    assert not plan_opened  # her şey hazır: kontrol ekranı açılmadan oluşturulur
    files = list((tmp_path / "cikti").iterdir())
    assert len(files) == 1 and pd.ExcelFile(files[0]).sheet_names == ["Detay"]
    assert any("Rapor oluşturuldu" in t for t in no_modal)

    # Kaydet, yeni gün: WMS yeni (kaydedilmemiş) kitap açar; başka adla
    wf = tmp_path / "akis.json"
    w.workflow_path = str(wf)
    w.session.save_workflow(str(wf))
    xl.books = [FakeWorkbook("Kitap7", {"Sayfa1": df_rows(pd.concat([picking, picking]), wms_title())}),
                FakeWorkbook("Personel.xlsx", {"Liste": df_rows(staff)}, path="C:\\ik")]
    w2 = MainWindow(library=lib, provider=xl.provider())
    w2.open_workflow(str(wf))
    from datetime import date, timedelta
    nxt = w.period_bar.period().date + timedelta(days=1)
    w2.period_bar.set_period(nxt, w.period_bar.period().shift)
    assert len(w2.session.result("Toplama Raporu")) == 10  # açılışta açık rapordan yüklendi
    monkeypatch.setattr(rd.RunPlanDialog, "exec", lambda self: plan_opened.append(1) or QDialog.Rejected)
    w2.build_report()
    # Personel listesi (tarihsiz ana veri) dünküyle aynı olabilir; bu uyarı sebebi değildir.
    # Toplama raporu yenilendiği için kontrol ekranı açılmadan oluşturulur.
    assert not plan_opened
    assert len(list((tmp_path / "cikti").iterdir())) == 2


def test_plan_dialog_mapping_and_stale(env, monkeypatch, tmp_path, picking, staff, qtbot):
    w, xl, lib = env
    build_flow(w, monkeypatch, tmp_path)
    w.build_report()
    from datetime import timedelta
    p0 = w.period_bar.period()
    w.period_bar.set_period(p0.date + timedelta(days=1), p0.shift)
    xl.books = [FakeWorkbook("Kitap2", {"S": df_rows(picking.rename(columns={"Toplanan": "Toplanan Miktar"}))}),
                FakeWorkbook("Personel.xlsx", {"Liste": df_rows(staff)}, path="C:\\ik")]
    b = w._builder()
    plans = b.plan()
    d = rd.RunPlanDialog(b, plans, w)
    qtbot.addWidget(d)
    assert not d.ok.isEnabled()
    d.table.selectRow(0)
    assert plans[0].status == "needs_mapping" and d.b_map.isEnabled()
    monkeypatch.setattr(sd.ColumnMapDialog, "exec", lambda self: QDialog.Accepted)
    d.map()  # önerilen eşleme (Toplanan Miktar -> Toplanan) kabul edilir
    assert not plans[0].blocking and any("Eşleme uygulandı" in m for m in plans[0].messages)
    d.table.selectRow(1)
    # personel listesi tarihsiz ana veri: dünküyle aynı olması uyarı değildir
    assert plans[1].status == "ok" and not d.b_stale.isEnabled()
    assert d.ok.isEnabled()
    res = b.build(d.plans)
    assert res.ok
    assert lib.by_name("Toplama Raporu").column_map == {"Toplanan Miktar": "Toplanan"}


def test_plan_dialog_pick_when_ambiguous(env, monkeypatch, tmp_path, picking, staff, qtbot):
    w, xl, lib = env
    build_flow(w, monkeypatch, tmp_path)
    xl.books = [FakeWorkbook("Kitap3", {"S": df_rows(picking)}), FakeWorkbook("Kitap4", {"S": df_rows(picking.head(2))}),
                FakeWorkbook("Personel.xlsx", {"Liste": df_rows(staff.head(3))}, path="C:\\ik")]
    b = w._builder()
    plans = b.plan()
    d = rd.RunPlanDialog(b, plans, w)
    qtbot.addWidget(d)
    d.table.selectRow(0)
    assert plans[0].status == "ambiguous"
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: (a[3][1], True))
    d.pick()
    assert plans[0].status == "ok" and len(plans[0].df) == 2
    assert d.ok.isEnabled()


def test_build_blocked_when_report_missing(env, monkeypatch, tmp_path):
    w, xl, lib = env
    build_flow(w, monkeypatch, tmp_path)
    xl.books = []
    seen = {}

    def plan_exec(self):
        seen["statuses"] = [p.status for p in self.plans]
        seen["ok"] = self.ok.isEnabled()
        return QDialog.Rejected
    monkeypatch.setattr(rd.RunPlanDialog, "exec", plan_exec)
    w.build_report()
    assert seen["statuses"] == ["not_found", "not_found"] and seen["ok"] is False
    assert not (tmp_path / "cikti").exists() or not list((tmp_path / "cikti").iterdir())


def test_library_dialog_and_run_settings(env, monkeypatch, tmp_path, qtbot):
    w, xl, lib = env
    build_flow(w, monkeypatch, tmp_path)
    w.build_report()
    d = rd.ReportLibraryDialog(lib, w.provider, w)
    qtbot.addWidget(d)
    assert d.list.count() == 2 and d.runs.rowCount() == 1
    assert "Tanıma sütunları" in d.detail.toPlainText()
    rs = rd.RunSettingsDialog(w.session.workflow, w)
    qtbot.addWidget(rs)
    rs.name.setText("Vardiya {gun}.{ay}")
    assert rs.example.text().startswith("Örnek: Vardiya ")


def test_link_existing_file_source_to_definition(env, monkeypatch, picking, qtbot):
    w, xl, lib = env
    w.session.add_source("Eski", picking, path="eski.xlsx")
    d = lib.save(rp.ReportDefinition(name="Toplama", columns=rp.columns_of(picking), key_columns=list(picking.columns)))
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Toplama", True))
    w.link_source("Eski")
    assert w.session.workflow.sources["Eski"].report_id == d.id
