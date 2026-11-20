"""Aşama 1: formül fonksiyonları, DÜŞEYARA, kural tablosu, referans tablolar."""

import pandas as pd
import pytest

from shiftflow.engine import Session
from shiftflow.engine import operations as ops
from shiftflow.engine.autorun import ReportBuilder
from shiftflow.engine.errors import MissingColumnError, ShiftFlowError
from shiftflow.engine.expression import evaluate
from shiftflow.engine.library import ReportLibrary


@pytest.fixture
def lib(tmp_path):
    lib = ReportLibrary(str(tmp_path / "lib.db"))
    yield lib
    lib.close()


@pytest.fixture
def locs():
    return pd.DataFrame({"Lokasyon Kodu": ["A-01", "A-02", "B-01", "B-01"],
                         "Bölge": ["Kuru", "Kuru", "Soğuk", "Soğuk (eski)"], "Kapasite": [100, 120, 80, 1]})


@pytest.fixture
def moves():
    return pd.DataFrame({
        "Lokasyon": ["A-01", "B-01", "C-09", "a-02 ", None],
        "Miktar": [10, 5, 3, 7, 1],
        "Başlangıç": pd.to_datetime(["2026-11-10 08:00", "2026-11-10 09:00", "2026-11-10 10:00",
                                     "2026-11-10 11:00", "2026-11-10 12:00"]),
        "Bitiş": pd.to_datetime(["2026-11-10 08:30", "2026-11-10 09:50", "2026-11-10 10:05",
                                 "2026-11-10 11:20", None]),
    })


# ------------------------------------------------------------- formüller
@pytest.mark.parametrize("formula,expected", [
    ('EĞER([Miktar] >= 7; "Çok"; "Az")', ["Çok", "Az", "Az", "Çok", "Az"]),
    ('eğer(ve([Miktar] > 2; [Miktar] < 8); 1; 0)', [0, 1, 1, 1, 0]),
    ('EĞER([Miktar]=10;"on";EĞER([Miktar]=5;"beş";"diğer"))', ["on", "beş", "diğer", "diğer", "diğer"]),
    ("YUVARLA([Miktar] / 3; 1)", [3.3, 1.7, 1.0, 2.3, 0.3]),
    ("SOLDAN([Lokasyon]; 1)", ["A", "B", "C", "a", ""]),
    ("([Bitiş] - [Başlangıç]) * 24 * 60", [30, 50, 5, 20, None]),
    ("SAAT([Başlangıç])", [8, 9, 10, 11, 12]),
    ("EĞERHATA(10 / ([Miktar] - 5); -1)", [2, -1, -5, 5, -2.5]),
    ('EBOŞSA([Lokasyon])', [False, False, False, False, True]),
    ("MAK([Miktar]; 6)", [10, 6, 6, 7, 6]),
    ("=[Miktar] ^ 2", [100, 25, 9, 49, 1]),
    ('IF([Miktar] <> 5; "x"; "y")', ["x", "y", "x", "x", "x"]),
])
def test_functions(moves, formula, expected):
    v, _ = evaluate(formula, moves)
    got = [None if (isinstance(x, float) and pd.isna(x)) else x for x in v.tolist()]
    assert got == expected


def test_guarded_division_no_warning(moves):
    _, d = evaluate("EĞERHATA(10 / ([Miktar] - 5); 0)", moves)
    assert d == 0
    _, d = evaluate("10 / ([Miktar] - 5)", moves)
    assert d == 1


def test_formula_errors(moves):
    with pytest.raises(ShiftFlowError):
        evaluate("BİLİNMEYEN([Miktar])", moves)
    with pytest.raises(ShiftFlowError):
        evaluate("EĞER([Miktar] > 1; 2", moves)
    with pytest.raises(ShiftFlowError):
        evaluate("Miktar * 2", moves)  # köşeli parantez unutulmuş
    with pytest.raises(MissingColumnError):
        evaluate("EĞER([Yok] > 1; 1; 0)", moves)


def test_condition_compares_two_columns():
    df = pd.DataFrame({"Toplanan": [5, 10, 12], "Hedef": [10, 10, 10]})
    r = ops.get("filter").run([df], {"conditions": [{"column": "Toplanan", "op": "ge", "value": "[Hedef]"}]}, "t")
    assert r.df["Toplanan"].tolist() == [10, 12]


# ------------------------------------------------------------- DÜŞEYARA
LK = {"table": "Lokasyonlar", "keys": [["Lokasyon", "Lokasyon Kodu"]],
      "columns": [{"column": "Bölge"}, {"column": "Kapasite", "as": "Lokasyon Kapasitesi"}]}


def test_lookup_keeps_rows_and_reports(moves, locs):
    r = ops.get("lookup").run([moves, locs], LK, "t")
    assert len(r.df) == len(moves)
    assert r.df["Bölge"].tolist()[:2] == ["Kuru", "Soğuk"]  # B-01 tekrarında ilki
    assert r.df["Bölge"].iloc[3] == "Kuru"  # 'a-02 ' -> A-02: Excel gibi harf duyarsız, boşluk kırpılır
    assert pd.isna(r.df["Bölge"].iloc[2])  # C-09 yok
    assert pd.api.types.is_numeric_dtype(r.df["Lokasyon Kapasitesi"])
    assert any("birden çok" in w for w in r.warnings)
    assert any("karşılığı" in w for w in r.warnings)


def test_lookup_duplicate_error_and_missing_value(moves, locs):
    with pytest.raises(ShiftFlowError):
        ops.get("lookup").run([moves, locs], {**LK, "on_duplicate": "error"}, "t")
    r = ops.get("lookup").run([moves, locs], {**LK, "columns": [{"column": "Bölge"}], "if_missing": "Tanımsız"}, "t")
    assert r.df["Bölge"].tolist()[2:] == ["Tanımsız", "Kuru", "Tanımsız"]


def test_lookup_in_workflow_follows_reference_changes(moves, locs):
    s = Session()
    s.add_source("Hareketler", moves)
    s.add_source("Lokasyonlar", locs)
    s.add_step("Hareketler", "lookup", LK)
    assert "Bölge" in s.result("Hareketler").columns
    # Arama tablosunda değişiklik -> sonuç güncellenir (bağımlılık izlenir)
    s.add_step("Lokasyonlar", "replace", {"column": "Bölge", "find": "Kuru", "replace": "Ambient", "whole_cell": True})
    assert s.result("Hareketler")["Bölge"].iloc[0] == "Ambient"
    # Arama tablosu silinemez, çünkü kullanılıyor
    with pytest.raises(ShiftFlowError):
        s.delete_dataset("Lokasyonlar")
    # Yeniden adlandırma başvuruyu günceller
    s.rename_dataset("Lokasyonlar", "Lokasyon Ana Verisi")
    assert s.workflow.dataset("Hareketler").steps[0].params["table"] == "Lokasyon Ana Verisi"
    assert len(s.result("Hareketler")) == 5


def test_lookup_cycle_rejected(moves, locs):
    s = Session()
    s.add_source("A", moves)
    s.add_derived("B", "copy", ["A"], {})
    with pytest.raises(ShiftFlowError):  # A, kendisinden türeyen B'ye bakamaz
        s.add_step("A", "lookup", {"table": "B", "keys": [["Lokasyon", "Lokasyon"]], "columns": [{"column": "Miktar", "as": "M2"}]})


# ------------------------------------------------------------- kural tablosu
def test_rules_first_match_wins(moves):
    p = {"name": "Durum", "default": "Normal", "rules": [
        {"conditions": [{"column": "Lokasyon", "op": "empty"}], "value": "Lokasyonsuz"},
        {"conditions": [{"column": "Miktar", "op": "ge", "value": "7"}], "value": "Yüksek"},
        {"conditions": [{"column": "Miktar", "op": "ge", "value": "9"}], "value": "Çok yüksek"},  # ölü kural
    ]}
    r = ops.get("rules").run([moves], p, "t")
    assert r.df["Durum"].tolist() == ["Yüksek", "Normal", "Normal", "Yüksek", "Lokasyonsuz"]
    assert any("Hiçbir satıra uygulanmayan kural: 3" in w for w in r.warnings)


def test_rules_with_formula_values(moves):
    p = {"name": "Prim", "default": "0", "rules": [
        {"conditions": [{"column": "Miktar", "op": "gt", "value": "5"}], "value": "[Miktar] * 2"}]}
    r = ops.get("rules").run([moves], p, "t")
    assert r.df["Prim"].tolist() == [20, 0, 0, 14, 0]
    assert pd.api.types.is_numeric_dtype(r.df["Prim"])


# ------------------------------------------------------------- referans tablolar
def test_reference_roundtrip_and_update(lib, locs):
    meta = lib.save_reference("Lokasyonlar", locs, note="WMS ana veri, 2026-11")
    df = lib.reference_df(meta["id"])
    assert df.equals(locs) or df.astype(str).equals(locs.astype(str))
    assert pd.api.types.is_integer_dtype(df["Kapasite"])
    with pytest.raises(ShiftFlowError):
        lib.save_reference("Lokasyonlar", locs)
    lib.save_reference("Lokasyonlar", locs.head(2), rid=meta["id"])
    assert lib.reference_meta(meta["id"])["rows"] == 2


def test_reference_source_used_automatically(lib, moves, locs, tmp_path):
    meta = lib.save_reference("Lokasyonlar", locs)
    s = Session()
    s.library = lib
    s.add_source("Hareketler", moves, path=str(tmp_path / "x.xlsx"))
    s.add_source("Lokasyonlar", lib.reference_df(meta["id"]), kind="reference", reference_id=meta["id"])
    s.add_step("Hareketler", "lookup", LK)
    p = tmp_path / "akis.json"
    s.save_workflow(str(p))
    assert "Kuru" not in p.read_text(encoding="utf-8")  # referans verisi iş akışına yazılmaz

    s2 = Session()
    s2.library = lib
    s2.load_workflow(str(p))
    s2.bind_source("Hareketler", moves)
    assert s2.run_all() == {}  # referans tablo kütüphaneden kendiliğinden geldi
    # Referans güncellenince bir sonraki çalıştırma yeni içeriği kullanır
    lib.save_reference("Lokasyonlar", locs.assign(Bölge="Yeni"), rid=meta["id"])
    b = ReportBuilder(s2, lib, None)
    s2.workflow.run_settings = {"output_dir": str(tmp_path / "o")}
    moves.to_excel(tmp_path / "x.xlsx", index=False)
    plans = b.plan()
    ref = [x for x in plans if x.mode == "reference"][0]
    assert ref.status == "ok" and "Referans tablo" in ref.messages[0]
    assert b.build(plans).ok
    assert s2.result("Hareketler")["Bölge"].iloc[0] == "Yeni"


def test_missing_reference_blocks(lib, moves, locs):
    s = Session()
    s.library = lib
    s.add_source("Lokasyonlar", locs, kind="reference", reference_id="t_yok")
    plans = ReportBuilder(s, lib, None).plan()
    assert plans[0].status == "error" and plans[0].blocking
