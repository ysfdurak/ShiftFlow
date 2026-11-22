"""Uygulama giriş noktası."""

from __future__ import annotations

import logging
import os
import sys
import traceback


def _log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "ShiftFlow")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "shiftflow.log")


def install_turkish(app) -> bool:
    """Qt'nin kendi metinleri (Tamam/İptal, Evet/Hayır, dosya penceresi) Türkçe görünsün.
    Önceden standart düğmeler İngilizce (OK/Cancel) kalıyordu."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)
    if tr.load(QLocale(QLocale.Turkish, QLocale.Turkey), "qtbase", "_",
               QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(tr)
        app._sf_translator = tr  # çöp toplayıcı silmesin
        return True
    return False


def main(argv=None) -> int:
    from .cli import wants_cli
    args0 = (argv if argv is not None else sys.argv)[1:]
    if wants_cli(args0):  # pencere açmadan çalıştır (Görev Zamanlayıcı)
        logging.basicConfig(filename=_log_path(), level=logging.WARNING,
                            format="%(asctime)s %(levelname)s %(message)s")
        from .cli import run
        try:
            return run(args0)
        except Exception as exc:  # noqa: BLE001 - zamanlanmış çalıştırma sessizce çökmesin, günlüğe yazılsın
            logging.exception("Komut satırı çalıştırması başarısız")
            from .cli import _log
            _log([f"=== HATA: {type(exc).__name__}: {exc}"])
            return 2
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import APP_NAME
    from .ui.main_window import MainWindow
    from .ui.style import STYLE

    # Günlüğe yalnızca hata türü ve konumu yazılır; hücre değerleri yazılmaz.
    logging.basicConfig(filename=_log_path(), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    app = QApplication(argv if argv is not None else sys.argv)
    install_turkish(app)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ShiftFlow")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    f = QFont("Segoe UI", 9) if sys.platform == "win32" else app.font()
    app.setFont(f)

    def excepthook(etype, value, tb):
        frames = traceback.extract_tb(tb)
        where = " <- ".join(f"{os.path.basename(fr.filename)}:{fr.lineno}" for fr in frames[-4:])
        logging.error("%s at %s", etype.__name__, where)
        QMessageBox.critical(None, APP_NAME,
                             "Beklenmeyen bir hata oluştu. İşlem tamamlanmadı; kaynak dosyalarınız değişmedi.\n\n"
                             f"Hata: {etype.__name__}\nAyrıntı günlüğü: {_log_path()}")

    sys.excepthook = excepthook
    smoke = os.environ.get("SHIFTFLOW_SMOKE_QUIT_MS")
    if smoke:  # CI: pencereyi açıp kendiliğinden kapanır; çıkış kodunun 0 olduğu denetlenir
        from PySide6.QtCore import QTimer

        def _kapat():  # karşılama penceresi (iç içe döngü) ve ana pencere sırayla kapanana kadar tekrarlar
            app.closeAllWindows()
            app.quit()
        smoke_timer = QTimer()
        smoke_timer.timeout.connect(_kapat)
        smoke_timer.start(int(smoke))
    win = MainWindow()
    win.show()
    args = (argv if argv is not None else sys.argv)[1:]
    if not any(a.lower().endswith(".json") for a in args):
        if not win.offer_recovery():
            win.first_run()
    for a in args:
        if a.lower().endswith(".json"):
            win.open_workflow(a)
        elif os.path.exists(a):
            win.open_file(a)
    del Qt
    rc = app.exec()
    # Pencere QApplication'dan önce yok edilsin (Windows'ta kapanışta erişim hatasını önler).
    win.deleteLater()
    del win
    import gc
    gc.collect()
    return rc


if __name__ == "__main__":
    sys.exit(main())
