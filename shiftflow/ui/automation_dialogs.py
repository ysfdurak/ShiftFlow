"""Otomasyon pencereleri: WMS ekran teşhisi ve zamanlanmış görev komutu."""

from __future__ import annotations

import os

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from ..engine import wms_probe as wp
from ..engine.errors import ShiftFlowError
from .common import busy, set_status, show_error, status_label


class WmsProbeDialog(QDialog):
    """WMS penceresini tarar; ekran otomasyonuna uygun mu söyler. Hiçbir şeye tıklamaz."""

    def __init__(self, parent=None, desktop_factory=None):
        super().__init__(parent)
        self.factory = desktop_factory
        self.result = None
        self.setWindowTitle("WMS ekranını incele")
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        h = QLabel("1) WMS'i açın ve raporu çalıştıracağınız ekrana gelin (rapor filtre penceresi açıkken en iyisi).\n"
                   "2) Aşağıdan WMS penceresini seçip <b>İncele</b>'ye basın.\n\n"
                   "ShiftFlow pencerenin menü, düğme ve alanlarının adlarını okur; hiçbir şeye tıklamaz, yazmaz. "
                   "Alanların içeriği ve tablo verisi okunmaz. Rapor yalnız bu bilgisayara kaydedilir.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        row = QHBoxLayout()
        self.windows = QComboBox()
        self.windows.setMinimumWidth(520)
        row.addWidget(self.windows, 1)
        b_ref = QPushButton("Listeyi yenile")
        b_ref.clicked.connect(self.reload)
        row.addWidget(b_ref)
        self.b_probe = QPushButton("İncele")
        self.b_probe.clicked.connect(self.run)
        row.addWidget(self.b_probe)
        lay.addLayout(row)
        self.status = status_label()
        lay.addWidget(self.status)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text, 1)
        bb = QDialogButtonBox()
        self.b_save = bb.addButton("Raporu kaydet", QDialogButtonBox.ActionRole)
        self.b_save.clicked.connect(self.save)
        self.b_copy = bb.addButton("Özeti kopyala", QDialogButtonBox.ActionRole)
        self.b_copy.clicked.connect(self.copy)
        bb.addButton("Kapat", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.b_save.setEnabled(False)
        self.b_copy.setEnabled(False)
        ok, msg = (True, "") if desktop_factory else wp.available()
        if not ok:
            set_status(self.status, "✖ " + msg, "err")
            self.b_probe.setEnabled(False)
            return
        self.reload()

    def reload(self):
        self.windows.clear()
        try:
            with busy():
                self._wins = wp.list_windows(self.factory)
        except ShiftFlowError as exc:
            show_error(self, exc)
            self._wins = []
        for w in self._wins:
            self.windows.addItem(f"{w['title']}    ({w['process'] or w['class']})")
        set_status(self.status, f"{len(self._wins)} pencere bulundu. WMS penceresini seçin.", "ok")

    def run(self):
        i = self.windows.currentIndex()
        if i < 0:
            return
        try:
            with busy():
                self.result = wp.probe(self._wins[i], self.factory)
        except ShiftFlowError as exc:
            show_error(self, exc)
            return
        kind = {"uygun": "ok", "kismen": "warn"}.get(self.result.verdict, "err")
        set_status(self.status, self.result.verdict_text, kind)
        self.text.setPlainText(self.result.report_text())
        self.b_save.setEnabled(True)
        self.b_copy.setEnabled(True)

    def save(self):
        if self.result is None:
            return
        try:
            path = wp.save_report(self.result)
        except OSError as exc:
            show_error(self, ShiftFlowError("Rapor kaydedilemedi.", detail=str(exc)))
            return
        set_status(self.status, f"Kaydedildi: {path}", "ok")
        self.saved_path = path

    def copy(self):
        if self.result is not None:
            QGuiApplication.clipboard().setText("\n".join(self.result.summary_lines()))
            set_status(self.status, "Özet panoya kopyalandı (yalnız sayılar ve sonuç; ağaç değil).", "ok")



# ====================================================================== zamanlanmış görev
def launcher_command() -> str:
    """ShiftFlow'u çalıştıran komut (exe paketi veya kaynak koddan)."""
    import sys
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"  # konsol penceresi açılmasın
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "shiftflow_main.py")
    return f'"{exe}" "{main}"'


def schtasks_commands(target: str, kind: str, shifts: list[dict], offset_min: int, mail: str, name: str) -> list[str]:
    """Her vardiya bitişinden offset dakika sonra çalışan günlük görevler için schtasks komutları."""
    from datetime import datetime, timedelta
    out = []
    flag = "--paket" if kind == "paket" else "--akis"
    run = f'{launcher_command()} {flag} "{target}" --donem otomatik --mail {mail}'
    tr = run.replace('"', '\\"')
    for sh in shifts:
        end = datetime.strptime(sh["end"], "%H:%M") + timedelta(minutes=offset_min)
        tn = f"ShiftFlow - {name} - {sh['name']}"
        out.append(f'schtasks /Create /F /SC DAILY /TN "{tn}" /ST {end:%H:%M} /TR "{tr}"')
    return out


class ScheduleDialog(QDialog):
    """Rapor paketini (veya iş akışını) vardiya sonlarında Windows Görev Zamanlayıcı ile çalıştırma."""

    def __init__(self, window, settings):
        super().__init__(window)
        from PySide6.QtWidgets import QFileDialog, QFormLayout, QLineEdit, QSpinBox
        self.window_, self.settings = window, settings
        self._QFileDialog = QFileDialog
        self.setWindowTitle("Zamanlanmış görev")
        self.resize(900, 600)
        lay = QVBoxLayout(self)
        h = QLabel("Seçilen rapor paketi her vardiya bitiminden sonra pencere açılmadan çalışır. Mail gönderilmez: "
                   "taslak olarak hazırlanır (Outlook Taslaklar klasörü veya .eml dosyası). Karar gerektiren durumda "
                   "o rapor atlanır ve bir uyarı taslağı hazırlanır.\n\n"
                   "Bilmeniz gerekenler: bilgisayar açık ve Windows oturumunuz açık olmalı (ekran kilitli olabilir). "
                   "Raporlar o saatte dosya/klasör kaynağından veya Excel'de açık kitaplardan alınır. WMS'te raporu "
                   "kendiliğinden açma adımı ekran otomasyonuyla ayrıca eklenecek.")
        h.setWordWrap(True)
        h.setObjectName("dialogHelp")
        lay.addWidget(h)
        f = QFormLayout()
        row = QHBoxLayout()
        last = settings.value("last_package", "") or ""
        self.target = QLineEdit(last or (window.workflow_path or ""))
        b = QPushButton("Seç…")
        b.clicked.connect(self._pick)
        row.addWidget(self.target, 1)
        row.addWidget(b)
        f.addRow("Rapor paketi / iş akışı:", row)
        self.offset = QSpinBox()
        self.offset.setRange(0, 115)
        self.offset.setValue(15)
        self.offset.setSuffix(" dakika")
        f.addRow("Vardiya bitiminden sonra:", self.offset)
        self.mail = QComboBox()
        self.mail.addItem("Outlook Taslaklar klasörüne kaydet", "outlook")
        self.mail.addItem(".eml dosyası olarak (çıktının yanına)", "eml")
        self.mail.addItem("Mail hazırlama", "yok")
        f.addRow("Mail:", self.mail)
        lay.addLayout(f)
        self.cmds = QPlainTextEdit()
        self.cmds.setReadOnly(True)
        lay.addWidget(QLabel("Görev Zamanlayıcı komutları (vardiya başına bir görev):"))
        lay.addWidget(self.cmds, 1)
        self.status = status_label()
        lay.addWidget(self.status)
        bb = QDialogButtonBox()
        b_try = bb.addButton("Şimdi bir kez dene", QDialogButtonBox.ActionRole)
        b_try.clicked.connect(self.try_now)
        b_copy = bb.addButton("Komutları kopyala", QDialogButtonBox.ActionRole)
        b_copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.cmds.toPlainText()),
                                        set_status(self.status, "Kopyalandı. Komut İstemi'ne yapıştırıp çalıştırın.",
                                                   "ok")))
        self.b_create = bb.addButton("Görevleri oluştur", QDialogButtonBox.ActionRole)
        self.b_create.clicked.connect(self.create)
        self.b_create.setEnabled(os.name == "nt")
        bb.addButton("Kapat", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        lay.addWidget(bb)
        for w in (self.target.textChanged, self.offset.valueChanged, self.mail.currentIndexChanged):
            w.connect(self.update_cmds)
        self.update_cmds()

    def _pick(self):
        path, _ = self._QFileDialog.getOpenFileName(self, "Rapor paketi veya iş akışı", os.path.dirname(
            self.target.text()), "ShiftFlow (*.sfpaket.json *.json)")
        if path:
            self.target.setText(path)

    def kind(self) -> str:
        return "paket" if self.target.text().lower().endswith(".sfpaket.json") else "akis"

    def commands(self) -> list[str]:
        t = self.target.text().strip()
        if not t:
            return []
        name = os.path.basename(t).replace(".sfpaket.json", "").replace(".json", "")
        return schtasks_commands(os.path.abspath(t), self.kind(), self.window_.session.shifts, self.offset.value(),
                                 self.mail.currentData(), name)

    def update_cmds(self):
        self.cmds.setPlainText("\n".join(self.commands()))

    def try_now(self):
        from .. import cli
        t = self.target.text().strip()
        if not t or not os.path.exists(t):
            set_status(self.status, "✖ Dosya bulunamadı.", "err")
            return
        flag = "--paket" if self.kind() == "paket" else "--akis"
        w = self.window_
        with busy():
            rc = cli.run([flag, t, "--donem", "otomatik", "--mail", self.mail.currentData()], provider=w.provider,
                         library=w.library, archive=w.archive, outlook=w.outlook)
        try:
            with open(cli.log_path(), encoding="utf-8") as fh:
                tail = fh.read().strip().split("\n\n")[-1]
        except OSError:
            tail = ""
        set_status(self.status, {0: "✓ Hepsi oluşturuldu.", 1: "⚠ Bazıları atlandı/hatalı.",
                                 2: "✖ Çalıştırılamadı."}.get(rc, "") + "\n" + tail, "ok" if rc == 0 else "warn")

    def create(self):
        import subprocess
        from PySide6.QtWidgets import QMessageBox
        cmds = self.commands()
        if not cmds or QMessageBox.question(self, "Görevleri oluştur", f"{len(cmds)} zamanlanmış görev oluşturulsun mu? "
                                            "(Aynı adlı görevler güncellenir.)") != QMessageBox.Yes:
            return
        out = []
        for c in cmds:
            r = subprocess.run(c, shell=True, capture_output=True, text=True)  # noqa: S602 - komut bizim ürettiğimiz
            out.append(("✓ " if r.returncode == 0 else "✖ ") + (r.stdout or r.stderr).strip())
        set_status(self.status, "\n".join(out), "ok" if all(x.startswith("✓") for x in out) else "err")
