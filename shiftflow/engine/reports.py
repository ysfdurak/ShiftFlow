"""Rapor tanımları: bir raporu bir kez tanımla, sonra her açıldığında tanı.

Tanıma dosya adına değil sütun başlıklarına dayanır. WMS'in açtığı ve
henüz kaydedilmemiş çalışma kitapları "Kitap1", "Book3" gibi rastgele
adlarla gelir; sayfa adı da çoğu zaman "Sheet1"dir. Buna karşılık
raporun sütun başlıkları her gün aynıdır. Bu yüzden:

  1. Tanım oluşturulurken örnek rapordaki başlıklar kaydedilir; kullanıcı
     tanıma için hangilerinin kullanılacağını (anahtar sütunlar) seçer.
  2. Açık her sayfanın ilk satırları taranır, başlık satırı aranır
     (rapor üstünde başlık/tarih satırları olsa bile bulunur).
  3. Anahtar sütunlarının en az %80'i bulunan sayfa aday olur.
  4. Seçilen adayın sütunları tanımla karşılaştırılır: eksik, yeni,
     adı değişmiş olabilecek ve tipi değişmiş sütunlar raporlanır.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd

from .values import tr_lower, type_kind

HEADER_SCAN_ROWS = 30
AMBIGUITY_MARGIN = 0.05


def norm(name) -> str:
    """Başlık karşılaştırması için: küçük harf (Türkçe), tek boşluk."""
    if name is None:
        return ""
    if isinstance(name, float) and name.is_integer():
        name = int(name)
    s = tr_lower(str(name)).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def loose(name) -> str:
    """Daha gevşek karşılaştırma: boşluk, alt çizgi, nokta, parantez yok sayılır."""
    return re.sub(r"[\s_.\-()/:]+", "", norm(name))


def new_report_id() -> str:
    import uuid
    return "r_" + uuid.uuid4().hex[:10]


@dataclass
class ReportDefinition:
    name: str
    columns: list[dict]  # [{"name":..., "type": number|date|text}] örnek rapordaki tüm sütunlar
    key_columns: list[str]  # tanıma için kullanılan sütunlar
    id: str = field(default_factory=new_report_id)
    workbook_hint: str = ""  # isteğe bağlı: çalışma kitabı adında geçen metin
    sheet_hint: str = ""  # isteğe bağlı: sayfa adında geçen metin
    min_score: float = 0.8
    column_map: dict = field(default_factory=dict)  # gelen ad -> beklenen ad (öğrenilen eşlemeler)
    description: str = ""
    updated: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ReportDefinition":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def touch(self):
        self.updated = datetime.now().isoformat(timespec="seconds")


def columns_of(df: pd.DataFrame) -> list[dict]:
    return [{"name": str(c), "type": type_kind(df[c])} for c in df.columns]


# ------------------------------------------------------------------ başlık satırı
def _row_cells(row) -> list:
    return [c for c in row if c is not None and not (isinstance(c, float) and pd.isna(c)) and str(c).strip() != ""]


def guess_header_row(rows: list[list], scan: int = HEADER_SCAN_ROWS) -> int:
    """Tanım yokken başlık satırını tahmin eder.

    Raporların üstünde "Toplama Raporu", "Tarih: 10.11.2026" gibi tek
    hücreli satırlar olabilir. Başlık satırı, dolu hücre sayısı tablonun
    genişliğine yakın ve hücrelerinin tamamı metin olan ilk satırdır.
    """
    top = rows[:scan]
    if not top:
        return 0
    widths = [len(_row_cells(r)) for r in top]
    maxw = max(widths) if widths else 0
    if maxw == 0:
        return 0
    for i, r in enumerate(top):
        cells = _row_cells(r)
        if len(cells) >= max(2, 0.6 * maxw) and all(isinstance(c, str) for c in cells):
            return i
    for i, w in enumerate(widths):
        if w >= 0.6 * maxw:
            return i
    return 0


def find_header_row(rows: list[list], key_columns: list[str], column_map: dict | None = None,
                    scan: int = HEADER_SCAN_ROWS) -> tuple[int, float]:
    """Anahtar sütunlarla en çok örtüşen satırı bulur: (satır no, oran)."""
    keys = {norm(k) for k in key_columns}
    if not keys:
        return guess_header_row(rows, scan), 0.0
    rev = {norm(src): norm(dst) for src, dst in (column_map or {}).items()}
    best, best_score = 0, -1.0
    for i, r in enumerate(rows[:scan]):
        cells = {norm(c) for c in _row_cells(r)}
        cells |= {rev[c] for c in cells if c in rev}
        score = len(keys & cells) / len(keys)
        if score > best_score:
            best, best_score = i, score
    return best, max(best_score, 0.0)


def header_names(rows: list[list], header_row: int) -> list[str]:
    if header_row >= len(rows):
        return []
    return [str(c).strip() for c in _row_cells(rows[header_row])]


# ------------------------------------------------------------------ eşleştirme
@dataclass
class Candidate:
    workbook_id: str
    workbook_name: str
    sheet: str
    header_row: int
    score: float
    columns: list[str]
    saved: bool = True
    path: str = ""
    origin: str = "excel"

    @property
    def label(self) -> str:
        tag = "" if self.saved else " (kaydedilmemiş)"
        return f"{self.workbook_name}{tag} › {self.sheet}"


def score_sheet(defn: ReportDefinition, workbook_name: str, sheet_name: str, preview: list[list]) -> tuple[int, float]:
    header, score = find_header_row(preview, defn.key_columns, defn.column_map)
    if defn.workbook_hint:
        score += 0.05 if norm(defn.workbook_hint) in norm(workbook_name) else -0.2
    if defn.sheet_hint:
        score += 0.05 if norm(defn.sheet_hint) in norm(sheet_name) else -0.2
    return header, score


def match_definition(defn: ReportDefinition, workbooks) -> list[Candidate]:
    """Tanıma uyan açık sayfaları puana göre sıralı döner."""
    out = []
    for wb in workbooks:
        for sh in wb.sheets:
            header, score = score_sheet(defn, wb.name, sh.name, sh.preview)
            if score >= defn.min_score:
                out.append(Candidate(wb.id, wb.name, sh.name, header, round(score, 3),
                                     header_names(sh.preview, header), wb.saved, wb.path, wb.origin))
    # Eşit puanda kaydedilmemiş (WMS’in yeni açtığı) kitap önce gelir.
    out.sort(key=lambda c: (-c.score, c.saved))
    return out


def recognize(definitions: list[ReportDefinition], wb, sheet) -> tuple[ReportDefinition | None, float, int]:
    """Bir sayfanın hangi rapor olduğunu bulur (en yüksek puan)."""
    best, best_s, best_h = None, 0.0, 0
    for d in definitions:
        h, s = score_sheet(d, wb.name, sheet.name, sheet.preview)
        if s >= d.min_score and s > best_s:
            best, best_s, best_h = d, s, h
    return best, best_s, best_h


def is_ambiguous(cands: list[Candidate]) -> bool:
    return len(cands) > 1 and (cands[0].score - cands[1].score) < AMBIGUITY_MARGIN


# ------------------------------------------------------------------ karşılaştırma
TYPE_NAMES = {"number": "Sayı", "date": "Tarih", "text": "Metin"}


def compare_columns(expected: list[dict], df: pd.DataFrame, column_map: dict | None = None) -> dict:
    """Beklenen sütunlar ile gelen tabloyu karşılaştırır.

    Dönen sözlük:
      missing      : beklenip gelmeyen sütunlar (iş akışını bozabilir)
      extra        : yeni gelen sütunlar (zararsız)
      suggestions  : eksik sütun -> yeni dosyadaki olası karşılığı
      type_changes : [(sütun, eski tip, yeni tip)]
      order_changed: sütun sırası değişti mi
      column_map   : bu tabloya uygulanacak eşleme (gelen -> beklenen)
    """
    cmap = {k: v for k, v in (column_map or {}).items() if k in df.columns}
    incoming = [cmap.get(c, c) for c in df.columns]
    exp_names = [c["name"] for c in expected]
    missing = [c for c in exp_names if c not in incoming]
    # Büyük/küçük harf veya boşluk farkı: otomatik eşlenir, sorulmaz.
    auto = {}
    inc_norm = {norm(c): c for c in df.columns if cmap.get(c, c) not in exp_names}
    for m in list(missing):
        hit = inc_norm.get(norm(m))
        if hit is not None:
            auto[hit] = m
            missing.remove(m)
    cmap.update(auto)
    incoming = [cmap.get(c, c) for c in df.columns]
    extra = [c for c in df.columns if cmap.get(c, c) not in exp_names]
    loose_extra = {loose(c): c for c in extra}
    suggestions = {}
    for m in missing:
        if loose(m) in loose_extra:
            suggestions[m] = loose_extra[loose(m)]
            continue
        close = difflib.get_close_matches(m, extra, n=1, cutoff=0.6)
        if not close:
            lower = {norm(e): e for e in extra}
            c2 = difflib.get_close_matches(norm(m), list(lower), n=1, cutoff=0.6)
            close = [lower[c2[0]]] if c2 else []
        if close:
            suggestions[m] = close[0]
    exp_types = {c["name"]: c.get("type") for c in expected}
    type_changes = []
    for c in df.columns:
        tgt = cmap.get(c, c)
        if tgt in exp_types and exp_types[tgt] and exp_types[tgt] != type_kind(df[c]):
            type_changes.append((tgt, exp_types[tgt], type_kind(df[c])))
    present = [c for c in incoming if c in exp_names]
    order_changed = present != [c for c in exp_names if c in present]
    return {"missing": missing, "extra": extra, "suggestions": suggestions, "type_changes": type_changes,
            "order_changed": order_changed, "column_map": cmap, "auto_mapped": auto}


def describe_changes(ch: dict) -> list[str]:
    lines = []
    if ch.get("missing"):
        lines.append("Eksik sütun: " + ", ".join(ch["missing"]))
    if ch.get("auto_mapped"):
        lines.append("Yazımı farklı, otomatik eşlendi: " + ", ".join(f"{a} → {b}" for a, b in ch["auto_mapped"].items()))
    if ch.get("extra"):
        lines.append("Yeni sütun: " + ", ".join(map(str, ch["extra"][:12])) + (" …" if len(ch["extra"]) > 12 else ""))
    if ch.get("type_changes"):
        lines.append("Tipi değişen: " + ", ".join(
            f"{c} ({TYPE_NAMES.get(a, a)} → {TYPE_NAMES.get(b, b)})" for c, a, b in ch["type_changes"]))
    if ch.get("order_changed"):
        lines.append("Sütun sırası değişmiş (sorun değil; sütunlar adla eşlenir).")
    return lines


def fingerprint(df: pd.DataFrame) -> str:
    """Tablonun içerik özeti. Aynı rapor iki kez kullanılırsa yakalamak için.

    Yalnızca özet saklanır; veri saklanmaz ve özetten veri geri elde edilemez.
    """
    h = hashlib.sha1(f"{df.shape}|{list(map(str, df.columns))}".encode())
    try:
        h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
    except (TypeError, ValueError):
        h.update(pd.util.hash_pandas_object(df.astype(str), index=False).values.tobytes())
    return h.hexdigest()
