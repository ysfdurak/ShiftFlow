"""Aynı değerin farklı yazılışlarını (boşluk / büyük-küçük harf) bulma ve birleştirme.

Kural: değerler sessizce değiştirilmez. Bir adım karşılaştırma, gruplama veya
tekrar kontrolü yaptığı sütunlarda farklı yazılış bulursa uyarı üretir; arayüz
kullanıcıya "düzeltilsin mi?" diye sorar. Kullanıcı onaylarsa adımın önüne
"Yazımı birleştir" adımı eklenir. Bu adım her çalıştırmada yeni veride de
uygulanır.
"""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from .values import tr_lower

_WS = re.compile(r"\s+")
_COMPARE = re.compile(r"(<>|<=|>=|=|<|>)|\b(EĞERSAY|ÇOKEĞERSAY|ETOPLA|ÇOKETOPLA|ORTALAMAEĞER|ÇOKEĞERORTALAMA|"
                      r"MAKEĞER|MİNEĞER|COUNTIFS?|SUMIFS?|AVERAGEIFS?|MAXIFS|MINIFS)\b", re.I)


def norm_text(v) -> str:
    """Karşılaştırma anahtarı: baş/son boşluk atılır, iç boşluklar teke iner, harfler küçültülür."""
    return tr_lower(_WS.sub(" ", str(v)).strip())


def find_variants(series: pd.Series, max_groups: int = 50) -> dict[str, list[str]]:
    """Normalleştirince aynı olan ama farklı yazılmış metin değerlerini döndürür.

    Dönüş: {en_sık_yazılış: [tüm yazılışlar, sıklık sırasıyla]}"""
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series) \
            or pd.api.types.is_bool_dtype(series):
        return {}
    s = series.dropna()
    s = s[s.map(lambda v: isinstance(v, str))]
    if s.empty:
        return {}
    counts = Counter(s.tolist())
    groups: dict[str, list[str]] = {}
    for val in counts:
        groups.setdefault(norm_text(val), []).append(val)
    out = {}
    for key, vals in groups.items():
        if len(vals) < 2 or key == "":
            continue
        vals.sort(key=lambda v: (-counts[v], v))
        out[vals[0]] = vals
        if len(out) >= max_groups:
            break
    return out


def _condition_cols(conds) -> list[str]:
    return [c.get("column") for c in conds or [] if c.get("column")]


def _formula_cols(*exprs) -> list[str]:
    from .expression import referenced_columns
    cols = []
    for e in exprs:
        if isinstance(e, str) and e.strip() and _COMPARE.search(e):
            try:
                cols += referenced_columns(e)
            except Exception:
                pass
    return cols


def concern_columns(op: str, p: dict) -> list[str]:
    """Bir adımın değerleri karşılaştırdığı / grupladığı sütunlar."""
    if p.get("ignore_variants"):
        return []
    cols: list[str] = []
    if op == "filter":
        cols = _condition_cols(p.get("conditions"))
    elif op == "dedupe":
        cols = list(p.get("columns") or [])
    elif op == "group":
        cols = list(p.get("by") or [])
    elif op == "pivot":
        cols = list(p.get("rows") or []) + list(p.get("columns") or [])
    elif op == "calc":
        cols = _formula_cols(p.get("formula"))
    elif op == "conditional":
        cols = _condition_cols(p.get("conditions")) + _formula_cols(p.get("then"), p.get("else"))
    elif op == "rules":
        for r in p.get("rules") or []:
            cols += _condition_cols(r.get("conditions")) + _formula_cols(r.get("value"))
        cols += _formula_cols(p.get("default"))
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def check(df: pd.DataFrame, op: str, p: dict) -> dict[str, dict[str, list[str]]]:
    """{sütun: {en_sık: [yazılışlar]}} — yalnız farklı yazılış bulunan sütunlar."""
    out = {}
    for c in concern_columns(op, p):
        if c in df.columns:
            v = find_variants(df[c])
            if v:
                out[c] = v
    return out


def _show(v: str) -> str:
    return "'" + v.replace("\t", "→") + "'"


def describe(found: dict[str, dict[str, list[str]]], limit: int = 3) -> list[str]:
    lines = []
    for col, groups in found.items():
        ex = list(groups.values())[:limit]
        sample = "; ".join(", ".join(_show(x) for x in g[:4]) for g in ex)
        more = f" (+{len(groups) - limit} değer daha)" if len(groups) > limit else ""
        lines.append(f"{col}: aynı değerin farklı yazılışları var — {sample}{more}. "
                     f"Boşluk/harf farkı yüzünden ayrı değer sayılıyor.")
    return lines


def unify(series: pd.Series) -> tuple[pd.Series, int]:
    """Her farklı yazılışı o grubun en sık yazılışıyla değiştirir. (yeni seri, değişen hücre)"""
    groups = find_variants(series, max_groups=10 ** 9)
    mapping = {v: best for best, vals in groups.items() for v in vals if v != best}
    if not mapping:
        return series, 0
    obj = series.astype(object)
    changed = int(obj.isin(list(mapping)).sum())
    new = obj.map(lambda v: mapping.get(v, v) if isinstance(v, str) else v)
    return new, changed
