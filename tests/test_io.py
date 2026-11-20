import pandas as pd
import pytest

from shiftflow.engine import io as sio
from shiftflow.engine.errors import DataImportError


def test_excel_sheets_and_header(make_xlsx, picking, staff):
    path = make_xlsx("r.xlsx", {"Toplama": picking, "Personel": staff})
    assert sio.list_sheets(path) == ["Toplama", "Personel"]
    df = sio.read_source(path, "Personel")
    assert list(df.columns) == list(staff.columns)
    assert len(df) == 4
    raw = sio.read_source(path, "Personel", header=False)
    assert raw.columns[0] == "Sütun 1" and len(raw) == 5


def test_excel_types_preserved(make_xlsx, picking):
    df = sio.read_source(make_xlsx("r.xlsx", {"S": picking}))
    assert pd.api.types.is_numeric_dtype(df["Toplanan"])
    assert pd.api.types.is_datetime64_any_dtype(df["Tarih"])


def test_missing_sheet(make_xlsx, picking):
    with pytest.raises(DataImportError):
        sio.read_source(make_xlsx("r.xlsx", {"S": picking}), "Yok")


def test_csv_semicolon_turkish(tmp_path):
    p = tmp_path / "r.csv"
    p.write_bytes("Ürün;Miktar;Tutar\nÇay;1.200;1.234,50\nŞeker;3;10,5\n".encode("cp1254"))
    df = sio.read_source(str(p))
    assert df["Ürün"].tolist() == ["Çay", "Şeker"]
    assert df["Miktar"].tolist() == [1200, 3]
    assert df["Tutar"].tolist() == [1234.5, 10.5]


def test_clipboard_paste():
    text = "Kod\tAd\tAdet\n001\tKalem\t5\n002\tDefter\t\n"
    df = sio.parse_text_table(text)
    assert df["Kod"].tolist() == ["001", "002"]
    assert df["Adet"].iloc[0] == 5 and pd.isna(df["Adet"].iloc[1])


def test_duplicate_and_empty_headers():
    df = sio.parse_text_table("Ad\tAd\t\n1\t2\t3\n")
    assert list(df.columns) == ["Ad", "Ad_2", "Sütun 3"]


def test_empty_inputs(tmp_path):
    with pytest.raises(DataImportError):
        sio.parse_text_table("   ")
    with pytest.raises(DataImportError):
        sio.read_source(str(tmp_path / "yok.xlsx"))
    p = tmp_path / "x.pdf"
    p.write_text("x")
    with pytest.raises(DataImportError):
        sio.read_source(str(p))


def test_safe_sheet_names():
    used = set()
    assert sio.safe_sheet_name("a/b", used) == "a_b"
    assert sio.safe_sheet_name("A_B", used) == "A_B (2)"
    assert len(sio.safe_sheet_name("x" * 40, used)) == 31


def test_export_with_empty_cells_and_text_dtype(tmp_path):
    df = pd.DataFrame({"A": pd.Series(["x", None, None], dtype="string"), "B": [None, None, None], "C": [1.5, None, 2]})
    sio.write_excel(str(tmp_path / "o.xlsx"), [("S", df)])
    back = pd.read_excel(tmp_path / "o.xlsx")
    assert len(back) == 3


def test_text_dates_with_leading_zero_become_dates():
    df = sio.parse_text_table("Tarih\tKod\n01.11.2026\t00123\n02.11.2026\t00456\n")
    assert pd.api.types.is_datetime64_any_dtype(df["Tarih"])
    assert df["Kod"].tolist() == ["00123", "00456"]
