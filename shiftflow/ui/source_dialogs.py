"""Veri içe aktarma, kaynak bağlama (yeni raporla çalıştırma) ve dışa aktarma diyalogları."""

from __future__ import annotations

import os

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..engine import io as sio
from ..engine.errors import ShiftFlowError
from ..engine.values import type_label
from .worker import run_task
from .common import PreviewTable, busy, fmt_n, set_status, show_error, status_label

FILE_FILTER = "Veri dosyaları (*.xlsx *.xlsm *.xls *.csv *.txt *.tsv);;Excel (*.xlsx *.xlsm *.xls);;CSV (*.csv *.txt *.tsv)"
TYPE_NAMES = {"number": "Sayı", "date": "Tarih", "text": "Metin"}


class ImportDialog(QDialog):
    """Dosya veya panodan veri alır; sayfa, başlık satırı ve adı seçtirir, önizler."""

    def __init__(self, parent=None, path: str | None = None, text: str | None = None, name: str = "",
                 sheet: str | None = None, header: bool = True, lock_name=False):
        super().__init__(parent)
        self.path, self.text = path, text
        self.df: pd.DataFrame | None = None
        self.setWindowTitle("Veri al" if path else "Panodan yapıştır")
        self.resize(900, 600)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        if path:
            f.addRow("Dosya:", QLabel(os.path.basename(path)))
        self.sheet = QComboBox()
        sheets = []
        if path:
            try:
                sheets = sio.list_sheets(path)
            except ShiftFlowError as exc:
                show_error(self, exc)
        if sheets:
            self.sheet.addItems(sheets)
            if sheet in sheets:
                self.sheet.setCurrentText(sheet)
            f.addRow("Çalışma sayfası:", self.sheet)
        self.header = QCheckBox("İlk satır sütun başlıklarıdır")
        self.header.setChecked(header)
        f.addRow("", self.header)
        default = name or (os.path.splitext(os.path.basename(path))[0] if path else "Yapıştırılan veri")
        self.name = QLineEdit(default)
        self.name.setEnabled(not lock_name)
        f.addRow("Veri kaynağının adı:", self.name)
        lay.addLayout(f)
        self.status = status_label()
        lay.addWidget(self.status)
        self.preview = PreviewTable(rows=200)
        lay.addWidget(self.preview, 1)
        self.types = QLabel()
        self.types.setWordWrap(True)
        self.types.setObjectName("dialogHelp")
        lay.addWidget(self.types)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Al")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok = bb.button(QDialogButtonBox.Ok)
        lay.addWidget(bb)
        self.sheet.currentTextChanged.connect(self.load)
        self.header.toggled.connect(self.load)
        QTimer.singleShot(0, self.load)

    def selected_sheet(self):
        return self.sheet.currentText() if self.sheet.count() else None

    def load(self):
        try:
            if self.path:
                path, sheet, header = self.path, self.selected_sheet(), self.header.isChecked()
                self.df = run_task(self, lambda: sio.read_source(path, sheet, header), "Dosya okunuyor…")
            else:
                self.df = sio.parse_text_table(self.text or "", header=self.header.isChecked())
        except ShiftFlowError as exc:
            self.df = None
            set_status(self.status, "✖ " + exc.message, "err")
            self.preview.set_frame(None)
            self.ok.setEnabled(False)
            return
        set_status(self.status, f"{fmt_n(len(self.df))} satır × {fmt_n(self.df.shape[1])} sütun alınacak. "
                                "Kaynak dosya değiştirilmez.")
        self.preview.set_frame(self.df)
        self.types.setText("Sütun tipleri: " + ", ".join(f"{c} ({type_label(self.df[c])})" for c in self.df.columns[:40]))
        self.ok.setEnabled(True)


def pick_file(parent, settings, title="Veri dosyası seç") -> str | None:
    start = settings.value("last_dir", os.path.expanduser("~"))
    path, _ = QFileDialog.getOpenFileName(parent, title, start, FILE_FILTER)
    if path:
        settings.setValue("last_dir", os.path.dirname(path))
    return path or None


class ColumnMapDialog(QDialog):
    """Yeni raporda bulunamayan sütunları kullanıcıya eşletir."""

    def __init__(self, source: str, check: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Sütun eşleme — {source}")
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        msg = QLabel(
            f"<b>{source}</b> için seçilen yeni dosyada iş akışının kullandığı bazı sütunlar yok. "
            "Rapor biçimi değişmiş olabilir. Her eksik sütun için yeni dosyadaki karşılığını seçin. "
            "Seçiminiz iş akışına kaydedilir; sonraki raporlarda tekrar sorulmaz."
        )
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self.table = QTableWidget(len(check["missing"]), 2)
        self.table.setHorizontalHeaderLabels(["İş akışının beklediği sütun", "Yeni dosyadaki karşılığı"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.combos = {}
        for i, m in enumerate(check["missing"]):
            it = QTableWidgetItem(m)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, it)
            cb = QComboBox()
            cb.addItem("(eşleme yok)", None)
            for e in check["extra"]:
                cb.addItem(str(e), e)
            sug = check["suggestions"].get(m)
            if sug is not None:
                cb.setCurrentIndex(cb.findData(sug))
            self.table.setCellWidget(i, 1, cb)
            self.combos[m] = cb
        lay.addWidget(self.table)
        if check.get("type_changes"):
            t = QLabel("⚠ Tipi değişen sütunlar: " + ", ".join(
                f"{c} ({TYPE_NAMES[a]} → {TYPE_NAMES[b]})" for c, a, b in check["type_changes"]))
            t.setWordWrap(True)
            t.setStyleSheet("color:#8a5a00")
            lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Eşlemeyi uygula")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def mapping(self) -> dict:
        out = {}
        for expected, cb in self.combos.items():
            if cb.currentData() is not None:
                out[cb.currentData()] = expected
        return out


class BindSourcesDialog(QDialog):
    """Kayıtlı iş akışını yeni tarihli raporlarla çalıştırmak için kaynakları bağlar."""

    def __init__(self, session, settings, parent=None):
        super().__init__(parent)
        self.session, self.settings = session, settings
        self.setWindowTitle("Kaynakları bağla — yeni verilerle çalıştır")
        self.resize(900, 420)
        lay = QVBoxLayout(self)
        h = QLabel("Her kaynak için yeni raporu seçin. Aynı yolda güncellenen dosyalar için "
                   "'Kayıtlı yollardan yükle' yeterlidir. İşlem adımları değişmez; yalnızca veri yenilenir.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.names = list(session.workflow.sources)
        self.table = QTableWidget(len(self.names), 4)
        self.table.setHorizontalHeaderLabels(["Kaynak", "Dosya / sayfa", "Durum", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for i, n in enumerate(self.names):
            self.table.setItem(i, 0, QTableWidgetItem(n))
            row = QHBoxLayout()
            b_file, b_paste = QPushButton("Dosya seç…"), QPushButton("Yapıştır")
            b_file.clicked.connect(lambda _=False, n=n: self.choose_file(n))
            b_paste.clicked.connect(lambda _=False, n=n: self.paste(n))
            from PySide6.QtWidgets import QWidget
            w = QWidget()
            row.setContentsMargins(2, 0, 2, 0)
            row.addWidget(b_file)
            row.addWidget(b_paste)
            w.setLayout(row)
            self.table.setCellWidget(i, 3, w)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(3, 190)
        lay.addWidget(self.table)
        hb = QHBoxLayout()
        b_saved = QPushButton("Kayıtlı yollardan yükle")
        b_saved.clicked.connect(self.load_saved)
        hb.addWidget(b_saved)
        hb.addStretch()
        lay.addLayout(hb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Çalıştır")
        bb.button(QDialogButtonBox.Cancel).setText("Kapat")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        for i, n in enumerate(self.names):
            spec = self.session.workflow.sources[n]
            where = (os.path.basename(spec.path) + (f" / {spec.sheet}" if spec.sheet else "")) if spec.path else "(yapıştırma)"
            self.table.setItem(i, 1, QTableWidgetItem(where))
            if n in self.session.data:
                st = QTableWidgetItem(f"✓ Yüklendi ({fmt_n(len(self.session.data[n]))} satır)")
                st.setForeground(Qt.darkGreen)
            else:
                st = QTableWidgetItem("Veri bekleniyor")
                st.setForeground(Qt.darkYellow)
            self.table.setItem(i, 2, st)

    def _bind(self, name, df, path, sheet, header) -> bool:
        check = self.session.check_source(name, df)
        cmap = {}
        if check["missing"]:
            dlg = ColumnMapDialog(name, check, self)
            if dlg.exec() != QDialog.Accepted:
                return False
            cmap = dlg.mapping()
            check = self.session.check_source(name, df, cmap)
        self.session.bind_source(name, df, path=path, sheet=sheet, header=header, column_map=cmap)
        self.refresh()
        return True

    def choose_file(self, name):
        path = pick_file(self, self.settings, f"{name} için yeni rapor")
        if not path:
            return
        spec = self.session.workflow.sources[name]
        dlg = ImportDialog(self, path=path, name=name, sheet=spec.sheet, header=spec.header, lock_name=True)
        if dlg.exec() == QDialog.Accepted and dlg.df is not None:
            self._bind(name, dlg.df, path, dlg.selected_sheet(), dlg.header.isChecked())

    def paste(self, name):
        text = QGuiApplication.clipboard().text()
        dlg = ImportDialog(self, text=text, name=name, header=self.session.workflow.sources[name].header, lock_name=True)
        if dlg.exec() == QDialog.Accepted and dlg.df is not None:
            self._bind(name, dlg.df, "", None, dlg.header.isChecked())

    def load_saved(self):
        problems = []
        for n in self.names:
            spec = self.session.workflow.sources[n]
            if not spec.path:
                problems.append(f"{n}: yapıştırılan veri; yeniden yapıştırın.")
                continue
            try:
                df = run_task(self, lambda: sio.read_source(spec.path, spec.sheet, spec.header),
                              f"{n} okunuyor…")
            except ShiftFlowError as exc:
                problems.append(f"{n}: {exc.message}")
                continue
            if not self._bind(n, df, spec.path, spec.sheet, spec.header):
                problems.append(f"{n}: sütun eşleme yapılmadı.")
        if problems:
            from .common import info
            info(self, "Bazı kaynaklar yüklenemedi:\n\n" + "\n".join(problems))


class ExportDialog(QDialog):
    """Dışa aktarılacak veri kümelerini ve sayfa adlarını seçtirir."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Excel'e aktar")
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        tpl = (session.workflow.run_settings.get("template") or {}).get("path")
        lay.addWidget(QLabel("Her veri kümesi ayrı bir Excel sayfasına yazılır. Sayfa adlarını değiştirebilir, "
                             "sayfaya Excel grafiği ekleyebilirsiniz."
                             + (" Şablon kullanılıyor: sayfa adı şablondaki bir sayfayla aynıysa tablo oraya, "
                                "'Başlangıç' hücresinden itibaren yazılır." if tpl else "")))
        saved_o = {o["dataset"]: o for o in session.workflow.outputs}
        saved = {k: v.get("sheet") or k for k, v in saved_o.items()}
        names = list(session.workflow.datasets)
        order = [n for n in saved if n in names] + [n for n in names if n not in saved]
        self.charts = {n: saved_o.get(n, {}).get("chart") for n in order}
        self.formats = {n: {k: saved_o.get(n, {})[k] for k in ("totals", "rules") if saved_o.get(n, {}).get(k)}
                        for n in order}
        self.table = QTableWidget(len(order), 6)
        self.table.setHorizontalHeaderLabels(["Aktar", "Veri kümesi", "Sayfa adı", "Başlangıç", "Grafik", "Biçim"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for i, n in enumerate(order):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if (n in saved or not saved) else Qt.Unchecked)
            self.table.setItem(i, 0, chk)
            it = QTableWidgetItem(n)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 1, it)
            self.table.setItem(i, 2, QTableWidgetItem(saved.get(n, n)))
            self.table.setItem(i, 3, QTableWidgetItem(saved_o.get(n, {}).get("start_cell", "A1")))
            b = QPushButton(self._chart_label(n))
            b.clicked.connect(lambda _=False, n=n, b=b: self._chart(n, b))
            self.table.setCellWidget(i, 4, b)
            fb = QPushButton(self._format_label(n))
            fb.setToolTip("Toplam satırı ve koşullu renk (örn. hedef altı kırmızı)")
            fb.clicked.connect(lambda _=False, n=n, b=fb: self._format(n, b))
            self.table.setCellWidget(i, 5, fb)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 130)
        self.table.setColumnWidth(5, 140)
        lay.addWidget(self.table)
        self.remember = QCheckBox("Bu seçimi iş akışına kaydet (sonraki çalıştırmalarda aynı çıktı)")
        self.remember.setChecked(True)
        lay.addWidget(self.remember)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Dosya seç ve aktar…")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _format_label(self, n):
        f = self.formats.get(n) or {}
        parts = (["toplam"] if f.get("totals") else []) + ([f"{len(f['rules'])} renk"] if f.get("rules") else [])
        return "✓ " + ", ".join(parts) if parts else "Biçim…"

    def _format(self, n, button):
        from .stage_dialogs import OutputFormatDialog
        try:
            df = self.session.result(n)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        d = OutputFormatDialog(df, self.formats.get(n), self, sheet=n)
        if d.exec() == QDialog.Accepted:
            self.formats[n] = d.spec()
            button.setText(self._format_label(n))

    def _chart_label(self, n):
        c = self.charts.get(n)
        from ..engine.excel_out import CHART_TYPES
        return f"✓ {CHART_TYPES.get(c.get('type'), 'Grafik')}" if c else "Grafik ekle…"

    def _chart(self, n, button):
        from .stage_dialogs import ChartDialog
        try:
            df = self.session.result(n)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        d = ChartDialog(df, self.charts.get(n), self, sheet=n)
        if d.exec() == QDialog.Accepted:
            self.charts[n] = d.spec()
            button.setText(self._chart_label(n))

    def items(self):
        """[(veri kümesi, sayfa adı, seçenekler)]"""
        out = []
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).checkState() == Qt.Checked:
                name = self.table.item(i, 1).text()
                sheet = self.table.item(i, 2).text().strip() or name
                opts = {}
                start = (self.table.item(i, 3).text() if self.table.item(i, 3) else "").strip().upper()
                if start and start != "A1":
                    opts["start_cell"] = start
                if self.charts.get(name):
                    opts["chart"] = self.charts[name]
                opts.update(self.formats.get(name) or {})
                out.append((name, sheet, opts))
        return out


def ask_text(parent, title, label, text="") -> str | None:
    val, ok = QInputDialog.getText(parent, title, label, text=text)
    return val.strip() if ok and val.strip() else None


class FolderImportDialog(QDialog):
    """Bir klasördeki desene uyan tüm dosyaları (günlük raporlar) alt alta tek kaynak olarak alır.

    Kaynak deseni kaydedilir; her çalıştırmada klasör yeniden taranır, yeni dosyalar kendiliğinden gelir."""

    def __init__(self, parent=None, folder: str = "", pattern: str = "*.xlsx", sheet: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Klasörden dosyalar")
        self.resize(900, 640)
        self.df = None
        lay = QVBoxLayout(self)
        h = QLabel("Klasördeki desene uyan tüm dosyalar alt alta eklenir ve her satıra dosya adı yazılır "
                   f"('{sio.FILE_COLUMN}' sütunu). Desen iş akışına kaydedilir: sonraki çalıştırmalarda klasör "
                   "yeniden taranır, yeni günün dosyası kendiliğinden gelir. Excel'in açık dosya kilitleri (~$) atlanır.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        f = QFormLayout()
        row = QHBoxLayout()
        self.folder = QLineEdit(folder)
        b = QPushButton("Gözat…")
        b.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(b)
        f.addRow("Klasör:", row)
        self.pattern = QLineEdit(pattern)
        self.pattern.setPlaceholderText("örn. toplama_*.xlsx  ·  *.csv  ·  Rapor_2026-11-??.xlsx")
        f.addRow("Dosya adı deseni:", self.pattern)
        self.sheet = QLineEdit(sheet)
        self.sheet.setPlaceholderText("boş: her dosyanın ilk sayfası")
        f.addRow("Sayfa adı:", self.sheet)
        self.header = QCheckBox("İlk satır başlık")
        self.header.setChecked(True)
        f.addRow("", self.header)
        self.name = QLineEdit()
        self.name.setPlaceholderText("örn. Toplama (tüm günler)")
        f.addRow("Kaynak adı:", self.name)
        lay.addLayout(f)
        self.files = QLabel()
        self.files.setWordWrap(True)
        lay.addWidget(self.files)
        b_read = QPushButton("Dosyaları oku ve önizle")
        b_read.clicked.connect(self.load)
        lay.addWidget(b_read)
        self.status = status_label()
        lay.addWidget(self.status)
        self.preview = PreviewTable(rows=100)
        lay.addWidget(self.preview, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Kaynak olarak ekle")
        self.ok.setEnabled(False)
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for w in (self.folder, self.pattern):
            w.textChanged.connect(self._list)
        self._list()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Klasör seç", self.folder.text() or os.path.expanduser("~"))
        if d:
            self.folder.setText(d)

    def full_pattern(self) -> str:
        return os.path.join(self.folder.text().strip(), self.pattern.text().strip() or "*.xlsx")

    def _list(self):
        self.ok.setEnabled(False)
        self.df = None
        if not self.folder.text().strip():
            self.files.setText("Klasör seçin.")
            return
        files = sio.folder_files(self.full_pattern())
        names = [os.path.basename(f) for f in files]
        self.files.setText(f"Uyan dosya: {len(files)}" + (": " + ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
                                                       if names else ""))
        if not self.name.text().strip():
            stem = (self.pattern.text().split("*")[0].strip(" _-") or os.path.basename(self.folder.text().rstrip("/\\")))
            self.name.setPlaceholderText(stem or "Klasör")

    def load(self):
        pat, sheet, header = self.full_pattern(), self.sheet.text().strip() or None, self.header.isChecked()
        try:
            self.df = run_task(self, lambda: sio.read_folder(pat, sheet, header), "Dosyalar okunuyor…")
        except ShiftFlowError as exc:
            self.df = None
            set_status(self.status, "✖ " + exc.message, "err")
            self.preview.set_frame(None)
            self.ok.setEnabled(False)
            return
        notes = self.df.attrs.get("notes", [])
        set_status(self.status, "\n".join(notes[:1] + ["⚠ " + n for n in notes[1:8]]),
                   "warn" if len(notes) > 1 else "ok")
        self.preview.set_frame(self.df)
        self.ok.setEnabled(True)

    def source_name(self) -> str:
        return self.name.text().strip() or self.name.placeholderText() or "Klasör"
