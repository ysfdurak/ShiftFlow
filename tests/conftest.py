"""Testlerde yalnızca sentetik veri kullanılır."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def picking():
    return pd.DataFrame({
        "Personel No": ["P01", "P02", "P03", "P01", "P04", "P05"],
        "Bölge": ["Marmara", "Ege", "Marmara", "Ege", None, "İç Anadolu"],
        "Toplanan": [120, 80, 0, 40, 55, 70],
        "Hedef": [100, 100, 0, 50, 50, 70],
        "Tarih": pd.to_datetime(["2026-11-01", "2026-11-01", "2026-11-02", "2026-11-02", "2026-11-03", "2026-11-03"]),
    })


@pytest.fixture
def staff():
    return pd.DataFrame({
        "Personel No": ["P01", "P02", "P03", "P06"],
        "Ad Soyad": ["Ali Yılmaz", "Ayşe Kaya", "Mehmet Demir", "Zeynep Ak"],
        "Vardiya": ["Gece", "Gündüz", "Gece", "Gündüz"],
    })


@pytest.fixture
def make_xlsx(tmp_path):
    def _make(name, sheets: dict):
        path = tmp_path / name
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            for sname, df in sheets.items():
                df.to_excel(w, sheet_name=sname, index=False)
        return str(path)
    return _make


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    """Testler kullanıcının gerçek rapor kütüphanesine dokunmasın."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Testler gerçek ayarlara (Windows'ta kayıt defteri) yazmasın; her test temiz ayarla başlar."""
    try:
        from PySide6.QtCore import QSettings
        from shiftflow.ui import main_window as mw
    except Exception:  # PySide6 yoksa
        return
    ini = str(tmp_path / "ayarlar.ini")
    monkeypatch.setattr(mw, "QSettings", lambda *a, **k: QSettings(ini, QSettings.IniFormat))


@pytest.fixture(autouse=True)
def no_startfile(monkeypatch):
    """Windows'ta testler üretilen Excel/.eml dosyalarını gerçek uygulamada açmasın."""
    import os
    monkeypatch.setattr(os, "startfile", lambda *a, **k: None, raising=False)


@pytest.fixture(autouse=True)
def no_blocking_message_box(monkeypatch):
    """Beklenmeyen bir hata/uyarı kutusu testi kilitlemesin: metniyle hemen düşsün."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except Exception:  # PySide6 yoksa
        return

    def _fail(self, *a, **k):
        raise AssertionError(f"Beklenmeyen ileti kutusu: {self.text()} {self.informativeText()}".strip())
    monkeypatch.setattr(QMessageBox, "exec", _fail)


@pytest.fixture(autouse=True)
def no_variant_prompt(monkeypatch):
    """Farklı yazılış sorusu testlerde pencere açmasın (varsayılan: 'Şimdi değil')."""
    try:
        from shiftflow.ui.main_window import MainWindow
    except Exception:  # PySide6 yoksa
        return
    monkeypatch.setattr(MainWindow, "ask_variant_fix", lambda self, lines, at_input: "later")


_EXIT = {"status": 0}


def pytest_sessionfinish(session, exitstatus):
    _EXIT["status"] = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """Ekransız Windows'ta yüzlerce test penceresinden sonra süreç kapanırken (DLL boşaltma) erişim hatası
    alınıyor; testlerin hepsi geçse de çıkış kodu bozuluyor. Sonuç yazıldıktan sonra süreç pytest'in
    kendi koduyla, DLL boşaltma adımı atlanarak sonlandırılır. Yalnız test ortamı içindir."""
    import sys
    if sys.platform == "win32":
        import ctypes
        sys.stdout.flush()
        sys.stderr.flush()
        k = ctypes.windll.kernel32
        k.TerminateProcess(k.GetCurrentProcess(), _EXIT["status"])
