"""İşlem diyalogları.

Her diyalog aynı kalıbı izler:
  - `build()` alanları oluşturur (düzenleme için mevcut parametrelerle doldurur),
  - `params()` işlem parametrelerini sözlük olarak döner,
  - her değişiklikte kısa bir gecikmeyle sonuç önizlenir; hata varsa
    "Uygula" düğmesi kapanır ve sebep diyalogda yazılır.
Diyaloglar veriyi değiştirmez; yalnızca parametre üretir. Uygulama işini
oturum (Session) yapar.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine import operations as ops
from ..engine.errors import JoinConfirmationRequired, ShiftFlowError
from ..engine.values import normalize_key
from .common import (
    ColumnChecklist,
    ConditionEditor,
    PreviewTable,
    column_combo,
    fmt_n,
    set_status,
    status_label,
)


class OpDialog(QDialog):
    op_key = ""
    title = ""
    help_text = ""
    needs_name = False
    default_name = ""
    show_preview = True

    def __init__(self, df: pd.DataFrame | None, params=None, preset=None, parent=None,
                 dataset_label: str = "", name: str | None = None, session=None, dataset: str | None = None,
                 context: dict | None = None):
        super().__init__(parent)
        # Birleştirme/alt alta ekleme diyalogları oturumu üst sınıf çağrılmadan önce ayarlar.
        self.session = session if session is not None else getattr(self, "session", None)
        self.dataset, self.context = dataset, context
        self.df = df
        self.p = dict(params or {})
        self.preset = preset
        self.setWindowTitle(self.title)
        self.resize(760, 600)
        root = QVBoxLayout(self)
        if dataset_label:
            lab = QLabel(f"Çalışılan veri kümesi: <b>{dataset_label}</b>")
            lab.setObjectName("dialogTarget")
            root.addWidget(lab)
        if self.help_text:
            h = QLabel(self.help_text)
            h.setWordWrap(True)
            h.setObjectName("dialogHelp")
            root.addWidget(h)
        self.body = QVBoxLayout()
        root.addLayout(self.body)
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self.refresh)
        if self.needs_name:
            f = QFormLayout()
            self.name_edit = QLineEdit(name or self.default_name)
            f.addRow("Yeni veri kümesinin adı:", self.name_edit)
            root.addLayout(f)
        self.build()
        self.status = status_label()
        root.addWidget(self.status)
        if self.show_preview:
            self.preview = PreviewTable(rows=100)
            root.addWidget(self.preview, 1)
            if getattr(self, "_pending_colors", None):
                self.preview.model_.set_header_colors(self._pending_colors)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Help)
        self.buttons.button(QDialogButtonBox.Ok).setText("Uygula")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        self.buttons.button(QDialogButtonBox.Help).setText("Yardım (F1)")
        self.buttons.helpRequested.connect(self.show_help)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("F1"), self, self.show_help)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._ready = True
        QTimer.singleShot(0, self.refresh)

    # alt sınıfların doldurduğu kısımlar -------------------------------
    def build(self):
        raise NotImplementedError

    def params(self) -> dict:
        raise NotImplementedError

    def frames(self) -> list[pd.DataFrame]:
        return [self.df]

    def dataset_name(self) -> str:
        return self.name_edit.text().strip() if self.needs_name else ""

    # ortak davranış ----------------------------------------------------
    def schedule(self, *_):
        self._timer.start()

    def summary(self, res: ops.OpResult) -> tuple[str, str]:
        before = sum(len(f) for f in self.frames()) if self.op_key == "append" else len(self.frames()[0])
        lines = [f"Sonuç: {fmt_n(len(res.df))} satır × {fmt_n(res.df.shape[1])} sütun (önce {fmt_n(before)} satır)"]
        lines += [m for m in res.messages if not m.startswith("Sonuç:")]
        kind = "ok"
        if res.warnings:
            lines += ["⚠ " + w for w in res.warnings]
            kind = "warn"
        return "\n".join(lines), kind

    def show_help(self):
        from .help import show_help
        show_help(self, self.op_key)

    def refresh(self):
        if not getattr(self, "_ready", False):
            return
        ok = self.buttons.button(QDialogButtonBox.Ok)
        try:
            p = self.params()
            if self.needs_name and not self.dataset_name():
                raise ShiftFlowError("Yeni veri kümesi için bir ad girin.")
            op = ops.get(self.op_key)
            if op.uses_context:
                p = dict(p, __context__=self.context)
            sess = getattr(self, "session", None)
            if op.uses_params and sess is not None and sess.parameters:
                p = dict(p, __params__=sess.parameters)
            res = op.run(self.frames(), p, "önizleme")
        except JoinConfirmationRequired as exc:
            set_status(self.status, "⚠ " + exc.message + "\nUygula derseniz onayınız istenecek.", "warn")
            ok.setEnabled(True)
            if self.show_preview:
                self.preview.set_frame(None)
            return
        except ShiftFlowError as exc:
            self._last_error = exc
            where = ""
            if getattr(exc, "pos", None) is not None and hasattr(self, "formula") and hasattr(self.formula, "line_col"):
                ln, col = self.formula.line_col(exc.pos)
                where = f" (satır {ln}, karakter {col})"
            set_status(self.status, "✖ " + exc.message + where, "err")
            ok.setEnabled(False)
            if self.show_preview:
                self.preview.set_frame(None)
            return
        except Exception as exc:  # beklenmeyen: kullanıcıya gösterilir, program çökmez
            set_status(self.status, f"✖ Beklenmeyen hata: {exc}", "err")
            ok.setEnabled(False)
            return
        self._last_error = None
        text, kind = self.summary(res)
        set_status(self.status, text, kind)
        ok.setEnabled(True)
        if self.show_preview:
            self.preview.set_frame(res.df)
            self.after_preview(res)

    def after_preview(self, res):
        pass


# ======================================================================= filtre
class FilterDialog(OpDialog):
    op_key = "filter"
    title = "Filtre"
    help_text = "Koşulları sağlamayan satırlar elenir. Kaynak veri değişmez; filtre bir adım olarak kaydedilir."

    def build(self):
        self.tabs = QTabWidget()
        conds = self.p.get("conditions", [])
        in_list = [c for c in conds if c.get("op") == "in_list"]
        # Koşul sekmesi
        self.editor = ConditionEditor(self.df, conds, self.p.get("mode", "and"), preset_column=self.preset)
        self.editor.changed.connect(self.schedule)
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.addWidget(self.editor)
        l1.addStretch()
        self.tabs.addTab(w1, "Koşullar")
        # Değer listesi sekmesi (Excel'in otomatik filtresi gibi)
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        top = QHBoxLayout()
        top.addWidget(QLabel("Sütun:"))
        preset = in_list[0]["column"] if in_list else self.preset
        self.v_col = column_combo(self.df.columns, preset)
        top.addWidget(self.v_col, 1)
        l2.addLayout(top)
        self.v_search = QLineEdit(placeholderText="Değer ara…")
        l2.addWidget(self.v_search)
        self.v_list = QListWidget()
        l2.addWidget(self.v_list, 1)
        row = QHBoxLayout()
        for txt, on in (("Tümünü seç", True), ("Hiçbirini seçme", False)):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, on=on: self._set_all(on))
            row.addWidget(b)
        row.addStretch()
        l2.addLayout(row)
        self.tabs.addTab(w2, "Değer listesi")
        self.body.addWidget(self.tabs)
        self._preselect = set(map(str, in_list[0]["value"])) if in_list else None
        self.v_col.currentTextChanged.connect(self._fill_values)
        self.v_search.textChanged.connect(self._search)
        self.v_list.itemChanged.connect(self.schedule)
        self.tabs.currentChanged.connect(self.schedule)
        self._fill_values()
        if in_list:
            self.tabs.setCurrentIndex(1)

    def _fill_values(self):
        self.v_list.blockSignals(True)
        self.v_list.clear()
        col = self.v_col.currentText()
        if col in self.df.columns:
            keys = normalize_key(self.df[col]).map(lambda k: ops.EMPTY_LABEL if k is None else k)
            counts = keys.value_counts()
            for val, n in list(counts.items())[:5000]:
                it = QListWidgetItem(f"{val}    ({fmt_n(n)})")
                it.setData(Qt.UserRole, val)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                on = self._preselect is None or val in self._preselect
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
                self.v_list.addItem(it)
        self._preselect = None
        self.v_list.blockSignals(False)
        self.schedule()

    def _search(self, t):
        t = t.lower()
        for i in range(self.v_list.count()):
            it = self.v_list.item(i)
            it.setHidden(t not in str(it.data(Qt.UserRole)).lower())

    def _set_all(self, on):
        self.v_list.blockSignals(True)
        for i in range(self.v_list.count()):
            it = self.v_list.item(i)
            if not it.isHidden():
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.v_list.blockSignals(False)
        self.schedule()

    def params(self):
        if self.tabs.currentIndex() == 1:
            vals = [self.v_list.item(i).data(Qt.UserRole) for i in range(self.v_list.count())
                    if self.v_list.item(i).checkState() == Qt.Checked]
            if not vals:
                raise ShiftFlowError("En az bir değer seçin.")
            return {"conditions": [{"column": self.v_col.currentText(), "op": "in_list", "value": vals}], "mode": "and"}
        return {"conditions": self.editor.conditions(), "mode": self.editor.mode()}


# ======================================================================= sıralama
class SortDialog(OpDialog):
    op_key = "sort"
    title = "Sırala"
    help_text = "Birden çok sütun seçerseniz önce ilk sütuna, eşitlikte sonrakine göre sıralanır."

    def build(self):
        self.rows = []
        self.box = QVBoxLayout()
        self.body.addLayout(self.box)
        keys = self.p.get("keys") or [{"column": self.preset, "ascending": self.p.get("_asc", True)}]
        for k in keys:
            self.add_row(k)
        b = QPushButton("+ Sıralama düzeyi ekle")
        b.clicked.connect(lambda: self.add_row({}))
        h = QHBoxLayout()
        h.addWidget(b)
        h.addStretch()
        self.body.addLayout(h)

    def add_row(self, k):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        col = column_combo(self.df.columns, k.get("column"))
        d = QComboBox()
        d.addItem("Küçükten büyüğe / A→Z", True)
        d.addItem("Büyükten küçüğe / Z→A", False)
        d.setCurrentIndex(0 if k.get("ascending", True) else 1)
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        h.addWidget(QLabel("Sütun:"))
        h.addWidget(col, 1)
        h.addWidget(d)
        h.addWidget(rm)
        entry = (w, col, d)
        self.rows.append(entry)
        self.box.addWidget(w)
        col.currentTextChanged.connect(self.schedule)
        d.currentIndexChanged.connect(self.schedule)
        rm.clicked.connect(lambda: self._rm(entry))
        self.schedule()

    def _rm(self, entry):
        if len(self.rows) > 1:
            self.rows.remove(entry)
            entry[0].setParent(None)
            self.schedule()

    def params(self):
        return {"keys": [{"column": c.currentText(), "ascending": d.currentData()} for _, c, d in self.rows]}


# ======================================================================= hesaplama
class CalcDialog(OpDialog):
    op_key = "calc"
    title = "Hesaplanan sütun"
    help_text = ("Excel formülü gibi yazın. Sütun adları köşeli parantez içinde: [Miktar] * [Birim Fiyat]. "
                 "Metin birleştirmek için &, karşılaştırma için = <> < > <= >=. EĞER, VE, YUVARLA, SOLDAN, SAAT gibi "
                 "fonksiyonlar kullanılabilir. Sıfıra bölmede sonuç boş kalır.")

    def build(self):
        self.resize(1040, 820)
        f = QFormLayout()
        self.name = QLineEdit(self.p.get("name", ""))
        self.name.setPlaceholderText("örn. Gerçekleşme %")
        f.addRow("Yeni sütun adı:", self.name)
        self.body.addLayout(f)
        from PySide6.QtWidgets import QSplitter
        from .formula_editor import FormulaEdit
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        left = QVBoxLayout(top)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("Formül:"))
        self.formula = FormulaEdit(columns=self.df.columns)
        self.formula.setPlainText(self.p.get("formula", ""))
        self.formula.setPlaceholderText("[Toplanan] / [Hedef] * 100     ('[' yazınca sütunlar, harf yazınca fonksiyonlar önerilir)")
        self.formula.setMinimumHeight(120)
        left.addWidget(self.formula, 1)
        self.sig = QLabel()
        self.sig.setObjectName("signature")
        self.sig.setTextFormat(Qt.RichText)
        self.formula.signatureChanged.connect(lambda t: self.sig.setText(t))
        left.addWidget(self.sig)
        tools = QHBoxLayout()
        for text, tip, fn in (
                ("Düzenle", "Uzun formülü girintili, okunur hâle getirir (Ctrl+Shift+F)", self.formula.format),
                ("Tek satır", "Formülü tek satıra toplar", self.formula.to_one_line),
                ("Seçimi dene", "Formülün seçili parçasını ilk satırlar için hesaplar", self._try_selection)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addSpacing(16)
        for sym in ("+", "-", "*", "/", "(", ")", "&", "=", "<>", ">", ">=", ";"):
            b = QPushButton("&&" if sym == "&" else sym)  # Qt'de tek & kısayol işaretidir
            b.setFixedWidth(34)
            b.clicked.connect(lambda _=False, s=sym: self._insert(f" {s} " if s not in "();" else s + (" " if s == ";" else "")))
            tools.addWidget(b)
        tools.addStretch()
        self.replace = QCheckBox("Aynı adlı sütun varsa üzerine yaz")
        self.replace.setChecked(self.p.get("replace", False))
        tools.addWidget(self.replace)
        self.only_filled = QCheckBox("Yalnız dolu satırlar")
        self.only_filled.setToolTip("Formüldeki sütunların hepsi boş olan satırlarda sonuç boş kalır (Excel'de "
                                    "formülü verinin bittiği yere kadar çekmek gibi).")
        self.only_filled.setChecked(self.p.get("only_filled", not self.p))  # yeni adımlarda açık
        tools.addWidget(self.only_filled)
        b_xl = QPushButton("Excel formülü yapıştır…")
        b_xl.setToolTip("Excel'deki =EĞER(DÜŞEYARA(B2;…)) gibi bir formülü ShiftFlow formülüne çevirir")
        b_xl.clicked.connect(self._from_excel)
        tools.addWidget(b_xl)
        left.addLayout(tools)
        split.addWidget(top)
        bottom = QWidget()
        h = QHBoxLayout(bottom)
        h.setContentsMargins(0, 0, 0, 0)
        cl = QVBoxLayout()
        cl.addWidget(QLabel("Sütunlar (eklemek için çift tıklayın):"))
        self.cols = QListWidget()
        self.cols.addItems([str(c) for c in self.df.columns])
        self.cols.itemDoubleClicked.connect(lambda it: self._insert(f"[{it.text()}]"))
        cl.addWidget(self.cols)
        h.addLayout(cl, 1)
        fn = QVBoxLayout()
        fn.addWidget(QLabel("Fonksiyonlar (çift tıklayın):"))
        self.funcs = QListWidget()
        from ..engine.expression import FUNCTION_HELP
        for name, usage, desc in FUNCTION_HELP:
            it = QListWidgetItem(f"{name}  —  {desc}")
            it.setToolTip(f"{usage}\n{desc}")
            it.setData(Qt.UserRole, usage)
            self.funcs.addItem(it)
        self.funcs.itemDoubleClicked.connect(self._insert_func)
        self.funcs.currentItemChanged.connect(
            lambda it, _p=None: self.func_help.setText(f"{it.data(Qt.UserRole)} — {it.toolTip().splitlines()[-1]}") if it else None)
        fn.addWidget(self.funcs)
        h.addLayout(fn, 2)
        split.addWidget(bottom)
        split.setSizes([260, 150])
        self.body.addWidget(split, 1)
        if self.preset and not self.p:
            self.formula.setPlainText(f"[{self.preset}]")
        self.name.textChanged.connect(self.schedule)
        self.formula.textChanged.connect(self.schedule)
        self.replace.toggled.connect(self.schedule)
        self.only_filled.toggled.connect(self.schedule)
        self.formula.columnsColored.connect(self._color_columns)
        self.formula.columnClicked.connect(self._show_column)
        self.formula.excelPasted.connect(lambda t: self._from_excel(t))
        self.formula.translate_paste = True
        self._pending_colors = self.formula.column_colors()
        self.func_help = QLabel("Fonksiyon bağımsız değişkenleri ';' ile ayrılır: EĞER([A] > 0; \"Var\"; \"Yok\")")
        self.func_help.setObjectName("dialogHelp")
        self.func_help.setWordWrap(True)
        self.func_help.setTextFormat(Qt.RichText)
        self.body.addWidget(self.func_help)

    def _insert(self, text):
        self.formula.insertPlainText(text)
        self.formula.setFocus()

    def _try_selection(self):
        from ..engine import expression as ex
        sel = self.formula.textCursor().selectedText().replace("\u2029", "\n").strip()
        if not sel:
            self.func_help.setText("Önce formülde denemek istediğiniz parçayı seçin (örn. bir DÜŞEYARA(…) ya da EĞER'in koşulu).")
            return
        try:
            frames = self.frames_for(sel)
            names = ex.referenced_tables(sel)
            vals, _ = ex.evaluate(sel, self.df.head(5), "seçim", dict(zip(names, frames[1:])))
        except ShiftFlowError as exc:
            self.func_help.setText(f"<span style='color:#a32020'>Seçim hesaplanamadı: {exc.message}</span>")
            return
        from .table_model import format_value
        shown = "; ".join(f"{i + 1}. satır: <b>{format_value(v) or '(boş)'}</b>" for i, v in enumerate(vals.tolist()))
        self.func_help.setText(f"Seçim <code>{sel[:60]}{'…' if len(sel) > 60 else ''}</code> → {shown}")

    def frames_for(self, formula_text):
        from ..engine.operations import _formula_refs
        names = _formula_refs({"formula": formula_text}, ["formula"])
        out = [self.df]
        for n in names:
            if self.session is None or n not in self.session.workflow.datasets:
                raise ShiftFlowError(f"Formüldeki '{n}' tablosu yok.")
            out.append(self.session.result(n))
        return out

    def refresh(self):
        super().refresh()
        err = getattr(self, "_last_error", None)
        self.formula.set_error(getattr(err, "pos", None) if err else None)

    def _from_excel(self, text=""):
        """Excel formülünü çevirir. text verilirse (yapıştırma) pencere o formülle açılır."""
        from .formula_dialogs import FormulaImportDialog
        d = FormulaImportDialog(self.session, self.dataset, self.df, self, mode="insert", text=text or "")
        if d.exec() == QDialog.Accepted and d.formula:
            if text and self.formula.toPlainText().strip():
                self.formula.insertPlainText(d.formula)  # yapıştırma: imlecin olduğu yere
            else:
                self.formula.setPlainText(d.formula)

    def _color_columns(self, colors):
        """Formülde kullanılan sütunlar önizleme başlığında ve listede aynı renkle görünür."""
        self._pending_colors = colors
        if getattr(self, "preview", None) is not None:
            self.preview.model_.set_header_colors(colors)
        if hasattr(self, "cols"):
            from PySide6.QtGui import QBrush, QColor
            for i in range(self.cols.count()):
                it = self.cols.item(i)
                c = colors.get(it.text())
                it.setForeground(QBrush(QColor(c)) if c else QBrush())
                f = it.font()
                f.setBold(bool(c))
                it.setFont(f)

    def showEvent(self, e):
        super().showEvent(e)
        self._color_columns(getattr(self, "_pending_colors", {}))

    def _show_column(self, name):
        if getattr(self, "preview", None) is None:
            return
        cols = [str(c) for c in self.preview.model_.frame().columns]
        if name in cols:
            self.preview.scrollTo(self.preview.model_.index(0, cols.index(name)))

    def frames(self):
        from ..engine.operations import _formula_refs
        names = _formula_refs({"formula": self.formula.toPlainText()}, ["formula"])
        if not names:
            return [self.df]
        if self.session is None:
            raise ShiftFlowError("Bu pencerede başka tablolara başvurulamıyor.")
        out = [self.df]
        for n in names:
            if n not in self.session.workflow.datasets:
                raise ShiftFlowError(f"Formüldeki '{n}' tablosu yok. Veri kümeleri: "
                                     + ", ".join(self.session.workflow.datasets))
            if self.dataset and (n == self.dataset or n in self.session.workflow.dependents_of(self.dataset)):
                raise ShiftFlowError(f"'{n}' bu tablodan türediği için formülde kullanılamaz (döngü olur).")
            out.append(self.session.result(n))
        return out

    def _insert_func(self, it):
        usage = it.data(Qt.UserRole)
        name = usage.split("(")[0]
        self._insert(name + "(")

    def params(self):
        out = {"name": self.name.text().strip(), "formula": self.formula.toPlainText().strip(),
               "replace": self.replace.isChecked()}
        if self.only_filled.isChecked() or "only_filled" in self.p:
            out["only_filled"] = self.only_filled.isChecked()
        return out

    def after_preview(self, res):
        name = self.name.text().strip()
        if name in res.df.columns:
            i = list(res.df.columns).index(name)
            self.preview.scrollTo(self.preview.model().index(0, i))


def _ref_frames(dlg, params, keys):
    from ..engine.operations import _formula_refs
    names = _formula_refs(params, keys)
    out = [dlg.df]
    for n in names:
        if dlg.session is None or n not in dlg.session.workflow.datasets:
            raise ShiftFlowError(f"Formüldeki '{n}' tablosu yok.")
        out.append(dlg.session.result(n))
    return out


class ConditionalDialog(OpDialog):
    op_key = "conditional"
    title = "Koşullu sütun (EĞER)"
    help_text = ("Koşul sağlanırsa 'Doğruysa' değeri, sağlanmazsa 'Yanlışsa' değeri yazılır. "
                 "Değer düz metin (Yüksek), sayı (0) veya formül ([Toplanan] * 2) olabilir.")

    def build(self):
        f = QFormLayout()
        self.name = QLineEdit(self.p.get("name", ""))
        self.name.setPlaceholderText("örn. Performans Durumu")
        f.addRow("Yeni sütun adı:", self.name)
        self.body.addLayout(f)
        g = QGroupBox("Koşul")
        gl = QVBoxLayout(g)
        self.editor = ConditionEditor(self.df, self.p.get("conditions"), self.p.get("mode", "and"), self.preset)
        gl.addWidget(self.editor)
        self.body.addWidget(g)
        f2 = QFormLayout()
        self.then = QLineEdit(str(self.p.get("then", "")))
        self.else_ = QLineEdit(str(self.p.get("else", "")))
        from .formula_editor import attach_editor_button
        f2.addRow("Doğruysa:", attach_editor_button(self.then, self.df.columns))
        f2.addRow("Yanlışsa:", attach_editor_button(self.else_, self.df.columns))
        self.replace = QCheckBox("Aynı adlı sütun varsa üzerine yaz")
        self.replace.setChecked(self.p.get("replace", False))
        f2.addRow("", self.replace)
        self.body.addLayout(f2)
        for w in (self.name, self.then, self.else_):
            w.textChanged.connect(self.schedule)
        self.editor.changed.connect(self.schedule)
        self.replace.toggled.connect(self.schedule)

    def params(self):
        return {"name": self.name.text().strip(), "conditions": self.editor.conditions(), "mode": self.editor.mode(),
                "then": self.then.text(), "else": self.else_.text(), "replace": self.replace.isChecked()}

    def frames(self):
        return _ref_frames(self, {"then": self.then.text(), "else": self.else_.text()}, ["then", "else"])


# ======================================================================= sütunlar
class SelectColumnsDialog(OpDialog):
    op_key = "select"
    title = "Sütunları seç ve sırala"
    help_text = "İşaretli sütunlar listedeki sırayla tutulur, diğerleri kaldırılır."

    def build(self):
        checked = self.p.get("columns") or list(self.df.columns)
        self.list = ColumnChecklist(self.df.columns, checked, orderable=True)
        self.list.changed.connect(self.schedule)
        self.body.addWidget(self.list)

    def params(self):
        return {"columns": self.list.checked()}


class RemoveColumnsDialog(OpDialog):
    op_key = "remove"
    title = "Sütun kaldır"

    def build(self):
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.changed.connect(self.schedule)
        self.body.addWidget(QLabel("Kaldırılacak sütunları işaretleyin:"))
        self.body.addWidget(self.list)

    def params(self):
        return {"columns": self.list.checked()}


class RenameDialog(OpDialog):
    op_key = "rename"
    title = "Sütunları yeniden adlandır"
    help_text = "Yalnızca değiştirmek istediğiniz satırlarda yeni adı düzenleyin."

    def build(self):
        mapping = self.p.get("mapping", {})
        self.table = QTableWidget(len(self.df.columns), 2)
        self.table.setHorizontalHeaderLabels(["Mevcut ad", "Yeni ad"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        for i, c in enumerate(self.df.columns):
            a = QTableWidgetItem(str(c))
            a.setFlags(a.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, QTableWidgetItem(str(mapping.get(c, c))))
        self.table.setColumnWidth(0, 260)
        self.table.itemChanged.connect(self.schedule)
        self.body.addWidget(self.table)
        if self.preset in list(self.df.columns):
            r = list(self.df.columns).index(self.preset)
            self.table.setCurrentCell(r, 1)
            QTimer.singleShot(0, lambda: self.table.editItem(self.table.item(r, 1)))

    def params(self):
        m = {}
        for i in range(self.table.rowCount()):
            old, new = self.table.item(i, 0).text(), self.table.item(i, 1).text().strip()
            if new != old:
                m[old] = new
        if not m:
            raise ShiftFlowError("Hiçbir ad değiştirilmedi.")
        return {"mapping": m}


class ConvertDialog(OpDialog):
    op_key = "convert"
    title = "Veri tipi dönüştür"
    help_text = ("Metin olarak gelen sayıları ('1.234,56') sayıya, tarihleri ('31.12.2026') tarihe çevirir. "
                 "Çevrilemeyen değerler boş bırakılır ve sayısı gösterilir.")

    def build(self):
        f = QFormLayout()
        self.col = column_combo(self.df.columns, self.p.get("column", self.preset))
        self.to = QComboBox()
        for k, v in ops.TYPE_TARGETS.items():
            self.to.addItem(v, k)
        if self.p.get("to"):
            self.to.setCurrentIndex(self.to.findData(self.p["to"]))
        self.strict = QCheckBox("Çevrilemeyen değer varsa işlemi durdur (hata ver)")
        self.strict.setChecked(self.p.get("strict", False))
        f.addRow("Sütun:", self.col)
        f.addRow("Yeni tip:", self.to)
        f.addRow("", self.strict)
        self.body.addLayout(f)
        self.col.currentTextChanged.connect(self.schedule)
        self.to.currentIndexChanged.connect(self.schedule)
        self.strict.toggled.connect(self.schedule)

    def params(self):
        return {"column": self.col.currentText(), "to": self.to.currentData(), "strict": self.strict.isChecked()}


class TextCleanDialog(OpDialog):
    op_key = "text_clean"
    title = "Metin temizle"
    help_text = "Baştaki/sondaki boşlukları siler, çoklu boşlukları teke indirir, büyük-küçük harfi Türkçe kurallarla düzenler."

    def build(self):
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(200)
        self.body.addWidget(self.list)
        h = QHBoxLayout()
        self.trim = QCheckBox("Baş/son boşlukları sil")
        self.trim.setChecked(self.p.get("trim", True))
        self.collapse = QCheckBox("Çoklu boşlukları teke indir")
        self.collapse.setChecked(self.p.get("collapse_spaces", True))
        self.case = QComboBox()
        for k, v in ops.TEXT_CASES.items():
            self.case.addItem(v, k)
        self.case.setCurrentIndex(max(0, self.case.findData(self.p.get("case", "none"))))
        h.addWidget(self.trim)
        h.addWidget(self.collapse)
        h.addWidget(QLabel("Harf:"))
        h.addWidget(self.case)
        h.addStretch()
        self.body.addLayout(h)
        self.list.changed.connect(self.schedule)
        self.trim.toggled.connect(self.schedule)
        self.collapse.toggled.connect(self.schedule)
        self.case.currentIndexChanged.connect(self.schedule)

    def params(self):
        return {"columns": self.list.checked(), "trim": self.trim.isChecked(),
                "collapse_spaces": self.collapse.isChecked(), "case": self.case.currentData()}


class UnifyDialog(OpDialog):
    op_key = "unify"
    title = "Yazımı birleştir"
    help_text = ("Aynı değerin boşluk veya büyük/küçük harf farkıyla yazılmış hâllerini ('Ege', 'Ege ', 'ege') "
                 "en sık kullanılan yazılışa çevirir. Her yeni raporda yeniden uygulanır.")

    def build(self):
        from ..engine import variants
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        found = {c: variants.find_variants(self.df[c]) for c in self.df.columns}
        found = {c: v for c, v in found.items() if v}
        if not checked:
            checked = list(found)
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(200)
        self.body.addWidget(self.list)
        if found:
            txt = "Farklı yazılış bulunan sütunlar: " + ", ".join(
                f"{c} ({len(v)} değer)" for c, v in found.items())
        else:
            txt = "Şu anki veride farklı yazılış bulunmadı. Adım yine de eklenebilir; yeni raporlarda uygulanır."
        lab = QLabel(txt)
        lab.setWordWrap(True)
        self.body.addWidget(lab)
        self.list.changed.connect(self.schedule)

    def params(self):
        return {"columns": self.list.checked()}


class DropEmptyRowsDialog(OpDialog):
    op_key = "drop_empty_rows"
    title = "Boş satırları kaldır"
    help_text = ("İşaretli sütunların hepsi boş olan satırları kaldırır. Excel'de formülleri verinin altına kadar "
                 "çekilmiş raporlarda formül sütunlarının işaretini kaldırın; yalnız gerçek veri sütunlarına bakılır.")

    def build(self):
        ignore = set(self.p.get("ignore") or [])
        checked = [c for c in (self.p.get("columns") or list(map(str, self.df.columns))) if c not in ignore]
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(240)
        self.body.addWidget(self.list)
        self.list.changed.connect(self.schedule)

    def params(self):
        chosen = self.list.checked()
        return {"ignore": [str(c) for c in self.df.columns if str(c) not in chosen]}


class ValidateDialog(OpDialog):
    op_key = "validate"
    title = "Doğrula"
    help_text = ("Rapor dağıtılmadan önce veriyi kontrol eder; veriyi değiştirmez. 'Uyar' seçilen kontroller "
                 "sağlanmazsa rapor uyarıyla oluşur; 'Raporu durdur' seçilenler sağlanmazsa Rapor oluştur ve Excel'e "
                 "aktar çıktı yazmaz. Formül kontrolünde parametre kullanılabilir: [Toplanan] <= {Üst Sınır}.")

    def build(self):
        self.resize(980, 640)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Kontrol", "Sütun", "Değer / alt sınır / formül", "Üst sınır",
                                              "Sağlanmazsa"])
        self.table.verticalHeader().setVisible(False)
        from PySide6.QtWidgets import QHeaderView
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(180)
        self.body.addWidget(self.table)
        row = QHBoxLayout()
        b_add = QPushButton("Kontrol ekle")
        b_add.clicked.connect(lambda: (self._add({"check": "not_empty", "column": self.preset or str(self.df.columns[0])}),
                                       self.schedule()))
        b_del = QPushButton("Seçiliyi sil")
        b_del.clicked.connect(lambda: (self.table.removeRow(self.table.currentRow()), self.schedule()))
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch()
        self.body.addLayout(row)
        for c in self.p.get("checks") or [{"check": "not_empty", "column": self.preset or str(self.df.columns[0])}]:
            self._add(c)

    def _add(self, c):
        r = self.table.rowCount()
        self.table.insertRow(r)
        kind = QComboBox()
        for k, v in ops.CHECKS.items():
            kind.addItem(v, k)
        kind.setCurrentIndex(max(0, kind.findData(c.get("check", "not_empty"))))
        col = column_combo(self.df.columns, c.get("column"))
        val = QLineEdit(str(c.get("formula") if c.get("check") == "formula" else
                            c.get("min", c.get("value", "")) or ""))
        hi = QLineEdit(str(c.get("max", "") or ""))
        fail = QComboBox()
        fail.addItem("Uyar", "warn")
        fail.addItem("Raporu durdur", "stop")
        fail.setCurrentIndex(1 if c.get("on_fail") == "stop" else 0)
        for w, i in ((kind, 0), (col, 1), (val, 2), (hi, 3), (fail, 4)):
            self.table.setCellWidget(r, i, w)
        for sig in (kind.currentIndexChanged, col.currentIndexChanged, fail.currentIndexChanged):
            sig.connect(self.schedule)
        for w in (val, hi):
            w.textChanged.connect(self.schedule)
        kind.currentIndexChanged.connect(lambda *_: self._sync(r))
        self._sync(r)

    def _sync(self, r):
        k = self.table.cellWidget(r, 0).currentData()
        self.table.cellWidget(r, 1).setEnabled(k in ("not_empty", "unique", "range"))
        self.table.cellWidget(r, 3).setEnabled(k == "range")
        ph = {"min_rows": "örn. 100", "range": "alt sınır (boş: yok)", "formula": "örn. [Toplanan] <= [Hedef] * 2",
              "not_empty": "", "unique": ""}[k]
        self.table.cellWidget(r, 2).setPlaceholderText(ph)
        self.table.cellWidget(r, 2).setEnabled(k in ("min_rows", "range", "formula"))

    def params(self):
        checks = []
        for r in range(self.table.rowCount()):
            k = self.table.cellWidget(r, 0).currentData()
            c = {"check": k, "on_fail": self.table.cellWidget(r, 4).currentData()}
            v = self.table.cellWidget(r, 2).text().strip()
            if k in ("not_empty", "unique", "range"):
                c["column"] = self.table.cellWidget(r, 1).currentText()
            if k == "min_rows":
                c["value"] = v
            elif k == "range":
                c["min"], c["max"] = v, self.table.cellWidget(r, 3).text().strip()
            elif k == "formula":
                c["formula"] = v
            checks.append(c)
        return {"checks": checks}


class FillDownDialog(OpDialog):
    op_key = "fill_down"
    title = "Aşağı doldur"
    help_text = ("Boş hücrelere üstteki dolu değeri yazar. Birleştirilmiş hücreli veya grup başlığı yalnız ilk "
                 "satırda yazan raporlar (Bölge, Ekip…) için.")

    def build(self):
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(220)
        self.body.addWidget(self.list)
        h = QHBoxLayout()
        self.dir = QComboBox()
        self.dir.addItem("Üstteki değerle (aşağı doldur)", "down")
        self.dir.addItem("Alttaki değerle (yukarı doldur)", "up")
        self.dir.setCurrentIndex(0 if self.p.get("direction", "down") == "down" else 1)
        h.addWidget(self.dir)
        h.addStretch()
        self.body.addLayout(h)
        self.list.changed.connect(self.schedule)
        self.dir.currentIndexChanged.connect(self.schedule)

    def params(self):
        return {"columns": self.list.checked(), "direction": self.dir.currentData()}


class FillEmptyDialog(OpDialog):
    op_key = "fill_empty"
    title = "Boşları doldur"
    help_text = "Seçili sütunlardaki boş hücrelere sabit bir değer yazar (örn. sayılarda 0, metinde 'Tanımsız')."

    def build(self):
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(220)
        self.body.addWidget(self.list)
        f = QFormLayout()
        self.value = QLineEdit(str(self.p.get("value", "0")))
        f.addRow("Yazılacak değer:", self.value)
        self.body.addLayout(f)
        self.list.changed.connect(self.schedule)
        self.value.textChanged.connect(self.schedule)

    def params(self):
        return {"columns": self.list.checked(), "value": self.value.text()}


class SplitDialog(OpDialog):
    op_key = "split"
    title = "Sütunlara böl"
    help_text = ("Bir sütundaki metni parçalara ayırır (Excel'deki 'Metni sütunlara dönüştür'). "
                 "Örn. lokasyon 'A-01-03' → Bölge, Koridor, Raf. Başında sıfır olan parçalar metin kalır.")

    def build(self):
        f = QFormLayout()
        self.col = column_combo(self.df.columns, self.p.get("column", self.preset))
        f.addRow("Bölünecek sütun:", self.col)
        self.mode = QComboBox()
        self.mode.addItem("Ayırıcıya göre", "delimiter")
        self.mode.addItem("Sabit karakter sayısına göre", "positions")
        self.mode.setCurrentIndex(0 if self.p.get("mode", "delimiter") == "delimiter" else 1)
        f.addRow("Bölme şekli:", self.mode)
        self.delim = QComboBox()
        self.delim.setEditable(True)
        for d in ("-", "/", ";", ",", "|", "_", ".", "boşluk"):
            self.delim.addItem(d)
        self.delim.setCurrentText(self.p.get("delimiter", "-"))
        f.addRow("Ayırıcı:", self.delim)
        from PySide6.QtWidgets import QSpinBox
        self.maxn = QSpinBox()
        self.maxn.setRange(0, 50)
        self.maxn.setSpecialValueText("hepsi")
        self.maxn.setValue(int(self.p.get("max_parts") or 0))
        f.addRow("En fazla parça:", self.maxn)
        self.positions = QLineEdit(str(self.p.get("positions", "")))
        self.positions.setPlaceholderText("örn. 1,2,2  → ilk 1 karakter, sonra 2, sonra 2")
        f.addRow("Karakter sayıları:", self.positions)
        self.names = QLineEdit(", ".join(self.p.get("names", [])))
        self.names.setPlaceholderText("örn. Bölge, Koridor, Raf  (boş bırakılırsa Lokasyon 1, Lokasyon 2…)")
        f.addRow("Yeni sütun adları:", self.names)
        self.keep = QCheckBox("Özgün sütunu koru")
        self.keep.setChecked(self.p.get("keep", True))
        f.addRow("", self.keep)
        self.body.addLayout(f)
        for w in (self.col, self.mode, self.delim, self.maxn):
            sig = getattr(w, "currentIndexChanged", None) or getattr(w, "valueChanged")
            sig.connect(self.schedule)
        self.delim.editTextChanged.connect(self.schedule)
        self.maxn.valueChanged.connect(self.schedule)
        for w in (self.positions, self.names):
            w.textChanged.connect(self.schedule)
        self.keep.toggled.connect(self.schedule)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self):
        d = self.mode.currentData() == "delimiter"
        self.delim.setEnabled(d)
        self.maxn.setEnabled(d)
        self.positions.setEnabled(not d)

    def params(self):
        return {"column": self.col.currentText(), "mode": self.mode.currentData(),
                "delimiter": self.delim.currentText(), "max_parts": self.maxn.value(),
                "positions": self.positions.text().strip(),
                "names": [x.strip() for x in self.names.text().split(",") if x.strip()],
                "keep": self.keep.isChecked()}


class UnpivotDialog(OpDialog):
    op_key = "unpivot"
    title = "Sütunları satırlara çevir"
    help_text = ("Yan yana duran sütunları (Gece | Gündüz | Akşam veya günler) iki sütuna indirir: adı ve değeri. "
                 "Böylece gruplanabilir, filtrelenebilir. Seçilmeyen sütunlar her satırda tekrar eder.")

    def build(self):
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(220)
        self.body.addWidget(QLabel("Satırlara çevrilecek sütunlar:"))
        self.body.addWidget(self.list)
        f = QFormLayout()
        self.name_col = QLineEdit(self.p.get("name_column", "Öznitelik"))
        self.value_col = QLineEdit(self.p.get("value_column", "Değer"))
        f.addRow("Sütun adlarının yazılacağı yeni sütun:", self.name_col)
        self.drop = QCheckBox("Boş değerli satırları atla")
        self.drop.setChecked(self.p.get("drop_empty", True))
        f.addRow("Değerlerin yazılacağı yeni sütun:", self.value_col)
        f.addRow("", self.drop)
        self.body.addLayout(f)
        self.list.changed.connect(self.schedule)
        for w in (self.name_col, self.value_col):
            w.textChanged.connect(self.schedule)
        self.drop.toggled.connect(self.schedule)

    def params(self):
        return {"columns": self.list.checked(), "name_column": self.name_col.text().strip(),
                "value_column": self.value_col.text().strip(), "drop_empty": self.drop.isChecked()}


class ReplaceDialog(OpDialog):
    op_key = "replace"
    title = "Bul ve değiştir"

    def build(self):
        f = QFormLayout()
        self.col = column_combo(self.df.columns, self.p.get("column", self.preset))
        self.find = QLineEdit(str(self.p.get("find", "")))
        self.repl = QLineEdit(str(self.p.get("replace", "")))
        self.whole = QCheckBox("Yalnızca hücrenin tamamı eşleşirse değiştir (büyük/küçük harf duyarsız)")
        self.whole.setChecked(self.p.get("whole_cell", False))
        f.addRow("Sütun:", self.col)
        f.addRow("Aranan:", self.find)
        f.addRow("Yeni değer:", self.repl)
        f.addRow("", self.whole)
        self.body.addLayout(f)
        for w in (self.find, self.repl):
            w.textChanged.connect(self.schedule)
        self.col.currentTextChanged.connect(self.schedule)
        self.whole.toggled.connect(self.schedule)

    def params(self):
        return {"column": self.col.currentText(), "find": self.find.text(), "replace": self.repl.text(),
                "whole_cell": self.whole.isChecked()}


class DedupeDialog(OpDialog):
    op_key = "dedupe"
    title = "Tekrarlı kayıtları kaldır"
    help_text = ("Seçili sütunlarda aynı değerlere sahip satırlardan yalnızca biri tutulur. "
                 "Hiç sütun seçmezseniz tüm sütunları aynı olan satırlar tekrar sayılır.")

    def build(self):
        checked = self.p.get("columns") or ([self.preset] if self.preset else [])
        self.list = ColumnChecklist(self.df.columns, checked)
        self.list.setMaximumHeight(220)
        self.body.addWidget(self.list)
        h = QHBoxLayout()
        self.keep = QComboBox()
        self.keep.addItem("İlk görüleni tut", "first")
        self.keep.addItem("Son görüleni tut", "last")
        self.keep.setCurrentIndex(0 if self.p.get("keep", "first") == "first" else 1)
        h.addWidget(self.keep)
        h.addStretch()
        self.body.addLayout(h)
        self.list.changed.connect(self.schedule)
        self.keep.currentIndexChanged.connect(self.schedule)

    def params(self):
        return {"columns": self.list.checked(), "keep": self.keep.currentData()}


# ======================================================================= birleştirme
class JoinDialog(OpDialog):
    op_key = "join"
    title = "İki veri kümesini birleştir"
    help_text = ("Ortak anahtar sütun(lar) üzerinden sağdaki tablonun sütunları soldakine eklenir. "
                 "Eşleşme sayıları ve satır çoğalması aşağıda gösterilir; hatalı birleştirmeler sessizce uygulanmaz.")
    needs_name = True
    default_name = "Birleşik"

    def __init__(self, session, left=None, right=None, params=None, parent=None, name=None, inputs=None):
        self.session = session
        self.names = list(session.workflow.datasets)
        if inputs:
            left, right = inputs
        self._left0, self._right0 = left, right
        self.key_rows = []
        super().__init__(None, params, parent=parent, name=name)
        self.resize(900, 700)

    def build(self):
        g = QGridLayout()
        self.left = QComboBox()
        self.right = QComboBox()
        self.left.addItems(self.names)
        self.right.addItems(self.names)
        if self._left0:
            self.left.setCurrentText(self._left0)
        if self._right0:
            self.right.setCurrentText(self._right0)
        elif len(self.names) > 1:
            self.right.setCurrentIndex(1 if self.left.currentIndex() == 0 else 0)
        self.how = QComboBox()
        for k, v in ops.JOIN_TYPES.items():
            self.how.addItem(v, k)
        self.how.setCurrentIndex(max(0, self.how.findData(self.p.get("how", "left"))))
        g.addWidget(QLabel("Sol veri kümesi:"), 0, 0)
        g.addWidget(self.left, 0, 1)
        g.addWidget(QLabel("Sağ veri kümesi:"), 0, 2)
        g.addWidget(self.right, 0, 3)
        g.addWidget(QLabel("Birleştirme türü:"), 1, 0)
        g.addWidget(self.how, 1, 1, 1, 3)
        self.body.addLayout(g)
        kb = QGroupBox("Anahtar sütunlar (eşleştirme alanları)")
        self.keys_box = QVBoxLayout(kb)
        self.body.addWidget(kb)
        h = QHBoxLayout()
        add = QPushButton("+ Anahtar ekle")
        add.clicked.connect(lambda: self.add_key())
        self.match_col = QCheckBox(f"Sonuca '{ops.MATCH_COL}' sütunu ekle (eşleşmeyenleri filtrelemek için)")
        self.match_col.setChecked(self.p.get("add_match_column", False))
        h.addWidget(add)
        h.addWidget(self.match_col)
        h.addStretch()
        self.body.addLayout(h)
        self.left.currentTextChanged.connect(self._reset_keys)
        self.right.currentTextChanged.connect(self._reset_keys)
        self.how.currentIndexChanged.connect(self.schedule)
        self.match_col.toggled.connect(self.schedule)
        if self.p.get("left_keys"):
            for a, b in zip(self.p["left_keys"], self.p["right_keys"]):
                self.add_key(a, b)
        else:
            self._reset_keys()

    def _frame(self, name):
        return self.session.result(name)

    def frames(self):
        return [self._frame(self.left.currentText()), self._frame(self.right.currentText())]

    def _reset_keys(self):
        for w, *_ in self.key_rows:
            w.setParent(None)
        self.key_rows.clear()
        try:
            lf, rf = self.frames()
        except ShiftFlowError:
            self.schedule()
            return
        common = [c for c in lf.columns if c in rf.columns]
        if common:
            self.add_key(common[0], common[0])
        else:
            self.add_key()
        self.schedule()

    def add_key(self, a=None, b=None):
        try:
            lf, rf = self.frames()
        except ShiftFlowError:
            return
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        ca, cb = column_combo(lf.columns, a), column_combo(rf.columns, b)
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        h.addWidget(QLabel("Sol:"))
        h.addWidget(ca, 1)
        h.addWidget(QLabel("="))
        h.addWidget(QLabel("Sağ:"))
        h.addWidget(cb, 1)
        h.addWidget(rm)
        entry = (w, ca, cb)
        self.key_rows.append(entry)
        self.keys_box.addWidget(w)
        ca.currentTextChanged.connect(self.schedule)
        cb.currentTextChanged.connect(self.schedule)
        rm.clicked.connect(lambda: self._rm_key(entry))
        self.schedule()

    def _rm_key(self, entry):
        if len(self.key_rows) > 1:
            self.key_rows.remove(entry)
            entry[0].setParent(None)
            self.schedule()

    def inputs(self):
        return [self.left.currentText(), self.right.currentText()]

    def params(self):
        if self.left.currentText() == self.right.currentText():
            raise ShiftFlowError("Sol ve sağ veri kümesi aynı olamaz.")
        p = {
            "how": self.how.currentData(),
            "left_keys": [a.currentText() for _, a, _b in self.key_rows],
            "right_keys": [b.currentText() for _, _a, b in self.key_rows],
            "right_label": self.right.currentText(),
            "add_match_column": self.match_col.isChecked(),
        }
        if self.p.get("allow_many_to_many"):
            p["allow_many_to_many"] = True
        return p


class AppendDialog(OpDialog):
    op_key = "append"
    title = "Alt alta ekle"
    help_text = "Seçili veri kümelerinin satırları alt alta eklenir. Sütunlar adlarına göre eşlenir."
    needs_name = True
    default_name = "Birleştirilmiş Liste"

    def __init__(self, session, current=None, params=None, parent=None, name=None, inputs=None):
        self.session = session
        self.names = list(session.workflow.datasets)
        self._checked = inputs or ([current] if current else [])
        super().__init__(None, params, parent=parent, name=name)

    def build(self):
        self.list = ColumnChecklist(self.names, self._checked, orderable=True)
        self.list.changed.connect(self.schedule)
        self.body.addWidget(QLabel("Eklenecek veri kümeleri (sırayla):"))
        self.body.addWidget(self.list)
        f = QFormLayout()
        self.src_col = QLineEdit(self.p.get("source_column", "Kaynak"))
        self.src_col.setToolTip("Boş bırakırsanız kaynak sütunu eklenmez.")
        f.addRow("Kaynak adını yazan sütun:", self.src_col)
        self.body.addLayout(f)
        self.src_col.textChanged.connect(self.schedule)

    def inputs(self):
        return self.list.checked()

    def frames(self):
        return [self.session.result(n) for n in self.inputs()]

    def params(self):
        if len(self.inputs()) < 2:
            raise ShiftFlowError("En az iki veri kümesi seçin.")
        return {"labels": self.inputs(), "source_column": self.src_col.text().strip()}


# ======================================================================= gruplama ve pivot
class ValueList(QWidget):
    """Değer alanları: (sütun, hesaplama) satırları."""

    def __init__(self, columns, values, on_change, parent=None):
        super().__init__(parent)
        self.columns, self.on_change = list(columns), on_change
        self.rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.box = QVBoxLayout()
        lay.addLayout(self.box)
        b = QPushButton("+ Değer alanı ekle")
        b.clicked.connect(lambda: self.add())
        h = QHBoxLayout()
        h.addWidget(b)
        h.addStretch()
        lay.addLayout(h)
        for v in values:
            self.add(v)

    def add(self, v=None):
        v = v or {}
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        col = column_combo(self.columns, v.get("column"))
        fn = QComboBox()
        for k, lab in ops.AGG_FUNCS.items():
            fn.addItem(lab, k)
        fn.setCurrentIndex(max(0, fn.findData(v.get("func", "sum"))))
        name = QLineEdit(v.get("name", ""))
        name.setPlaceholderText("sütun adı (isteğe bağlı)")
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        h.addWidget(col, 2)
        h.addWidget(fn, 1)
        h.addWidget(name, 2)
        h.addWidget(rm)
        entry = (w, col, fn, name)
        self.rows.append(entry)
        self.box.addWidget(w)
        col.currentTextChanged.connect(self.on_change)
        fn.currentIndexChanged.connect(self.on_change)
        name.textChanged.connect(self.on_change)
        rm.clicked.connect(lambda: self._rm(entry))
        self.on_change()

    def set_columns(self, columns):
        self.columns = list(columns)

    def _rm(self, entry):
        self.rows.remove(entry)
        entry[0].setParent(None)
        self.on_change()

    def values(self):
        out = []
        for _, c, f, n in self.rows:
            v = {"column": c.currentText(), "func": f.currentData()}
            if n.text().strip():
                v["name"] = n.text().strip()
            out.append(v)
        return out


def _default_value(df):
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    return {"column": nums[0], "func": "sum"} if nums else {"column": df.columns[0], "func": "count"}


class SummaryOptions(QWidget):
    """Grupla/Pivot ortak seçenekleri: tarih gruplama, değere göre sıralama, ilk N (pivotta: yüzde gösterimi)."""

    def __init__(self, p, on_change, pivot=False, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QSpinBox
        f = QFormLayout(self)
        f.setContentsMargins(0, 0, 0, 0)
        self.date = QComboBox()
        for k, v in ops.DATE_GROUPS.items():
            self.date.addItem(v, k)
        self.date.setCurrentIndex(max(0, self.date.findData(p.get("date_group", "none"))))
        self.date.setToolTip("Tarih/saat alanlarını saate, güne, haftaya veya aya göre gruplar (Excel pivotundaki gibi)")
        f.addRow("Tarih alanlarını grupla:", self.date)
        self.show_as = None
        if pivot:
            self.show_as = QComboBox()
            for k, v in ops.SHOW_AS.items():
                self.show_as.addItem(v, k)
            self.show_as.setCurrentIndex(max(0, self.show_as.findData(p.get("show_as", "value"))))
            f.addRow("Değerleri göster:", self.show_as)
            self.show_as.currentIndexChanged.connect(on_change)
        self.sort = QCheckBox("Değere göre büyükten küçüğe sırala")
        self.sort.setChecked(bool(p.get("sort_by_value")))
        f.addRow("", self.sort)
        self.top = QSpinBox()
        self.top.setRange(0, 100000)
        self.top.setSpecialValueText("hepsi")
        self.top.setValue(int(p.get("top_n") or 0))
        f.addRow("Yalnız ilk N satır:", self.top)
        self.date.currentIndexChanged.connect(on_change)
        self.sort.toggled.connect(on_change)
        self.top.valueChanged.connect(on_change)

    def params(self):
        out = {}
        if self.date.currentData() != "none":
            out["date_group"] = self.date.currentData()
        if self.show_as is not None and self.show_as.currentData() != "value":
            out["show_as"] = self.show_as.currentData()
        if self.sort.isChecked():
            out["sort_by_value"] = True
        if self.top.value():
            out["top_n"] = self.top.value()
        return out


class GroupDialog(OpDialog):
    op_key = "group"
    title = "Grupla ve özetle"
    help_text = "Seçili sütunların her farklı değer birleşimi için bir satır oluşur; değer alanları hesaplanır."
    needs_name = True
    default_name = "Özet"

    def build(self):
        h = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Gruplama sütunları:"))
        by = self.p.get("by") or ([self.preset] if self.preset else [])
        self.by = ColumnChecklist(self.df.columns, by, orderable=True)
        self.by.changed.connect(self.schedule)
        left.addWidget(self.by)
        h.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Hesaplamalar:"))
        self.vals = ValueList(self.df.columns, self.p.get("values") or [_default_value(self.df)], self.schedule)
        right.addWidget(self.vals)
        self.opts = SummaryOptions(self.p, self.schedule)
        right.addWidget(self.opts)
        right.addStretch()
        h.addLayout(right, 2)
        self.body.addLayout(h)

    def params(self):
        return {"by": self.by.checked(), "values": self.vals.values(), **self.opts.params()}


class FieldList(QWidget):
    def __init__(self, title, items, on_change, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(title))
        self.list = QListWidget()
        self.list.addItems(items)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setMaximumHeight(130)
        # Sürükle-bırak: alanlar listesinden buraya bırakılabilir, kendi içinde sıralanabilir
        self.list.setDragDropMode(QAbstractItemView.DragDrop)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, self._after_drop))
        lay.addWidget(self.list)
        h = QHBoxLayout()
        for txt, fn in (("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1)), ("Kaldır", self._remove)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            h.addWidget(b)
        lay.addLayout(h)
        self.on_change = on_change

    def items(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _after_drop(self):
        """Bırakılan alan tekrar ediyorsa veya diğer listede de varsa düzelt."""
        seen = set()
        for i in reversed(range(self.list.count())):
            t = self.list.item(i).text()
            if t in seen:
                self.list.takeItem(i)
            seen.add(t)
        other = getattr(self, "other", None)
        if other is not None:  # aynı alan hem satırda hem sütunda olamaz: son bırakılan yer geçerli
            mine = set(self.items())
            for j in reversed(range(other.list.count())):
                if other.list.item(j).text() in mine:
                    other.list.takeItem(j)
        self.on_change()

    def add(self, name):
        if name and name not in self.items():
            self.list.addItem(name)
            self.on_change()

    def _move(self, d):
        r = self.list.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(n, it)
        self.list.setCurrentRow(n)
        self.on_change()

    def _remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)
            self.on_change()


class PivotDialog(OpDialog):
    op_key = "pivot"
    title = "Pivot tablo"
    help_text = ("Alanı seçip 'Satıra' veya 'Sütuna' ekleyin, ardından değer alanlarını belirleyin. "
                 "Birden fazla satır alanı ve birden fazla değer/hesaplama desteklenir.")
    needs_name = True
    default_name = "Pivot"

    def build(self):
        self.resize(980, 760)
        h = QHBoxLayout()
        avail = QVBoxLayout()
        avail.addWidget(QLabel("Alanlar:"))
        self.fields = QListWidget()
        self.fields.addItems([str(c) for c in self.df.columns])
        self.fields.setDragDropMode(QAbstractItemView.DragOnly)
        self.fields.setDefaultDropAction(Qt.CopyAction)
        self.fields.setToolTip("Alanı sürükleyip Satır veya Sütun alanlarına bırakabilirsiniz")
        avail.addWidget(self.fields)
        bh = QHBoxLayout()
        to_r, to_c = QPushButton("→ Satıra"), QPushButton("→ Sütuna")
        to_r.clicked.connect(lambda: self._add(self.rows))
        to_c.clicked.connect(lambda: self._add(self.cols))
        self.fields.itemDoubleClicked.connect(lambda *_: self._add(self.rows))
        bh.addWidget(to_r)
        bh.addWidget(to_c)
        avail.addLayout(bh)
        h.addLayout(avail, 1)
        mid = QVBoxLayout()
        rows = self.p.get("rows") or ([self.preset] if self.preset else [])
        self.rows = FieldList("Satır alanları:", rows, self.schedule)
        self.cols = FieldList("Sütun alanları:", self.p.get("columns", []), self.schedule)
        self.rows.other, self.cols.other = self.cols, self.rows
        mid.addWidget(self.rows)
        mid.addWidget(self.cols)
        h.addLayout(mid, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Değer alanları:"))
        self.vals = ValueList(self.df.columns, self.p.get("values") or [_default_value(self.df)], self.schedule)
        right.addWidget(self.vals)
        self.totals = QCheckBox("Genel toplam satır/sütunu ekle")
        self.totals.setChecked(self.p.get("totals", True))
        self.totals.toggled.connect(self.schedule)
        right.addWidget(self.totals)
        self.opts = SummaryOptions(self.p, self.schedule, pivot=True)
        right.addWidget(self.opts)
        right.addStretch()
        h.addLayout(right, 2)
        self.body.addLayout(h)

    def _add(self, target):
        it = self.fields.currentItem()
        if it:
            for fl in (self.rows, self.cols):
                if fl is not target and it.text() in fl.items():
                    return
            target.add(it.text())

    def params(self):
        return {"rows": self.rows.items(), "columns": self.cols.items(), "values": self.vals.values(),
                "totals": self.totals.isChecked(), **self.opts.params()}


# ======================================================================= DÜŞEYARA
class LookupDialog(OpDialog):
    op_key = "lookup"
    title = "Eşleştir (DÜŞEYARA)"
    help_text = ("Başka bir tablodan (referans tablo, personel listesi…) anahtar sütuna göre değer getirir. "
                 "Satır sayısı değişmez. Büyük/küçük harf ve baştaki/sondaki boşluk fark etmez. "
                 "Bulunamayan ve arama tablosunda birden çok kez geçen anahtarlar ayrıca bildirilir.")

    def build(self):
        self.resize(900, 720)
        wf = self.session.workflow
        blocked = set(wf.dependents_of(self.dataset)) | {self.dataset}
        self.tables = [n for n in wf.datasets if n not in blocked]
        f = QFormLayout()
        self.table = QComboBox()
        self.table.addItems(self.tables)
        if self.p.get("table") in self.tables:
            self.table.setCurrentText(self.p["table"])
        f.addRow("Arama tablosu:", self.table)
        self.body.addLayout(f)
        if not self.tables:
            self.body.addWidget(QLabel("Kullanılabilir başka veri kümesi yok. Önce arama tablosunu (referans tablo, "
                                       "dosya veya açık Excel) ekleyin."))
        kb = QGroupBox("Anahtar sütunlar")
        self.keys_box = QVBoxLayout(kb)
        self.body.addWidget(kb)
        add = QPushButton("+ Anahtar ekle")
        add.clicked.connect(lambda: self.add_key())
        h = QHBoxLayout()
        h.addWidget(add)
        h.addStretch()
        self.body.addLayout(h)
        g = QGroupBox("Getirilecek sütunlar (işaretleyin; isterseniz yeni ad verin)")
        gl = QVBoxLayout(g)
        self.cols = QTableWidget(0, 3)
        self.cols.setHorizontalHeaderLabels(["Getir", "Arama tablosundaki sütun", "Yeni sütun adı"])
        self.cols.verticalHeader().setVisible(False)
        self.cols.horizontalHeader().setStretchLastSection(True)
        self.cols.setColumnWidth(0, 50)
        self.cols.setColumnWidth(1, 260)
        self.cols.setMaximumHeight(170)
        self.cols.itemChanged.connect(self.schedule)
        gl.addWidget(self.cols)
        self.body.addWidget(g)
        f2 = QFormLayout()
        self.missing = QLineEdit(str(self.p.get("if_missing", "")))
        self.missing.setPlaceholderText("boş bırakılabilir (örn. Tanımsız veya 0)")
        self.dup = QComboBox()
        self.dup.addItem("İlk bulunanı al ve uyar (Excel gibi)", "first")
        self.dup.addItem("İşlemi durdur", "error")
        self.dup.setCurrentIndex(0 if self.p.get("on_duplicate", "first") == "first" else 1)
        self.replace = QCheckBox("Aynı adlı sütun varsa üzerine yaz")
        self.replace.setChecked(self.p.get("replace", False))
        f2.addRow("Bulunamazsa:", self.missing)
        f2.addRow("Arama tablosunda tekrar varsa:", self.dup)
        f2.addRow("", self.replace)
        self.body.addLayout(f2)
        self.key_rows = []
        self.table.currentTextChanged.connect(self._table_changed)
        self.missing.textChanged.connect(self.schedule)
        self.dup.currentIndexChanged.connect(self.schedule)
        self.replace.toggled.connect(self.schedule)
        self._table_changed(initial=True)

    def table_frame(self):
        name = self.table.currentText()
        if not name:
            raise ShiftFlowError("Arama tablosu seçin.")
        return self.session.result(name)

    def frames(self):
        return [self.df, self.table_frame()]

    def _table_changed(self, *_, initial=False):
        for w, *_r in self.key_rows:
            w.setParent(None)
        self.key_rows.clear()
        self.cols.blockSignals(True)
        self.cols.setRowCount(0)
        try:
            t = self.table_frame()
        except ShiftFlowError:
            self.cols.blockSignals(False)
            self.schedule()
            return
        keys = self.p.get("keys") if initial and self.p.get("keys") else None
        if keys:
            for a, b in keys:
                self.add_key(a, b)
        else:
            common = [c for c in self.df.columns if c in t.columns]
            self.add_key(common[0] if common else None, common[0] if common else None)
        chosen = {c["column"]: c.get("as") or c["column"] for c in (self.p.get("columns") or [])} if initial else {}
        key_right = {b.currentText() for _, _a, b in self.key_rows}
        for c in t.columns:
            r = self.cols.rowCount()
            self.cols.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if str(c) in chosen else Qt.Unchecked)
            self.cols.setItem(r, 0, chk)
            it = QTableWidgetItem(str(c))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            if str(c) in key_right:
                it.setToolTip("Anahtar sütun")
            self.cols.setItem(r, 1, it)
            self.cols.setItem(r, 2, QTableWidgetItem(chosen.get(str(c), str(c))))
        self.cols.blockSignals(False)
        self.schedule()

    def add_key(self, a=None, b=None):
        try:
            t = self.table_frame()
        except ShiftFlowError:
            return
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        ca, cb = column_combo(self.df.columns, a), column_combo(t.columns, b)
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        h.addWidget(QLabel("Bu tabloda:"))
        h.addWidget(ca, 1)
        h.addWidget(QLabel("="))
        h.addWidget(QLabel("Arama tablosunda:"))
        h.addWidget(cb, 1)
        h.addWidget(rm)
        entry = (w, ca, cb)
        self.key_rows.append(entry)
        self.keys_box.addWidget(w)
        ca.currentTextChanged.connect(self.schedule)
        cb.currentTextChanged.connect(self.schedule)
        rm.clicked.connect(lambda: (len(self.key_rows) > 1) and (self.key_rows.remove(entry), w.setParent(None), self.schedule()))
        self.schedule()

    def params(self):
        cols = []
        for r in range(self.cols.rowCount()):
            if self.cols.item(r, 0).checkState() == Qt.Checked:
                src = self.cols.item(r, 1).text()
                new = (self.cols.item(r, 2).text() or "").strip() or src
                cols.append({"column": src, "as": new} if new != src else {"column": src})
        return {"table": self.table.currentText(),
                "keys": [[a.currentText(), b.currentText()] for _, a, b in self.key_rows],
                "columns": cols, "if_missing": self.missing.text(), "on_duplicate": self.dup.currentData(),
                "replace": self.replace.isChecked()}


# ======================================================================= kural tablosu
class RulesDialog(OpDialog):
    op_key = "rules"
    title = "Kural tablosu"
    help_text = ("Kurallar yukarıdan aşağıya denenir; bir satıra İLK uyan kuralın değeri yazılır. Hiçbirine uymayan "
                 "satırlara 'Hiçbiri uymazsa' değeri yazılır. Değer düz metin, sayı veya formül olabilir "
                 "([Miktar] * 2). Koşulda başka bir sütunla karşılaştırmak için değere [Sütun] yazın.")

    def build(self):
        self.resize(980, 760)
        f = QFormLayout()
        self.name = QLineEdit(self.p.get("name", ""))
        self.name.setPlaceholderText("örn. Performans Sınıfı")
        f.addRow("Yeni sütun adı:", self.name)
        self.body.addLayout(f)
        h = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list)
        row = QHBoxLayout()
        for text, fn in (("+ Kural", self.add_rule), ("Sil", self.del_rule), ("▲", lambda: self.move(-1)),
                         ("▼", lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        left.addLayout(row)
        h.addLayout(left, 1)
        self.editor_box = QVBoxLayout()
        right = QGroupBox("Seçili kural")
        right.setLayout(self.editor_box)
        h.addWidget(right, 2)
        self.body.addLayout(h)
        f2 = QFormLayout()
        self.default = QLineEdit(str(self.p.get("default", "")))
        self.default.setPlaceholderText("boş bırakılabilir")
        self.default.textChanged.connect(self.schedule)
        self.replace = QCheckBox("Aynı adlı sütun varsa üzerine yaz")
        self.replace.setChecked(self.p.get("replace", False))
        self.replace.toggled.connect(self.schedule)
        from .formula_editor import attach_editor_button
        f2.addRow("Hiçbiri uymazsa:", attach_editor_button(self.default, self.df.columns))
        f2.addRow("", self.replace)
        self.body.addLayout(f2)
        self.name.textChanged.connect(self.schedule)
        self.rules = [dict(r) for r in (self.p.get("rules") or [])] or [
            {"conditions": [{"column": self.preset or str(self.df.columns[0]), "op": "eq", "value": ""}], "mode": "and", "value": ""}]
        self.cur = -1
        self.editor = None
        self._fill()
        self.list.setCurrentRow(0)

    def _fill(self):
        self.list.blockSignals(True)
        self.list.clear()
        for i, r in enumerate(self.rules, start=1):
            conds = " VE ".join(ops.describe_condition(c) for c in r.get("conditions", [])) if r.get("mode") != "or" \
                else " VEYA ".join(ops.describe_condition(c) for c in r.get("conditions", []))
            self.list.addItem(f"{i}) {conds or '…'}  →  {r.get('value', '')}")
        self.list.blockSignals(False)

    def _store(self):
        if self.editor is None or not 0 <= self.cur < len(self.rules):
            return
        try:
            conds = self.editor.conditions()
        except ShiftFlowError:
            conds = [r.condition() for r in self.editor.rows]
        self.rules[self.cur] = {"conditions": conds, "mode": self.editor.mode(), "value": self.value.text()}

    def _select(self, row):
        self._store()
        while self.editor_box.count():
            w = self.editor_box.takeAt(0).widget()
            if w:
                w.setParent(None)
        self.cur = row
        if not 0 <= row < len(self.rules):
            self.editor = None
            return
        r = self.rules[row]
        self.editor = ConditionEditor(self.df, r.get("conditions"), r.get("mode", "and"))
        self.editor.changed.connect(self._changed)
        self.editor_box.addWidget(self.editor)
        w = QWidget()
        fl = QFormLayout(w)
        self.value = QLineEdit(str(r.get("value", "")))
        self.value.setPlaceholderText("örn. Hedefte  ·  0  ·  [Miktar] * 2")
        self.value.textChanged.connect(self._changed)
        from .formula_editor import attach_editor_button
        fl.addRow("Değer:", attach_editor_button(self.value, self.df.columns))
        self.editor_box.addWidget(w)

    def _changed(self, *_):
        self._store()
        cur = self.cur
        self._fill()
        self.list.blockSignals(True)
        self.list.setCurrentRow(cur)
        self.list.blockSignals(False)
        self.schedule()

    def add_rule(self):
        self._store()
        self.rules.append({"conditions": [{"column": str(self.df.columns[0]), "op": "eq", "value": ""}], "mode": "and", "value": ""})
        self._fill()
        self.list.setCurrentRow(len(self.rules) - 1)

    def del_rule(self):
        if len(self.rules) <= 1 or self.cur < 0:
            return
        del self.rules[self.cur]
        self.cur = -1
        self.editor = None
        self._fill()
        self.list.setCurrentRow(0)
        self.schedule()

    def move(self, d):
        self._store()
        i, j = self.cur, self.cur + d
        if not (0 <= i < len(self.rules) and 0 <= j < len(self.rules)):
            return
        self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
        self.cur = -1
        self.editor = None
        self._fill()
        self.list.setCurrentRow(j)
        self.schedule()

    def params(self):
        self._store()
        for i, r in enumerate(self.rules, start=1):
            for c in r["conditions"]:
                if c["op"] not in ops.NO_VALUE_OPS and not str(c.get("value", "")).strip():
                    raise ShiftFlowError(f"{i}. kuralda '{c['column']}' koşulu için değer girin.")
        return {"name": self.name.text().strip(), "rules": self.rules, "default": self.default.text(),
                "replace": self.replace.isChecked()}

    def frames(self):
        return _ref_frames(self, {"default": self.default.text(), "rules": self.rules}, ["default", "rules"])


# ======================================================================= dönem filtresi
class PeriodFilterDialog(OpDialog):
    op_key = "period_filter"
    title = "Dönem filtresi (vardiya / gün)"
    help_text = ("Seçili döneme düşen satırlar kalır. Dönem, araç çubuğundaki tarih ve vardiya seçiminden gelir; "
                 "adımın içine saat yazılmaz. Böylece aynı iş akışı her vardiya için çalışır.")

    def build(self):
        f = QFormLayout()
        dates = [c for c in self.df.columns if pd.api.types.is_datetime64_any_dtype(self.df[c])]
        others = [c for c in self.df.columns if c not in dates]
        self.col = column_combo(dates + others, self.p.get("column") or (dates[0] if dates else self.preset))
        self.scope = QComboBox()
        self.scope.addItem("Seçili vardiya (vardiya saatleri)", "period")
        self.scope.addItem("Seçili günün tamamı", "day")
        self.scope.setCurrentIndex(0 if self.p.get("scope", "period") == "period" else 1)
        f.addRow("Tarih/saat sütunu:", self.col)
        f.addRow("Aralık:", self.scope)
        self.body.addLayout(f)
        from ..engine.periods import from_context
        per = from_context(self.context)
        lab = QLabel(f"Şu an seçili dönem: <b>{per.label}</b>" if per else "Dönem seçilmedi.")
        self.body.addWidget(lab)
        self.col.currentTextChanged.connect(self.schedule)
        self.scope.currentIndexChanged.connect(self.schedule)

    def params(self):
        return {"column": self.col.currentText(), "scope": self.scope.currentData()}


# Adım türü -> diyalog sınıfı (düzenleme için)
STEP_DIALOGS = {
    "filter": FilterDialog, "sort": SortDialog, "calc": CalcDialog, "conditional": ConditionalDialog,
    "select": SelectColumnsDialog, "remove": RemoveColumnsDialog, "rename": RenameDialog,
    "convert": ConvertDialog, "text_clean": TextCleanDialog, "replace": ReplaceDialog, "dedupe": DedupeDialog,
    "lookup": LookupDialog, "rules": RulesDialog, "period_filter": PeriodFilterDialog,
    "unify": UnifyDialog, "fill_down": FillDownDialog, "fill_empty": FillEmptyDialog, "split": SplitDialog,
    "unpivot": UnpivotDialog, "drop_empty_rows": DropEmptyRowsDialog, "validate": ValidateDialog,
}
DERIVED_DIALOGS = {"group": GroupDialog, "pivot": PivotDialog}
