import pytest

pytest.importorskip("PySide6")


def test_qt_standard_buttons_are_turkish(qapp):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QDialogButtonBox

    from shiftflow.app import install_turkish
    assert install_turkish(qapp)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    texts = {b.text().replace("&", "") for b in box.buttons()}
    assert "Cancel" not in texts and texts & {"İptal", "Vazgeç"}
    QCoreApplication.removeTranslator(qapp._sf_translator)
