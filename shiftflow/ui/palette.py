"""İşlem arama listesi (Ctrl+K): yazdıkça yapılabilecek işlemler süzülür."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from ..engine.values import tr_lower


@dataclass
class Command:
    title: str
    description: str
    run: Callable[[], None]
    group: str = "İşlem"
    keywords: str = ""
    boost: int = 0  # seçili sütuna uygun komutlar öne çıkar
    enabled: bool = True
    _hay: str = field(default="", repr=False)

    def haystack(self) -> str:
        if not self._hay:
            self._hay = tr_lower(f"{self.title} {self.keywords} {self.description} {self.group}")
        return self._hay


def _fold(s: str) -> str:
    """Türkçe karakter yazılmasa da bulunsun: 'dusey' -> 'düşey'."""
    return s.translate(str.maketrans("çğıöşüâî", "cgiosuai"))


def score(cmd: Command, query: str) -> int | None:
    q = _fold(tr_lower(query.strip()))
    if not q:
        return 100 + cmd.boost
    hay = _fold(cmd.haystack())
    title = _fold(tr_lower(cmd.title))
    words = q.split()
    if not all(w in hay for w in words):
        return None
    s = cmd.boost
    if title.startswith(q):
        s += 300
    elif q in title:
        s += 200
    elif all(w in title for w in words):
        s += 150
    elif all(w in _fold(tr_lower(cmd.keywords)) for w in words):
        s += 100
    return s


def filter_commands(cmds: list[Command], query: str) -> list[Command]:
    scored = [(score(c, query), i, c) for i, c in enumerate(cmds)]
    return [c for s, i, c in sorted((x for x in scored if x[0] is not None), key=lambda x: (-x[0], x[1]))]


class CommandPalette(QDialog):
    def __init__(self, commands: list[Command], parent=None, context: str = ""):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.commands = commands
        self.chosen: Command | None = None
        self.setObjectName("palette")
        self.resize(680, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ne yapmak istiyorsunuz?  (örn. düşeyara, boş, tekrar, yuvarla, vardiya, pivot)")
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)
        if context:
            c = QLabel(context)
            c.setObjectName("dialogHelp")
            lay.addWidget(c)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda *_: self.run_current())
        self.list.itemClicked.connect(lambda *_: self.run_current())
        lay.addWidget(self.list, 1)
        tip = QLabel("↑↓ seç · Enter uygula · Esc kapat")
        tip.setObjectName("dialogHelp")
        lay.addWidget(tip)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for c in filter_commands(self.commands, self.search.text())[:60]:
            it = QListWidgetItem(f"{c.title}\n   {c.group} · {c.description}")
            it.setData(Qt.UserRole, c)
            if not c.enabled:
                it.setForeground(QColor("#a5adb4"))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.search and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                if 0 <= r < self.list.count():
                    self.list.setCurrentRow(r)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.run_current()
                return True
        return super().eventFilter(obj, ev)

    def run_current(self):
        it = self.list.currentItem()
        if it is None:
            return
        c = it.data(Qt.UserRole)
        if not c.enabled:
            return
        self.chosen = c
        self.accept()
