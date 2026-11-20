"""Aşama 2-4: vardiya/dönem, arşiv, grafik ve şablon, mail taslağı."""

import email
from datetime import date, datetime

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook  # noqa: F401

from shiftflow.engine import Session
from shiftflow.engine import mailer
from shiftflow.engine import operations as ops
from shiftflow.engine import periods as pr
from shiftflow.engine.archive import Archive
from shiftflow.engine.autorun import ReportBuilder, mail_draft
from shiftflow.engine.errors import ShiftFlowError
from shiftflow.engine.excel_out import template_warnings, write_excel
from shiftflow.engine.library import ReportLibrary

S = pr.DEFAULT_SHIFTS
NIGHT = [{"name": "Sabah", "start": "06:00", "end": "14:00"}, {"name": "Öğle", "start": "14:00", "end": "22:00"},
         {"name": "Gece", "start": "22:00", "end": "06:00"}]


@pytest.fixture
def lib(tmp_path):
    lib = ReportLibrary(str(tmp_path / "lib.db"))
    yield lib
    lib.close()


@pytest.fixture
def arc(tmp_path):
    a = Archive(str(tmp_path / "archive.db"))
    yield a
    a.close()


# ------------------------------------------------------------- vardiya ve dönem
@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 11, 10, 15, 50), ("2026-11-10", "Gündüz")),   # vardiya bitmek üzere -> bu vardiya
    (datetime(2026, 11, 10, 16, 40), ("2026-11-10", "Gündüz")),   # yeni vardiyanın ilk 2 saati -> biten vardiya
    (datetime(2026, 11, 10, 19, 0), ("2026-11-10", "Akşam")),
    (datetime(2026, 11, 11, 0, 30), ("2026-11-10", "Akşam")),     # gece yarısından sonra -> dünün akşamı
    (datetime(2026, 11, 11, 7, 0), ("2026-11-11", "Gece")),
])
def test_auto_period_default_shifts(now, expected):
    p = pr.auto_period(now, S)
    assert (p.date.isoformat(), p.shift) == expected and p.auto


def test_overnight_shift_dates_belong_to_start_day():
    p = pr.auto_period(datetime(2026, 11, 11, 3, 0), NIGHT)
    assert (p.date.isoformat(), p.shift) == ("2026-11-10", "Gece")
    assert p.start == datetime(2026, 11, 10, 22) and p.end == datetime(2026, 11, 11, 6)
    prev = pr.previous(p, NIGHT)
    assert (prev.date.isoformat(), prev.shift) == ("2026-11-10", "Öğle")
    first = pr.make_period(date(2026, 11, 11), "Sabah", NIGHT)
    assert pr.previous(first, NIGHT).key == "2026-11-10|Gece"


def test_manual_selection_and_whole_day():
    p = pr.make_period(date(2026, 11, 9), None, S)
    assert p.shift_label == pr.WHOLE_DAY and (p.end - p.start).days == 1
    with pytest.raises(ShiftFlowError):
        pr.make_period(date(2026, 11, 9), "Yok", S)


def test_shift_validation():
    assert pr.validate_shifts([{"name": "A", "start": "8:00", "end": "20:00"},
                               {"name": "B", "start": "20:00", "end": "08:00"}])[0]["start"] == "08:00"
    with pytest.raises(ShiftFlowError):
        pr.validate_shifts([{"name": "A", "start": "08:00", "end": "17:00"}, {"name": "B", "start": "16:00", "end": "00:00"}])
    with pytest.raises(ShiftFlowError):
        pr.validate_shifts([{"name": "A", "start": "25:00", "end": "08:00"}])
    with pytest.raises(ShiftFlowError):
        pr.validate_shifts([{"name": "A", "start": "08:00", "end": "16:00"}, {"name": "a", "start": "16:00", "end": "00:00"}])


def _events():
    return pd.DataFrame({
        "İşlem Zamanı": pd.to_datetime(["2026-11-10 07:59", "2026-11-10 08:00", "2026-11-10 12:00",
                                        "2026-11-10 15:59", "2026-11-10 16:00", None]),
        "Miktar": [1, 2, 3, 4, 5, 6]})


def test_period_filter_uses_selected_period():
    s = Session()
    s.add_source("E", _events())
    s.set_period(pr.make_period(date(2026, 11, 10), "Gündüz", S))
    s.add_step("E", "period_filter", {"column": "İşlem Zamanı"})
    assert s.result("E")["Miktar"].tolist() == [2, 3, 4]
    s.set_period(pr.make_period(date(2026, 11, 10), "Gece", S))  # dönem değişince sonuç değişir
    assert s.result("E")["Miktar"].tolist() == [1]
    s.set_period(pr.make_period(date(2026, 11, 10), None, S))
    assert len(s.result("E")) == 5
    st = s.step_statuses("E")[1]
    assert any("boş" in w for w in st.warnings)


def test_period_filter_without_period_errors():
    with pytest.raises(ShiftFlowError):
        ops.get("period_filter").run([_events()], {"column": "İşlem Zamanı"}, "t")


# ------------------------------------------------------------- arşiv
def test_archive_write_replace_and_read(arc):
    p1 = pr.make_period(date(2026, 11, 10), "Gündüz", S)
    p2 = pr.make_period(date(2026, 11, 10), "Akşam", S)
    df = pd.DataFrame({"Ekip": ["A", "B"], "Toplanan": [10, 20], "Tarih Saat": pd.to_datetime(["2026-11-10 09:00"] * 2)})
    arc.write("Günlük / Özet", df, p1)
    arc.write("Günlük / Özet", df.assign(Toplanan=[1, 2]), p1)  # aynı dönem tekrar -> değiştirilir
    arc.write("Günlük / Özet", df.assign(Yeni=[True, False]), p2)  # yeni sütun eklenir
    assert arc.periods("Günlük / Özet")[0]["rows"] == 2
    out = arc.read("Günlük / Özet")
    assert len(out) == 4
    assert list(out.columns[:2]) == ["Tarih", "Vardiya"]
    assert out[out["Vardiya"] == "Gündüz"]["Toplanan"].tolist() == [1, 2]
    assert pd.api.types.is_datetime64_any_dtype(out["Tarih Saat"])
    assert out["Yeni"].isna().sum() == 2
    meta = arc.sets()[0]
    assert meta["periods"] == 2 and meta["first"] == "2026-11-10"


def test_archive_ranges(arc):
    df = pd.DataFrame({"x": [1]})
    for d in (8, 9, 10):
        for sh in ("Gece", "Gündüz", "Akşam"):
            arc.write("K", df.assign(x=d * 10 + ["Gece", "Gündüz", "Akşam"].index(sh)), pr.make_period(date(2026, 11, d), sh, S))
    cur = pr.make_period(date(2026, 11, 10), "Gece", S)
    got = lambda spec: arc.resolve(spec, cur, S)[0]["x"].tolist()  # noqa: E731
    assert got({"set": "K", "range": {"type": "previous_shift"}}) == [92]          # dünün akşamı
    assert got({"set": "K", "range": {"type": "same_shift_previous_day"}}) == [90]
    assert got({"set": "K", "range": {"type": "previous_day"}}) == [90, 91, 92]
    assert len(got({"set": "K", "range": {"type": "last_days", "days": 2}})) == 6
    assert len(got({"set": "K", "range": {"type": "all"}})) == 9
    with pytest.raises(ShiftFlowError):
        arc.read("Yok")


def _run_setup(lib, arc, tmp_path, df, period, extra=None):
    s = Session()
    s.library, s.archive = lib, arc
    path = tmp_path / "rapor.xlsx"
    df.to_excel(path, index=False)
    s.add_source("Toplama", df, path=str(path))
    s.add_derived("Özet", "group", ["Toplama"], {"by": ["Ekip"], "values": [{"column": "Toplanan", "func": "sum"}]})
    s.workflow.name = "Vardiya"
    s.set_outputs([{"dataset": "Özet", "sheet": "Özet"}])
    s.workflow.run_settings = {"output_dir": str(tmp_path / "o"), "file_name": "{akis} {tarih} {vardiya}",
                               "archive": {"enabled": True}, **(extra or {})}
    return s, ReportBuilder(s, lib, None, arc, period)


def test_build_archives_and_previous_shift_comparison(lib, arc, tmp_path):
    df = pd.DataFrame({"Ekip": ["A", "B", "A"], "Toplanan": [10, 20, 5]})
    p1 = pr.make_period(date(2026, 11, 10), "Gündüz", S)
    s, b = _run_setup(lib, arc, tmp_path, df, p1)
    res = b.build(b.plan())
    assert res.ok and res.path.endswith("Vardiya 2026-11-10 Gündüz.xlsx")
    assert any("Arşive yazıldı: Vardiya / Özet" in n for n in res.notes)
    # Sonraki vardiya: önceki vardiyayı arşivden kaynak olarak ekle ve karşılaştır
    s.add_source("Önceki", arc.read("Vardiya / Özet"), kind="archive",
                 archive={"set": "Vardiya / Özet", "range": {"type": "previous_shift"}})
    s.add_step("Özet", "lookup", {"table": "Önceki", "keys": [["Ekip", "Ekip"]],
                                  "columns": [{"column": "Toplanan (Toplam)", "as": "Önceki Vardiya"}]})
    s.add_step("Özet", "calc", {"name": "Fark", "formula": "[Toplanan (Toplam)] - [Önceki Vardiya]"})
    df2 = pd.DataFrame({"Ekip": ["A", "B"], "Toplanan": [30, 10]})
    df2.to_excel(tmp_path / "rapor.xlsx", index=False)
    p2 = pr.make_period(date(2026, 11, 10), "Akşam", S)
    b2 = ReportBuilder(s, lib, None, arc, p2)
    plans = b2.plan()
    a = [x for x in plans if x.mode == "archive"][0]
    assert "önceki vardiya" in a.messages[0] and len(a.df) == 2
    assert b2.archive_conflicts() == []
    res2 = b2.build(plans)
    assert res2.ok
    out = pd.read_excel(res2.path, "Özet").set_index("Ekip")
    assert out.loc["A", "Önceki Vardiya"] == 15 and out.loc["A", "Fark"] == 15
    # Aynı dönemi yeniden oluşturmak çakışma olarak bildirilir ve kayıt değiştirilir
    assert b2.archive_conflicts() == ["Vardiya / Özet"]
    assert len(arc.periods("Vardiya / Özet")) == 2


def test_archive_source_empty_period_is_warning_not_block(lib, arc, tmp_path):
    df = pd.DataFrame({"Ekip": ["A"], "Toplanan": [1]})
    p = pr.make_period(date(2026, 11, 10), "Gündüz", S)
    arc.write("Vardiya / Özet", pd.DataFrame({"Ekip": ["A"], "Toplanan (Toplam)": [1]}), p)
    s, b = _run_setup(lib, arc, tmp_path, df, pr.make_period(date(2026, 11, 20), "Gündüz", S))
    s.add_source("Önceki", arc.read("Vardiya / Özet"), kind="archive",
                 archive={"set": "Vardiya / Özet", "range": {"type": "previous_shift"}})
    plans = b.plan()
    a = [x for x in plans if x.mode == "archive"][0]
    assert a.df.empty and not a.blocking and "kayıt yok" in a.messages[-1]
    assert list(a.df.columns)[:2] == ["Tarih", "Vardiya"]


# ------------------------------------------------------------- grafik ve şablon
def test_chart_written(tmp_path):
    pivot = pd.DataFrame({"Vardiya": ["Akşam", "Gece", "Genel Toplam"], "A Blok": [5, 7, 12], "B Blok": [1, 2, 3],
                          "Genel Toplam": [6, 9, 15]})
    w = []
    p = tmp_path / "g.xlsx"
    write_excel(str(p), [("Pivot", pivot, {"chart": {"type": "col", "category": "Vardiya", "title": "Bloklar"}})], warnings=w)
    import zipfile
    xml = zipfile.ZipFile(p).read("xl/charts/chart1.xml").decode()
    assert xml.count("<ser>") == 2  # Genel Toplam sütunu dışarıda
    assert "$A$2:$A$3" in xml and "$A$4" not in xml  # Genel Toplam satırı dışarıda
    assert "barChart" in xml and "Bloklar" in xml
    assert w == []


def test_chart_missing_columns_warn_not_fail(tmp_path):
    df = pd.DataFrame({"Ekip": ["A"], "Adet": [1]})
    w = []
    write_excel(str(tmp_path / "x.xlsx"), [("S", df, {"chart": {"category": "Yok"}})], warnings=w)
    assert w and "grafik eklenmedi" in w[0]


def test_template_keeps_formatting_and_formulas(tmp_path):
    t = tmp_path / "sablon.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Rapor"
    ws["A1"] = "VARDİYA RAPORU"
    ws["A1"].font = ws["A1"].font.copy(bold=True, size=16)
    ws["A2"] = "{vardiya}"
    ws["E1"] = "=SUM(B5:B100)"
    ws.column_dimensions["A"].width = 30
    wb.create_sheet("Kapak")
    wb.save(t)
    s = Session()
    s.add_source("T", pd.DataFrame({"Ekip": ["A", "B"], "Toplanan": [10, 20]}))
    s.workflow.run_settings = {"template": {"path": str(t), "cells": [
        {"sheet": "Rapor", "cell": "A2", "value": "{vardiya} vardiyası – {tarih}"},
        {"sheet": "Yok", "cell": "A1", "value": "x"}]}}
    w = []
    out = tmp_path / "cikti.xlsx"
    s.export(str(out), [("T", "Rapor", {"start_cell": "A4"}), ("T", "Ek Sayfa")],
             context={"vardiya": "Gece", "tarih": "10.11.2026"}, warnings=w)
    wb2 = load_workbook(out)
    r = wb2["Rapor"]
    assert r["A1"].value == "VARDİYA RAPORU" and r["A1"].font.bold and r.column_dimensions["A"].width == 30
    assert r["A2"].value == "Gece vardiyası – 10.11.2026"
    assert r["E1"].value == "=SUM(B5:B100)"  # şablon formülü korunur
    assert [r["A4"].value, r["B5"].value] == ["Ekip", 10]
    assert wb2.sheetnames == ["Rapor", "Kapak", "Ek Sayfa"]
    assert any("Yok" in x for x in w)
    with pytest.raises(ShiftFlowError):  # şablonun üzerine yazılamaz
        s.export(str(t), [("T", "Rapor")])


def test_template_warnings_for_images(tmp_path):
    import zipfile
    p = tmp_path / "s.xlsx"
    Workbook().save(p)
    with zipfile.ZipFile(p, "a") as z:
        z.writestr("xl/media/image1.png", b"x")
    assert any("resim" in w for w in template_warnings(str(p)))


# ------------------------------------------------------------- mail
MAIL = {"enabled": True, "to": "amir@firma.com; mudur@firma.com", "cc": "kalite@firma.com",
        "per_shift": {"Gece": {"to": "gece.lideri@firma.com"}},
        "subject": "{akis} – {vardiya} vardiyası {tarih}", "intro": "Merhaba,\n{donem} raporu ektedir.",
        "summary_dataset": "Özet", "summary_rows": 10, "attach": True}


def test_mail_draft_and_eml(lib, arc, tmp_path):
    df = pd.DataFrame({"Ekip": ["A", "B"], "Toplanan": [1000, 2.5]})
    p = pr.make_period(date(2026, 11, 10), "Gece", S)
    s, b = _run_setup(lib, arc, tmp_path, df, p, {"mail": MAIL})
    res = b.build(b.plan())
    d = mail_draft(b, res)
    assert d.to == ["amir@firma.com", "mudur@firma.com", "gece.lideri@firma.com"]
    assert d.cc == ["kalite@firma.com"]
    assert d.subject == "Vardiya – Gece vardiyası 10.11.2026"
    assert "1.000" in d.html and "2,50" in d.html and "Gece" in d.html
    assert d.attachments == [res.path]
    d.validate()
    eml = mailer.save_eml(d, str(tmp_path / "taslak"))
    msg = email.message_from_bytes(open(eml, "rb").read())
    assert msg["X-Unsent"] == "1" and "gece.lideri@firma.com" in msg["To"]
    assert any(part.get_filename() == res.path.split("/")[-1] for part in msg.walk())


def test_mail_disabled_or_invalid(lib, arc, tmp_path):
    df = pd.DataFrame({"Ekip": ["A"], "Toplanan": [1]})
    s, b = _run_setup(lib, arc, tmp_path, df, pr.make_period(date(2026, 11, 10), "Gündüz", S))
    res = b.build(b.plan())
    assert mail_draft(b, res) is None
    d = mailer.MailDraft(to=["yanlis-adres"], subject="x")
    with pytest.raises(ShiftFlowError):
        d.validate()
    with pytest.raises(ShiftFlowError):
        mailer.MailDraft(to=[]).validate()


class _FakeItem:
    def __init__(self, log):
        self.log, self.Attachments = log, self
        self.To = self.CC = self.BCC = self.Subject = self.HTMLBody = ""

    def Add(self, p):
        self.log.append(("attach", p))

    def Display(self, modal):
        self.log.append(("display", self.To))

    def Send(self):
        self.log.append(("send", self.To))


class _FakeOutlook:
    def __init__(self, log):
        self.log = log

    def CreateItem(self, kind):
        return _FakeItem(self.log)


def test_outlook_display_and_send_with_fake(tmp_path):
    f = tmp_path / "r.xlsx"
    f.write_bytes(b"x")
    log = []
    m = mailer.OutlookMailer(app_factory=lambda: _FakeOutlook(log))
    d = mailer.MailDraft(to=["a@b.com", "c@d.com"], subject="S", html="<p>x</p>", attachments=[str(f)])
    m.display(d)
    assert ("display", "a@b.com; c@d.com") in log and ("send", "a@b.com; c@d.com") not in log
    m.send(d)
    assert ("send", "a@b.com; c@d.com") in log


def test_stale_rules_with_shifts(lib, arc, tmp_path):
    """Günlük tek rapor + dönem filtresi: aynı dosya vardiyalar için tekrar kullanılabilir.
    Vardiya başına ayrı rapor (filtre yok): aynı veri ikinci vardiyada 'yenilenmemiş' sayılır."""
    df = pd.DataFrame({"Ekip": ["A"], "Toplanan": [1], "Zaman": pd.to_datetime(["2026-11-10 09:00"])})
    d, g, a = (pr.make_period(date(2026, 11, 10), n, S) for n in ("Gece", "Gündüz", "Akşam"))
    s, b = _run_setup(lib, arc, tmp_path, df, d)
    assert b.build(b.plan()).ok
    b2 = ReportBuilder(s, lib, None, arc, g)
    assert b2.plan()[0].status == "stale"  # filtre yok: Gündüz raporu Gece'ninkiyle aynı olamaz
    s.add_step("Toplama", "period_filter", {"column": "Zaman"})
    b3 = ReportBuilder(s, lib, None, arc, a)
    assert b3.plan()[0].status == "ok"  # günlük rapor vardiyalara bölünüyor: sorun yok
    b4 = ReportBuilder(s, lib, None, arc, pr.make_period(date(2026, 11, 11), "Gece", S))
    assert b4.plan()[0].status == "stale"  # ertesi gün aynı dosya: yenilenmemiş
