"""Excel formülünü ShiftFlow formülüne çeviren pencere."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..engine import expression
from ..engine import excel_formula as xf
from ..engine.errors import ShiftFlowError
from ..engine.values import tr_lower
from .common import PreviewTable, fmt_n, set_status, status_label


def excel_columns(session, name: str, current_df: pd.DataFrame | None = None) -> list[str]:
    """Bir tablonun Excel'deki muhtemel sütun sırası.

    Kaynak tablolarda önce raporun özgün sütunları, ardından ShiftFlow'da eklenen
    (hesaplanan) sütunlar gelir. Raporun yanına eklenmiş formüllü sütunlar
    Excel'de de genellikle sağa doğru sırayla durduğu için bu sıra çoğu zaman
    Excel düzeniyle aynıdır.
    """
    wf = session.workflow if session else None
    cols = list(map(str, current_df.columns)) if current_df is not None else []
    if wf and name in wf.datasets and wf.datasets[name].origin.type == "source":
        try:
            src = list(map(str, session.source_frame(wf.datasets[name].origin.source).columns))
        except ShiftFlowError:
            src = []
        if current_df is None:
            try:
                cols = list(map(str, session.result(name).columns))
            except ShiftFlowError:
                cols = []
        return src + [c for c in cols if c not in src]
    if current_df is None and wf and name in wf.datasets:
        try:
            cols = list(map(str, session.result(name).columns))
        except ShiftFlowError:
            cols = []
    return cols


class FormulaImportDialog(QDialog):
    """Excel formülünü yapıştır → ShiftFlow formülü + önizleme.

    mode="step": Uygula, yeni hesaplanan sütun adımı için `self.params` üretir.
    mode="insert": yalnızca çevrilmiş formülü (`self.formula`) döner (Hesapla penceresine).
    """

    def __init__(self, session, dataset: str | None, df: pd.DataFrame, parent=None, mode="step", text=""):
        super().__init__(parent)
        self.session, self.dataset, self.df, self.mode = session, dataset, df, mode
        self.params, self.formula = None, ""
        self.setWindowTitle("Excel formülünden sütun")
        self.resize(980, 780)
        lay = QVBoxLayout(self)
        h = QLabel("Excel'deki formülü (= ile başlayan) yapıştırın. Hücre adresleri sütun adlarına, başka sayfalar "
                   "ShiftFlow tablolarına çevrilir. DÜŞEYARA, İNDİS/KAÇINCI, ÇAPRAZARA, EĞERSAY, ETOPLA ve TOPLA(B:B) "
                   "gibi kalıplar tanınır. Türkçe ve İngilizce Excel yazımı desteklenir.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.src = QPlainTextEdit(text)
        self.src.setPlaceholderText('=EĞER(DÜŞEYARA(B2;Personel!A:C;3;0)="";"Tanımsız";C2&"-"&D2)')
        self.src.setMaximumHeight(80)
        lay.addWidget(self.src)
        g = QGroupBox(f"Bu tablo ({dataset or 'seçili tablo'}) Excel'de nasıl dizilmiş?")
        gf = QFormLayout(g)
        row = QHBoxLayout()
        self.start = QLineEdit("A")
        self.start.setMaximumWidth(50)
        self.row = QSpinBox()
        self.row.setRange(0, 1_000_000)
        self.row.setSpecialValueText("otomatik")
        self.row.setMinimumWidth(140)
        row.addWidget(QLabel("İlk sütun harfi:"))
        row.addWidget(self.start)
        row.addSpacing(20)
        row.addWidget(QLabel("Formülün yazıldığı satır:"))
        row.addWidget(self.row)
        row.addStretch()
        gf.addRow(row)
        self.map_label = QLabel()
        self.map_label.setWordWrap(True)
        self.map_label.setObjectName("dialogHelp")
        gf.addRow(self.map_label)
        lay.addWidget(g)
        self.sheet_box = QGroupBox("Formüldeki diğer sayfalar → ShiftFlow tabloları")
        sl = QVBoxLayout(self.sheet_box)
        self.sheets = QTableWidget(0, 3)
        self.sheets.setHorizontalHeaderLabels(["Excel sayfası", "ShiftFlow tablosu", "İlk sütun harfi"])
        self.sheets.verticalHeader().setVisible(False)
        self.sheets.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sheets.setMaximumHeight(120)
        sl.addWidget(self.sheets)
        self.sheet_box.hide()
        lay.addWidget(self.sheet_box)
        lay.addWidget(QLabel("ShiftFlow formülü (gerekirse düzenleyebilirsiniz):"))
        from .formula_editor import FormulaEdit
        self.out = FormulaEdit(columns=df.columns)
        self.out.setMinimumHeight(130)
        lay.addWidget(self.out)
        self.sig = QLabel()
        self.sig.setObjectName("signature")
        self.out.signatureChanged.connect(self.sig.setText)
        lay.addWidget(self.sig)
        f = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("örn. Ekip Lideri")
        if mode == "step":
            f.addRow("Yeni sütun adı:", self.name)
        lay.addLayout(f)
        self.status = status_label()
        lay.addWidget(self.status)
        self.preview = PreviewTable(rows=100)
        lay.addWidget(self.preview, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Sütun olarak ekle" if mode == "step" else "Formüle aktar")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        self.op = "calc"
        if mode == "step":
            from PySide6.QtWidgets import QDialogButtonBox as _B
            self.b_excel = bb.addButton("Excel'e bırak", _B.ActionRole)
            self.b_excel.setToolTip("ShiftFlow'da karşılığı olmayan formülü çıktı dosyasına Excel formülü olarak yazar; "
                                    "Excel açılınca hesaplanır. Bu sütun ShiftFlow'daki sonraki adımlarda kullanılamaz.")
            self.b_excel.clicked.connect(self._accept_excel)
            self.b_excel.hide()
        from PySide6.QtWidgets import QDialogButtonBox as _B2
        self.b_param = bb.addButton("Parametre yap…", _B2.ActionRole)
        self.b_param.setToolTip("$H$1 gibi sabit hücreyi iş akışı parametresine bağlar; formülde {Ad} olarak geçer.")
        self.b_param.clicked.connect(self._make_params)
        self.b_param.hide()
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._timer = QTimer(self, singleShot=True, interval=300)
        self._timer.timeout.connect(self.translate)
        self._ptimer = QTimer(self, singleShot=True, interval=300)
        self._ptimer.timeout.connect(self.preview_result)
        self._translating = False
        self.src.textChanged.connect(self._timer.start)
        self.start.textChanged.connect(self._timer.start)
        self.row.valueChanged.connect(self._timer.start)
        self.out.textChanged.connect(lambda: None if self._translating else self._ptimer.start())
        self.name.textChanged.connect(self._ptimer.start)
        self._sheet_names: list[str] = []
        self.translate()

    # ------------------------------------------------------------ eşleme
    def datasets(self):
        if not self.session:
            return []
        blocked = set(self.session.workflow.dependents_of(self.dataset)) | {self.dataset} if self.dataset else set()
        return [n for n in self.session.workflow.datasets if n not in blocked]

    def current_map(self):
        cols = excel_columns(self.session, self.dataset, self.df) if self.session and self.dataset else list(map(str, self.df.columns))
        return xf.letter_map(cols, (self.start.text() or "A").strip().upper())

    def _sync_sheets(self, names):
        if names == self._sheet_names:
            return
        self._sheet_names = list(names)
        self.sheets.blockSignals(True)
        self.sheets.setRowCount(len(names))
        options = self.datasets()
        for i, sh in enumerate(names):
            it = QTableWidgetItem(sh)
            self.sheets.setItem(i, 0, it)
            cb = QComboBox()
            cb.addItem("(eşleme yok)", "")
            for n in options:
                cb.addItem(n, n)
            guess = next((n for n in options if tr_lower(n) == tr_lower(sh)), None) or \
                next((n for n in options if tr_lower(sh) in tr_lower(n) or tr_lower(n) in tr_lower(sh)), None)
            if guess:
                cb.setCurrentIndex(cb.findData(guess))
            cb.currentIndexChanged.connect(self._timer.start)
            self.sheets.setCellWidget(i, 1, cb)
            le = QLineEdit("A")
            le.textChanged.connect(self._timer.start)
            self.sheets.setCellWidget(i, 2, le)
        self.sheets.blockSignals(False)
        self.sheet_box.setVisible(bool(names))

    def sheet_map(self):
        out = {}
        for i, sh in enumerate(self._sheet_names):
            ds = self.sheets.cellWidget(i, 1).currentData()
            start = (self.sheets.cellWidget(i, 2).text() or "A").strip().upper()
            cols = excel_columns(self.session, ds) if ds else []
            out[sh] = (ds or None, xf.letter_map(cols, start))
        return out

    # ------------------------------------------------------------ çeviri
    def translate(self):
        text = self.src.toPlainText().strip()
        cmap = self.current_map()
        self.map_label.setText("Bu tablo: " + ", ".join(f"{k}={v}" for k, v in list(cmap.items())[:30])
                               + (" …" if len(cmap) > 30 else ""))
        if not text:
            self._set_out("")
            set_status(self.status, "Excel formülünü yapıştırın.", "warn")
            self.ok.setEnabled(False)
            return
        try:
            info = xf.scan(text)
            self._sync_sheets(info["sheets"])
            pcells = self.session.parameter_cells if self.session else {}
            tr = xf.translate(text, cmap, self.sheet_map(), current_row=self.row.value() or None, params=pcells)
        except ShiftFlowError as exc:
            self._set_out("")
            set_status(self.status, "✖ " + exc.message + "\nÇevrilemiyorsa 'Excel'e bırak' ile çıktıya Excel formülü "
                       "olarak yazdırabilirsiniz.", "err")
            self.ok.setEnabled(False)
            if hasattr(self, "b_excel"):
                self.b_excel.setVisible(True)
            self._row_used = None
            return
        if not self.row.value() and tr.current_row:
            self.row.blockSignals(True)
            self.row.setSpecialValueText(f"otomatik ({tr.current_row})")
            self.row.blockSignals(False)
        self._warnings = tr.warnings
        self._row_used = tr.current_row
        self._fixed = tr.fixed_cells
        if hasattr(self, "b_param"):
            self.b_param.setVisible(bool(tr.fixed_cells) and self.session is not None)
        self._set_out(tr.formula)
        if hasattr(self, "b_excel"):
            self.b_excel.setVisible("[?" in tr.formula or bool(tr.warnings))
        self.preview_result()

    def _set_out(self, text):
        self._translating = True
        if len(text) > 90:
            try:
                text = expression.format_formula(text)
            except ShiftFlowError:
                pass
        self.out.setPlainText(text)
        self._translating = False

    def tables(self):
        if not self.session:
            return {}
        out = {}
        for t in expression.referenced_tables(self.out.toPlainText()):
            try:
                out[t] = self.session.result(t)
            except ShiftFlowError:
                pass
        return out

    def preview_result(self):
        formula = self.out.toPlainText().strip()
        warns = ["⚠ " + w for w in getattr(self, "_warnings", [])]
        if not formula:
            self.ok.setEnabled(False)
            return
        try:
            notes = []
            vals, div0 = expression.evaluate(formula, self.df, "önizleme", self.tables(), notes,
                                             params=self.session.parameters if self.session else None)
        except ShiftFlowError as exc:
            self.out.set_error(getattr(exc, "pos", None))
            set_status(self.status, "\n".join(warns + ["✖ " + exc.message]), "err")
            self.ok.setEnabled(False)
            self.preview.set_frame(None)
            return
        name = self.name.text().strip() or "Yeni sütun"
        shown = self.df.copy()
        shown.insert(0, name, vals.to_numpy())
        self.preview.set_frame(shown)
        filled = int(vals.notna().sum())
        msg = [f"Formül çalışıyor: {fmt_n(filled)} / {fmt_n(len(vals))} satırda değer var."] + warns + \
              ["⚠ " + n for n in notes]
        if div0:
            msg.append(f"⚠ {fmt_n(div0)} satırda sıfıra bölme.")
        set_status(self.status, "\n".join(msg), "warn" if (warns or notes or div0) else "ok")
        self.ok.setEnabled(True)

    def _make_params(self):
        """Formüldeki sabit hücreler için parametre adı ve değeri sorar."""
        from PySide6.QtWidgets import QInputDialog
        cells, values = {}, {}
        for cell in getattr(self, "_fixed", []):
            name, ok = QInputDialog.getText(self, "Parametre yap", f"{cell} hücresi için parametre adı "
                                            "(örn. Hedef Oran):", text=self.session.parameter_cells.get(cell, ""))
            if not ok or not name.strip():
                return
            known = self.session.parameters.get(name.strip())
            val, ok = QInputDialog.getText(self, "Parametre yap", f"'{name.strip()}' değeri (Excel'deki {cell} "
                                           "hücresinin değeri):", text="" if known is None else str(known))
            if not ok:
                return
            cells[cell] = name.strip()
            values[name.strip()] = val
        try:
            self.session.define_parameters_from_cells(cells, values)
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return
        self.translate()

    def _accept_excel(self):
        """Formülü çevirmeden çıktıya Excel formülü olarak yazdır."""
        name = self.name.text().strip()
        if not name:
            set_status(self.status, "✖ Sütun için bir ad girin.", "err")
            return
        row = self.row.value() or getattr(self, "_row_used", None) or xf.scan(self.src.toPlainText())["current_row"] or 2
        try:
            tpl, warns = xf.to_template(self.src.toPlainText(), self.current_map(), row)
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return
        self.op = "excel_formula"
        self.params = {"name": name, "template": tpl, "excel": self.src.toPlainText().strip()}
        self.excel_warnings = warns
        self.accept()

    def _accept(self):
        self.formula = self.out.toPlainText().strip()
        if self.mode == "step":
            name = self.name.text().strip()
            if not name:
                set_status(self.status, "✖ Yeni sütun için bir ad girin.", "err")
                return
            self.params = {"name": name, "formula": self.formula, "replace": False}
        self.accept()


# ====================================================================== formüllü sütunlar
def _same(a, b) -> bool:
    """Excel değeri ile ShiftFlow sonucu aynı mı (sayılarda küçük yuvarlama farkı yok sayılır)."""
    from ..engine.values import to_number
    if expression._is_na(a) and expression._is_na(b):
        return True
    if expression._is_na(a) or expression._is_na(b):
        return str(a if not expression._is_na(a) else b).strip() == ""
    try:
        x, _ = to_number(pd.Series([a, b], dtype=object))
        if x.notna().all():
            return abs(float(x.iloc[0]) - float(x.iloc[1])) <= 1e-6 * max(1.0, abs(float(x.iloc[0])))
    except Exception:  # noqa: BLE001
        pass
    if isinstance(a, pd.Timestamp) or isinstance(b, pd.Timestamp):
        try:
            return pd.Timestamp(a) == pd.Timestamp(b)
        except Exception:  # noqa: BLE001
            return False
    return tr_lower(str(a).strip()) == tr_lower(str(b).strip())


class FormulaColumnsDialog(QDialog):
    """Açık Excel'de (veya .xlsx dosyasında) raporun yanına eklenmiş formüllü sütunları bulur,
    hepsini ShiftFlow formülüne çevirir ve Excel'deki değerlerle karşılaştırır.

    Uygula: seçilen sütunlar için `self.steps` = [hesaplanan sütun parametreleri] (soldan sağa).
    `load_sheet(sayfa, referans_mı) -> veri kümesi adı`: formülün kullandığı ama yüklenmemiş
    sayfayı aynı kitaptan yükler (ana pencere sağlar)."""

    def __init__(self, session, dataset: str, provider, workbook_id: str, sheet: str, parent=None,
                 load_sheet=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QPushButton
        self.session, self.dataset, self.provider = session, dataset, provider
        self.wb, self.sheet, self.load_sheet = workbook_id, sheet, load_sheet
        self.steps: list[dict] = []
        self.setWindowTitle(f"Excel'deki formüllü sütunlar — {sheet}")
        self.resize(1180, 640)
        lay = QVBoxLayout(self)
        h = QLabel("Excel'de bu tablonun yanına eklenmiş formüllü sütunlar bulundu. Her biri ShiftFlow formülüne "
                   "çevrildi ve Excel'deki değerlerle karşılaştırıldı. Seçtikleriniz 'Hesaplanan sütun' adımı olarak "
                   "eklenir; böylece formüller her yeni raporda kendiliğinden uygulanır. Excel'e hiçbir şey yazılmaz.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        self.missing_box = QGroupBox("Formüllerin kullandığı ama yüklenmemiş sayfalar")
        mb = QHBoxLayout(self.missing_box)
        self.missing_label = QLabel()
        self.missing_label.setWordWrap(True)
        mb.addWidget(self.missing_label, 1)
        self.as_ref = QCheckBox("Referans tablo olarak kaydet (sabit listeler: personel, ürün…)")
        self.as_ref.setChecked(True)
        mb.addWidget(self.as_ref)
        self.b_load = QPushButton("Bu kitaptan yükle")
        self.b_load.clicked.connect(self._load_missing)
        self.b_load.setEnabled(load_sheet is not None)
        mb.addWidget(self.b_load)
        lay.addWidget(self.missing_box)
        self.param_box = QGroupBox("Sabit hücreler (parametre hücresi olabilir)")
        pb = QHBoxLayout(self.param_box)
        self.param_label = QLabel()
        self.param_label.setWordWrap(True)
        pb.addWidget(self.param_label, 1)
        b_par = QPushButton("Parametre olarak tanımla")
        b_par.setToolTip("Adı ve değeri Excel'den alınır; sonradan Dosya → Parametreler'den değiştirilebilir.")
        b_par.clicked.connect(self._make_params)
        pb.addWidget(b_par)
        lay.addWidget(self.param_box)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Sütun", "Excel formülü", "ShiftFlow formülü", "Excel ile uyum",
                                              "Not"])
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 300)
        self.table.setWordWrap(True)
        lay.addWidget(self.table, 1)
        self.status = status_label()
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Seçilenleri adım olarak ekle")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.grid = provider.formula_rows(workbook_id, sheet)
        self.reload()

    # ------------------------------------------------------------ çeviri
    def _sheet_letters(self, sheet) -> dict:
        """Diğer sayfanın gerçek başlık düzeni (harf → sütun adı), kitaptan okunarak."""
        try:
            g = self.provider.formula_rows(self.wb, sheet)
        except ShiftFlowError:
            return {}
        best, row = 0, None
        for r in g.rows[:30]:
            filled = [v for v in r if isinstance(v, str) and v.strip() and not v.startswith("=")]
            if len(filled) > best:
                best, row = len(filled), r
        if row is None:
            return {}
        return {xf.col_letter(g.first_col + j): str(v).strip() for j, v in enumerate(row)
                if v is not None and str(v).strip()}

    def _datasets_by_name(self):
        return {tr_lower(n): n for n in self.session.workflow.datasets}

    def sheet_map(self, names) -> dict:
        by = self._datasets_by_name()
        out = {}
        for sh in names:
            ds = by.get(tr_lower(sh))
            if ds is None:  # 'Personel' sayfası 'Toplama - Personel' adıyla yüklenmiş olabilir
                ds = next((n for k, n in by.items() if k.endswith(" - " + tr_lower(sh))), None)
            letters = self._sheet_letters(sh) if ds else {}
            if ds and not letters:
                letters = xf.letter_map(excel_columns(self.session, ds), "A")
            out[sh] = (ds, letters)
        return out

    def reload(self):
        sheets = set()
        for r in self.grid.rows:
            for v in r:
                if isinstance(v, str) and v.startswith("="):
                    try:
                        sheets |= set(xf.scan(v)["sheets"])
                    except ShiftFlowError:
                        pass
        sheets.discard(self.sheet)
        smap = self.sheet_map(sorted(sheets))
        self.missing = [s for s, (ds, _) in smap.items() if ds is None]
        self.missing_box.setVisible(bool(self.missing))
        self.missing_label.setText(", ".join(self.missing))
        try:
            self.header_row, self.cols = xf.find_formula_columns(self.grid, self.df_columns(), smap, self.sheet,
                                                                 params=self.session.parameter_cells)
        except ShiftFlowError as exc:
            self.cols = []
            set_status(self.status, "✖ " + exc.message, "err")
            self.ok.setEnabled(False)
            return
        self._fixed_props = {}
        for fc in self.cols:
            for cell in fc.fixed_cells:
                if cell not in self._fixed_props:
                    val, label = xf.cell_value(self.grid, cell)
                    self._fixed_props[cell] = (label or f"Parametre {cell}", val)
        self.param_box.setVisible(bool(self._fixed_props))
        self.param_label.setText("; ".join(f"{c} → {{{n}}} = {'?' if v is None else v}"
                                           for c, (n, v) in self._fixed_props.items()))
        self._fill()

    def _make_params(self):
        cells = {c: n for c, (n, v) in self._fixed_props.items()}
        values = {n: ("" if v is None else v) for c, (n, v) in self._fixed_props.items()}
        try:
            self.session.define_parameters_from_cells(cells, values)
        except ShiftFlowError as exc:
            set_status(self.status, "✖ " + exc.message, "err")
            return
        self.reload()

    def df_columns(self):
        try:
            return list(map(str, self.session.result(self.dataset).columns))
        except ShiftFlowError:
            return []

    def _check(self, fc):
        """(uyum metni, oran) — Excel'deki değer veri kümesinde varsa karşılaştırır."""
        if not fc.formula or "[?" in fc.formula:
            return "—", None
        try:
            df = self.session.result(self.dataset)
            tables = {}
            for t in expression.referenced_tables(fc.formula):
                tables[t] = self.session.result(t)
            vals, _ = expression.evaluate(fc.formula, df, fc.name, tables, params=self.session.parameters)
        except ShiftFlowError as exc:
            return "✖ " + exc.message[:80], 0.0
        if fc.name not in df.columns:
            return f"çalışıyor ({fmt_n(int(vals.notna().sum()))} değer)", None
        orig = df[fc.name]
        same = sum(_same(a, b) for a, b in zip(orig.tolist(), vals.tolist()))
        rate = same / max(1, len(df))
        return f"{fmt_n(same)} / {fmt_n(len(df))} satır aynı", rate

    def _fill(self):
        from PySide6.QtCore import Qt
        self.table.setRowCount(len(self.cols))
        n_ok = 0
        for i, fc in enumerate(self.cols):
            text, rate = self._check(fc)
            name = QTableWidgetItem(f"{fc.name}  ({fc.letter})")
            good = bool(fc.formula) and "[?" not in fc.formula and (rate is None or rate >= 0.99) \
                and not text.startswith("✖")
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.Checked if good else Qt.Unchecked)
            n_ok += good
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem(fc.excel))
            self.table.setItem(i, 2, QTableWidgetItem(fc.formula or "(çevrilemedi)"))
            it = QTableWidgetItem(text)
            from PySide6.QtGui import QColor
            if rate is not None:
                it.setForeground(QColor("#1d6b3a" if rate >= 0.99 else "#a32020"))
            self.table.setItem(i, 3, it)
            self.table.setItem(i, 4, QTableWidgetItem(" ".join(fc.warnings)))
        self.table.resizeRowsToContents()
        if not self.cols:
            set_status(self.status, "Bu tabloda formüllü sütun bulunamadı (ilk veri satırında '=' ile başlayan "
                                    "hücre yok).", "warn")
        else:
            msg = f"{len(self.cols)} formüllü sütun bulundu; {n_ok} tanesi sorunsuz çevrildi ve işaretlendi."
            tail = self._formula_only_rows()
            if tail:
                msg += (f" {fmt_n(tail)} satırda yalnız formül sonucu var (formül verinin altına çekilmiş); bu "
                        "satırlar atılacak, formüller yalnız dolu satırlara uygulanacak.")
            if self.missing:
                msg += " Yüklenmemiş sayfalar yüzünden bazıları çevrilemedi; önce sayfaları yükleyin."
            set_status(self.status, msg, "ok" if n_ok == len(self.cols) else "warn")
        self.ok.setEnabled(bool(self.cols))

    def _formula_only_rows(self) -> int:
        """Formül sütunları dışındaki tüm sütunları boş olan satır sayısı."""
        try:
            df = self.session.result(self.dataset)
        except ShiftFlowError:
            return 0
        names = {fc.name for fc in self.cols}
        rest = [c for c in df.columns if c not in names]
        if not rest:
            return 0
        blank = pd.concat([df[c].isna() | df[c].map(lambda v: isinstance(v, str) and not v.strip())
                           for c in rest], axis=1).all(axis=1)
        return int(blank.sum())

    def _load_missing(self):
        if not self.load_sheet:
            return
        for sh in list(self.missing):
            try:
                self.load_sheet(sh, self.as_ref.isChecked())
            except ShiftFlowError as exc:
                set_status(self.status, "✖ " + exc.message, "err")
                return
        self.reload()

    def selected(self):
        from PySide6.QtCore import Qt
        return [fc for i, fc in enumerate(self.cols) if self.table.item(i, 0).checkState() == Qt.Checked]

    def _accept(self):
        from PySide6.QtWidgets import QMessageBox
        chosen = self.selected()
        bad = [fc for fc in chosen if not fc.formula or "[?" in fc.formula]
        if bad and QMessageBox.question(
                self, "Çevrilemeyen formüller",
                "Şu sütunların ShiftFlow karşılığı yok: " + ", ".join(fc.name for fc in bad) +
                "\n\nBunlar çıktı dosyasına Excel formülü olarak yazılsın mı? (Excel açılınca hesaplanır; "
                "ShiftFlow'daki sonraki adımlarda bu sütunlar kullanılamaz.)",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        letters = {}
        header = None
        for i, r in enumerate(self.grid.rows):
            if self.grid.first_row + i == self.header_row:
                header = r
        if header:
            letters = {xf.col_letter(self.grid.first_col + j): str(v).strip() for j, v in enumerate(header)
                       if v is not None and str(v).strip()}
        steps = []
        for fc in chosen:
            if fc in bad:
                tpl, _ = xf.to_template(fc.excel, letters, self.header_row + 1)
                steps.append({"_op": "excel_formula", "name": fc.name, "template": tpl, "excel": fc.excel})
            else:
                steps.append({"name": fc.name, "formula": fc.formula, "replace": True, "only_filled": True})
        self.steps = steps
        self.accept()
