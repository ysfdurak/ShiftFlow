"""Uygulama içi yardım: kullanım kılavuzu (docs/KULLANIM_KILAVUZU.md) pencerede, ilgili bölüm açık.

F1 ana pencerede kılavuzu, işlem pencerelerinde o işlemin bölümünü açar. Kılavuz programla birlikte
gelir (PyInstaller paketinde de `docs` klasörü bulunur); internete bağlanmaz.
"""
from __future__ import annotations

import os
import re
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QSplitter, QTextBrowser, QVBoxLayout)

GUIDE = "KULLANIM_KILAVUZU.md"

# İşlem → kılavuz bölümünün başlığında geçen metin
SECTION_FOR = {
    "calc": "4.1 Formüller", "conditional": "4. İşlem ekleme", "lookup": "4.2 Eşleştir", "rules": "4.3 Kural",
    "unify": "4.6 Aynı değerin", "filter": "4. İşlem ekleme", "split": "4. İşlem ekleme",
    "fill_down": "4. İşlem ekleme", "fill_empty": "4. İşlem ekleme", "unpivot": "4. İşlem ekleme",
    "drop_empty_rows": "4. İşlem ekleme", "join": "6. Birleştirme", "append": "6. Birleştirme",
    "group": "7. Grupla", "pivot": "7. Grupla", "period_filter": "9.5 Dönem", "validate": "4.7 Doğrulama",
    "excel_formula": "4.1 Formüller", "palette": "4.5 İşlem ara", "build": "9. Açık raporlar",
    "archive": "9.6 Rapor arşivi", "mail": "9.7 Vardiya maili", "steps": "5. Adımları yönetme",
    "package": "9.9 Rapor paketleri", "dashboard": "9.10 Gösterge paneli", "export": "10. Excel'e aktarma",
    "folder": "3. Veri alma", "trash": "9.11 Çöp kutusu", "automation": "9.12 Otomasyon",
}


def docs_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    cands = [os.path.join(base, "docs")] if base else []
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.normpath(os.path.join(here, "..", "..", "docs")))
    for c in cands:
        if os.path.exists(os.path.join(c, GUIDE)):
            return c
    return cands[-1]


def sample_workflow() -> str | None:
    """Program klasöründeki örnek iş akışı (ornekler/ornek_vardiya_akisi.json); yoksa None."""
    base = getattr(sys, "_MEIPASS", None)
    here = os.path.dirname(os.path.abspath(__file__))
    for root in ([base] if base else []) + [os.path.normpath(os.path.join(here, "..", ".."))]:
        path = os.path.join(root, "ornekler", "ornek_vardiya_akisi.json")
        if os.path.exists(path):
            return path
    return None


def load_guide() -> str:
    try:
        with open(os.path.join(docs_dir(), GUIDE), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "# Kılavuz bulunamadı\n\nKullanım kılavuzu dosyası (docs/KULLANIM_KILAVUZU.md) program klasöründe yok."


def headings(md: str) -> list[tuple[int, str]]:
    return [(len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#{2,3})\s+(.+)$", md, re.M)]


class HelpDialog(QDialog):
    def __init__(self, parent=None, section: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("ShiftFlow — Kullanım kılavuzu")
        self.resize(1000, 720)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Kılavuzda ara:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("örn. düşeyara, vardiya, parametre (Enter: sonraki)")
        self.search.returnPressed.connect(self.find_text)
        top.addWidget(self.search, 1)
        lay.addLayout(top)
        split = QSplitter()
        self.toc = QListWidget()
        self.toc.setMaximumWidth(280)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setSearchPaths([docs_dir()])
        md = load_guide()
        self.view.setMarkdown(md)
        for level, title in headings(md):
            self.toc.addItem(("    " if level == 3 else "") + title)
        self.toc.currentTextChanged.connect(lambda t: self.go(t.strip()))
        split.addWidget(self.toc)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if section:
            self.go(section)

    def go(self, heading: str) -> bool:
        doc = self.view.document()
        c = doc.find(heading, 0)
        if c.isNull():
            return False
        self.view.setTextCursor(c)
        # başlık pencerenin üstüne gelsin
        self.view.moveCursor(QTextCursor.End)
        self.view.setTextCursor(c)
        self.view.ensureCursorVisible()
        return True

    def find_text(self):
        q = self.search.text().strip()
        if not q:
            return
        if not self.view.find(q):
            self.view.moveCursor(QTextCursor.Start)
            self.view.find(q)


def show_help(parent, key: str | None = None):
    d = HelpDialog(parent, SECTION_FOR.get(key or "", key))
    d.exec()


class WelcomeDialog(QDialog):
    """İlk açılışta karşılama: kişi ne yapmak istediğini seçer (`choice`)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ShiftFlow'a hoş geldiniz")
        self.resize(600, 420)
        self.choice = None
        lay = QVBoxLayout(self)
        t = QLabel(
            "<h2>ShiftFlow Data Studio</h2>"
            "<p>Her gün Excel'de elle yaptığınız rapor işini (filtre, formül, DÜŞEYARA, pivot) <b>bir kez</b> "
            "tanımlarsınız; ertesi gün raporları açıp <b>▶ Rapor oluştur</b>'a basarsınız.</p>"
            "<p>Veriler yalnız bu bilgisayarda işlenir, kaynak dosyalarınız değişmez.</p>"
            "<p><b>Nasıl başlamak istersiniz?</b></p>")
        t.setWordWrap(True)
        t.setTextFormat(Qt.RichText)
        lay.addWidget(t)
        options = [
            ("sample", "Örnekle dene (önerilir, 2 dakika)",
             "Hazır vardiya verisi ve iş akışı açılır, ardından ekran adım adım tanıtılır."),
            ("excel", "Açık Excel'deki raporumla başla", "WMS raporunu Excel'de açtıysanız buradan alın."),
            ("file", "Dosyadan başla", "Bilgisayardaki bir Excel veya CSV dosyasını seçin."),
            ("tour", "Önce ekranı tanıt", "Veri yüklemeden ekranın bölümlerini gösterir."),
        ]
        for key, title, sub in options:
            b = QPushButton(f"{title}\n{sub}")
            b.setObjectName("welcomeOption")
            b.setStyleSheet("QPushButton#welcomeOption { text-align: left; padding: 8px 12px; }")
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            lay.addWidget(b)
            if key == "sample":
                b.setDefault(True)
        row = QHBoxLayout()
        self.b_guide = QPushButton("Kullanım kılavuzu")
        self.b_guide.clicked.connect(lambda: (self.accept(), show_help(parent)))
        row.addWidget(self.b_guide)
        row.addStretch()
        b = QPushButton("Kapat")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)

    def _pick(self, key):
        self.choice = key
        self.accept()


del QTextDocument
