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
def no_variant_prompt(monkeypatch):
    """Farklı yazılış sorusu testlerde pencere açmasın (varsayılan: 'Şimdi değil')."""
    try:
        from shiftflow.ui.main_window import MainWindow
    except Exception:  # PySide6 yoksa
        return
    monkeypatch.setattr(MainWindow, "ask_variant_fix", lambda self, lines, at_input: "later")
