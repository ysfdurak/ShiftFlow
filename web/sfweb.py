"""ShiftFlow tarayıcı demosu için köprü.

Tarayıcıdaki JavaScript arayüzü yalnızca `dispatch(ad, json_argümanlar)`
fonksiyonunu çağırır ve JSON metin geri alır. Motor (shiftflow.engine)
masaüstü uygulamasıyla AYNI koddur; burada yalnızca:

- örnek (sentetik) veri üretilir,
- oturumun durumu arayüzün çizebileceği sade bir sözlüğe çevrilir,
- hatalar {"ok": false, "error": ...} olarak döndürülür.

Bu dosya Pyodide (tarayıcıda Python) içinde çalışır; testlerde ve yerel
geliştirme sunucusunda (dev_server.py) normal Python ile de çalışır.
Ağ bağlantısı kurmaz; dosyalar tarayıcının sanal diskindeki /tmp altındadır.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import shiftflow
from shiftflow.engine import Session, ShiftFlowError, operations, variants
from shiftflow.engine import excel_out
from shiftflow.engine import io as sio
from shiftflow.engine.values import type_kind

WORK_DIR = os.environ.get("SFWEB_DIR", "/tmp/sfweb")
PREVIEW_ROWS = 200
MAX_UPLOAD_ROWS = 200_000

_session = Session()
_day = 0  # örnek verinin kaçıncı günü (Yeni günün verisi düğmesi artırır)


# ================================================================ örnek veri
_NAMES = ["Ayşe Kaya", "Mehmet Demir", "Elif Şahin", "Burak Yıldız", "Zeynep Arslan", "Emre Koç",
          "Selin Aydın", "Can Öztürk", "Deniz Çelik", "Hakan Polat", "Merve Kurt", "Okan Aksoy",
          "Gizem Erdem", "Serkan Tekin", "Ece Güneş", "Tolga Kaplan", "Buse Yalçın", "Kerem Şen"]
_TEAMS = ["Toplama 1", "Toplama 2", "Paketleme"]
_ZONES = ["A Blok", "B Blok", "Soğuk Oda", "Yüksek Raf"]
_SHIFTS = [("Sabah", 7), ("Akşam", 15), ("Gece", 23)]


def sample_frames(day: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sentetik vardiya verisi + personel listesi. Gerçek kişi/şirket verisi değildir.

    Bilerek konan sorunlar (demoda uygulamanın yakaladığını göstermek için):
    - 'A Blok' bazı satırlarda 'A Blok ' (sonda boşluk) ve 'a blok' yazılmış,
    - iki personel (P019, P020) personel listesinde yok,
    - birkaç satırda Toplanan Adet 0.
    """
    rng = random.Random(1000 + day)
    base = datetime(2026, 11, 2) + timedelta(days=day)
    rows = []
    order = 50000 + day * 1000
    for shift, start in _SHIFTS:
        people = rng.sample(range(1, 21), 14)
        for pid in people:
            for _ in range(rng.randint(3, 6)):
                order += 1
                zone = rng.choice(_ZONES)
                if zone == "A Blok":
                    r = rng.random()
                    zone = "A Blok " if r < 0.12 else ("a blok" if r < 0.2 else zone)
                qty = rng.randint(20, 160)
                if rng.random() < 0.02:
                    qty = 0
                minutes = max(5, int(qty / rng.uniform(1.2, 2.6)))
                errors = rng.choices([0, 0, 0, 1, 2, 3], k=1)[0] if qty else 0
                t = base + timedelta(hours=start, minutes=rng.randint(0, 470))
                rows.append({
                    "Tarih": t.replace(second=0),
                    "Vardiya": shift,
                    "Personel ID": f"P{pid:03d}",
                    "Bölge": zone,
                    "Sipariş No": f"SP-{order}",
                    "Toplanan Adet": qty,
                    "Hatalı Adet": errors,
                    "Süre (dk)": minutes,
                })
    data = pd.DataFrame(rows).sort_values("Tarih", kind="mergesort").reset_index(drop=True)
    staff = pd.DataFrame([
        {"Personel ID": f"P{i + 1:03d}", "Ad Soyad": _NAMES[i], "Ekip": _TEAMS[i % 3]}
        for i in range(len(_NAMES))
    ])
    return data, staff


# ================================================================ dönüştürme yardımcıları
def _cell(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        if pd.isna(v):
            return None
        return v.strftime("%d.%m.%Y") if not (v.hour or v.minute) else v.strftime("%d.%m.%Y %H:%M")
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f) if f.is_integer() and abs(f) < 1e15 else round(f, 6)
    return str(v)


def _err(exc: Exception) -> dict:
    if isinstance(exc, ShiftFlowError):
        cause = getattr(exc, "cause", None)
        if isinstance(cause, ShiftFlowError):
            return {"ok": False, "error": cause.message, "detail": cause.detail}
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    return {"ok": False, "error": f"Beklenmeyen hata: {type(exc).__name__}: {exc}", "detail": ""}


def _status(st, index: int) -> dict:
    found = {c: v for c, v in (st.variants or {}).items() if v}
    return {
        "index": index,
        "label": st.label,
        "rows_before": st.rows_before,
        "rows_after": st.rows_after,
        "cols_after": st.cols_after,
        "messages": list(st.messages or []),
        "warnings": list(st.warnings or []),
        "error": None if st.error is None else (st.error.message if isinstance(st.error, ShiftFlowError) else str(st.error)),
        "variants": {c: [{"keep": k, "forms": forms} for k, forms in g.items()] for c, g in found.items()},
    }


# ================================================================ komutlar
def meta(_=None):
    return {
        "version": shiftflow.__version__,
        "conditions": operations.CONDITION_OPS,
        "no_value": sorted(operations.NO_VALUE_OPS),
        "aggs": operations.AGG_FUNCS,
        "cases": operations.TEXT_CASES,
        "checks": operations.CHECKS,
        "labels": {k: o.label for k, o in operations.REGISTRY.items()},
    }


def reset(_=None):
    global _session, _day
    _session = Session()
    _day = 0
    return {}


def load_sample(_=None):
    reset()
    data, staff = sample_frames(0)
    _session.add_source("Vardiya verisi", data, kind="paste")
    _session.add_source("Personel listesi", staff, kind="paste")
    return {"focus": "Vardiya verisi"}


def load_file(a):
    path, name = a["path"], a.get("name") or os.path.splitext(os.path.basename(a["path"]))[0]
    df = sio.read_source(path, a.get("sheet"))
    if len(df) > MAX_UPLOAD_ROWS:
        raise ShiftFlowError(f"Demo en fazla {MAX_UPLOAD_ROWS:,} satır kabul eder; dosyada {len(df):,} satır var."
                             .replace(",", "."))
    name = _session.add_source(name, df, kind="file", path="")
    return {"focus": name}


def sheets(a):
    return {"sheets": sio.list_sheets(a["path"])}


def build_demo_flow(_=None):
    """Tek tıkla örnek iş akışı: eşleştir, hesapla, doğrula, pivot."""
    load_sample()
    s, d = _session, "Vardiya verisi"
    s.add_step(d, "filter", {"conditions": [{"column": "Toplanan Adet", "op": "gt", "value": "0"}], "mode": "and"})
    s.add_step(d, "lookup", {"table": "Personel listesi", "keys": [["Personel ID", "Personel ID"]],
                             "columns": [{"column": "Ad Soyad", "as": "Ad Soyad"}, {"column": "Ekip", "as": "Ekip"}],
                             "if_missing": "Listede yok", "on_duplicate": "first"})
    s.add_step(d, "calc", {"name": "Adet/Saat", "formula": "YUVARLA([Toplanan Adet] / [Süre (dk)] * 60; 1)"})
    s.add_step(d, "calc", {"name": "Hata %", "formula": "YUVARLA([Hatalı Adet] / [Toplanan Adet] * 100; 2)"})
    s.add_step(d, "conditional", {"name": "Durum", "conditions": [{"column": "Adet/Saat", "op": "ge", "value": "90"}],
                                  "mode": "and", "then": "\"Hedefte\"", "else": "\"Hedef altı\""})
    s.add_step(d, "validate", {"checks": [{"check": "not_empty", "column": "Personel ID", "on_fail": "stop"},
                                          {"check": "range", "column": "Hata %", "min": "0", "max": "10",
                                           "on_fail": "warn"}]})
    p = s.add_derived("Bölge özeti", "pivot", [d], {
        "rows": ["Bölge"], "columns": ["Vardiya"],
        "values": [{"column": "Toplanan Adet", "func": "sum"}], "totals": True})
    s.add_derived("Personel performansı", "group", [d], {
        "by": ["Ad Soyad", "Ekip"],
        "values": [{"column": "Toplanan Adet", "func": "sum", "name": "Toplam Adet"},
                   {"column": "Adet/Saat", "func": "mean", "name": "Ort. Adet/Saat"},
                   {"column": "Hatalı Adet", "func": "sum", "name": "Hatalı"}]})
    s.workflow.outputs = []
    return {"focus": p}


def next_day(_=None):
    """Aynı akışı ertesi günün (yeni) örnek verisiyle tekrar çalıştırır."""
    global _day
    if "Vardiya verisi" not in _session.workflow.sources:
        raise ShiftFlowError("Bu düğme örnek veriyle çalışır. Önce 'Örnek veriyi yükle' veya 'Örnek akışı kur'.")
    _day += 1
    data, staff = sample_frames(_day)
    _session.bind_source("Vardiya verisi", data)
    if "Personel listesi" in _session.workflow.sources:
        _session.bind_source("Personel listesi", staff)
    return {"day": _day, "date": (datetime(2026, 11, 2) + timedelta(days=_day)).strftime("%d.%m.%Y")}


def state(a):
    s = _session
    names = list(s.workflow.datasets)
    out = {"datasets": [], "undo": s.can_undo(), "redo": s.can_redo(), "focus": None}
    for n in names:
        ds = s.workflow.datasets[n]
        out["datasets"].append({"name": n, "origin": ds.origin.type, "inputs": list(ds.origin.inputs),
                                "steps": len(ds.steps)})
    focus = (a or {}).get("dataset")
    if focus not in names:
        focus = names[0] if names else None
    out["focus"] = focus
    if not focus:
        return out
    ds = s.workflow.datasets[focus]
    sts = s.step_statuses(focus)
    steps = []
    for i, st in enumerate(sts):
        d = _status(st, i - 1)
        if i > 0:
            step = ds.steps[i - 1]
            d.update(op=step.op, enabled=step.enabled)
        else:
            d.update(op=ds.origin.type, enabled=True)
        steps.append(d)
    out["steps"] = steps
    upto = (a or {}).get("upto")
    if upto is None or upto >= len(ds.steps):
        upto = len(ds.steps) - 1
    out["upto"] = upto
    try:
        df = s.result(focus, upto)
        out["preview"] = {
            "columns": [{"name": str(c), "type": type_kind(df[c])} for c in df.columns],
            "rows": [[_cell(v) for v in row] for row in df.head(PREVIEW_ROWS).itertuples(index=False, name=None)],
            "total": len(df),
        }
    except ShiftFlowError as exc:
        out["preview"] = None
        out["preview_error"] = _err(exc)["error"]
    return out


def columns(a):
    """Bir veri kümesinin belirli bir adımdaki sütunları (formlar için)."""
    ds = a["dataset"]
    upto = a.get("upto")
    df = _session.result(ds, upto)
    return {"columns": [{"name": str(c), "type": type_kind(df[c])} for c in df.columns]}


def add_step(a):
    pos = a.get("position")
    _session.add_step(a["dataset"], a["op"], a["params"], position=pos)
    return {}


def edit_step(a):
    _session.edit_step(a["dataset"], a["index"], a["params"])
    return {}


def add_derived(a):
    name = _session.add_derived(a["name"], a["op"], a["inputs"], a["params"])
    return {"focus": name}


def delete_step(a):
    _session.delete_step(a["dataset"], a["index"])
    return {}


def move_step(a):
    _session.move_step(a["dataset"], a["index"], a["delta"])
    return {}


def toggle_step(a):
    ds = _session.workflow.dataset(a["dataset"])
    _session.set_step_enabled(a["dataset"], a["index"], not ds.steps[a["index"]].enabled)
    return {}


def delete_dataset(a):
    _session.delete_dataset(a["dataset"])
    return {}


def fix_variants(a):
    _session.fix_variants(a["dataset"], a["index"], a["columns"])
    return {}


def ignore_variants(a):
    _session.ignore_variants(a["dataset"], a["index"])
    return {}


def undo(_=None):
    _session.undo()
    return {}


def redo(_=None):
    _session.redo()
    return {}


def step_params(a):
    ds = _session.workflow.dataset(a["dataset"])
    st = ds.steps[a["index"]]
    return {"op": st.op, "params": st.params}


def export(a):
    """Seçili veri kümelerini biçimli bir Excel dosyasına yazar (doğrulamalar katı modda)."""
    a = a or {}
    names = a.get("datasets") or list(_session.workflow.datasets)
    os.makedirs(WORK_DIR, exist_ok=True)
    path = os.path.join(WORK_DIR, "ShiftFlow_rapor.xlsx")
    _session.strict_validation = True
    try:
        sheets_ = []
        for n in names:
            df = _session.result(n)
            sheets_.append((n, df, {"totals": _session.workflow.datasets[n].origin.type == "source"}))
        warnings: list[str] = []
        excel_out.write_excel(path, sheets_, warnings=warnings)
    finally:
        _session.strict_validation = False
    return {"path": path, "file": "ShiftFlow_rapor.xlsx", "warnings": warnings}


def workflow_json(_=None):
    return {"json": _session.workflow.to_json()}


COMMANDS = {f.__name__: f for f in (
    meta, reset, load_sample, load_file, sheets, build_demo_flow, next_day, state, columns, add_step,
    edit_step, add_derived, delete_step, move_step, toggle_step, delete_dataset, fix_variants,
    ignore_variants, undo, redo, step_params, export, workflow_json)}


def dispatch(name: str, args_json: str = "null") -> str:
    """Arayüzün tek giriş noktası. Her zaman JSON metin döner."""
    try:
        fn = COMMANDS.get(name)
        if fn is None:
            raise ShiftFlowError(f"Bilinmeyen komut: {name}")
        args = json.loads(args_json) if args_json else None
        res = fn(args)
        return json.dumps({"ok": True, **(res or {})}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - arayüze her hata açıklamayla dönmeli
        return json.dumps(_err(exc), ensure_ascii=False)
