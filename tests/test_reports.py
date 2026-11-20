"""Rapor tanıma, değişiklik yakalama ve 'Rapor oluştur' senaryoları."""

import json

import pandas as pd
import pytest

from shiftflow.engine import Session
from shiftflow.engine import reports as rp
from shiftflow.engine.autorun import ReportBuilder, format_file_name
from shiftflow.engine.errors import ShiftFlowError
from shiftflow.engine.excel_live import ComExcelProvider, FileWorkbookProvider, MultiProvider
from shiftflow.engine.library import ReportLibrary
from shiftflow.engine.workflow import Workflow

from fake_excel import FakeApp, FakeWorkbook, df_rows, wms_title


@pytest.fixture
def lib(tmp_path):
    lib = ReportLibrary(str(tmp_path / "lib.db"))
    yield lib
    lib.close()


def provider_with(*workbooks):
    return ComExcelProvider(apps_factory=lambda: [FakeApp(list(workbooks))])


def define(lib, df, name, keys=None):
    d = rp.ReportDefinition(name=name, columns=rp.columns_of(df), key_columns=keys or [str(c) for c in df.columns])
    return lib.save(d)


def scenario(lib, picking, staff, tmp_path):
    """Toplama raporu (WMS, kaydedilmemiş) + personel listesi (kayıtlı kitap)."""
    d1 = define(lib, picking, "Toplama Raporu")
    d2 = define(lib, staff, "Personel Listesi")
    s = Session()
    s.library = lib
    s.add_source("Toplama", picking, kind="report", report_id=d1.id)
    s.add_source("Personel", staff, kind="report", report_id=d2.id)
    s.add_step("Toplama", "filter", {"conditions": [{"column": "Toplanan", "op": "gt", "value": "0"}]})
    s.add_derived("Detay", "join", ["Toplama", "Personel"],
                  {"how": "left", "left_keys": ["Personel No"], "right_keys": ["Personel No"]})
    s.add_derived("Özet", "group", ["Detay"], {"by": ["Bölge"], "values": [{"column": "Toplanan", "func": "sum"}]})
    s.set_outputs([{"dataset": "Detay", "sheet": "Detay"}, {"dataset": "Özet", "sheet": "Özet"}])
    s.workflow.name = "Günlük"
    s.workflow.run_settings = {"output_dir": str(tmp_path / "cikti"), "file_name": "{akis} {tarih}"}
    return s, d1, d2


# ------------------------------------------------------------- başlık ve eşleştirme
def test_header_row_detected_below_title_rows(picking):
    rows = df_rows(picking, wms_title())
    h, score = rp.find_header_row(rows, list(picking.columns))
    assert h == 3 and score == 1.0
    assert rp.guess_header_row(rows) == 3


def test_recognition_ignores_case_and_spaces(picking):
    d = rp.ReportDefinition(name="T", columns=rp.columns_of(picking), key_columns=["Personel No", "Toplanan"])
    rows = df_rows(picking.rename(columns={"Personel No": "PERSONEL  NO"}))
    h, score = rp.find_header_row(rows, d.key_columns)
    assert score == 1.0


def test_match_prefers_correct_sheet_and_detects_ambiguity(picking, staff):
    d = rp.ReportDefinition(name="T", columns=rp.columns_of(picking), key_columns=list(picking.columns))
    p = provider_with(FakeWorkbook("Kitap1", {"Sheet1": df_rows(picking, wms_title())}),
                      FakeWorkbook("personel.xlsx", {"P": df_rows(staff)}, path="C:\\x"))
    cands = rp.match_definition(d, p.list_workbooks())
    assert len(cands) == 1 and cands[0].workbook_name == "Kitap1" and not cands[0].saved
    p2 = provider_with(FakeWorkbook("Kitap1", {"Sheet1": df_rows(picking)}),
                       FakeWorkbook("Kitap2", {"Sheet1": df_rows(picking)}))
    assert rp.is_ambiguous(rp.match_definition(d, p2.list_workbooks()))


def test_partial_key_match_threshold(picking):
    d = rp.ReportDefinition(name="T", columns=rp.columns_of(picking), key_columns=list(picking.columns))
    fewer = picking.drop(columns=["Tarih"])  # 4/5 = 0.8 -> hâlâ tanınır
    p = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(fewer)}))
    assert rp.match_definition(d, p.list_workbooks())
    fewer2 = picking.drop(columns=["Tarih", "Hedef"])  # 3/5 = 0.6 -> tanınmaz
    p = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(fewer2)}))
    assert not rp.match_definition(d, p.list_workbooks())


def test_hints(picking):
    d = rp.ReportDefinition(name="T", columns=rp.columns_of(picking), key_columns=list(picking.columns),
                            workbook_hint="toplama")
    p = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(picking)}),
                      FakeWorkbook("Toplama_10112026.xlsx", {"S": df_rows(picking)}, path="C:\\x"))
    cands = rp.match_definition(d, p.list_workbooks())
    assert cands[0].workbook_name.startswith("Toplama") and not rp.is_ambiguous(cands)


def test_compare_columns(picking):
    exp = rp.columns_of(picking)
    changed = picking.rename(columns={"Toplanan": "Toplanan Adet", "Bölge": "BÖLGE"})
    changed["Yeni"] = 1
    changed["Hedef"] = changed["Hedef"].astype(str) + " ad"
    ch = rp.compare_columns(exp, changed)
    assert ch["missing"] == ["Toplanan"]
    assert ch["suggestions"]["Toplanan"] == "Toplanan Adet"
    assert ch["auto_mapped"] == {"BÖLGE": "Bölge"}
    assert "Yeni" in ch["extra"]
    assert ("Hedef", "number", "text") in ch["type_changes"]


def test_fingerprint_stable_and_sensitive(picking):
    assert rp.fingerprint(picking) == rp.fingerprint(picking.copy())
    other = picking.copy()
    other.loc[0, "Toplanan"] = 999
    assert rp.fingerprint(picking) != rp.fingerprint(other)


# ------------------------------------------------------------- COM sağlayıcı (sahte nesnelerle)
def test_com_provider_reads_unsaved_and_types(picking):
    p = provider_with(FakeWorkbook("Kitap1", {"Sheet1": df_rows(picking, wms_title()), "Boş": []}))
    wbs = p.list_workbooks()
    assert wbs[0].saved is False and wbs[0].path == ""
    assert [s.name for s in wbs[0].sheets] == ["Sheet1", "Boş"]
    rows = p.read(wbs[0].id, "Sheet1")
    from shiftflow.engine import io as sio
    df = sio.frame_from_rows(rows, 3)
    assert list(df.columns) == list(picking.columns)
    assert df["Toplanan"].tolist() == picking["Toplanan"].tolist()
    assert pd.api.types.is_datetime64_any_dtype(df["Tarih"])


def test_com_provider_single_cell_and_errors():
    p = provider_with(FakeWorkbook("K", {"S": [["tek"]]}))
    assert p.read(p.list_workbooks()[0].id, "S") == [["tek"]]

    def boom():
        raise Exception("Call was rejected by callee. (0x8001010A)")
    with pytest.raises(ShiftFlowError) as e:
        ComExcelProvider(apps_factory=boom).list_workbooks()
    assert "meşgul" in e.value.message
    with pytest.raises(ShiftFlowError):
        provider_with().read("yok", "S")


def test_file_provider_and_multi(make_xlsx, picking, staff):
    path = make_xlsx("r.xlsx", {"Toplama": picking, "Personel": staff})
    fp = FileWorkbookProvider([path])
    wbs = fp.list_workbooks()
    assert [s.name for s in wbs[0].sheets] == ["Toplama", "Personel"]
    mp = MultiProvider([provider_with(FakeWorkbook("Kitap1", {"S": df_rows(picking)})), fp])
    assert len(mp.list_workbooks()) == 2
    assert mp.read(path, "Personel")[0][0] == "Personel No"


# ------------------------------------------------------------- kütüphane
def test_library_crud_and_unique_name(lib, picking):
    d = define(lib, picking, "Toplama")
    assert lib.get(d.id).name == "Toplama"
    with pytest.raises(ShiftFlowError):
        define(lib, picking, "Toplama")
    with pytest.raises(ShiftFlowError):
        lib.save(rp.ReportDefinition(name="X", columns=[], key_columns=[]))
    lib.delete(d.id)
    assert lib.list() == []


# ------------------------------------------------------------- Rapor oluştur
def test_build_from_open_reports_end_to_end(lib, picking, staff, tmp_path):
    s, d1, d2 = scenario(lib, picking, staff, tmp_path)
    new_pick = pd.concat([picking, picking], ignore_index=True)
    prov = provider_with(FakeWorkbook("Kitap1", {"Sheet1": df_rows(new_pick, wms_title())}),
                         FakeWorkbook("Personel.xlsx", {"Liste": df_rows(staff)}, path="C:\\ik"))
    b = ReportBuilder(s, lib, prov)
    plans = b.plan()
    assert [p.status for p in plans] == ["ok", "ok"]
    assert plans[0].chosen.workbook_name == "Kitap1"
    res = b.build(plans)
    assert res.ok, res.errors
    assert pd.ExcelFile(res.path).sheet_names == ["Detay", "Özet"]
    assert len(pd.read_excel(res.path, "Detay")) == 10  # 12 satır - 2 sıfır toplama
    assert lib.recent_runs()[0]["status"] == "ok"


def test_same_report_again_is_flagged_stale(lib, picking, staff, tmp_path):
    s, *_ = scenario(lib, picking, staff, tmp_path)
    prov = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(picking)}),
                         FakeWorkbook("P.xlsx", {"S": df_rows(staff)}, path="C:\\"))
    from datetime import date
    from shiftflow.engine import periods as pr
    b = ReportBuilder(s, lib, prov, period=pr.make_period(date(2026, 11, 10), "Gündüz", pr.DEFAULT_SHIFTS))
    assert b.build(b.plan()).ok
    # aynı dönemi aynı veriyle yeniden oluşturmak sorun değil
    assert b.plan()[0].status == "ok"
    # ertesi gün aynı veri -> rapor yenilenmemiş
    b = ReportBuilder(s, lib, prov, period=pr.make_period(date(2026, 11, 11), "Gündüz", pr.DEFAULT_SHIFTS))
    plans = b.plan()
    assert plans[0].status == "stale" and plans[0].blocking
    assert plans[1].status == "ok"  # personel listesi (tarihsiz ana veri) her gün aynı olabilir
    with pytest.raises(ShiftFlowError):
        b.build(plans)
    plans[0].accept_stale = True
    r2 = b.build(plans)
    assert r2.ok and any("aynı veriyle" in n for n in r2.notes)


def test_changed_report_needs_mapping_and_learns(lib, picking, staff, tmp_path):
    s, d1, _ = scenario(lib, picking, staff, tmp_path)
    changed = picking.rename(columns={"Toplanan": "Toplanan Miktar"})
    changed["Yeni Alan"] = "x"
    prov = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(changed)}),
                         FakeWorkbook("P.xlsx", {"S": df_rows(staff)}, path="C:\\"))
    b = ReportBuilder(s, lib, prov)
    plans = b.plan()
    p = plans[0]
    assert p.status == "needs_mapping"
    assert p.changes["suggestions"] == {"Toplanan": "Toplanan Miktar"}
    b.apply_mapping(p, {"Toplanan Miktar": "Toplanan"})
    assert p.status == "changed"  # yeni sütun var ama engel değil
    assert b.build(plans).ok
    # Eşleme rapor tanımına öğretildi: başka bir iş akışı da sormadan çalışır
    assert lib.get(d1.id).column_map == {"Toplanan Miktar": "Toplanan"}
    s2 = Session()
    s2.library = lib
    s2.add_source("T", picking, kind="report", report_id=d1.id)
    changed2 = changed.copy()
    changed2.loc[0, "Hedef"] = 1  # farklı veri (bayat sayılmasın)
    b2 = ReportBuilder(s2, lib, provider_with(FakeWorkbook("Kitap5", {"S": df_rows(changed2)})))
    assert b2.plan()[0].status == "changed"


def test_errors_prevent_output(lib, picking, staff, tmp_path):
    s, *_ = scenario(lib, picking, staff, tmp_path)
    bad = picking.copy()
    bad["Toplanan"] = "metin"  # filtre sayısal karşılaştırma yapamaz
    prov = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(bad)}),
                         FakeWorkbook("P.xlsx", {"S": df_rows(staff)}, path="C:\\"))
    b = ReportBuilder(s, lib, prov)
    plans = b.plan()
    assert plans[0].status == "changed" and plans[0].changes["type_changes"]
    res = b.build(plans)
    assert not res.ok and "Toplama" in res.errors
    assert not (tmp_path / "cikti").exists() or not list((tmp_path / "cikti").iterdir())
    assert lib.recent_runs()[0]["status"] == "error"


def test_not_found_and_ambiguous_then_choose(lib, picking, staff, tmp_path):
    s, *_ = scenario(lib, picking, staff, tmp_path)
    b = ReportBuilder(s, lib, provider_with(FakeWorkbook("P.xlsx", {"S": df_rows(staff)}, path="C:\\")))
    plans = b.plan()
    assert plans[0].status == "not_found"
    prov = provider_with(FakeWorkbook("Kitap1", {"S": df_rows(picking)}),
                         FakeWorkbook("Kitap2", {"S": df_rows(picking.head(3))}),
                         FakeWorkbook("P.xlsx", {"S": df_rows(staff)}, path="C:\\"))
    b = ReportBuilder(s, lib, prov)
    plans = b.plan()
    assert plans[0].status == "ambiguous"
    b.choose(plans[0], [c for c in plans[0].candidates if c.workbook_name == "Kitap2"][0])
    assert plans[0].status == "ok" and len(plans[0].df) == 3


def test_fallback_to_file(lib, picking, staff, tmp_path, make_xlsx):
    s, *_ = scenario(lib, picking, staff, tmp_path)
    path = make_xlsx("dun.xlsx", {"Toplama": picking})
    b = ReportBuilder(s, lib, provider_with(FakeWorkbook("P.xlsx", {"S": df_rows(staff)}, path="C:\\")))
    plans = b.plan()
    b.use_file(plans[0], path, "Toplama")
    assert plans[0].status == "ok"
    assert b.build(plans).ok


def test_mixed_sources_file_and_report(lib, picking, staff, tmp_path, make_xlsx):
    d1 = define(lib, picking, "Toplama")
    staff_path = make_xlsx("p.xlsx", {"P": staff})
    s = Session()
    s.library = lib
    s.add_source("Toplama", picking, kind="report", report_id=d1.id)
    s.add_source("Personel", staff, path=staff_path, sheet="P")
    s.workflow.run_settings = {"output_dir": str(tmp_path / "o")}
    b = ReportBuilder(s, lib, provider_with(FakeWorkbook("Kitap1", {"S": df_rows(picking)})))
    plans = b.plan()
    assert [p.mode for p in plans] == ["report", "file"]
    assert b.build(plans).ok


def test_output_file_names(tmp_path, lib, picking, staff):
    from datetime import datetime
    assert format_file_name("{akis} {tarih} {saat}", "Gün/Sonu", datetime(2026, 11, 10, 7, 5)) == "Gün_Sonu 2026-11-10 0705"
    s, *_ = scenario(lib, picking, staff, tmp_path)
    b = ReportBuilder(s, lib, None)
    p1 = b.output_path(datetime(2026, 11, 10))
    open(p1, "w").close()
    p2 = b.output_path(datetime(2026, 11, 10))
    assert p1 != p2 and p2.endswith("(2).xlsx")


def test_workflow_embeds_definitions_and_imports_on_other_pc(lib, picking, staff, tmp_path):
    s, d1, d2 = scenario(lib, picking, staff, tmp_path)
    p = tmp_path / "akis.json"
    s.save_workflow(str(p))
    data = json.loads(p.read_text(encoding="utf-8"))
    assert set(data["reports"]) == {d1.id, d2.id}
    assert data["sources"][0]["report_id"] == d1.id
    other = ReportLibrary(str(tmp_path / "baska_pc.db"))
    s2 = Session()
    s2.library = other
    s2.load_workflow(str(p))
    assert other.get(d1.id).name == "Toplama Raporu"
    other.close()


def test_v1_workflow_still_opens():
    v1 = {"format": "shiftflow-workflow", "schema_version": 1, "name": "eski",
          "sources": [{"name": "A", "kind": "file", "path": "", "sheet": None, "header": True,
                       "expected_columns": [], "column_map": {}}],
          "datasets": [{"name": "A", "origin": {"type": "source", "source": "A"}, "steps": []}], "outputs": []}
    wf = Workflow.from_dict(v1)
    assert wf.sources["A"].report_id is None and wf.reports == {}


def test_library_trash_and_restore(tmp_path):
    import pandas as pd
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.engine.reports import ReportDefinition
    lib = ReportLibrary(str(tmp_path / "x.db"))
    d = lib.save(ReportDefinition(name="Toplama", columns=[], key_columns=["A", "B"]))
    lib.delete(d.id)
    assert lib.get(d.id) is None and lib.trash()[0]["kind"] == "report"
    lib.save(ReportDefinition(name="Toplama", columns=[], key_columns=["C", "D"]))  # aynı adla yenisi
    name = lib.restore(lib.trash()[0]["id"])
    assert name == "Toplama (geri)" and lib.by_name("Toplama (geri)").key_columns == ["A", "B"]
    m = lib.save_reference("P", pd.DataFrame({"x": [1]}))
    lib.save_reference("P", pd.DataFrame({"x": [1, 2]}), rid=m["id"])
    old = [t for t in lib.trash() if t["kind"] == "reference_old"][0]
    lib.restore(old["id"])
    assert len(lib.reference_df(m["id"])) == 1  # eski içerik geri geldi
    lib.purge_trash(days=-1)
    assert lib.trash() == []
