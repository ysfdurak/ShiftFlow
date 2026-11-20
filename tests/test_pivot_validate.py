"""Pivot/grup: tarih gruplama, yüzde gösterimi, sıralama ve ilk N; Doğrula adımı."""

import os

import pandas as pd
import pytest

from shiftflow.engine import operations as O
from shiftflow.engine.errors import ShiftFlowError
from shiftflow.engine.session import Session

DF = pd.DataFrame({"Zaman": pd.to_datetime(["2026-11-10 08:15", "2026-11-10 08:45", "2026-11-10 09:10",
                                            "2026-11-11 08:30", "2026-11-17 10:00"]),
                   "Ekip": ["A", "B", "A", "A", "B"], "Adet": [10, 20, 30, 40, 50]})
SUM = [{"column": "Adet", "func": "sum"}]


def piv(**p):
    return O.REGISTRY["pivot"].run([DF], dict({"values": SUM}, **p), "t").df


def test_date_groups():
    assert piv(rows=["Zaman"], date_group="hour")["Zaman"].tolist() == ["08:00", "09:00", "10:00", "Genel Toplam"]
    assert piv(rows=["Zaman"], date_group="week")["Zaman"].tolist()[:2] == ["2026-H46", "2026-H47"]
    assert piv(rows=["Zaman"], date_group="month")["Adet (Toplam)"].tolist() == [150, 150]
    assert list(piv(rows=["Ekip"], columns=["Zaman"], date_group="day").columns)[1] == "10.11.2026"
    assert piv(rows=["Zaman"], date_group="weekday")["Zaman"].tolist()[:2] == ["2 Sal", "3 Çar"]


def test_show_as_percent():
    t = piv(rows=["Ekip"], columns=["Zaman"], date_group="day", show_as="pct_total")
    assert t["Genel Toplam"].tolist() == [53.3, 46.7, 100.0]
    r = piv(rows=["Ekip"], columns=["Zaman"], date_group="weekday", show_as="pct_row")
    assert r["Genel Toplam"].tolist() == [100.0, 100.0, 100.0]


def test_top_n_and_sort():
    t = piv(rows=["Zaman"], columns=["Ekip"], date_group="hour", top_n=2)
    assert t["Zaman"].tolist() == ["08:00", "10:00", "Genel Toplam"]
    assert t["Genel Toplam"].tolist() == [70, 50, 120]  # toplam gösterilen satırlardan
    g = O.REGISTRY["group"].run([DF], {"by": ["Ekip"], "values": SUM, "sort_by_value": True}, "t").df
    assert g["Ekip"].tolist() == ["A", "B"] and g["Adet (Toplam)"].tolist() == [80, 70]
    g2 = O.REGISTRY["group"].run([DF], {"by": ["Zaman"], "values": SUM, "date_group": "day", "sort_by_value": True,
                                        "top_n": 1}, "t").df
    assert len(g2) == 1 and g2["Adet (Toplam)"].tolist() == [60]


VD = pd.DataFrame({"K": ["a", "b", "b", None], "T": [1, 5, 200, 3]})


@pytest.mark.parametrize("check,ok", [
    ({"check": "not_empty", "column": "K"}, False), ({"check": "unique", "column": "T"}, True),
    ({"check": "unique", "column": "K"}, False), ({"check": "min_rows", "value": "4"}, True),
    ({"check": "min_rows", "value": "5"}, False), ({"check": "range", "column": "T", "min": "0", "max": "250"}, True),
    ({"check": "formula", "formula": "[T] < 100"}, False),
])
def test_checks(check, ok):
    r = O.REGISTRY["validate"].run([VD], {"checks": [check]}, "t")
    assert (not r.warnings) is ok
    assert r.df is VD  # veri değişmez


def test_stop_blocks_output_but_not_editing(tmp_path):
    s = Session()
    s.add_source("T", VD)
    s.set_parameters({"Üst": 100})
    s.add_step("T", "validate", {"checks": [{"check": "range", "column": "T", "max": "{Üst}", "on_fail": "stop"}]})
    assert any("durdurur" in w for w in s.step_statuses("T")[1].warnings)  # düzenlerken uyarı
    with pytest.raises(ShiftFlowError, match="durduruldu"):
        s.export(str(tmp_path / "o.xlsx"))
    assert not os.path.exists(tmp_path / "o.xlsx") and not s.strict_validation
    s.set_parameters({"Üst": 1000})
    s.export(str(tmp_path / "o.xlsx"))
    assert os.path.exists(tmp_path / "o.xlsx")


def test_validate_formula_with_lookup_refs():
    s = Session()
    s.add_source("T", VD)
    s.add_source("H", pd.DataFrame({"K": ["a", "b"], "Max": [10, 10]}))
    s.add_step("T", "validate", {"checks": [{"check": "formula",
                                             "formula": 'EĞERHATA(DÜŞEYARA([K]; "H"; 2; 0); 999) >= [T]'}]})
    with pytest.raises(ShiftFlowError):
        s.delete_dataset("H")  # doğrulama formülü kullandığı sürece silinemez
    w = s.step_statuses("T")[1].warnings
    assert len(w) == 1 and "satır 3" in w[0]


# ---------------------------------------------------------------- arayüz
def test_dialogs(qtbot):
    pytest.importorskip("PySide6")
    from shiftflow.ui import dialogs as dlg
    d = dlg.ValidateDialog(VD, params={"checks": [{"check": "range", "column": "T", "min": "0", "max": "9",
                                                   "on_fail": "stop"}]})
    qtbot.addWidget(d)
    assert d.params() == {"checks": [{"check": "range", "on_fail": "stop", "column": "T", "min": "0", "max": "9"}]}
    p = dlg.PivotDialog(DF, params={"rows": ["Zaman"], "columns": [], "values": SUM, "date_group": "hour",
                                    "top_n": 2}, name="P")
    qtbot.addWidget(p)
    assert p.params()["date_group"] == "hour" and p.params()["top_n"] == 2
    # sürükle-bırak benzetimi: sütun alanına bırakılan alan satırdan çıkar
    p.cols.list.addItem("Zaman")
    qtbot.wait(10)
    assert p.rows.items() == [] and p.cols.items() == ["Zaman"]
