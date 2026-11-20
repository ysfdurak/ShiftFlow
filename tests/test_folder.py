"""Klasörden çoklu dosya kaynağı."""

import os
import time

import pandas as pd
import pytest

from shiftflow.engine import io as sio
from shiftflow.engine.session import Session


def _write(folder, name, df):
    p = os.path.join(folder, name)
    df.to_excel(p, index=False)
    return p


def test_read_folder_union_and_file_column(tmp_path):
    d = str(tmp_path)
    _write(d, "toplama_01.xlsx", pd.DataFrame({"Kod": ["001"], "Adet": [1]}))
    time.sleep(0.01)
    _write(d, "toplama_02.xlsx", pd.DataFrame({"Kod": ["002"], "Adet": [2], "Not": ["x"]}))
    _write(d, "baska.xlsx", pd.DataFrame({"Z": [1]}))
    open(os.path.join(d, "~$toplama_03.xlsx"), "w").close()  # Excel kilidi atlanır
    df = sio.read_source(os.path.join(d, "toplama_*.xlsx"))
    assert list(df.columns) == ["Kod", "Adet", "Not", sio.FILE_COLUMN]
    assert df[sio.FILE_COLUMN].tolist() == ["toplama_01.xlsx", "toplama_02.xlsx"]
    assert df["Kod"].tolist() == ["001", "002"]
    assert any("fazla sütun: Not" in n for n in df.attrs["notes"])
    from shiftflow.engine.errors import DataImportError
    with pytest.raises(DataImportError):
        sio.read_source(os.path.join(d, "yok_*.xlsx"))


def test_folder_source_picks_up_new_files(tmp_path):
    d = str(tmp_path)
    _write(d, "r1.xlsx", pd.DataFrame({"Kod": ["a"], "Adet": [1]}))
    pat = os.path.join(d, "r*.xlsx")
    s = Session()
    s.add_source("R", sio.read_source(pat), kind="folder", path=pat)
    p = tmp_path / "a.json"
    s.save_workflow(str(p))
    _write(d, "r2.xlsx", pd.DataFrame({"Kod": ["b"], "Adet": [2]}))
    s2 = Session()
    s2.load_workflow(str(p))
    s2.bind_source("R", s2.load_source_file("R"))
    assert s2.result("R")["Kod"].tolist() == ["a", "b"]


def test_builder_uses_folder(tmp_path):
    from shiftflow.engine.autorun import ReportBuilder, SourcePlan
    d = str(tmp_path)
    _write(d, "r1.xlsx", pd.DataFrame({"Kod": ["a"], "Adet": [1]}))
    _write(d, "r2.xlsx", pd.DataFrame({"Kod": ["b"], "Adet": [2]}))
    pat = os.path.join(d, "r*.xlsx")
    s = Session()
    s.add_source("R", sio.read_source(pat), kind="folder", path=pat)
    b = ReportBuilder(s, None, None)
    sp = SourcePlan(source="R", mode="file", path=pat)
    b.use_file(sp, pat)
    assert sp.df is not None and len(sp.df) == 2 and any("2 dosya" in m for m in sp.messages)
