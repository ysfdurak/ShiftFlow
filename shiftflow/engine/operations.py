"""Veri işlemleri.

Her işlem saf bir fonksiyondur: girdi tablolarını değiştirmez, yeni tablo
üretir. Kayıt defteri (`REGISTRY`) yeni işlem türü eklemeyi tek yere
indirger: bir `Operation` tanımlayıp `register` ile kaydetmek yeterlidir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import expression
from .errors import JoinConfirmationRequired, MissingColumnError, ShiftFlowError, TypeMismatchError
from .values import (
    _parse_number_text,
    is_empty,
    normalize_key,
    to_number,
    tr_lower,
    tr_title,
    tr_upper,
)

EMPTY_LABEL = "(Boş)"


@dataclass
class OpResult:
    df: pd.DataFrame
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class Operation:
    key: str
    label: str
    run: Callable[[list[pd.DataFrame], dict, str], OpResult]
    describe: Callable[[dict], str]
    inputs: str = "1"  # "1", "2" veya "n"
    new_dataset: bool = False  # Sonuç ayrı veri kümesi mi (pivot, birleştirme)?
    # Adım başka veri kümelerinden okuyorsa (örn. DÜŞEYARA'nın arama tablosu) onların adları.
    refs: Callable[[dict], list[str]] | None = None
    # Adım çalıştırma bağlamına (seçili tarih/vardiya) ihtiyaç duyuyorsa True.
    uses_context: bool = False
    uses_params: bool = False  # formülde {parametre} kullanabilir (iş akışı parametreleri verilir)


REGISTRY: dict[str, Operation] = {}


def register(op: Operation) -> Operation:
    REGISTRY[op.key] = op
    return op


def get(key: str) -> Operation:
    if key not in REGISTRY:
        raise ShiftFlowError(f"Bilinmeyen işlem türü: '{key}'. İş akışı daha yeni bir sürümle kaydedilmiş olabilir.")
    return REGISTRY[key]


def _need(df: pd.DataFrame, cols, label: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise MissingColumnError(missing, df.columns, label)


def _fmt_n(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# ---------------------------------------------------------------- filtre

CONDITION_OPS = {
    "eq": "eşittir",
    "ne": "eşit değildir",
    "gt": "büyüktür",
    "ge": "büyük veya eşittir",
    "lt": "küçüktür",
    "le": "küçük veya eşittir",
    "contains": "içerir",
    "not_contains": "içermez",
    "startswith": "ile başlar",
    "endswith": "ile biter",
    "empty": "boştur",
    "not_empty": "boş değildir",
    "in_list": "listedekilerden biri",
}
NO_VALUE_OPS = {"empty", "not_empty"}


def _text(series: pd.Series) -> pd.Series:
    def f(v):
        if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        if isinstance(v, pd.Timestamp):
            return v.strftime("%d.%m.%Y")
        return tr_lower(str(v))
    return series.map(f)


def condition_mask(df: pd.DataFrame, cond: dict, label: str) -> pd.Series:
    col, op, value = cond.get("column"), cond.get("op"), cond.get("value")
    _need(df, [col], label)
    s = df[col]
    if op not in CONDITION_OPS:
        raise ShiftFlowError(f"Bilinmeyen koşul: {op}")
    if op == "empty":
        return is_empty(s)
    if op == "not_empty":
        return ~is_empty(s)
    if op == "in_list":
        wanted = {str(v) for v in (value or [])}
        keys = normalize_key(s).map(lambda k: EMPTY_LABEL if k is None else k)
        return keys.isin(wanted)
    if value is None:
        value = ""
    sval = str(value)
    ref = re.fullmatch(r"\[(.+)\]", sval.strip())
    if ref and op in ("eq", "ne", "gt", "ge", "lt", "le"):
        other = ref.group(1)
        _need(df, [other], label)
        sym = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}[op]
        return expression._compare(s, df[other], sym, expression._Ctx(df, label))
    if op in ("contains", "not_contains", "startswith", "endswith"):
        t, v = _text(s), tr_lower(sval)
        if op == "contains":
            return t.str.contains(v, regex=False)
        if op == "not_contains":
            return ~t.str.contains(v, regex=False)
        if op == "startswith":
            return t.str.startswith(v)
        return t.str.endswith(v)

    # eşitlik ve büyüklük karşılaştırmaları
    if pd.api.types.is_datetime64_any_dtype(s):
        target = pd.to_datetime(sval, dayfirst=True, errors="coerce")
        if pd.isna(target):
            raise TypeMismatchError(f"'{col}' bir tarih sütunu; '{sval}' tarih olarak anlaşılamadı (örn. 31.12.2026).")
        left = s
    else:
        num_val = _parse_number_text(sval)
        numeric_col = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        if op in ("eq", "ne") and (num_val is None or not numeric_col):
            t = _text(s)
            m = t == tr_lower(sval.strip())
            return m if op == "eq" else ~m
        if num_val is None:
            raise TypeMismatchError(f"'{sval}' sayı değil; '{CONDITION_OPS[op]}' karşılaştırması için sayı girin.")
        if numeric_col:
            left = s.astype(float)
        else:
            left, bad = to_number(s)
            if left.notna().sum() == 0:
                raise TypeMismatchError(
                    f"'{col}' sütunu sayı içermiyor; '{CONDITION_OPS[op]}' karşılaştırması yapılamaz."
                )
        target = num_val
    ops = {
        "eq": lambda a: a == target, "ne": lambda a: a != target,
        "gt": lambda a: a > target, "ge": lambda a: a >= target,
        "lt": lambda a: a < target, "le": lambda a: a <= target,
    }
    return ops[op](left).fillna(False).astype(bool)


def combined_mask(df, conditions, mode, label):
    if not conditions:
        raise ShiftFlowError("En az bir filtre koşulu girin.")
    masks = [condition_mask(df, c, label) for c in conditions]
    m = masks[0]
    for x in masks[1:]:
        m = (m & x) if mode != "or" else (m | x)
    return m


def describe_condition(c: dict) -> str:
    op = c.get("op")
    if op in NO_VALUE_OPS:
        return f"{c.get('column')} {CONDITION_OPS.get(op, op)}"
    if op == "in_list":
        vals = c.get("value") or []
        shown = ", ".join(map(str, vals[:3])) + (f" (+{len(vals) - 3})" if len(vals) > 3 else "")
        return f"{c.get('column')} ∈ {{{shown}}}"
    return f"{c.get('column')} {CONDITION_OPS.get(op, op)} {c.get('value')}"


def _run_filter(inputs, p, label):
    df = inputs[0]
    m = combined_mask(df, p.get("conditions", []), p.get("mode", "and"), label)
    out = df[m].reset_index(drop=True)
    r = OpResult(out)
    removed = len(df) - len(out)
    r.messages.append(f"{_fmt_n(removed)} satır elendi, {_fmt_n(len(out))} satır kaldı.")
    if len(out) == 0:
        r.warnings.append("Filtre sonucunda hiç satır kalmadı. Koşulları kontrol edin.")
    return r


register(Operation(
    "filter", "Filtre", _run_filter,
    lambda p: "Filtre: " + (" VE " if p.get("mode", "and") != "or" else " VEYA ").join(
        describe_condition(c) for c in p.get("conditions", [])),
))


# ---------------------------------------------------------------- sıralama

def _run_sort(inputs, p, label):
    df = inputs[0]
    keys = p.get("keys", [])
    if not keys:
        raise ShiftFlowError("Sıralama için en az bir sütun seçin.")
    _need(df, [k["column"] for k in keys], label)

    def keyfunc(s):
        if not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s)):
            return s.map(lambda v: tr_lower(str(v)) if isinstance(v, str) else v)
        return s
    out = df.sort_values(
        [k["column"] for k in keys], ascending=[k.get("ascending", True) for k in keys],
        kind="mergesort", na_position="last", key=keyfunc,
    ).reset_index(drop=True)
    return OpResult(out)


register(Operation(
    "sort", "Sırala", _run_sort,
    lambda p: "Sırala: " + ", ".join(
        f"{k['column']} {'A→Z' if k.get('ascending', True) else 'Z→A'}" for k in p.get("keys", [])),
))


# ---------------------------------------------------------------- sütun işlemleri

def _run_select(inputs, p, label):
    df = inputs[0]
    cols = p.get("columns", [])
    if not cols:
        raise ShiftFlowError("En az bir sütun seçin.")
    _need(df, cols, label)
    return OpResult(df[cols].copy())


register(Operation("select", "Sütun seç", _run_select,
                   lambda p: f"Sütun seç: {len(p.get('columns', []))} sütun"))


def _run_remove(inputs, p, label):
    df = inputs[0]
    cols = p.get("columns", [])
    _need(df, cols, label)
    if len(cols) >= df.shape[1]:
        raise ShiftFlowError("Tüm sütunlar kaldırılamaz; en az bir sütun kalmalı.")
    return OpResult(df.drop(columns=cols))


register(Operation("remove", "Sütun kaldır", _run_remove,
                   lambda p: "Sütun kaldır: " + ", ".join(p.get("columns", []))))


def _run_rename(inputs, p, label):
    df = inputs[0]
    mapping = {k: v for k, v in p.get("mapping", {}).items() if k != v}
    _need(df, list(mapping), label)
    for old, new in mapping.items():
        if not str(new).strip():
            raise ShiftFlowError(f"'{old}' için yeni ad boş olamaz.")
    final = [mapping.get(c, c) for c in df.columns]
    dup = {c for c in final if final.count(c) > 1}
    if dup:
        raise ShiftFlowError(f"Bu ad zaten kullanılıyor: {', '.join(dup)}")
    return OpResult(df.rename(columns=mapping))


register(Operation("rename", "Yeniden adlandır", _run_rename,
                   lambda p: "Yeniden adlandır: " + ", ".join(f"{a} → {b}" for a, b in p.get("mapping", {}).items())))


def _check_new_name(df, name, replace):
    name = str(name or "").strip()
    if not name:
        raise ShiftFlowError("Yeni sütun için bir ad girin.")
    if name in df.columns and not replace:
        raise ShiftFlowError(f"'{name}' adlı sütun zaten var. Başka bir ad seçin veya 'üzerine yaz'ı işaretleyin.")
    return name


def _tables(inputs, p, keys):
    names = _formula_refs(p, keys)
    out = dict(zip(names, inputs[1:]))
    if p.get("__params__"):
        out["__params__"] = p["__params__"]  # evaluate() bunu iş akışı parametreleri olarak alır
    return out


def _formula_refs(p, keys):
    out = []
    for k in keys:
        if k == "rules":
            vals = [r.get("value", "") for r in p.get("rules", [])]
        else:
            vals = [p.get(k, "")]
        for v in vals:
            for t in expression.referenced_tables(str(v or "")):
                if t not in out:
                    out.append(t)
    return out


def _run_calc(inputs, p, label):
    df = inputs[0]
    name = _check_new_name(df, p.get("name"), p.get("replace", False))
    notes: list[str] = []
    values, div0 = expression.evaluate(p.get("formula", ""), df, label, _tables(inputs, p, ["formula"]), notes)
    skipped = 0
    if p.get("only_filled"):
        # Excel'de formülün boş satırlara kadar aşağı çekilmesi gibi olmasın: formüldeki sütunların
        # hepsi boş olan satırlarda sonuç boş kalır.
        cols = [c for c in expression.referenced_columns(p.get("formula", "")) if c in df.columns]
        if cols:
            empty = pd.concat([_blank_mask(df[c]) for c in cols], axis=1).all(axis=1)
            skipped = int(empty.sum())
            if skipped:
                values = values.astype(object).where(~empty.to_numpy(), None)
    out = df.copy()
    out[name] = values.to_numpy()
    r = OpResult(out)
    if skipped:
        r.messages.append(f"{_fmt_n(skipped)} boş satıra formül uygulanmadı (yalnız dolu satırlar).")
    r.warnings.extend(notes)
    if div0:
        r.warnings.append(f"{_fmt_n(div0)} satırda sıfıra bölme oluştu; bu hücreler boş bırakıldı.")
    return r


register(Operation("calc", "Hesaplanan sütun", _run_calc,
                   lambda p: f"Hesapla: {p.get('name')} = {' '.join(str(p.get('formula', '')).split())}",
                   refs=lambda p: _formula_refs(p, ["formula"]), uses_params=True))


def _branch_value(expr: str, df, label, tables=None, notes=None):
    expr = (expr or "").strip()
    if not expr:
        return pd.Series([None] * len(df), index=df.index, dtype=object), 0
    try:
        return expression.evaluate(expr, df, label, tables, notes)
    except ShiftFlowError:
        # Tırnaksız yazılmış düz metin ("Yüksek") kabul edilir.
        if "[" not in expr and '"' not in expr:
            num = _parse_number_text(expr)
            val = num if num is not None else expr
            return pd.Series([val] * len(df), index=df.index), 0
        raise


def _run_conditional(inputs, p, label):
    df = inputs[0]
    name = _check_new_name(df, p.get("name"), p.get("replace", False))
    m = combined_mask(df, p.get("conditions", []), p.get("mode", "and"), label)
    tables, notes = _tables(inputs, p, ["then", "else"]), []
    then_v, d1 = _branch_value(p.get("then", ""), df, label, tables, notes)
    else_v, d2 = _branch_value(p.get("else", ""), df, label, tables, notes)
    res = then_v.where(m, else_v)
    out = df.copy()
    out[name] = res.to_numpy()
    r = OpResult(out)
    r.messages.append(f"Koşulu sağlayan satır: {_fmt_n(int(m.sum()))} / {_fmt_n(len(df))}")
    r.warnings.extend(notes)
    if d1 + d2:
        r.warnings.append("Bazı satırlarda sıfıra bölme oluştu; bu hücreler boş bırakıldı.")
    return r


register(Operation(
    "conditional", "Koşullu sütun", _run_conditional,
    lambda p: f"Koşullu: {p.get('name')} = EĞER({' VE '.join(describe_condition(c) for c in p.get('conditions', []))}; "
              f"{p.get('then')}; {p.get('else')})",
    refs=lambda p: _formula_refs(p, ["then", "else"]), uses_params=True,
))


TYPE_TARGETS = {"number": "Sayı", "integer": "Tam sayı", "text": "Metin", "date": "Tarih"}


def _run_convert(inputs, p, label):
    df = inputs[0]
    col, target = p.get("column"), p.get("to")
    _need(df, [col], label)
    s = df[col]
    out = df.copy()
    bad = 0
    if target in ("number", "integer"):
        conv, bad = to_number(s)
        if target == "integer":
            conv = conv.round().astype("Int64")
        out[col] = conv
    elif target == "text":
        out[col] = _text_keep_case(s)
    elif target == "date":
        if pd.api.types.is_datetime64_any_dtype(s):
            conv = s
        elif pd.api.types.is_numeric_dtype(s):
            conv = pd.to_datetime(s, unit="D", origin="1899-12-30", errors="coerce")  # Excel seri tarihi
        else:
            conv = pd.to_datetime(s.astype("string").str.strip(), dayfirst=True, errors="coerce", format="mixed")
        bad = int((conv.isna() & ~is_empty(s)).sum())
        out[col] = conv
    else:
        raise ShiftFlowError(f"Bilinmeyen hedef tip: {target}")
    r = OpResult(out)
    if bad:
        if p.get("strict", False):
            raise TypeMismatchError(
                f"'{col}' sütununda {_fmt_n(bad)} değer {TYPE_TARGETS[target].lower()} tipine çevrilemedi."
            )
        r.warnings.append(f"{_fmt_n(bad)} değer {TYPE_TARGETS[target].lower()} tipine çevrilemedi ve boş bırakıldı.")
    return r


def _text_keep_case(s):
    def f(v):
        if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
            return None
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        if isinstance(v, pd.Timestamp):
            return v.strftime("%d.%m.%Y")
        return str(v)
    return s.map(f).astype(object)


register(Operation("convert", "Tip dönüştür", _run_convert,
                   lambda p: f"Tip dönüştür: {p.get('column')} → {TYPE_TARGETS.get(p.get('to'), p.get('to'))}"))


def _run_dedupe(inputs, p, label):
    df = inputs[0]
    cols = p.get("columns") or None
    if cols:
        _need(df, cols, label)
    keep = p.get("keep", "first")
    dup = df.duplicated(subset=cols, keep=keep)
    out = df[~dup].reset_index(drop=True)
    r = OpResult(out)
    r.messages.append(f"{_fmt_n(int(dup.sum()))} tekrarlı satır kaldırıldı.")
    return r


register(Operation("dedupe", "Tekrarları kaldır", _run_dedupe,
                   lambda p: "Tekrarları kaldır: " + (", ".join(p["columns"]) if p.get("columns") else "tüm sütunlar")))


TEXT_CASES = {"none": "Değiştirme", "upper": "BÜYÜK HARF", "lower": "küçük harf", "title": "Baş Harfler Büyük"}


def _run_text_clean(inputs, p, label):
    df = inputs[0]
    cols = p.get("columns", [])
    if not cols:
        raise ShiftFlowError("Temizlenecek en az bir sütun seçin.")
    _need(df, cols, label)
    out = df.copy()
    case = p.get("case", "none")
    changed = 0
    for c in cols:
        s = out[c]

        def f(v):
            if not isinstance(v, str):
                return v
            x = v
            if p.get("trim", True):
                x = x.strip()
            if p.get("collapse_spaces", True):
                x = " ".join(x.split())
            if case == "upper":
                x = tr_upper(x)
            elif case == "lower":
                x = tr_lower(x)
            elif case == "title":
                x = tr_title(x)
            return x if x != "" else None
        new = s.map(f)
        changed += int((new.astype(object).fillna("\0") != s.astype(object).fillna("\0")).sum())
        out[c] = new
    r = OpResult(out)
    r.messages.append(f"{_fmt_n(changed)} hücre değişti.")
    return r


register(Operation("text_clean", "Metin temizle", _run_text_clean,
                   lambda p: "Metin temizle: " + ", ".join(p.get("columns", []))
                   + (f" ({TEXT_CASES.get(p.get('case'))})" if p.get("case", "none") != "none" else "")))


def _run_unify(inputs, p, label):
    from . import variants
    df = inputs[0]
    cols = p.get("columns", [])
    if not cols:
        raise ShiftFlowError("Yazımı birleştirilecek en az bir sütun seçin.")
    _need(df, cols, label)
    out = df.copy()
    r = OpResult(out)
    total = 0
    for c in cols:
        new, n = variants.unify(out[c])
        if n:
            out[c] = new
            total += n
            r.messages.append(f"{c}: {_fmt_n(n)} hücre en sık yazılışa çevrildi.")
    if not total:
        r.messages.append("Farklı yazılış bulunmadı; değişiklik yok.")
    r.df = out
    return r


register(Operation("unify", "Yazımı birleştir", _run_unify,
                   lambda p: "Yazımı birleştir (boşluk/harf): " + ", ".join(p.get("columns", []))))


def _run_excel_formula(inputs, p, label):
    """Excel'de hesaplanacak sütun: ShiftFlow karşılığı olmayan formül çıktıya Excel formülü olarak yazılır.

    Burada sütun boş kalır (veya kaynakta Excel'in hesapladığı değer varsa o korunur);
    sonraki adımlarda bu sütunun değeri kullanılamaz."""
    df = inputs[0]
    name = str(p.get("name") or "").strip()
    if not name:
        raise ShiftFlowError("Sütun için bir ad girin.")
    if not str(p.get("template") or "").startswith("="):
        raise ShiftFlowError("Excel formülü boş.")
    out = df.copy()
    r = OpResult(out)
    if name not in out.columns:
        out[name] = pd.Series([None] * len(out), index=out.index, dtype=object)
        r.messages.append(f"'{name}' değeri Excel çıktısında formülle hesaplanacak (burada boş görünür).")
    else:
        r.messages.append(f"'{name}' Excel çıktısına formül olarak yazılacak (burada kaynaktaki değer görünüyor).")
    r.df = out
    return r


register(Operation("excel_formula", "Excel'de hesaplanacak sütun", _run_excel_formula,
                   lambda p: f"Excel formülü: {p.get('name')} {p.get('template', '')}"))


# ---------------------------------------------------------------- 3.5: biçim dönüşümleri
def _blank_mask(s: pd.Series) -> pd.Series:
    return s.isna() | s.map(lambda v: isinstance(v, str) and not v.strip()).astype(bool)


def _run_drop_empty_rows(inputs, p, label):
    """Boş satırları kaldırır. 'ignore' sütunları (örn. Excel'de aşağı çekilmiş formül sonuçları) yok sayılır:
    geri kalan sütunların hepsi boşsa satır atılır."""
    df = inputs[0]
    ignore = set(p.get("ignore") or [])
    cols = [c for c in (p.get("columns") or list(df.columns)) if c in df.columns and c not in ignore]
    if not cols:
        raise ShiftFlowError("Kontrol edilecek en az bir sütun kalmalı.")
    empty = pd.concat([_blank_mask(df[c]) for c in cols], axis=1).all(axis=1)
    out = df[~empty.to_numpy()].reset_index(drop=True)
    r = OpResult(out)
    r.messages.append(f"{_fmt_n(int(empty.sum()))} boş satır kaldırıldı." if empty.any() else "Boş satır yok.")
    return r


register(Operation("drop_empty_rows", "Boş satırları kaldır", _run_drop_empty_rows,
                   lambda p: "Boş satırları kaldır" + (f" ({', '.join(p['ignore'])} yok sayılarak)"
                                                        if p.get("ignore") else "")))


# ---------------------------------------------------------------- doğrulama
CHECKS = {"not_empty": "Boş olmasın", "unique": "Tekrar etmesin", "min_rows": "En az satır sayısı",
          "range": "Değer aralığında olsun", "formula": "Formül her satırda doğru olsun"}


def _check_one(df, c, tables, params, label):
    """(geçti mi, açıklama) — c: {"check", "column", "value", "min", "max", "formula"}"""
    kind = c.get("check")
    col = c.get("column")
    if kind in ("not_empty", "unique", "range"):
        _need(df, [col], label)
    if kind == "not_empty":
        bad = _blank_mask(df[col])
        n = int(bad.sum())
        return n == 0, f"'{col}' boş olmasın: {_fmt_n(n)} boş satır" + _rows_hint(bad)
    if kind == "unique":
        s = df[col]
        dup = s.duplicated(keep=False) & ~_blank_mask(s)
        n = int(s[dup].nunique())
        ex = ", ".join(map(str, s[dup].drop_duplicates().head(3).tolist()))
        return n == 0, f"'{col}' tekrar etmesin: {_fmt_n(n)} değer birden çok kez geçiyor" + (f" (örn. {ex})" if n else "")
    if kind == "min_rows":
        try:
            want = int(float(str(c.get("value", "1")).replace(",", ".")))
        except ValueError as exc:
            raise ShiftFlowError("En az satır sayısı için bir sayı yazın.") from exc
        return len(df) >= want, f"En az {_fmt_n(want)} satır: {_fmt_n(len(df))} satır var"
    if kind == "range":
        x, _ = to_number(df[col])
        lo, hi = _bound(c.get("min"), params), _bound(c.get("max"), params)
        bad = pd.Series(False, index=df.index)
        if lo is not None:
            bad |= x < lo
        if hi is not None:
            bad |= x > hi
        n = int(bad.sum())
        rng = f"{'' if lo is None else _num_txt(lo)} – {'' if hi is None else _num_txt(hi)}"
        return n == 0, f"'{col}' {rng} aralığında: {_fmt_n(n)} satır dışında" + _rows_hint(bad)
    if kind == "formula":
        f = str(c.get("formula", "")).strip()
        if not f:
            raise ShiftFlowError("Doğrulama formülünü yazın (örn. [Toplanan] <= [Hedef] * 2).")
        v, _ = expression.evaluate(f, df, label, dict(tables, __params__=params) if params else tables)
        ok = v.fillna(False).astype(bool) if v.dtype == bool or v.dtype == object else v.fillna(0) != 0
        bad = ~ok
        n = int(bad.sum())
        return n == 0, f"{f}: {_fmt_n(n)} satırda sağlanmıyor" + _rows_hint(bad)
    raise ShiftFlowError(f"Bilinmeyen kontrol: {kind}")


def _bound(v, params):
    t = str(v if v is not None else "").strip()
    if not t:
        return None
    if t.startswith("{") and t.endswith("}"):
        key = next((k for k in (params or {}) if k.lower() == t[1:-1].strip().lower()), None)
        if key is None:
            raise ShiftFlowError(f"'{t}' parametresi tanımlı değil.")
        return float(params[key])
    n = _parse_number_text(t)
    if n is None:
        raise ShiftFlowError(f"Aralık sınırı sayı olmalı: '{t}'")
    return n


def _num_txt(x):
    return str(int(x)) if float(x).is_integer() else str(x).replace(".", ",")


def _validate_formulas(p) -> str:
    return " & ".join(f"({c.get('formula')})" for c in p.get("checks", []) if str(c.get("formula", "")).strip())


def _rows_hint(bad: pd.Series) -> str:
    idx = [i + 1 for i, b in enumerate(bad.tolist()) if b][:5]
    return f" (satır {', '.join(map(str, idx))}{'…' if int(bad.sum()) > 5 else ''})" if idx else ""


def _run_validate(inputs, p, label):
    """Veriyi değiştirmez; kurallar sağlanmazsa uyarır veya raporu durdurur (çıktı yazılmaz)."""
    df = inputs[0]
    checks = p.get("checks") or []
    if not checks:
        raise ShiftFlowError("En az bir kontrol ekleyin.")
    tables = _tables(inputs, dict(p, f=_validate_formulas(p)), ["f"])
    params = tables.pop("__params__", None)
    r = OpResult(df)
    stops = []
    for c in checks:
        ok, text = _check_one(df, c, tables, params, label)
        if ok:
            r.messages.append("✓ " + text)
        elif c.get("on_fail", "warn") == "stop":
            stops.append(text)
        else:
            r.warnings.append("Doğrulama: " + text)
    if stops and p.get("__strict__"):
        raise ShiftFlowError("Doğrulama başarısız; rapor durduruldu:\n• " + "\n• ".join(stops),
                             detail="Bu kontrolü 'Uyar' yaparsanız rapor uyarıyla oluşturulur.")
    for t in stops:  # düzenleme sırasında uyarı; Rapor oluştur / Excel'e aktar çıktıyı durdurur
        r.warnings.append("⛔ Doğrulama (rapor oluştururken durdurur): " + t)
    return r


register(Operation("validate", "Doğrula", _run_validate,
                   lambda p: "Doğrula: " + "; ".join(
                       f"{CHECKS.get(c.get('check'), c.get('check'))}"
                       + (f" ({c.get('column')})" if c.get("column") and c.get("check") != "formula" else "")
                       + (f" ({c.get('formula')})" if c.get("check") == "formula" else "")
                       + (" ⛔" if c.get("on_fail") == "stop" else "")
                       for c in p.get("checks", [])),
                   refs=lambda p: _formula_refs({"f": _validate_formulas(p)}, ["f"]),
                   uses_params=True))


def _run_fill_down(inputs, p, label):
    """Birleştirilmiş hücreler / gruplu raporlar: boş hücreye üstteki dolu değer yazılır."""
    df = inputs[0]
    cols = p.get("columns", [])
    if not cols:
        raise ShiftFlowError("Aşağı doldurulacak en az bir sütun seçin.")
    _need(df, cols, label)
    out = df.copy()
    r = OpResult(out)
    direction = p.get("direction", "down")
    for c in cols:
        s = out[c].astype(object).where(~_blank_mask(out[c]), None)
        filled = s.ffill() if direction == "down" else s.bfill()
        n = int((s.isna() & filled.notna()).sum())
        out[c] = filled.infer_objects() if pd.api.types.is_numeric_dtype(df[c]) else filled
        if n:
            r.messages.append(f"{c}: {_fmt_n(n)} boş hücre {'üstteki' if direction == 'down' else 'alttaki'} "
                              "değerle dolduruldu.")
    if not r.messages:
        r.messages.append("Doldurulacak boş hücre yok.")
    r.df = out
    return r


register(Operation("fill_down", "Aşağı doldur", _run_fill_down,
                   lambda p: ("Aşağı doldur: " if p.get("direction", "down") == "down" else "Yukarı doldur: ")
                   + ", ".join(p.get("columns", []))))


def _run_fill_empty(inputs, p, label):
    df = inputs[0]
    cols = p.get("columns", [])
    if not cols:
        raise ShiftFlowError("Boşları doldurulacak en az bir sütun seçin.")
    _need(df, cols, label)
    raw = p.get("value", "")
    out = df.copy()
    r = OpResult(out)
    for c in cols:
        m = _blank_mask(out[c])
        n = int(m.sum())
        if not n:
            continue
        if pd.api.types.is_numeric_dtype(out[c]) and not pd.api.types.is_bool_dtype(out[c]):
            v = _parse_number_text(str(raw)) if not isinstance(raw, (int, float)) else raw
            if v is None:
                raise TypeMismatchError(f"'{c}' sayı sütunu; '{raw}' sayı değil. Sayı yazın (örn. 0).")
            out[c] = out[c].astype(float).where(~m, float(v))
            if (out[c].dropna() % 1 == 0).all():
                out[c] = out[c].astype("Int64") if out[c].isna().any() else out[c].astype("int64")
        else:
            out[c] = out[c].astype(object).where(~m, raw)
        r.messages.append(f"{c}: {_fmt_n(n)} boş hücreye '{raw}' yazıldı.")
    if not r.messages:
        r.messages.append("Boş hücre yok.")
    r.df = out
    return r


register(Operation("fill_empty", "Boşları doldur", _run_fill_empty,
                   lambda p: f"Boşları doldur ({p.get('value', '')!r}): " + ", ".join(p.get("columns", []))))


def _run_split(inputs, p, label):
    """Metni sütunlara böl: 'A-01-03' → Bölge / Koridor / Raf. Ayırıcıya veya sabit konumlara göre."""
    from .values import infer_types
    df = inputs[0]
    col = p.get("column")
    _need(df, [col], label)
    mode = p.get("mode", "delimiter")
    blank = _blank_mask(df[col]).tolist()
    text = [None if b else str(v) for v, b in zip(df[col].tolist(), blank)]  # düz liste: pandas tip çevirmesin
    if mode == "delimiter":
        sep = p.get("delimiter", "-")
        if sep == "":
            raise ShiftFlowError("Ayırıcıyı yazın (örn. - veya boşluk için 'boşluk' seçin).")
        sep = {"\\t": "\t", "boşluk": " "}.get(sep, sep)
        maxn = int(p.get("max_parts") or 0)
        parts = [None if v is None else (v.split(sep, maxn - 1) if maxn > 0 else v.split(sep)) for v in text]
    else:
        try:
            widths = [int(x) for x in str(p.get("positions", "")).replace(";", ",").split(",") if x.strip()]
        except ValueError:
            widths = []
        if not widths or any(w <= 0 for w in widths):
            raise ShiftFlowError("Konumları karakter sayısı olarak yazın, örn. 1,2,2 (ilk 1, sonra 2, sonra 2 karakter).")

        def cut(v):
            if v is None:
                return None
            out, i = [], 0
            for w in widths:
                out.append(v[i:i + w])
                i += w
            if i < len(v) and p.get("rest_to_last", True):
                out[-1] = out[-1] + v[i:]
            while out and out[-1] == "":
                out.pop()  # kısa metin: eksik parçalar boş kalır
            return out
        parts = [cut(v) for v in text]
    n = max((len(x) for x in parts if x is not None), default=0)
    if n == 0:
        raise ShiftFlowError(f"'{col}' sütununda bölünecek değer yok.")
    names = [x.strip() for x in (p.get("names") or []) if str(x).strip()]
    names = (names + [f"{col} {i + 1}" for i in range(len(names), n)])[:n]
    clash = [x for x in names if x in df.columns and (p.get("keep", True) or x != col)]
    if clash:
        raise ShiftFlowError("Bu adlarla sütun zaten var: " + ", ".join(clash) + ". Farklı ad yazın.")
    pos = list(df.columns).index(col)
    out = df.copy()
    if not p.get("keep", True):
        out = out.drop(columns=[col])
    else:
        pos += 1
    trim = p.get("trim", True)
    new = pd.DataFrame({nm: pd.Series([(v[i].strip() if trim else v[i]) if v is not None and i < len(v) else None
                                       for v in parts], index=df.index, dtype=object)
                        for i, nm in enumerate(names)}, index=df.index)
    if p.get("detect_types", True):
        new = infer_types(new)
    for i, nm in enumerate(names):
        out.insert(min(pos + i, out.shape[1]), nm, new[nm])
    r = OpResult(out)
    short = sum(1 for v in parts if v is not None and len(v) < n)
    r.messages.append(f"{col} → {', '.join(names)}")
    if short:
        r.warnings.append(f"{_fmt_n(short)} satırda parça sayısı az; eksik parçalar boş bırakıldı.")
    return r


register(Operation("split", "Sütunlara böl", _run_split,
                   lambda p: f"Sütunlara böl: {p.get('column')} "
                   + (f"('{p.get('delimiter', '-')}' ile)" if p.get("mode", "delimiter") == "delimiter"
                      else f"(konum {p.get('positions')})")))


def _run_unpivot(inputs, p, label):
    """Yan yana sütunları satırlara çevirir (Excel'deki 'sütunları özet dışı bırak').

    Örn. Personel | Gece | Gündüz | Akşam  →  Personel | Vardiya | Adet"""
    df = inputs[0]
    vals = p.get("columns", [])
    if not vals:
        raise ShiftFlowError("Satırlara çevrilecek en az bir sütun seçin.")
    _need(df, vals, label)
    keep = [c for c in df.columns if c not in vals]
    attr = (p.get("name_column") or "Öznitelik").strip()
    valc = (p.get("value_column") or "Değer").strip()
    if attr == valc or attr in keep or valc in keep:
        raise ShiftFlowError(f"Yeni sütun adları ('{attr}', '{valc}') birbirinden ve mevcut sütunlardan farklı olmalı.")
    out = df.melt(id_vars=keep, value_vars=vals, var_name=attr, value_name=valc)
    if p.get("drop_empty", True):
        out = out[~_blank_mask(out[valc])]
    out = out.reset_index(drop=True)
    r = OpResult(out)
    r.messages.append(f"{len(vals)} sütun satıra çevrildi: {_fmt_n(len(df))} → {_fmt_n(len(out))} satır.")
    return r


register(Operation("unpivot", "Sütunları satırlara çevir", _run_unpivot,
                   lambda p: f"Satırlara çevir: {', '.join(p.get('columns', []))} → "
                   f"{p.get('name_column') or 'Öznitelik'} / {p.get('value_column') or 'Değer'}"))


def _run_replace(inputs, p, label):
    df = inputs[0]
    col = p.get("column")
    _need(df, [col], label)
    find, repl = str(p.get("find", "")), p.get("replace", "")
    if find == "":
        raise ShiftFlowError("Aranacak değeri girin.")
    out = df.copy()
    s = out[col]
    if p.get("whole_cell", False):
        key = _text(s)
        m = key == tr_lower(find)
        num = _parse_number_text(str(repl)) if pd.api.types.is_numeric_dtype(s) else None
        out[col] = s.astype(object).where(~m, num if num is not None else repl)
        n = int(m.sum())
    else:
        txt = _text_keep_case(s)
        m = txt.fillna("").str.contains(find, regex=False)
        n = int(m.sum())
        out[col] = txt.where(~m, txt.str.replace(find, str(repl), regex=False)).where(txt.notna(), s)
        if n and pd.api.types.is_numeric_dtype(s):
            conv, bad = to_number(out[col])
            if bad == 0:
                out[col] = conv
    r = OpResult(out)
    r.messages.append(f"{_fmt_n(n)} hücrede değişiklik yapıldı.")
    if n == 0:
        r.warnings.append(f"'{find}' değeri '{col}' sütununda bulunamadı.")
    return r


register(Operation("replace", "Bul ve değiştir", _run_replace,
                   lambda p: f"Bul/değiştir: {p.get('column')}: '{p.get('find')}' → '{p.get('replace')}'"))


# ---------------------------------------------------------------- birleştirme

JOIN_TYPES = {
    "left": "Sol birleştirme (soldaki tüm satırlar)",
    "inner": "İç birleştirme (yalnız eşleşenler)",
    "outer": "Tam birleştirme (her iki taraftaki tüm satırlar)",
}
MATCH_COL = "Eşleşme Durumu"


def _key_frame(df, keys, side):
    k = pd.DataFrame(index=df.index)
    empty = pd.Series(False, index=df.index)
    for i, c in enumerate(keys):
        nk = normalize_key(df[c])
        empty |= nk.isna()
        k[f"__k{i}"] = nk
    # Boş anahtarlar hiçbir satırla eşleşmesin diye benzersiz değer verilir.
    for i in range(len(keys)):
        col = k[f"__k{i}"]
        k[f"__k{i}"] = col.where(~empty, [f"\x00{side}{j}" for j in range(len(df))])
    return k, int(empty.sum())


def join_diagnostics(left: pd.DataFrame, right: pd.DataFrame, p: dict, label: str = "") -> dict:
    lk, rk = p.get("left_keys", []), p.get("right_keys", [])
    if not lk or len(lk) != len(rk):
        raise ShiftFlowError("Her iki taraf için aynı sayıda anahtar sütun seçin.")
    _need(left, lk, label + " / sol")
    _need(right, rk, label + " / sağ")
    lkf, l_empty = _key_frame(left, lk, "L")
    rkf, r_empty = _key_frame(right, rk, "R")
    kcols = list(lkf.columns)
    l_tuple = lkf.apply(tuple, axis=1) if len(kcols) > 1 else lkf[kcols[0]]
    r_tuple = rkf.apply(tuple, axis=1) if len(kcols) > 1 else rkf[kcols[0]]
    l_dup = int(l_tuple.duplicated(keep=False).sum())
    r_dup = int(r_tuple.duplicated(keep=False).sum())
    r_set, l_set = set(r_tuple), set(l_tuple)
    l_matched = int(l_tuple.isin(r_set).sum())
    r_matched = int(r_tuple.isin(l_set).sum())
    # Çoktan-çoğa: her iki tarafta tekrar eden ve birbiriyle eşleşen anahtar var mı?
    l_counts, r_counts = l_tuple.value_counts(), r_tuple.value_counts()
    common = l_counts.index.intersection(r_counts.index)
    mm_keys = [k for k in common if l_counts[k] > 1 and r_counts[k] > 1]
    pair_rows = int((l_counts[common] * r_counts[common]).sum()) if len(common) else 0
    how = p.get("how", "left")
    l_un, r_un = len(left) - l_matched, len(right) - r_matched
    expected = pair_rows + (l_un if how in ("left", "outer") else 0) + (r_un if how == "outer" else 0)
    if l_dup == 0 and r_dup == 0:
        rel = "Bire-bir"
    elif l_dup == 0:
        rel = "Bire-çok (sağ tarafta tekrar eden anahtarlar var)"
    elif r_dup == 0:
        rel = "Çoka-bir (sol tarafta tekrar eden anahtarlar var)"
    else:
        rel = "Çoktan-çoğa" if mm_keys else "Her iki tarafta tekrar var (birbiriyle eşleşmiyor)"
    examples_l = [x for x in left[lk[0]].dropna().astype(str).head(3)]
    examples_r = [x for x in right[rk[0]].dropna().astype(str).head(3)]
    return {
        "left_rows": len(left), "right_rows": len(right),
        "left_matched": l_matched, "right_matched": r_matched,
        "left_unmatched": l_un, "right_unmatched": r_un,
        "left_dup_rows": l_dup, "right_dup_rows": r_dup,
        "left_empty_keys": l_empty, "right_empty_keys": r_empty,
        "many_to_many_keys": len(mm_keys), "relationship": rel,
        "expected_rows": expected, "how": how,
        "examples_left": examples_l, "examples_right": examples_r,
    }


def diagnostics_text(d: dict) -> list[str]:
    lines = [
        f"İlişki türü: {d['relationship']}",
        f"Sol: {_fmt_n(d['left_rows'])} satır, eşleşen {_fmt_n(d['left_matched'])}, eşleşmeyen {_fmt_n(d['left_unmatched'])}",
        f"Sağ: {_fmt_n(d['right_rows'])} satır, eşleşen {_fmt_n(d['right_matched'])}, eşleşmeyen {_fmt_n(d['right_unmatched'])}",
        f"Birleştirme sonrası beklenen satır: {_fmt_n(d['expected_rows'])}",
    ]
    if d["left_dup_rows"]:
        lines.append(f"Solda tekrar eden anahtara sahip satır: {_fmt_n(d['left_dup_rows'])}")
    if d["right_dup_rows"]:
        lines.append(f"Sağda tekrar eden anahtara sahip satır: {_fmt_n(d['right_dup_rows'])}")
    if d["left_empty_keys"] or d["right_empty_keys"]:
        lines.append(f"Anahtarı boş satır: sol {_fmt_n(d['left_empty_keys'])}, sağ {_fmt_n(d['right_empty_keys'])} (bunlar eşleşmez)")
    return lines


def _run_join(inputs, p, label):
    left, right = inputs[0], inputs[1]
    d = join_diagnostics(left, right, p, label)
    if d["many_to_many_keys"] and not p.get("allow_many_to_many", False):
        raise JoinConfirmationRequired(
            f"Çoktan-çoğa eşleşme var: {_fmt_n(d['many_to_many_keys'])} anahtar her iki tabloda da tekrar ediyor. "
            f"Satır sayısı {_fmt_n(d['left_rows'])} yerine {_fmt_n(d['expected_rows'])} olacak. "
            "Bu genellikle yanlış anahtar seçiminden kaynaklanır.",
            d,
        )
    lk, rk = p["left_keys"], p["right_keys"]
    how = p.get("how", "left")
    rname = p.get("right_label") or "sağ"
    suffix = f" ({rname})"
    lkf, _ = _key_frame(left, lk, "L")
    rkf, _ = _key_frame(right, rk, "R")
    L = pd.concat([left.reset_index(drop=True), lkf.reset_index(drop=True)], axis=1)
    R = right.reset_index(drop=True).copy()
    same = [(a, b) for a, b in zip(lk, rk) if a == b]
    for i, (a, _b) in enumerate(same):
        R = R.rename(columns={a: f"__rk{i}"})
    R = pd.concat([R, rkf.reset_index(drop=True)], axis=1)
    kcols = list(lkf.columns)
    merged = pd.merge(L, R, on=kcols, how=how, suffixes=("", suffix), indicator="__ind", sort=False)
    for i, (a, _b) in enumerate(same):
        merged[a] = merged[a].where(merged["__ind"] != "right_only", merged[f"__rk{i}"])
        merged = merged.drop(columns=[f"__rk{i}"])
    ind = merged.pop("__ind")
    merged = merged.drop(columns=kcols)
    if p.get("add_match_column", False):
        merged[MATCH_COL] = ind.map({"both": "Eşleşti", "left_only": "Yalnız solda", "right_only": "Yalnız sağda"}).astype(object)
    r = OpResult(merged.reset_index(drop=True), stats={"join": d})
    r.messages.extend(diagnostics_text(d))
    r.messages.append(f"Sonuç: {_fmt_n(len(merged))} satır")
    collided = [c for c in right.columns if c in left.columns and c not in rk]
    if collided:
        r.messages.append(f"Aynı isimli sütunlar sağ taraf için '{suffix.strip()}' ekiyle adlandırıldı: {', '.join(collided)}")
    if d["left_matched"] == 0:
        r.warnings.append(
            "Hiç eşleşme bulunamadı. Anahtar sütunların doğru seçildiğini ve değer biçimlerinin "
            f"aynı olduğunu kontrol edin (sol örnek: {', '.join(d['examples_left'])}; "
            f"sağ örnek: {', '.join(d['examples_right'])})."
        )
    if how == "left" and len(merged) > len(left):
        r.warnings.append(
            f"Sağ tabloda tekrar eden anahtarlar nedeniyle satır sayısı {_fmt_n(len(left))} → {_fmt_n(len(merged))} arttı."
        )
    if d["many_to_many_keys"]:
        r.warnings.append("Çoktan-çoğa eşleşme kullanıcı onayıyla uygulandı.")
    return r


register(Operation(
    "join", "Birleştir", _run_join,
    lambda p: f"Birleştir ({JOIN_TYPES.get(p.get('how'), p.get('how')).split(' (')[0]}): "
              + ", ".join(f"{a} = {b}" for a, b in zip(p.get("left_keys", []), p.get("right_keys", []))),
    inputs="2", new_dataset=True,
))


def _run_append(inputs, p, label):
    if len(inputs) < 2:
        raise ShiftFlowError("Alt alta eklemek için en az iki veri kümesi seçin.")
    labels = p.get("labels") or [f"Kaynak {i + 1}" for i in range(len(inputs))]
    frames = []
    for df, lab in zip(inputs, labels):
        f = df.copy()
        if p.get("source_column"):
            f[p["source_column"]] = lab
        frames.append(f)
    out = pd.concat(frames, ignore_index=True, sort=False)
    r = OpResult(out)
    all_cols = set(out.columns)
    for df, lab in zip(inputs, labels):
        missing = [c for c in out.columns if c not in df.columns and c != p.get("source_column")]
        if missing:
            r.warnings.append(f"{lab} içinde olmayan sütunlar boş bırakıldı: {', '.join(missing[:10])}")
    r.messages.append(" + ".join(_fmt_n(len(x)) for x in inputs) + f" = {_fmt_n(len(out))} satır")
    del all_cols
    return r


register(Operation("append", "Alt alta ekle", _run_append,
                   lambda p: "Alt alta ekle: " + " + ".join(p.get("labels") or []),
                   inputs="n", new_dataset=True))


# ---------------------------------------------------------------- gruplama / pivot

AGG_FUNCS = {"sum": "Toplam", "count": "Adet", "mean": "Ortalama", "min": "Min", "max": "Maks", "nunique": "Benzersiz adet"}
TOTAL_LABEL = "Genel Toplam"


DATE_GROUPS = {"none": "Gruplama yok", "hour": "Saat", "day": "Gün", "week": "Hafta", "month": "Ay",
               "weekday": "Haftanın günü", "year": "Yıl"}
_WEEKDAYS = ["1 Pzt", "2 Sal", "3 Çar", "4 Per", "5 Cum", "6 Cmt", "7 Paz"]


def _date_group(s: pd.Series, how: str) -> pd.Series:
    """Tarih/saat sütununu Excel pivotundaki gibi gruplar (metin etiketler, doğal sırada)."""
    d = s if pd.api.types.is_datetime64_any_dtype(s) else pd.to_datetime(s, errors="coerce", dayfirst=True)
    if how == "hour":
        out = d.dt.hour.map(lambda h: None if pd.isna(h) else f"{int(h):02d}:00")
    elif how == "day":
        out = d.dt.normalize()
        return out
    elif how == "week":
        iso = d.dt.isocalendar()
        out = pd.Series([None if pd.isna(y) else f"{int(y)}-H{int(w):02d}" for y, w in zip(iso.year, iso.week)],
                        index=s.index, dtype=object)
    elif how == "month":
        out = d.map(lambda x: None if pd.isna(x) else f"{x.year}-{x.month:02d}")
    elif how == "weekday":
        out = d.dt.weekday.map(lambda w: None if pd.isna(w) else _WEEKDAYS[int(w)])
    elif how == "year":
        out = d.dt.year.map(lambda y: None if pd.isna(y) else int(y))
    else:
        return s
    return out.astype(object)


def _apply_date_groups(df, fields, how):
    if not how or how == "none":
        return df, []
    out, done = df.copy(), []
    for c in fields:
        s = df[c]
        is_date = pd.api.types.is_datetime64_any_dtype(s)
        if not is_date and not pd.api.types.is_numeric_dtype(s):
            sample = s.dropna().astype(str).head(50)
            is_date = len(sample) > 0 and pd.to_datetime(sample, errors="coerce", dayfirst=True,
                                                         format="mixed").notna().mean() >= 0.9
        if is_date:
            out[c] = _date_group(s, how)
            done.append(c)
    return out, done


def _prep_group(df, by, values, label, date_group=None):
    _need(df, by + [v["column"] for v in values], label)
    work, _ = _apply_date_groups(df, by, date_group)
    work = work.copy()
    empty_groups = 0
    for c in by:
        e = is_empty(work[c])
        empty_groups += int(e.sum())
        work[c] = work[c].astype(object).where(~e, EMPTY_LABEL)
    for v in values:
        if v["func"] in ("sum", "mean", "min", "max"):
            col = work[v["column"]]
            if pd.api.types.is_datetime64_any_dtype(col) and v["func"] in ("min", "max"):
                continue
            if not pd.api.types.is_numeric_dtype(col) or pd.api.types.is_bool_dtype(col):
                conv, bad = to_number(col)
                if bad:
                    raise TypeMismatchError(
                        f"'{v['column']}' sütununda sayı olmayan {_fmt_n(bad)} değer var; "
                        f"{AGG_FUNCS[v['func']].lower()} hesaplanamaz. 'Adet' seçin veya önce tip dönüştürün."
                    )
                work[v["column"]] = conv
    return work, empty_groups


def _value_name(v):
    return v.get("name") or f"{v['column']} ({AGG_FUNCS.get(v['func'], v['func'])})"


def _run_group(inputs, p, label):
    df = inputs[0]
    by, values = p.get("by", []), p.get("values", [])
    if not by:
        raise ShiftFlowError("Gruplama için en az bir sütun seçin.")
    if not values:
        raise ShiftFlowError("En az bir hesaplama (toplam, adet...) ekleyin.")
    work, empty_groups = _prep_group(df, by, values, label, p.get("date_group"))
    named = {}
    for v in values:
        name = _value_name(v)
        if name in named or name in by:
            raise ShiftFlowError(f"Aynı hesaplama iki kez eklenmiş: {name}")
        named[name] = pd.NamedAgg(column=v["column"], aggfunc=v["func"])
    out = work.groupby(by, sort=True, dropna=False).agg(**named).reset_index()
    r = OpResult(out)
    r.messages.append(f"{_fmt_n(len(df))} satır {_fmt_n(len(out))} gruba indirildi.")
    out = _sort_top(out, [c for c in out.columns if c not in by][:1], p, r, None)
    r.df = out
    if empty_groups:
        r.warnings.append(f"Gruplama alanı boş olan {_fmt_n(empty_groups)} hücre '{EMPTY_LABEL}' grubunda toplandı.")
    return r


register(Operation(
    "group", "Grupla", _run_group,
    lambda p: f"Grupla: {', '.join(p.get('by', []))} → " + ", ".join(_value_name(v) for v in p.get("values", [])),
    new_dataset=True,
))


def _hdr(x) -> str:
    """Pivot sütun başlığı: tarihler Türkçe biçimde (10.11.2026)."""
    if isinstance(x, pd.Timestamp):
        return x.strftime("%d.%m.%Y") if not (x.hour or x.minute) else x.strftime("%d.%m.%Y %H:%M")
    return str(x)


def _run_pivot(inputs, p, label):
    df = inputs[0]
    rows, cols, values = p.get("rows", []), p.get("columns", []), p.get("values", [])
    if not rows and not cols:
        raise ShiftFlowError("Pivot için en az bir satır veya sütun alanı seçin.")
    if not values:
        raise ShiftFlowError("Pivot için en az bir değer alanı ekleyin.")
    overlap = set(rows) & set(cols)
    if overlap:
        raise ShiftFlowError(f"Aynı alan hem satıra hem sütuna konamaz: {', '.join(overlap)}")
    work, empty_groups = _prep_group(df, rows + cols, values, label, p.get("date_group"))
    totals = p.get("totals", True)
    pieces = []
    for v in values:
        vname = _value_name(v)
        pt = pd.pivot_table(
            work, index=rows or None, columns=cols or None, values=v["column"], aggfunc=v["func"],
            margins=totals and bool(rows) and bool(cols) or (totals and bool(rows) and not cols),
            margins_name=TOTAL_LABEL, observed=True, dropna=False, sort=True,
        )
        if isinstance(pt, pd.Series):
            pt = pt.to_frame(vname)
        elif not cols:
            pt.columns = [vname]
        else:
            # Tek değer alanında Excel gibi yalnız sütun değerleri başlık olur.
            prefix = [] if len(values) == 1 else [vname]
            names = [" | ".join(prefix + [_hdr(x) for x in (c if isinstance(c, tuple) else (c,))]) for c in pt.columns]
            if set(names) & set(rows):
                names = [" | ".join([vname] + [_hdr(x) for x in (c if isinstance(c, tuple) else (c,))])
                         for c in pt.columns]
            pt.columns = names
        pieces.append(pt)
    out = pd.concat(pieces, axis=1)
    # dropna=False tüm alan birleşimlerini üretir; Excel gibi yalnızca veride
    # gerçekten bulunan birleşimler kalsın.
    out = out.loc[~out.isna().all(axis=1), ~out.isna().all(axis=0)]
    if rows:
        out = out.reset_index()
    else:
        out = out.reset_index(drop=True)
    # Pivot hücrelerinde değer yoksa adet = 0, diğerleri boş kalır.
    for v in values:
        if v["func"] in ("count", "nunique"):
            for c in out.columns:
                if c in rows:
                    continue
                if len(values) == 1 or c == _value_name(v) or str(c).startswith(_value_name(v) + " | "):
                    out[c] = out[c].fillna(0).astype("int64")
    r = OpResult(out)
    value_cols = [c for c in out.columns if c not in rows]
    if p.get("show_as", "value") != "value":
        out = _show_as(out, rows, value_cols, p["show_as"], r)
    key = [TOTAL_LABEL] if TOTAL_LABEL in value_cols else value_cols
    out = _sort_top(out, key, p, r, rows[0] if rows else None,
                    recompute=all(v["func"] in ("sum", "count") for v in values) and p.get("show_as", "value") == "value")
    r.df = out
    r.messages.append(f"Pivot: {_fmt_n(len(out))} satır × {_fmt_n(out.shape[1])} sütun")
    if empty_groups:
        r.warnings.append(f"Alanı boş olan {_fmt_n(empty_groups)} hücre '{EMPTY_LABEL}' olarak gruplandı.")
    if out.shape[1] > 200:
        r.warnings.append("Pivot çok fazla sütun üretti; sütun alanında çok sayıda farklı değer olabilir.")
    return r


SHOW_AS = {"value": "Değer", "pct_total": "Genel toplamın %'si", "pct_row": "Satır toplamının %'si",
           "pct_col": "Sütun toplamının %'si"}


def _show_as(out, rows, value_cols, how, r):
    """Pivot değerlerini yüzdeye çevirir (Excel'deki 'Değerleri farklı göster')."""
    out = out.copy()
    first = rows[0] if rows else None
    is_total_row = (out[first].astype(str) == TOTAL_LABEL) if first else pd.Series(False, index=out.index)
    data_cols = [c for c in value_cols if c != TOTAL_LABEL]
    vals = out[value_cols].apply(pd.to_numeric, errors="coerce").astype(float)
    body = vals.loc[~is_total_row, data_cols]
    if how == "pct_total":
        denom = body.sum().sum()
        res = vals / denom * 100 if denom else vals * float("nan")
    elif how == "pct_row":
        rs = body.sum(axis=1).reindex(vals.index)
        if is_total_row.any():
            rs[is_total_row] = vals.loc[is_total_row, data_cols].sum(axis=1)
        res = vals.div(rs.replace(0, float("nan")), axis=0) * 100
    else:  # pct_col
        cs = body.sum()
        if TOTAL_LABEL in value_cols:
            cs[TOTAL_LABEL] = body.sum(axis=1).sum()
        res = vals.div(cs.replace(0, float("nan")), axis=1) * 100
    out[value_cols] = res.round(1)
    r.messages.append(f"Değerler: {SHOW_AS[how]} (yüzde, 1 ondalık).")
    return out


def _sort_top(out, key_cols, p, r, first_row_field, recompute=False):
    """Değere göre büyükten küçüğe sırala ve/veya ilk N satırı tut; Genel Toplam en altta kalır."""
    n = int(p.get("top_n") or 0)
    if not p.get("sort_by_value") and not n:
        return out
    if not key_cols:
        return out
    is_total = (out[first_row_field].astype(str) == TOTAL_LABEL) if first_row_field else \
        pd.Series(False, index=out.index)
    body, total = out[~is_total], out[is_total]
    score = body[key_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    body = body.loc[score.sort_values(ascending=False, kind="stable").index]
    if n and len(body) > n:
        r.messages.append(f"İlk {n} satır gösteriliyor ({_fmt_n(len(body))} satırdan).")
        body = body.head(n)
        if len(total):
            if recompute:
                total = total.copy()
                for c in out.columns:
                    if c != first_row_field and pd.api.types.is_numeric_dtype(out[c]):
                        total[c] = body[c].sum()
                r.messages.append("Genel Toplam yalnız gösterilen satırların toplamı.")
            else:
                total = total.iloc[0:0]
                r.warnings.append("İlk N seçiliyken bu hesaplamada Genel Toplam satırı gösterilmez.")
    return pd.concat([body, total]).reset_index(drop=True)


register(Operation(
    "pivot", "Pivot", _run_pivot,
    lambda p: "Pivot: satır [" + ", ".join(p.get("rows", [])) + "], sütun [" + ", ".join(p.get("columns", []))
              + "], değer [" + ", ".join(_value_name(v) for v in p.get("values", [])) + "]",
    new_dataset=True,
))


# ---------------------------------------------------------------- DÜŞEYARA (arama)
def _run_lookup(inputs, p, label):
    """Excel'deki DÜŞEYARA/ÇAPRAZARA gibi: satır sayısı DEĞİŞMEZ.

    params:
      table   : arama tablosunun veri kümesi adı (referans tablo, personel listesi…)
      keys    : [[bu tablodaki sütun, arama tablosundaki sütun], ...]
      columns : [{"column": getirilecek sütun, "as": yeni ad}]
      if_missing : bulunamazsa yazılacak değer (boş bırakılabilir)
      on_duplicate : "first" (ilkini al, uyar) | "error" (durdur)
    """
    df, table = inputs[0], inputs[1]
    keys = p.get("keys") or []
    cols = p.get("columns") or []
    if not keys:
        raise ShiftFlowError("Eşleştirme için anahtar sütun seçin.")
    if not cols:
        raise ShiftFlowError("Arama tablosundan getirilecek en az bir sütun seçin.")
    _need(df, [k[0] for k in keys], label)
    _need(table, [k[1] for k in keys] + [c["column"] for c in cols], label + f" / {p.get('table')}")
    out_names = [c.get("as") or c["column"] for c in cols]
    for n in out_names:
        if n in df.columns and not p.get("replace", False):
            raise ShiftFlowError(f"'{n}' adlı sütun zaten var. Farklı bir ad verin veya 'üzerine yaz'ı seçin.")
    def nk(series):  # Excel'deki DÜŞEYARA gibi büyük/küçük harf duyarsız, boşluklar kırpılmış
        return normalize_key(series).map(lambda k: tr_lower(k) if isinstance(k, str) else k)
    lk = pd.Series(list(zip(*[nk(df[a]) for a, _ in keys])), index=df.index) if len(keys) > 1 \
        else nk(df[keys[0][0]])
    rk = pd.Series(list(zip(*[nk(table[b]) for _, b in keys])), index=table.index) if len(keys) > 1 \
        else nk(table[keys[0][1]])
    r = OpResult(df.copy())
    empty_r = rk.map(lambda k: k is None or (isinstance(k, tuple) and any(x is None for x in k))).astype(bool)
    rk2, tab = rk[~empty_r], table[~empty_r]
    dup = rk2.duplicated(keep=False)
    if dup.any():
        n_keys = rk2[dup].nunique()
        examples = ", ".join(map(str, list(dict.fromkeys(rk2[dup]))[:3]))
        if p.get("on_duplicate", "first") == "error":
            raise ShiftFlowError(f"Arama tablosunda {n_keys} anahtar birden çok kez geçiyor (örn. {examples}). "
                                 "Hangi satırın kullanılacağı belirsiz.")
        r.warnings.append(f"Arama tablosunda {n_keys} anahtar birden çok kez geçiyor (örn. {examples}); "
                          "Excel'deki gibi ilk bulunan kullanıldı.")
    first = (~rk2.duplicated(keep="first")).astype(bool)
    pos_map = {k: i for i, k in enumerate(rk2[first])}
    pos = np.array([pos_map.get(k, -1) if k is not None else -1 for k in lk], dtype=int)
    found = pos >= 0
    missing_val = p.get("if_missing", "")
    for c, name in zip(cols, out_names):
        vals = tab.loc[first, c["column"]].to_numpy()
        res = pd.Series([vals[i] if i >= 0 else None for i in pos], index=df.index, dtype=object)
        if missing_val not in ("", None):
            num = _parse_number_text(str(missing_val))
            res = res.where(found, num if num is not None and pd.api.types.is_numeric_dtype(tab[c["column"]]) else missing_val)
        if pd.api.types.is_numeric_dtype(tab[c["column"]]) and missing_val in ("", None):
            res = pd.to_numeric(res, errors="coerce")
        elif pd.api.types.is_datetime64_any_dtype(tab[c["column"]]):
            res = pd.to_datetime(res, errors="coerce")
        r.df[name] = res.to_numpy()
    n_miss = int((~found).sum())
    r.messages.append(f"{_fmt_n(int(found.sum()))} satır eşleşti, {_fmt_n(n_miss)} satır bulunamadı.")
    if n_miss:
        orig = df.loc[~found, keys[0][0]].dropna().astype(str).str.strip()
        ex = ", ".join(list(dict.fromkeys(orig))[:5])
        r.warnings.append(f"{_fmt_n(n_miss)} satırın karşılığı arama tablosunda yok" + (f" (örn. {ex})" if ex else "") + ".")
    if n_miss == len(df) and len(df):
        r.warnings.append("Hiçbir satır eşleşmedi; anahtar sütunları ve değer biçimlerini kontrol edin.")
    return r


register(Operation(
    "lookup", "Eşleştir (DÜŞEYARA)", _run_lookup,
    lambda p: f"Eşleştir: {', '.join(a for a, _ in p.get('keys', []))} → {p.get('table')} "
              f"[{', '.join(c.get('as') or c['column'] for c in p.get('columns', []))}]",
    refs=lambda p: [p["table"]] if p.get("table") else [],
))


# ---------------------------------------------------------------- kural tablosu
def _run_rules(inputs, p, label):
    """Sırayla denenen kurallar: ilk uyan kuralın değeri yazılır.

    params: name, rules: [{conditions, mode, value, label?}], default, replace
    """
    df = inputs[0]
    name = _check_new_name(df, p.get("name"), p.get("replace", False))
    rules = p.get("rules") or []
    if not rules:
        raise ShiftFlowError("En az bir kural ekleyin.")
    tables, notes = _tables(inputs, p, ["default", "rules"]), []
    result, _ = _branch_value(p.get("default", ""), df, label, tables, notes)
    result = result.astype(object)
    assigned = pd.Series(False, index=df.index)
    counts = []
    for i, rule in enumerate(rules, start=1):
        m = combined_mask(df, rule.get("conditions", []), rule.get("mode", "and"), f"{label} / kural {i}")
        take = m & ~assigned
        val, _ = _branch_value(rule.get("value", ""), df, f"{label} / kural {i}", tables, notes)
        result = result.where(~take, val.astype(object))
        assigned |= take
        counts.append(int(take.sum()))
    out = df.copy()
    out[name] = result.to_numpy()
    try:
        conv, bad = to_number(out[name])
        if bad == 0 and out[name].notna().any() and all(
                not isinstance(v, str) for v in out[name].dropna().head(50)):
            out[name] = conv
    except Exception:
        pass
    r = OpResult(out)
    r.messages.append("Kural başına satır: " + ", ".join(
        f"{i}) {_fmt_n(c)}" for i, c in enumerate(counts, start=1)) + f"; hiçbirine uymayan: {_fmt_n(int((~assigned).sum()))}")
    r.warnings.extend(notes)
    unused = [str(i) for i, c in enumerate(counts, start=1) if c == 0]
    if unused and len(df):
        r.warnings.append(f"Hiçbir satıra uygulanmayan kural: {', '.join(unused)} (üstteki bir kural bu satırları almış olabilir).")
    return r


register(Operation(
    "rules", "Kural tablosu", _run_rules,
    lambda p: f"Kurallar: {p.get('name')} ({len(p.get('rules', []))} kural)",
    refs=lambda p: _formula_refs(p, ["default", "rules"]), uses_params=True,
))


# ---------------------------------------------------------------- dönem filtresi
def _run_period_filter(inputs, p, label):
    """Seçili döneme (vardiya veya gün) düşen satırları tutar.

    Dönem, 'Rapor oluştur' sırasında seçilen tarih/vardiyadan gelir; adımın
    kendisinde sabit saat yazılmaz. Böylece aynı iş akışı her vardiya için çalışır.
    """
    df = inputs[0]
    ctx = p.get("__context__")
    if not ctx:
        raise ShiftFlowError("Dönem seçilmedi. Araç çubuğundaki tarih/vardiya seçimini kontrol edin.")
    col = p.get("column")
    _need(df, [col], label)
    s = df[col]
    if not pd.api.types.is_datetime64_any_dtype(s):
        conv = pd.to_datetime(s.astype("string").str.strip(), dayfirst=True, errors="coerce", format="mixed")
        if conv.isna().all() and (~is_empty(s)).any():
            raise TypeMismatchError(f"'{col}' sütunu tarih/saat içermiyor; dönem filtresi uygulanamaz.")
        s = conv
    start, end = pd.Timestamp(ctx["start"]), pd.Timestamp(ctx["end"])
    if p.get("scope") == "day":
        start = pd.Timestamp(ctx["date"])
        end = start + pd.Timedelta(days=1)
    m = (s >= start) & (s < end)
    out = df[m.fillna(False).to_numpy()].reset_index(drop=True)
    r = OpResult(out)
    r.messages.append(f"{start:%d.%m.%Y %H:%M} – {end:%d.%m.%Y %H:%M} arası: {_fmt_n(len(out))} satır "
                      f"({_fmt_n(len(df) - len(out))} satır dönem dışında)")
    n_bad = int(s.isna().sum())
    if n_bad:
        r.warnings.append(f"{_fmt_n(n_bad)} satırda '{col}' boş veya okunamadı; bu satırlar elendi.")
    if len(out) == 0 and len(df):
        r.warnings.append("Seçili dönemde hiç satır yok. Doğru vardiyayı seçtiğinizden emin olun.")
    return r


register(Operation(
    "period_filter", "Dönem filtresi", _run_period_filter,
    lambda p: f"Dönem filtresi: {p.get('column')} {'seçili gün' if p.get('scope') == 'day' else 'seçili vardiya/gün'}",
    uses_context=True,
))
