import hashlib
import json

import pandas as pd
import pytest

from shiftflow.engine import Session, Workflow
from shiftflow.engine import io as sio
from shiftflow.engine.errors import ExportError, ShiftFlowError, WorkflowError


def build(picking, staff):
    s = Session()
    s.add_source("Toplama", picking, path="toplama.xlsx")
    s.add_source("Personel", staff, path="personel.xlsx")
    s.add_step("Toplama", "calc", {"name": "Oran", "formula": "[Toplanan] / [Hedef] * 100"})
    s.add_step("Toplama", "filter", {"conditions": [{"column": "Toplanan", "op": "gt", "value": "0"}]})
    s.add_step("Personel", "filter", {"conditions": [{"column": "Vardiya", "op": "eq", "value": "Gece"}]})
    s.add_derived("Birleşik", "join", ["Toplama", "Personel"], {
        "how": "left", "left_keys": ["Personel No"], "right_keys": ["Personel No"], "right_label": "Personel"})
    s.add_derived("Özet", "pivot", ["Birleşik"], {
        "rows": ["Bölge"], "columns": [], "values": [{"column": "Toplanan", "func": "sum"}], "totals": True})
    return s


def test_independent_branches(picking, staff):
    s = build(picking, staff)
    assert len(s.result("Toplama")) == 5
    assert len(s.result("Personel")) == 2
    j = s.result("Birleşik")
    assert len(j) == 5
    assert j["Vardiya"].notna().sum() == 2  # yalnızca gece vardiyası eşleşir


def test_dependents_see_new_steps(picking, staff):
    s = build(picking, staff)
    before = s.result("Özet")
    s.add_step("Toplama", "filter", {"conditions": [{"column": "Bölge", "op": "eq", "value": "Marmara"}]})
    after = s.result("Özet")
    assert len(after) < len(before)


def test_source_data_untouched(picking, staff):
    copy = picking.copy()
    s = build(picking, staff)
    s.result("Özet")
    pd.testing.assert_frame_equal(picking, copy)


def test_intermediate_results(picking, staff):
    s = build(picking, staff)
    assert len(s.result("Toplama", upto=-1)) == 6
    assert "Oran" in s.result("Toplama", upto=0).columns
    st = s.step_statuses("Toplama")
    assert [x.rows_after for x in st] == [6, 6, 5]
    assert st[1].warnings  # sıfıra bölme


def test_failing_step_rejected_and_rolled_back(picking, staff):
    s = build(picking, staff)
    n = len(s.workflow.dataset("Toplama").steps)
    with pytest.raises(ShiftFlowError):
        s.add_step("Toplama", "calc", {"name": "x", "formula": "[Yok] * 2"})
    assert len(s.workflow.dataset("Toplama").steps) == n


def test_change_that_breaks_dependent_is_rejected(picking, staff):
    s = build(picking, staff)
    with pytest.raises(ShiftFlowError) as e:
        s.add_step("Toplama", "remove", {"columns": ["Bölge"]})
    assert "Özet" in e.value.message


def test_move_step_dependency_check(picking, staff):
    s = Session()
    s.add_source("T", picking)
    s.add_step("T", "calc", {"name": "Fark", "formula": "[Toplanan] - [Hedef]"})
    s.add_step("T", "filter", {"conditions": [{"column": "Fark", "op": "gt", "value": "0"}]})
    with pytest.raises(ShiftFlowError):
        s.move_step("T", 1, -1)  # filtre, Fark oluşmadan önce çalışamaz
    assert s.workflow.dataset("T").steps[0].op == "calc"
    s.add_step("T", "sort", {"keys": [{"column": "Toplanan", "ascending": False}]})
    assert s.move_step("T", 2, -1) == 1


def test_edit_and_delete_step(picking, staff):
    s = build(picking, staff)
    s.edit_step("Toplama", 1, {"conditions": [{"column": "Toplanan", "op": "gt", "value": "60"}]})
    assert len(s.result("Toplama")) == 3
    s.delete_step("Toplama", 1)
    assert len(s.result("Toplama")) == 6


def test_undo_redo(picking, staff):
    s = build(picking, staff)
    s.add_step("Toplama", "sort", {"keys": [{"column": "Toplanan"}]})
    assert len(s.workflow.dataset("Toplama").steps) == 3
    s.undo()
    assert len(s.workflow.dataset("Toplama").steps) == 2
    s.redo()
    assert len(s.workflow.dataset("Toplama").steps) == 3


def test_delete_dataset_blocked_by_dependents(picking, staff):
    s = build(picking, staff)
    with pytest.raises(ShiftFlowError):
        s.delete_dataset("Birleşik")
    s.delete_dataset("Özet")
    s.delete_dataset("Birleşik")
    assert "Birleşik" not in s.workflow.datasets


def test_rename_dataset_updates_references(picking, staff):
    s = build(picking, staff)
    s.rename_dataset("Birleşik", "Ana Tablo")
    assert s.workflow.dataset("Özet").origin.inputs == ["Ana Tablo"]
    assert len(s.result("Özet")) > 0


def test_cycle_detection():
    data = {
        "format": "shiftflow-workflow", "schema_version": 1, "sources": [],
        "datasets": [
            {"name": "A", "origin": {"type": "copy", "inputs": ["B"], "params": {}}, "steps": []},
            {"name": "B", "origin": {"type": "copy", "inputs": ["A"], "params": {}}, "steps": []},
        ],
    }
    with pytest.raises(WorkflowError) as e:
        Workflow.from_dict(data)
    assert "döngüsel" in e.value.message


def test_json_rejects_foreign_and_newer():
    with pytest.raises(WorkflowError):
        Workflow.from_json('{"a": 1}')
    with pytest.raises(WorkflowError):
        Workflow.from_json('{"format": "shiftflow-workflow", "schema_version": 99}')
    with pytest.raises(WorkflowError):
        Workflow.from_json("bozuk")


def test_json_contains_no_data(picking, staff, tmp_path):
    s = build(picking, staff)
    p = tmp_path / "akis.json"
    s.save_workflow(str(p))
    text = p.read_text(encoding="utf-8")
    assert "Ali Yılmaz" not in text  # veri değil, yalnız tanım saklanır
    assert json.loads(text)["schema_version"] == 3


def test_rerun_with_new_data(picking, staff, tmp_path, make_xlsx):
    s = build(picking, staff)
    p = tmp_path / "akis.json"
    s.save_workflow(str(p))
    old_rows = len(s.result("Birleşik"))

    s2 = Session()
    s2.load_workflow(str(p))
    assert set(s2.unbound_sources()) == {"Toplama", "Personel"}
    new_pick = pd.concat([picking, picking], ignore_index=True)
    s2.bind_source("Toplama", new_pick)
    s2.bind_source("Personel", staff)
    errors = s2.run_all()
    assert errors == {}
    assert len(s2.result("Birleşik")) == old_rows * 2


def test_rerun_with_renamed_column_and_mapping(picking, staff, tmp_path):
    s = build(picking, staff)
    p = tmp_path / "akis.json"
    s.save_workflow(str(p))
    s2 = Session()
    s2.load_workflow(str(p))
    changed = picking.rename(columns={"Toplanan": "Toplanan Adet"})
    check = s2.check_source("Toplama", changed)
    assert check["missing"] == ["Toplanan"]
    assert check["suggestions"]["Toplanan"] == "Toplanan Adet"
    s2.bind_source("Toplama", changed)
    s2.bind_source("Personel", staff)
    errors = s2.run_all()
    assert "Toplama" in errors and "Toplanan" in errors["Toplama"].message
    assert "Birleşik" in errors  # sonraki kümeler de çalışamaz
    s2.bind_source("Toplama", changed, column_map={"Toplanan Adet": "Toplanan"})
    assert s2.run_all() == {}
    # eşleme iş akışına kaydedilir; bir sonraki raporda tekrar sorulmaz
    assert s2.check_source("Toplama", changed)["missing"] == []


def test_type_change_detected(picking, staff):
    s = build(picking, staff)
    changed = picking.copy()
    changed["Toplanan"] = changed["Toplanan"].astype(str) + " adet"
    assert s.check_source("Toplama", changed)["type_changes"] == [("Toplanan", "number", "text")]


def test_export_multi_sheet_and_source_protection(picking, staff, tmp_path, make_xlsx):
    src = make_xlsx("kaynak.xlsx", {"Rapor": picking})
    digest = hashlib.md5(open(src, "rb").read()).hexdigest()
    s = Session()
    s.add_source("Toplama", sio.read_source(src), path=src)
    s.add_derived("Grup", "group", ["Toplama"], {"by": ["Bölge"], "values": [{"column": "Toplanan", "func": "sum"}]})
    with pytest.raises(ExportError):
        s.export(src)
    out = tmp_path / "cikti.xlsx"
    sheets = s.export(str(out), [("Toplama", "Ham Veri"), ("Grup", "Bölge/Özet")])
    assert sheets == ["Ham Veri", "Bölge_Özet"]
    x = pd.ExcelFile(out)
    assert x.sheet_names == sheets
    assert hashlib.md5(open(src, "rb").read()).hexdigest() == digest


def test_failing_step_does_not_touch_source_file(picking, make_xlsx):
    src = make_xlsx("kaynak.xlsx", {"Rapor": picking})
    digest = hashlib.md5(open(src, "rb").read()).hexdigest()
    s = Session()
    s.add_source("T", sio.read_source(src), path=src)
    with pytest.raises(ShiftFlowError):
        s.add_step("T", "calc", {"name": "x", "formula": "[Bölge] / 0"})
    assert hashlib.md5(open(src, "rb").read()).hexdigest() == digest


def test_outputs_saved_in_workflow(picking, staff, tmp_path):
    s = build(picking, staff)
    s.set_outputs([{"dataset": "Birleşik", "sheet": "Detay"}, {"dataset": "Özet", "sheet": "Özet"}])
    out = tmp_path / "o.xlsx"
    assert s.export(str(out)) == ["Detay", "Özet"]


def test_relative_source_paths_resolved(picking, tmp_path, make_xlsx):
    src = make_xlsx("rapor.xlsx", {"S": picking})
    s = Session()
    s.add_source("T", sio.read_source(src), path="rapor.xlsx", sheet="S")
    p = tmp_path / "akis.json"
    s.save_workflow(str(p))
    s2 = Session()
    s2.load_workflow(str(p))
    assert s2.workflow.sources["T"].path == src
    assert len(s2.load_source_file("T")) == 6
