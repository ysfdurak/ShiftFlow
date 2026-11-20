"""Gösterge paneli penceresi: kutucuklar (KPI, sütun/çubuk/çizgi grafiği, tablo)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from ..engine import dashboard as db
from ..engine import operations as ops
from .table_model import format_value

ACCENT = QColor("#1f6fb2")
MUTED = QColor("#6b7680")


def _short(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f} Mn".replace(".", ",")
    if a >= 10_000:
        return f"{v / 1000:.0f} B"
    return format_value(round(v, 2))


class ChartWidget(QWidget):
    """Basit, bağımlılıksız grafik çizimi (sütun, çubuk, çizgi)."""

    def __init__(self, data: db.TileData, parent=None):
        super().__init__(parent)
        self.data = data
        self.setMinimumHeight(190)

    def paintEvent(self, _):
        d = self.data
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 6, -8, -6)
        vals = [v or 0.0 for v in d.values]
        if not vals:
            p.setPen(MUTED)
            p.drawText(r, Qt.AlignCenter, "Veri yok")
            return
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        fm = p.fontMetrics()
        vmax = max(max(vals), 0.0)
        vmin = min(min(vals), 0.0)
        span = (vmax - vmin) or 1.0
        if d.kind == "bar":  # yatay çubuk
            n = len(vals)
            lab_w = min(max(fm.horizontalAdvance(lb) for lb in d.labels) + 8, r.width() * 0.4)
            h = r.height() / n
            for i, (lb, v) in enumerate(zip(d.labels, vals)):
                y = r.top() + i * h
                p.setPen(MUTED)
                p.drawText(QRectF(r.left(), y, lab_w - 4, h), Qt.AlignRight | Qt.AlignVCenter,
                           fm.elidedText(lb, Qt.ElideRight, int(lab_w - 4)))
                w = (r.width() - lab_w - 60) * (v - 0) / (vmax or 1.0)
                p.fillRect(QRectF(r.left() + lab_w, y + h * 0.15, max(w, 1), h * 0.7), ACCENT)
                p.setPen(QColor("#1f2a33"))
                p.drawText(QRectF(r.left() + lab_w + max(w, 1) + 4, y, 60, h), Qt.AlignLeft | Qt.AlignVCenter,
                           _short(v))
            return
        bottom = r.bottom() - fm.height() - 4
        top = r.top() + fm.height()
        plot_h = bottom - top
        n = len(vals)
        step = r.width() / n

        def ypos(v):
            return bottom - (v - vmin) / span * plot_h
        p.setPen(QPen(QColor("#d9dee3"), 1))
        p.drawLine(QPointF(r.left(), ypos(0)), QPointF(r.right(), ypos(0)))
        every = max(1, int(n / max(1, r.width() / 60)))
        for i, lb in enumerate(d.labels):
            if i % every == 0:
                p.setPen(MUTED)
                p.drawText(QRectF(r.left() + i * step, bottom + 2, step * every, fm.height()), Qt.AlignHCenter,
                           fm.elidedText(lb, Qt.ElideRight, int(step * every)))
        if d.kind == "line":
            pts = [QPointF(r.left() + (i + 0.5) * step, ypos(v)) for i, v in enumerate(vals)]
            p.setPen(QPen(ACCENT, 2))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            p.setBrush(ACCENT)
            for pt in pts:
                p.drawEllipse(pt, 2.5, 2.5)
            if pts:
                p.setPen(QColor("#1f2a33"))
                p.drawText(QRectF(pts[-1].x() - 60, pts[-1].y() - fm.height() - 2, 60, fm.height()),
                           Qt.AlignRight, _short(vals[-1]))
            return
        bw = step * 0.7
        for i, v in enumerate(vals):
            x = r.left() + i * step + (step - bw) / 2
            y0, y1 = ypos(0), ypos(v)
            p.fillRect(QRectF(x, min(y0, y1), bw, abs(y1 - y0) or 1), ACCENT)
            if n <= 16:
                p.setPen(QColor("#1f2a33"))
                p.drawText(QRectF(x - 10, min(y0, y1) - fm.height(), bw + 20, fm.height()), Qt.AlignHCenter,
                           _short(v))


class TileWidget(QFrame):
    def __init__(self, data: db.TileData, on_edit, on_remove, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.setStyleSheet("QFrame#tile { background: #ffffff; border: 1px solid #d9dee3; border-radius: 6px; }")
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(f"<b>{data.title}</b>")
        head.addWidget(t, 1)
        for txt, fn, tip in (("✎", on_edit, "Düzenle"), ("✕", on_remove, "Kaldır")):
            b = QPushButton(txt)
            b.setFixedWidth(26)
            b.setToolTip(tip)
            b.setFlat(True)
            b.clicked.connect(fn)
            head.addWidget(b)
        lay.addLayout(head)
        if data.error:
            e = QLabel("✖ " + data.error)
            e.setStyleSheet("color:#a32020")
            e.setWordWrap(True)
            lay.addWidget(e, 1)
        elif data.kind == "kpi":
            v = QLabel("—" if data.value is None else format_value(round(data.value, 2)))
            f = v.font()
            f.setPointSize(f.pointSize() + 16)
            f.setBold(True)
            v.setFont(f)
            v.setStyleSheet("color:#1f6fb2")
            v.setAlignment(Qt.AlignCenter)
            lay.addWidget(v, 1)
        elif data.kind == "table":
            from .common import PreviewTable
            tb = PreviewTable(rows=50)
            tb.set_frame(data.table)
            lay.addWidget(tb, 1)
        else:
            lay.addWidget(ChartWidget(data), 1)
        if data.note:
            n = QLabel(data.note)
            n.setStyleSheet("color:#6b7680")
            lay.addWidget(n)
        self.data = data


class TileDialog(QDialog):
    def __init__(self, session, tile=None, parent=None):
        super().__init__(parent)
        tile = dict(tile or {})
        self.session = session
        self.setWindowTitle("Kutucuk")
        self.resize(480, 360)
        f = QFormLayout(self)
        self.title = QLineEdit(tile.get("title", ""))
        f.addRow("Başlık:", self.title)
        self.kind = QComboBox()
        for k, v in db.KINDS.items():
            self.kind.addItem(v, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(tile.get("kind", "column"))))
        f.addRow("Tür:", self.kind)
        self.ds = QComboBox()
        self.ds.addItems(list(session.workflow.datasets))
        if tile.get("dataset") in session.workflow.datasets:
            self.ds.setCurrentText(tile["dataset"])
        f.addRow("Veri kümesi:", self.ds)
        self.x = QComboBox()
        self.y = QComboBox()
        f.addRow("Yatay eksen (gruplama):", self.x)
        f.addRow("Değer sütunu:", self.y)
        self.agg = QComboBox()
        for k, v in db.AGGS.items():
            self.agg.addItem(v, k)
        self.agg.setCurrentIndex(max(0, self.agg.findData(tile.get("agg", "sum"))))
        f.addRow("Hesaplama:", self.agg)
        self.dg = QComboBox()
        for k, v in ops.DATE_GROUPS.items():
            self.dg.addItem(v, k)
        self.dg.setCurrentIndex(max(0, self.dg.findData(tile.get("date_group", "none"))))
        f.addRow("Tarih gruplama:", self.dg)
        self.top = QSpinBox()
        self.top.setRange(0, 1000)
        self.top.setSpecialValueText("hepsi")
        self.top.setValue(int(tile.get("top_n") or 0))
        f.addRow("İlk N:", self.top)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.ds.currentTextChanged.connect(lambda *_: self._cols(tile))
        self.kind.currentIndexChanged.connect(self._sync)
        self._cols(tile)
        self._sync()

    def _cols(self, tile):
        try:
            cols = [str(c) for c in self.session.result(self.ds.currentText()).columns]
        except Exception:  # noqa: BLE001
            cols = []
        for cb, key in ((self.x, "x"), (self.y, "y")):
            cb.clear()
            cb.addItems(cols)
            if tile.get(key) in cols:
                cb.setCurrentText(tile[key])

    def _sync(self):
        k = self.kind.currentData()
        for w in (self.x, self.dg, self.top):
            w.setEnabled(k in ("column", "bar", "line"))
        self.agg.setEnabled(k != "table")
        self.y.setEnabled(k != "table")

    def tile(self) -> dict:
        t = {"title": self.title.text().strip(), "kind": self.kind.currentData(), "dataset": self.ds.currentText(),
             "y": self.y.currentText(), "agg": self.agg.currentData()}
        if t["kind"] in ("column", "bar", "line"):
            t["x"] = self.x.currentText()
            if self.dg.currentData() != "none":
                t["date_group"] = self.dg.currentData()
            if self.top.value():
                t["top_n"] = self.top.value()
        return t


class DashboardDialog(QDialog):
    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window_ = window
        self.session = window.session
        self.setWindowTitle("Gösterge paneli")
        self.resize(1100, 760)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        h = QLabel("Kutucuklar iş akışıyla kaydedilir ve her açılışta güncel sonuçtan hesaplanır. Geçmiş eğilim "
                   "için Arşiv'den bir dönem aralığı ekleyip _tarih sütununa göre gün/hafta gruplayın.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        top.addWidget(h, 1)
        for txt, fn in (("Kutucuk ekle", self.add), ("Yenile", self.refresh), ("Resim olarak kaydet…", self.save_png)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            top.addWidget(b)
        lay.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        lay.addWidget(self.scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.tiles = db.tiles_of(self.session)
        if not self.tiles:
            self.tiles = self.suggest()
        self.refresh()

    def suggest(self) -> list[dict]:
        """Boş panel için öneri: ilk veri kümesinin ilk sayı sütunu ve ilk metin sütunu."""
        for name in self.session.workflow.datasets:
            try:
                df = self.session.result(name)
            except Exception:  # noqa: BLE001
                continue
            nums = [str(c) for c in df.columns if str(df[c].dtype).startswith(("int", "float", "Int", "Float"))]
            texts = [str(c) for c in df.columns if str(c) not in nums]
            if nums:
                tiles = [{"title": f"Toplam {nums[0]}", "kind": "kpi", "dataset": name, "y": nums[0], "agg": "sum"}]
                if texts:
                    tiles.append({"title": f"{texts[0]} bazında {nums[0]}", "kind": "column", "dataset": name,
                                  "x": texts[0], "y": nums[0], "agg": "sum", "top_n": 12})
                return tiles
        return []

    def refresh(self):
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(10)
        self.widgets = []
        for i, t in enumerate(self.tiles):
            data = db.compute_tile(self.session, t)
            w = TileWidget(data, lambda _=False, i=i: self.edit(i), lambda _=False, i=i: self.remove(i))
            w.setMinimumHeight(260 if t.get("kind") != "kpi" else 150)
            grid.addWidget(w, *self._pos(i))
            self.widgets.append(w)
        if not self.tiles:
            grid.addWidget(QLabel("Henüz kutucuk yok. 'Kutucuk ekle' ile başlayın."), 0, 0)
        grid.setRowStretch(grid.rowCount(), 1)
        self.scroll.setWidget(host)

    @staticmethod
    def _pos(i):
        return divmod(i, 2)

    def _save(self):
        try:
            db.set_tiles(self.session, self.tiles)
            self.window_._title()
        except Exception:  # noqa: BLE001 - panel ayarı kaydedilemese de görünüm çalışır
            pass

    def add(self):
        d = TileDialog(self.session, None, self)
        if d.exec() == QDialog.Accepted:
            self.tiles.append(d.tile())
            self._save()
            self.refresh()

    def edit(self, i):
        d = TileDialog(self.session, self.tiles[i], self)
        if d.exec() == QDialog.Accepted:
            self.tiles[i] = d.tile()
            self._save()
            self.refresh()

    def remove(self, i):
        del self.tiles[i]
        self._save()
        self.refresh()

    def save_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Paneli resim olarak kaydet", "gosterge_paneli.png", "PNG (*.png)")
        if path:
            self.scroll.widget().grab().save(path)
