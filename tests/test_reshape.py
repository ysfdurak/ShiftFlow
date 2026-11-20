"""Aşağı doldur, boşları doldur, sütunlara böl, sütunları satırlara çevir."""

import pandas as pd
import pytest

from shiftflow.engine import operations as O
from shiftflow.engine.errors import ShiftFlowError


def run(op, df, p):
    return O.REGISTRY[op].run([df], p, "t")


def test_fill_down_and_up():
    df = pd.DataFrame({"Bölge": ["Ege", None, "  ", "Marmara", None], "N": [1, 2, 3, 4, 5]})
    assert run("fill_down", df, {"columns": ["Bölge"]}).df["Bölge"].tolist() == \
        ["Ege", "Ege", "Ege", "Marmara", "Marmara"]
    assert run("fill_down", df, {"columns": ["Bölge"], "direction": "up"}).df["Bölge"].tolist()[:3] == \
        ["Ege", "Marmara", "Marmara"]


def test_fill_empty_keeps_types():
    df = pd.DataFrame({"Adet": [1, None, 3], "Ad": ["a", None, ""]})
    r = run("fill_empty", df, {"columns": ["Adet", "Ad"], "value": "0"}).df
    assert r["Adet"].tolist() == [1, 0, 3] and str(r["Adet"].dtype) == "int64"
    assert r["Ad"].tolist() == ["a", "0", "0"]
    with pytest.raises(ShiftFlowError):
        run("fill_empty", df, {"columns": ["Adet"], "value": "yok"})


def test_split_delimiter_keeps_leading_zero_and_position():
    df = pd.DataFrame({"Lok": ["A-01-03", "B-12-7", None, "C-1"], "X": [1, 2, 3, 4]})
    r = run("split", df, {"column": "Lok", "delimiter": "-", "names": ["Bölge", "Koridor", "Raf"]})
    assert list(r.df.columns) == ["Lok", "Bölge", "Koridor", "Raf", "X"]
    assert r.df["Koridor"].tolist() == ["01", "12", None, "1"]
    assert r.warnings  # 'C-1' iki parçalı
    r2 = run("split", df, {"column": "Lok", "delimiter": "-", "keep": False, "max_parts": 2})
    assert list(r2.df.columns) == ["Lok 1", "Lok 2", "X"] and r2.df["Lok 2"][0] == "01-03"


def test_split_positions_and_errors():
    df = pd.DataFrame({"Kod": ["TR34ABC", "DE1"]})
    r = run("split", df, {"column": "Kod", "mode": "positions", "positions": "2,2,3", "names": ["Ülke", "İl", "Ek"]})
    assert r.df["Ülke"].tolist() == ["TR", "DE"] and r.df["İl"].tolist() == [34, 1]
    assert r.df["Ek"].tolist()[1] is None
    with pytest.raises(ShiftFlowError):
        run("split", df, {"column": "Kod", "mode": "positions", "positions": "a"})
    with pytest.raises(ShiftFlowError):
        run("split", df, {"column": "Kod", "delimiter": "4", "names": ["Kod"], "keep": True})


def test_unpivot():
    df = pd.DataFrame({"Personel": ["P1", "P2"], "Gece": [5, None], "Gündüz": [3, 4]})
    r = run("unpivot", df, {"columns": ["Gece", "Gündüz"], "name_column": "Vardiya", "value_column": "Adet"})
    assert list(r.df.columns) == ["Personel", "Vardiya", "Adet"] and len(r.df) == 3
    with pytest.raises(ShiftFlowError):
        run("unpivot", df, {"columns": ["Gece"], "name_column": "Personel"})


@pytest.mark.parametrize("key", ["fill_down", "fill_empty", "split", "unpivot"])
def test_dialogs_build(qtbot, key):
    pytest.importorskip("PySide6")
    from shiftflow.ui import dialogs as dlg
    df = pd.DataFrame({"Lok": ["A-01", "B-02"], "Gece": [1, 2], "Gündüz": [3, None]})
    d = dlg.STEP_DIALOGS[key](df, preset="Gece" if key == "unpivot" else "Lok")
    qtbot.addWidget(d)
    d.refresh()
    assert O.REGISTRY[key].run([df], d.params(), "t").df is not None
