"""Excel formülünü ShiftFlow formülüne çevirir.

Excel'de formül hücre adresleriyle yazılır (C2, Personel!A:C); ShiftFlow'da
sütun ve tablo adlarıyla ([Toplanan], "Personel"). Çevirici:

- Aynı satırdaki hücre başvurularını (C2, $C2) sütun adına çevirir: [Toplanan].
- Başka sayfaya/sütun aralığına bakan fonksiyonları tablo fonksiyonlarına çevirir:
    DÜŞEYARA(B2;Personel!A:C;3;0)          -> ÇAPRAZARA([Personel No]; "Personel"; "Personel No"; "Ekip Lideri")
    İNDİS(P!C:C;KAÇINCI(B2;P!A:A;0))        -> ÇAPRAZARA(...)
    ÇAPRAZARA(B2;P!A:A;P!C:C;"Yok")         -> ÇAPRAZARA(...; "Yok")
    EĞERSAY(B:B;B2)                         -> EĞERSAY("BU"; "Personel No"; [Personel No])
    ETOPLA / ÇOKETOPLA / ÇOKEĞERSAY / ORTALAMAEĞER benzer
    TOPLA(E:E), MAK(E2:E500)                 -> TABLOTOPLA("BU"; "Toplanan"), TABLOMAK(...)
    TOPLA(D2:F2)                             -> TOPLA([D]; [E]; [F])   (aynı satırdaki aralık)
- Türkçe (; ayırıcı) ve İngilizce (, ayırıcı) Excel yazımını tanır; İngilizce
  fonksiyon adlarını Türkçeye çevirir. "_xlfn." öneklerini atar.
- Çevrilemeyenleri (sabit hücre $H$1, başka satıra başvuru, DOLAYLI, KAYDIR…)
  uyarı olarak bildirir; formülü tahminle tamamlamaz.

Harf -> sütun eşlemesi: Rapor sayfasında A sütunu ShiftFlow tablosunun ilk
sütunudur (başlangıç harfi değiştirilebilir).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .errors import ShiftFlowError
from .values import tr_upper

# Excel adı -> ShiftFlow adı (Türkçe Excel adları çoğunlukla aynıdır)
NAME_MAP = {
    "IF": "EĞER", "IFS": "ÇOKEĞER", "AND": "VE", "OR": "YADA", "NOT": "DEĞİL", "IFERROR": "EĞERHATA",
    "IFNA": "EĞERHATA", "EĞERYOKSA": "EĞERHATA", "ISBLANK": "EBOŞSA", "ROUND": "YUVARLA", "ROUNDUP": "YUKARIYUVARLA",
    "ROUNDDOWN": "AŞAĞIYUVARLA", "ABS": "MUTLAK", "INT": "TAMSAYI", "MOD": "MOD", "MAX": "MAK", "MIN": "MİN",
    "SUM": "TOPLA", "AVERAGE": "ORTALAMA", "VALUE": "SAYIYAÇEVİR", "LEFT": "SOLDAN", "RIGHT": "SAĞDAN",
    "MID": "PARÇAAL", "LEN": "UZUNLUK", "TRIM": "KIRP", "UPPER": "BÜYÜKHARF", "LOWER": "KÜÇÜKHARF",
    "PROPER": "YAZIMDÜZENİ", "CONCATENATE": "BİRLEŞTİR", "CONCAT": "BİRLEŞTİR", "ARALIKBİRLEŞTİR": "BİRLEŞTİR",
    "SUBSTITUTE": "YERİNEKOY", "YEAR": "YIL", "MONTH": "AY", "DAY": "GÜN", "HOUR": "SAAT", "MINUTE": "DAKİKA",
    "WEEKDAY": "HAFTANINGÜNÜ", "ISOWEEKNUM": "HAFTASAY", "ISOHAFTASAY": "HAFTASAY", "TODAY": "BUGÜN",
    "NOW": "ŞİMDİ", "DATE": "TARİH", "TEXT": "METNEÇEVİR", "VLOOKUP": "DÜŞEYARA", "XLOOKUP": "ÇAPRAZARA",
    "INDEX": "İNDİS", "MATCH": "KAÇINCI", "COUNTIF": "EĞERSAY", "COUNTIFS": "ÇOKEĞERSAY", "SUMIF": "ETOPLA",
    "SUMIFS": "ÇOKETOPLA", "AVERAGEIF": "ORTALAMAEĞER", "COUNT": "BAĞ_DEĞ_SAY", "COUNTA": "BAĞ_DEĞ_DOLU_SAY",
    "TRUE": "DOĞRU", "FALSE": "YANLIŞ",
    "AVERAGEIFS": "ÇOKEĞERORTALAMA", "MAXIFS": "MAKEĞER", "MINIFS": "MİNEĞER", "FIND": "BUL", "SEARCH": "MBUL",
    "REPLACE": "DEĞİŞTİR", "REPT": "YİNELE", "TEXTJOIN": "METİNBİRLEŞTİR", "EXACT": "ÖZDEŞ", "ISNUMBER": "ESAYIYSA",
    "ISTEXT": "EMETİNSE", "CHOOSE": "SEÇ", "SQRT": "KAREKÖK", "PRODUCT": "ÇARPIM", "MEDIAN": "ORTANCA",
    "TIME": "ZAMAN", "EDATE": "SERİTARİH", "EOMONTH": "SERİAY", "WORKDAY": "İŞGÜNÜ", "NETWORKDAYS": "TAMİŞGÜNÜ",
    "DATEDIF": "ETARİHLİ", "DATEVALUE": "TARİHSAYISI", "ÇOKEĞERORTALAMA": "ÇOKEĞERORTALAMA",
    "RANK": "SIRA", "RANK.EQ": "SIRA", "RANK.EŞİT": "SIRA",
}
UNSUPPORTED = {"DOLAYLI", "INDIRECT", "KAYDIR", "OFFSET", "HÜCRE", "CELL", "SATIR", "ROW", "SÜTUN", "COLUMN",
               "ALTTOPLAM", "SUBTOTAL", "TOPLAMA", "AGGREGATE", "ETOPLA.ÇARPIM", "TOPLA.ÇARPIM", "SUMPRODUCT",
               "FİLTRE", "FILTER", "BENZERSİZ", "UNIQUE", "SIRALA", "SORT", "LET", "LAMBDA"}
TABLE_AGG = {"TOPLA": "TABLOTOPLA", "ORTALAMA": "TABLOORT", "MAK": "TABLOMAK", "MİN": "TABLOMİN",
             "BAĞ_DEĞ_SAY": "TABLOSAY", "BAĞ_DEĞ_DOLU_SAY": "TABLOSAY"}

_REF = r"\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?\d+:\$?\d+"
_TOKEN = re.compile(
    r"\s*(?:"
    r"(\"(?:[^\"]|\"\")*\")"                                                       # 1 metin
    r"|((?:'(?:[^']|'')+'|[A-Za-zÇĞİÖŞÜçğıöşü_][\w.ÇĞİÖŞÜçğıöşü]*)!(?:" + _REF + r"))"  # 2 sayfalı başvuru
    r"|(" + _REF + r")(?![\w(])"                                                    # 3 başvuru
    r"|(\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)"                                          # 4 sayı
    r"|((?:_xlfn\.|_xlws\.)?[A-Za-zÇĞİÖŞÜçğıöşü_][\w.ÇĞİÖŞÜçğıöşü]*)"                  # 5 ad
    r"|(<>|<=|>=|[-+*/^&=<>%(),;])"                                                 # 6 işaret
    r")"
)


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(i: int) -> str:
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def letter_map(columns, start: str = "A") -> dict:
    """{'A': 'Tarih', 'B': 'Personel No', ...} — tablo `start` sütunundan başlıyorsa kaydırır."""
    s = col_index(start or "A")
    return {col_letter(s + i): str(c) for i, c in enumerate(columns)}


@dataclass
class Ref:
    sheet: str | None
    kind: str  # cell | area | cols | rows
    c1: str = ""
    r1: int | None = None
    c2: str = ""
    r2: int | None = None
    abs_row: bool = False
    text: str = ""


def _parse_ref(text: str) -> Ref:
    sheet = None
    if "!" in text:
        sheet, text = text.rsplit("!", 1)
        if sheet.startswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
    raw = text
    if re.fullmatch(r"\$?\d+:\$?\d+", text):
        return Ref(sheet, "rows", text=raw)
    m = re.fullmatch(r"(\$?)([A-Za-z]{1,3}):(\$?)([A-Za-z]{1,3})", text)
    if m:
        return Ref(sheet, "cols", m.group(2).upper(), None, m.group(4).upper(), None, text=raw)
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})(\$?)(\d+)(?::\$?([A-Za-z]{1,3})(\$?)(\d+))?", text)
    if not m:
        raise ShiftFlowError(f"Hücre başvurusu anlaşılamadı: {raw}")
    if m.group(4):
        return Ref(sheet, "area", m.group(1).upper(), int(m.group(3)), m.group(4).upper(), int(m.group(6)),
                   abs_row=bool(m.group(2)), text=raw)
    return Ref(sheet, "cell", m.group(1).upper(), int(m.group(3)), abs_row=bool(m.group(2)), text=raw)


def detect_separator(f: str) -> str:
    """Türkçe Excel ';' ayırıcı ve ',' ondalık kullanır; İngilizce ',' ayırıcı ve '.' ondalık."""
    outside = re.sub(r"\"(?:[^\"]|\"\")*\"", "", f)
    if ";" in outside:
        return ";"
    names = re.findall(r"([A-Za-zÇĞİÖŞÜçğıöşü_][\w.ÇĞİÖŞÜçğıöşü]*)\s*\(", outside)
    if not names:
        return ";"  # fonksiyon yok: virgül ancak ondalık olabilir (Türkçe yazım)
    english = {k for k in NAME_MAP if k.isascii()}
    if any(re.sub(r"^_xl(fn|ws)\.", "", n).upper() in english for n in names):
        return ","
    if any(not n.isascii() for n in names):
        return ";"
    return ","


def tokenize(formula: str):
    f = (formula or "").strip()
    if f.startswith("="):
        f = f[1:]
    sep = detect_separator(f)
    pos, out = 0, []
    while pos < len(f):
        m = _TOKEN.match(f, pos)
        if not m or m.end() == pos:
            rest = f[pos:].strip()
            if not rest:
                break
            raise ShiftFlowError(f"Excel formülü anlaşılamadı, şu kısımda: '{rest[:25]}'")
        s, sref, ref, num, name, op = m.groups()
        if s is not None:
            out.append(("str", s[1:-1].replace('""', '"')))
        elif sref or ref:
            out.append(("ref", _parse_ref(sref or ref)))
        elif num:
            if sep == ";":
                num = num.replace(",", ".")
            elif "," in num:  # İngilizce yazımda virgül ayırıcıdır; sayıyı geri böl
                a, b = num.split(",", 1)
                out.extend([("num", float(a)), ("op", ";"), ("num", float(b))])
                pos = m.end()
                continue
            out.append(("num", float(num)))
        elif name:
            out.append(("name", re.sub(r"^_xl(fn|ws)\.", "", name)))
        else:
            if op == ",":
                op = "," if sep == ";" else ";"
            out.append(("op", op))
        pos = m.end()
    return out, sep


# ---------------------------------------------------------------------- AST
class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tk = self.peek()
        self.i += 1
        return tk

    def is_op(self, *ops):
        k, v = self.peek()
        return k == "op" and v in ops

    def parse(self):
        n = self.cmp()
        if self.i < len(self.t):
            raise ShiftFlowError(f"Excel formülünde fazla karakter: {self.t[self.i][1]}")
        return n

    def cmp(self):
        n = self.cat()
        while self.is_op("=", "<>", "<", ">", "<=", ">="):
            n = ("bin", self.take()[1], n, self.cat())
        return n

    def cat(self):
        n = self.add()
        while self.is_op("&"):
            self.take()
            n = ("bin", "&", n, self.add())
        return n

    def add(self):
        n = self.mul()
        while self.is_op("+", "-"):
            n = ("bin", self.take()[1], n, self.mul())
        return n

    def mul(self):
        n = self.pw()
        while self.is_op("*", "/"):
            n = ("bin", self.take()[1], n, self.pw())
        return n

    def pw(self):
        n = self.un()
        while self.is_op("^"):
            self.take()
            n = ("bin", "^", n, self.un())
        return n

    def un(self):
        if self.is_op("-", "+"):
            return ("un", self.take()[1], self.un())
        n = self.prim()
        while self.is_op("%"):
            self.take()
            n = ("pct", n)
        return n

    def prim(self):
        k, v = self.take()
        if k == "num":
            return ("num", v)
        if k == "str":
            return ("str", v)
        if k == "ref":
            return ("ref", v)
        if k == "name":
            if self.is_op("("):
                self.take()
                args = []
                if not self.is_op(")"):
                    args.append(self.cmp() if not self.is_op(";") else ("empty",))
                    while self.is_op(";"):
                        self.take()
                        args.append(self.cmp() if not self.is_op(";", ")") else ("empty",))
                if not self.is_op(")"):
                    raise ShiftFlowError(f"{v}( … ) parantezi kapanmamış.")
                self.take()
                return ("func", v, args)
            return ("name", v)
        if k == "op" and v == "(":
            n = self.cmp()
            if not self.is_op(")"):
                raise ShiftFlowError("Excel formülünde kapanmayan parantez var.")
            self.take()
            return ("paren", n)
        raise ShiftFlowError(f"Excel formülünde beklenmeyen öğe: {v}")


# ---------------------------------------------------------------------- çeviri
@dataclass
class Translation:
    formula: str
    warnings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)
    current_row: int | None = None
    fixed_cells: list[str] = field(default_factory=list)  # parametre olabilecek sabit hücreler (H1)


def scan(formula: str) -> dict:
    """Formülde geçen sayfalar ve satır numaraları (eşleme penceresi için)."""
    toks, sep = tokenize(formula)
    sheets, rows = [], Counter()
    for k, v in toks:
        if k == "ref":
            if v.sheet and v.sheet not in sheets:
                sheets.append(v.sheet)
            if v.kind == "cell" and not v.sheet and not v.abs_row:
                rows[v.r1] += 1
    return {"sheets": sheets, "current_row": rows.most_common(1)[0][0] if rows else None, "separator": sep}


class Translator:
    def __init__(self, current: dict, sheets: dict | None = None, current_sheet: str | None = None,
                 current_row: int | None = None):
        """current: {harf: sütun} (formülün bulunduğu sayfa)
        sheets: {Excel sayfa adı: (veri kümesi adı veya None, {harf: sütun})}"""
        self.current, self.sheets = current, sheets or {}
        self.params: dict = {}  # {"H1": "Hedef Oran"}: sabit hücre → iş akışı parametresi
        self.fixed_cells: list[str] = []
        self.current_sheet = current_sheet
        self.row = current_row
        self.warn: list[str] = []
        self.tables: list[str] = []

    def w(self, text):
        if text not in self.warn:
            self.warn.append(text)

    # tablo/sütun çözümleme
    def _sheet(self, ref: Ref):
        if ref.sheet is None or ref.sheet == self.current_sheet:
            return "BU", self.current
        ds, cmap = self.sheets.get(ref.sheet, (None, {}))
        if not ds:
            self.w(f"'{ref.sheet}' sayfası bir ShiftFlow tablosuyla eşlenmedi.")
            return f"?{ref.sheet}", cmap
        if ds not in self.tables:
            self.tables.append(ds)
        return ds, cmap

    def _colname(self, letter, cmap, where):
        name = cmap.get(letter)
        if name is None:
            self.w(f"{where}: {letter} sütununun karşılığı yok (sayfadaki sütun sayısını veya başlangıç harfini kontrol edin).")
            return f"?{letter}"
        return name

    def _q(self, s: str) -> str:
        return '"' + str(s).replace('"', '""') + '"'

    def _col_of_range(self, node, fname, which=0):
        """Aralık düğümünden (tablo, sütun adı) — tek sütunluk aralık beklenir."""
        if node[0] != "ref" or node[1].kind not in ("cols", "area"):
            raise _Fallback(f"{fname}: sütun aralığı bekleniyordu")
        ref = node[1]
        table, cmap = self._sheet(ref)
        letter = ref.c1 if which == 0 else col_letter(col_index(ref.c1) + which)
        return table, self._colname(letter, cmap, fname)

    # düğüm -> metin
    def emit(self, n) -> str:
        k = n[0]
        if k == "num":
            v = n[1]
            return str(int(v)) if float(v).is_integer() else str(v).replace(".", ",")
        if k == "str":
            return self._q(n[1])
        if k == "empty":
            return '""'
        if k == "name":
            up = tr_upper(n[1])
            if up in ("DOĞRU", "TRUE") or n[1].upper() == "TRUE":
                return "DOĞRU"
            if up in ("YANLIŞ", "FALSE") or n[1].upper() == "FALSE":
                return "YANLIŞ"
            self.w(f"'{n[1]}' adı (tanımlı ad olabilir) çevrilemedi.")
            return f"[?{n[1]}]"
        if k == "paren":
            return "(" + self.emit(n[1]) + ")"
        if k == "pct":
            return "(" + self.emit(n[1]) + " / 100)"
        if k == "un":
            return n[1] + self.emit(n[2])
        if k == "bin":
            return f"{self.emit(n[2])} {n[1]} {self.emit(n[3])}"
        if k == "ref":
            return self.emit_ref(n[1])
        if k == "func":
            return self.emit_func(n[1], n[2])
        raise ShiftFlowError(f"Çevrilemeyen öğe: {n}")

    def emit_ref(self, ref: Ref) -> str:
        if ref.kind == "cell":
            if ref.sheet and ref.sheet != self.current_sheet:
                self.w(f"{ref.sheet}!{ref.text}: başka sayfadaki tek hücreye başvuru çevrilemez; "
                       "değeri sabit yazın veya bir tablo fonksiyonu (DÜŞEYARA vb.) kullanın.")
                return f"[?{ref.sheet}!{ref.text}]"
            key = ref.text.replace("$", "").upper()
            if key in self.params:
                return "{" + self.params[key] + "}"
            if not ref.abs_row and self.row is not None and ref.r1 != self.row and abs(ref.r1 - self.row) <= 50 \
                    and ref.c1 in self.current:
                d = ref.r1 - self.row
                fn = "ÖNCEKİ" if d < 0 else "SONRAKİ"
                col = f"[{self._colname(ref.c1, self.current, ref.text)}]"
                self.w(f"{ref.text}: {abs(d)} satır {'üstteki' if d < 0 else 'alttaki'} hücre → {fn}(); sonuç "
                       "satırların sırasına bağlıdır (gerekirse önce Sırala adımı ekleyin).")
                return f"{fn}({col})" if abs(d) == 1 else f"{fn}({col}; {abs(d)})"
            if ref.abs_row or (self.row is not None and ref.r1 != self.row):
                self.w(f"{ref.text}: sabit hücre (örn. hedef oranı gibi bir parametre hücresi). 'Parametre yap' ile "
                       "iş akışı parametresine bağlayın veya değeri formüle sabit yazın.")
                self.fixed_cells.append(key)
                return f"[?{ref.text}]"
            return f"[{self._colname(ref.c1, self.current, ref.text)}]"
        if ref.kind == "area" and ref.r1 == ref.r2 and (self.row is None or ref.r1 == self.row) and not ref.sheet:
            cols = [col_letter(i) for i in range(col_index(ref.c1), col_index(ref.c2) + 1)]
            return "; ".join(f"[{self._colname(c, self.current, ref.text)}]" for c in cols)
        self.w(f"{ref.text}: aralık bu konumda çevrilemez.")
        return f"[?{ref.text}]"

    def emit_func(self, name: str, args: list) -> str:
        up = tr_upper(name)
        up = NAME_MAP.get(name.upper(), NAME_MAP.get(up, up))
        try:
            special = self._special(up, args)
        except _Fallback as fb:
            self.w(f"{up}: {fb} — olduğu gibi bırakıldı, elle düzenleyin.")
            special = None
        if special is not None:
            return special
        if up in UNSUPPORTED:
            self.w(f"{up} fonksiyonunun ShiftFlow'da karşılığı yok.")
        from .expression import FUNCTIONS
        if up not in FUNCTIONS and up not in UNSUPPORTED and up not in ("İNDİS", "KAÇINCI"):
            self.w(f"{up} fonksiyonu ShiftFlow'da tanınmıyor.")
        return f"{up}(" + "; ".join(self.emit(a) for a in args) + ")"

    def _running(self, n) -> bool:
        """$D$2:D5 gibi: başı sabit, sonu bu satır olan tek sütunlu aralık (yürüyen toplam kalıbı)."""
        if n[0] != "ref":
            return False
        r = n[1]
        return (r.kind == "area" and not r.sheet and r.c1 == r.c2 and r.abs_row and self.row is not None
                and r.r2 == self.row and r.r1 < r.r2)

    def _is_range(self, n):
        return n[0] == "ref" and n[1].kind in ("cols", "area") and not (
            n[1].kind == "area" and n[1].r1 == n[1].r2 and not n[1].sheet)

    def _special(self, up, a):
        if up == "TOPLA" and len(a) == 1 and self._running(a[0]):
            return f"KÜMÜLATİF([{self._colname(a[0][1].c1, self.current, a[0][1].text)}])"
        if up == "EĞERSAY" and len(a) == 2 and self._running(a[0]):
            col = f"[{self._colname(a[0][1].c1, self.current, a[0][1].text)}]"
            if self.emit(a[1]) == col:
                return f"KÜMÜLATİF(1; {col})"  # kaçıncı tekrar (=EĞERSAY($A$2:A2;A2))
        if up == "DÜŞEYARA":
            if len(a) < 3 or not self._is_range(a[1]):
                raise _Fallback("ikinci bağımsız değişken bir aralık olmalı")
            if len(a) > 3 and self.emit(a[3]) not in ("0", "YANLIŞ"):
                self.w("DÜŞEYARA: yaklaşık eşleşme (DOĞRU/1) ShiftFlow'da tam eşleşme olarak çevrildi.")
            if a[2][0] != "num":
                raise _Fallback("sütun sıra numarası sabit olmalı")
            table, key = self._col_of_range(a[1], "DÜŞEYARA", 0)
            _, ret = self._col_of_range(a[1], "DÜŞEYARA", int(a[2][1]) - 1)
            return f"ÇAPRAZARA({self.emit(a[0])}; {self._q(table)}; {self._q(key)}; {self._q(ret)})"
        if up == "ÇAPRAZARA":
            if len(a) < 3:
                raise _Fallback("en az üç bağımsız değişken gerekir")
            t1, key = self._col_of_range(a[1], "ÇAPRAZARA")
            t2, ret = self._col_of_range(a[2], "ÇAPRAZARA")
            if t1 != t2:
                raise _Fallback("arama ve sonuç aralıkları aynı sayfada olmalı")
            extra = f"; {self.emit(a[3])}" if len(a) > 3 and a[3][0] != "empty" else ""
            if len(a) > 4:
                self.w("ÇAPRAZARA: eşleşme modu/arama modu bağımsız değişkenleri yok sayıldı (tam eşleşme).")
            return f"ÇAPRAZARA({self.emit(a[0])}; {self._q(t1)}; {self._q(key)}; {self._q(ret)}{extra})"
        if up == "İNDİS":
            if len(a) >= 2 and a[1][0] == "func" and NAME_MAP.get(a[1][1].upper(), tr_upper(a[1][1])) == "KAÇINCI":
                m = a[1][2]
                if len(m) >= 3 and self.emit(m[2]) not in ("0",):
                    self.w("KAÇINCI: yaklaşık eşleşme tam eşleşme olarak çevrildi.")
                t1, key = self._col_of_range(m[1], "KAÇINCI")
                offset = int(a[2][1]) - 1 if len(a) > 2 and a[2][0] == "num" else 0
                t2, ret = self._col_of_range(a[0], "İNDİS", offset)
                if t1 != t2:
                    raise _Fallback("İNDİS ve KAÇINCI aralıkları aynı sayfada olmalı")
                return f"ÇAPRAZARA({self.emit(m[0])}; {self._q(t1)}; {self._q(key)}; {self._q(ret)})"
            raise _Fallback("yalnızca İNDİS(aralık; KAÇINCI(…; aralık; 0)) kalıbı çevrilebilir")
        if up == "EĞERSAY":
            t, c = self._col_of_range(a[0], "EĞERSAY")
            return f"EĞERSAY({self._q(t)}; {self._q(c)}; {self._crit(a[1])})"
        if up in ("ÇOKEĞERSAY",):
            parts, table = [], None
            for i in range(0, len(a), 2):
                t, c = self._col_of_range(a[i], up)
                if table and t != table:
                    raise _Fallback("tüm aralıklar aynı sayfada olmalı")
                table = t
                parts += [self._q(c), self._crit(a[i + 1])]
            return f"ÇOKEĞERSAY({self._q(table)}; " + "; ".join(parts) + ")"
        if up in ("ETOPLA", "ORTALAMAEĞER"):
            t, c = self._col_of_range(a[0], up)
            target = c
            if len(a) > 2:
                t2, target = self._col_of_range(a[2], up)
                if t2 != t:
                    raise _Fallback("aralıklar aynı sayfada olmalı")
            return f"{up}({self._q(t)}; {self._q(c)}; {self._crit(a[1])}; {self._q(target)})"
        if up in ("ÇOKETOPLA", "ÇOKEĞERORTALAMA", "MAKEĞER", "MİNEĞER"):
            t, s = self._col_of_range(a[0], up)
            parts = []
            for i in range(1, len(a), 2):
                t2, c = self._col_of_range(a[i], up)
                if t2 != t:
                    raise _Fallback("tüm aralıklar aynı sayfada olmalı")
                parts += [self._q(c), self._crit(a[i + 1])]
            return f"{up}({self._q(t)}; {self._q(s)}; " + "; ".join(parts) + ")"
        if up == "SIRA":
            if len(a) < 2:
                raise _Fallback("SIRA(değer; aralık; [sıra]) en az iki bağımsız değişken alır")
            t, c = self._col_of_range(a[1], "SIRA")
            if t not in ("BU", None) and t != self.current_sheet:
                raise _Fallback("başka sayfadaki aralıkta sıralama çevrilemez")
            v = self.emit(a[0])
            if v != f"[{c}]":
                raise _Fallback("yalnız satırın kendi değerinin sırası çevrilebilir")
            order = self.emit(a[2]) if len(a) > 2 else "0"
            return f"SIRA({v}; {order})"
        if up in TABLE_AGG and len(a) == 1 and self._is_range(a[0]):
            t, c = self._col_of_range(a[0], up)
            return f"{TABLE_AGG[up]}({self._q(t)}; {self._q(c)})"
        if up in TABLE_AGG and any(self._is_range(x) for x in a):
            raise _Fallback("birden çok aralığın toplamı çevrilemez")
        if up in ("BAĞ_DEĞ_SAY", "BAĞ_DEĞ_DOLU_SAY") and any(self._is_range(x) for x in a):
            raise _Fallback("yalnızca tek sütun aralığı desteklenir")
        return None

    def _crit(self, n) -> str:
        if n[0] == "bin" and n[1] == "&" and n[2][0] == "str" and re.match(r"^(<>|>=|<=|=|<|>)$", n[2][1] or ""):
            self.w("Satıra bağlı karşılaştırmalı ölçüt (\">\"&C2) desteklenmiyor; yalnızca eşitlik veya sabit ölçüt.")
        return self.emit(n)


class _Fallback(Exception):
    pass


def translate(formula: str, current: dict, sheets: dict | None = None, current_sheet: str | None = None,
              current_row: int | None = None, params: dict | None = None) -> Translation:
    """params: {"H1": "Hedef Oran"} — sabit hücreleri iş akışı parametresine bağlar ({Hedef Oran})."""
    toks, _sep = tokenize(formula)
    info = scan(formula)
    row = current_row if current_row is not None else info["current_row"]
    tr = Translator(current, sheets, current_sheet, row)
    tr.params = {k.replace("$", "").upper(): v for k, v in (params or {}).items()}
    ast = _P(toks).parse()
    text = tr.emit(ast)
    t = Translation(text, tr.warn, tr.tables, info["sheets"], row)
    t.fixed_cells = list(dict.fromkeys(tr.fixed_cells))
    return t


# ---------------------------------------------------------------------- formüllü sütunlar
@dataclass
class FormulaColumn:
    name: str  # başlık (sütun adı)
    letter: str  # Excel sütun harfi
    excel: str  # Excel'deki formül (ilk veri satırı)
    formula: str = ""  # ShiftFlow karşılığı
    warnings: list = field(default_factory=list)
    tables: list = field(default_factory=list)  # başvurulan diğer sayfalar
    same_in_next_rows: bool = True  # sonraki satırlarda aynı formül kalıbı mı
    fixed_cells: list = field(default_factory=list)  # parametre olabilecek sabit hücreler


def _r1c1(formula: str, row: int) -> str:
    """Formülü satırdan bağımsız hâle getirir: göreli satır numaraları {+0} olur (kalıp karşılaştırma)."""
    def sub(m):
        if m.group(3):  # $ ile sabit satır
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{{{int(m.group(4)) - row:+d}}}"
    return re.sub(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)", sub, formula)


def find_formula_columns(grid, columns, sheets: dict | None = None, current_sheet: str | None = None,
                         params: dict | None = None):
    """Açık Excel/dosyadaki tablonun formüllü sütunlarını bulur ve çevirir.

    grid: excel_live.FormulaGrid; columns: veri kümesindeki sütun adları (başlık satırını bulmak için).
    Döner: (başlık satırının Excel numarası, [FormulaColumn])"""
    want = {str(c).strip() for c in columns}
    best, best_i = 0, None
    for i, row in enumerate(grid.rows):
        hits = sum(1 for v in row if isinstance(v, str) and v.strip() in want)
        if hits > best:
            best, best_i = hits, i
    if best_i is None or best < max(1, min(len(want), 2)):
        raise ShiftFlowError("Excel sayfasında bu tablonun başlık satırı bulunamadı.")
    header = grid.rows[best_i]
    names = {}
    for j, v in enumerate(header):
        if v is not None and str(v).strip():
            names[col_letter(grid.first_col + j)] = str(v).strip()
    data = [(k, r) for k, r in enumerate(grid.rows[best_i + 1:], start=best_i + 1) if any(x is not None for x in r)]
    if not data:
        return grid.first_row + best_i, []
    k0, first = data[0]
    excel_row = grid.first_row + k0
    out = []
    for j, v in enumerate(first):
        if not (isinstance(v, str) and v.startswith("=")):
            continue
        letter = col_letter(grid.first_col + j)
        name = names.get(letter)
        if not name:
            continue
        fc = FormulaColumn(name=name, letter=letter, excel=v)
        pattern = _r1c1(v, excel_row)
        for k, r in data[1:4]:
            nv = r[j] if j < len(r) else None
            if isinstance(nv, str) and nv.startswith("=") and _r1c1(nv, grid.first_row + k) != pattern:
                fc.same_in_next_rows = False
        try:
            t = translate(v, names, sheets or {}, current_sheet, excel_row, params=params)
            fc.formula, fc.warnings, fc.tables = t.formula, list(t.warnings), list(t.tables)
            fc.fixed_cells = list(t.fixed_cells)
        except ShiftFlowError as exc:
            fc.warnings = [exc.message]
        if not fc.same_in_next_rows:
            fc.warnings.append("Alttaki satırlarda formül farklı; yalnız ilk satırın formülü alındı.")
        out.append(fc)
    return grid.first_row + best_i, out


# ---------------------------------------------------------------------- Excel'e bırak
# Türkçe Excel adı -> İngilizce (dosyaya formül İngilizce yazılır; Excel kendi dilinde gösterir)
_TR_EN_EXTRA = {
    "DOLAYLI": "INDIRECT", "KAYDIR": "OFFSET", "HÜCRE": "CELL", "SATIR": "ROW", "SÜTUN": "COLUMN",
    "ALTTOPLAM": "SUBTOTAL", "TOPLAMA": "AGGREGATE", "TOPLA.ÇARPIM": "SUMPRODUCT", "ETOPLA.ÇARPIM": "SUMPRODUCT",
    "FİLTRE": "_xlfn._xlws.FILTER", "BENZERSİZ": "_xlfn.UNIQUE", "SIRALA": "_xlfn._xlws.SORT",
    "İNDİS": "INDEX", "KAÇINCI": "MATCH", "YATAYARA": "HLOOKUP", "ARA": "LOOKUP", "SEÇ": "CHOOSE",
    "DEĞER": "VALUE", "METNEÇEVİR": "TEXT", "ÇAPRAZARA": "_xlfn.XLOOKUP", "ÇOKEĞER": "_xlfn.IFS",
    "EĞERYOKSA": "_xlfn.IFNA", "ÇOKEĞERORTALAMA": "AVERAGEIFS", "MAKEĞER": "_xlfn.MAXIFS",
    "MİNEĞER": "_xlfn.MINIFS", "METİNBİRLEŞTİR": "_xlfn.TEXTJOIN", "BİRLEŞTİR": "CONCATENATE",
    "BAĞ_DEĞ_SAY": "COUNT", "BAĞ_DEĞ_DOLU_SAY": "COUNTA", "DOĞRU": "TRUE", "YANLIŞ": "FALSE",
    "EHATALIYSA": "ISERROR", "ESAYIYSA": "ISNUMBER", "EMETİNSE": "ISTEXT", "EBOŞSA": "ISBLANK",
    "BUL": "FIND", "MBUL": "SEARCH", "DEĞİŞTİR": "REPLACE", "YİNELE": "REPT", "ÖZDEŞ": "EXACT",
    "KAREKÖK": "SQRT", "ÇARPIM": "PRODUCT", "ORTANCA": "MEDIAN", "ZAMAN": "TIME", "SERİTARİH": "EDATE",
    "SERİAY": "EOMONTH", "İŞGÜNÜ": "WORKDAY", "TAMİŞGÜNÜ": "NETWORKDAYS", "ETARİHLİ": "DATEDIF",
    "TARİHSAYISI": "DATEVALUE", "ISOHAFTASAY": "ISOWEEKNUM",
}


def _tr_to_en():
    out = {}
    for en, tr in NAME_MAP.items():
        if en.isascii() and not tr.isascii() or (en.isascii() and tr != en and not tr.isascii()):
            out.setdefault(tr, en)
    for en, tr in NAME_MAP.items():
        if en.isascii() and tr.isascii() and tr != en:
            out.setdefault(tr, en)  # SOLDAN -> LEFT gibi ASCII Türkçe adlar
    out.update(_TR_EN_EXTRA)
    return out


TR_EN = _tr_to_en()


def to_template(formula: str, current: dict, current_row: int) -> tuple[str, list[str]]:
    """Excel formülünü çıktıya yazılabilir şablona çevirir.

    current: {harf: sütun adı} (bu tablonun Excel'deki düzeni). Aynı satıra (veya yakın satıra)
    göreli başvurular `{Sütun}` / `{Sütun|-1}` olur; çıktı yazılırken o sütunun yeni harfi ve satırı
    konur. Sabit başvurular ($H$1) ve başka sayfalar olduğu gibi kalır (uyarı verilir).
    Ad ve ayırıcılar İngilizceye çevrilir (Excel dosyası formülleri İngilizce saklar)."""
    f = (formula or "").strip()
    if f.startswith("="):
        f = f[1:]
    sep = detect_separator(f)
    warns: list[str] = []
    out, pos = [], 0
    while pos < len(f):
        m = _TOKEN.match(f, pos)
        if not m or m.end() == pos:
            rest = f[pos:].strip()
            if not rest:
                break
            raise ShiftFlowError(f"Excel formülü anlaşılamadı, şu kısımda: '{rest[:25]}'")
        raw = m.group(0)
        s, sref, ref, num, name, op = m.groups()
        space = raw[: len(raw) - len(raw.lstrip())]
        if s is not None:
            out.append(space + s)
        elif sref:
            out.append(space + sref)
            sheet = sref.rsplit("!", 1)[0].strip("'")
            msg = f"'{sheet}' sayfasına başvuru var; çıktı kitabında bu sayfa yoksa Excel #BAŞV! gösterir."
            if msg not in warns:
                warns.append(msg)
        elif ref:
            r = _parse_ref(ref)
            if r.kind == "cell" and r.c1 in current and not r.abs_row and abs((r.r1 or 0) - current_row) <= 50:
                d = (r.r1 or 0) - current_row
                out.append(space + "{" + current[r.c1].replace("}", "}}") + ("" if d == 0 else f"|{d:+d}") + "}")
            else:
                out.append(space + ref)
                msg = f"{ref} başvurusu olduğu gibi yazılır (çıktıda aynı hücreye bakar)."
                if msg not in warns:
                    warns.append(msg)
        elif num:
            if sep == ";":
                num = num.replace(",", ".")
            out.append(space + num)
        elif name:
            up = tr_upper(re.sub(r"^_xl(fn|ws)\.", "", name))
            en = TR_EN.get(up, up if up.isascii() else None)
            if en is None:
                en = up
                warns.append(f"{up} fonksiyonunun İngilizce adı bilinmiyor; Excel'de #AD? hatası verebilir.")
            out.append(space + en)
        else:
            if op == ";":
                op = ","
            elif op == "," and sep == ";":
                op = ","  # Türkçe yazımda ',' yalnız sayı içinde olur; buraya gelmez
            out.append(space + op)
        pos = m.end()
    return "=" + "".join(out).strip(), warns


_TPL = re.compile(r"\{((?:[^{}]|\}\})+?)(?:\|([+-]\d+))?\}")


def render_template(template: str, letters: dict, row: int) -> str:
    """Şablondaki {Sütun} yerlerine çıktıdaki harf+satır koyar. Bilinmeyen sütun: #BAŞV!"""
    parts = re.split(r"(\"(?:[^\"]|\"\")*\")", template)
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(p)
            continue

        def sub(m):
            name = m.group(1).replace("}}", "}")
            off = int(m.group(2) or 0)
            letter = letters.get(name)
            return f"{letter}{row + off}" if letter and row + off >= 1 else "#REF!"
        out.append(_TPL.sub(sub, p))
    return "".join(out)


def cell_value(grid, ref: str):
    """FormulaGrid içinden 'H1' hücresinin değeri ve solundaki/üstündeki etiket: (değer, etiket)."""
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref.strip())
    if not m:
        return None, None
    c, r = col_index(m.group(1)) - grid.first_col, int(m.group(2)) - grid.first_row
    if r < 0 or c < 0 or r >= len(grid.rows):
        return None, None
    row = grid.rows[r]
    val = row[c] if c < len(row) else None
    label = None
    if c >= 1 and isinstance(row[c - 1], str) and row[c - 1].strip() and not row[c - 1].startswith("="):
        label = row[c - 1].strip().rstrip(":")
    elif r >= 1 and c < len(grid.rows[r - 1]) and isinstance(grid.rows[r - 1][c], str):
        label = grid.rows[r - 1][c].strip().rstrip(":")
    if isinstance(val, str) and val.startswith("="):
        val = None  # formüllü hücre: değeri bilinmiyor
    return val, label
