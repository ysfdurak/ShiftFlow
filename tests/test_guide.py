"""Sade düzen ve rehber: örnekle dene, ekran rehberi, karşılama, boş ekran bağlantıları."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from shiftflow.engine.library import ReportLibrary  # noqa: E402
from shiftflow.ui import help as help_ui  # noqa: E402
from shiftflow.ui.main_window import MainWindow, main_tour_steps, short_step_label  # noqa: E402


@pytest.fixture
def w(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    win = MainWindow(library=ReportLibrary(str(tmp_path / "l.db")))
    qtbot.addWidget(win)
    win.resize(1366, 728)
    win.show()
    return win


def test_short_step_label():
    assert short_step_label("Hesapla: Gerçekleşme % = EĞERHATA(YUVARLA([A]/[B]*100;1);0)") == "Hesapla: Gerçekleşme %"
    long = short_step_label("Eşleştir: Personel No → Personel [Ad Soyad, Ekip Lideri, Vardiya]")
    assert len(long) <= 38 and long.endswith("…")


def test_open_sample_loads_data_and_period(w):
    assert help_ui.sample_workflow()
    w.open_sample()
    assert w.workflow_path is None  # örnek dosyanın üzerine kaydedilmez
    assert w.current == "Toplama" and len(w.session.result("Toplama")) > 0
    p = w.period_bar.period()
    assert p.date.isoformat() == "2026-11-01" and w.period_bar.b_auto.isVisibleTo(w.period_bar)


def test_tour_walks_all_steps_and_closes(w, qtbot):
    w.open_sample()
    from shiftflow.ui.tour import Tour
    t = Tour(w, main_tour_steps(w))
    t.start()
    for i in range(len(t.steps)):
        t.go(i)
        assert t.active and t.bubble.title.text()
        if i in (0, 1, 3, 4):  # hedef görünür olmalı (vurgu deliği boş değil)
            assert not t.overlay.hole.isNull(), t.bubble.title.text()
        assert w.rect().contains(t.bubble.geometry())
    t.go(len(t.steps))  # Bitir
    assert not t.active


def test_column_info_hidden_by_default_and_layers(w):
    assert not w.col_dock.isVisible()
    assert w.findChild(type(w.ribbon), "ribbon") is w.ribbon
    # ayrı üst araç çubuğu yok: Rapor oluştur ve dönem şerit satırında
    from PySide6.QtWidgets import QToolBar
    assert [tb.objectName() for tb in w.findChildren(QToolBar) if tb.parent() is w] == ["tb_ribbon"]
    from PySide6.QtCore import Qt
    assert w.ribbon.cornerWidget(Qt.TopLeftCorner).isAncestorOf(w.build_button)
    assert w.ribbon.cornerWidget(Qt.TopRightCorner).isAncestorOf(w.period_bar)


def test_welcome_choice_and_empty_links(w, monkeypatch):
    called = []
    monkeypatch.setattr(w, "open_from_excel", lambda: called.append("excel"))
    w._empty_link("excel")
    d = help_ui.WelcomeDialog(w)
    d._pick("sample")
    assert d.choice == "sample" and called == ["excel"]
    assert "Örnekle deneyin" in w.empty_hint.text()
