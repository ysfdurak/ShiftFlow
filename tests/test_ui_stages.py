"""Aşama 1-4 arayüz akışları (ekransız Qt, sahte Outlook)."""

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from shiftflow.engine import mailer  # noqa: E402
from shiftflow.engine import periods as pr  # noqa: E402
from shiftflow.engine.archive import Archive  # noqa: E402
from shiftflow.engine.library import ReportLibrary  # noqa: E402
from shiftflow.ui import dialogs as dlg  # noqa: E402
from shiftflow.ui import main_window as mw  # noqa: E402
from shiftflow.ui import stage_dialogs as sg  # noqa: E402
from shiftflow.ui.main_window import MainWindow  # noqa: E402

from test_stage2_4 import _FakeOutlook  # noqa: E402


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)
    return shown


@pytest.fixture
def env(qtbot, tmp_path):
    lib = ReportLibrary(str(tmp_path / "lib.db"))
    arc = Archive(str(tmp_path / "arc.db"))
    log = []
    w = MainWindow(library=lib, archive=arc, outlook=mailer.OutlookMailer(app_factory=lambda: _FakeOutlook(log)))
    qtbot.addWidget(w)
    w.show()
    return w, lib, arc, log


def moves():
    return pd.DataFrame({
        "Lokasyon": ["A-01", "B-01", "C-09", "a-01"],
        "Ekip": ["X", "Y", "X", "Y"],
        "Miktar": [10, 5, 3, 7],
        "İşlem Zamanı": pd.to_datetime(["2026-11-10 08:10", "2026-11-10 09:00", "2026-11-10 17:00", "2026-11-10 15:30"]),
    })


LOCS = pd.DataFrame({"Lokasyon Kodu": ["A-01", "B-01"], "Bölge": ["Kuru", "Soğuk"]})


def test_formula_help_inserts_function(qtbot):
    d = dlg.CalcDialog(moves())
    qtbot.addWidget(d)
    it = d.funcs.item(0)
    d._insert_func(it)
    assert d.formula.toPlainText().startswith("EĞER(")
    d.name.setText("Sınıf")
    d.formula.setPlainText('EĞER([Miktar] >= 7; "Yüksek"; "Düşük")')
    d.refresh()
    assert d.buttons.button(QDialogButtonBox.Ok).isEnabled(), d.status.text()


def test_reference_and_lookup_via_window(env, monkeypatch, qtbot):
    w, lib, arc, _ = env
    m = lib.save_reference("Lokasyonlar", LOCS)
    w.session.add_source("Hareketler", moves())
    w.refresh_all("Hareketler")
    monkeypatch.setattr(sg.ReferenceTablesDialog, "exec", lambda self: (setattr(self, "chosen", m), QDialog.Accepted)[1])
    w.open_references()
    assert w.session.workflow.sources["Lokasyonlar"].reference_id == m["id"]
    w.refresh_all("Hareketler")

    def setup(d):
        d.table.setCurrentText("Lokasyonlar")
        d.key_rows[0][1].setCurrentText("Lokasyon")
        d.key_rows[0][2].setCurrentText("Lokasyon Kodu")
        for r in range(d.cols.rowCount()):
            if d.cols.item(r, 1).text() == "Bölge":
                d.cols.item(r, 0).setCheckState(Qt.Checked)
        d.missing.setText("Tanımsız")
        d.refresh()
        assert d.buttons.button(QDialogButtonBox.Ok).isEnabled(), d.status.text()
        return QDialog.Accepted
    monkeypatch.setattr(dlg.LookupDialog, "exec", setup)
    w.add_step("lookup")
    assert w.table.model_.frame()["Bölge"].tolist() == ["Kuru", "Soğuk", "Tanımsız", "Kuru"]
    assert "Referans: Lokasyonlar" in " ".join(w.ds_list.item(i).text() for i in range(w.ds_list.count()))


def test_reference_dialog_lists_and_previews(env, qtbot):
    w, lib, *_ = env
    lib.save_reference("Lokasyonlar", LOCS)
    d = sg.ReferenceTablesDialog(lib, w, get_frame=lambda n: ("Ürünler", pd.DataFrame({"Kod": [1]}), ""))
    qtbot.addWidget(d)
    assert d.list.count() == 1 and d.preview.model().rowCount() == 2
    d.load(None)
    assert d.list.count() == 2


def test_rules_dialog(qtbot):
    d = dlg.RulesDialog(moves(), preset="Miktar")
    qtbot.addWidget(d)
    d.name.setText("Sınıf")
    row = d.editor.rows[0]
    row.op.setCurrentIndex(row.op.findData("ge"))
    row.value.setText("7")
    d.value.setText("Yüksek")
    d.add_rule()
    row = d.editor.rows[0]
    row.col.setCurrentText("Ekip")
    row.value.setText("X")
    d.value.setText("X ekibi")
    d.default.setText("Diğer")
    d.refresh()
    assert d.buttons.button(QDialogButtonBox.Ok).isEnabled(), d.status.text()
    assert d.preview.model_.frame()["Sınıf"].tolist() == ["Yüksek", "Diğer", "X ekibi", "Yüksek"]
    d.list.setCurrentRow(1)
    d.move(-1)
    assert d.params()["rules"][0]["value"] == "X ekibi"


def test_period_bar_drives_period_filter(env, qtbot):
    w, *_ = env
    w.session.add_source("E", moves())
    w.refresh_all("E")
    w.period_bar.set_period(date(2026, 11, 10), "Gündüz")
    assert "elle" in w.period_bar.auto_label.text()
    w.quick_step("period_filter", {"column": "İşlem Zamanı"})
    assert w.table.model().rowCount() == 3
    w.period_bar.set_period(date(2026, 11, 10), "Akşam")
    assert w.table.model().rowCount() == 1
    w.period_bar.set_auto()
    assert "otomatik" in w.period_bar.auto_label.text()


def test_period_filter_dialog_shows_period(env, qtbot):
    w, *_ = env
    w.period_bar.set_period(date(2026, 11, 10), "Gündüz")
    d = dlg.PeriodFilterDialog(moves(), context=w.session.context)
    qtbot.addWidget(d)
    d.refresh()
    assert "3 satır" in d.status.text()


def test_shift_settings_dialog(env, qtbot):
    w, lib, *_ = env
    d = sg.ShiftSettingsDialog(lib, w)
    qtbot.addWidget(d)
    d.table.setRowCount(0)
    for s in ({"name": "Sabah", "start": "06:00", "end": "14:00"}, {"name": "Öğle", "start": "14:00", "end": "22:00"},
              {"name": "Gece", "start": "22:00", "end": "06:00"}):
        d._row(s)
    d._save()
    assert d.result() == QDialog.Accepted
    assert [s["name"] for s in lib.get_setting("shifts")] == ["Sabah", "Öğle", "Gece"]
    d2 = sg.ShiftSettingsDialog(lib, w)
    qtbot.addWidget(d2)
    d2.table.item(0, 2).setText("15:00")  # Öğle ile çakışır
    d2._save()
    assert "çakışıyor" in d2.status.text()


def _setup_flow(w, tmp_path, mail=None):
    s = w.session
    path = tmp_path / "rapor.xlsx"
    moves().to_excel(path, index=False)
    s.add_source("Hareketler", moves(), path=str(path))
    s.add_step("Hareketler", "period_filter", {"column": "İşlem Zamanı"})
    s.add_derived("Ekip Özeti", "group", ["Hareketler"], {"by": ["Ekip"], "values": [{"column": "Miktar", "func": "sum"}]})
    s.workflow.name = "Vardiya Raporu"
    s.set_outputs([{"dataset": "Ekip Özeti", "sheet": "Özet",
                    "chart": {"type": "col", "category": "Ekip", "values": []}}])
    s.set_run_settings({"output_dir": str(tmp_path / "cikti"), "file_name": "{akis} {tarih} {vardiya}",
                        "open_after": False, "archive": {"enabled": True, "sets": {}},
                        **({"mail": mail} if mail else {})})
    w.period_bar.set_period(date(2026, 11, 10), "Gündüz")
    w.refresh_all("Ekip Özeti")


def test_build_with_archive_chart_and_conflict(env, tmp_path, monkeypatch, no_modal):
    w, lib, arc, _ = env
    _setup_flow(w, tmp_path)
    w.build_report()
    out = tmp_path / "cikti" / "Vardiya Raporu 2026-11-10 Gündüz.xlsx"
    assert out.exists()
    import zipfile
    assert any(n.startswith("xl/charts/") for n in zipfile.ZipFile(out).namelist())
    assert arc.periods("Vardiya Raporu / Ekip Özeti")[0]["shift"] == "Gündüz"
    # aynı dönem aynı veriyle yeniden: kontrol ekranı açılmaz (bayat sayılmaz),
    # ama arşiv çakışması sorulur; 'Hayır' -> rapor oluşur, arşive yazılmaz
    from shiftflow.ui import report_dialogs as rd
    monkeypatch.setattr(rd.RunPlanDialog, "exec", lambda self: pytest.fail("kontrol ekranı açılmamalıydı"))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    w.build_report()
    assert any("zaten var" in a for a in asked)
    assert len(arc.periods("Vardiya Raporu / Ekip Özeti")) == 1


def test_archive_dialog_adds_previous_shift_source(env, tmp_path, qtbot, monkeypatch):
    w, lib, arc, _ = env
    _setup_flow(w, tmp_path)
    w.build_report()
    w.period_bar.set_period(date(2026, 11, 10), "Akşam")
    d = sg.ArchiveDialog(arc, w, period=w.period_bar.period(), shifts=w.session.shifts)
    qtbot.addWidget(d)
    assert d.sets.count() == 1 and d.periods.rowCount() == 1
    assert "10.11.2026 · Gündüz" in d.range_hint.text()

    def fake_exec(self):
        self._add()
        return QDialog.Accepted
    monkeypatch.setattr(sg.ArchiveDialog, "exec", fake_exec)
    w.open_archive()
    name = [n for n in w.session.workflow.sources if n.startswith("Ekip Özeti")][0]
    assert w.session.workflow.sources[name].archive["range"]["type"] == "previous_shift"
    assert set(w.session.result(name)["Ekip"]) == {"X", "Y"}
    assert "Arşiv: Önceki vardiya" in " ".join(w.ds_list.item(i).text() for i in range(w.ds_list.count()))


def test_report_settings_dialog_roundtrip(env, qtbot, tmp_path):
    w, *_ = env
    _setup_flow(w, tmp_path)
    d = sg.ReportSettingsDialog(w.session.workflow, w, shifts=w.session.shifts)
    qtbot.addWidget(d)
    d.mail_on.setChecked(True)
    d.to.setText("yanlis")
    d._save()
    assert "Geçersiz" in d.status.text() and d.result() != QDialog.Accepted
    d.to.setText("amir@firma.com; mudur@firma.com")
    d.per_shift.item(0, 1).setText("gece@firma.com")
    d.summary.setCurrentIndex(d.summary.findData("Ekip Özeti"))
    d._save()
    rs = d.settings_dict()
    assert rs["mail"]["per_shift"] == {"Gece": {"to": "gece@firma.com", "cc": ""}}
    assert rs["mail"]["summary_dataset"] == "Ekip Özeti" and rs["archive"]["enabled"]
    assert rs["output_dir"] == str(tmp_path / "cikti")


def test_build_then_mail_preview_send_with_confirmation(env, tmp_path, monkeypatch):
    w, lib, arc, log = env
    _setup_flow(w, tmp_path, mail={"enabled": True, "to": "amir@firma.com", "subject": "{akis} – {vardiya} {tarih}",
                                    "summary_dataset": "Ekip Özeti", "attach": True})
    seen = {}

    def preview_exec(self):
        seen["subject"] = self.subject.text()
        seen["html"] = self.draft.html
        self.send()  # onay sorusu -> Yes (fixture)
        return QDialog.Accepted
    monkeypatch.setattr(sg.MailPreviewDialog, "exec", preview_exec)
    w.build_report()
    assert seen["subject"] == "Vardiya Raporu – Gündüz 10.11.2026"
    assert "Ekip Özeti" in seen["html"]
    assert ("send", "amir@firma.com") in log
    assert any(x[0] == "attach" and x[1].endswith("Gündüz.xlsx") for x in log)


def test_mail_send_cancelled_does_not_send(env, tmp_path, monkeypatch, qtbot):
    w, lib, arc, log = env
    d = sg.MailPreviewDialog(mailer.MailDraft(to=["a@b.com"], subject="S", html="x"),
                             mailer.OutlookMailer(app_factory=lambda: _FakeOutlook(log)), w)
    qtbot.addWidget(d)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    d.send()
    assert not any(x[0] == "send" for x in log)
    d.open_draft()
    assert ("display", "a@b.com") in log and d.result_action == "draft"


def test_mail_preview_without_outlook_offers_eml(qtbot, tmp_path):
    f = tmp_path / "r.xlsx"
    f.write_bytes(b"x")
    d = sg.MailPreviewDialog(mailer.MailDraft(to=["a@b.com"], subject="S", html="x", attachments=[str(f)]),
                             mailer.OutlookMailer(), None)
    qtbot.addWidget(d)
    assert not d.b_send.isEnabled() and not d.b_draft.isEnabled()  # Linux: Outlook yok
    d.open_eml()
    assert d.result_action == "eml" and d.eml_path.endswith(".eml")


def test_export_dialog_chart_and_start_cell(env, tmp_path, qtbot, monkeypatch):
    w, *_ = env
    _setup_flow(w, tmp_path)
    from shiftflow.ui.source_dialogs import ExportDialog
    d = ExportDialog(w.session, w)
    qtbot.addWidget(d)
    items = d.items()
    assert items[0][0] == "Ekip Özeti" and items[0][2]["chart"]["category"] == "Ekip"
    d.table.item(0, 3).setText("b5")
    assert d.items()[0][2]["start_cell"] == "B5"
