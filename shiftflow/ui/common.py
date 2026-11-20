"""Arayüzde tekrar kullanılan parçalar."""

from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..engine import operations as ops
from ..engine.errors import ShiftFlowError
from .table_model import DataFrameModel, copy_value


def show_error(parent, exc: Exception, title="İşlem yapılamadı"):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    if isinstance(exc, ShiftFlowError):
        box.setText(exc.message)
        if exc.detail:
            box.setDetailedText(exc.detail)
    else:
        box.setText("Beklenmeyen bir hata oluştu. İşlem uygulanmadı; verileriniz değişmedi.")
        box.setDetailedText(f"{type(exc).__name__}: {exc}")
    box.exec()


def info(parent, text, title="ShiftFlow"):
    QMessageBox.information(parent, title, text)


def ask(parent, text, title="Onay") -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


@contextmanager
def busy():
    QApplication.setOverrideCursor(Qt.WaitCursor)
    QApplication.processEvents()
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def fmt_n(n) -> str:
    return f"{int(n):,}".replace(",", ".")


class FilterHeader(QHeaderView):
    """Excel'deki gibi her başlıkta ▾ filtre oku. Oka tıklayınca `arrowClicked(sütun no)` yayınlanır."""

    arrowClicked = Signal(int)
    ARROW = 16

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.arrows = True

    def paintSection(self, painter, rect, index):
        painter.save()
        super().paintSection(painter, rect, index)
        painter.restore()
        if self.arrows and rect.width() > 40:
            from PySide6.QtGui import QColor
            painter.save()
            painter.setPen(QColor("#6b7680"))
            r = rect.adjusted(rect.width() - self.ARROW - 2, 0, -2, 0)
            painter.drawText(r, int(Qt.AlignCenter), "▾")
            painter.restore()

    def _on_arrow(self, pos) -> int:
        i = self.logicalIndexAt(pos)
        if i < 0 or not self.arrows:
            return -1
        right = self.sectionViewportPosition(i) + self.sectionSize(i)
        return i if right - self.ARROW - 4 <= pos.x() <= right else -1

    def mousePressEvent(self, e):
        i = self._on_arrow(e.position().toPoint())
        if i >= 0 and e.button() == Qt.LeftButton:
            self.arrowClicked.emit(i)
            return
        super().mousePressEvent(e)


class DataTable(QTableView):
    """Excel benzeri, salt okunur, sanal tablo görünümü."""

    selectionStats = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = DataFrameModel(self)
        self.setModel(self.model_)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(True)
        vh = self.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(22)
        vh.setMinimumWidth(44)
        self.setHorizontalHeader(FilterHeader(self))
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setHighlightSections(True)
        hh.setSectionsClickable(True)
        self.selectionModel().selectionChanged.connect(self._emit_stats)

    def set_frame(self, df: pd.DataFrame | None):
        self.model_.set_frame(df)
        self._fit_columns()
        self.selectionStats.emit("")
        if getattr(self, "_frozen_n", 0):
            self.freeze(self._frozen_n)

    # ------------------------------------------------------------ sütun dondurma (Excel'deki "Bölmeleri dondur")
    def freeze(self, n: int):
        """Soldaki n sütunu sabitler: yatay kaydırmada görünür kalır. n=0 kaldırır."""
        n = max(0, min(int(n), self.model_.columnCount()))
        self._frozen_n = n
        fv = getattr(self, "_frozen", None)
        if n == 0:
            if fv is not None:
                fv.hide()
            return
        if fv is None:
            fv = QTableView(self)
            fv.setModel(self.model_)
            fv.setSelectionModel(self.selectionModel())
            fv.setFocusPolicy(Qt.NoFocus)
            fv.verticalHeader().hide()
            fv.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            fv.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            fv.setVerticalScrollMode(self.verticalScrollMode())
            fv.setAlternatingRowColors(True)
            fv.setWordWrap(False)
            fv.verticalHeader().setDefaultSectionSize(self.verticalHeader().defaultSectionSize())
            fv.setStyleSheet("QTableView { border: none; border-right: 2px solid #9aa4ad; }")
            fv.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
            self.verticalScrollBar().valueChanged.connect(fv.verticalScrollBar().setValue)
            self.horizontalHeader().sectionResized.connect(self._frozen_resized)
            fv.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
            fv.horizontalHeader().customContextMenuRequested.connect(self._frozen_header_menu)
            self._frozen = fv
        for c in range(self.model_.columnCount()):
            fv.setColumnHidden(c, c >= n or self.isColumnHidden(c))
            fv.setColumnWidth(c, self.columnWidth(c))
        fv.show()
        fv.raise_()
        self._frozen_geometry()

    def _frozen_header_menu(self, pos):
        # Dondurulmuş başlıktaki konum ana başlığa aynen aktarılırsa, tablo yatay kaydırılmışken
        # ana başlık o noktada başka bir sütun bulur. Sütun burada bulunur ve menüye bildirilir.
        self._header_menu_col = self._frozen.horizontalHeader().logicalIndexAt(pos)
        try:
            self.horizontalHeader().customContextMenuRequested.emit(pos)
        finally:
            self._header_menu_col = None

    def header_column_at(self, pos) -> int:
        """Başlık sağ tık menüsünün sütunu (dondurulmuş bölge dahil)."""
        forced = getattr(self, "_header_menu_col", None)
        return forced if forced is not None else self.horizontalHeader().logicalIndexAt(pos)

    def frozen_count(self) -> int:
        return getattr(self, "_frozen_n", 0)

    def _frozen_resized(self, i, _old, new):
        fv = getattr(self, "_frozen", None)
        if fv is not None and i < self._frozen_n:
            fv.setColumnWidth(i, new)
            self._frozen_geometry()

    def _frozen_geometry(self):
        fv = getattr(self, "_frozen", None)
        if fv is None or not self._frozen_n:
            return
        w = sum(self.columnWidth(c) for c in range(self._frozen_n) if not self.isColumnHidden(c))
        fv.setGeometry(self.verticalHeader().width() + self.frameWidth(), self.frameWidth(), w,
                       self.viewport().height() + self.horizontalHeader().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._frozen_geometry()

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        # dondurulmuş sütundaki hücreye gidilirken yatay kaydırma yapılmasın
        if index.isValid() and index.column() < getattr(self, "_frozen_n", 0):
            h = self.horizontalScrollBar().value()
            super().scrollTo(index, hint)
            self.horizontalScrollBar().setValue(h)
            return
        super().scrollTo(index, hint)

    def _fit_columns(self):
        df = self.model_.frame()
        fm = self.fontMetrics()
        for i, c in enumerate(df.columns):
            sample = [fm.horizontalAdvance(self.model_.data(self.model_.index(r, i)) or "") for r in range(min(60, len(df)))]
            w = max([fm.horizontalAdvance(str(c)) + 28] + sample) + 14
            self.setColumnWidth(i, max(60, min(w, 320)))

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(e)

    def copy_selection(self, with_header=False):
        idx = self.selectedIndexes()
        if not idx:
            return
        rows = sorted({i.row() for i in idx})
        cols = sorted({i.column() for i in idx})
        if len(rows) * len(cols) > 2_000_000:
            QMessageBox.warning(self, "Kopyala", "Seçim çok büyük. Büyük veriler için 'Excel'e aktar' kullanın.")
            return
        sel = {(i.row(), i.column()) for i in idx}
        lines = []
        if with_header:
            lines.append("\t".join(str(self.model_.frame().columns[c]) for c in cols))
        for r in rows:
            lines.append("\t".join(copy_value(self.model_.raw_value(r, c)) if (r, c) in sel else "" for c in cols))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _emit_stats(self, *_):
        idx = self.selectionModel().selectedIndexes()
        if len(idx) < 2:
            self.selectionStats.emit("")
            return
        if len(idx) > 300_000:
            self.selectionStats.emit(f"Seçili hücre: {fmt_n(len(idx))}")
            return
        total, cnt, nums = 0.0, 0, 0
        for i in idx:
            v = self.model_.raw_value(i.row(), i.column())
            if v is None or v is pd.NA or (isinstance(v, float) and v != v):
                continue
            cnt += 1
            if self.model_.is_numeric(i.column()):
                try:
                    total += float(v)
                    nums += 1
                except (TypeError, ValueError):
                    pass
        from .table_model import format_value
        parts = [f"Sayı: {fmt_n(cnt)}"]
        if nums:
            parts += [f"Toplam: {format_value(total)}", f"Ortalama: {format_value(total / nums)}"]
        self.selectionStats.emit("   ".join(parts))


class PreviewTable(DataTable):
    """Diyaloglarda küçük önizleme tablosu."""

    def __init__(self, parent=None, rows=200):
        super().__init__(parent)
        self._limit = rows
        self.setMinimumHeight(160)
        self.horizontalHeader().arrows = False

    def set_frame(self, df):
        super().set_frame(None if df is None else df.head(self._limit))


def column_combo(columns, current=None, editable=False) -> QComboBox:
    cb = QComboBox()
    cb.addItems([str(c) for c in columns])
    cb.setEditable(editable)
    if current is not None and str(current) in [str(c) for c in columns]:
        cb.setCurrentText(str(current))
    elif current is not None and editable:
        cb.setCurrentText(str(current))
    cb.setMinimumContentsLength(14)
    cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    return cb


class ColumnChecklist(QWidget):
    """Arama kutulu, işaretlenebilir sütun listesi (sıra değiştirme isteğe bağlı)."""

    changed = Signal()

    def __init__(self, columns, checked=None, orderable=False, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit(placeholderText="Sütun ara…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.list = QListWidget()
        checked_list = [c for c in (checked or []) if c in list(columns)]
        checked = set(checked_list)
        ordered = checked_list + [c for c in columns if c not in checked] if orderable and checked else list(columns)
        for c in ordered:
            it = QListWidgetItem(str(c))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c in checked else Qt.Unchecked)
            self.list.addItem(it)
        self.list.itemChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b_all = QPushButton("Tümü")
        b_none = QPushButton("Hiçbiri")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(b_all)
        row.addWidget(b_none)
        if orderable:
            up, down = QPushButton("▲ Yukarı"), QPushButton("▼ Aşağı")
            up.clicked.connect(lambda: self._move(-1))
            down.clicked.connect(lambda: self._move(1))
            row.addWidget(up)
            row.addWidget(down)
        row.addStretch()
        lay.addLayout(row)

    def _filter(self, text):
        t = text.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(t not in it.text().lower())

    def _set_all(self, on):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if not it.isHidden():
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _move(self, d):
        r = self.list.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(n, it)
        self.list.setCurrentRow(n)
        self.changed.emit()

    def checked(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class ConditionRow(QWidget):
    removed = Signal(object)
    changed = Signal()

    def __init__(self, df: pd.DataFrame, cond=None, parent=None):
        super().__init__(parent)
        self.df = df
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        cond = cond or {}
        self.col = column_combo(df.columns, cond.get("column"))
        self.op = QComboBox()
        for k, v in ops.CONDITION_OPS.items():
            if k != "in_list":
                self.op.addItem(v, k)
        if cond.get("op"):
            i = self.op.findData(cond["op"])
            if i >= 0:
                self.op.setCurrentIndex(i)
        self.value = QLineEdit(str(cond.get("value", "") or ""))
        self.value.setPlaceholderText("değer")
        self.rm = QPushButton("✕")
        self.rm.setFixedWidth(28)
        self.rm.setToolTip("Koşulu kaldır")
        for w in (self.col, self.op, self.value, self.rm):
            lay.addWidget(w)
        lay.setStretch(2, 1)
        self.col.currentTextChanged.connect(self._update_completer)
        self.col.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.op.currentIndexChanged.connect(self._toggle)
        self.op.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.value.textChanged.connect(lambda *_: self.changed.emit())
        self.rm.clicked.connect(lambda: self.removed.emit(self))
        self._update_completer()
        self._toggle()

    def _update_completer(self):
        c = self.col.currentText()
        if c in self.df.columns:
            vals = self.df[c].dropna().astype(str).drop_duplicates().head(500).tolist()
            comp = QCompleter(vals, self)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            self.value.setCompleter(comp)

    def _toggle(self):
        self.value.setEnabled(self.op.currentData() not in ops.NO_VALUE_OPS)

    def condition(self) -> dict:
        c = {"column": self.col.currentText(), "op": self.op.currentData()}
        if c["op"] not in ops.NO_VALUE_OPS:
            c["value"] = self.value.text()
        return c


class ConditionEditor(QWidget):
    """Birden çok koşul + VE/VEYA seçimi."""

    changed = Signal()

    def __init__(self, df, conditions=None, mode="and", preset_column=None, parent=None):
        super().__init__(parent)
        self.df = df
        self.rows: list[ConditionRow] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        mode_row = QHBoxLayout()
        self.r_and = QRadioButton("Tüm koşullar sağlansın (VE)")
        self.r_or = QRadioButton("Koşullardan biri yeterli (VEYA)")
        (self.r_or if mode == "or" else self.r_and).setChecked(True)
        self.r_and.toggled.connect(lambda *_: self.changed.emit())
        mode_row.addWidget(self.r_and)
        mode_row.addWidget(self.r_or)
        mode_row.addStretch()
        lay.addLayout(mode_row)
        self.box = QVBoxLayout()
        lay.addLayout(self.box)
        add = QPushButton("+ Koşul ekle")
        add.clicked.connect(lambda: self.add_row())
        h = QHBoxLayout()
        h.addWidget(add)
        h.addStretch()
        lay.addLayout(h)
        conds = [c for c in (conditions or []) if c.get("op") != "in_list"]
        for c in conds or [{"column": preset_column}]:
            self.add_row(c)

    def add_row(self, cond=None):
        r = ConditionRow(self.df, cond)
        r.removed.connect(self._remove)
        r.changed.connect(self.changed.emit)
        self.rows.append(r)
        self.box.addWidget(r)
        self.changed.emit()

    def _remove(self, row):
        if len(self.rows) == 1:
            return
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self.changed.emit()

    def conditions(self):
        out = [r.condition() for r in self.rows]
        for c in out:
            if c["op"] not in ops.NO_VALUE_OPS and not str(c.get("value", "")).strip():
                raise ShiftFlowError(f"'{c['column']}' koşulu için bir değer girin "
                                     "(boş hücreleri seçmek için 'boştur' koşulunu kullanın).")
        return out

    def mode(self):
        return "or" if self.r_or.isChecked() else "and"


def status_label() -> QLabel:
    lab = QLabel()
    lab.setWordWrap(True)
    lab.setObjectName("dialogStatus")
    return lab


def set_status(label: QLabel, text: str, kind="ok"):
    colors = {"ok": "#1d6b3a", "warn": "#8a5a00", "err": "#a32020"}
    label.setStyleSheet(f"color: {colors.get(kind, '#333')};")
    label.setText(text)
