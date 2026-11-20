"""Rapor paketi penceresi: iş akışlarını listele, kaydet/aç, seçili dönem için hepsini çalıştır."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QProgressDialog, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..engine import package as pk
from ..engine.errors import ShiftFlowError
from .common import show_error


class PackageDialog(QDialog):
    def __init__(self, window, settings, path: str | None = None):
        super().__init__(window)
        self.window_, self.settings = window, settings
        self.path = path
        self.setWindowTitle("Rapor paketi")
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        h = QLabel("Birden çok iş akışını (örn. Toplama, Sevkiyat, Stok) aynı dönem için sırayla çalıştırır. "
                   "Kaynağında çözülmesi gereken bir sorun olan iş akışı atlanır ve özette yazılır; diğerleri "
                   "çalışmaya devam eder. İş akışı dosyaları değiştirilmez.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        f = QFormLayout()
        self.name = QLineEdit("Rapor paketi")
        f.addRow("Paket adı:", self.name)
        lay.addLayout(f)
        row = QHBoxLayout()
        self.list = QListWidget()
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        for txt, fn in (("İş akışı ekle…", self.add), ("Açık akışı ekle", self.add_current), ("▲", lambda: self.move(-1)),
                        ("▼", lambda: self.move(1)), ("Kaldır", self.remove)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch()
        row.addLayout(col)
        lay.addLayout(row, 1)
        g = QGroupBox("Ayarlar")
        gf = QFormLayout(g)
        self.stop = QCheckBox("Bir iş akışı oluşturulamazsa kalanları çalıştırma")
        gf.addRow("", self.stop)
        self.arc = QComboBox()
        self.arc.addItem("Arşivdeki kaydı yeni sonuçla değiştir", "replace")
        self.arc.addItem("Arşive yazma (rapor yine oluşur)", "skip")
        gf.addRow("Dönem arşivde varsa:", self.arc)
        self.mail_on = QCheckBox("Tüm çıktıları tek mailde gönder (her akışın kendi maili yerine)")
        gf.addRow("", self.mail_on)
        self.mail_to = QLineEdit()
        self.mail_to.setPlaceholderText("vardiya-sorumlulari@sirket.com; mudur@sirket.com")
        gf.addRow("Kime:", self.mail_to)
        self.mail_cc = QLineEdit()
        gf.addRow("Bilgi:", self.mail_cc)
        self.mail_subject = QLineEdit("{akis} — {tarih} {vardiya}")
        gf.addRow("Konu:", self.mail_subject)
        lay.addWidget(g)
        bb = QDialogButtonBox()
        b_open = bb.addButton("Paket aç…", QDialogButtonBox.ActionRole)
        b_open.clicked.connect(self.open)
        b_save = bb.addButton("Kaydet…", QDialogButtonBox.ActionRole)
        b_save.clicked.connect(self.save)
        self.b_run = bb.addButton("▶ Paketi çalıştır", QDialogButtonBox.AcceptRole)
        self.b_run.clicked.connect(self.run)
        bb.addButton("Kapat", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.results: list = []
        if path:
            self._load(path)

    # ------------------------------------------------------------ paket
    def package(self) -> pk.ReportPackage:
        return pk.ReportPackage(
            name=self.name.text().strip() or "Rapor paketi",
            workflows=[self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())],
            stop_on_error=self.stop.isChecked(), archive_mode=self.arc.currentData(),
            mail={"enabled": self.mail_on.isChecked(), "to": self.mail_to.text(), "cc": self.mail_cc.text(),
                  "subject": self.mail_subject.text()} if self.mail_on.isChecked() else {})

    def set_package(self, p: pk.ReportPackage):
        self.name.setText(p.name)
        self.list.clear()
        for w in p.workflows:
            self._add_path(w)
        self.stop.setChecked(p.stop_on_error)
        self.arc.setCurrentIndex(max(0, self.arc.findData(p.archive_mode)))
        m = p.mail or {}
        self.mail_on.setChecked(bool(m.get("enabled")))
        self.mail_to.setText(m.get("to", ""))
        self.mail_cc.setText(m.get("cc", ""))
        self.mail_subject.setText(m.get("subject") or "{akis} — {tarih} {vardiya}")

    def _add_path(self, path):
        from PySide6.QtWidgets import QListWidgetItem
        it = QListWidgetItem(f"{os.path.splitext(os.path.basename(path))[0]}    ({path})"
                             + ("" if os.path.exists(path) else "  ✖ dosya yok"))
        it.setData(Qt.UserRole, path)
        self.list.addItem(it)

    def add(self):
        start = self.settings.value("wf_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, "İş akışı ekle", start, "ShiftFlow iş akışı (*.json)")
        for p in paths:
            if not p.endswith(pk.EXT):
                self._add_path(p)

    def add_current(self):
        p = getattr(self.window_, "workflow_path", None)
        if not p:
            QMessageBox.information(self, "Rapor paketi", "Açık iş akışı henüz kaydedilmedi (Ctrl+S).")
            return
        self._add_path(p)

    def move(self, d):
        r = self.list.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(n, it)
        self.list.setCurrentRow(n)

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)

    def _load(self, path):
        try:
            self.set_package(pk.ReportPackage.load(path))
            self.path = path
        except ShiftFlowError as exc:
            show_error(self, exc)

    def open(self):
        start = self.settings.value("wf_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Rapor paketi aç", start, "Rapor paketi (*.sfpaket.json)")
        if path:
            self._load(path)

    def save(self):
        start = self.path or os.path.join(self.settings.value("wf_dir", os.path.expanduser("~")),
                                          (self.name.text().strip() or "paket") + pk.EXT)
        path, _ = QFileDialog.getSaveFileName(self, "Rapor paketini kaydet", start, "Rapor paketi (*.sfpaket.json)")
        if not path:
            return
        if not path.endswith(pk.EXT):
            path = path[:-5] + pk.EXT if path.endswith(".json") else path + pk.EXT
        try:
            self.package().save(path)
            self.path = path
            self.settings.setValue("last_package", path)
        except OSError as exc:
            show_error(self, ShiftFlowError("Paket kaydedilemedi.", detail=str(exc)))

    # ------------------------------------------------------------ çalıştırma
    def run(self):
        p = self.package()
        if not p.workflows:
            QMessageBox.information(self, "Rapor paketi", "Pakete en az bir iş akışı ekleyin.")
            return
        w = self.window_
        period = w.period_bar.period()
        prog = QProgressDialog("Hazırlanıyor…", "", 0, len(p.workflows), self)
        prog.setCancelButton(None)
        prog.setWindowTitle("Rapor paketi çalışıyor")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def progress(i, n, name):
            prog.setValue(i)
            prog.setLabelText(f"{i + 1} / {n}: {name}")
            QApplication.processEvents()
        try:
            # Açık Excel (COM) ana iş parçacığında kullanılır; bu yüzden arka plana alınmaz.
            self.results = pk.run_package(p, w.library, w.provider, w.archive, period, progress)
        finally:
            prog.setValue(len(p.workflows))
            prog.close()
        ResultsDialog(p, self.results, w, period, self).exec()


class ResultsDialog(QDialog):
    def __init__(self, pkg, results, window, period, parent=None):
        super().__init__(parent)
        self.pkg, self.results, self.window_, self.period = pkg, results, window, period
        ok = sum(r.status == "ok" for r in results)
        self.setWindowTitle(f"Paket sonucu — {ok} / {len(results)} oluşturuldu")
        self.resize(900, 460)
        lay = QVBoxLayout(self)
        t = QTableWidget(len(results), 4)
        t.setHorizontalHeaderLabels(["İş akışı", "Durum", "Çıktı / açıklama", ""])
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setWordWrap(True)
        for i, r in enumerate(results):
            t.setItem(i, 0, QTableWidgetItem(r.name))
            t.setItem(i, 1, QTableWidgetItem(r.label))
            t.setItem(i, 2, QTableWidgetItem(r.path or r.message))
            if r.status == "ok" and r.path:
                b = QPushButton("Aç")
                b.clicked.connect(lambda _=False, path=r.path: self._open(path))
                t.setCellWidget(i, 3, b)
            elif r.status in ("skipped", "error"):
                b = QPushButton("Akışı aç")
                b.setToolTip("Bu iş akışını ana pencerede açar; Rapor oluştur ile sorunu çözebilirsiniz")
                b.clicked.connect(lambda _=False, wf=r.workflow: (self.accept(), self.parent().accept(),
                                                                  self.window_.open_workflow(wf)))
                t.setCellWidget(i, 3, b)
        t.resizeRowsToContents()
        lay.addWidget(t, 1)
        self.table = t
        bb = QDialogButtonBox()
        self.draft = pk.combined_draft(pkg, results, period)
        if self.draft is not None:
            bm = bb.addButton("Birleşik maili hazırla…", QDialogButtonBox.ActionRole)
            bm.clicked.connect(self.mail)
        own = [r for r in results if r.draft is not None]
        if own:
            bo = bb.addButton(f"Mailleri önizle ({len(own)})…", QDialogButtonBox.ActionRole)
            bo.clicked.connect(lambda: self.own_mails(own))
        bb.addButton("Kapat", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        lay.addWidget(bb)

    def _open(self, path):
        if hasattr(os, "startfile"):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                pass

    def mail(self):
        from .stage_dialogs import MailPreviewDialog
        MailPreviewDialog(self.draft, self.window_.outlook, self).exec()

    def own_mails(self, items):
        from .stage_dialogs import MailPreviewDialog
        for r in items:
            d = MailPreviewDialog(r.draft, self.window_.outlook, self)
            d.setWindowTitle(f"Mail önizleme — {r.name}")
            if d.exec() != QDialog.Accepted and d.result_action is None:
                break
