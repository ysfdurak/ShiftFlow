"""Açık raporlar, rapor tanımları, 'Rapor oluştur' kontrol ekranı ve çıktı ayarları."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine import io as sio
from ..engine import reports as rp
from ..engine.autorun import DEFAULT_FILE_NAME, STATUS_LABELS, format_file_name
from ..engine.errors import ShiftFlowError
from ..engine.excel_live import FileWorkbookProvider, MultiProvider
from .common import ColumnChecklist, PreviewTable, ask, busy, fmt_n, info, set_status, show_error, status_label
from .source_dialogs import FILE_FILTER, ColumnMapDialog

STATUS_COLORS = {"ok": "#1d6b3a", "changed": "#1d6b3a", "needs_mapping": "#8a5a00", "ambiguous": "#8a5a00",
                 "stale": "#8a5a00", "not_found": "#a32020", "error": "#a32020"}
STATUS_ICONS = {"ok": "✓", "changed": "✓", "needs_mapping": "⚠", "ambiguous": "⚠", "stale": "⚠",
                "not_found": "✖", "error": "✖"}


def _letters(n):
    out = []
    for i in range(n):
        s, k = "", i + 1
        while k:
            k, r = divmod(k - 1, 26)
            s = chr(65 + r) + s
        out.append(s)
    return out


def raw_frame(rows):
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame([list(r) + [None] * (width - len(r)) for r in rows], columns=_letters(width), dtype=object)


# =========================================================================== açık raporlar
class OpenReportsDialog(QDialog):
    """Açık Excel kitaplarını (kaydedilmemişler dahil) listeler, tanınan raporları işaretler.

    Sonuç: `self.result_df`, `self.result_name`, `self.result_report` (tanım veya None),
    `self.result_ref` (kitap/sayfa bilgisi).
    """

    def __init__(self, provider, library, parent=None, settings=None, define_only=False):
        super().__init__(parent)
        self.base_provider, self.library, self.settings = provider, library, settings
        self.extra_files: list[str] = []
        self.define_only = define_only
        self.result_df = None
        self.result_name = ""
        self.result_report = None
        self.result_ref = None
        self.setWindowTitle("Açık raporlar")
        self.resize(1150, 680)
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("dialogHelp")
        lay.addWidget(self.info)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Çalışma kitabı / sayfa", "Tanınan rapor"])
        self.tree.setColumnWidth(0, 260)
        self.tree.currentItemChanged.connect(self._selected)
        ll.addWidget(self.tree)
        hb = QHBoxLayout()
        b_ref = QPushButton("Yenile")
        b_ref.clicked.connect(self.refresh)
        b_file = QPushButton("Dosyadan ekle…")
        b_file.setToolTip("Kaydedilmiş bir örnek rapor dosyasını listeye ekler")
        b_file.clicked.connect(self.add_file)
        hb.addWidget(b_ref)
        hb.addWidget(b_file)
        hb.addStretch()
        ll.addLayout(hb)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        hr = QHBoxLayout()
        hr.addWidget(QLabel("Başlık satırı:"))
        self.header_row = QSpinBox()
        self.header_row.setMinimum(1)
        self.header_row.setMaximum(30)
        self.header_row.valueChanged.connect(self._update_columns)
        hr.addWidget(self.header_row)
        self.cols_label = QLabel()
        self.cols_label.setWordWrap(True)
        hr.addWidget(self.cols_label, 1)
        rl.addLayout(hr)
        self.preview = PreviewTable(rows=30)
        rl.addWidget(self.preview, 1)
        self.status = status_label()
        rl.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([380, 770])
        lay.addWidget(split, 1)
        bb = QHBoxLayout()
        self.b_define = QPushButton("Rapor olarak tanımla…")
        self.b_define.clicked.connect(self.define)
        self.b_take = QPushButton("Veri olarak al")
        self.b_take.setDefault(True)
        self.b_take.clicked.connect(self.take)
        b_close = QPushButton("Kapat")
        b_close.clicked.connect(self.reject)
        bb.addStretch()
        bb.addWidget(self.b_define)
        if not define_only:
            bb.addWidget(self.b_take)
        bb.addWidget(b_close)
        lay.addLayout(bb)
        self.workbooks = []
        self.refresh()

    def provider(self):
        if self.extra_files:
            return MultiProvider([self.base_provider, FileWorkbookProvider(self.extra_files)])
        return self.base_provider

    def refresh(self):
        self.tree.clear()
        prov = self.provider()
        ok, msg = prov.available()
        defs = self.library.list() if self.library else []
        try:
            with busy():
                self.workbooks = prov.list_workbooks() if ok else []
        except ShiftFlowError as exc:
            self.workbooks = []
            msg = exc.message
        n_sheets = sum(len(w.sheets) for w in self.workbooks)
        text = (f"Açık kitaplar taranır; kaydedilmemiş olanlar da listelenir. {len(defs)} rapor tanımı var. "
                "Bir sayfa seçip veri olarak alabilir veya bir kez rapor olarak tanımlayabilirsiniz.")
        if msg:
            text = f"<span style='color:#8a5a00'>⚠ {msg}</span><br>" + \
                   "Örnek bir rapor dosyasıyla çalışmak için 'Dosyadan ekle…' kullanın."
        elif not self.workbooks:
            text = "Açık Excel kitabı bulunamadı. WMS'ten raporu açıp 'Yenile'ye basın veya 'Dosyadan ekle…' kullanın."
        self.info.setText(text)
        first = None
        for wb in self.workbooks:
            top = QTreeWidgetItem([wb.name + ("" if wb.saved else "  (kaydedilmemiş)") + (f"  ({wb.note})" if wb.note else ""), ""])
            top.setToolTip(0, wb.path or "Kaydedilmemiş kitap")
            self.tree.addTopLevelItem(top)
            for sh in wb.sheets:
                d, score, hdr = rp.recognize(defs, wb, sh)
                it = QTreeWidgetItem([f"{sh.name}  ·  {fmt_n(sh.n_rows)} satır (başlık satırları dahil)", f"✓ {d.name}" if d else ""])
                it.setData(0, Qt.UserRole, (wb, sh, d, hdr))
                if d:
                    it.setForeground(1, QColor("#1d6b3a"))
                top.addChild(it)
                if first is None and sh.n_rows:
                    first = it
            top.setExpanded(True)
        if first:
            self.tree.setCurrentItem(first)
        self.b_take.setEnabled(n_sheets > 0)
        self.b_define.setEnabled(n_sheets > 0)

    def add_file(self):
        start = self.settings.value("last_dir", os.path.expanduser("~")) if self.settings else os.path.expanduser("~")
        paths, _ = QFileDialog.getOpenFileNames(self, "Örnek rapor dosyası", start, FILE_FILTER)
        if paths:
            self.extra_files.extend(p for p in paths if p not in self.extra_files)
            self.refresh()

    def current(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _selected(self, *_):
        cur = self.current()
        if not cur:
            self.preview.set_frame(None)
            return
        wb, sh, d, hdr = cur
        self.preview.set_frame(raw_frame(sh.preview))
        guess = hdr if d else rp.guess_header_row(sh.preview)
        self.header_row.blockSignals(True)
        self.header_row.setValue(guess + 1)
        self.header_row.blockSignals(False)
        self._update_columns()
        if d:
            set_status(self.status, f"Bu sayfa '{d.name}' raporu olarak tanındı.")
        else:
            set_status(self.status, "Bu sayfa henüz tanımlı bir rapora uymuyor. Her gün gelecekse 'Rapor olarak tanımla…'.",
                       "warn")

    def _update_columns(self):
        cur = self.current()
        if not cur:
            return
        _, sh, _, _ = cur
        names = rp.header_names(sh.preview, self.header_row.value() - 1)
        self.cols_label.setText("Sütunlar: " + ", ".join(names[:20]) + (" …" if len(names) > 20 else ""))
        self.preview.selectRow(self.header_row.value() - 1)

    def _load(self):
        cur = self.current()
        if not cur:
            raise ShiftFlowError("Soldan bir sayfa seçin.")
        wb, sh, d, _ = cur
        with busy():
            rows = self.provider().read(wb.id, sh.name)
            df = sio.frame_from_rows(rows, self.header_row.value() - 1)
        return wb, sh, d, df

    def define(self):
        try:
            wb, sh, d, df = self._load()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        dlg = DefineReportDialog(df, wb.name, sh.name, self.library, existing=None, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.result_report = dlg.definition
            self.refresh()
            if self.define_only:
                self.accept()

    def take(self):
        try:
            wb, sh, d, df = self._load()
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        if d is None and self.library is not None and ask(
                self, "Bu sayfa tanımlı bir rapora uymuyor.\n\nHer gün gelen bir rapor ise şimdi tanımlarsanız "
                      "'Rapor oluştur' onu açık kitaplar arasında kendiliğinden bulur. Şimdi tanımlansın mı?"):
            dlg = DefineReportDialog(df, wb.name, sh.name, self.library, parent=self)
            if dlg.exec() == QDialog.Accepted:
                d = dlg.definition
        self.result_df, self.result_report = df, d
        self.result_ref = (wb, sh)
        self.result_name = d.name if d else os.path.splitext(wb.name)[0]
        self.accept()


class DefineReportDialog(QDialog):
    """Bir raporu bir kez tanımlar: adı, tanıma için kullanılacak sütunlar, isteğe bağlı ipuçları."""

    def __init__(self, df: pd.DataFrame | None, workbook_name: str, sheet_name: str, library,
                 existing: rp.ReportDefinition | None = None, parent=None):
        super().__init__(parent)
        self.library, self.existing = library, existing
        self.definition = None
        self.df = df
        self.setWindowTitle("Rapor tanımı" if existing is None else f"Rapor tanımı — {existing.name}")
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        h = QLabel("Rapor, sütun başlıklarından tanınır; dosya adı ve sayfa adı her gün değişse de (Kitap1, Sheet1…) "
                   "bulunur. Her gün mutlaka gelen sütunları işaretli bırakın; bazen gelmeyen sütunların işaretini kaldırın.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        f = QFormLayout()
        columns = [c["name"] for c in existing.columns] if existing else [str(c) for c in df.columns]
        default_name = existing.name if existing else os.path.splitext(workbook_name)[0]
        if not existing and default_name.lower().startswith(("kitap", "book")):
            default_name = ""
        self.name = QLineEdit(default_name)
        self.name.setPlaceholderText("örn. WMS Toplama Performans Raporu")
        self.desc = QLineEdit(existing.description if existing else "")
        self.desc.setPlaceholderText("isteğe bağlı: WMS'te hangi menüden alındığı vb.")
        f.addRow("Rapor adı:", self.name)
        f.addRow("Açıklama:", self.desc)
        lay.addLayout(f)
        lay.addWidget(QLabel("Tanıma için kullanılacak sütunlar:"))
        self.keys = ColumnChecklist(columns, existing.key_columns if existing else columns)
        lay.addWidget(self.keys, 1)
        g = QFormLayout()
        self.use_wb = QCheckBox("Kitap adında şu metin geçsin:")
        self.wb_hint = QLineEdit(existing.workbook_hint if existing else "")
        self.use_wb.setChecked(bool(existing and existing.workbook_hint))
        self.use_sh = QCheckBox("Sayfa adında şu metin geçsin:")
        self.sh_hint = QLineEdit(existing.sheet_hint if existing else ("" if sheet_name.lower().startswith(("sheet", "sayfa")) else sheet_name))
        self.use_sh.setChecked(bool(existing and existing.sheet_hint))
        g.addRow(self.use_wb, self.wb_hint)
        g.addRow(self.use_sh, self.sh_hint)
        lay.addLayout(g)
        note = QLabel("Benzer sütunlara sahip iki farklı rapor varsa (örn. toplama ve sayım) kitap veya sayfa adı "
                      "ipucu kullanın. Rapor, işaretli sütunların en az %80'i bulunduğunda tanınır.")
        note.setWordWrap(True)
        note.setObjectName("dialogHelp")
        lay.addWidget(note)
        if existing and existing.column_map:
            ml = QLabel("Öğrenilmiş sütun eşlemeleri: " + ", ".join(f"{a} → {b}" for a, b in existing.column_map.items()))
            ml.setWordWrap(True)
            lay.addWidget(ml)
            self.clear_map = QCheckBox("Öğrenilmiş eşlemeleri temizle")
            lay.addWidget(self.clear_map)
        else:
            self.clear_map = None
        self.status = status_label()
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        if self.existing:
            d = rp.ReportDefinition.from_dict(self.existing.to_dict())
        else:
            d = rp.ReportDefinition(name="", columns=rp.columns_of(self.df), key_columns=[])
        d.name = self.name.text().strip()
        d.description = self.desc.text().strip()
        d.key_columns = self.keys.checked()
        d.workbook_hint = self.wb_hint.text().strip() if self.use_wb.isChecked() else ""
        d.sheet_hint = self.sh_hint.text().strip() if self.use_sh.isChecked() else ""
        if self.clear_map is not None and self.clear_map.isChecked():
            d.column_map = {}
        if len(d.key_columns) < 2 and len(d.columns) >= 2:
            set_status(self.status, "✖ Güvenilir tanıma için en az iki sütun işaretleyin.", "err")
            return
        try:
            self.definition = self.library.save(d)
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return
        self.accept()


class ReportLibraryDialog(QDialog):
    """Rapor tanımları ve çalıştırma geçmişi."""

    def __init__(self, library, provider, parent=None, settings=None):
        super().__init__(parent)
        self.library, self.provider, self.settings = library, provider, settings
        self.setWindowTitle("Rapor tanımları")
        self.resize(940, 600)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        w = QWidget()
        wl = QHBoxLayout(w)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        left.addWidget(self.list)
        row = QHBoxLayout()
        for text, fn in (("Açık rapordan yeni…", self.new), ("Düzenle…", self.edit), ("Sil", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        left.addLayout(row)
        wl.addLayout(left, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        wl.addWidget(self.detail, 1)
        tabs.addTab(w, "Tanımlar")
        self.runs = QTableWidget(0, 4)
        self.runs.setHorizontalHeaderLabels(["Zaman", "İş akışı", "Durum", "Çıktı / mesaj"])
        self.runs.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.runs.verticalHeader().setVisible(False)
        self.runs.setEditTriggers(QTableWidget.NoEditTriggers)
        tabs.addTab(self.runs, "Çalıştırma geçmişi")
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self, select=None):
        self.list.clear()
        for d in self.library.list():
            it = QListWidgetItem(f"{d.name}\n   {len(d.key_columns)} tanıma sütunu · güncelleme {d.updated[:10]}")
            it.setData(Qt.UserRole, d.id)
            self.list.addItem(it)
            if d.id == select:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.detail.setPlainText("Henüz rapor tanımı yok.\n\nWMS'ten bir rapor açın ve 'Açık rapordan yeni…' ile "
                                     "bir kez tanımlayın. Sonraki günlerde ShiftFlow bu raporu açık kitaplar arasında "
                                     "kendiliğinden bulur.")
        runs = self.library.recent_runs(100)
        self.runs.setRowCount(len(runs))
        for i, r in enumerate(runs):
            st = "✓ başarılı" if r["status"] == "ok" else "✖ hata"
            vals = [r["ts"].replace("T", " "), r["workflow"] or "", st, r["output"] or r["message"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 2:
                    it.setForeground(QColor("#1d6b3a" if r["status"] == "ok" else "#a32020"))
                self.runs.setItem(i, j, it)
        self.runs.resizeColumnsToContents()

    def selected(self):
        it = self.list.currentItem()
        return self.library.get(it.data(Qt.UserRole)) if it else None

    def _show(self, *_):
        d = self.selected()
        if not d:
            return
        lines = [d.name, d.description, "",
                 "Tanıma sütunları: " + ", ".join(d.key_columns),
                 "Tüm sütunlar: " + ", ".join(f"{c['name']} ({rp.TYPE_NAMES.get(c['type'], c['type'])})" for c in d.columns)]
        if d.workbook_hint:
            lines.append(f"Kitap adı ipucu: {d.workbook_hint}")
        if d.sheet_hint:
            lines.append(f"Sayfa adı ipucu: {d.sheet_hint}")
        if d.column_map:
            lines.append("Öğrenilmiş eşlemeler: " + ", ".join(f"{a} → {b}" for a, b in d.column_map.items()))
        self.detail.setPlainText("\n".join(x for x in lines if x is not None))

    def new(self):
        dlg = OpenReportsDialog(self.provider, self.library, self, settings=self.settings, define_only=True)
        dlg.exec()
        self.refresh(dlg.result_report.id if dlg.result_report else None)

    def edit(self):
        d = self.selected()
        if not d:
            return
        dlg = DefineReportDialog(None, "", "", self.library, existing=d, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh(d.id)

    def delete(self):
        d = self.selected()
        if d and ask(self, f"'{d.name}' rapor tanımı silinsin mi?\n\nBu tanıma bağlı iş akışları, iş akışı dosyasında "
                           "saklanan kopya sayesinde çalışmaya devam eder.\n\nSilinen kayıt 30 gün çöp kutusunda durur (Rapor → Çöp kutusu) ve geri yüklenebilir."):
            self.library.delete(d.id)
            self.refresh()


# =========================================================================== rapor oluştur
class RunPlanDialog(QDialog):
    """'Rapor oluştur' öncesi kontrol ekranı. Yalnızca karar gerektiren bir durum varsa açılır."""

    def __init__(self, builder, plans, parent=None, settings=None):
        super().__init__(parent)
        self.builder, self.plans, self.settings = builder, plans, settings
        self.setWindowTitle("Rapor oluştur — kaynak kontrolü")
        self.resize(1000, 560)
        lay = QVBoxLayout(self)
        h = QLabel("Her kaynak için kullanılacak veri aşağıda. ✓ olanlar hazır; ⚠ ve ✖ olanlar için bir karar verin. "
                   "Hepsi hazır olduğunda 'Raporu oluştur' etkinleşir.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Kaynak", "Rapor tanımı", "Kullanılacak veri", "Satır", "Durum"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show)
        lay.addWidget(self.table, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail.setMinimumHeight(70)
        self.detail.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.detail)
        row = QHBoxLayout()
        self.b_map = QPushButton("Sütunları eşle…")
        self.b_pick = QPushButton("Raporu seç…")
        self.b_file = QPushButton("Dosya seç…")
        self.b_stale = QPushButton("Yine de bu veriyi kullan")
        self.b_scan = QPushButton("Yeniden tara")
        for b, fn in ((self.b_map, self.map), (self.b_pick, self.pick), (self.b_file, self.file),
                      (self.b_stale, self.accept_stale), (self.b_scan, self.rescan)):
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Raporu oluştur")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self):
        cur = max(self.table.currentRow(), 0)
        self.table.setRowCount(len(self.plans))
        for i, p in enumerate(self.plans):
            status = p.status
            label = STATUS_LABELS[status] + (" — onaylandı" if status == "stale" and p.accept_stale else "")
            vals = [p.source, p.report_name or ("dosya" if p.mode == "file" else "—"), p.where,
                    fmt_n(len(p.df)) if p.df is not None else "", f"{STATUS_ICONS[status]} {label}"]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 4:
                    color = "#1d6b3a" if not p.blocking else STATUS_COLORS[status]
                    it.setForeground(QColor(color))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        if self.plans:
            self.table.selectRow(min(cur, len(self.plans) - 1))
        self.ok.setEnabled(not any(p.blocking for p in self.plans))
        self._show()

    def current(self):
        r = self.table.currentRow()
        return self.plans[r] if 0 <= r < len(self.plans) else None

    def _show(self):
        p = self.current()
        if not p:
            return
        self.detail.setText("<br>".join(p.messages) or "Sorun yok.")
        self.b_map.setEnabled(p.status == "needs_mapping")
        self.b_pick.setEnabled(p.mode == "report" and len(p.candidates) > 0)
        self.b_stale.setEnabled(p.status == "stale" and not p.accept_stale)
        self.b_file.setEnabled(True)

    def map(self):
        p = self.current()
        if not p or p.status != "needs_mapping":
            return
        dlg = ColumnMapDialog(p.source, p.changes, self)
        if dlg.exec() == QDialog.Accepted:
            m = dlg.mapping()
            if not m:
                return
            learn = p.mode == "report"
            self.builder.apply_mapping(p, m, learn=learn)
            self.fill()

    def pick(self):
        p = self.current()
        if not p or not p.candidates:
            return
        labels = [f"{c.label}  (uyum %{int(min(c.score, 1) * 100)})" for c in p.candidates]
        choice, ok = QInputDialog.getItem(self, "Rapor seç", f"'{p.source}' için kullanılacak açık rapor:", labels, 0, False)
        if ok:
            with busy():
                self.builder.choose(p, p.candidates[labels.index(choice)])
            self.fill()

    def file(self):
        p = self.current()
        if not p:
            return
        start = self.settings.value("last_dir", os.path.expanduser("~")) if self.settings else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, f"{p.source} için dosya", start, FILE_FILTER)
        if not path:
            return
        sheet = None
        sheets = sio.list_sheets(path)
        if len(sheets) > 1:
            sheet, ok = QInputDialog.getItem(self, "Çalışma sayfası", "Sayfa:", sheets, 0, False)
            if not ok:
                return
        with busy():
            self.builder.use_file(p, path, sheet)
        self.fill()

    def accept_stale(self):
        p = self.current()
        if p and p.status == "stale":
            p.accept_stale = True
            self.fill()

    def rescan(self):
        try:
            with busy():
                self.plans[:] = self.builder.plan()
        except ShiftFlowError as exc:
            show_error(self, exc)
        self.fill()


class RunSettingsDialog(QDialog):
    """Çıktı klasörü ve dosya adı kalıbı (iş akışında saklanır)."""

    def __init__(self, workflow, parent=None):
        super().__init__(parent)
        self.wf = workflow
        rs = workflow.run_settings
        self.setWindowTitle("Çıktı ayarları")
        self.resize(640, 260)
        lay = QVBoxLayout(self)
        f = QFormLayout()
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
        lay.addLayout(f)
        hint = QLabel("Kullanılabilir alanlar: {akis} iş akışı adı, {tarih} 2026-11-10, {saat} 0730, {gun}, {ay}, {yil}. "
                      "Aynı adlı dosya varsa üzerine yazılmaz; sonuna (2), (3) eklenir.")
        hint.setWordWrap(True)
        hint.setObjectName("dialogHelp")
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._preview()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Çıktı klasörü", self.dir.text())
        if d:
            self.dir.setText(d)

    def _preview(self):
        # Örnek, ana penceredeki seçili dönemle yazılır (önceden hep bugünün tarihi görünüyordu).
        bar = getattr(self.parent(), "period_bar", None)
        period = bar.period() if bar is not None else None
        self.example.setText("Örnek: " + format_file_name(self.name.text() or DEFAULT_FILE_NAME,
                                                          self.wf.name or "Rapor", datetime.now(), period) + ".xlsx")

    def settings_dict(self):
        return {"output_dir": self.dir.text().strip(), "file_name": self.name.text().strip() or DEFAULT_FILE_NAME,
                "open_after": self.open_after.isChecked()}
