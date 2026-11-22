"""Excel'e benzeyen, güvenli formül dili.

Desteklenenler:
    [Sütun Adı]                      sütun başvurusu
    12  12,5  12.5  "metin"           sabitler; DOĞRU / YANLIŞ
    + - * / ^  ( )                   aritmetik (tarih - tarih = gün farkı)
    &                                metin birleştirme
    =  <>  <  >  <=  >=              karşılaştırma (metinde büyük/küçük harf duyarsız)
    FONKSİYON(a; b; c)               Türkçe veya İngilizce adlarla, ';' ile ayrılır

Örnekler:
    [Miktar] * [Birim Fiyat]
    EĞER([Gerçekleşme] >= 100; "Hedefte"; "Hedef altı")
    EĞER(VE([Bölge] = "Soğuk Oda"; [Süre] > 40); "Gecikme"; "")
    YUVARLA([Toplanan] / [Hedef] * 100; 1)
    SOLDAN([Lokasyon]; 3) & "-" & YIL([Tarih])
    ([Bitiş] - [Başlangıç]) * 24 * 60          -> dakika

Python `eval` kullanılmaz. İfade küçük bir ayrıştırıcıyla sütunlar üzerinde
vektörel hesaplanır; kullanıcı formülü kod çalıştıramaz. Başa yazılan '='
(Excel alışkanlığı) yok sayılır.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from .errors import MissingColumnError, ShiftFlowError, TypeMismatchError
from .values import to_number, tr_lower, tr_title, tr_upper

_TOKEN = re.compile(
    r"\s*(?:"
    r"(\[(?:[^\]]|\]\])+\])"                       # 1 sütun
    r"|(\d+(?:[.,]\d+)?)"                           # 2 sayı
    r"|(\"(?:[^\"]|\"\")*\")"                       # 3 metin
    r"|(<>|<=|>=|[-+*/^&()=<>;])"                   # 4 işaret
    r"|([A-Za-zÇĞİÖŞÜçğıöşü_][A-Za-z0-9ÇĞİÖŞÜçğıöşü_.]*)"  # 5 ad
    r"|(\{[^{}]+\})"                                 # 6 iş akışı parametresi {Hedef Oran}
    r")"
)


@dataclass
class Tok:
    kind: str  # col, num, str, op, name
    value: object
    pos: int = 0  # formül metnindeki başlangıç konumu (hata yerini göstermek için)
    end: int = 0


def formula_error(message: str, pos: int | None) -> ShiftFlowError:
    e = ShiftFlowError(message)
    e.pos = pos
    return e


def tokenize(expr: str) -> list[Tok]:
    raw = expr or ""
    lead = len(raw) - len(raw.lstrip())
    expr = raw.strip()
    if expr.startswith("="):
        expr = expr[1:]
        lead += 1
    pos, toks = 0, []
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            rest = expr[pos:].strip()
            if not rest:
                break
            bad = pos + (len(expr[pos:]) - len(expr[pos:].lstrip()))
            hint = ""
            if rest.startswith('"'):
                hint = " Tırnak kapanmamış olabilir."
            elif rest.startswith("["):
                hint = " Köşeli parantez kapanmamış olabilir."
            raise formula_error(
                f"Formül anlaşılamadı, şu kısımda sorun var: '{rest[:20]}'.{hint} "
                "Sütun adlarını köşeli parantez içinde yazın, örn. [Miktar] * 2; "
                "fonksiyon bağımsız değişkenlerini ';' ile ayırın.", lead + bad)
        col, num, string, op, name, param = m.groups()
        start = lead + m.start(m.lastindex)
        end = lead + m.end()
        if col:
            toks.append(Tok("col", col[1:-1].replace("]]", "]"), start, end))
        elif num:
            toks.append(Tok("num", float(num.replace(",", ".")), start, end))
        elif string:
            toks.append(Tok("str", string[1:-1].replace('""', '"'), start, end))
        elif op:
            toks.append(Tok("op", op, start, end))
        elif param:
            toks.append(Tok("param", param[1:-1].strip(), start, end))
        else:
            toks.append(Tok("name", name, start, end))
        pos = m.end()
    if not toks:
        raise ShiftFlowError("Formül boş.")
    return toks


def check_parentheses(expr: str) -> None:
    """Parantez dengesini kontrol eder; hatanın yerini bildirir."""
    toks = tokenize(expr)
    stack = []
    for t in toks:
        if t.kind == "op" and t.value == "(":
            stack.append(t)
        elif t.kind == "op" and t.value == ")":
            if not stack:
                raise formula_error("Fazladan kapanan parantez var.", t.pos)
            stack.pop()
    if stack:
        t = stack[-1]
        i = toks.index(t)
        owner = toks[i - 1].value if i > 0 and toks[i - 1].kind == "name" else None
        what = f"{owner}( … ) parantezi" if owner else "Açılan bir parantez"
        raise formula_error(f"{what} kapanmamış; sonuna ')' ekleyin.", t.pos)


SIGNATURES = {
    "EĞER": ["koşul", "doğruysa", "yanlışsa"], "ÇOKEĞER": ["koşul1", "değer1", "koşul2", "değer2", "…"],
    "VE": ["koşul1", "koşul2", "…"], "YADA": ["koşul1", "koşul2", "…"], "DEĞİL": ["koşul"],
    "EĞERHATA": ["değer", "hata/boş ise"], "EBOŞSA": ["değer"],
    "YUVARLA": ["sayı", "basamak"], "YUKARIYUVARLA": ["sayı", "basamak"], "AŞAĞIYUVARLA": ["sayı", "basamak"],
    "MUTLAK": ["sayı"], "TAMSAYI": ["sayı"], "MOD": ["sayı", "bölen"], "MAK": ["değer1", "değer2", "…"],
    "MİN": ["değer1", "değer2", "…"], "TOPLA": ["değer1", "değer2", "…"], "ORTALAMA": ["değer1", "değer2", "…"],
    "SAYIYAÇEVİR": ["metin"], "SOLDAN": ["metin", "karakter sayısı"], "SAĞDAN": ["metin", "karakter sayısı"],
    "PARÇAAL": ["metin", "başlangıç", "karakter sayısı"], "UZUNLUK": ["metin"], "KIRP": ["metin"],
    "BÜYÜKHARF": ["metin"], "KÜÇÜKHARF": ["metin"], "YAZIMDÜZENİ": ["metin"], "BİRLEŞTİR": ["metin1", "metin2", "…"],
    "YERİNEKOY": ["metin", "eski", "yeni"], "YIL": ["tarih"], "AY": ["tarih"], "GÜN": ["tarih"], "SAAT": ["tarih"],
    "DAKİKA": ["tarih"], "HAFTANINGÜNÜ": ["tarih", "tür (2: pazartesi=1)"], "HAFTASAY": ["tarih"], "BUGÜN": [],
    "ŞİMDİ": [], "TARİH": ["yıl", "ay", "gün"], "METNEÇEVİR": ["değer", "biçim (\"0,0%\", \"gg.aa.yyyy\")"],
    "DÜŞEYARA": ["aranan", "\"tablo\"", "sütun (sıra no veya ad)", "0"],
    "ÇAPRAZARA": ["aranan", "\"tablo\"", "\"anahtar sütun\"", "\"getirilecek sütun\"", "bulunamazsa"],
    "EĞERSAY": ["\"tablo\" (BU)", "\"sütun\"", "ölçüt"],
    "ÇOKEĞERSAY": ["\"tablo\"", "\"sütun1\"", "ölçüt1", "\"sütun2\"", "ölçüt2", "…"],
    "ETOPLA": ["\"tablo\"", "\"ölçüt sütunu\"", "ölçüt", "\"toplam sütunu\""],
    "ÇOKETOPLA": ["\"tablo\"", "\"toplam sütunu\"", "\"sütun1\"", "ölçüt1", "…"],
    "ORTALAMAEĞER": ["\"tablo\"", "\"ölçüt sütunu\"", "ölçüt", "\"ortalama sütunu\""],
    "TABLOTOPLA": ["\"tablo\"", "\"sütun\""], "TABLOSAY": ["\"tablo\"", "\"sütun\""],
    "TABLOORT": ["\"tablo\"", "\"sütun\""], "TABLOMAK": ["\"tablo\"", "\"sütun\""],
    "TABLOMİN": ["\"tablo\"", "\"sütun\""],
    "ÇOKEĞERORTALAMA": ["\"tablo\"", "\"ortalama sütunu\"", "\"sütun1\"", "ölçüt1", "…"],
    "MAKEĞER": ["\"tablo\"", "\"değer sütunu\"", "\"sütun1\"", "ölçüt1", "…"],
    "MİNEĞER": ["\"tablo\"", "\"değer sütunu\"", "\"sütun1\"", "ölçüt1", "…"],
    "BUL": ["aranan", "metin", "başlangıç"], "MBUL": ["aranan", "metin", "başlangıç"],
    "DEĞİŞTİR": ["metin", "başlangıç", "karakter sayısı", "yeni metin"], "YİNELE": ["metin", "kaç kez"],
    "METİNBİRLEŞTİR": ["ayraç", "boşları atla (DOĞRU)", "metin1", "metin2", "…"], "ÖZDEŞ": ["metin1", "metin2"],
    "ESAYIYSA": ["değer"], "EMETİNSE": ["değer"], "SEÇ": ["sıra", "değer1", "değer2", "…"],
    "KAREKÖK": ["sayı"], "ÇARPIM": ["değer1", "değer2", "…"], "ORTANCA": ["değer1", "değer2", "…"],
    "BAĞ_DEĞ_SAY": ["değer1", "değer2", "…"], "BAĞ_DEĞ_DOLU_SAY": ["değer1", "değer2", "…"],
    "ZAMAN": ["saat", "dakika", "saniye"], "SERİTARİH": ["tarih", "ay sayısı"], "SERİAY": ["tarih", "ay sayısı"],
    "İŞGÜNÜ": ["başlangıç", "iş günü sayısı"], "TAMİŞGÜNÜ": ["başlangıç", "bitiş"],
    "ETARİHLİ": ["başlangıç", "bitiş", "\"Y\"/\"M\"/\"D\""], "TARİHSAYISI": ["metin"],
    "ÖNCEKİ": ["[sütun]", "kaç satır önce (1)", "[grup sütunu]"],
    "SONRAKİ": ["[sütun]", "kaç satır sonra (1)", "[grup sütunu]"],
    "KÜMÜLATİF": ["[sütun]", "[grup sütunu]"], "SIRA": ["[sütun]", "0: büyükten / 1: küçükten", "[grup sütunu]"],
}


def signature_at(expr: str, cursor: int) -> tuple[str, int] | None:
    """İmlecin içinde bulunduğu fonksiyon ve kaçıncı bağımsız değişkende olduğu."""
    text = expr[:cursor]
    depth, arg, i = 0, 0, len(text) - 1
    in_str = False
    # geriye doğru tarama: tırnak ve köşeli parantez içleri atlanır
    while i >= 0:
        ch = text[i]
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "]":
                j = text.rfind("[", 0, i)
                i = j if j >= 0 else i
            elif ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    m = re.search(r"([A-Za-zÇĞİÖŞÜçğıöşü_][A-Za-z0-9ÇĞİÖŞÜçğıöşü_.]*)\s*$", text[:i])
                    if not m:
                        return None
                    return _fname(m.group(1)), arg
                depth -= 1
            elif ch == ";" and depth == 0:
                arg += 1
        i -= 1
    return None


def signature_text(name: str, arg: int) -> str:
    canon = _ALIASES.get(name, name)
    sig = SIGNATURES.get(canon)
    if sig is None:
        return ""
    parts = []
    for i, a in enumerate(sig):
        cur = i == arg or (a == "…" and arg >= i)
        parts.append(f"<b>{a}</b>" if cur else a)
    return f"{canon}(" + "; ".join(parts) + ")"


def _group(toks: list[Tok]):
    """Token listesini iç içe yapıya çevirir: ('call', ad, [argümanlar]) / ('paren', [..]) / Tok."""
    def parse_seq(i, stop):
        seq = []
        while i < len(toks):
            t = toks[i]
            if t.kind == "op" and t.value in stop:
                return seq, i
            if t.kind == "name" and i + 1 < len(toks) and toks[i + 1].kind == "op" and toks[i + 1].value == "(":
                args, cur = [], []
                i += 2
                while i < len(toks):
                    part, i = parse_seq(i, (";", ")"))
                    args.append(part)
                    if i >= len(toks) or toks[i].value == ")":
                        break
                    i += 1
                seq.append(("call", t.value, args))
                i += 1
                continue
            if t.kind == "op" and t.value == "(":
                inner, i = parse_seq(i + 1, (")",))
                seq.append(("paren", inner))
                i += 1
                continue
            seq.append(t)
            i += 1
        return seq, i
    seq, _ = parse_seq(0, ())
    return seq


def _tok_text(t: Tok) -> str:
    if t.kind == "col":
        return "[" + str(t.value).replace("]", "]]") + "]"
    if t.kind == "str":
        return '"' + str(t.value).replace('"', '""') + '"'
    if t.kind == "num":
        v = float(t.value)
        return str(int(v)) if v.is_integer() else str(v).replace(".", ",")
    return str(t.value)


def _is_unary(prev) -> bool:
    return prev is None or (isinstance(prev, Tok) and prev.kind == "op" and prev.value not in (")",))


def _op_text(item, prev) -> str:
    if item.value in ("-", "+") and _is_unary(prev):
        return item.value
    return f" {item.value} "


def _squash(text: str) -> str:
    """Satır başındaki girintiye dokunmadan çift boşlukları teke indirir."""
    return "\n".join(re.match(r"^\s*", ln).group(0) + re.sub(r" {2,}", " ", ln.lstrip(" "))
                     for ln in text.split("\n"))


def _inline(seq) -> str:
    out, prev = [], None
    for item in seq:
        if isinstance(item, Tok):
            out.append(_op_text(item, prev) if item.kind == "op" else _tok_text(item))
        elif item[0] == "call":
            out.append(f"{item[1]}(" + "; ".join(_inline(a).strip() for a in item[2]) + ")")
        else:
            out.append("(" + _inline(item[1]).strip() + ")")
        prev = item
    return _squash("".join(out))


def _pretty(seq, indent: int, width: int) -> str:
    flat = _inline(seq).strip()
    if len(flat) + indent * 4 <= width:
        return flat
    out, prev = [], None
    for item in seq:
        if isinstance(item, Tok):
            out.append(_op_text(item, prev) if item.kind == "op" else _tok_text(item))
        elif item[0] == "call":
            single = f"{item[1]}(" + "; ".join(_inline(a).strip() for a in item[2]) + ")"
            if len(single) + indent * 4 <= width:
                out.append(single)
            else:
                pad = "    " * (indent + 1)
                args = [pad + _pretty(a, indent + 1, width).strip() for a in item[2]]
                out.append(f"{item[1]}(\n" + ";\n".join(args) + "\n" + "    " * indent + ")")
        else:
            inner = _pretty(item[1], indent + 1, width).strip()
            if "\n" in inner:
                out.append("(\n" + "    " * (indent + 1) + inner + "\n" + "    " * indent + ")")
            else:
                out.append("(" + inner + ")")
        prev = item
    return _squash("".join(out))


def format_formula(expr: str, width: int = 70) -> str:
    """Uzun formülü girintili, okunur biçime getirir (anlamı değişmez)."""
    toks = tokenize(expr)
    check_parentheses(expr)
    return _pretty(_group(toks), 0, width).strip()


def one_line(expr: str) -> str:
    toks = tokenize(expr)
    return _inline(_group(toks)).strip()


def referenced_columns(expr: str) -> list[str]:
    return [t.value for t in tokenize(expr) if t.kind == "col"]


def rename_table(expr: str, old: str, new: str) -> str:
    """Formüldeki tablo adını değiştirir (yalnızca formül o tabloya başvuruyorsa)."""
    if not expr or old not in referenced_tables(expr):
        return expr
    q_old = '"' + old.replace('"', '""') + '"'
    q_new = '"' + new.replace('"', '""') + '"'
    return expr.replace(q_old, q_new)


def referenced_tables(expr: str) -> list[str]:
    """Formülün tablo fonksiyonlarıyla başvurduğu veri kümeleri (\"BU\" hariç)."""
    if not expr or not str(expr).strip():
        return []
    try:
        toks = tokenize(str(expr))
    except ShiftFlowError:
        return []
    out = []
    for i, t in enumerate(toks):
        if t.kind != "name" or i + 1 >= len(toks) or toks[i + 1].value != "(":
            continue
        fname = _fname(t.value)
        canonical = _ALIASES.get(fname, fname)
        if canonical not in TABLE_ARG and fname not in TABLE_ARG:
            continue
        want = TABLE_ARG.get(fname, TABLE_ARG.get(canonical))
        depth, arg, j = 0, 0, i + 1
        while j < len(toks):
            tk = toks[j]
            if tk.kind == "op" and tk.value == "(":
                depth += 1
                if depth == 1:
                    j += 1
                    if arg == want and j < len(toks) and toks[j].kind == "str":
                        nxt = toks[j + 1] if j + 1 < len(toks) else None
                        if nxt is not None and nxt.kind == "op" and nxt.value in (";", ")"):
                            name = toks[j].value
                            if name.upper() not in SELF_TABLE and name not in out:
                                out.append(name)
                    continue
            elif tk.kind == "op" and tk.value == ")":
                depth -= 1
                if depth == 0:
                    break
            elif tk.kind == "op" and tk.value == ";" and depth == 1:
                arg += 1
                if arg == want and j + 1 < len(toks) and toks[j + 1].kind == "str":
                    nxt = toks[j + 2] if j + 2 < len(toks) else None
                    if nxt is not None and nxt.kind == "op" and nxt.value in (";", ")"):
                        name = toks[j + 1].value
                        if name.upper() not in SELF_TABLE and name not in out:
                            out.append(name)
            j += 1
    return out


# ---------------------------------------------------------------------- değer yardımcıları
def _is_na(x) -> bool:
    return x is None or x is pd.NA or x is pd.NaT or (isinstance(x, float) and math.isnan(x))


def _text_series(v, index) -> pd.Series:
    def fmt(x):
        if _is_na(x):
            return ""
        if isinstance(x, (bool, np.bool_)):
            return "DOĞRU" if x else "YANLIŞ"
        if isinstance(x, (float, np.floating)) and float(x).is_integer():
            return str(int(x))
        if isinstance(x, (float, np.floating)):
            return f"{x:.10g}".replace(".", ",")
        if isinstance(x, pd.Timestamp):
            return x.strftime("%d.%m.%Y") if not (x.hour or x.minute) else x.strftime("%d.%m.%Y %H:%M")
        return str(x)
    if isinstance(v, pd.Series):
        return v.map(fmt).astype(object)
    return pd.Series([fmt(v)] * len(index), index=index, dtype=object)


class _Ctx:
    def __init__(self, df, label, tables=None):
        self.df, self.label, self.div_zero = df, label, 0
        self.tables = tables or {}
        self.notes: list[str] = []
        self.params: dict = {}

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    @property
    def index(self):
        return self.df.index

    def series(self, v) -> pd.Series:
        if isinstance(v, pd.Series):
            return v
        return pd.Series([v] * len(self.df), index=self.df.index, dtype=object if isinstance(v, str) else None)

    def num(self, v, what="değer"):
        """Aritmetik için sayıya çevirir; tarihleri olduğu gibi bırakır."""
        if isinstance(v, (bool, np.bool_)):
            return float(v)
        if isinstance(v, str):
            from .values import _parse_number_text
            p = _parse_number_text(v)
            if p is None:
                raise TypeMismatchError(f"'{v}' metni aritmetik işlemde kullanılamaz.")
            return p
        if isinstance(v, (pd.Timestamp, datetime)):
            return pd.Timestamp(v)
        if isinstance(v, pd.Series):
            if pd.api.types.is_datetime64_any_dtype(v):
                return v
            if pd.api.types.is_bool_dtype(v):
                return v.astype(float)
            if pd.api.types.is_numeric_dtype(v):
                return v.astype(float)
            conv, bad = to_number(v)
            if bad:
                examples = [x for x in v.dropna().astype(str) if x.strip()][:3]
                name = v.name if v.name is not None else what
                raise TypeMismatchError(
                    f"'{name}' sütununda sayı olmayan {bad} değer var, hesaplama yapılamadı. "
                    f"Örnek: {', '.join(examples)}. Önce 'Tip dönüştür' adımıyla düzeltin "
                    "veya bu satırları filtreleyin."
                )
            return conv
        return v

    def boolean(self, v) -> pd.Series:
        if isinstance(v, pd.Series):
            if pd.api.types.is_bool_dtype(v):
                return v.fillna(False).astype(bool)
            if pd.api.types.is_numeric_dtype(v):
                return (v.fillna(0) != 0)
            t = _text_series(v, self.index).map(tr_lower)
            return t.isin(["doğru", "true", "1", "evet"])
        if isinstance(v, (bool, np.bool_)):
            return pd.Series(bool(v), index=self.index)
        if isinstance(v, (int, float)):
            return pd.Series(v != 0 and not _is_na(v), index=self.index)
        return pd.Series(tr_lower(str(v)) in ("doğru", "true", "1", "evet"), index=self.index)


def _is_numberlike(v, ctx) -> bool:
    if isinstance(v, (bool, np.bool_, int, float, np.integer, np.floating)):
        return True
    if isinstance(v, str):
        from .values import _parse_number_text
        return _parse_number_text(v) is not None
    if isinstance(v, pd.Series):
        if pd.api.types.is_numeric_dtype(v):
            return True
        if pd.api.types.is_datetime64_any_dtype(v):
            return False
        _, bad = to_number(v)
        return bad == 0 and v.notna().any()
    return False


def _is_datelike(v) -> bool:
    return isinstance(v, (pd.Timestamp, datetime)) or (isinstance(v, pd.Series) and pd.api.types.is_datetime64_any_dtype(v))


def _compare(a, b, op, ctx):
    if _is_datelike(a) or _is_datelike(b):
        x, y = a, b
        if isinstance(x, str):
            x = pd.to_datetime(x, dayfirst=True, errors="coerce")
        if isinstance(y, str):
            y = pd.to_datetime(y, dayfirst=True, errors="coerce")
        x, y = ctx.series(x), ctx.series(y)
    elif _is_numberlike(a, ctx) and _is_numberlike(b, ctx):
        x, y = ctx.series(ctx.num(a)), ctx.series(ctx.num(b))
    else:
        x = _text_series(a, ctx.index).map(tr_lower)
        y = _text_series(b, ctx.index).map(tr_lower)
    ops = {"=": lambda: x == y, "<>": lambda: x != y, "<": lambda: x < y, ">": lambda: x > y,
           "<=": lambda: x <= y, ">=": lambda: x >= y}
    res = ops[op]()
    return pd.Series(res, index=ctx.index).fillna(op == "<>").astype(bool)


def _arith(a, b, op, ctx):
    a, b = ctx.num(a), ctx.num(b)
    da, db = _is_datelike(a), _is_datelike(b)
    if da or db:
        if op == "-" and da and db:
            return (ctx.series(a) - ctx.series(b)) / pd.Timedelta(days=1)
        if op in "+-" and da and not db:
            delta = pd.to_timedelta(ctx.series(b).astype(float), unit="D").dt.round("ms")
            return ctx.series(a) + delta if op == "+" else ctx.series(a) - delta
        if op == "+" and db and not da:
            return ctx.series(b) + pd.to_timedelta(ctx.series(a).astype(float), unit="D").dt.round("ms")
        raise TypeMismatchError("Tarihlerle yalnızca toplama/çıkarma yapılabilir (tarih - tarih = gün sayısı).")
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "^":
        return np.power(a, b)
    b_arr = b if isinstance(b, pd.Series) else pd.Series(b, index=ctx.index, dtype=float)
    zero = b_arr == 0
    ctx.div_zero += int(zero.sum())
    return a / b_arr.where(~zero, np.nan)


# ---------------------------------------------------------------------- fonksiyonlar
def _round_half_away(x, n):
    f = 10.0 ** n
    return np.sign(x) * np.floor(np.abs(x) * f + 0.5) / f


def _dt(v, ctx, fname):
    s = ctx.series(v)
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    conv = pd.to_datetime(_text_series(s, ctx.index).replace("", None), dayfirst=True, errors="coerce", format="mixed")
    if conv.isna().all() and s.notna().any():
        raise TypeMismatchError(f"{fname}: tarih bekleniyor.")
    return conv


def _f_if(ctx, args):
    if len(args) not in (2, 3):
        raise ShiftFlowError("EĞER(koşul; doğruysa; yanlışsa) üç bağımsız değişken alır.")
    cond = ctx.boolean(args[0])
    a = ctx.series(args[1])
    b = ctx.series(args[2] if len(args) == 3 else False)
    return a.where(cond, b)


def _f_iferror(ctx, args):
    a, b = ctx.series(args[0]), ctx.series(args[1])
    bad = a.isna()
    if a.dtype == object:
        bad = bad | a.map(lambda x: isinstance(x, float) and math.isinf(x))
    elif pd.api.types.is_float_dtype(a):
        bad = bad | np.isinf(a)
    return a.where(~bad, b)


def _rowwise(ctx, args, fn):
    cols = [ctx.series(ctx.num(a)).astype(float) for a in args]
    frame = pd.concat(cols, axis=1)
    return fn(frame)


def _text_fn(fn):
    def run(ctx, args):
        t = _text_series(args[0], ctx.index)
        return fn(ctx, t, args[1:])
    return run


def _int_arg(ctx, args, i, default):
    if len(args) <= i:
        return default
    v = ctx.num(args[i])
    if isinstance(v, pd.Series):
        v = v.iloc[0] if len(v) else default
    return int(v)


def _weekday(ctx, args):
    d = _dt(args[0], ctx, "HAFTANINGÜNÜ")
    typ = _int_arg(ctx, args, 1, 1)
    wd = d.dt.day_of_week  # pazartesi=0
    return (wd + 1) if typ == 2 else ((wd + 1) % 7 + 1)


# ---------------------------------------------------------------------- tablo fonksiyonları
SELF_TABLE = {"BU", "THIS", ""}
TABLE_ARG = {  # fonksiyon -> tablo adının bulunduğu bağımsız değişken sırası
    "DÜŞEYARA": 1, "VLOOKUP": 1, "ÇAPRAZARA": 1, "XLOOKUP": 1,
    "EĞERSAY": 0, "COUNTIF": 0, "ÇOKEĞERSAY": 0, "COUNTIFS": 0, "ETOPLA": 0, "SUMIF": 0,
    "ÇOKETOPLA": 0, "SUMIFS": 0, "ORTALAMAEĞER": 0, "AVERAGEIF": 0,
    "TABLOTOPLA": 0, "TABLOSAY": 0, "TABLOORT": 0, "TABLOMAK": 0, "TABLOMİN": 0,
}


def _scalar(v, what):
    if isinstance(v, pd.Series):
        raise ShiftFlowError(f"{what} sabit bir değer olmalı (tırnak içinde yazın).")
    return v


def _table(ctx, name, fname):
    name = str(_scalar(name, f"{fname}: tablo adı")).strip()
    if name.upper() in SELF_TABLE:
        return ctx.df, "bu tablo"
    if name not in ctx.tables:
        raise ShiftFlowError(f"{fname}: '{name}' adlı tablo (veri kümesi) bulunamadı. Tablo adını tırnak içinde, "
                             "veri kümeleri listesindeki gibi yazın; içinde bulunduğunuz tablo için \"BU\" yazın.")
    return ctx.tables[name], name


def _col(table, ref, tname, fname):
    ref = _scalar(ref, f"{fname}: sütun")
    if isinstance(ref, (int, float)) and not isinstance(ref, bool):
        i = int(ref)
        if not 1 <= i <= table.shape[1]:
            raise ShiftFlowError(f"{fname}: '{tname}' tablosunda {i}. sütun yok ({table.shape[1]} sütun var).")
        return table.columns[i - 1]
    if ref not in table.columns:
        raise MissingColumnError([ref], table.columns, f"{fname} / {tname}")
    return ref


def _keys(series: pd.Series) -> pd.Series:
    from .values import normalize_key
    return normalize_key(series).map(lambda k: tr_lower(k) if isinstance(k, str) else k)


def _lookup(ctx, value, table, tname, key_col, ret_col, fname, missing=None):
    rk = _keys(table[key_col])
    valid = rk.notna().to_numpy()
    dup = int(rk[valid].duplicated().sum())
    if dup:
        ctx.note(f"{fname}: '{tname}' tablosunda '{key_col}' değerlerinden {dup} tanesi tekrar ediyor; ilk bulunan kullanıldı.")
    first = valid & ~rk.duplicated().to_numpy()
    mapping = dict(zip(rk[first].tolist(), table[ret_col].to_numpy()[first]))
    lk = _keys(ctx.series(value))
    vals = [mapping.get(k, None) if k is not None else None for k in lk]
    found = np.array([k is not None and k in mapping for k in lk])
    res = pd.Series(vals, index=ctx.index, dtype=object)
    if pd.api.types.is_numeric_dtype(table[ret_col]):
        res = pd.to_numeric(res, errors="coerce")
    elif pd.api.types.is_datetime64_any_dtype(table[ret_col]):
        res = pd.to_datetime(res, errors="coerce")
    n_miss = int((~found).sum())
    if missing is not None:
        res = res.astype(object).where(found, missing if not isinstance(missing, pd.Series) else missing)
    elif n_miss:
        ctx.note(f"{fname}: {n_miss} satırın karşılığı '{tname}' tablosunda yok (boş bırakıldı; "
                 "EĞERHATA ile başka değer verebilirsiniz).")
    return res


def _f_vlookup(ctx, a):
    if len(a) < 3:
        raise ShiftFlowError("DÜŞEYARA(aranan; \"Tablo\"; sütun; [0]) en az üç bağımsız değişken alır.")
    if len(a) > 3 and ctx.boolean(a[3]).any():
        raise ShiftFlowError("DÜŞEYARA: yaklaşık eşleşme (DOĞRU/1) desteklenmiyor; dördüncü değeri 0 yapın.")
    table, tname = _table(ctx, a[1], "DÜŞEYARA")
    return _lookup(ctx, a[0], table, tname, table.columns[0], _col(table, a[2], tname, "DÜŞEYARA"), "DÜŞEYARA")


def _f_xlookup(ctx, a):
    if len(a) < 4:
        raise ShiftFlowError("ÇAPRAZARA(aranan; \"Tablo\"; \"Anahtar sütun\"; \"Getirilecek sütun\"; [bulunamazsa]) "
                             "en az dört bağımsız değişken alır.")
    table, tname = _table(ctx, a[1], "ÇAPRAZARA")
    key = _col(table, a[2], tname, "ÇAPRAZARA")
    ret = _col(table, a[3], tname, "ÇAPRAZARA")
    return _lookup(ctx, a[0], table, tname, key, ret, "ÇAPRAZARA", a[4] if len(a) > 4 else None)


def _crit_scalar_mask(series: pd.Series, crit) -> pd.Series:
    """Excel ölçütü: 5, "Ege", ">5", "<>İptal", ">=10", "A*" (joker)."""
    import fnmatch
    if isinstance(crit, (bool, np.bool_)):
        return series.astype(object).map(lambda x: x is True or x is np.True_)
    op, val = "=", crit
    if isinstance(crit, str):
        m = re.match(r"^\s*(<>|>=|<=|=|<|>)(.*)$", crit)
        if m:
            op, val = m.group(1), m.group(2)
    from .values import _parse_number_text
    num = val if isinstance(val, (int, float)) else _parse_number_text(str(val)) if str(val).strip() else None
    if num is not None and (pd.api.types.is_numeric_dtype(series) or op not in ("=", "<>")):
        x, _ = to_number(series)
        res = {"=": x == num, "<>": x != num, ">": x > num, "<": x < num, ">=": x >= num, "<=": x <= num}[op]
        return pd.Series(res, index=series.index).fillna(op == "<>").astype(bool)
    t = _text_series(series, series.index).map(tr_lower)
    v = tr_lower(str(val))
    if any(ch in v for ch in "*?"):
        m = t.map(lambda s: fnmatch.fnmatchcase(s, v))
    else:
        m = t == v
    if op == "<>":
        return ~m
    if op == "=":
        return m
    raise ShiftFlowError(f"'{crit}' ölçütü metinle kullanılamaz.")


def _agg_if(ctx, table, tname, pairs, value_col, how, fname):
    """EĞERSAY/ETOPLA ailesinin ortak hesabı (vektörel).

    pairs: [(sütun, ölçüt)]. Ölçüt sabitse tablo önce süzülür; satıra bağlıysa
    (örn. [Personel No]) tablo o sütunlara göre gruplanır ve her satır kendi
    değerinin sonucunu alır.
    """
    t = table
    row_pairs = []
    for col, crit in pairs:
        if isinstance(crit, pd.Series):
            row_pairs.append((col, crit))
        else:
            t = t[_crit_scalar_mask(t[col], crit).to_numpy()]
    vals = None
    if value_col is not None:
        vals, bad = to_number(t[value_col])
        if bad:
            ctx.note(f"{fname}: '{value_col}' sütununda sayı olmayan {bad} değer yok sayıldı.")
    if not row_pairs:
        if how == "count":
            out = float(len(t))
        elif how == "sum":
            out = float(vals.sum()) if vals is not None else 0.0
        elif how in ("max", "min"):
            v = vals.max() if how == "max" else vals.min()
            out = float(v) if vals is not None and pd.notna(v) else np.nan
        else:
            out = float(vals.mean()) if vals is not None and vals.notna().any() else np.nan
        return pd.Series(out, index=ctx.index, dtype=float)
    key_cols = [c for c, _ in row_pairs]
    g = pd.DataFrame({f"k{i}": _keys(t[c]).to_numpy() for i, c in enumerate(key_cols)})
    if vals is not None:
        g["v"] = vals.to_numpy()
    kcols = [f"k{i}" for i in range(len(key_cols))]
    if how == "count":
        agg = g.groupby(kcols, dropna=True).size()
    elif how == "sum":
        agg = g.groupby(kcols, dropna=True)["v"].sum()
    elif how in ("max", "min"):
        agg = getattr(g.groupby(kcols, dropna=True)["v"], how)()
    else:
        agg = g.groupby(kcols, dropna=True)["v"].mean()
    mapping = agg.to_dict()
    row_keys = list(zip(*[_keys(ctx.series(v)) for _, v in row_pairs])) if len(row_pairs) > 1 \
        else list(_keys(ctx.series(row_pairs[0][1])))
    default = np.nan if how in ("mean", "max", "min") else 0.0
    return pd.Series([mapping.get(k, default) if k is not None else default for k in row_keys],
                     index=ctx.index, dtype=float)


def _f_countif(ctx, a):
    table, tname = _table(ctx, a[0], "EĞERSAY")
    return _agg_if(ctx, table, tname, [(_col(table, a[1], tname, "EĞERSAY"), a[2])], None, "count", "EĞERSAY")


def _pairs(ctx, table, tname, args, fname):
    if len(args) % 2:
        raise ShiftFlowError(f"{fname}: sütun ve ölçütler çift olarak verilmeli (sütun; ölçüt; sütun; ölçüt…).")
    return [(_col(table, args[i], tname, fname), args[i + 1]) for i in range(0, len(args), 2)]


def _f_countifs(ctx, a):
    table, tname = _table(ctx, a[0], "ÇOKEĞERSAY")
    return _agg_if(ctx, table, tname, _pairs(ctx, table, tname, a[1:], "ÇOKEĞERSAY"), None, "count", "ÇOKEĞERSAY")


def _f_sumif(ctx, a):
    table, tname = _table(ctx, a[0], "ETOPLA")
    crit_col = _col(table, a[1], tname, "ETOPLA")
    sum_col = _col(table, a[3], tname, "ETOPLA") if len(a) > 3 else crit_col
    return _agg_if(ctx, table, tname, [(crit_col, a[2])], sum_col, "sum", "ETOPLA")


def _f_sumifs(ctx, a):
    table, tname = _table(ctx, a[0], "ÇOKETOPLA")
    sum_col = _col(table, a[1], tname, "ÇOKETOPLA")
    return _agg_if(ctx, table, tname, _pairs(ctx, table, tname, a[2:], "ÇOKETOPLA"), sum_col, "sum", "ÇOKETOPLA")


def _f_averageif(ctx, a):
    table, tname = _table(ctx, a[0], "ORTALAMAEĞER")
    crit_col = _col(table, a[1], tname, "ORTALAMAEĞER")
    avg_col = _col(table, a[3], tname, "ORTALAMAEĞER") if len(a) > 3 else crit_col
    return _agg_if(ctx, table, tname, [(crit_col, a[2])], avg_col, "mean", "ORTALAMAEĞER")


def _f_table_agg(how):
    def run(ctx, a):
        table, tname = _table(ctx, a[0], "TABLO")
        col = _col(table, a[1], tname, "TABLO")
        if how == "count":
            return pd.Series(float(table[col].notna().sum()), index=ctx.index)
        v, _ = to_number(table[col])
        val = {"sum": v.sum(), "mean": v.mean(), "max": v.max(), "min": v.min()}[how]
        return pd.Series(float(val) if pd.notna(val) else np.nan, index=ctx.index)
    return run


def _f_ifs(ctx, a):
    if len(a) < 2 or len(a) % 2:
        raise ShiftFlowError("ÇOKEĞER(koşul1; değer1; koşul2; değer2; …) çift sayıda bağımsız değişken alır.")
    res = pd.Series([None] * len(ctx.df), index=ctx.index, dtype=object)
    done = pd.Series(False, index=ctx.index)
    for i in range(0, len(a), 2):
        c = ctx.boolean(a[i]) & ~done
        res = res.where(~c, ctx.series(a[i + 1]).astype(object))
        done |= c
    return res


def _f_text(ctx, a):
    fmt = str(_scalar(a[1], "METNEÇEVİR: biçim")) if len(a) > 1 else "0"
    v = a[0]
    low = tr_lower(fmt)
    if any(x in low for x in ("gg", "dd", "yy", "aa", "mm")):
        d = _dt(v, ctx, "METNEÇEVİR")
        py = low.replace("gg", "%d").replace("dd", "%d").replace("yyyy", "%Y").replace("yy", "%y")
        py = py.replace("aa", "%m").replace("mm", "%m").replace("ss", "%H").replace("hh", "%H").replace("dk", "%M")
        return d.dt.strftime(py).astype(object).where(d.notna(), "")
    x = ctx.series(ctx.num(v)).astype(float)
    pct = fmt.endswith("%")
    if pct:
        x = x * 100
    tr_style = "," in fmt and not fmt.startswith("#,##") or "#." in fmt
    if tr_style:  # Türkçe: '.' binlik, ',' ondalık
        dec = len(fmt.split(",")[1].rstrip("%")) if "," in fmt else 0
        thousands = "#." in fmt
    else:  # İngilizce: ',' binlik, '.' ondalık
        dec = len(fmt.split(".")[1].rstrip("%")) if "." in fmt else 0
        thousands = "#," in fmt
    def f(n):
        if pd.isna(n):
            return ""
        s = f"{n:,.{dec}f}" if thousands else f"{n:.{dec}f}"
        s = s.replace(",", "§").replace(".", ",").replace("§", ".")
        return s + ("%" if pct else "")
    return x.map(f).astype(object)


FUNCTIONS = {
    # tablo
    "DÜŞEYARA": _f_vlookup, "ÇAPRAZARA": _f_xlookup, "EĞERSAY": _f_countif, "ÇOKEĞERSAY": _f_countifs,
    "ETOPLA": _f_sumif, "ÇOKETOPLA": _f_sumifs, "ORTALAMAEĞER": _f_averageif,
    "TABLOTOPLA": _f_table_agg("sum"), "TABLOSAY": _f_table_agg("count"), "TABLOORT": _f_table_agg("mean"),
    "TABLOMAK": _f_table_agg("max"), "TABLOMİN": _f_table_agg("min"),
    "ÇOKEĞER": _f_ifs, "METNEÇEVİR": _f_text,
    # mantık
    "EĞER": _f_if, "IF": _f_if,
    "VE": lambda c, a: pd.concat([c.boolean(x) for x in a], axis=1).all(axis=1),
    "AND": lambda c, a: pd.concat([c.boolean(x) for x in a], axis=1).all(axis=1),
    "YADA": lambda c, a: pd.concat([c.boolean(x) for x in a], axis=1).any(axis=1),
    "OR": lambda c, a: pd.concat([c.boolean(x) for x in a], axis=1).any(axis=1),
    "DEĞİL": lambda c, a: ~c.boolean(a[0]), "NOT": lambda c, a: ~c.boolean(a[0]),
    "EĞERHATA": _f_iferror, "IFERROR": _f_iferror,
    "EBOŞSA": lambda c, a: c.series(a[0]).map(lambda x: _is_na(x) or (isinstance(x, str) and not x.strip())).astype(bool),
    "ISBLANK": lambda c, a: c.series(a[0]).map(lambda x: _is_na(x) or (isinstance(x, str) and not x.strip())).astype(bool),
    # sayı
    "YUVARLA": lambda c, a: _round_half_away(c.series(c.num(a[0])).astype(float), _int_arg(c, a, 1, 0)),
    "ROUND": lambda c, a: _round_half_away(c.series(c.num(a[0])).astype(float), _int_arg(c, a, 1, 0)),
    "YUKARIYUVARLA": lambda c, a: np.sign(c.series(c.num(a[0])).astype(float)) * np.ceil(
        np.abs(c.series(c.num(a[0])).astype(float)) * 10.0 ** _int_arg(c, a, 1, 0)) / 10.0 ** _int_arg(c, a, 1, 0),
    "ROUNDUP": None,
    "AŞAĞIYUVARLA": lambda c, a: np.sign(c.series(c.num(a[0])).astype(float)) * np.floor(
        np.abs(c.series(c.num(a[0])).astype(float)) * 10.0 ** _int_arg(c, a, 1, 0)) / 10.0 ** _int_arg(c, a, 1, 0),
    "ROUNDDOWN": None,
    "MUTLAK": lambda c, a: np.abs(c.series(c.num(a[0])).astype(float)), "ABS": None,
    "TAMSAYI": lambda c, a: np.floor(c.series(c.num(a[0])).astype(float)), "INT": None,
    "MOD": lambda c, a: np.mod(c.series(c.num(a[0])).astype(float), c.num(a[1])),
    "MAK": lambda c, a: _rowwise(c, a, lambda f: f.max(axis=1)), "MAX": None,
    "MİN": lambda c, a: _rowwise(c, a, lambda f: f.min(axis=1)), "MIN": None,
    "TOPLA": lambda c, a: _rowwise(c, a, lambda f: f.sum(axis=1, min_count=1)), "SUM": None,
    "ORTALAMA": lambda c, a: _rowwise(c, a, lambda f: f.mean(axis=1)), "AVERAGE": None,
    "SAYIYAÇEVİR": lambda c, a: to_number(_text_series(a[0], c.index))[0], "VALUE": None,
    # metin
    "SOLDAN": _text_fn(lambda c, t, r: t.str[: _int_arg(c, r, 0, 1)]), "LEFT": None,
    "SAĞDAN": _text_fn(lambda c, t, r: t.map(lambda s, n=_int_arg(c, r, 0, 1): s[-n:] if n else "")), "RIGHT": None,
    "PARÇAAL": _text_fn(lambda c, t, r: t.str[_int_arg(c, r, 0, 1) - 1: _int_arg(c, r, 0, 1) - 1 + _int_arg(c, r, 1, 1)]),
    "MID": None,
    "UZUNLUK": _text_fn(lambda c, t, r: t.str.len()), "LEN": None,
    "KIRP": _text_fn(lambda c, t, r: t.map(lambda s: " ".join(s.split()))), "TRIM": None,
    "BÜYÜKHARF": _text_fn(lambda c, t, r: t.map(tr_upper)), "UPPER": None,
    "KÜÇÜKHARF": _text_fn(lambda c, t, r: t.map(tr_lower)), "LOWER": None,
    "YAZIMDÜZENİ": _text_fn(lambda c, t, r: t.map(tr_title)), "PROPER": None,
    "BİRLEŞTİR": lambda c, a: pd.concat([_text_series(x, c.index) for x in a], axis=1).agg("".join, axis=1),
    "CONCAT": None, "CONCATENATE": None, "ARALIKBİRLEŞTİR": None,
    "YERİNEKOY": lambda c, a: _text_series(a[0], c.index).str.replace(
        str(a[1]) if not isinstance(a[1], pd.Series) else str(a[1].iloc[0]),
        str(a[2]) if not isinstance(a[2], pd.Series) else str(a[2].iloc[0]), regex=False), "SUBSTITUTE": None,
    # tarih
    "YIL": lambda c, a: _dt(a[0], c, "YIL").dt.year, "YEAR": None,
    "AY": lambda c, a: _dt(a[0], c, "AY").dt.month, "MONTH": None,
    "GÜN": lambda c, a: _dt(a[0], c, "GÜN").dt.day, "DAY": None,
    "SAAT": lambda c, a: _dt(a[0], c, "SAAT").dt.hour, "HOUR": None,
    "DAKİKA": lambda c, a: _dt(a[0], c, "DAKİKA").dt.minute, "MINUTE": None,
    "HAFTANINGÜNÜ": _weekday, "WEEKDAY": None,
    "HAFTASAY": lambda c, a: _dt(a[0], c, "HAFTASAY").dt.isocalendar().week.astype(float), "ISOWEEKNUM": None,
    "BUGÜN": lambda c, a: pd.Timestamp.now().normalize(), "TODAY": None,
    "ŞİMDİ": lambda c, a: pd.Timestamp.now().floor("s"), "NOW": None,
    "TARİH": lambda c, a: pd.to_datetime(pd.DataFrame({
        "year": c.series(c.num(a[0])), "month": c.series(c.num(a[1])), "day": c.series(c.num(a[2]))}), errors="coerce"),
    "DATE": None,
}


# ---------------------------------------------------------------------- 3.5: ek fonksiyonlar
def _f_ifs_agg(how, fname):
    """ÇOKEĞERORTALAMA / MAKEĞER / MİNEĞER("Tablo"; "Değer sütunu"; "Sütun"; ölçüt; …)"""
    def run(ctx, a):
        if len(a) < 4:
            raise ShiftFlowError(f"{fname}(\"Tablo\"; \"Değer sütunu\"; \"Sütun\"; ölçüt; …) en az dört "
                                 "bağımsız değişken alır.")
        table, tname = _table(ctx, a[0], fname)
        val = _col(table, a[1], tname, fname)
        return _agg_if(ctx, table, tname, _pairs(ctx, table, tname, a[2:], fname), val, how, fname)
    return run


def _ints(ctx, args, i, default) -> pd.Series:
    """Satıra göre değişebilen tamsayı bağımsız değişkeni (ör. BUL sonucunu PARÇAAL'a vermek)."""
    if len(args) <= i:
        return pd.Series(default, index=ctx.index)
    v = ctx.num(args[i])
    if isinstance(v, pd.Series):
        return pd.to_numeric(v, errors="coerce")
    return pd.Series(float(v), index=ctx.index)


def _slice_text(ctx, args, how):
    t = _text_series(args[0], ctx.index)
    if how == "left":
        n = _ints(ctx, args, 1, 1)
        vals = [s[: int(k)] if pd.notna(k) and k >= 0 else None for s, k in zip(t, n)]
    elif how == "right":
        n = _ints(ctx, args, 1, 1)
        vals = [(s[-int(k):] if k else "") if pd.notna(k) and k >= 0 else None for s, k in zip(t, n)]
    else:
        st, n = _ints(ctx, args, 1, 1), _ints(ctx, args, 2, 1)
        vals = [s[int(a) - 1: int(a) - 1 + int(b)] if pd.notna(a) and pd.notna(b) and a >= 1 and b >= 0 else None
                for s, a, b in zip(t, st, n)]
    return pd.Series(vals, index=ctx.index, dtype=object)


def _find(case_sensitive):
    def run(ctx, a):
        if len(a) < 2:
            raise ShiftFlowError("BUL(aranan; metin; [başlangıç]) en az iki bağımsız değişken alır.")
        needle = _text_series(a[0], ctx.index)
        hay = _text_series(a[1], ctx.index)
        start = _ints(ctx, a, 2, 1)
        out = []
        for n, h, st in zip(needle, hay, start):
            if not case_sensitive:
                n, h = tr_lower(n), tr_lower(h)
            k = h.find(n, int(st) - 1) if pd.notna(st) and st >= 1 else -1
            out.append(float(k + 1) if k >= 0 else np.nan)  # bulunamazsa boş (EĞERHATA ile yakalanır)
        return pd.Series(out, index=ctx.index, dtype=float)
    return run


def _f_replace_at(ctx, a):
    if len(a) != 4:
        raise ShiftFlowError("DEĞİŞTİR(metin; başlangıç; karakter sayısı; yeni metin) dört bağımsız değişken alır.")
    t, new = _text_series(a[0], ctx.index), _text_series(a[3], ctx.index)
    st, n = _ints(ctx, a, 1, 1), _ints(ctx, a, 2, 0)
    return pd.Series([s[: int(x) - 1] + r + s[int(x) - 1 + int(k):] if pd.notna(x) and pd.notna(k) else None
                      for s, r, x, k in zip(t, new, st, n)], index=ctx.index, dtype=object)


def _f_rept(ctx, a):
    t, n = _text_series(a[0], ctx.index), _ints(ctx, a, 1, 1)
    return pd.Series([s * int(k) if pd.notna(k) and k >= 0 else None for s, k in zip(t, n)],
                     index=ctx.index, dtype=object)


def _f_textjoin(ctx, a):
    if len(a) < 3:
        raise ShiftFlowError("METİNBİRLEŞTİR(ayraç; boşları_atla; metin1; metin2; …) en az üç bağımsız değişken alır.")
    sep = str(_scalar(a[0], "METİNBİRLEŞTİR: ayraç"))
    skip = ctx.boolean(a[1])
    parts = [_text_series(x, ctx.index) for x in a[2:]]
    frame = pd.concat(parts, axis=1)
    return pd.Series([sep.join(v for v in row if not (sk and v == "")) for row, sk in
                      zip(frame.itertuples(index=False), skip)], index=ctx.index, dtype=object)


def _f_exact(ctx, a):
    return (_text_series(a[0], ctx.index) == _text_series(a[1], ctx.index)).astype(bool)


def _is_number_value(x):
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, (bool, np.bool_)) \
        and not (isinstance(x, float) and math.isnan(x))


def _f_isnumber(ctx, a):
    s = ctx.series(a[0])
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return s.notna().astype(bool)
    return s.map(_is_number_value).astype(bool)


def _f_istext(ctx, a):
    return ctx.series(a[0]).map(lambda x: isinstance(x, str)).astype(bool)


def _f_choose(ctx, a):
    if len(a) < 2:
        raise ShiftFlowError("SEÇ(sıra; değer1; değer2; …) en az iki bağımsız değişken alır.")
    k = _ints(ctx, a, 0, 1)
    opts = [ctx.series(x).astype(object) for x in a[1:]]
    return pd.Series([opts[int(i) - 1].iloc[r] if pd.notna(i) and 1 <= i <= len(opts) else None
                      for r, i in enumerate(k)], index=ctx.index, dtype=object)


def _f_time(ctx, a):
    h, m, sec = (_ints(ctx, a, i, 0) for i in range(3))
    return (h * 3600 + m * 60 + sec) / 86400.0  # Excel gibi gün kesri: [Tarih] + ZAMAN(8; 0; 0)


def _months(ctx, a, fname, end_of_month):
    d = _dt(a[0], ctx, fname)
    n = _ints(ctx, a, 1, 0)
    out = []
    for x, k in zip(d, n):
        if pd.isna(x) or pd.isna(k):
            out.append(pd.NaT)
            continue
        y = x + pd.DateOffset(months=int(k))
        out.append((y + pd.offsets.MonthEnd(0)).normalize() if end_of_month else y.normalize())
    return pd.Series(pd.to_datetime(out), index=ctx.index)


def _busday(ctx, a, fname, count):
    d1 = _dt(a[0], ctx, fname).dt.normalize()
    if count:
        d2 = _dt(a[1], ctx, fname).dt.normalize()
        out = []
        for x, y in zip(d1, d2):
            if pd.isna(x) or pd.isna(y):
                out.append(np.nan)
            elif y >= x:
                out.append(float(np.busday_count(x.date(), (y + pd.Timedelta(days=1)).date())))
            else:
                out.append(-float(np.busday_count(y.date(), (x + pd.Timedelta(days=1)).date())))
        return pd.Series(out, index=ctx.index, dtype=float)
    n = _ints(ctx, a, 1, 0)
    out = [pd.Timestamp(np.busday_offset(x.date(), int(k), roll="backward" if k >= 0 else "forward"))
           if pd.notna(x) and pd.notna(k) else pd.NaT for x, k in zip(d1, n)]
    return pd.Series(pd.to_datetime(out), index=ctx.index)


def _f_datedif(ctx, a):
    if len(a) != 3:
        raise ShiftFlowError("ETARİHLİ(başlangıç; bitiş; \"Y\"/\"M\"/\"D\") üç bağımsız değişken alır.")
    d1, d2 = _dt(a[0], ctx, "ETARİHLİ").dt.normalize(), _dt(a[1], ctx, "ETARİHLİ").dt.normalize()
    unit = tr_upper(str(_scalar(a[2], "ETARİHLİ: birim")))
    unit = {"G": "D", "A": "M"}.get(unit, unit)
    if unit not in ("Y", "M", "D"):
        raise ShiftFlowError("ETARİHLİ: birim \"Y\" (yıl), \"M\" (ay) veya \"D\" (gün) olmalı.")
    out = []
    for x, y in zip(d1, d2):
        if pd.isna(x) or pd.isna(y) or y < x:
            out.append(np.nan)
            continue
        if unit == "D":
            out.append(float((y - x).days))
            continue
        months = (y.year - x.year) * 12 + (y.month - x.month) - (1 if y.day < x.day else 0)
        out.append(float(months // 12 if unit == "Y" else months))
    return pd.Series(out, index=ctx.index, dtype=float)


def _rowcount(numeric):
    def run(ctx, a):
        cols = []
        for x in a:
            s = ctx.series(x)
            if numeric:
                cols.append(s.map(_is_number_value) if not pd.api.types.is_numeric_dtype(s) else s.notna())
            else:
                cols.append(s.map(lambda v: not _is_na(v) and not (isinstance(v, str) and v == "")))
        return pd.concat(cols, axis=1).sum(axis=1).astype(float)
    return run


def _groups(ctx, a, i):
    """i. bağımsız değişken verilmişse grup anahtarları (satır sırası korunur)."""
    if len(a) <= i:
        return None
    g = ctx.series(a[i])
    return _text_series(g, ctx.index).map(tr_lower)


def _shift(direction):
    def run(ctx, a):
        if not a:
            raise ShiftFlowError("ÖNCEKİ([Sütun]; [kaç satır]; [grup sütunu]) en az bir bağımsız değişken alır.")
        v = ctx.series(a[0])
        n = _int_arg(ctx, a, 1, 1) * direction
        g = _groups(ctx, a, 2)
        if g is None:
            return v.shift(n)
        return v.groupby(g.to_numpy(), sort=False).shift(n)
    return run


def _f_cumulative(ctx, a):
    if not a:
        raise ShiftFlowError("KÜMÜLATİF([Sütun]; [grup sütunu]) en az bir bağımsız değişken alır.")
    v = ctx.series(ctx.num(a[0])).astype(float).fillna(0.0)
    g = _groups(ctx, a, 1)
    return v.cumsum() if g is None else v.groupby(g.to_numpy(), sort=False).cumsum()


def _f_rank(ctx, a):
    if not a:
        raise ShiftFlowError("SIRA([Sütun]; [0: büyükten küçüğe, 1: küçükten büyüğe]; [grup sütunu]) "
                             "en az bir bağımsız değişken alır.")
    v = ctx.series(ctx.num(a[0])).astype(float)
    asc = bool(_int_arg(ctx, a, 1, 0))
    g = _groups(ctx, a, 2)
    if g is None:
        return v.rank(method="min", ascending=asc)
    return v.groupby(g.to_numpy(), sort=False).rank(method="min", ascending=asc)


FUNCTIONS.update({
    "ÇOKEĞERORTALAMA": _f_ifs_agg("mean", "ÇOKEĞERORTALAMA"), "MAKEĞER": _f_ifs_agg("max", "MAKEĞER"),
    "MİNEĞER": _f_ifs_agg("min", "MİNEĞER"),
    "SOLDAN": lambda c, a: _slice_text(c, a, "left"), "SAĞDAN": lambda c, a: _slice_text(c, a, "right"),
    "PARÇAAL": lambda c, a: _slice_text(c, a, "mid"),
    "BUL": _find(True), "MBUL": _find(False), "DEĞİŞTİR": _f_replace_at, "YİNELE": _f_rept,
    "METİNBİRLEŞTİR": _f_textjoin, "ÖZDEŞ": _f_exact,
    "ESAYIYSA": _f_isnumber, "EMETİNSE": _f_istext, "SEÇ": _f_choose,
    "KAREKÖK": lambda c, a: np.sqrt(c.series(c.num(a[0])).astype(float).where(lambda x: x >= 0)),
    "ÇARPIM": lambda c, a: _rowwise(c, a, lambda f: f.prod(axis=1, min_count=1)),
    "ORTANCA": lambda c, a: _rowwise(c, a, lambda f: f.median(axis=1)),
    "BAĞ_DEĞ_SAY": _rowcount(True), "BAĞ_DEĞ_DOLU_SAY": _rowcount(False),
    "ZAMAN": _f_time, "SERİTARİH": lambda c, a: _months(c, a, "SERİTARİH", False),
    "SERİAY": lambda c, a: _months(c, a, "SERİAY", True),
    "İŞGÜNÜ": lambda c, a: _busday(c, a, "İŞGÜNÜ", False), "TAMİŞGÜNÜ": lambda c, a: _busday(c, a, "TAMİŞGÜNÜ", True),
    "ETARİHLİ": _f_datedif,
    "TARİHSAYISI": lambda c, a: _dt(a[0], c, "TARİHSAYISI").dt.normalize(),
    # satırlar arası (mevcut satır sırasına göre)
    "ÖNCEKİ": _shift(1), "SONRAKİ": _shift(-1), "KÜMÜLATİF": _f_cumulative, "SIRA": _f_rank,
})
TABLE_ARG.update({"ÇOKEĞERORTALAMA": 0, "AVERAGEIFS": 0, "MAKEĞER": 0, "MAXIFS": 0, "MİNEĞER": 0, "MINIFS": 0})

_ALIASES = {
    "ROUNDUP": "YUKARIYUVARLA", "ROUNDDOWN": "AŞAĞIYUVARLA", "ABS": "MUTLAK", "INT": "TAMSAYI", "MAX": "MAK",
    "MIN": "MİN", "SUM": "TOPLA", "AVERAGE": "ORTALAMA", "VALUE": "SAYIYAÇEVİR", "LEFT": "SOLDAN",
    "RIGHT": "SAĞDAN", "MID": "PARÇAAL", "LEN": "UZUNLUK", "TRIM": "KIRP", "UPPER": "BÜYÜKHARF",
    "LOWER": "KÜÇÜKHARF", "PROPER": "YAZIMDÜZENİ", "CONCAT": "BİRLEŞTİR", "CONCATENATE": "BİRLEŞTİR",
    "ARALIKBİRLEŞTİR": "BİRLEŞTİR", "SUBSTITUTE": "YERİNEKOY", "YEAR": "YIL", "MONTH": "AY", "DAY": "GÜN",
    "HOUR": "SAAT", "MINUTE": "DAKİKA", "WEEKDAY": "HAFTANINGÜNÜ", "ISOWEEKNUM": "HAFTASAY", "TODAY": "BUGÜN",
    "NOW": "ŞİMDİ", "DATE": "TARİH",
    "VLOOKUP": "DÜŞEYARA", "XLOOKUP": "ÇAPRAZARA", "COUNTIF": "EĞERSAY", "COUNTIFS": "ÇOKEĞERSAY",
    "SUMIF": "ETOPLA", "SUMIFS": "ÇOKETOPLA", "AVERAGEIF": "ORTALAMAEĞER", "IFS": "ÇOKEĞER", "TEXT": "METNEÇEVİR",
    "EĞERYOKSA": "EĞERHATA", "IFNA": "EĞERHATA",
    "IF": "EĞER", "AND": "VE", "OR": "YADA", "NOT": "DEĞİL", "IFERROR": "EĞERHATA", "ISBLANK": "EBOŞSA",
    "ROUND": "YUVARLA",
    "AVERAGEIFS": "ÇOKEĞERORTALAMA", "MAXIFS": "MAKEĞER", "MINIFS": "MİNEĞER", "FIND": "BUL", "SEARCH": "MBUL",
    "REPLACE": "DEĞİŞTİR", "REPT": "YİNELE", "TEXTJOIN": "METİNBİRLEŞTİR", "EXACT": "ÖZDEŞ", "ISNUMBER": "ESAYIYSA",
    "ISTEXT": "EMETİNSE", "CHOOSE": "SEÇ", "SQRT": "KAREKÖK", "PRODUCT": "ÇARPIM", "MEDIAN": "ORTANCA",
    "COUNT": "BAĞ_DEĞ_SAY", "COUNTA": "BAĞ_DEĞ_DOLU_SAY", "TIME": "ZAMAN", "EDATE": "SERİTARİH",
    "EOMONTH": "SERİAY", "WORKDAY": "İŞGÜNÜ", "NETWORKDAYS": "TAMİŞGÜNÜ", "DATEDIF": "ETARİHLİ",
    "DATEVALUE": "TARİHSAYISI", "RANK": "SIRA", "RANK.EQ": "SIRA", "RANK.EŞİT": "SIRA",
    "PREVIOUS": "ÖNCEKİ", "CUMULATIVE": "KÜMÜLATİF",
}
for _k, _v in _ALIASES.items():
    FUNCTIONS[_k] = FUNCTIONS[_v]
CONSTANTS = {"DOĞRU": True, "TRUE": True, "YANLIŞ": False, "FALSE": False}

# Arayüzde gösterilen yardım (ad, kullanım, açıklama)
FUNCTION_HELP = [
    ("EĞER", "EĞER(koşul; doğruysa; yanlışsa)", "Koşula göre iki değerden birini verir"),
    ("ÇOKEĞER", "ÇOKEĞER(k1; d1; k2; d2; …)", "İlk doğru koşulun değeri (iç içe EĞER yerine)"),
    ("DÜŞEYARA", "DÜŞEYARA([Personel No]; \"Personel\"; \"Ekip Lideri\"; 0)",
     "Başka tablonun İLK sütununda arar, istenen sütunu (ad veya sıra no) getirir"),
    ("ÇAPRAZARA", "ÇAPRAZARA([Kod]; \"Ürünler\"; \"Ürün Kodu\"; \"Kategori\"; \"Yok\")",
     "Belirtilen anahtar sütunda arar; bulunamazsa son değer"),
    ("EĞERSAY / ÇOKEĞERSAY", "EĞERSAY(\"BU\"; \"Personel No\"; [Personel No])",
     "Koşula uyan satır sayısı; \"BU\" içinde bulunulan tablo. Ölçüt \">5\", \"<>İptal\", \"A*\" olabilir"),
    ("ETOPLA / ÇOKETOPLA", "ETOPLA(\"BU\"; \"Ekip\"; [Ekip]; \"Toplanan\")", "Koşula uyan satırların toplamı"),
    ("ORTALAMAEĞER", "ORTALAMAEĞER(\"BU\"; \"Ekip\"; [Ekip]; \"Süre\")", "Koşula uyan satırların ortalaması"),
    ("TABLOTOPLA / TABLOSAY / TABLOORT", "[Toplanan] / TABLOTOPLA(\"BU\"; \"Toplanan\")",
     "Bir sütunun tablo genelinde toplamı (pay hesabı); TABLOMAK, TABLOMİN de var"),
    ("METNEÇEVİR", "METNEÇEVİR([Oran]; \"0,0%\")", "Sayı/tarihi biçimli metne çevirir (\"gg.aa.yyyy\")"),
    ("VE / YADA / DEĞİL", "VE(k1; k2; …)", "Koşulları birleştirir"),
    ("EĞERHATA", "EĞERHATA(değer; yerine)", "Boş veya hatalıysa (örn. sıfıra bölme) yerine değeri verir"),
    ("EBOŞSA", "EBOŞSA([Sütun])", "Hücre boşsa DOĞRU"),
    ("YUVARLA", "YUVARLA(sayı; basamak)", "Excel gibi yuvarlar; YUKARIYUVARLA, AŞAĞIYUVARLA da var"),
    ("MUTLAK / TAMSAYI / MOD", "MOD(sayı; bölen)", "Sayı işlemleri"),
    ("MAK / MİN / TOPLA / ORTALAMA", "MAK([A]; [B]; 0)", "Aynı satırdaki değerler arasında"),
    ("SOLDAN / SAĞDAN / PARÇAAL", "PARÇAAL([Lokasyon]; 3; 2)", "Metnin bir kısmını alır"),
    ("UZUNLUK / KIRP", "KIRP([Ad])", "Metin uzunluğu / fazla boşlukları siler"),
    ("BÜYÜKHARF / KÜÇÜKHARF / YAZIMDÜZENİ", "BÜYÜKHARF([Ad])", "Türkçe kurallarla harf düzeni"),
    ("BİRLEŞTİR / YERİNEKOY", "YERİNEKOY([Kod]; \"-\"; \"\")", "Metin birleştirme / değiştirme"),
    ("SAYIYAÇEVİR", "SAYIYAÇEVİR([Miktar])", "Metni sayıya çevirir"),
    ("YIL / AY / GÜN / SAAT / DAKİKA", "SAAT([İşlem Zamanı])", "Tarihin parçası"),
    ("HAFTANINGÜNÜ / HAFTASAY", "HAFTANINGÜNÜ([Tarih]; 2)", "2: pazartesi=1"),
    ("BUGÜN / ŞİMDİ / TARİH", "TARİH(2026; 11; 10)", "Tarih üretir"),
    ("ÇOKEĞERORTALAMA / MAKEĞER / MİNEĞER", "MAKEĞER(\"BU\"; \"Süre\"; \"Ekip\"; [Ekip])",
     "Koşula uyan satırların ortalaması / en büyüğü / en küçüğü"),
    ("BUL / MBUL", "SOLDAN([Lokasyon]; BUL(\"-\"; [Lokasyon]) - 1)",
     "Metnin içindeki konum (MBUL harf duyarsız); bulunamazsa boş"),
    ("DEĞİŞTİR / YİNELE", "DEĞİŞTİR([Kod]; 1; 2; \"TR\")", "Belirli konumdaki karakterleri değiştirir / tekrarlar"),
    ("METİNBİRLEŞTİR", "METİNBİRLEŞTİR(\" - \"; DOĞRU; [Bölge]; [Koridor])", "Ayraçla birleştirir, boşları atlar"),
    ("ÖZDEŞ", "ÖZDEŞ([Kod]; \"A1\")", "Harf ve boşluk dahil birebir aynı mı"),
    ("ESAYIYSA / EMETİNSE", "ESAYIYSA([Miktar])", "Değer sayı mı / metin mi"),
    ("SEÇ", "SEÇ(HAFTANINGÜNÜ([Tarih]; 2); \"Pzt\"; \"Sal\"; …)", "Sıra numarasına göre değer seçer"),
    ("KAREKÖK / ÇARPIM / ORTANCA", "ÇARPIM([Adet]; [Birim])", "Satırdaki değerlerle"),
    ("BAĞ_DEĞ_SAY / BAĞ_DEĞ_DOLU_SAY", "BAĞ_DEĞ_DOLU_SAY([A]; [B]; [C])", "Satırdaki sayı / dolu hücre sayısı"),
    ("ZAMAN", "[Tarih] + ZAMAN(8; 0; 0)", "Saat:dakika:saniye (gün kesri olarak)"),
    ("SERİTARİH / SERİAY", "SERİAY([Tarih]; 0)", "N ay sonrası / o ayın son günü"),
    ("İŞGÜNÜ / TAMİŞGÜNÜ", "TAMİŞGÜNÜ([Sipariş]; [Teslim])", "Hafta sonu hariç gün (tatiller hariç değil)"),
    ("ETARİHLİ", "ETARİHLİ([Giriş]; BUGÜN(); \"Y\")", "İki tarih arası tam yıl/ay/gün"),
    ("TARİHSAYISI", "TARİHSAYISI(\"10.11.2026\")", "Metni tarihe çevirir"),
    ("ÖNCEKİ / SONRAKİ", "[Sayaç] - ÖNCEKİ([Sayaç]; 1; [Personel No])",
     "Önceki/sonraki satırın değeri (Excel'deki =D3-D2); grup verilirse grup içinde"),
    ("KÜMÜLATİF", "KÜMÜLATİF([Toplanan]; [Personel No])", "Yürüyen toplam; KÜMÜLATİF(1; [Kod]) kaçıncı tekrar"),
    ("SIRA", "SIRA([Toplanan]; 0; [Ekip])", "Sıralama (1 = en büyük); grup içinde de olabilir"),
]


def _fname(name: str) -> str:
    """'eğer', 'EĞER', 'if', 'IF' hepsi tanınsın."""
    for cand in (tr_upper(name), name.upper()):
        if cand in FUNCTIONS or cand in CONSTANTS:
            return cand
    return tr_upper(name)


class _Parser:
    def __init__(self, toks, ctx):
        self.toks, self.i, self.ctx = toks, 0, ctx

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def is_op(self, *ops):
        t = self.peek()
        return t is not None and t.kind == "op" and t.value in ops

    def parse(self):
        try:
            v = self.comparison()
            if self.peek() is not None:
                t = self.peek()
                hint = " (iki değer arasında işaret veya ';' eksik olabilir)" if t.kind in ("col", "num", "str", "name") else ""
                raise formula_error(f"Formülde beklenmeyen öğe: '{t.value}'{hint}", t.pos)
            return v
        except ShiftFlowError as exc:
            if getattr(exc, "pos", None) is None:
                t = self.toks[min(max(self.i - 1, 0), len(self.toks) - 1)] if self.toks else None
                exc.pos = t.pos if t is not None else None
            raise

    def comparison(self):
        v = self.concat()
        while self.is_op("=", "<>", "<", ">", "<=", ">="):
            op = self.take().value
            v = _compare(v, self.concat(), op, self.ctx)
        return v

    def concat(self):
        v = self.additive()
        while self.is_op("&"):
            self.take()
            r = self.additive()
            v = _text_series(v, self.ctx.index) + _text_series(r, self.ctx.index)
        return v

    def additive(self):
        v = self.term()
        while self.is_op("+", "-"):
            op = self.take().value
            v = _arith(v, self.term(), op, self.ctx)
        return v

    def term(self):
        v = self.power()
        while self.is_op("*", "/"):
            op = self.take().value
            v = _arith(v, self.power(), op, self.ctx)
        return v

    def power(self):
        v = self.unary()
        while self.is_op("^"):
            self.take()
            v = _arith(v, self.unary(), "^", self.ctx)
        return v

    def unary(self):
        if self.is_op("-"):
            self.take()
            return -self.ctx.num(self.unary())
        if self.is_op("+"):
            self.take()
            return self.ctx.num(self.unary())
        return self.atom()

    def atom(self):
        t = self.take()
        if t is None:
            raise ShiftFlowError("Formül eksik bitiyor (örn. son işaretten sonra değer yok).")
        if t.kind == "num":
            return float(t.value)
        if t.kind == "str":
            return str(t.value)
        if t.kind == "col":
            if t.value not in self.ctx.df.columns:
                raise MissingColumnError([t.value], self.ctx.df.columns, self.ctx.label)
            return self.ctx.df[t.value]
        if t.kind == "param":
            params = self.ctx.params
            key = next((k for k in params if tr_lower(k) == tr_lower(t.value)), None)
            if key is None:
                known = ", ".join("{" + k + "}" for k in params) or "henüz parametre yok"
                raise formula_error(f"'{{{t.value}}}' parametresi tanımlı değil ({known}). "
                                    "Parametreler: Dosya → Parametreler.", t.pos)
            return params[key]
        if t.kind == "name":
            name = _fname(t.value)
            if name in CONSTANTS and not self.is_op("("):
                return CONSTANTS[name]
            if name not in FUNCTIONS:
                raise ShiftFlowError(f"Bilinmeyen fonksiyon: {t.value}. Sütun adıysa köşeli parantez kullanın: [{t.value}]")
            if not self.is_op("("):
                raise ShiftFlowError(f"{t.value} fonksiyonundan sonra parantez bekleniyor.")
            self.take()
            args = []
            if not self.is_op(")"):
                args.append(self.comparison())
                while self.is_op(";"):
                    self.take()
                    args.append(self.comparison())
            c = self.take()
            if c is None or c.value != ")":
                raise ShiftFlowError(f"{t.value}(…) parantezi kapanmamış.")
            try:
                return FUNCTIONS[name](self.ctx, args)
            except ShiftFlowError:
                raise
            except IndexError:
                raise ShiftFlowError(f"{t.value}: bağımsız değişken eksik.") from None
            except Exception as exc:
                raise ShiftFlowError(f"{t.value} hesaplanamadı: {exc}") from exc
        if t.value == "(":
            v = self.comparison()
            c = self.take()
            if c is None or c.value != ")":
                raise ShiftFlowError("Formülde kapanmayan parantez var.")
            return v
        raise ShiftFlowError(f"Formülde beklenmeyen işaret: '{t.value}'")


def evaluate(expr: str, df: pd.DataFrame, step_label: str = "", tables: dict | None = None,
             notes: list | None = None, params: dict | None = None) -> tuple[pd.Series, int]:
    """İfadeyi hesaplar. (sonuç serisi, sıfıra bölme sayısı) döner.

    tables: formülün DÜŞEYARA/EĞERSAY gibi fonksiyonlarla başvurduğu tablolar {ad: tablo}.
    notes: verilirse, hesaplama notları (bulunamayan anahtar vb.) buna eklenir.
    """
    tables = dict(tables or {})
    params = dict(params or tables.pop("__params__", None) or {})
    ctx = _Ctx(df, step_label, tables)
    ctx.params = params
    check_parentheses(expr)
    v = _Parser(tokenize(expr), ctx).parse()
    if not isinstance(v, pd.Series):
        v = pd.Series([v] * len(df), index=df.index)
    elif not v.index.equals(df.index):
        v = pd.Series(np.asarray(v), index=df.index)
    if pd.api.types.is_float_dtype(v):
        v = v.where(~np.isinf(v), np.nan)
    # EĞER/EĞERHATA ile korunmuş bölmelerde uyarı verme: sonuçta boş yoksa sorun yok.
    div0 = ctx.div_zero if v.isna().any() else 0
    if notes is not None:
        has_empty = bool(v.isna().any())
        for n in ctx.notes:
            # EĞERHATA/EĞER ile korunmuş aramalar: sonuçta boş kalmadıysa uyarmaya gerek yok.
            if "karşılığı" in n and not has_empty:
                continue
            if n not in notes:
                notes.append(n)
    return v, div0


def referenced_params(expr: str) -> list[str]:
    try:
        return [t.value for t in tokenize(expr) if t.kind == "param"]
    except ShiftFlowError:
        return []
