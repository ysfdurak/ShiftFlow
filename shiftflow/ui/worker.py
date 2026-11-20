"""Uzun işlemleri arka planda çalıştırma.

`run_task(parent, fn, ...)` işlevi `fn`'i ayrı bir iş parçacığında çalıştırır, bitene kadar
bekler ve sonucunu döndürür (hata varsa aynı hatayı yükseltir). Bu sırada:

* pencere donmaz (yeniden çizilir, "yanıt vermiyor" olmaz);
* kısa sürede bitmezse ilerleme penceresi açılır: hangi adımın hesaplandığı ve **İptal** düğmesi;
* kullanıcının fare/klavye girdisi ilerleme penceresi dışında yok sayılır. Böylece işlem
  sürerken iş akışı başka bir yerden değiştirilemez (motor tek iş parçacığından kullanılır).

İptal, motorun bir sonraki adım sınırında `Cancelled` hatasıyla durmasını sağlar;
`Session._commit` yarım değişikliği geri alır. Excel/Outlook (COM) çağrıları bu yolla
çalıştırılmaz: COM nesneleri oluşturuldukları iş parçacığına bağlıdır.

`fn` içinde arayüz nesnelerine dokunulmamalıdır (yalnız motor çağrıları).
"""
from __future__ import annotations

import gc
import threading
import time

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtGui import QCursor, QWindow
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

SHOW_AFTER_MS = 400
_INPUT = {QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick, QEvent.KeyPress,
          QEvent.KeyRelease, QEvent.Wheel, QEvent.Shortcut, QEvent.ShortcutOverride, QEvent.Drop,
          QEvent.ContextMenu}

_state = {"active": 0}


def active() -> bool:
    """Şu anda arka planda bir görev çalışıyor mu? (otomatik kayıt gibi işler bekler)"""
    return _state["active"] > 0


class _InputBlocker(QObject):
    """Görev sürerken fare/klavye girdisini yalnız ilerleme penceresine geçirir."""

    def __init__(self, allowed):
        super().__init__()
        self.allowed = allowed

    def eventFilter(self, obj, ev):
        if ev.type() not in _INPUT:
            return False
        dlg = self.allowed()
        if dlg is None:
            return True
        if isinstance(obj, QWidget):
            return obj.window() is not dlg
        if isinstance(obj, QWindow):
            return obj is not dlg.windowHandle()
        return True


def run_task(parent, fn, text: str = "İşleniyor…", session=None, cancellable: bool = True):
    """fn()'i arka planda çalıştırır ve sonucunu döndürür. Bkz. modül açıklaması.

    Çalışan iş parçacığı hiçbir Qt nesnesine dokunmaz: ilerleme metni ortak bir sözlüğe
    yazılır, ana iş parçacığı onu kısa aralıklarla okuyup pencereye yansıtır."""
    app = QApplication.instance()
    if app is None or active() or threading.current_thread() is not threading.main_thread():
        return fn()  # iç içe çağrı veya arayüz yok: doğrudan çalıştır
    cancel = threading.Event()
    state = {"text": text, "result": None, "error": None, "dlg": None, "shown_at": None}
    old = (session.cancel_event, session.progress) if session is not None else None

    def progress(msg):
        state["text"] = msg

    if session is not None:
        session.cancel_event = cancel if cancellable else None
        session.progress = progress

    def target():
        try:
            state["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - ana iş parçacığında yeniden yükseltilir
            state["error"] = exc

    th = threading.Thread(target=target, name="shiftflow-gorev", daemon=True)
    can_cancel = cancellable and session is not None
    started = time.monotonic()

    def poll():
        d = state["dlg"]
        if d is None and (time.monotonic() - started) * 1000 >= SHOW_AFTER_MS:
            d = QProgressDialog(text, "İptal" if can_cancel else "", 0, 0, parent)
            d.setWindowTitle("Lütfen bekleyin")
            d.setWindowModality(Qt.WindowModal)
            d.setMinimumDuration(0)
            d.setMinimumWidth(460)
            d.setAutoClose(False)
            d.setAutoReset(False)
            if not can_cancel:
                d.setCancelButton(None)

            def on_cancel():
                cancel.set()
                state["text"] = "İptal ediliyor… (çalışan adım bitince durur)"
            d.canceled.connect(on_cancel)
            state["dlg"] = d
            d.show()
        if d is not None and d.labelText() != state["text"]:
            d.setLabelText(state["text"])

    blocker = _InputBlocker(lambda: state["dlg"])
    app.installEventFilter(blocker)
    QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
    _state["active"] += 1
    # Çöp toplayıcı iş parçacığında çalışıp eski Qt nesnelerini (kapanmış pencereler) orada
    # yok etmesin: Qt nesneleri yalnız ana iş parçacığında silinmeli. Görev sonunda burada toplanır.
    gc_was = gc.isenabled()
    gc.disable()
    try:
        th.start()
        th.join(0.05)  # kısa işler olay döngüsüne girmeden biter
        flags = QEventLoop.AllEvents  # girdi olayları _InputBlocker ile süzülür (İptal düğmesi çalışsın)
        while th.is_alive():
            poll()
            app.processEvents(flags, 40)
            th.join(0.04)
    finally:
        if gc_was:
            gc.enable()
        _state["active"] -= 1
        app.removeEventFilter(blocker)
        QApplication.restoreOverrideCursor()
        d = state["dlg"]
        if d is not None:
            d.hide()
            d.setParent(None)
            d.deleteLater()
            state["dlg"] = None
        if session is not None:
            session.cancel_event, session.progress = old
    if state["error"] is not None:
        raise state["error"]
    return state["result"]
