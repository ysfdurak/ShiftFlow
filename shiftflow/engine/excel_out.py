"""Excel çıktısı: çok sayfalı tablo, gerçek Excel grafikleri ve şablona yazma.

Sayfa seçenekleri (iş akışındaki her çıktı satırında saklanır):
    {"dataset": "Ekip Özeti", "sheet": "Özet",
     "start_cell": "A5",              # şablonda tablonun başlayacağı hücre (varsayılan A1)
     "chart": {"type": "col",         # col (sütun), bar (yatay çubuk), line (çizgi), pie (pasta)
               "category": "Ekip Lideri",
               "values": ["Toplanan Adet (Toplam)"],   # boşsa: tüm sayısal sütunlar
               "title": "Ekiplere göre toplama",
               "position": "right"}}  # right | below

Şablon (iş akışı çıktı ayarlarında):
    {"path": "C:/.../vardiya_sablonu.xlsx",
     "cells": [{"sheet": "Kapak", "cell": "B2", "value": "{vardiya} vardiyası – {tarih}"}]}

Şablondaki biçimler, sütun genişlikleri, birleştirilmiş hücreler, koşullu
biçimlendirme ve FORMÜLLER korunur. Excel dosyayı açınca şablondaki
formüller yeni veriyle hesaplanır; böylece özet hücreleri şablonda formülle
kurulabilir. Uyarı: openpyxl şablondaki resimleri (logo) ve şablonda
hazır duran grafikleri koruyamaz; ShiftFlow'un eklediği grafikler sorunsuzdur.
"""

from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd

from .errors import ExportError, ShiftFlowError

TOTAL_LABEL = "Genel Toplam"
CHART_TYPES = {"col": "Sütun", "bar": "Yatay çubuk", "line": "Çizgi", "pie": "Pasta"}
MAX_CHART_POINTS = 200
_BAD_SHEET = re.compile(r"[\[\]\:\*\?\/\\]")


def safe_sheet_name(name: str, used: set[str]) -> str:
    base = _BAD_SHEET.sub("_", str(name)).strip("'") or "Sayfa"
    base = base[:31]
    candidate, n = base, 1
    while candidate.lower() in {u.lower() for u in used}:
        n += 1
        suffix = f" ({n})"
        candidate = base[: 31 - len(suffix)] + suffix
    used.add(candidate)
    return candidate


def template_warnings(path: str) -> list[str]:
    """Şablonda korunamayacak öğeleri bildirir."""
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return ["Şablon dosyası okunamadı (.xlsx olmalı)."]
    if any(n.startswith("xl/media/") for n in names):
        out.append("Şablondaki resimler (logo vb.) çıktıya taşınamaz.")
    if any(n.startswith("xl/charts/") for n in names):
        out.append("Şablonda hazır duran grafikler çıktıya taşınamaz; grafikleri ShiftFlow'un çıktı ayarlarından ekleyin.")
    if any(n.startswith("xl/pivotTables/") for n in names):
        out.append("Şablondaki Excel PivotTable'ları korunamaz.")
    if any(n.endswith("vbaProject.bin") for n in names):
        out.append("Şablondaki makrolar korunamaz.")
    return out


def fill_placeholders(text, context: dict | None):
    if not isinstance(text, str) or not context:
        return text
    return re.sub(r"\{(\w+)\}", lambda m: str(context.get(m.group(1), m.group(0))), text)


def _py(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime().replace(tzinfo=None)
    if isinstance(v, np.generic):
        v = v.item()
        if isinstance(v, float) and np.isnan(v):
            return None
    return v


def _cell_ref(ref: str) -> tuple[int, int]:
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
    try:
        col, row = coordinate_from_string((ref or "A1").strip().upper())
    except Exception as exc:
        raise ShiftFlowError(f"Hücre adresi anlaşılamadı: '{ref}' (örn. A5).") from exc
    return row, column_index_from_string(col)


COLORS = {"red": ("FFC7CE", "9C0006", "Kırmızı"), "green": ("C6EFCE", "006100", "Yeşil"),
          "yellow": ("FFEB9C", "9C5700", "Sarı"), "blue": ("DDEBF7", "1F4E78", "Mavi"),
          "gray": ("EDEDED", "404040", "Gri")}
RULE_OPS = {">": "greaterThan", "<": "lessThan", ">=": "greaterThanOrEqual", "<=": "lessThanOrEqual",
            "=": "equal", "<>": "notEqual"}


def _add_rules(ws, df, row0, col0, rules, warnings):
    """Koşullu renk (Excel'in kendi koşullu biçimlendirmesi; dosyada değer değişince renk de değişir)."""
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    if not len(df):
        return
    cols = list(map(str, df.columns))
    last_row = row0 + len(df)
    for rule in rules:
        col = str(rule.get("column", ""))
        if col not in cols:
            if warnings is not None:
                warnings.append(f"Koşullu renk: '{col}' sütunu çıktıda yok; kural atlandı.")
            continue
        letter = get_column_letter(col0 + cols.index(col))
        fill_c, font_c, _ = COLORS.get(rule.get("color", "red"), COLORS["red"])
        fill = PatternFill("solid", start_color=fill_c, end_color=fill_c)
        font = Font(color=font_c)
        raw = str(rule.get("value", "")).strip()
        from .values import _parse_number_text
        num = _parse_number_text(raw) if raw else None
        val = str(num) if num is not None else '"' + raw.replace('"', '""') + '"'
        op = rule.get("op", ">")
        first, end_col = f"{letter}{row0 + 1}", get_column_letter(col0 + len(cols) - 1)
        if rule.get("whole_row"):
            sym = {"=": "=", "<>": "<>"}.get(op, op)
            rng = f"{get_column_letter(col0)}{row0 + 1}:{end_col}{last_row}"
            ref = f"${letter}{row0 + 1}"
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f"{ref}{sym}{val}"], fill=fill, font=font))
        else:
            ws.conditional_formatting.add(f"{first}:{letter}{last_row}",
                                          CellIsRule(operator=RULE_OPS.get(op, "greaterThan"), formula=[val],
                                                     fill=fill, font=font))


_NO_SUM_WORDS = ("%", "oran", "yüzde", "yuzde", "ortalama", "ort.", "ratio", "rate", "percent", "skor", "puan")
_ID_SUFFIX = (" no", "no", " id", "id", " kodu", " kod", " numarası", " numarasi")


def _summable(name) -> bool:
    """Toplamı anlamlı sütun mu? Yüzde/oran/ortalama ve kimlik (No, ID, Kod) sütunları toplanmaz:
    önceden 'Gerçekleşme %' sütunu toplanıp 385,50 gibi anlamsız bir sayı yazılıyordu."""
    low = str(name).strip().lower()
    if any(w in low for w in _NO_SUM_WORDS):
        return False
    return not any(low == s.strip() or low.endswith(s) for s in _ID_SUFFIX)


def _add_totals(ws, df, row0, col0):
    """Tablonun altına toplam satırı: ALTTOPLAM(109; …) — Excel'de filtrelenince yalnız görünenleri toplar."""
    from openpyxl.styles import Border, Font, Side
    from openpyxl.utils import get_column_letter
    if not len(df):
        return
    r = row0 + len(df) + 1
    first, last = row0 + 1, row0 + len(df)
    bold, top = Font(bold=True), Border(top=Side(style="thin"))
    label_done = False
    for j, c in enumerate(df.columns):
        cell = ws.cell(row=r, column=col0 + j)
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            if not _summable(c):
                cell.border = top
                continue
            L = get_column_letter(col0 + j)
            cell.value = f"=SUBTOTAL(109,{L}{first}:{L}{last})"
            cell.number_format = "#,##0" if (s.dropna() % 1 == 0).all() else "#,##0.00"
        elif not label_done:
            cell.value = "Toplam"
            label_done = True
        cell.font, cell.border = bold, top


def _write_formulas(ws, df: pd.DataFrame, row0: int, col0: int, formulas: dict):
    """'Excel'de hesaplanacak' sütunlara her satır için Excel formülü yazar (Excel açınca hesaplar)."""
    from openpyxl.utils import get_column_letter

    from .excel_formula import render_template
    letters = {str(c): get_column_letter(col0 + j) for j, c in enumerate(df.columns)}
    for name, tpl in formulas.items():
        if name not in letters:
            continue
        j = list(map(str, df.columns)).index(name)
        for i in range(len(df)):
            r = row0 + 1 + i
            c = ws.cell(row=r, column=col0 + j, value=render_template(tpl, letters, r))
            c.number_format = "General"


def _write_table(ws, df: pd.DataFrame, row0: int, col0: int, styled: bool, clear: bool):
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    ncols = df.shape[1]
    if clear and ws.max_row >= row0:
        for r in ws.iter_rows(min_row=row0, max_row=ws.max_row, min_col=col0, max_col=col0 + max(ncols, 1) - 1):
            for c in r:
                if not isinstance(c.value, str) or not c.value.startswith("="):
                    c.value = None
    fill = PatternFill("solid", fgColor="DDE7F0")
    for j, name in enumerate(df.columns):
        c = ws.cell(row=row0, column=col0 + j, value=str(name))
        if styled:
            c.font = Font(bold=True)
            c.fill = fill
    date_cols = {j for j, c in enumerate(df.columns) if pd.api.types.is_datetime64_any_dtype(df[c])}
    has_time = {j for j in date_cols if (df.iloc[:, j].dropna().dt.floor("D") != df.iloc[:, j].dropna()).any()}
    num_fmt = {}
    for j, c in enumerate(df.columns):
        s = df.iloc[:, j]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            vals = s.dropna()
            num_fmt[j] = "#,##0" if len(vals) == 0 or (vals % 1 == 0).all() else "#,##0.00"
    for i, row in enumerate(df.itertuples(index=False), start=1):
        for j, v in enumerate(row):
            c = ws.cell(row=row0 + i, column=col0 + j, value=_py(v))
            if c.value is None:
                continue
            if j in date_cols:
                c.number_format = "dd.mm.yyyy hh:mm" if j in has_time else "dd.mm.yyyy"
            elif j in num_fmt and c.number_format == "General":
                c.number_format = num_fmt[j]
    if styled:
        ws.freeze_panes = ws.cell(row=row0 + 1, column=col0)
        if len(df):
            ws.auto_filter.ref = f"{get_column_letter(col0)}{row0}:{get_column_letter(col0 + ncols - 1)}{row0 + len(df)}"
        for j, col in enumerate(df.columns):
            sample = [len(str(v)) for v in df[col].head(200) if not pd.isna(v)]
            width = max([len(str(col))] + sample)
            ws.column_dimensions[get_column_letter(col0 + j)].width = min(max(width + 2, 8), 50)


def _add_chart(ws, df: pd.DataFrame, row0: int, col0: int, spec: dict, sheet_label: str, warnings: list):
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.utils import get_column_letter

    cols = [str(c) for c in df.columns]
    cat = spec.get("category") or (cols[0] if cols else None)
    if cat not in cols:
        warnings.append(f"{sheet_label}: grafik için '{cat}' sütunu yok; grafik eklenmedi.")
        return
    wanted = spec.get("values") or [c for c in cols if c != cat and pd.api.types.is_numeric_dtype(df[c])]
    values = [v for v in wanted if v in cols and v != cat]
    missing = [v for v in wanted if v not in cols]
    if missing:
        warnings.append(f"{sheet_label}: grafikte bulunamayan sütunlar atlandı: {', '.join(missing)}")
    if spec.get("exclude_total", True):
        values = [v for v in values if v != TOTAL_LABEL and not v.endswith("| " + TOTAL_LABEL)]
    values = [v for v in values if pd.api.types.is_numeric_dtype(df[v])]
    if not values:
        warnings.append(f"{sheet_label}: grafik için sayısal değer sütunu yok; grafik eklenmedi.")
        return
    n = len(df)
    if spec.get("exclude_total", True) and n and str(df[cat].iloc[-1]) == TOTAL_LABEL:
        n -= 1
    if n == 0:
        warnings.append(f"{sheet_label}: tablo boş olduğu için grafik eklenmedi.")
        return
    if n > MAX_CHART_POINTS:
        warnings.append(f"{sheet_label}: grafik ilk {MAX_CHART_POINTS} satırla sınırlandı ({n} satır var).")
        n = MAX_CHART_POINTS
    typ = spec.get("type", "col")
    if typ == "pie":
        ch = PieChart()
        values = values[:1]
    elif typ == "line":
        ch = LineChart()
    else:
        ch = BarChart()
        ch.type = "bar" if typ == "bar" else "col"
    ch.title = spec.get("title") or (values[0] if len(values) == 1 else sheet_label)
    ch.width, ch.height = (22 if n > 12 else 16), (10 if typ != "bar" else max(8, min(25, 0.6 * n)))
    cat_idx = col0 + cols.index(cat)
    cats = Reference(ws, min_col=cat_idx, min_row=row0 + 1, max_row=row0 + n)
    for v in values:
        idx = col0 + cols.index(v)
        ch.add_data(Reference(ws, min_col=idx, min_row=row0, max_row=row0 + n), titles_from_data=True)
    ch.set_categories(cats)
    if typ != "pie":
        # openpyxl eksenleri varsayılan olarak "silinmiş" yazar; gerçek Excel'de eksen etiketleri
        # görünmüyordu (LibreOffice gösterdiği için testte fark edilmedi).
        ch.x_axis.delete = False
        ch.y_axis.delete = False
    if typ != "pie" and len(values) == 1:
        ch.legend = None
    if spec.get("position") == "below":
        anchor = f"{get_column_letter(col0)}{row0 + len(df) + 3}"
    else:
        anchor = f"{get_column_letter(col0 + len(cols) + 1)}{row0}"
    ws.add_chart(ch, anchor)


def write_excel(path: str, sheets: list, protected_paths=(), template: dict | None = None,
                context: dict | None = None, warnings: list | None = None) -> list[str]:
    """Veri kümelerini sayfalara yazar. Yazılan sayfa adlarını döner.

    sheets: [(sayfa adı, tablo)] veya [(sayfa adı, tablo, seçenekler)].
    """
    from openpyxl import Workbook, load_workbook

    warnings = warnings if warnings is not None else []
    if not sheets:
        raise ExportError("Dışa aktarılacak veri kümesi seçilmedi.")
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    target = os.path.normcase(os.path.abspath(path))
    for p in protected_paths:
        if p and os.path.normcase(os.path.abspath(p)) == target:
            raise ExportError("Çıktı dosyası bir kaynak veya şablon dosyasıyla aynı. Kaynak dosyalar korunur; "
                              "farklı bir dosya adı seçin.")
    tpath = (template or {}).get("path")
    if tpath:
        if not os.path.exists(tpath):
            raise ExportError(f"Şablon dosyası bulunamadı: {tpath}")
        try:
            wb = load_workbook(tpath)
        except Exception as exc:
            raise ExportError("Şablon dosyası açılamadı (.xlsx olmalı, parola korumasız).", detail=str(exc)) from exc
        warnings.extend(template_warnings(tpath))
        used = set(wb.sheetnames)
        fresh = False
    else:
        wb = Workbook()
        used = set()
        fresh = True
    default_ws = wb.active if fresh else None
    written = []
    for item in sheets:
        name, df = item[0], item[1]
        opts = item[2] if len(item) > 2 and item[2] else {}
        in_template = bool(tpath) and name in wb.sheetnames
        if in_template:
            ws, sname = wb[name], name
        else:
            sname = safe_sheet_name(name, used)
            if default_ws is not None:
                ws = default_ws
                ws.title = sname
                default_ws = None
            else:
                ws = wb.create_sheet(sname)
        row0, col0 = _cell_ref(opts.get("start_cell", "A1")) if in_template else (1, 1)
        out = df.copy()
        for c in out.columns:
            if isinstance(out[c].dtype, pd.DatetimeTZDtype):
                out[c] = out[c].dt.tz_localize(None)
        _write_table(ws, out, row0, col0, styled=not in_template, clear=in_template)
        if opts.get("formulas"):
            _write_formulas(ws, out, row0, col0, opts["formulas"])
        if opts.get("rules"):
            _add_rules(ws, out, row0, col0, opts["rules"], warnings)
        if opts.get("totals"):
            _add_totals(ws, out, row0, col0)
        if opts.get("chart"):
            _add_chart(ws, out, row0, col0, opts["chart"], sname, warnings)
        written.append(sname)
    for cell in (template or {}).get("cells", []) if tpath else []:
        sh = cell.get("sheet")
        if sh not in wb.sheetnames:
            warnings.append(f"Şablonda '{sh}' sayfası yok; {cell.get('cell')} hücresi yazılmadı.")
            continue
        r, c = _cell_ref(cell.get("cell"))
        wb[sh].cell(row=r, column=c, value=fill_placeholders(cell.get("value", ""), context))
    try:
        wb.save(path)
    except PermissionError as exc:
        raise ExportError("Dosyaya yazılamadı. Dosya Excel'de açık olabilir; kapatıp tekrar deneyin.",
                          detail=str(exc)) from exc
    return written
