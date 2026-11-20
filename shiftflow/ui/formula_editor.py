"""Uzun formüller için düzenleyici.

- Renklendirme: sütunlar, fonksiyonlar, metinler, sayılar, işaretler
- Parantez eşleştirme: imleç bir parantezin yanındayken eşi vurgulanır
- Otomatik tamamlama: '[' yazınca sütunlar, harf yazınca fonksiyonlar
- İmza ipucu: imlecin bulunduğu fonksiyon ve sıradaki bağımsız değişken
- Hata yeri: formül hatalıysa hatanın olduğu yer dalgalı çizgiyle işaretlenir
- Biçimlendir (Ctrl+Shift+F) / tek satır: anlam değişmeden girintileme
"""

from __future__ import annotations

import re

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QTextEdit

from ..engine import expression

_NAME = r"[A-Za-zÇĞİÖŞÜçğıöşü_][A-Za-z0-9ÇĞİÖŞÜçğıöşü_.]*"


def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


# Formülde geçen sütunlar sırayla bu renkleri alır (Excel'deki renkli başvurular gibi)
COLUMN_COLORS = ["#1565c0", "#c62828", "#2e7d32", "#6a1b9a", "#ef6c00", "#00838f", "#ad1457", "#5d4037"]
_COL_RX = re.compile(r"\[((?:[^\]]|\]\])*)\]")


def column_colors(text: str) -> dict[str, str]:
    """{sütun adı: renk} — formülde ilk geçiş sırasına göre."""
    out: dict[str, str] = {}
    masked = re.sub(r"\"(?:[^\"]|\"\")*\"?", lambda m: " " * len(m.group(0)), text)
    for m in _COL_RX.finditer(masked):
        name = m.group(1).replace("]]", "]")
        if name and name not in out:
            out[name] = COLUMN_COLORS[len(out) % len(COLUMN_COLORS)]
    return out


def looks_like_excel(text: str) -> bool:
    """Yapıştırılan metin Excel formülü mü? (= ile başlar ve hücre/sayfa başvurusu içerir)"""
    t = text.strip()
    if not t.startswith("=") or "\n" in t.strip():
        return False
    masked = re.sub(r"\"(?:[^\"]|\"\")*\"", "", t)
    masked = re.sub(r"\[[^\]]*\]", "", masked)
    return bool(re.search(r"(?<![A-Za-zÇĞİÖŞÜçğıöşü_])\$?[A-Za-z]{1,3}\$?\d+\b|![\$A-Za-z]|\b[A-Za-z]{1,3}:[A-Za-z]{1,3}\b",
                          masked))


class FormulaHighlighter(QSyntaxHighlighter):
    RULES = [
        (re.compile(r"\d+(?:[.,]\d+)?"), _fmt("#a15c00")),
        (re.compile(r"<>|<=|>=|[-+*/^&=<>;]"), _fmt("#6b7680", bold=True)),
        (re.compile(_NAME + r"(?=\s*\()"), _fmt("#6a1b9a", bold=True)),
        (re.compile(r"\b(DOĞRU|YANLIŞ|TRUE|FALSE)\b", re.I), _fmt("#6a1b9a")),
        (re.compile(r"\[(?:[^\]]|\]\])*\]"), _fmt("#0d5fa6")),
        (re.compile(r"\"(?:[^\"]|\"\")*\"?"), _fmt("#1d6b3a")),
    ]

    colors: dict[str, str] = {}

    def highlightBlock(self, text):
        for rx, f in self.RULES:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        for m in _COL_RX.finditer(text):
            c = self.colors.get(m.group(1).replace("]]", "]"))
            if c:
                # metin içindeki köşeli parantezler (tırnak) renklenmesin
                if text[:m.start()].count('"') % 2:
                    continue
                self.setFormat(m.start(), m.end() - m.start(), _fmt(c, bold=True))


def matching_paren(text: str, pos: int) -> int | None:
    """`pos` konumundaki parantezin eşinin konumu (tırnak ve [ ] içleri atlanır)."""
    if pos < 0 or pos >= len(text) or text[pos] not in "()":
        return None
    mask = [False] * len(text)
    for m in re.finditer(r"\"(?:[^\"]|\"\")*\"|\[(?:[^\]]|\]\])*\]", text):
        for i in range(m.start(), m.end()):
            mask[i] = True
    if mask[pos]:
        return None
    step, open_c, close_c = (1, "(", ")") if text[pos] == "(" else (-1, ")", "(")
    depth, i = 0, pos
    while 0 <= i < len(text):
        if not mask[i]:
            if text[i] == open_c:
                depth += 1
            elif text[i] == close_c:
                depth -= 1
                if depth == 0:
                    return i
        i += step
    return None


class FormulaEdit(QPlainTextEdit):
    signatureChanged = Signal(str)
    columnsColored = Signal(dict)  # {sütun: renk} formül değişince
    columnClicked = Signal(str)  # imleç bir [sütun] üzerine gelince
    excelPasted = Signal(str)  # Excel formülü yapıştırıldı (çevrilmek üzere)

    def __init__(self, parent=None, columns=None):
        super().__init__(parent)
        f = QFont("Consolas" if self.font().family() else "monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(max(self.font().pointSize(), 10))
        self.setFont(f)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.highlighter = FormulaHighlighter(self.document())
        self._error = None
        self._columns: list[str] = []
        # Türkçe adlar (İngilizce eş adlar listede tekrar görünmesin)
        self.functions = sorted(k for k in expression.FUNCTIONS if k not in expression._ALIASES)
        self.model = QStringListModel(self)
        self.completer = QCompleter(self.model, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.activated.connect(self._insert_completion)
        self._mode = None
        self._prefix = ""
        self.set_columns(list(columns) if columns is not None else [])
        self.highlighter.colors = {}
        self.translate_paste = False  # True: Excel formülü yapıştırılınca excelPasted sinyali
        self._colors: dict[str, str] = {}
        self.cursorPositionChanged.connect(self._cursor_moved)
        self.textChanged.connect(self._clear_error)
        self.textChanged.connect(self._recolor)

    # ------------------------------------------------------------ dış arayüz
    def set_columns(self, cols):
        self._columns = [str(c) for c in cols]

    def set_error(self, pos: int | None):
        self._error = pos
        self._refresh_marks()

    def format(self):
        try:
            text = expression.format_formula(self.toPlainText())
        except Exception as exc:  # hatalı formül biçimlendirilemez; yeri işaretlenir
            self.set_error(getattr(exc, "pos", None))
            return False
        self.setPlainText(text)
        return True

    def to_one_line(self):
        try:
            self.setPlainText(expression.one_line(self.toPlainText()))
        except Exception as exc:
            self.set_error(getattr(exc, "pos", None))

    def line_col(self, pos: int) -> tuple[int, int]:
        text = self.toPlainText()[:pos]
        return text.count("\n") + 1, len(text) - (text.rfind("\n") + 1) + 1

    def column_colors(self) -> dict[str, str]:
        return dict(self._colors)

    def _recolor(self):
        cols = column_colors(self.toPlainText())
        if cols != self._colors:
            self._colors = cols
            self.highlighter.colors = cols
            self.highlighter.rehighlight()
            self.columnsColored.emit(dict(cols))

    def column_at(self, pos: int) -> str | None:
        text = self.toPlainText()
        for m in _COL_RX.finditer(text):
            if m.start() <= pos <= m.end() and not text[:m.start()].count('"') % 2:
                return m.group(1).replace("]]", "]")
        return None

    def insertFromMimeData(self, source):
        """Excel'den kopyalanan formül (=B2*C2 gibi) yapıştırılınca çeviri önerilir."""
        text = source.text() if source.hasText() else ""
        if looks_like_excel(text) and self.translate_paste:
            self.excelPasted.emit(text.strip())
            return
        super().insertFromMimeData(source)

    # ------------------------------------------------------------ işaretler
    def _clear_error(self):
        if self._error is not None:
            self._error = None
            self._refresh_marks()

    def _sel(self, start, length, fmt):
        s = QTextEdit.ExtraSelection()
        c = self.textCursor()
        c.setPosition(start)
        c.setPosition(start + length, QTextCursor.KeepAnchor)
        s.cursor = c
        s.format = fmt
        return s

    def _refresh_marks(self):
        sels = []
        text = self.toPlainText()
        pos = self.textCursor().position()
        for p in (pos, pos - 1):
            if 0 <= p < len(text) and text[p] in "()":
                m = matching_paren(text, p)
                f = QTextCharFormat()
                if m is None:
                    f.setBackground(QColor("#f6c9c9"))
                    sels.append(self._sel(p, 1, f))
                else:
                    f.setBackground(QColor("#cde2f6"))
                    f.setFontWeight(QFont.Bold)
                    sels.append(self._sel(p, 1, f))
                    sels.append(self._sel(m, 1, f))
                break
        if self._error is not None and 0 <= self._error <= len(text):
            f = QTextCharFormat()
            f.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            f.setUnderlineColor(QColor("#c62828"))
            f.setBackground(QColor("#fde7e7"))
            end = self._error
            while end < len(text) and not text[end].isspace() and text[end] not in ";)":
                end += 1
            sels.append(self._sel(self._error, max(1, end - self._error), f))
        line = QTextEdit.ExtraSelection()
        line.format.setBackground(QColor("#f7f9fb"))
        line.format.setProperty(QTextFormat.FullWidthSelection, True)
        line.cursor = self.textCursor()
        line.cursor.clearSelection()
        self.setExtraSelections([line] + sels)

    def _cursor_moved(self):
        self._refresh_marks()
        col = self.column_at(self.textCursor().position())
        if col:
            self.columnClicked.emit(col)
        sig = expression.signature_at(self.toPlainText(), self.textCursor().position())
        self.signatureChanged.emit(expression.signature_text(*sig) if sig else "")

    # ------------------------------------------------------------ tamamlama
    def _context(self):
        text = self.toPlainText()[: self.textCursor().position()]
        if text.count('"') % 2:
            return None, ""
        m = re.search(r"\[([^\]\[]*)$", text)
        if m:
            return "col", m.group(1)
        m = re.search(r"(?<![\]\w\"])(" + _NAME + r")$", text)
        if m and len(m.group(1)) >= 2:
            return "func", m.group(1)
        return None, ""

    def _update_completer(self):
        mode, prefix = self._context()
        self._mode, self._prefix = mode, prefix
        if mode is None:
            self.completer.popup().hide()
            return
        items = self._columns if mode == "col" else self.functions
        from ..engine.values import tr_lower
        p = tr_lower(prefix)
        # önce yazılanla başlayanlar, sonra içinde geçenler
        items = sorted(items, key=lambda x: (not tr_lower(x).startswith(p), tr_lower(x)))
        self.model.setStringList(items)
        self.completer.setCompletionPrefix(prefix)
        if self.completer.completionCount() == 0 or (
                self.completer.completionCount() == 1 and self.completer.currentCompletion() == prefix):
            self.completer.popup().hide()
            return
        cr = self.cursorRect()
        cr.setWidth(max(260, self.completer.popup().sizeHintForColumn(0) + 30))
        self.completer.complete(cr)
        self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))

    def _insert_completion(self, text):
        c = self.textCursor()
        c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(self._prefix))
        if self._mode == "col":
            c.insertText(text.replace("]", "]]") + "]")
        else:
            c.insertText(text + "(")
        self.setTextCursor(c)
        self.completer.popup().hide()

    def keyPressEvent(self, e):
        popup = self.completer.popup()
        if popup.isVisible() and e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            idx = popup.currentIndex()
            if idx.isValid():
                self._insert_completion(idx.data())
                return
        if popup.isVisible() and e.key() == Qt.Key_Escape:
            popup.hide()
            return
        if e.key() == Qt.Key_F and e.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
            self.format()
            return
        if e.key() == Qt.Key_Tab:
            self.insertPlainText("    ")
            return
        super().keyPressEvent(e)
        if e.text() and (e.text().isprintable() or e.key() == Qt.Key_Backspace):
            self._update_completer()


# ------------------------------------------------------------------ tek satırlık kutular için
class FormulaEditDialog:
    """Tek satırlık formül kutusunu (Doğruysa/Yanlışsa, kural değeri) büyük düzenleyicide açar."""

    @staticmethod
    def edit(parent, text: str, columns, title="Formülü düzenle") -> str | None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        d = QDialog(parent)
        d.setWindowTitle(title)
        d.resize(760, 360)
        lay = QVBoxLayout(d)
        h = QLabel("Uzun formülü burada yazın. Ctrl+Shift+F ile girintili gösterebilirsiniz; kutuya tek satır "
                   "olarak geri yazılır. Düz metin için tırnak gerekmez (Hedefte), formülde metin tırnak içinde.")
        h.setWordWrap(True)
        lay.addWidget(h)
        ed = FormulaEdit(columns=columns)
        ed.setPlainText(text or "")
        lay.addWidget(ed, 1)
        sig = QLabel()
        sig.setObjectName("signature")
        ed.signatureChanged.connect(sig.setText)
        lay.addWidget(sig)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() != QDialog.Accepted:
            return None
        out = ed.toPlainText().strip()
        if "\n" in out:
            try:
                out = expression.one_line(out)
            except Exception:  # noqa: BLE001 - hatalı formül de olduğu gibi döner; önizleme hatayı gösterir
                out = " ".join(out.split())
        return out


def attach_editor_button(line_edit, columns, parent=None):
    """QLineEdit'in sağına '…' düğmesi koyar; tıklanınca büyük formül düzenleyici açılır. Düzeni döndürür."""
    from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget
    w = QWidget(parent)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(line_edit, 1)
    b = QToolButton()
    b.setText("…")
    b.setToolTip("Büyük formül düzenleyicide aç")

    def go():
        res = FormulaEditDialog.edit(w, line_edit.text(), columns)
        if res is not None:
            line_edit.setText(res)
    b.clicked.connect(go)
    h.addWidget(b)
    w.editor_button = b
    return w
