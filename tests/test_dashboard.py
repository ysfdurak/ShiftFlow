"""Gösterge paneli: kutucuk hesapları ve pencere."""

import pandas as pd
import pytest

from shiftflow.engine import dashboard as db
from shiftflow.engine.session import Session

DF = pd.DataFrame({"Ekip": ["A", "B", "A", "C"], "Adet": [10, 20, 30, 5],
                   "_tarih": pd.to_datetime(["2026-11-08", "2026-11-09", "2026-11-09", "2026-11-10"])})


@pytest.fixture
def s():
    s = Session()
    s.add_source("T", DF)
    return s


def test_kpi_and_charts(s):
    assert db.compute_tile(s, {"kind": "kpi", "dataset": "T", "y": "Adet", "agg": "sum"}).value == 65
    c = db.compute_tile(s, {"kind": "column", "dataset": "T", "x": "Ekip", "y": "Adet", "agg": "sum"})
    assert c.labels == ["A", "B", "C"] and c.values == [40, 20, 5]
    line = db.compute_tile(s, {"kind": "line", "dataset": "T", "x": "_tarih", "y": "Adet", "agg": "sum",
                               "date_group": "day"})
    assert line.labels == ["08.11", "09.11", "10.11"] and line.values == [10, 50, 5]
    top = db.compute_tile(s, {"kind": "bar", "dataset": "T", "x": "Ekip", "y": "Adet", "agg": "count", "top_n": 1})
    assert top.labels == ["A"] and top.values == [2]
    assert db.compute_tile(s, {"kind": "column", "dataset": "T", "y": "Yok"}).error
    assert db.compute_tile(s, {"kind": "table", "dataset": "T", "rows": 2}).table.shape[0] == 2


def test_tiles_saved_with_workflow(s, tmp_path):
    db.set_tiles(s, [{"kind": "kpi", "dataset": "T", "y": "Adet"}])
    p = tmp_path / "a.json"
    s.save_workflow(str(p))
    s2 = Session()
    s2.load_workflow(str(p))
    assert db.tiles_of(s2) == [{"kind": "kpi", "dataset": "T", "y": "Adet"}]


def test_dashboard_window(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QDialog, QMessageBox
    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui import dashboard_ui as du
    from shiftflow.ui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    w = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(w)
    w.session.add_source("T", DF)
    d = du.DashboardDialog(w)
    qtbot.addWidget(d)
    assert [t["kind"] for t in d.tiles] == ["kpi", "column"]  # boş panelde öneri
    monkeypatch.setattr(du.TileDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(du.TileDialog, "tile", lambda self: {"kind": "line", "dataset": "T", "x": "_tarih",
                                                              "y": "Adet", "agg": "sum", "date_group": "day"})
    d.add()
    assert len(d.widgets) == 3 and db.tiles_of(w.session)[-1]["kind"] == "line"
    d.resize(1100, 760)
    d.show()
    qtbot.wait(20)
    img = d.scroll.widget().grab()
    assert img.width() > 100
    d.remove(0)
    assert len(db.tiles_of(w.session)) == 2


def test_value_summary_and_column_suggestion(qtbot):
    pytest.importorskip("PySide6")
    from shiftflow.engine.errors import MissingColumnError
    from shiftflow.ui.stage_dialogs import ValueDistributionDialog, value_summary
    info, tbl = value_summary(DF["Ekip"])
    assert tbl["Değer"].tolist()[0] == "A" and tbl["Adet"].tolist()[0] == 2 and tbl["%"].tolist()[0] == 50.0
    info2, _ = value_summary(DF["Adet"])
    assert ("Toplam", "65") in info2
    got = []
    d = ValueDistributionDialog(DF, "Ekip", on_filter=got.append)
    qtbot.addWidget(d)
    assert d.raw(1, DF["Ekip"]) in ("B", "C")
    e = MissingColumnError(["Toplanan"], ["Toplanan Adet", "Hedef"])
    assert "Bunu mu demek istediniz: [Toplanan] yerine [Toplanan Adet]?" in e.message
