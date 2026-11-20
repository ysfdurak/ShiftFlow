"""Dondurulmuş sütun + yatay kaydırma: başlık sağ tık menüsü doğru sütunu bulmalı."""
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from shiftflow.ui.common import DataTable  # noqa: E402


def test_frozen_header_menu_column_after_scroll(qtbot):
    t = DataTable()
    qtbot.addWidget(t)
    t.resize(500, 300)
    t.set_frame(pd.DataFrame({f"S{i}": range(5) for i in range(30)}))
    t.show()
    t.freeze(2)
    t.horizontalScrollBar().setValue(t.horizontalScrollBar().maximum())
    seen = []
    t.horizontalHeader().customContextMenuRequested.connect(lambda pos: seen.append(t.header_column_at(pos)))
    fh = t._frozen.horizontalHeader()
    pos = fh.rect().topLeft()
    pos.setX(fh.sectionViewportPosition(1) + 5)
    pos.setY(5)
    fh.customContextMenuRequested.emit(pos)
    assert seen == [1]
    # ana başlıkta aynı noktada kaydırma nedeniyle başka bir sütun var; o sütun dönmemeli
    assert t.horizontalHeader().logicalIndexAt(pos) != 1
