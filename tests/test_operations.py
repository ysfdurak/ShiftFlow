import pandas as pd
import pytest

from shiftflow.engine import operations as ops
from shiftflow.engine.errors import (
    JoinConfirmationRequired,
    MissingColumnError,
    ShiftFlowError,
    TypeMismatchError,
)
from shiftflow.engine.values import _parse_number_text, infer_types, tr_upper


def run(key, dfs, params):
    if not isinstance(dfs, list):
        dfs = [dfs]
    return ops.get(key).run(dfs, params, "test")


# ------------------------------------------------------------- değerler
@pytest.mark.parametrize("text,val", [
    ("1.234,56", 1234.56), ("1234.56", 1234.56), ("1,5", 1.5), ("12.345", 12345),
    ("1.234.567", 1234567), ("%12", 0.12), ("₺ 1.000,00", 1000.0), ("-3", -3), ("abc", None), ("", None),
])
def test_parse_number(text, val):
    assert _parse_number_text(text) == val


def test_infer_types_keeps_leading_zero_codes():
    df = pd.DataFrame({"Kod": ["001", "002"], "Adet": ["1.000", "2"], "Ad": ["x", "y"]})
    out = infer_types(df)
    assert out["Kod"].tolist() == ["001", "002"]
    assert out["Adet"].tolist() == [1000, 2]
    assert not pd.api.types.is_numeric_dtype(out["Ad"])


def test_turkish_upper():
    assert tr_upper("istanbul ılık") == "İSTANBUL ILIK"


# ------------------------------------------------------------- filtre
def test_filter_and_or(picking):
    r = run("filter", picking, {"conditions": [
        {"column": "Bölge", "op": "eq", "value": "marmara"},
        {"column": "Toplanan", "op": "gt", "value": "50"}], "mode": "and"})
    assert r.df["Personel No"].tolist() == ["P01"]
    r = run("filter", picking, {"conditions": [
        {"column": "Bölge", "op": "eq", "value": "Ege"},
        {"column": "Bölge", "op": "empty"}], "mode": "or"})
    assert len(r.df) == 3


def test_filter_does_not_modify_input(picking):
    before = picking.copy()
    run("filter", picking, {"conditions": [{"column": "Toplanan", "op": "gt", "value": "50"}]})
    pd.testing.assert_frame_equal(picking, before)


def test_filter_in_list_with_empty(picking):
    r = run("filter", picking, {"conditions": [{"column": "Bölge", "op": "in_list", "value": ["Ege", "(Boş)"]}]})
    assert len(r.df) == 3


def test_filter_text_numbers(picking):
    df = pd.DataFrame({"Miktar": ["1.200", "15", "abc"]})
    r = run("filter", df, {"conditions": [{"column": "Miktar", "op": "gt", "value": "100"}]})
    assert r.df["Miktar"].tolist() == ["1.200"]


def test_filter_type_mismatch():
    df = pd.DataFrame({"Ad": ["a", "b"]})
    with pytest.raises(TypeMismatchError):
        run("filter", df, {"conditions": [{"column": "Ad", "op": "gt", "value": "5"}]})


def test_filter_missing_column(picking):
    with pytest.raises(MissingColumnError) as e:
        run("filter", picking, {"conditions": [{"column": "Yok", "op": "eq", "value": "1"}]})
    assert "Yok" in e.value.message


def test_filter_date(picking):
    r = run("filter", picking, {"conditions": [{"column": "Tarih", "op": "ge", "value": "02.11.2026"}]})
    assert len(r.df) == 4


def test_filter_empty_result_warns(picking):
    r = run("filter", picking, {"conditions": [{"column": "Toplanan", "op": "gt", "value": "1000"}]})
    assert r.df.empty and r.warnings


# ------------------------------------------------------------- hesaplama
def test_calc_two_columns(picking):
    r = run("calc", picking, {"name": "Fark", "formula": "[Toplanan] - [Hedef]"})
    assert r.df["Fark"].tolist() == [20, -20, 0, -10, 5, 0]


def test_calc_division_by_zero(picking):
    r = run("calc", picking, {"name": "Oran", "formula": "[Toplanan] / [Hedef] * 100"})
    assert pd.isna(r.df["Oran"].iloc[2])
    assert r.df["Oran"].iloc[0] == 120
    assert any("sıfıra bölme" in w for w in r.warnings)


def test_calc_constant_comma_decimal(picking):
    r = run("calc", picking, {"name": "x", "formula": "[Hedef] * 1,5"})
    assert r.df["x"].iloc[0] == 150


def test_calc_concat(picking):
    r = run("calc", picking, {"name": "Anahtar", "formula": '[Personel No] & "-" & [Toplanan]'})
    assert r.df["Anahtar"].iloc[0] == "P01-120"


def test_calc_type_mismatch(picking):
    with pytest.raises(TypeMismatchError):
        run("calc", picking, {"name": "x", "formula": "[Bölge] * 2"})


def test_calc_missing_column(picking):
    with pytest.raises(MissingColumnError):
        run("calc", picking, {"name": "x", "formula": "[Yok] * 2"})


def test_calc_bad_formula(picking):
    with pytest.raises(ShiftFlowError):
        run("calc", picking, {"name": "x", "formula": "[Toplanan] * "})
    with pytest.raises(ShiftFlowError):
        run("calc", picking, {"name": "x", "formula": "__import__('os')"})


def test_calc_existing_name_rejected(picking):
    with pytest.raises(ShiftFlowError):
        run("calc", picking, {"name": "Hedef", "formula": "1"})


def test_conditional(picking):
    r = run("conditional", picking, {
        "name": "Durum", "conditions": [{"column": "Toplanan", "op": "ge", "value": "70"}],
        "then": "Yüksek", "else": '"Düşük"'})
    assert r.df["Durum"].tolist() == ["Yüksek", "Yüksek", "Düşük", "Düşük", "Düşük", "Yüksek"]


def test_conditional_formula_branch(picking):
    r = run("conditional", picking, {
        "name": "Prim", "conditions": [{"column": "Bölge", "op": "eq", "value": "Marmara"}],
        "then": "[Toplanan] * 2", "else": "0"})
    assert r.df["Prim"].tolist()[:3] == [240, 0, 0]


# ------------------------------------------------------------- diğer
def test_convert_and_dedupe():
    df = pd.DataFrame({"Tarih": ["01.11.2026", "x", None], "A": [1, 1, 2]})
    r = run("convert", df, {"column": "Tarih", "to": "date"})
    assert r.df["Tarih"].iloc[0] == pd.Timestamp("2026-11-01")
    assert r.warnings  # 'x' çevrilemedi
    with pytest.raises(TypeMismatchError):
        run("convert", df, {"column": "Tarih", "to": "date", "strict": True})
    r = run("dedupe", df, {"columns": ["A"]})
    assert len(r.df) == 2


def test_text_clean_and_replace():
    df = pd.DataFrame({"Ad": ["  ali   yılmaz ", "AYŞE"], "N": [1, 2]})
    r = run("text_clean", df, {"columns": ["Ad"], "case": "title"})
    assert r.df["Ad"].tolist() == ["Ali Yılmaz", "Ayşe"]
    r = run("replace", df, {"column": "Ad", "find": "AYŞE", "replace": "Ayşe", "whole_cell": True})
    assert r.df["Ad"].iloc[1] == "Ayşe"
    r = run("replace", df, {"column": "N", "find": "2", "replace": "5"})
    assert r.df["N"].tolist() == [1, 5]


def test_rename_conflict(picking):
    with pytest.raises(ShiftFlowError):
        run("rename", picking, {"mapping": {"Toplanan": "Hedef"}})


# ------------------------------------------------------------- birleştirme
JOIN = {"left_keys": ["Personel No"], "right_keys": ["Personel No"], "right_label": "Personel"}


def test_left_join_counts(picking, staff):
    r = run("join", [picking, staff], {**JOIN, "how": "left"})
    assert len(r.df) == len(picking)
    d = r.stats["join"]
    assert d["left_unmatched"] == 2  # P04, P05
    assert d["right_unmatched"] == 1  # P06
    assert "Ad Soyad" in r.df.columns


def test_inner_and_outer_join(picking, staff):
    assert len(run("join", [picking, staff], {**JOIN, "how": "inner"}).df) == 4
    out = run("join", [picking, staff], {**JOIN, "how": "outer", "add_match_column": True}).df
    assert len(out) == 7
    p06 = out[out["Personel No"] == "P06"]
    assert len(p06) == 1 and p06[ops.MATCH_COL].iloc[0] == "Yalnız sağda"


def test_join_key_type_normalization():
    a = pd.DataFrame({"Kod": [1, 2, 3], "x": [1, 2, 3]})
    b = pd.DataFrame({"Kod": ["1", " 2 ", "9"], "y": ["a", "b", "c"]})
    r = run("join", [a, b], {"left_keys": ["Kod"], "right_keys": ["Kod"], "how": "inner"})
    assert sorted(r.df["y"]) == ["a", "b"]


def test_join_empty_keys_do_not_match():
    a = pd.DataFrame({"K": ["A", None], "x": [1, 2]})
    b = pd.DataFrame({"K": ["A", None], "y": [1, 2]})
    r = run("join", [a, b], {"left_keys": ["K"], "right_keys": ["K"], "how": "inner"})
    assert len(r.df) == 1


def test_join_many_to_many_requires_confirmation():
    a = pd.DataFrame({"K": ["A", "A"], "x": [1, 2]})
    b = pd.DataFrame({"K": ["A", "A"], "y": [1, 2]})
    with pytest.raises(JoinConfirmationRequired) as e:
        run("join", [a, b], {"left_keys": ["K"], "right_keys": ["K"], "how": "left"})
    assert e.value.diagnostics["expected_rows"] == 4
    r = run("join", [a, b], {"left_keys": ["K"], "right_keys": ["K"], "how": "left", "allow_many_to_many": True})
    assert len(r.df) == 4


def test_join_one_to_many_warns(picking):
    right = pd.DataFrame({"Personel No": ["P02", "P02"], "Not": ["a", "b"]})
    r = run("join", [picking, right], {**JOIN, "how": "left"})
    assert len(r.df) == len(picking) + 1
    assert any("arttı" in w for w in r.warnings)


def test_join_no_match_warns():
    a = pd.DataFrame({"K": ["001"], "x": [1]})
    b = pd.DataFrame({"K": ["1"], "y": [1]})
    r = run("join", [a, b], {"left_keys": ["K"], "right_keys": ["K"], "how": "left"})
    assert any("Hiç eşleşme" in w for w in r.warnings)


def test_join_column_collision_and_multi_key():
    a = pd.DataFrame({"D": ["X", "X"], "L": [1, 2], "Adet": [5, 6]})
    b = pd.DataFrame({"Depo": ["X", "X"], "Lok": ["1", "2"], "Adet": [7, 8]})
    r = run("join", [a, b], {"left_keys": ["D", "L"], "right_keys": ["Depo", "Lok"], "how": "left", "right_label": "Stok"})
    assert r.df["Adet (Stok)"].tolist() == [7, 8]
    assert r.df["Adet"].tolist() == [5, 6]


def test_join_missing_key():
    a = pd.DataFrame({"K": [1]})
    with pytest.raises(MissingColumnError):
        run("join", [a, a], {"left_keys": ["Z"], "right_keys": ["K"]})


def test_append(picking, staff):
    r = run("append", [picking, staff], {"labels": ["Toplama", "Personel"], "source_column": "Kaynak"})
    assert len(r.df) == 10
    assert set(r.df["Kaynak"]) == {"Toplama", "Personel"}
    assert r.warnings


# ------------------------------------------------------------- gruplama / pivot
def test_group(picking):
    r = run("group", picking, {"by": ["Bölge"], "values": [
        {"column": "Toplanan", "func": "sum"}, {"column": "Personel No", "func": "count"},
        {"column": "Toplanan", "func": "mean"}]})
    df = r.df.set_index("Bölge")
    assert df.loc["Marmara", "Toplanan (Toplam)"] == 120
    assert df.loc["(Boş)", "Personel No (Adet)"] == 1
    assert r.warnings


def test_group_non_numeric_sum(picking):
    with pytest.raises(TypeMismatchError):
        run("group", picking, {"by": ["Bölge"], "values": [{"column": "Personel No", "func": "sum"}]})


def test_pivot_multi(picking):
    r = run("pivot", picking, {"rows": ["Bölge"], "columns": ["Tarih"], "values": [
        {"column": "Toplanan", "func": "sum"}, {"column": "Hedef", "func": "max"}], "totals": True})
    df = r.df
    assert df["Bölge"].iloc[-1] == ops.TOTAL_LABEL
    total_col = "Toplanan (Toplam) | " + ops.TOTAL_LABEL
    assert df[total_col].iloc[-1] == picking["Toplanan"].sum()


def test_pivot_rows_only_and_count_zero(picking):
    r = run("pivot", picking, {"rows": ["Bölge"], "values": [{"column": "Personel No", "func": "count"}]})
    assert r.df.iloc[-1, 1] == 6
    r = run("pivot", picking, {"rows": ["Bölge"], "columns": ["Personel No"],
                               "values": [{"column": "Toplanan", "func": "count"}]})
    assert (r.df.select_dtypes("number") >= 0).all().all()


def test_pivot_validation(picking):
    with pytest.raises(ShiftFlowError):
        run("pivot", picking, {"rows": [], "columns": [], "values": [{"column": "Toplanan", "func": "sum"}]})
    with pytest.raises(ShiftFlowError):
        run("pivot", picking, {"rows": ["Bölge"], "columns": ["Bölge"], "values": [{"column": "Toplanan", "func": "sum"}]})


def test_empty_dataframe_operations():
    df = pd.DataFrame({"A": pd.Series([], dtype=float), "B": pd.Series([], dtype=object)})
    assert run("filter", df, {"conditions": [{"column": "A", "op": "gt", "value": "1"}]}).df.empty
    assert run("calc", df, {"name": "C", "formula": "[A] * 2"}).df.empty
    assert run("group", df, {"by": ["B"], "values": [{"column": "A", "func": "sum"}]}).df.empty
