"""Kullanım kılavuzundaki ekran görüntülerini (docs/ekran/*.png) örnek veriden üretir.

    python tools/ekran_goruntuleri.py            # docs/ekran klasörüne yazar
    QT_QPA_PLATFORM=offscreen python tools/ekran_goruntuleri.py   # ekransız (CI)

Görüntüler gerçek pencerelerden alınır; arayüz değişince komut yeniden çalıştırılır.
Exe paketi (shiftflow.spec) bu klasörü kılavuzla birlikte taşır.
"""
from __future__ import annotations

import os
import sys
import tempfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)

from openpyxl import Workbook  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402


def _bekle(app, n=5):
    for _ in range(n):
        app.processEvents()


def _kitap(path):
    """Formüllü sütunları olan küçük bir sentetik Excel raporu."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Toplama"
    ws.append(["TOPLAMA RAPORU"])
    ws.append([])
    ws.append(["Personel No", "Toplanan", "Hedef", "Oran", "Ad", "Durum"])
    for i, (p, t, h) in enumerate([("P1", 120, 100), ("P2", 80, 100), ("P9", 50, 50)], start=4):
        ws.append([p, t, h, f"=B{i}/C{i}", f'=IFERROR(VLOOKUP(A{i},Personel!A:B,2,0),"Tanımsız")',
                   f'=IF(D{i}>=1,"Hedefte","Altı")'])
    ps = wb.create_sheet("Personel")
    ps.append(["No", "Ad Soyad"])
    ps.append(["P1", "Ali"])
    ps.append(["P2", "Ayşe"])
    wb.save(path)
    return str(path)


def main(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="sf_ekran_")
    os.environ["LOCALAPPDATA"] = os.path.join(tmp, "appdata")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from shiftflow.ui.style import STYLE
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    yazilan = []

    from shiftflow.engine.library import ReportLibrary
    from shiftflow.ui import main_window as mw
    from shiftflow.ui.formula_editor import FormulaEdit
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
    mw.MainWindow.ask_variant_fix = lambda self, lines, at_input: "later"

    def kaydet(widget, ad):
        _bekle(app)
        p = os.path.join(out_dir, ad)
        widget.grab().save(p)
        yazilan.append(p)

    # 1) Adım listesi: kapalı bir adım ve notlu bir adım
    w = mw.MainWindow(library=ReportLibrary(os.path.join(tmp, "l.db")))
    w.resize(1366, 768)
    w.show()
    w.open_sample()
    steps = w.session.workflow.datasets[w.current].steps
    if len(steps) >= 3:
        w.session.set_step_note(w.current, 1, "Ad ve ekip lideri personel listesinden gelir")
        from shiftflow.engine.session import StepFailure
        for i in range(len(steps) - 1, 1, -1):  # sonraki adımların dayanmadığı bir adımı kapat
            try:
                w.session.set_step_enabled(w.current, i, False)
                break
            except StepFailure:
                w.session.undo()
        w.refresh_all(w.current)
    _bekle(app, 10)
    kaydet(w, "adimlar_35.png")

    # 2) Formül düzenleyici: iç içe formül, girintili
    d = QDialog(w)
    d.setWindowTitle("Formülü düzenle")
    d.resize(760, 300)
    from PySide6.QtWidgets import QLabel, QVBoxLayout
    lay = QVBoxLayout(d)
    ed = FormulaEdit(columns=["Personel No", "Toplanan", "Hedef", "Vardiya"])
    ed.setPlainText('EĞER(EBOŞSA([Personel No]); "Tanımsız"; EĞER([Toplanan] / [Hedef] >= 1; '
                    '"Hedefte"; EĞER([Vardiya] = "Gece"; "Gece altı"; "Altı")))')
    lay.addWidget(ed, 1)
    sig = QLabel()
    ed.signatureChanged.connect(sig.setText)
    lay.addWidget(sig)
    d.show()
    ed.format()
    cur = ed.textCursor()
    cur.setPosition(ed.toPlainText().find("[Toplanan]"))
    ed.setTextCursor(cur)
    ed.setFocus()
    kaydet(d, "formul_duzenleyici.png")
    d.close()

    # 3) Gösterge paneli: örnek verideki önerilen kutucuklar
    from shiftflow.ui import dashboard_ui as du
    g = du.DashboardDialog(w)
    g.resize(1100, 700)
    g.show()
    _bekle(app, 10)
    kaydet(g, "gosterge_paneli.png")
    g.close()

    # 4) Excel'deki formüllü sütunlar penceresi
    from shiftflow.ui.formula_dialogs import FormulaColumnsDialog
    w2 = mw.MainWindow(library=ReportLibrary(os.path.join(tmp, "l2.db")))
    path = _kitap(os.path.join(tmp, "rapor.xlsx"))
    df = pd.DataFrame({"Personel No": ["P1", "P2", "P9"], "Toplanan": [120, 80, 50], "Hedef": [100, 100, 50],
                       "Oran": [1.2, 0.8, 1.0], "Ad": ["Ali", "Ayşe", "Tanımsız"],
                       "Durum": ["Hedefte", "Altı", "Hedefte"]})
    w2.session.add_source("Toplama", df, path=path, sheet="Toplama")
    w2.refresh_all("Toplama")
    prov, pairs = w2._workbook_choices(w2.session.workflow.sources["Toplama"])
    wb = [p for p in pairs if p[1].name == "Toplama"][0][0]
    f = FormulaColumnsDialog(w2.session, "Toplama", prov, wb.id, "Toplama", w2,
                             load_sheet=lambda n, ref: w2._load_workbook_sheet(prov, wb, n, ref))
    f._load_missing()
    f.resize(980, 420)
    f.show()
    kaydet(f, "formullu_sutunlar.png")
    f.close()
    w.close()
    w2.close()
    return yazilan


if __name__ == "__main__":
    for p in main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(KOK, "docs", "ekran")):
        print(p)
