"""Program içi gösterge paneli (dashboard): iş akışının veri kümelerinden kutucuklar.

Kutucuk türleri: sayı (KPI), sütun grafiği, çubuk grafiği, çizgi grafiği, küçük tablo.
Tanım iş akışında saklanır (`run_settings["dashboard"]`); her açılışta güncel sonuçtan hesaplanır.
Arşivden eklenen bir kaynak (ör. "son 30 gün") ile günlere göre eğilim gösterilebilir.

Bu panel bu bilgisayarda çalışır. Ekibin ortak bir panelden izlemesi istenirse veriler bir sunucuda
(şirket sunucusu veya VPS) tutulmalıdır; bu sürümün kapsamında değildir.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import operations as ops
from .errors import ShiftFlowError

KINDS = {"kpi": "Sayı (KPI)", "column": "Sütun grafiği", "bar": "Çubuk grafiği", "line": "Çizgi grafiği",
         "table": "Tablo"}
AGGS = {k: v for k, v in ops.AGG_FUNCS.items()}


@dataclass
class TileData:
    kind: str
    title: str
    labels: list = field(default_factory=list)
    values: list = field(default_factory=list)
    value: float | None = None  # KPI
    table: pd.DataFrame | None = None
    note: str = ""
    error: str = ""


def _fmt_label(v) -> str:
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d.%m") if not (v.hour or v.minute) else v.strftime("%d.%m %H:%M")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def compute_tile(session, tile: dict) -> TileData:
    kind = tile.get("kind", "column")
    title = tile.get("title") or tile.get("y") or tile.get("dataset", "")
    out = TileData(kind=kind, title=title)
    try:
        df = session.result(tile["dataset"])
    except KeyError:
        out.error = "Veri kümesi seçilmedi."
        return out
    except ShiftFlowError as exc:
        out.error = exc.message
        return out
    if kind == "table":
        out.table = df.head(int(tile.get("rows") or 10))
        out.note = f"{len(df):,} satırdan ilk {len(out.table)}".replace(",", ".")
        return out
    y, agg = tile.get("y"), tile.get("agg", "sum")
    if agg != "count" and (not y or y not in df.columns):
        out.error = f"'{y}' sütunu yok." if y else "Değer sütunu seçin."
        return out
    col = y if y in df.columns else df.columns[0]
    if kind == "kpi":
        res = ops.REGISTRY["group"].run([df.assign(_hepsi="")],
                                        {"by": ["_hepsi"], "values": [{"column": col, "func": agg}]}, title).df
        out.value = float(res.iloc[0, 1]) if len(res) else None
        out.note = f"{AGGS.get(agg, agg)} · {len(df):,} satır".replace(",", ".")
        return out
    x = tile.get("x")
    if not x or x not in df.columns:
        out.error = "Grafik için gruplama (yatay eksen) sütunu seçin."
        return out
    p = {"by": [x], "values": [{"column": col, "func": agg, "name": "değer"}]}
    if tile.get("date_group") and tile["date_group"] != "none":
        p["date_group"] = tile["date_group"]
    if kind in ("column", "bar") and tile.get("sort", True):
        p["sort_by_value"] = True
    if tile.get("top_n"):
        p["top_n"] = int(tile["top_n"])
    try:
        res = ops.REGISTRY["group"].run([df], p, title).df
    except ShiftFlowError as exc:
        out.error = exc.message
        return out
    out.labels = [_fmt_label(v) for v in res[x].tolist()]
    out.values = [None if pd.isna(v) else float(v) for v in res["değer"].tolist()]
    out.note = f"{AGGS.get(agg, agg)} · {x}"
    return out


def tiles_of(session) -> list[dict]:
    return list((session.workflow.run_settings.get("dashboard") or {}).get("tiles") or [])


def set_tiles(session, tiles: list[dict]):
    def mut(wf):
        rs = dict(wf.run_settings)
        rs["dashboard"] = {"tiles": list(tiles)}
        wf.run_settings = rs
    session._commit(mut, check=[])
