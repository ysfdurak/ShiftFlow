"""Ekran rehberi: ana pencerenin bölümlerini sırayla vurgulayıp kısa açıklama gösterir.

Pencerenin üstüne yarı saydam bir katman çizilir; anlatılan bölüm aydınlık kalır, yanında bir
balon (başlık, metin, Geri / İleri / Kapat) durur. Rehber hiçbir şeye tıklamaz ve veriyi değiştirmez;
yalnız gerekirse şeritte ilgili sekmeyi açar. Esc veya "Rehberi kapat" ile çıkılır.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

DIM = QColor(16, 26, 36, 150)
ACCENT = QColor("#1f6fb2")


class _Overlay(QWidget):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.hole = QRect()
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(host.rect())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRect(self.rect())
        if not self.hole.isNull():
            inner = QPainterPath()
            inner.addRoundedRect(self.hole, 6, 6)
            path = path.subtracted(inner)
        p.fillPath(path, DIM)
        if not self.hole.isNull():
            p.setPen(QPen(ACCENT, 3))
            p.drawRoundedRect(self.hole, 6, 6)

    def mousePressEvent(self, e):
        e.accept()  # rehber açıkken alttaki pencereye tıklanmaz


class _Bubble(QFrame):
    def __init__(self, host: QWidget, tour: "Tour"):
        super().__init__(host)
        self.setObjectName("tourBubble")
        self.setStyleSheet("QFrame#tourBubble { background: #ffffff; border: 1px solid #9fb3c6; border-radius: 8px; }"
                           "QLabel#tourTitle { font-size: 15px; font-weight: 700; color: #173a5a; }"
                           "QLabel#tourText { font-size: 13px; color: #26323c; }"
                           "QLabel#tourCount { color: #6b7680; }")
        self.setFixedWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        self.title = QLabel()
        self.title.setObjectName("tourTitle")
        self.text = QLabel()
        self.text.setObjectName("tourText")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName("tourCount")
        row.addWidget(self.count)
        row.addStretch()
        self.b_close = QPushButton("Rehberi kapat")
        self.b_back = QPushButton("Geri")
        self.b_next = QPushButton("İleri")
        self.b_next.setDefault(True)
        self.b_close.clicked.connect(tour.close)
        self.b_back.clicked.connect(lambda: tour.go(tour.index - 1))
        self.b_next.clicked.connect(lambda: tour.go(tour.index + 1))
        for b in (self.b_close, self.b_back, self.b_next):
            row.addWidget(b)
        lay.addLayout(row)
        esc = QShortcut(QKeySequence("Escape"), self, tour.close)
        esc.setContext(Qt.WidgetWithChildrenShortcut)


class Tour(QObject):
    """steps: [(hedef widget'ı döndüren fonksiyon, başlık, metin (HTML), hazırlık fonksiyonu veya None)]"""

    def __init__(self, host: QWidget, steps: list):
        super().__init__(host)
        self.host, self.steps, self.index = host, steps, 0
        self.overlay = _Overlay(host)
        self.bubble = _Bubble(host, self)
        self.overlay.hide()
        self.bubble.hide()
        host.installEventFilter(self)

    # ------------------------------------------------------------------ akış
    def start(self):
        self.overlay.setGeometry(self.host.rect())
        self.overlay.show()
        self.overlay.raise_()
        self.bubble.show()
        self.bubble.raise_()
        self.go(0)

    def go(self, i: int):
        if i >= len(self.steps):
            self.close()
            return
        self.index = max(0, i)
        target_fn, title, text, prepare = self.steps[self.index]
        if prepare:
            prepare()
        self.bubble.title.setText(title)
        self.bubble.text.setText(text)
        self.bubble.count.setText(f"{self.index + 1} / {len(self.steps)}")
        self.bubble.b_back.setEnabled(self.index > 0)
        self.bubble.b_next.setText("Bitir" if self.index == len(self.steps) - 1 else "İleri")
        self.bubble.b_next.setFocus()
        self._place(target_fn)

    def close(self):
        self.host.removeEventFilter(self)
        self.overlay.hide()
        self.bubble.hide()
        self.overlay.deleteLater()
        self.bubble.deleteLater()

    @property
    def active(self) -> bool:
        return self.bubble.isVisible()

    # ------------------------------------------------------------------ yerleşim
    def target_rect(self, target_fn) -> QRect:
        try:
            w = target_fn()
        except Exception:  # noqa: BLE001 - hedef yoksa balon ortada durur
            w = None
        if w is None or not w.isVisible():
            return QRect()
        top_left = w.mapTo(self.host, QPoint(0, 0))
        return QRect(top_left, w.size()).adjusted(-4, -4, 4, 4).intersected(self.host.rect())

    def _place(self, target_fn):
        r = self.target_rect(target_fn)
        self.overlay.hole = r
        self.overlay.update()
        self.bubble.adjustSize()
        bw, bh = self.bubble.width(), self.bubble.sizeHint().height()
        H = self.host.rect()
        if r.isNull():
            pos = QPoint((H.width() - bw) // 2, (H.height() - bh) // 2)
        else:
            # önce hedefin altı, sığmazsa sağı, sonra solu, en son üstü
            cands = [QPoint(r.left(), r.bottom() + 12), QPoint(r.right() + 12, r.top()),
                     QPoint(r.left() - bw - 12, r.top()), QPoint(r.left(), r.top() - bh - 12)]
            pos = next((c for c in cands if H.contains(QRect(c, self.bubble.size().expandedTo(
                self.bubble.sizeHint())))), cands[0])
        pos.setX(max(8, min(pos.x(), H.width() - bw - 8)))
        pos.setY(max(8, min(pos.y(), H.height() - bh - 8)))
        self.bubble.move(pos)
        self.bubble.raise_()

    def eventFilter(self, obj, e):
        if obj is self.host and e.type() == QEvent.Resize and self.active:
            self.overlay.setGeometry(self.host.rect())
            self._place(self.steps[self.index][0])
        return False
