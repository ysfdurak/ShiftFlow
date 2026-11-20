"""Referans tablolar, arşiv, vardiyalar, dönem seçici, grafik, rapor ayarları ve mail önizleme."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..engine import archive as arc_mod
from ..engine import mailer
from ..engine import periods as pr
from ..engine.autorun import DEFAULT_FILE_NAME, format_file_name
from ..engine.errors import ShiftFlowError
from ..engine.excel_out import CHART_TYPES, template_warnings
from .common import ColumnChecklist, PreviewTable, ask, busy, fmt_n, info, set_status, show_error, status_label


def _buttons(dlg, ok="Kaydet", cancel="Vazgeç"):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok)
    bb.button(QDialogButtonBox.Cancel).setText(cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


def _help(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setObjectName("dialogHelp")
    return lab


# =========================================================================== referans tablolar
class ReferenceTablesDialog(QDialog):
    """Bir kez alınıp saklanan sabit tablolar (lokasyon-bölge, ürün-kategori, personel-ekip…).

    Sonuç: `self.chosen` → iş akışına eklenecek referans tablonun meta bilgisi (veya None).
    """

    def __init__(self, library, parent=None, get_frame=None, allow_add=True):
        super().__init__(parent)
        self.library, self.get_frame = library, get_frame
        self.chosen = None
        self.setWindowTitle("Referans tablolar")
        self.resize(1000, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(_help(
            "Referans tablolar, raporla her gün gelmeyen ama eşleştirmede kullanılan sabit verilerdir "
            "(lokasyon → bölge, ürün → kategori, personel → ekip). Bir kez kaydedilir; iş akışları her çalıştırmada "
            "buradan otomatik okur. İçerik değişince 'İçeriği yenile' ile güncellenir; bağlı iş akışları bir sonraki "
            "çalıştırmada yeni içeriği kullanır. Bu tablolar yalnızca bu bilgisayarda saklanır."))
        h = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        left.addWidget(self.list)
        row = QHBoxLayout()
        b_new = QPushButton("Yeni…")
        b_new.clicked.connect(lambda: self.load(None))
        b_upd = QPushButton("İçeriği yenile…")
        b_upd.clicked.connect(lambda: self.load(self.selected()))
        b_del = QPushButton("Sil")
        b_del.clicked.connect(self.delete)
        for b in (b_new, b_upd, b_del):
            row.addWidget(b)
        left.addLayout(row)
        h.addLayout(left, 1)
        right = QVBoxLayout()
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        right.addWidget(self.meta)
        self.preview = PreviewTable(rows=200)
        right.addWidget(self.preview, 1)
        h.addLayout(right, 2)
        lay.addLayout(h, 1)
        bb = QHBoxLayout()
        bb.addStretch()
        self.b_add = QPushButton("İş akışına ekle")
        self.b_add.clicked.connect(self._add)
        if allow_add:
            bb.addWidget(self.b_add)
        b_close = QPushButton("Kapat")
        b_close.clicked.connect(self.reject)
        bb.addWidget(b_close)
        lay.addLayout(bb)
        self.refresh()

    def refresh(self, select=None):
        self.list.clear()
        for m in self.library.list_references():
            it = QListWidgetItem(f"{m['name']}\n   {fmt_n(m['rows'])} satır · {m['updated'][:16].replace('T', ' ')}")
            it.setData(Qt.UserRole, m["id"])
            self.list.addItem(it)
            if m["id"] == select:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.meta.setText("Henüz referans tablo yok. 'Yeni…' ile dosyadan, panodan veya açık Excel'den ekleyin.")
            self.preview.set_frame(None)
        self.b_add.setEnabled(self.list.count() > 0)

    def selected(self):
        it = self.list.currentItem()
        return self.library.reference_meta(it.data(Qt.UserRole)) if it else None

    def _show(self, *_):
        m = self.selected()
        if not m:
            return
        cols = ", ".join(c["name"] for c in m["columns"])
        self.meta.setText(f"<b>{m['name']}</b><br>{m.get('note') or ''}<br>Sütunlar: {cols}<br>"
                          f"Son güncelleme: {m['updated'].replace('T', ' ')}")
        self.preview.set_frame(self.library.reference_df(m["id"]))

    def load(self, meta):
        if self.get_frame is None:
            return
        got = self.get_frame(meta["name"] if meta else "")
        if not got:
            return
        name, df, note = got
        try:
            if meta:
                old = {c["name"] for c in meta["columns"]}
                lost = old - {str(c) for c in df.columns}
                if lost and not ask(self, "Yeni içerikte şu sütunlar yok: " + ", ".join(sorted(lost))
                                    + "\n\nBu tabloyu kullanan eşleştirmeler hata verebilir. Yine de güncellensin mi?"):
                    return
                m = self.library.save_reference(meta["name"], df, note or meta.get("note", ""), rid=meta["id"])
            else:
                m = self.library.save_reference(name, df, note)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        self.refresh(m["id"])

    def delete(self):
        m = self.selected()
        if m and ask(self, f"'{m['name']}' referans tablosu silinsin mi?\n\nBu tabloyu kullanan iş akışları "
                           "çalıştırılırken 'referans tablo yok' hatası verir.\n\nSilinen kayıt 30 gün çöp kutusunda durur (Rapor → Çöp kutusu) ve geri yüklenebilir."):
            self.library.delete_reference(m["id"])
            self.refresh()

    def _add(self):
        self.chosen = self.selected()
        if self.chosen:
            self.accept()


# =========================================================================== arşiv
class ArchiveDialog(QDialog):
    """Arşiv kümeleri ve dönemleri; arşivden kaynak ekleme.

    Sonuç: `self.source_spec` → {"set":..., "range": {...}} (veya None).
    """

    def __init__(self, archive, parent=None, allow_add=True, period=None, shifts=None):
        super().__init__(parent)
        self.archive, self.period, self.shifts = archive, period, shifts or pr.DEFAULT_SHIFTS
        self.source_spec = None
        self.setWindowTitle("Rapor arşivi")
        self.resize(1000, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(_help(
            "Arşiv açık olan iş akışlarında her 'Rapor oluştur' sonucu dönemiyle (tarih + vardiya) buraya yazılır. "
            "Aynı dönem yeniden oluşturulursa eski kayıt değiştirilir. Arşivden bir aralığı (önceki vardiya, son 7 gün…) "
            "iş akışına kaynak olarak ekleyip karşılaştırma ve geriye dönük raporlar hazırlayabilirsiniz."))
        h = QHBoxLayout()
        self.sets = QListWidget()
        self.sets.currentItemChanged.connect(self._show)
        h.addWidget(self.sets, 1)
        right = QVBoxLayout()
        self.periods = QTableWidget(0, 4)
        self.periods.setHorizontalHeaderLabels(["Tarih", "Vardiya", "Satır", "Yazılma"])
        self.periods.verticalHeader().setVisible(False)
        self.periods.setSelectionBehavior(QTableWidget.SelectRows)
        self.periods.setEditTriggers(QTableWidget.NoEditTriggers)
        self.periods.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        right.addWidget(self.periods, 1)
        prow = QHBoxLayout()
        b_delp = QPushButton("Seçili dönemi sil")
        b_delp.clicked.connect(self.delete_period)
        b_dels = QPushButton("Kümeyi sil")
        b_dels.clicked.connect(self.delete_set)
        prow.addWidget(b_delp)
        prow.addWidget(b_dels)
        prow.addStretch()
        right.addLayout(prow)
        g = QGroupBox("İş akışına kaynak olarak ekle")
        gf = QFormLayout(g)
        self.range = QComboBox()
        for k, v in arc_mod.RANGE_TYPES.items():
            self.range.addItem(v, k)
        self.days = QSpinBox()
        self.days.setRange(1, 366)
        self.days.setValue(7)
        self.d_from, self.d_to = QDateEdit(QDate.currentDate().addDays(-7)), QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
        dr = QHBoxLayout()
        dr.addWidget(self.d_from)
        dr.addWidget(QLabel("–"))
        dr.addWidget(self.d_to)
        gf.addRow("Aralık:", self.range)
        gf.addRow("Gün sayısı:", self.days)
        gf.addRow("Tarihler:", dr)
        self.range_hint = QLabel()
        self.range_hint.setObjectName("dialogHelp")
        self.range_hint.setWordWrap(True)
        gf.addRow("", self.range_hint)
        self.range.currentIndexChanged.connect(self._range_ui)
        right.addWidget(g)
        h.addLayout(right, 2)
        lay.addLayout(h, 1)
        bb = QHBoxLayout()
        bb.addStretch()
        self.b_add = QPushButton("Kaynak olarak ekle")
        self.b_add.clicked.connect(self._add)
        if allow_add:
            bb.addWidget(self.b_add)
        else:
            g.hide()
        b_close = QPushButton("Kapat")
        b_close.clicked.connect(self.reject)
        bb.addWidget(b_close)
        lay.addLayout(bb)
        self._range_ui()
        self.refresh()

    def _range_ui(self):
        t = self.range.currentData()
        self.days.setEnabled(t == "last_days")
        self.d_from.setEnabled(t == "date_range")
        self.d_to.setEnabled(t == "date_range")
        hints = {"previous_shift": "Rapor oluşturulurken seçilen vardiyadan bir önceki vardiya.",
                 "same_shift_previous_day": "Bir önceki günün aynı vardiyası.",
                 "previous_day": "Seçilen günden bir önceki günün tüm vardiyaları.",
                 "last_days": "Seçilen günden önceki N gün (seçilen gün hariç).",
                 "this_month": "Ayın ilk gününden seçilen güne kadar.",
                 "date_range": "Sabit tarih aralığı.", "all": "Arşivin tamamı."}
        txt = hints.get(t, "")
        if self.period is not None and t in ("previous_shift", "same_shift_previous_day"):
            p = pr.previous(self.period, self.shifts) if t == "previous_shift" else pr.same_shift_previous_day(self.period, self.shifts)
            txt += f" Şu anki seçime göre: {p.label}"
        self.range_hint.setText(txt)

    def refresh(self):
        self.sets.clear()
        for m in self.archive.sets():
            span = f"{m['first']} – {m['last']}" if m["first"] else "boş"
            it = QListWidgetItem(f"{m['name']}\n   {m['periods']} dönem · {fmt_n(m['rows'])} satır · {span}")
            it.setData(Qt.UserRole, m["name"])
            self.sets.addItem(it)
        if self.sets.count():
            self.sets.setCurrentRow(0)
        else:
            self.periods.setRowCount(0)
        self.b_add.setEnabled(self.sets.count() > 0)

    def current_set(self):
        it = self.sets.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _show(self, *_):
        name = self.current_set()
        rows = self.archive.periods(name) if name else []
        self.periods.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([date.fromisoformat(r["date"]).strftime("%d.%m.%Y"), r["shift"], fmt_n(r["rows"]),
                                   r["written"].replace("T", " ")]):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, r["key"])
                self.periods.setItem(i, j, it)

    def delete_period(self):
        name = self.current_set()
        r = self.periods.currentRow()
        if not name or r < 0:
            return
        key = self.periods.item(r, 0).data(Qt.UserRole)
        if ask(self, f"{self.periods.item(r, 0).text()} {self.periods.item(r, 1).text()} dönemi arşivden silinsin mi?\n\nSilinen kayıt 30 gün çöp kutusunda durur (Rapor → Çöp kutusu) ve geri yüklenebilir."):
            self.archive.delete_period(name, key)
            self._show()

    def delete_set(self):
        name = self.current_set()
        if name and ask(self, f"'{name}' arşiv kümesinin TÜM dönemleri silinsin mi?\n\nSilinen kayıt 30 gün çöp kutusunda durur (Rapor → Çöp kutusu) ve geri yüklenebilir."):
            self.archive.delete_set(name)
            self.refresh()

    def range_spec(self):
        t = self.range.currentData()
        rng = {"type": t}
        if t == "last_days":
            rng["days"] = self.days.value()
        if t == "date_range":
            rng["from"] = self.d_from.date().toPython().isoformat()
            rng["to"] = self.d_to.date().toPython().isoformat()
        return rng

    def _add(self):
        name = self.current_set()
        if name:
            self.source_spec = {"set": name, "range": self.range_spec()}
            self.accept()


# =========================================================================== vardiyalar
class ShiftSettingsDialog(QDialog):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Vardiya tanımları")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(_help(
            "Vardiyalar bir kez tanımlanır. Gece yarısını geçen vardiya (22:00–06:00) desteklenir; vardiyanın tarihi "
            "başladığı gündür. 'Rapor oluştur' tarih ve vardiyayı sizin seçiminize göre kullanır; varsayılan değer "
            "saatten hesaplanır."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Vardiya adı", "Başlangıç", "Bitiş"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for s in library.get_setting("shifts", pr.DEFAULT_SHIFTS):
            self._row(s)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        b_add, b_del = QPushButton("+ Vardiya"), QPushButton("Seçiliyi sil")
        b_add.clicked.connect(lambda: self._row({"name": "", "start": "", "end": ""}))
        b_del.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch()
        lay.addLayout(row)
        f = QFormLayout()
        self.grace = QSpinBox()
        self.grace.setRange(0, 480)
        self.grace.setSuffix(" dakika")
        self.grace.setValue(int(library.get_setting("shift_grace_minutes", pr.DEFAULT_GRACE_MINUTES)))
        f.addRow("Varsayılan dönem:", QLabel("Vardiya başladıktan sonraki"))
        f.addRow("", self.grace)
        f.addRow("", _help("…içinde rapor oluşturulursa varsayılan olarak biten (önceki) vardiya seçilir. "
                           "Örn. 120 dakika: 16:40'ta varsayılan 08:00–16:00 vardiyasıdır."))
        lay.addLayout(f)
        self.status = status_label()
        lay.addWidget(self.status)
        bb = _buttons(self)
        bb.accepted.disconnect()
        bb.accepted.connect(self._save)
        lay.addWidget(bb)

    def _row(self, s):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for j, k in enumerate(("name", "start", "end")):
            self.table.setItem(r, j, QTableWidgetItem(s.get(k, "")))

    def shifts(self):
        out = []
        for r in range(self.table.rowCount()):
            vals = [(self.table.item(r, j).text() if self.table.item(r, j) else "").strip() for j in range(3)]
            if any(vals):
                out.append({"name": vals[0], "start": vals[1], "end": vals[2]})
        return out

    def _save(self):
        try:
            shifts = pr.validate_shifts(self.shifts())
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return
        self.library.set_setting("shifts", shifts)
        self.library.set_setting("shift_grace_minutes", self.grace.value())
        self.accept()


# =========================================================================== dönem seçici
class PeriodBar(QWidget):
    """Araç çubuğundaki tarih + vardiya seçimi. Varsayılan: saatten otomatik."""

    changed = Signal(object)

    def __init__(self, get_shifts, get_auto, parent=None):
        super().__init__(parent)
        self.get_shifts, self.get_auto = get_shifts, get_auto
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(QLabel("Dönem:"))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy")
        lay.addWidget(self.date)
        self.shift = QComboBox()
        self.shift.setMinimumContentsLength(17)
        self.shift.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        lay.addWidget(self.shift)
        self.auto_label = QLabel()
        self.auto_label.setObjectName("dialogHelp")
        lay.addWidget(self.auto_label)
        self.b_auto = QPushButton("Otomatik")
        self.b_auto.setToolTip("Saate göre varsayılan dönemi seç")
        self.b_auto.clicked.connect(self.set_auto)
        lay.addWidget(self.b_auto)
        self._auto = True
        self._block = False
        self.date.dateChanged.connect(self._user_changed)
        self.shift.currentIndexChanged.connect(self._user_changed)
        self.reload_shifts()
        self.set_auto()

    def reload_shifts(self):
        cur = self.shift.currentText()
        self._block = True
        self.shift.clear()
        for s in self.get_shifts():
            self.shift.addItem(f"{s['name']} ({s['start']}–{s['end']})", s["name"])
        self.shift.addItem(pr.WHOLE_DAY, pr.WHOLE_DAY)
        i = self.shift.findText(cur)
        if i >= 0:
            self.shift.setCurrentIndex(i)
        self._block = False

    def set_auto(self):
        p = self.get_auto()
        self._block = True
        self.date.setDate(QDate(p.date.year, p.date.month, p.date.day))
        i = self.shift.findData(p.shift_label)
        self.shift.setCurrentIndex(max(i, 0))
        self._block = False
        self._auto = True
        self.auto_label.setText("(otomatik)")
        self.changed.emit(self.period())

    def _user_changed(self, *_):
        if self._block:
            return
        self._auto = False
        self.auto_label.setText("(elle seçildi)")
        self.changed.emit(self.period())

    def period(self) -> pr.Period:
        d = self.date.date().toPython()
        p = pr.make_period(d, self.shift.currentData(), self.get_shifts())
        p.auto = self._auto
        return p

    def set_period(self, d: date, shift: str | None):
        self._block = True
        self.date.setDate(QDate(d.year, d.month, d.day))
        i = self.shift.findData(shift or pr.WHOLE_DAY)
        if i >= 0:
            self.shift.setCurrentIndex(i)
        self._block = False
        self._user_changed()


# =========================================================================== grafik
class ChartDialog(QDialog):
    def __init__(self, df, spec=None, parent=None, sheet=""):
        super().__init__(parent)
        spec = dict(spec or {})
        self.setWindowTitle(f"Grafik — {sheet}")
        self.resize(520, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(_help("Excel çıktısında bu sayfaya gerçek bir Excel grafiği eklenir. 'Genel Toplam' satır ve "
                            "sütunları grafiğe katılmaz. Değer sütunu seçmezseniz tüm sayısal sütunlar kullanılır; "
                            "pivotta sütun adları her gün değişebiliyorsa bu seçeneği kullanın."))
        f = QFormLayout()
        self.enabled = QCheckBox("Bu sayfaya grafik ekle")
        self.enabled.setChecked(bool(spec) or True)
        self.type = QComboBox()
        for k, v in CHART_TYPES.items():
            self.type.addItem(v, k)
        self.type.setCurrentIndex(max(0, self.type.findData(spec.get("type", "col"))))
        cols = [str(c) for c in df.columns]
        self.category = QComboBox()
        self.category.addItems(cols)
        if spec.get("category") in cols:
            self.category.setCurrentText(spec["category"])
        self.title = QLineEdit(spec.get("title", ""))
        self.title.setPlaceholderText("boş: otomatik")
        self.position = QComboBox()
        self.position.addItem("Tablonun sağında", "right")
        self.position.addItem("Tablonun altında", "below")
        self.position.setCurrentIndex(0 if spec.get("position", "right") == "right" else 1)
        f.addRow("", self.enabled)
        f.addRow("Grafik türü:", self.type)
        f.addRow("Kategori (eksen):", self.category)
        f.addRow("Başlık:", self.title)
        f.addRow("Konum:", self.position)
        lay.addLayout(f)
        nums = [c for c in cols if str(df[c].dtype) not in ("object", "str", "string") and c in cols]
        lay.addWidget(QLabel("Değer sütunları (boş = tüm sayısal sütunlar):"))
        self.values = ColumnChecklist(nums, spec.get("values") or [])
        lay.addWidget(self.values, 1)
        lay.addWidget(_buttons(self, "Tamam"))

    def spec(self):
        if not self.enabled.isChecked():
            return None
        return {"type": self.type.currentData(), "category": self.category.currentText(),
                "values": self.values.checked(), "title": self.title.text().strip(),
                "position": self.position.currentData()}


# =========================================================================== rapor ayarları
class ReportSettingsDialog(QDialog):
    """Çıktı, arşiv, şablon ve mail ayarları (iş akışında saklanır)."""

    def __init__(self, workflow, parent=None, datasets=None, shifts=None):
        super().__init__(parent)
        self.wf = workflow
        rs = workflow.run_settings
        self.shifts = shifts or pr.DEFAULT_SHIFTS
        self.datasets = datasets or list(workflow.datasets)
        self.setWindowTitle("Rapor ayarları")
        self.resize(780, 620)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # --- Çıktı
        w = QWidget()
        f = QFormLayout(w)
        row = QHBoxLayout()
        self.dir = QLineEdit(rs.get("output_dir") or os.path.join(os.path.expanduser("~"), "Documents", "ShiftFlow Raporları"))
        b = QPushButton("Gözat…")
        b.clicked.connect(self._browse)
        row.addWidget(self.dir, 1)
        row.addWidget(b)
        f.addRow("Çıktı klasörü:", row)
        self.name = QLineEdit(rs.get("file_name") or DEFAULT_FILE_NAME)
        self.name.textChanged.connect(self._preview)
        f.addRow("Dosya adı:", self.name)
        self.example = QLabel()
        self.example.setObjectName("dialogHelp")
        f.addRow("", self.example)
        self.open_after = QCheckBox("Rapor oluşunca dosyayı aç")
        self.open_after.setChecked(rs.get("open_after", True))
        f.addRow("", self.open_after)
        self.period_mode = QComboBox()
        self.period_mode.addItem("Vardiya", "shift")
        self.period_mode.addItem("Gün", "day")
        self.period_mode.setCurrentIndex(0 if rs.get("period_mode", "shift") == "shift" else 1)
        f.addRow("Varsayılan dönem türü:", self.period_mode)
        f.addRow("", _help("Dosya adında: {akis} iş akışı adı, {tarih} seçili dönemin tarihi (2026-11-10), "
                           "{vardiya} seçili vardiya, {saat} oluşturma saati, {gun} {ay} {yil}. "
                           "Aynı adlı dosya varsa üzerine yazılmaz; sonuna (2), (3) eklenir."))
        self.tabs.addTab(w, "Çıktı")

        # --- Arşiv
        a = rs.get("archive") or {}
        w = QWidget()
        al = QVBoxLayout(w)
        self.arc_on = QCheckBox("Her 'Rapor oluştur' sonucunu arşive yaz")
        self.arc_on.setChecked(bool(a.get("enabled")))
        al.addWidget(self.arc_on)
        al.addWidget(_help("Arşivlenen veri kümeleri dönemiyle (tarih + vardiya) saklanır. Arşiv kümesi adı değişmezse "
                           "iş akışının adı değişse de geçmiş korunur. Hiç seçim yapmazsanız çıktı sayfaları arşivlenir."))
        self.arc_table = QTableWidget(len(self.datasets), 2)
        self.arc_table.setHorizontalHeaderLabels(["Veri kümesi", "Arşiv kümesi adı"])
        self.arc_table.verticalHeader().setVisible(False)
        self.arc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        sets = a.get("sets") or {}
        base = workflow.name or "İş akışı"
        for i, n in enumerate(self.datasets):
            it = QTableWidgetItem(n)
            it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            it.setCheckState(Qt.Checked if n in sets else Qt.Unchecked)
            self.arc_table.setItem(i, 0, it)
            self.arc_table.setItem(i, 1, QTableWidgetItem(sets.get(n, f"{base} / {n}")))
        self.arc_table.setColumnWidth(0, 240)
        al.addWidget(self.arc_table, 1)
        self.tabs.addTab(w, "Arşiv")

        # --- Şablon
        t = rs.get("template") or {}
        w = QWidget()
        tl = QVBoxLayout(w)
        tl.addWidget(_help("Kendi Excel şablonunuzu (başlık, renkler, sütun genişlikleri, formüllü özet hücreleri) seçin. "
                           "Çıktı sayfası şablondaki aynı adlı sayfaya, 'Excel'e aktar' penceresinde belirtilen başlangıç "
                           "hücresinden itibaren yazılır. Şablondaki formüller korunur ve Excel açılınca yeni veriyle "
                           "hesaplanır. Aşağıdaki hücrelere {tarih}, {vardiya}, {donem}, {akis}, {olusturma} yazılabilir."))
        tr = QHBoxLayout()
        self.tpl = QLineEdit(t.get("path", ""))
        self.tpl.setPlaceholderText("şablon kullanılmıyor")
        b1, b2 = QPushButton("Seç…"), QPushButton("Kaldır")
        b1.clicked.connect(self._pick_template)
        b2.clicked.connect(lambda: self.tpl.setText(""))
        tr.addWidget(self.tpl, 1)
        tr.addWidget(b1)
        tr.addWidget(b2)
        tl.addLayout(tr)
        self.tpl_warn = QLabel()
        self.tpl_warn.setWordWrap(True)
        self.tpl_warn.setStyleSheet("color:#8a5a00")
        tl.addWidget(self.tpl_warn)
        self.cells = QTableWidget(0, 3)
        self.cells.setHorizontalHeaderLabels(["Sayfa", "Hücre", "Değer"])
        self.cells.verticalHeader().setVisible(False)
        self.cells.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for c in t.get("cells", []):
            self._cell_row(c)
        tl.addWidget(self.cells, 1)
        cr = QHBoxLayout()
        b3, b4 = QPushButton("+ Hücre"), QPushButton("Seçiliyi sil")
        b3.clicked.connect(lambda: self._cell_row({"sheet": "", "cell": "A1", "value": "{vardiya} – {tarih}"}))
        b4.clicked.connect(lambda: self.cells.removeRow(self.cells.currentRow()) if self.cells.currentRow() >= 0 else None)
        cr.addWidget(b3)
        cr.addWidget(b4)
        cr.addStretch()
        tl.addLayout(cr)
        self.tpl.textChanged.connect(self._tpl_check)
        self.tabs.addTab(w, "Şablon")

        # --- Mail
        m = rs.get("mail") or {}
        w = QWidget()
        ml = QVBoxLayout(w)
        self.mail_on = QCheckBox("Rapor oluşunca mail taslağı hazırla")
        self.mail_on.setChecked(bool(m.get("enabled")))
        ml.addWidget(self.mail_on)
        ml.addWidget(_help("Mail KENDİLİĞİNDEN GÖNDERİLMEZ. Rapor oluşunca önizleme açılır; Outlook'ta taslak olarak "
                           "açabilir veya onaylayarak gönderebilirsiniz. Adresleri ';' ile ayırın."))
        mf = QFormLayout()
        self.to = QLineEdit(m.get("to", ""))
        self.to.setPlaceholderText("vardiya.amiri@firma.com; depo.mudur@firma.com")
        self.cc = QLineEdit(m.get("cc", ""))
        self.bcc = QLineEdit(m.get("bcc", ""))
        self.subject = QLineEdit(m.get("subject") or mailer.DEFAULT_SUBJECT)
        self.intro = QPlainTextEdit(m.get("intro") or mailer.DEFAULT_INTRO)
        self.intro.setMaximumHeight(90)
        self.summary = QComboBox()
        self.summary.addItem("(tablo ekleme)", "")
        for n in self.datasets:
            self.summary.addItem(n, n)
        self.summary.setCurrentIndex(max(0, self.summary.findData(m.get("summary_dataset", ""))))
        self.summary_rows = QSpinBox()
        self.summary_rows.setRange(1, 500)
        self.summary_rows.setValue(int(m.get("summary_rows", 30)))
        self.attach = QCheckBox("Excel çıktısını ekle")
        self.attach.setChecked(m.get("attach", True))
        self.notes = QCheckBox("Kaynak bilgilerini (rapor, satır sayısı) maile ekle")
        self.notes.setChecked(m.get("include_notes", False))
        mf.addRow("Kime:", self.to)
        mf.addRow("Bilgi:", self.cc)
        mf.addRow("Gizli:", self.bcc)
        mf.addRow("Konu:", self.subject)
        mf.addRow("Metin:", self.intro)
        sr = QHBoxLayout()
        sr.addWidget(self.summary, 1)
        sr.addWidget(QLabel("en fazla"))
        sr.addWidget(self.summary_rows)
        sr.addWidget(QLabel("satır"))
        mf.addRow("Mail içine tablo:", sr)
        mf.addRow("", self.attach)
        mf.addRow("", self.notes)
        ml.addLayout(mf)
        ml.addWidget(QLabel("Vardiyaya göre EK alıcılar (isteğe bağlı):"))
        per = m.get("per_shift") or {}
        self.per_shift = QTableWidget(len(self.shifts), 3)
        self.per_shift.setHorizontalHeaderLabels(["Vardiya", "Ek Kime", "Ek Bilgi"])
        self.per_shift.verticalHeader().setVisible(False)
        self.per_shift.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.per_shift.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for i, s in enumerate(self.shifts):
            it = QTableWidgetItem(s["name"])
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.per_shift.setItem(i, 0, it)
            self.per_shift.setItem(i, 1, QTableWidgetItem(per.get(s["name"], {}).get("to", "")))
            self.per_shift.setItem(i, 2, QTableWidgetItem(per.get(s["name"], {}).get("cc", "")))
        self.per_shift.setMaximumHeight(130)
        ml.addWidget(self.per_shift)
        self.tabs.addTab(w, "Mail")

        self.status = status_label()
        lay.addWidget(self.status)
        bb = _buttons(self)
        bb.accepted.disconnect()
        bb.accepted.connect(self._save)
        lay.addWidget(bb)
        self._preview()
        self._tpl_check()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Çıktı klasörü", self.dir.text())
        if d:
            self.dir.setText(d)

    def _preview(self):
        p = pr.make_period(date.today(), self.shifts[0]["name"], self.shifts) if self.shifts else None
        self.example.setText("Örnek: " + format_file_name(self.name.text() or DEFAULT_FILE_NAME, self.wf.name or "Rapor",
                                                          datetime.now(), p) + ".xlsx")

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Excel şablonu", self.tpl.text() or os.path.expanduser("~"),
                                              "Excel (*.xlsx)")
        if path:
            self.tpl.setText(path)

    def _tpl_check(self):
        p = self.tpl.text().strip()
        self.tpl_warn.setText(" ".join(template_warnings(p)) if p and os.path.exists(p) else
                              ("Dosya bulunamadı." if p else ""))

    def _cell_row(self, c):
        r = self.cells.rowCount()
        self.cells.insertRow(r)
        for j, k in enumerate(("sheet", "cell", "value")):
            self.cells.setItem(r, j, QTableWidgetItem(str(c.get(k, ""))))

    def _save(self):
        addrs = mailer.split_addresses(self.to.text()) + mailer.split_addresses(self.cc.text()) + \
            mailer.split_addresses(self.bcc.text())
        for r in range(self.per_shift.rowCount()):
            for j in (1, 2):
                addrs += mailer.split_addresses(self.per_shift.item(r, j).text() if self.per_shift.item(r, j) else "")
        bad = mailer.invalid_addresses(addrs)
        if bad:
            self.tabs.setCurrentIndex(3)
            set_status(self.status, "✖ Geçersiz e-posta adresi: " + ", ".join(bad), "err")
            return
        if self.mail_on.isChecked() and not mailer.split_addresses(self.to.text()):
            self.tabs.setCurrentIndex(3)
            set_status(self.status, "✖ Mail açıksa en az bir 'Kime' adresi girin.", "err")
            return
        self.accept()

    def settings_dict(self) -> dict:
        rs = dict(self.wf.run_settings)
        rs.update({"output_dir": self.dir.text().strip(), "file_name": self.name.text().strip() or DEFAULT_FILE_NAME,
                   "open_after": self.open_after.isChecked(), "period_mode": self.period_mode.currentData()})
        sets = {}
        for i in range(self.arc_table.rowCount()):
            if self.arc_table.item(i, 0).checkState() == Qt.Checked:
                sets[self.arc_table.item(i, 0).text()] = self.arc_table.item(i, 1).text().strip()
        rs["archive"] = {"enabled": self.arc_on.isChecked(), "sets": sets}
        cells = []
        for r in range(self.cells.rowCount()):
            vals = [(self.cells.item(r, j).text() if self.cells.item(r, j) else "").strip() for j in range(3)]
            if vals[0] and vals[1]:
                cells.append({"sheet": vals[0], "cell": vals[1], "value": vals[2]})
        rs["template"] = {"path": self.tpl.text().strip(), "cells": cells} if self.tpl.text().strip() else {}
        per = {}
        for r in range(self.per_shift.rowCount()):
            to = self.per_shift.item(r, 1).text().strip() if self.per_shift.item(r, 1) else ""
            cc = self.per_shift.item(r, 2).text().strip() if self.per_shift.item(r, 2) else ""
            if to or cc:
                per[self.per_shift.item(r, 0).text()] = {"to": to, "cc": cc}
        rs["mail"] = {"enabled": self.mail_on.isChecked(), "to": self.to.text().strip(), "cc": self.cc.text().strip(),
                      "bcc": self.bcc.text().strip(), "subject": self.subject.text().strip(),
                      "intro": self.intro.toPlainText(), "summary_dataset": self.summary.currentData(),
                      "summary_rows": self.summary_rows.value(), "attach": self.attach.isChecked(),
                      "include_notes": self.notes.isChecked(), "per_shift": per}
        return rs


# =========================================================================== mail önizleme
class MailPreviewDialog(QDialog):
    """Mail önizleme. Gönderim yalnızca 'Gönder' + onay ile yapılır."""

    def __init__(self, draft: mailer.MailDraft, outlook: mailer.OutlookMailer, parent=None):
        super().__init__(parent)
        self.draft, self.outlook = draft, outlook
        self.result_action = None
        self.setWindowTitle("Mail önizleme")
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.to = QLineEdit("; ".join(draft.to))
        self.cc = QLineEdit("; ".join(draft.cc))
        self.subject = QLineEdit(draft.subject)
        f.addRow("Kime:", self.to)
        f.addRow("Bilgi:", self.cc)
        f.addRow("Konu:", self.subject)
        att = ", ".join(os.path.basename(a) for a in draft.attachments) or "yok"
        f.addRow("Ek:", QLabel(att))
        lay.addLayout(f)
        self.body = QTextBrowser()
        self.body.setHtml(draft.html)
        lay.addWidget(self.body, 1)
        ok, msg = outlook.available()
        note = "Mail sizin onayınız olmadan gönderilmez." + ("" if ok else f" {msg} Taslağı .eml dosyası olarak açabilirsiniz.")
        lay.addWidget(_help(note))
        self.status = status_label()
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.b_draft = QPushButton("Outlook'ta taslak olarak aç")
        self.b_send = QPushButton("Gönder…")
        self.b_eml = QPushButton(".eml olarak aç")
        b_close = QPushButton("Göndermeden kapat")
        self.b_draft.setEnabled(ok)
        self.b_send.setEnabled(ok)
        self.b_draft.clicked.connect(self.open_draft)
        self.b_send.clicked.connect(self.send)
        self.b_eml.clicked.connect(self.open_eml)
        b_close.clicked.connect(self.reject)
        for b in (self.b_draft, self.b_send, self.b_eml):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(b_close)
        lay.addLayout(row)

    def current(self) -> mailer.MailDraft:
        d = mailer.MailDraft(**{**self.draft.__dict__})
        d.to = mailer.split_addresses(self.to.text())
        d.cc = mailer.split_addresses(self.cc.text())
        d.subject = self.subject.text().strip()
        d.validate()
        return d

    def _do(self, fn, action):
        try:
            with busy():
                fn(self.current())
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return False
        self.result_action = action
        self.accept()
        return True

    def open_draft(self):
        self._do(self.outlook.display, "draft")

    def send(self):
        try:
            d = self.current()
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return
        n = len(d.to) + len(d.cc) + len(d.bcc)
        if ask(self, f"Mail şimdi {n} alıcıya gönderilecek:\n\n" + "\n".join(d.to + d.cc) + "\n\nGönderilsin mi?",
               "Gönderimi onayla"):
            self._do(self.outlook.send, "sent")

    def open_eml(self):
        def fn(d):
            folder = os.path.dirname(d.attachments[0]) if d.attachments else tempfile.gettempdir()
            self.eml_path = mailer.save_eml(d, os.path.join(folder, "mail_taslagi"))
            if sys.platform == "win32":
                os.startfile(self.eml_path)  # type: ignore[attr-defined]
        self._do(fn, "eml")



class ParametersDialog(QDialog):
    """İş akışı parametreleri: hedef oranı, mola süresi gibi sabitler. Formülde {Ad} ile kullanılır."""

    def __init__(self, params: dict, parent=None, usage: dict | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHeaderView, QPushButton, QTableWidget, QTableWidgetItem
        self.setWindowTitle("Parametreler")
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        h = QLabel("Excel'de bir hücreye yazıp formüllerde $H$1 diye kullandığınız sabitler (hedef oranı, kur, mola "
                   "süresi…) burada tutulur. Formülde süslü parantezle kullanılır: [Toplanan] / [Hedef] >= "
                   "{Hedef Oran}. Değeri değiştirince tüm formüller yeniden hesaplanır.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Ad", "Değer", "Kullanıldığı adımlar"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._Item = QTableWidgetItem
        usage = usage or {}
        for k, v in params.items():
            self._add(k, v, usage.get(k, ""))
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_add = QPushButton("Parametre ekle")
        b_add.clicked.connect(lambda: self._add("", "", ""))
        b_del = QPushButton("Seçiliyi sil")
        b_del.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add(self, name, value, used):
        from PySide6.QtCore import Qt
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, self._Item(str(name)))
        v = value
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        self.table.setItem(r, 1, self._Item(str(v).replace(".", ",") if isinstance(v, float) else str(v)))
        u = self._Item(used)
        u.setFlags(u.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, 2, u)
        if not name:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(self.table.item(r, 0))

    def values(self) -> dict:
        out = {}
        for r in range(self.table.rowCount()):
            k = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            v = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            if k:
                out[k] = v
        return out


class OutputFormatDialog(QDialog):
    """Excel çıktısı sayfa biçimi: toplam satırı ve koşullu renk kuralları (Excel'in kendi koşullu biçimi)."""

    def __init__(self, df, spec=None, parent=None, sheet=""):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QComboBox, QHeaderView, QLineEdit, QPushButton, QTableWidget
        from ..engine.excel_out import COLORS
        spec = dict(spec or {})
        self.df = df
        self.setWindowTitle(f"Sayfa biçimi — {sheet}")
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        h = QLabel("Renk kuralları Excel'in koşullu biçimlendirmesi olarak yazılır: dosyada değer değişirse renk de "
                   "değişir. Değer bir parametre olabilir: {Hedef Oran}. Metin değerleri tırnaksız yazılır.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.totals = QCheckBox("Tablonun altına toplam satırı ekle (filtrelenince yalnız görünenleri toplar)")
        self.totals.setChecked(bool(spec.get("totals")))
        lay.addWidget(self.totals)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Sütun", "Koşul", "Değer", "Renk", "Tüm satırı boya"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        self._mk = (QComboBox, QLineEdit, QCheckBox)
        self._colors = COLORS
        row = QHBoxLayout()
        b_add = QPushButton("Kural ekle")
        b_add.clicked.connect(lambda: self._add({}))
        b_del = QPushButton("Seçiliyi sil")
        b_del.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch()
        lay.addLayout(row)
        for r in spec.get("rules", []):
            self._add(r)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add(self, r):
        QComboBox, QLineEdit, QCheckBox = self._mk
        i = self.table.rowCount()
        self.table.insertRow(i)
        col = QComboBox()
        col.addItems([str(c) for c in self.df.columns])
        if r.get("column") in [str(c) for c in self.df.columns]:
            col.setCurrentText(r["column"])
        op = QComboBox()
        for k, v in ((">", "büyüktür"), ("<", "küçüktür"), (">=", "büyük veya eşit"), ("<=", "küçük veya eşit"),
                     ("=", "eşittir"), ("<>", "eşit değildir")):
            op.addItem(v, k)
        op.setCurrentIndex(max(0, op.findData(r.get("op", "<"))))
        val = QLineEdit(str(r.get("value", "")))
        color = QComboBox()
        for k, (_, _, name) in self._colors.items():
            color.addItem(name, k)
        color.setCurrentIndex(max(0, color.findData(r.get("color", "red"))))
        whole = QCheckBox()
        whole.setChecked(bool(r.get("whole_row")))
        for j, w in enumerate((col, op, val, color, whole)):
            self.table.setCellWidget(i, j, w)

    def spec(self) -> dict:
        rules = []
        for i in range(self.table.rowCount()):
            g = self.table.cellWidget
            if not g(i, 2).text().strip():
                continue
            rules.append({"column": g(i, 0).currentText(), "op": g(i, 1).currentData(), "value": g(i, 2).text().strip(),
                          "color": g(i, 3).currentData(), "whole_row": g(i, 4).isChecked()})
        out = {}
        if self.totals.isChecked():
            out["totals"] = True
        if rules:
            out["rules"] = rules
        return out


def value_summary(s, top=20):
    """(özet satırları, en sık değerler tablosu) — sütun değer dağılımı."""
    import pandas as pd
    from .table_model import format_value
    n = len(s)
    blank = int((s.isna() | s.map(lambda v: isinstance(v, str) and not v.strip())).sum())
    info = [("Satır", format_value(n)), ("Boş", format_value(blank)), ("Farklı değer", format_value(int(s.nunique())))]
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        d = s.dropna()
        if len(d):
            info += [("En küçük", format_value(d.min())), ("En büyük", format_value(d.max())),
                     ("Ortalama", format_value(round(float(d.mean()), 2))), ("Toplam", format_value(d.sum()))]
    elif pd.api.types.is_datetime64_any_dtype(s):
        d = s.dropna()
        if len(d):
            info += [("İlk", format_value(d.min())), ("Son", format_value(d.max()))]
    vc = s.astype(object).where(s.notna(), "(Boş)").value_counts().head(top)
    tbl = pd.DataFrame({"Değer": vc.index.map(format_value), "Adet": vc.values,
                        "%": (vc.values / max(n, 1) * 100).round(1)})
    return info, tbl


class ValueDistributionDialog(QDialog):
    """Sütundaki en sık değerler ve özet; bir değere çift tıklayınca o değerle filtre önerilir."""

    def __init__(self, df, column, parent=None, on_filter=None):
        super().__init__(parent)
        from .common import PreviewTable
        self.setWindowTitle(f"Değer dağılımı — {column}")
        self.resize(520, 560)
        lay = QVBoxLayout(self)
        info, tbl = value_summary(df[column])
        lay.addWidget(QLabel("  ·  ".join(f"<b>{k}:</b> {v}" for k, v in info)))
        lay.addWidget(QLabel("En sık 20 değer (çift tıklayın: yalnız bu değeri göster):"))
        self.table = PreviewTable(rows=20)
        self.table.set_frame(tbl)
        self.tbl = tbl
        lay.addWidget(self.table, 1)
        if on_filter is not None:
            self.table.doubleClicked.connect(lambda idx: (on_filter(self.raw(idx.row(), df[column])), self.accept()))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def raw(self, row, s):
        vc = s.astype(object).where(s.notna(), "(Boş)").value_counts().head(20)
        return vc.index[row]



class TrashDialog(QDialog):
    """Çöp kutusu: silinen rapor tanımları, referans tablolar, arşiv dönemleri/kümeleri (30 gün)."""

    def __init__(self, library, archive, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHeaderView, QPushButton, QTableWidget, QTableWidgetItem
        from ..engine.library import TRASH_KINDS
        self.library, self.archive = library, archive
        self._Item, self._kinds = QTableWidgetItem, TRASH_KINDS
        self.setWindowTitle("Çöp kutusu")
        self.resize(780, 440)
        lay = QVBoxLayout(self)
        h = QLabel("Silinen veya üzerine yazılan kayıtlar 30 gün burada durur. Geri yüklenen kayıt eski yerine döner; "
                   "aynı adla yenisi varsa adın sonuna '(geri)' eklenir. Arşivde aynı dönem şimdi varsa o hâli de "
                   "çöp kutusuna taşınır, hiçbir şey kaybolmaz.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tür", "Ad", "Ayrıntı", "Silinme"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self.status = QLabel()
        lay.addWidget(self.status)
        bb = QDialogButtonBox()
        b = bb.addButton("Geri yükle", QDialogButtonBox.ActionRole)
        b.clicked.connect(self.restore)
        bb.addButton("Kapat", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        from ..engine.archive import Archive
        items = []
        if self.library is not None:
            for t in self.library.trash():
                items.append(("lib", t["id"], self._kinds.get(t["kind"], t["kind"]), t["name"] or "", "",
                              t["deleted"]))
        if self.archive is not None:
            for t in self.archive.trash():
                items.append(("arc", t["id"], "Arşiv: " + Archive.TRASH_KINDS.get(t["kind"], t["kind"]),
                              t["set"], (t["key"] or "").replace("|", " · ") + (" — " if t["key"] else "") + t["info"],
                              t["deleted"]))
        items.sort(key=lambda x: x[5], reverse=True)
        self.items = items
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            for j, v in enumerate(it[2:5] + (it[5].replace("T", " "),)):
                self.table.setItem(i, j, self._Item(str(v)))
        if not items:
            self.status.setText("Çöp kutusu boş.")

    def restore(self):
        r = self.table.currentRow()
        if r < 0:
            return
        src, tid = self.items[r][:2]
        try:
            name = (self.library if src == "lib" else self.archive).restore(tid)
        except Exception as exc:  # noqa: BLE001
            from .common import show_error
            show_error(self, exc)
            return
        self.status.setText(f"Geri yüklendi: {name}")
        self.refresh()
