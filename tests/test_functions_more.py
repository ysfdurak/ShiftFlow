"""3.5'te eklenen formül fonksiyonları ve Excel çevirisi."""

import pandas as pd
import pytest

from shiftflow.engine import excel_formula as X
from shiftflow.engine import expression as E

DF = pd.DataFrame({"Lok": ["A-01-03", "B-12-7", "C"], "Ekip": ["X", "X", "Y"], "S": [10, 30, 20],
                   "T": pd.to_datetime(["2026-11-06", "2026-11-09", "2026-01-31"])})


def ev(f):
    return list(E.evaluate(f, DF, "t", tables={"BU": DF})[0])


@pytest.mark.parametrize("f,expected", [
    ('SOLDAN([Lok]; BUL("-"; [Lok]) - 1)', ["A", "B", None]),
    ('PARÇAAL([Lok]; BUL("-"; [Lok]) + 1; 2)', ["01", "12", None]),
    ('EĞERHATA(BUL("-"; [Lok]); 0)', [2.0, 2.0, 0.0]),
    ('MAKEĞER("BU"; "S"; "Ekip"; [Ekip])', [30.0, 30.0, 20.0]),
    ('MİNEĞER("BU"; "S"; "Ekip"; [Ekip]; "S"; ">10")', [30.0, 30.0, 20.0]),
    ('ÇOKEĞERORTALAMA("BU"; "S"; "Ekip"; "X")', [20.0, 20.0, 20.0]),
    ('METİNBİRLEŞTİR("/"; DOĞRU; [Ekip]; ""; [S])', ["X/10", "X/30", "Y/20"]),
    ('ÖZDEŞ([Ekip]; "x")', [False, False, False]),
    ('ESAYIYSA([S])', [True, True, True]),
    ('EMETİNSE([Lok])', [True, True, True]),
    ('SEÇ(2; "a"; "b"; "c")', ["b", "b", "b"]),
    ('ÇARPIM([S]; 2)', [20.0, 60.0, 40.0]),
    ('BAĞ_DEĞ_DOLU_SAY([S]; [Lok]; "")', [2.0, 2.0, 2.0]),
    ('DEĞİŞTİR([Lok]; 1; 1; "Z")', ["Z-01-03", "Z-12-7", "Z"]),
    ('YİNELE("*"; 3)', ["***"] * 3),
    ('TAMİŞGÜNÜ([T]; TARİH(2026; 11; 13))', [6.0, 5.0, 205.0]),
    ('ETARİHLİ(TARİH(2025; 1; 15); [T]; "M")', [21.0, 21.0, 12.0]),
])
def test_new_functions(f, expected):
    assert ev(f) == expected


def test_date_functions():
    assert ev("[T] + ZAMAN(8; 30; 0)")[0] == pd.Timestamp("2026-11-06 08:30")
    assert ev("SERİAY([T]; 1)")[2] == pd.Timestamp("2026-02-28")
    assert ev("SERİTARİH([T]; 1)")[0] == pd.Timestamp("2026-12-06")
    # Excel İŞGÜNÜ: cumartesiden 1 iş günü sonrası pazartesi
    assert ev("İŞGÜNÜ([T]; 1)") == [pd.Timestamp("2026-11-09"), pd.Timestamp("2026-11-10"),
                                    pd.Timestamp("2026-02-02")]
    assert ev('TARİHSAYISI("10.11.2026")')[0] == pd.Timestamp("2026-11-10")


def test_english_names_and_completion_list_has_no_duplicates():
    assert ev('LEFT([Lok]; FIND("-"; [Lok]) - 1)')[0] == "A"
    names = sorted(k for k in E.FUNCTIONS if k not in E._ALIASES)
    for en in ("IF", "AND", "ROUND", "FIND", "MAXIFS"):
        assert en not in names


@pytest.mark.parametrize("xl,sf", [
    ("=MAXIFS(C:C,B:B,B2)", 'MAKEĞER("BU"; "Süre"; "Ekip"; [Ekip])'),
    ('=LEFT(D2,FIND("-",D2)-1)', 'SOLDAN([Lok]; BUL("-"; [Lok]) - 1)'),
    ("=COUNTA(A2:C2)", "BAĞ_DEĞ_DOLU_SAY([Personel]; [Ekip]; [Süre])"),
    ("=EOMONTH(A2,0)", "SERİAY([Personel]; 0)"),
])
def test_translator_new_patterns(xl, sf):
    cols = X.letter_map(["Personel", "Ekip", "Süre", "Lok"], "A")
    t = X.translate(xl, cols, {}, None, 2)
    assert t.formula == sf and not t.warnings
