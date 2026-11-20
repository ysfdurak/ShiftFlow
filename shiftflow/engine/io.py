"""Veri içe ve dışa aktarma.

Kaynak dosyalar yalnızca okunur. Dışa aktarma, bir kaynak dosyanın
üzerine yazmayı reddeder.
"""

from __future__ import annotations

import csv
import io as _io
import os
import re

import pandas as pd

from .errors import DataImportError, ExportError
from .values import infer_types

try:  # Hızlı okuma motoru; yoksa openpyxl kullanılır.
    import python_calamine  # noqa: F401

    _EXCEL_ENGINE = "calamine"
except ImportError:  # pragma: no cover
    _EXCEL_ENGINE = "openpyxl"

EXCEL_EXT = {".xlsx", ".xlsm", ".xls"}
CSV_EXT = {".csv", ".txt", ".tsv"}


def excel_engine() -> str:
    return _EXCEL_ENGINE


def list_sheets(path: str) -> list[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXCEL_EXT:
        return []
    try:
        with pd.ExcelFile(path, engine=_EXCEL_ENGINE) as xf:
            return list(xf.sheet_names)
    except Exception as exc:
        raise DataImportError(
            f"Excel dosyası açılamadı: {os.path.basename(path)}. "
            "Dosya bozuk, parola korumalı veya başka bir programda kilitli olabilir.",
            detail=str(exc),
        ) from exc


def clean_headers(df: pd.DataFrame, header: bool) -> pd.DataFrame:
    """Başlıkları düzenler: boş başlık -> 'Sütun N', tekrarlar -> 'Ad_2'."""
    if not header:
        df.columns = [f"Sütun {i + 1}" for i in range(df.shape[1])]
        return df
    names, seen = [], {}
    for i, c in enumerate(df.columns):
        if c is None or (isinstance(c, float) and pd.isna(c)):
            name = ""
        elif isinstance(c, float) and c.is_integer():
            name = str(int(c))
        elif isinstance(c, pd.Timestamp):
            name = c.strftime("%d.%m.%Y")
        else:
            name = str(c).strip()
        if not name or name.startswith("Unnamed:"):
            name = f"Sütun {i + 1}"
        base = name
        n = seen.get(base, 0)
        while name in names:
            n += 1
            name = f"{base}_{n + 1}"
        seen[base] = n
        names.append(name)
    df.columns = names
    return df


def _drop_empty_edges(df: pd.DataFrame) -> pd.DataFrame:
    """Tamamen boş satır ve sütunları atar (Excel raporlarında sık görülür)."""
    def _blank(v):
        return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())

    if df.empty:
        return df
    blank = df.map(_blank)
    df = df.loc[~blank.all(axis=1), ~blank.all(axis=0)]
    return df.reset_index(drop=True)


def read_excel(path: str, sheet: str | None = None, header: bool = True) -> pd.DataFrame:
    try:
        raw = pd.read_excel(
            path, sheet_name=sheet if sheet else 0, header=None, engine=_EXCEL_ENGINE, dtype=object
        )
    except ValueError as exc:
        raise DataImportError(f"'{sheet}' adlı çalışma sayfası bulunamadı.", detail=str(exc)) from exc
    except Exception as exc:
        raise DataImportError(
            f"Excel dosyası okunamadı: {os.path.basename(path)}.", detail=str(exc)
        ) from exc
    return _finish(raw, header)


def _finish(raw: pd.DataFrame, header: bool) -> pd.DataFrame:
    raw = _drop_empty_edges(raw)
    if raw.empty:
        raise DataImportError("Seçilen kaynakta veri bulunamadı (tablo boş).")
    if header:
        cols = list(raw.iloc[0])
        df = raw.iloc[1:].reset_index(drop=True)
        df.columns = cols
    else:
        df = raw
    df = clean_headers(df, header)
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v)
    df = df.replace({"": None})
    return infer_types(df)


def frame_from_rows(rows: list[list], header_row: int = 0, header: bool = True) -> pd.DataFrame:
    """Ham satırlardan (açık Excel, ham sayfa) tablo üretir.

    `header_row` başlık satırının sırasıdır; üstündeki rapor başlığı/tarih
    satırları atılır. Altındaki tamamen boş satırlar da atılır.
    """
    body = rows[header_row:] if header_row else rows
    if not body:
        raise DataImportError("Seçilen kaynakta veri bulunamadı (tablo boş).")
    width = max(len(r) for r in body)
    raw = pd.DataFrame([list(r) + [None] * (width - len(r)) for r in body], dtype=object)
    return _finish(raw, header)


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (";", "\t", ",", "|")}
        return max(counts, key=counts.get)


def read_csv(path: str, header: bool = True, delimiter: str | None = None) -> pd.DataFrame:
    data = None
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            with open(path, encoding=enc) as fh:
                data = fh.read()
            break
        except UnicodeDecodeError:
            continue
    if data is None:  # pragma: no cover
        raise DataImportError("CSV dosyasının karakter kodlaması tanınamadı.")
    return parse_text_table(data, header=header, delimiter=delimiter)


def parse_text_table(text: str, header: bool = True, delimiter: str | None = None) -> pd.DataFrame:
    """CSV veya Excel'den kopyalanan (sekmeyle ayrılmış) metni tabloya çevirir."""
    if not text or not text.strip():
        raise DataImportError("Yapıştırılan içerik boş.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if delimiter is None:
        delimiter = "\t" if "\t" in text.split("\n", 1)[0] else _sniff_delimiter(text[:5000])
    try:
        raw = pd.read_csv(
            _io.StringIO(text), sep=delimiter, header=None, dtype=str,
            keep_default_na=False, skip_blank_lines=True, engine="python",
            quoting=csv.QUOTE_MINIMAL,
        )
    except Exception as exc:
        raise DataImportError("Metin tablo olarak okunamadı. Ayırıcı karakteri kontrol edin.",
                              detail=str(exc)) from exc
    raw = raw.astype(object)
    return _finish(raw, header)


FILE_COLUMN = "Kaynak dosya"


def is_pattern(path: str) -> bool:
    """Klasör kaynağı: yol bir desen içerir (C:\\Raporlar\\toplama_*.xlsx)."""
    return bool(path) and any(ch in os.path.basename(path) for ch in "*?")


def folder_files(pattern: str) -> list[str]:
    import glob
    files = [f for f in glob.glob(pattern) if os.path.isfile(f)
             and not os.path.basename(f).startswith("~$")]  # Excel'in kilit dosyaları
    return sorted(files, key=lambda f: (os.path.getmtime(f), f))


def read_folder(pattern: str, sheet: str | None = None, header: bool = True) -> pd.DataFrame:
    """Desene uyan tüm dosyaları alt alta okur; her satıra '{FILE_COLUMN}' sütunu eklenir.

    Sütunları farklı dosyalar birleşimle (eksik sütunlar boş) okunur ve `df.attrs["notes"]` içinde bildirilir."""
    files = folder_files(pattern)
    if not files:
        raise DataImportError(f"Bu desene uyan dosya yok: {pattern}")
    frames, notes, first_cols = [], [], None
    for f in files:
        try:
            df = read_source(f, sheet, header)
        except DataImportError as exc:
            raise DataImportError(f"{os.path.basename(f)} okunamadı: {exc.message}", detail=exc.detail) from exc
        if first_cols is None:
            first_cols = list(df.columns)
        else:
            miss = [c for c in first_cols if c not in df.columns]
            extra = [c for c in df.columns if c not in first_cols]
            if miss or extra:
                notes.append(f"{os.path.basename(f)}: " + "; ".join(
                    ([f"eksik sütun: {', '.join(map(str, miss))}"] if miss else [])
                    + ([f"fazla sütun: {', '.join(map(str, extra))}"] if extra else [])))
        df = df.copy()
        df[FILE_COLUMN] = os.path.basename(f)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True, sort=False)
    cols = [c for c in out.columns if c != FILE_COLUMN] + [FILE_COLUMN]
    out = out[cols]
    out.attrs["notes"] = [f"{len(files)} dosya okundu, {len(out):,} satır.".replace(",", ".")] + notes
    out.attrs["files"] = [os.path.basename(f) for f in files]
    return out


def read_source(path: str, sheet: str | None = None, header: bool = True) -> pd.DataFrame:
    if is_pattern(path):
        return read_folder(path, sheet, header)
    if not os.path.exists(path):
        raise DataImportError(f"Dosya bulunamadı: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in EXCEL_EXT:
        return read_excel(path, sheet, header)
    if ext in CSV_EXT:
        return read_csv(path, header)
    raise DataImportError(f"Desteklenmeyen dosya türü: {ext}. Excel (.xlsx) veya CSV seçin.")


# Excel çıktısı ayrı modülde (grafik ve şablon desteğiyle). Eski adlar korunur.
from .excel_out import safe_sheet_name, write_excel  # noqa: E402,F401
