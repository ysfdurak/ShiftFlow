"""WMS ekran teşhisi: masaüstü WMS penceresinin ekran otomasyonuna uygun olup olmadığını ölçer.

Ne yapar: Seçilen pencerenin kontrol ağacını (menü, düğme, giriş alanı, sekme) iki yöntemle tarar
(Windows UI Automation = "uia" ve klasik Win32) ve düğme/alan adlarının okunup okunamadığını raporlar.
Hiçbir şeye tıklamaz, yazmaz; yalnız okur.

Gizlilik: Giriş alanlarının içeriği (değer) okunmaz. Tablo, liste, ağaç ve belge kontrollerinin içine
girilmez (rapor verisi orada olur); yalnız kaç öğe olduğu sayılır. Adlar 60 karakterle sınırlanır.
Rapor yalnız bu bilgisayarda kaydedilir.

Windows'ta pywinauto gerekir. Testlerde `desktop_factory` ile sahte pencere ağacı verilir.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

from .errors import ShiftFlowError

ACTION_TYPES = {"Button", "MenuItem", "SplitButton", "TabItem", "Hyperlink", "CheckBox", "RadioButton"}
INPUT_TYPES = {"Edit", "ComboBox", "Spinner", "Calendar"}
CONTAINER_TYPES = {"Menu", "MenuBar", "ToolBar", "Tab", "Group", "Pane", "Window", "Custom", "Text", "StatusBar",
                   "TitleBar", "ScrollBar", "Image", "Header", "HeaderItem", "Separator", "Thumb"}
DATA_TYPES = {"DataGrid", "Table", "List", "Tree", "Document", "DataItem", "ListItem", "TreeItem"}
# Win32 sınıf adlarından kontrol türü (uia türü vermeyen eski programlar için)
WIN32_CLASS = {"button": "Button", "edit": "Edit", "combobox": "ComboBox", "syslistview32": "List",
               "systreeview32": "Tree", "systabcontrol32": "Tab", "toolbarwindow32": "ToolBar", "static": "Text",
               "richedit": "Edit", "tedit": "Edit", "tbutton": "Button", "tbitbtn": "Button", "tspeedbutton": "Button",
               "tcombobox": "ComboBox", "tdatetimepicker": "Edit", "tstringgrid": "DataGrid", "tdbgrid": "DataGrid",
               "tpagecontrol": "Tab", "tmainmenu": "MenuBar"}

FRAMEWORKS = [
    ("windowsforms10", ".NET WinForms", "Genellikle iyi çalışır (uia)."),
    ("hwndwrapper", "WPF", "Genellikle çok iyi çalışır (uia)."),
    ("sunawt", "Java (AWT/Swing)", "Düğme adları çoğu zaman görünmez. Windows'ta 'Java Access Bridge' açılırsa "
                                   "okunabilir hâle gelebilir (IT'ye sorun)."),
    ("tform", "Delphi", "Kısmen çalışır; win32 yöntemiyle düğmeler genelde bulunur, menüler bulunmayabilir."),
    ("tapplication", "Delphi", "Kısmen çalışır; win32 yöntemiyle düğmeler genelde bulunur."),
    ("fnwnd", "PowerBuilder", "Tablolar okunamaz; düğme ve alanlar kısmen bulunur."),
    ("pbframe", "PowerBuilder", "Tablolar okunamaz; düğme ve alanlar kısmen bulunur."),
    ("chrome_widgetwin", "Chromium/Electron", "Erişilebilirlik açıksa iyi çalışır."),
    ("transparent windows client", "Citrix (uzak uygulama)", "Düğmeler okunamaz; ekran otomasyonu önerilmez."),
    ("tscshellcontainerclass", "Uzak masaüstü", "Düğmeler okunamaz; ekran otomasyonu önerilmez."),
    ("thunderrt6", "Visual Basic 6", "win32 yöntemiyle kısmen çalışır."),
    ("afx:", "MFC (C++)", "win32 yöntemiyle genellikle çalışır."),
]


@dataclass
class ProbeNode:
    depth: int
    control_type: str
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    enabled: bool = True
    note: str = ""  # örn. "tablo: 42 öğe (içerik okunmadı)"


@dataclass
class BackendResult:
    backend: str
    nodes: list[ProbeNode] = field(default_factory=list)
    error: str = ""
    truncated: bool = False

    def count(self, types, named=True) -> int:
        return sum(1 for n in self.nodes if n.control_type in types and (not named or n.name or n.automation_id))

    @property
    def actions(self) -> int:
        return self.count(ACTION_TYPES)

    @property
    def inputs(self) -> int:
        return self.count(INPUT_TYPES)

    @property
    def menus(self) -> int:
        return sum(1 for n in self.nodes if n.control_type == "MenuItem" and n.name)

    @property
    def unnamed_ratio(self) -> float:
        inter = [n for n in self.nodes if n.control_type in ACTION_TYPES | INPUT_TYPES | {"Pane", "Custom"}]
        if not inter:
            return 1.0
        return sum(1 for n in inter if not (n.name or n.automation_id)) / len(inter)


@dataclass
class ProbeResult:
    title: str
    class_name: str
    process: str
    results: dict[str, BackendResult]
    framework: str = ""
    framework_hint: str = ""
    verdict: str = ""  # uygun | kismen | uygun_degil
    verdict_text: str = ""
    best_backend: str = ""
    time: str = ""

    def summary_lines(self) -> list[str]:
        out = [f"Pencere: {self.title}", f"Program: {self.process or '?'} · sınıf: {self.class_name}"]
        if self.framework:
            out.append(f"Teknoloji tahmini: {self.framework} — {self.framework_hint}")
        for b, r in self.results.items():
            if r.error:
                out.append(f"[{b}] taranamadı: {r.error}")
            else:
                out.append(f"[{b}] {len(r.nodes)} öğe · adı okunan düğme/menü: {r.actions} (menü öğesi {r.menus}) · "
                           f"giriş alanı: {r.inputs} · adsız oranı: %{round(r.unnamed_ratio * 100)}"
                           + (" · (tarama sınırı aşıldı)" if r.truncated else ""))
        out.append("")
        out.append("SONUÇ: " + self.verdict_text)
        return out

    def report_text(self, max_nodes=600) -> str:
        lines = ["ShiftFlow — WMS ekran teşhis raporu", f"Tarih: {self.time}",
                 "Bu rapor giriş alanlarının içeriğini ve tablo verisini içermez.", ""]
        lines += self.summary_lines()
        for b, r in self.results.items():
            lines += ["", f"--- Kontrol ağacı ({b}) ---"]
            for n in r.nodes[:max_nodes]:
                bits = [n.control_type]
                if n.name:
                    bits.append(f"'{n.name}'")
                if n.automation_id:
                    bits.append(f"id={n.automation_id}")
                if n.class_name:
                    bits.append(f"[{n.class_name}]")
                if not n.enabled:
                    bits.append("(pasif)")
                if n.note:
                    bits.append(n.note)
                lines.append("  " * n.depth + " ".join(bits))
            if len(r.nodes) > max_nodes:
                lines.append(f"… {len(r.nodes) - max_nodes} öğe daha")
        return "\n".join(lines)


def _txt(v, limit=60) -> str:
    s = " ".join(str(v or "").split())
    return s[:limit] + ("…" if len(s) > limit else "")


def _info(w, backend):
    ei = getattr(w, "element_info", None)
    ct = getattr(ei, "control_type", None) or ""
    cls = getattr(ei, "class_name", "") or ""
    if not ct:  # win32: türü sınıf adından çıkar (WindowsForms10.EDIT.app… gibi adlar da)
        low = cls.lower()
        ct = next((v for k, v in WIN32_CLASS.items() if low.startswith(k)), None)
        if ct is None:
            ct = next((v for k, v in (("edit", "Edit"), ("combobox", "ComboBox"), ("button", "Button"),
                                      ("listview", "List"), ("grid", "DataGrid"), ("treeview", "Tree"))
                       if k in low), "Pane")
    name = getattr(ei, "name", "") or ""
    aid = getattr(ei, "automation_id", "") or ""
    try:
        enabled = bool(w.is_enabled())
    except Exception:  # noqa: BLE001
        enabled = True
    return str(ct), name, str(aid), cls, enabled


def _walk(root, backend, max_nodes=3000, max_depth=25) -> BackendResult:
    res = BackendResult(backend)
    stack = [(root, 0)]
    while stack:
        w, depth = stack.pop()
        if len(res.nodes) >= max_nodes:
            res.truncated = True
            break
        try:
            ct, name, aid, cls, enabled = _info(w, backend)
        except Exception:  # noqa: BLE001
            continue
        keep = ct not in INPUT_TYPES and (backend == "uia" or ct in ACTION_TYPES or ct in ("Text", "MenuItem"))
        # win32'de pencere metni çoğu zaman içeriktir: yalnız düğme/etiket adları yazılır
        node = ProbeNode(depth, ct, _txt(name) if keep else "", _txt(aid, 40), _txt(cls, 40), enabled)
        if ct in INPUT_TYPES and name and backend == "uia":
            # uia'da Name alanın etiketidir; win32'de ise alanın içeriğidir (değer) — o yüzden yazılmaz
            node.name = _txt(name)
        res.nodes.append(node)
        if ct in DATA_TYPES:
            try:
                node.note = f"({len(w.children())} öğe; içerik okunmadı)"
            except Exception:  # noqa: BLE001
                node.note = "(içerik okunmadı)"
            continue  # rapor verisi burada olur: içine girme
        if depth >= max_depth:
            continue
        try:
            kids = w.children()
        except Exception:  # noqa: BLE001
            kids = []
        for k in reversed(kids):
            stack.append((k, depth + 1))
    return res


def _framework(class_names: list[str]) -> tuple[str, str]:
    low = " ".join(c.lower() for c in class_names)
    for key, name, hint in FRAMEWORKS:
        if key in low:
            return name, hint
    return "", ""


def _verdict(p: ProbeResult):
    ok = {b: r for b, r in p.results.items() if not r.error}
    if not ok:
        p.verdict, p.verdict_text = "uygun_degil", "Pencere taranamadı."
        return
    best = max(ok.values(), key=lambda r: (r.actions + r.inputs, -r.unnamed_ratio))
    p.best_backend = best.backend
    if p.framework.startswith(("Citrix", "Uzak")):
        p.verdict, p.verdict_text = "uygun_degil", ("WMS uzak bağlantı penceresi içinde çalışıyor; düğmeler bu "
                                                    "bilgisayardan okunamaz. Ekran otomasyonu önerilmez.")
    elif best.actions >= 5 and best.inputs >= 1 and best.unnamed_ratio <= 0.5:
        p.verdict = "uygun"
        p.verdict_text = (f"UYGUN. '{best.backend}' yöntemiyle {best.actions} düğme/menü ve {best.inputs} giriş "
                          "alanı adıyla bulunuyor. Rapor menüsü, filtre alanları ve Çalıştır düğmesi adla "
                          "tanınabilir; ekran otomasyonu güvenilir şekilde kurulabilir.")
    elif best.actions >= 2:
        p.verdict = "kismen"
        p.verdict_text = (f"KISMEN UYGUN. '{best.backend}' yöntemiyle {best.actions} düğme/menü ve {best.inputs} "
                          "giriş alanı bulunuyor ama birçok öğenin adı yok. Raporu açacağınız ekranı (filtre "
                          "penceresi açıkken) ayrıca inceleyin; gerekli alanlar adlıysa kurulabilir.")
    else:
        p.verdict = "uygun_degil"
        p.verdict_text = ("UYGUN DEĞİL. Düğme ve alan adları okunamıyor; yalnız ekran konumuna göre tıklanabilir. "
                          "Bu çok kırılgandır (pencere boyutu, çözünürlük, güncelleme bozabilir), önerilmez.")


# ---------------------------------------------------------------------- pywinauto bağlantısı
def available() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "WMS ekran teşhisi yalnız Windows'ta çalışır."
    try:
        import pywinauto  # noqa: F401
    except ImportError:
        return False, "pywinauto kurulu değil. Komut: pip install pywinauto"
    return True, ""


def _desktop(backend):  # pragma: no cover - yalnız Windows
    from pywinauto import Desktop
    return Desktop(backend=backend)


def _process_name(w) -> str:
    try:
        pid = w.element_info.process_id
    except Exception:  # noqa: BLE001
        return ""
    try:  # pragma: no cover - yalnız Windows
        import psutil
        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001
        return f"pid {pid}"


def list_windows(desktop_factory=None) -> list[dict]:
    """Açık üst düzey pencereler: [{"title", "class", "process", "handle"}] (başlıksızlar atlanır)."""
    factory = desktop_factory or _desktop
    try:
        wins = factory("uia").windows()
    except Exception as exc:  # noqa: BLE001
        raise ShiftFlowError("Açık pencereler listelenemedi.", detail=str(exc)) from exc
    out = []
    for w in wins:
        try:
            title = w.window_text()
        except Exception:  # noqa: BLE001
            continue
        if not title or not title.strip():
            continue
        ei = w.element_info
        out.append({"title": _txt(title, 120), "class": getattr(ei, "class_name", "") or "",
                    "process": _process_name(w), "handle": getattr(ei, "handle", None)})
    return out


def _find(desktop, handle, title):
    for w in desktop.windows():
        ei = w.element_info
        if handle is not None and getattr(ei, "handle", None) == handle:
            return w
    for w in desktop.windows():
        try:
            if _txt(w.window_text(), 120) == title:
                return w
        except Exception:  # noqa: BLE001
            continue
    return None


def probe(window: dict, desktop_factory=None, backends=("uia", "win32"), max_nodes=3000) -> ProbeResult:
    """Pencereyi iki yöntemle tarar ve uygunluk sonucunu verir. Hiçbir şeye tıklamaz."""
    factory = desktop_factory or _desktop
    results, classes = {}, [window.get("class", "")]
    for b in backends:
        try:
            w = _find(factory(b), window.get("handle"), window.get("title"))
            if w is None:
                results[b] = BackendResult(b, error="pencere bulunamadı (kapanmış olabilir)")
                continue
            r = _walk(w, b, max_nodes=max_nodes)
            results[b] = r
            classes += [n.class_name for n in r.nodes[:200]]
        except Exception as exc:  # noqa: BLE001
            results[b] = BackendResult(b, error=_txt(str(exc), 120))
    fw, hint = _framework(classes)
    p = ProbeResult(window.get("title", ""), window.get("class", ""), window.get("process", ""), results, fw, hint,
                    time=datetime.now().strftime("%d.%m.%Y %H:%M"))
    _verdict(p)
    return p


def save_report(p: ProbeResult, folder: str | None = None) -> str:
    base = os.environ.get("LOCALAPPDATA")
    folder = folder or (os.path.join(base, "ShiftFlow") if base else os.path.join(os.path.expanduser("~"), ".shiftflow"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"wms_teshis_{datetime.now():%Y%m%d_%H%M%S}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(p.report_text())
    return path
