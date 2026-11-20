"""Formülde tablo fonksiyonları ve Excel formülü çevirici."""

import pandas as pd
import pytest

from shiftflow.engine import Session
from shiftflow.engine import excel_formula as xf
from shiftflow.engine.errors import MissingColumnError, ShiftFlowError
from shiftflow.engine.expression import evaluate, referenced_tables


@pytest.fixture
def t():
    return pd.DataFrame({"Personel No": ["P1", "P2", "P3", "P1"], "Ekip": ["X", "Y", "X", "Y"],
                         "Toplanan": [10, 20, 30, 40], "Bölge": ["Ege", "Ege", "Marmara", None]})


@pytest.fixture
def per():
    return pd.DataFrame({"Personel No": ["p1 ", "P2", "P2"], "Ad": ["Ali", "Ayşe", "Eski"], "Ekip Lideri": ["Gül", "Okan", "x"]})


def ev(f, df, tables=None):
    notes = []
    v, _ = evaluate(f, df, "t", tables, notes)
    return [None if (isinstance(x, float) and pd.isna(x)) else x for x in v.tolist()], notes


def test_vlookup_by_index_and_name(t, per):
    v, notes = ev('DÜŞEYARA([Personel No]; "Personel"; 3; 0)', t, {"Personel": per})
    assert v == ["Gül", "Okan", None, "Gül"]
    assert any("tekrar" in n for n in notes) and any("karşılığı" in n for n in notes)
    v, _ = ev('VLOOKUP([Personel No]; "Personel"; "Ad"; FALSE)', t, {"Personel": per})
    assert v[1] == "Ayşe"  # ilk bulunan
    with pytest.raises(ShiftFlowError):
        ev('DÜŞEYARA([Personel No]; "Personel"; 3; 1)', t, {"Personel": per})
    with pytest.raises(ShiftFlowError):
        ev('DÜŞEYARA([Personel No]; "Personel"; 9; 0)', t, {"Personel": per})
    with pytest.raises(ShiftFlowError):
        ev('DÜŞEYARA([Personel No]; "Yok"; 2; 0)', t, {"Personel": per})


def test_xlookup_with_default_and_nested(t, per):
    f = ('EĞER(ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ad"; "") = ""; "Tanımsız"; '
         'ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ad") & " / " & [Ekip]) & '
         'EĞER([Toplanan] > ORTALAMAEĞER("BU"; "Ekip"; [Ekip]; "Toplanan"); " ▲"; "")')
    v, notes = ev(f, t, {"Personel": per})
    assert v == ["Ali / X", "Ayşe / Y", "Tanımsız ▲", "Ali / Y ▲"]
    with pytest.raises(MissingColumnError):
        ev('ÇAPRAZARA([Personel No]; "Personel"; "Kod"; "Ad")', t, {"Personel": per})


def test_countif_sumif_families(t):
    assert ev('EĞERSAY("BU"; "Personel No"; [Personel No])', t)[0] == [2, 1, 1, 2]
    assert ev('EĞERSAY("BU"; "Bölge"; "e*")', t)[0] == [2, 2, 2, 2]
    assert ev('EĞERSAY("BU"; "Toplanan"; ">15")', t)[0] == [3, 3, 3, 3]
    assert ev('ÇOKEĞERSAY("BU"; "Ekip"; [Ekip]; "Toplanan"; ">15")', t)[0] == [1, 2, 1, 2]
    assert ev('ETOPLA("BU"; "Ekip"; [Ekip]; "Toplanan")', t)[0] == [40, 60, 40, 60]
    assert ev('ÇOKETOPLA("BU"; "Toplanan"; "Ekip"; "X"; "Bölge"; "<>Marmara")', t)[0] == [10] * 4
    assert ev('ORTALAMAEĞER("BU"; "Ekip"; [Ekip]; "Toplanan")', t)[0] == [20, 30, 20, 30]
    assert ev('[Toplanan] / TABLOTOPLA("BU"; "Toplanan")', t)[0] == [0.1, 0.2, 0.3, 0.4]
    assert ev('TABLOMAK("BU"; "Toplanan") - [Toplanan]', t)[0] == [30, 20, 10, 0]
    with pytest.raises(ShiftFlowError):
        ev('ÇOKEĞERSAY("BU"; "Ekip")', t)


def test_ifs_and_text(t):
    assert ev('ÇOKEĞER([Toplanan] > 25; "Y"; [Toplanan] > 15; "O"; DOĞRU; "D")', t)[0] == ["D", "O", "Y", "Y"]
    assert ev('METNEÇEVİR([Toplanan] / 100; "0,0%")', t)[0][0] == "10,0%"
    assert ev('METNEÇEVİR([Toplanan] * 100; "#.##0")', t)[0][3] == "4.000"


def test_referenced_tables():
    f = ('EĞER(DÜŞEYARA([A]; "Personel"; 2; 0) = ""; ETOPLA("Stok"; "Kod"; [Kod]; "Adet"); '
         'EĞERSAY("BU"; "A"; [A]) + ÇAPRAZARA([A]; "Personel"; "A"; "B"))')
    assert referenced_tables(f) == ["Personel", "Stok"]
    assert referenced_tables("[A] * 2") == []


def test_formula_tables_are_dependencies(t, per):
    s = Session()
    s.add_source("T", t)
    s.add_source("Personel", per)
    s.add_step("T", "calc", {"name": "Lider", "formula": 'DÜŞEYARA([Personel No]; "Personel"; "Ekip Lideri"; 0)'})
    assert s.result("T")["Lider"].tolist()[:2] == ["Gül", "Okan"]
    s.add_step("Personel", "replace", {"column": "Ekip Lideri", "find": "Gül", "replace": "GÜL", "whole_cell": True})
    assert s.result("T")["Lider"].iloc[0] == "GÜL"  # arama tablosundaki değişiklik yansır
    with pytest.raises(ShiftFlowError):
        s.delete_dataset("Personel")
    s.rename_dataset("Personel", "İK")  # formüldeki tablo adı da güncellenir
    assert '"İK"' in s.workflow.dataset("T").steps[0].params["formula"]
    assert s.result("T")["Lider"].iloc[0] == "GÜL"


def test_formula_table_cycle_rejected(t):
    s = Session()
    s.add_source("T", t)
    s.add_derived("Özet", "group", ["T"], {"by": ["Ekip"], "values": [{"column": "Toplanan", "func": "sum"}]})
    with pytest.raises(ShiftFlowError):
        s.add_step("T", "calc", {"name": "x", "formula": 'DÜŞEYARA([Ekip]; "Özet"; 2; 0)'})


def test_conditional_and_rules_can_use_lookups(t, per):
    s = Session()
    s.add_source("T", t)
    s.add_source("Personel", per)
    s.add_step("T", "rules", {"name": "Sorumlu", "default": 'DÜŞEYARA([Personel No]; "Personel"; 2; 0)', "rules": [
        {"conditions": [{"column": "Toplanan", "op": "gt", "value": "35"}], "value": '"Kontrol: " & [Ekip]'}]})
    assert s.result("T")["Sorumlu"].tolist() == ["Ali", "Ayşe", None, "Kontrol: Y"] or \
        s.result("T")["Sorumlu"].iloc[3] == "Kontrol: Y"


# ------------------------------------------------------------- çevirici
CUR = xf.letter_map(["Tarih", "Personel No", "Bölge", "Toplanan", "Hedef", "Süre"])
SHEETS = {"Personel": ("Personel", xf.letter_map(["Personel No", "Ad Soyad", "Ekip Lideri"])),
          "Lokasyon Listesi": ("Lokasyonlar", xf.letter_map(["Kod", "Bölge Adı"]))}


@pytest.mark.parametrize("excel,expected", [
    ('=EĞER(DÜŞEYARA(B2;Personel!A:C;3;0)="";"Yok";DÜŞEYARA(B2;Personel!$A:$C;2;YANLIŞ)&" - "&C2)',
     'EĞER(ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ekip Lideri") = ""; "Yok"; '
     'ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ad Soyad") & " - " & [Bölge])'),
    ('=IF(D2>E2,"Hedefte",CONCATENATE(B2,"-",ROUND(D2/E2*100,1),"%"))',
     'EĞER([Toplanan] > [Hedef]; "Hedefte"; BİRLEŞTİR([Personel No]; "-"; YUVARLA([Toplanan] / [Hedef] * 100; 1); "%"))'),
    ('=EĞERHATA(İNDİS(Personel!C:C;KAÇINCI(B2;Personel!A:A;0));"Tanımsız")',
     'EĞERHATA(ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ekip Lideri"); "Tanımsız")'),
    ("=EĞERSAY(B:B;B2)", 'EĞERSAY("BU"; "Personel No"; [Personel No])'),
    ("=ETOPLA(B:B;B2;D:D)/TOPLA(D:D)", 'ETOPLA("BU"; "Personel No"; [Personel No]; "Toplanan") / TABLOTOPLA("BU"; "Toplanan")'),
    ('=ÇOKETOPLA($D$2:$D$5000;$C$2:$C$5000;C2;$F$2:$F$5000;">40")',
     'ÇOKETOPLA("BU"; "Toplanan"; "Bölge"; [Bölge]; "Süre"; ">40")'),
    ("=_xlfn.XLOOKUP(B2,'Lokasyon Listesi'!A:A,'Lokasyon Listesi'!B:B,\"?\")",
     'ÇAPRAZARA([Personel No]; "Lokasyonlar"; "Kod"; "Bölge Adı"; "?")'),
    ("=TOPLA(D2:F2)", "TOPLA([Toplanan]; [Hedef]; [Süre])"),
    ("=D2*1,5+10%", "[Toplanan] * 1,5 + (10 / 100)"),
    ("=SUM(D2:E2)*1.5", "TOPLA([Toplanan]; [Hedef]) * 1,5"),
])
def test_translate(excel, expected):
    tr = xf.translate(excel, CUR, SHEETS)
    assert tr.formula == expected, tr.warnings
    assert tr.warnings == []


def test_translate_warnings():
    tr = xf.translate("=TOPLA(D2:F2)*$H$1", CUR, SHEETS)
    assert "[?$H$1]" in tr.formula and "sabit hücre" in tr.warnings[0]
    tr = xf.translate("=D2-D1", CUR, SHEETS)  # önceki satıra başvuru
    assert tr.current_row == 2 and any("D1" in w for w in tr.warnings)
    tr = xf.translate('=DOLAYLI("A1")', CUR, SHEETS)
    assert any("karşılığı yok" in w for w in tr.warnings)
    tr = xf.translate("=DÜŞEYARA(B2;Bilinmeyen!A:B;2;0)", CUR, SHEETS)
    assert any("eşlenmedi" in w for w in tr.warnings)
    with pytest.raises(ShiftFlowError):
        xf.translate("=EĞER(A2>1;", CUR, SHEETS)


def test_translate_start_letter_and_scan():
    cmap = xf.letter_map(["Kod", "Adet"], "C")  # tablo C sütunundan başlıyor
    assert xf.translate("=D7*2", cmap).formula == "[Adet] * 2"
    info = xf.scan("=EĞER(Personel!B5>0;C5;'Stok Listesi'!A:A)")
    assert info["sheets"] == ["Personel", "Stok Listesi"] and info["current_row"] == 5


def test_translated_formula_runs_end_to_end():
    t = pd.DataFrame({"Tarih": ["01.11.2026"] * 3, "Personel No": ["P1", "P2", "P9"], "Bölge": ["Ege", "Ege", "X"],
                      "Toplanan": [10, 30, 5], "Hedef": [20, 20, 0], "Süre": [1, 2, 3]})
    per = pd.DataFrame({"Personel No": ["P1", "P2"], "Ad Soyad": ["Ali", "Ayşe"], "Ekip Lideri": ["Gül", "Okan"]})
    excel = '=EĞER(EĞERHATA(DÜŞEYARA(B2;Personel!A:C;3;0);"")="";"Tanımsız";DÜŞEYARA(B2;Personel!A:C;2;0)&" ("&YUVARLA(EĞERHATA(D2/E2;0)*100;0)&"%)")'
    tr = xf.translate(excel, CUR, SHEETS)
    s = Session()
    s.add_source("T", t)
    s.add_source("Personel", per)
    s.add_step("T", "calc", {"name": "Etiket", "formula": tr.formula})
    assert s.result("T")["Etiket"].tolist() == ["Ali (50%)", "Ayşe (150%)", "Tanımsız"]
