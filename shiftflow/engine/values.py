"""Değer dönüştürme yardımcıları (Türkçe sayı biçimi, metin, tip tespiti)."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

_DATE_RE = r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(\s+\d{1,2}:\d{2}(:\d{2})?)?$"
_NUM_RE = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")


def _parse_number_text(text: str):
    """'1.234,56' / '1234.56' / '1,5' / '%12' gibi metinleri sayıya çevirir.

    Başarısız olursa None döner. Türk yerel ayarı esas alınır:
    hem nokta hem virgül varsa sondaki ayırıcı ondalıktır; yalnız virgül
    varsa virgül ondalıktır; yalnız nokta ve tam üç haneli gruplar varsa
    ("1.234.567") nokta binlik ayırıcıdır.
    """
    t = text.strip().replace(" ", "").replace(" ", "")
    if not t:
        return None
    for sym in ("₺", "TL", "$", "€"):
        t = t.replace(sym, "")
    percent = t.endswith("%") or t.startswith("%")
    t = t.strip("%")
    if "," in t and "." in t:
        # Ondalık ayırıcı sondaki işarettir; önündeki kısım ya düz rakam ya da
        # düzgün üçlü gruplar olmalı ("1.2.34,56" gibi bozuk gruplama sayı sayılmaz).
        dec, grp = (",", ".") if t.rfind(",") > t.rfind(".") else (".", ",")
        whole, _, frac = t.rpartition(dec)
        if dec in whole or not re.fullmatch(r"[+-]?\d{1,3}(" + re.escape(grp) + r"\d{3})+", whole) or (frac and not frac.isdigit()):
            return None
        t = whole.replace(grp, "") + "." + frac
    elif "," in t:
        if t.count(",") > 1:
            if not re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+", t):
                return None
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".")
    elif t.count(".") > 1 or re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", t):
        # 1.234.567 veya 12.345 -> binlik ayırıcı
        # (12.345 belirsizdir; Türk raporlarında binlik kabul edilir).
        # 01.11.2026 gibi tarihler 3'lü gruplara uymadığı için sayı sayılmaz.
        if not re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", t):
            return None
        t = t.replace(".", "")
    if not _NUM_RE.match(t):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v / 100 if percent else v


def to_number(series: pd.Series) -> tuple[pd.Series, int]:
    """Seriyi sayıya çevirir. (sonuç, çevrilemeyen dolu hücre sayısı) döner."""
    if pd.api.types.is_bool_dtype(series):
        return series.astype(float), 0
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float), 0
    out = np.full(len(series), np.nan)
    bad = 0
    for i, v in enumerate(series.to_numpy(dtype=object)):
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
            continue
        if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
            out[i] = float(v)
            continue
        s = str(v)
        if not s.strip():
            continue
        p = _parse_number_text(s)
        if p is None:
            bad += 1
        else:
            out[i] = p
    return pd.Series(out, index=series.index, name=series.name), bad


def is_empty(series: pd.Series) -> pd.Series:
    """Boş hücre maskesi: NaN/None veya yalnız boşluktan oluşan metin."""
    mask = series.isna()
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        s = series.astype("string")
        mask = mask | s.str.strip().eq("").fillna(False).astype(bool)
    return mask.astype(bool)


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def tr_title(s: str) -> str:
    return " ".join(tr_upper(w[:1]) + tr_lower(w[1:]) for w in s.split(" "))


def infer_types(df: pd.DataFrame, min_ratio: float = 1.0) -> pd.DataFrame:
    """Metin olarak okunan sütunlarda sayı ve tarih tipini tahmin eder.

    Bir sütun yalnızca dolu hücrelerinin tamamı sayıya çevrilebiliyorsa
    sayı yapılır. Başında sıfır olan kodlar ("00123") metin kalır, çünkü
    bunlar genellikle ürün/lokasyon kodudur.
    """
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if s.dtype != object and not pd.api.types.is_string_dtype(s):
            continue
        filled = s[~is_empty(s)]
        if filled.empty:
            continue
        sample = filled.head(2000)
        stxt = sample.astype(str).str.strip()
        if stxt.str.match(_DATE_RE).all():
            parsed = pd.to_datetime(s.astype("string").str.strip(), dayfirst=True, errors="coerce", format="mixed")
            if parsed[~is_empty(s)].notna().all():
                out[col] = parsed
                continue
        if sample.astype(str).str.strip().str.match(r"^0\d+$").any():
            continue
        # 16+ haneli tam sayılar (barkod, seri no, IBAN parçası) sayıya çevrilince
        # son haneleri yuvarlanır ve farklı kodlar aynı değere düşer: metin kalır.
        if filled.astype(str).str.strip().str.match(r"^[+-]?\d{16,}$").any():
            continue
        _, bad_sample = to_number(sample)
        if bad_sample and not sample.astype(str).str.strip().str.match(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}").all():
            continue  # açıkça metin sütunu; tamamını taramaya gerek yok
        txt = filled.astype(str).str.strip()
        if txt.str.match(r"^0\d+$").any():
            continue
        num, bad = to_number(filled) if not bad_sample else (None, 1)
        if bad == 0:
            full, _ = to_number(s)
            if (full.dropna() % 1 == 0).all() and full.notna().any():
                full = full.astype("Int64") if full.isna().any() else full.astype("int64")
            out[col] = full
            continue
        if txt.str.match(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}").all():
            parsed = pd.to_datetime(txt, dayfirst=True, errors="coerce")
            if parsed.notna().all():
                out[col] = pd.to_datetime(s.astype("string").str.strip(), dayfirst=True, errors="coerce")
    return out


def type_label(series: pd.Series) -> str:
    """Kullanıcıya gösterilecek sade tip adı."""
    if pd.api.types.is_bool_dtype(series):
        return "Evet/Hayır"
    if pd.api.types.is_integer_dtype(series):
        return "Tam sayı"
    if pd.api.types.is_numeric_dtype(series):
        return "Sayı"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "Tarih"
    return "Metin"


def type_kind(series: pd.Series) -> str:
    """İş akışında saklanan kaba tip: number / date / text."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    return "text"


def normalize_key(series: pd.Series) -> pd.Series:
    """Birleştirme anahtarını karşılaştırılabilir metne çevirir.

    1, 1.0 ve "1" aynı anahtar sayılır; baştaki/sondaki boşluk atılır.
    Boş anahtarlar None kalır (çağıran taraf eşleşmemelerini sağlar).
    """
    vals = series.to_numpy(dtype=object)
    out = []
    for v in vals:
        if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
        elif isinstance(v, (float, np.floating)) and float(v).is_integer():
            out.append(str(int(v)))
        elif isinstance(v, pd.Timestamp):
            out.append(v.isoformat())
        else:
            s = str(v).strip()
            out.append(s if s else None)
    return pd.Series(out, index=series.index, dtype=object)
