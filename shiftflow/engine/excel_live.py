"""Açık Excel çalışma kitaplarına erişim.

İki sağlayıcı vardır ve ikisi aynı arayüzü sunar:

- `ComExcelProvider` (yalnız Windows, pywin32): Çalışan Excel'deki tüm
  kitapları listeler; kaydedilmemiş kitaplar dahil. WMS raporu kendi
  Excel penceresinde açtığında da bulunabilmesi için Windows'un "çalışan
  nesneler tablosu" (ROT) taranır; bulunamazsa etkin Excel kullanılır.
- `FileWorkbookProvider`: Diskteki .xlsx/.csv dosyalarını aynı biçimde
  sunar. Tanım oluştururken örnek dosya kullanmak ve testler için.

Excel'e yalnızca okuma yapılır: hücre, sayfa, kitap değiştirilmez;
kitap kapatılmaz, kaydedilmez.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass, field

import pandas as pd

from .errors import DataImportError

PREVIEW_ROWS = 30


@dataclass
class SheetRef:
    name: str
    preview: list[list]  # ilk satırlar (ham değerler)
    n_rows: int
    n_cols: int


@dataclass
class WorkbookRef:
    id: str
    name: str
    path: str = ""
    saved: bool = True
    origin: str = "excel"  # "excel" | "file"
    sheets: list[SheetRef] = field(default_factory=list)


class Provider:
    """Sağlayıcı arayüzü."""

    name = "?"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def list_workbooks(self) -> list[WorkbookRef]:
        raise NotImplementedError

    def read(self, workbook_id: str, sheet: str) -> list[list]:
        raise NotImplementedError

    def formula_rows(self, workbook_id: str, sheet: str, n: int = PREVIEW_ROWS + 10) -> "FormulaGrid":
        """İlk `n` satırın formülleri (formül yoksa değer). Excel'e yazmaz."""
        raise DataImportError("Bu kaynaktan formül okunamıyor.")


@dataclass
class FormulaGrid:
    """Sayfanın sol üst köşesinden itibaren hücreler: formül ('=' ile) veya değer."""
    first_row: int  # Excel satır numarası (1'den)
    first_col: int  # Excel sütun numarası (1'den; A=1)
    rows: list[list]


# ---------------------------------------------------------------------- yardımcılar
def _clean_value(v):
    """COM'dan gelen değeri sade Python değerine çevirir."""
    if v is None:
        return None
    if isinstance(v, _dt.datetime):  # pywintypes.datetime da bunun alt sınıfıdır
        try:
            return _dt.datetime(v.year, v.month, v.day, v.hour, v.minute, v.second)
        except (ValueError, OverflowError):
            return None
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v) if isinstance(v, float) else v
    return str(v)


def _as_rows(value) -> list[list]:
    """Range.Value tek hücrede düz değer, çok hücrede iç içe demet döner."""
    if value is None:
        return []
    if not isinstance(value, (tuple, list)):
        return [[_clean_value(value)]]
    return [[_clean_value(c) for c in (row if isinstance(row, (tuple, list)) else (row,))] for row in value]


# ---------------------------------------------------------------------- COM (Windows)
class ComExcelProvider(Provider):
    name = "Açık Excel"

    def __init__(self, apps_factory=None):
        """`apps_factory`: test için sahte Excel uygulama nesneleri döndüren fonksiyon."""
        self._apps_factory = apps_factory or _excel_applications
        self._cache: dict[str, object] = {}

    def available(self):
        if self._apps_factory is not _excel_applications:
            return True, ""
        if sys.platform != "win32":
            return False, "Açık Excel kitaplarına erişim yalnızca Windows'ta çalışır."
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            return False, "pywin32 kurulu değil. Komut: pip install pywin32"
        return True, ""

    def list_workbooks(self) -> list[WorkbookRef]:
        self._cache.clear()
        out = []
        try:
            apps = self._apps_factory()
        except Exception as exc:  # COM hataları çeşitli türlerde gelir
            raise DataImportError(_com_message(exc), detail=str(exc)) from exc
        for ai, app in enumerate(apps):
            try:
                books = list(app.Workbooks)
            except Exception as exc:
                raise DataImportError(_com_message(exc), detail=str(exc)) from exc
            for wb in books:
                try:
                    name = str(wb.Name)
                    path = str(wb.FullName) if wb.Path else ""
                    saved = bool(wb.Path)
                    wid = f"{ai}:{name}"
                    self._cache[wid] = wb
                    ref = WorkbookRef(id=wid, name=name, path=path, saved=saved, origin="excel")
                    for ws in wb.Worksheets:
                        try:
                            ur = ws.UsedRange
                            nr, nc = int(ur.Rows.Count), int(ur.Columns.Count)
                            pv = _as_rows(ur.Resize(min(nr, PREVIEW_ROWS), nc).Value) if nr and nc else []
                            ref.sheets.append(SheetRef(str(ws.Name), pv, nr, nc))
                        except Exception:
                            continue  # grafik sayfası, korumalı sayfa vb.
                    out.append(ref)
                except Exception:
                    continue
        return out

    def read(self, workbook_id: str, sheet: str) -> list[list]:
        wb = self._cache.get(workbook_id)
        if wb is None:
            raise DataImportError("Çalışma kitabı artık açık değil. Listeyi yenileyin.")
        try:
            ws = wb.Worksheets(sheet)
            return _as_rows(ws.UsedRange.Value)
        except Exception as exc:
            raise DataImportError(_com_message(exc), detail=str(exc)) from exc


    def formula_rows(self, workbook_id: str, sheet: str, n: int = PREVIEW_ROWS + 10) -> FormulaGrid:
        wb = self._cache.get(workbook_id)
        if wb is None:
            raise DataImportError("Çalışma kitabı artık açık değil. Listeyi yenileyin.")
        try:
            ws = wb.Worksheets(sheet)
            ur = ws.UsedRange
            nr, nc = int(ur.Rows.Count), int(ur.Columns.Count)
            rng = ur.Resize(min(nr, n), nc)
            # .Formula İngilizce yazımı (virgül ayırıcı) verir; çevirici ikisini de tanır
            return FormulaGrid(int(getattr(ur, "Row", 1)), int(getattr(ur, "Column", 1)), _as_rows(rng.Formula))
        except DataImportError:
            raise
        except Exception as exc:
            raise DataImportError(_com_message(exc), detail=str(exc)) from exc


def _com_message(exc) -> str:
    text = str(exc)
    if "0x8001010a" in text.lower() or "-2147418111" in text or "call was rejected" in text.lower() \
            or "reddedildi" in text.lower():
        return ("Excel şu anda meşgul (bir hücre düzenleniyor veya bir pencere açık olabilir). "
                "Excel'de Enter veya Esc'e basıp tekrar deneyin.")
    return "Açık Excel kitaplarına erişilemedi. Excel açık mı?"


def _excel_applications():  # pragma: no cover - yalnız Windows'ta çalışır
    """Çalışan tüm Excel örneklerini bulur."""
    import pythoncom
    import win32com.client

    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    apps, seen = [], set()
    try:
        rot = pythoncom.GetRunningObjectTable()
        ctx = pythoncom.CreateBindCtx(0)
        for mon in rot:
            try:
                display = mon.GetDisplayName(ctx, None)
            except Exception:
                continue
            low = display.lower()
            if not (low.endswith((".xlsx", ".xlsm", ".xls", ".xlsb", ".csv")) or "excel" in low
                    or "kitap" in low or "book" in low):
                continue
            try:
                obj = rot.GetObject(mon)
                disp = win32com.client.Dispatch(obj.QueryInterface(pythoncom.IID_IDispatch))
                app = disp.Application
                hwnd = int(app.Hwnd)
                if hwnd in seen:
                    continue
                seen.add(hwnd)
                apps.append(app)
            except Exception:
                continue
    except Exception:
        pass
    if not apps:
        try:
            apps.append(win32com.client.GetActiveObject("Excel.Application"))
        except Exception:
            pass
    return apps


# ---------------------------------------------------------------------- dosya
class FileWorkbookProvider(Provider):
    name = "Dosya"

    def __init__(self, paths: list[str]):
        self.paths = list(paths)
        self._raw: dict[tuple[str, str], list[list]] = {}

    def list_workbooks(self) -> list[WorkbookRef]:
        from . import io as sio

        out = []
        for p in self.paths:
            ext = os.path.splitext(p)[1].lower()
            ref = WorkbookRef(id=p, name=os.path.basename(p), path=p, saved=True, origin="file")
            try:
                if ext in sio.CSV_EXT:
                    df = sio.read_csv(p, header=False)
                    sheets = {"CSV": [list(r) for r in df.itertuples(index=False)]}
                else:
                    with pd.ExcelFile(p, engine=sio.excel_engine()) as xf:
                        sheets = {}
                        for s in xf.sheet_names:
                            raw = xf.parse(s, header=None, dtype=object)
                            sheets[s] = [[None if (isinstance(v, float) and pd.isna(v)) else
                                          (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for v in r]
                                         for r in raw.itertuples(index=False)]
            except Exception as exc:
                raise DataImportError(f"Dosya okunamadı: {os.path.basename(p)}", detail=str(exc)) from exc
            for s, rows in sheets.items():
                self._raw[(p, s)] = rows
                ref.sheets.append(SheetRef(s, rows[:PREVIEW_ROWS], len(rows), max((len(r) for r in rows), default=0)))
            out.append(ref)
        return out

    def read(self, workbook_id: str, sheet: str) -> list[list]:
        if (workbook_id, sheet) not in self._raw:
            self.list_workbooks()
        return self._raw[(workbook_id, sheet)]

    def formula_rows(self, workbook_id: str, sheet: str, n: int = PREVIEW_ROWS + 10) -> FormulaGrid:
        """Kaydedilmiş .xlsx dosyasındaki formüller (openpyxl, salt okunur)."""
        if os.path.splitext(workbook_id)[1].lower() not in (".xlsx", ".xlsm"):
            raise DataImportError("Formüller yalnız .xlsx/.xlsm dosyalarından okunabilir.")
        try:
            from openpyxl import load_workbook
            wb = load_workbook(workbook_id, read_only=True, data_only=False)
            try:
                ws = wb[sheet]
                rows, first_row, first_col = [], None, None
                for row in ws.iter_rows(min_row=1, max_row=n):
                    cells = [c for c in row if getattr(c, "column", None) is not None]
                    if not cells:
                        rows.append([])
                        continue
                    first_col = min(first_col or cells[0].column, cells[0].column)
                    rows.append([(c.column, c.value) for c in cells])
            finally:
                wb.close()
        except DataImportError:
            raise
        except Exception as exc:
            raise DataImportError(f"Formüller okunamadı: {os.path.basename(workbook_id)}", detail=str(exc)) from exc
        first_col = first_col or 1
        out = []
        for r in rows:
            line = []
            for col, v in r:
                while len(line) < col - first_col:
                    line.append(None)
                line.append(v if not hasattr(v, "text") else getattr(v, "text", None))
            out.append(line)
        return FormulaGrid(1, first_col, out)


class MultiProvider(Provider):
    """Açık Excel + ek dosyaları tek listede birleştirir."""

    name = "Açık Excel ve dosyalar"

    def __init__(self, providers: list[Provider]):
        self.providers = providers
        self._owner: dict[str, Provider] = {}

    def available(self):
        msgs = [m for ok, m in (p.available() for p in self.providers) if not ok]
        return any(p.available()[0] for p in self.providers), " ".join(msgs)

    def list_workbooks(self):
        out = []
        for p in self.providers:
            if not p.available()[0]:
                continue
            for wb in p.list_workbooks():
                self._owner[wb.id] = p
                out.append(wb)
        return out

    def read(self, workbook_id, sheet):
        return self._owner[workbook_id].read(workbook_id, sheet)

    def formula_rows(self, workbook_id, sheet, n=PREVIEW_ROWS + 10):
        return self._owner[workbook_id].formula_rows(workbook_id, sheet, n)


def default_provider() -> ComExcelProvider:
    return ComExcelProvider()
