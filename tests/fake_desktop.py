"""pywinauto masaüstünü taklit eden sahte pencere ağaçları (testler Linux'ta çalışsın diye)."""


class EI:
    def __init__(self, control_type="", name="", automation_id="", class_name="", handle=None, process_id=1):
        self.control_type, self.name, self.automation_id = control_type, name, automation_id
        self.class_name, self.handle, self.process_id = class_name, handle, process_id


class W:
    def __init__(self, ei, children=(), text=None, enabled=True):
        self.element_info, self._children, self._text, self._enabled = ei, list(children), text, enabled
        self.clicked = 0

    def children(self):
        return list(self._children)

    def window_text(self):
        return self._text if self._text is not None else self.element_info.name

    def is_enabled(self):
        return self._enabled

    def click_input(self):  # teşhis hiçbir şeye tıklamamalı
        self.clicked += 1
        raise AssertionError("teşhis tıklama yaptı")


class Desktop:
    def __init__(self, wins):
        self._wins = wins

    def windows(self):
        return list(self._wins)


def winforms_wms(backend):
    """İyi bir .NET WMS: adlı menü, düğme ve alanlar; içinde veri olan bir tablo."""
    if backend == "uia":
        grid = W(EI("DataGrid", "Sonuçlar", "grdSonuc"), [W(EI("DataItem", "P01 Ali Yılmaz 120"))] * 3)
        kids = [
            W(EI("MenuBar", "Menü"), [W(EI("MenuItem", "Raporlar")), W(EI("MenuItem", "Stok")),
                                      W(EI("MenuItem", "Sevkiyat"))]),
            W(EI("Edit", "Başlangıç tarihi", "dtBas", "WindowsForms10.EDIT"), text="10.11.2026 00:00"),
            W(EI("Edit", "Bitiş tarihi", "dtBit", "WindowsForms10.EDIT")),
            W(EI("ComboBox", "Depo", "cmbDepo")),
            W(EI("Button", "Listele", "btnListele")), W(EI("Button", "Temizle", "btnTemizle")),
            W(EI("Button", "Kapat", "btnKapat")), grid,
        ]
        root = W(EI("Window", "WMS — Toplama Raporu", "", "WindowsForms10.Window.8.app", handle=42), kids)
    else:
        root = W(EI("", "WMS — Toplama Raporu", "", "WindowsForms10.Window.8.app", handle=42),
                 [W(EI("", "10.11.2026 00:00", "", "WindowsForms10.EDIT")), W(EI("", "Listele", "", "Button"))])
    return Desktop([root, W(EI("Window", "", "", "Shell_TrayWnd"))])


def java_wms(backend):
    """Erişilebilirliği kapalı Java uygulaması: her şey adsız panel."""
    kids = [W(EI("Pane" if backend == "uia" else "", "", "", "SunAwtCanvas")) for _ in range(12)]
    return Desktop([W(EI("Window" if backend == "uia" else "", "Depo Yönetim", "", "SunAwtFrame", handle=7), kids)])
