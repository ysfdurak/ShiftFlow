"""Arka planda çalıştırma: pencere donmaz, ilerleme görünür, iptal değişikliği geri alır."""

import time

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QProgressDialog  # noqa: E402

from shiftflow.engine import operations as ops  # noqa: E402
from shiftflow.engine.errors import Cancelled, ShiftFlowError  # noqa: E402
from shiftflow.engine.session import Session  # noqa: E402
from shiftflow.ui import worker  # noqa: E402


@pytest.fixture
def slow_calc(monkeypatch):
    real = ops.REGISTRY["calc"].run

    def slow(inputs, p, label):
        time.sleep(0.25)
        return real(inputs, p, label)
    monkeypatch.setattr(ops.REGISTRY["calc"], "run", slow)


def _session(n_steps=0):
    s = Session()
    s.add_source("T", pd.DataFrame({"A": range(10)}))
    for i in range(n_steps):
        s.add_step("T", "calc", {"name": f"C{i}", "formula": "[A] * 2"})
    return s


def test_result_and_error_are_returned(qtbot):
    assert worker.run_task(None, lambda: 41 + 1) == 42
    with pytest.raises(ShiftFlowError):
        worker.run_task(None, lambda: (_ for _ in ()).throw(ShiftFlowError("x")))
    assert not worker.active()


def test_event_loop_keeps_running_and_dialog_shows(qtbot, slow_calc):
    s = _session()
    ticks, seen = [], {}
    t = QTimer()
    t.timeout.connect(lambda: ticks.append(1))
    t.start(50)

    def look():
        d = [w for w in QApplication.topLevelWidgets() if isinstance(w, QProgressDialog) and w.isVisible()]
        if d:
            seen["label"] = d[0].labelText()
    QTimer.singleShot(worker.SHOW_AFTER_MS + 350, look)
    for i in range(4):
        s.workflow.dataset("T").steps.append(ops_step(i))
    s._cache.clear()
    worker.run_task(None, lambda: s.result("T"), "Hesaplanıyor…", session=s)
    t.stop()
    assert len(ticks) >= 5  # olay döngüsü işledi: pencere donmadı
    assert "adım" in seen.get("label", "")  # ilerleme penceresi adım adını gösterdi
    assert s.cancel_event is None and s.progress is None


def ops_step(i):
    from shiftflow.engine.workflow import Step
    return Step(op="calc", params={"name": f"C{i}", "formula": "[A] * 2"})


def test_cancel_rolls_back_change(qtbot, slow_calc):
    s = _session(1)
    before = [x.params for x in s.workflow.dataset("T").steps]

    def cancel():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QProgressDialog) and w.isVisible():
                from PySide6.QtWidgets import QPushButton
                from PySide6.QtTest import QTest
                btn = w.findChild(QPushButton)
                QTest.mouseClick(btn, Qt.LeftButton)  # kullanıcı İptal'e tıklar (girdi süzgecinden geçer)
    QTimer.singleShot(worker.SHOW_AFTER_MS + 200, cancel)

    def change():
        def mut(wf):
            for i in range(6):
                wf.dataset("T").steps.append(ops_step(10 + i))
        s._commit(mut, focus="T")
    with pytest.raises(Cancelled):
        worker.run_task(None, change, session=s)
    assert [x.params for x in s.workflow.dataset("T").steps] == before
    assert not s.can_redo()
    assert len(s.result("T").columns) == 2


def test_input_outside_dialog_is_blocked(qtbot, slow_calc):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    s = _session(0)
    clicked = []
    b = QPushButton("dışarıdaki düğme")
    qtbot.addWidget(b)
    b.clicked.connect(lambda: clicked.append(1))
    b.show()
    QTimer.singleShot(100, lambda: QTest.mouseClick(b, Qt.LeftButton))
    for i in range(3):
        s.workflow.dataset("T").steps.append(ops_step(i))
    s._cache.clear()
    worker.run_task(None, lambda: s.result("T"), session=s)
    assert clicked == []  # görev sürerken iş akışı başka yerden değiştirilemez
