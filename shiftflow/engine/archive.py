"""Rapor arşivi: her 'Rapor oluştur' sonucunu dönem (tarih + vardiya) ile saklar.

Konum: rapor kütüphanesinin yanında `archive.db` (tek kullanıcı, yerel).

Yapı:
- Arşiv kümesi (set): Bir iş akışının bir veri kümesinin geçmişi,
  örn. "Günlük toplama / Ekip Özeti". Her kümenin kendi tablosu vardır.
- Her satıra `_donem`, `_tarih`, `_vardiya` alanları eklenir.
- Aynı dönem yeniden oluşturulursa o dönemin eski kayıtları silinip yenisi
  yazılır (çift kayıt olmaz).
- Rapor biçimi zamanla değişirse yeni sütunlar tabloya eklenir; eski
  dönemlerde bu sütunlar boş görünür.

Arşivden okunan tabloya "Tarih" ve "Vardiya" sütunları eklenir; böylece
geçmiş veriler pivotta tarihe/vardiyaya göre gruplanabilir.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd

from . import periods as pr
from .errors import ShiftFlowError
from .values import type_kind

RANGE_TYPES = {
    "previous_shift": "Önceki vardiya",
    "same_shift_previous_day": "Dünün aynı vardiyası",
    "previous_day": "Önceki gün (tüm vardiyalar)",
    "last_days": "Önceki N gün",
    "this_month": "Bu ay (bugüne kadar)",
    "date_range": "Tarih aralığı",
    "all": "Tüm arşiv",
}
META_COLS = ("_donem", "_tarih", "_vardiya")


def default_archive_path() -> str:
    from .library import default_db_path
    return os.path.join(os.path.dirname(default_db_path()), "archive.db")


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


class Archive:
    def __init__(self, path: str | None = None):
        self.path = path or default_archive_path()
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False)  # tek iş parçacığı kullanır; arayüz görev sırasında kilitli
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS arc_sets (
                    name TEXT PRIMARY KEY, tbl TEXT NOT NULL, columns TEXT NOT NULL, created TEXT, updated TEXT);
                CREATE TABLE IF NOT EXISTS arc_periods (
                    set_name TEXT NOT NULL, period_key TEXT NOT NULL, date TEXT NOT NULL, shift TEXT,
                    rows INTEGER, written TEXT, PRIMARY KEY (set_name, period_key));
                CREATE TABLE IF NOT EXISTS arc_trash (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, set_name TEXT NOT NULL,
                    period_key TEXT, info TEXT, payload TEXT NOT NULL, deleted TEXT NOT NULL);
            """)
            self.purge_trash()
            self.db.commit()
        except sqlite3.Error as exc:
            raise ShiftFlowError("Rapor arşivi açılamadı.", detail=f"{self.path}: {exc}") from exc
        self.version = 0  # her yazmada artar (önbellek geçersizleştirme)

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ meta
    def sets(self) -> list[dict]:
        out = []
        for name, cols, updated in self.db.execute("SELECT name, columns, updated FROM arc_sets ORDER BY name"):
            r = self.db.execute("SELECT COUNT(*), MIN(date), MAX(date), SUM(rows) FROM arc_periods WHERE set_name=?",
                                (name,)).fetchone()
            out.append({"name": name, "columns": json.loads(cols), "updated": updated, "periods": r[0],
                        "first": r[1], "last": r[2], "rows": r[3] or 0})
        return out

    def set_meta(self, name):
        r = self.db.execute("SELECT tbl, columns FROM arc_sets WHERE name=?", (name,)).fetchone()
        return (r[0], json.loads(r[1])) if r else (None, None)

    def periods(self, name: str) -> list[dict]:
        rows = self.db.execute("SELECT period_key, date, shift, rows, written FROM arc_periods WHERE set_name=? "
                               "ORDER BY date DESC, period_key DESC", (name,)).fetchall()
        return [dict(zip(("key", "date", "shift", "rows", "written"), r)) for r in rows]

    def has_period(self, name: str, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM arc_periods WHERE set_name=? AND period_key=?", (name, key)).fetchone() is not None

    # ------------------------------------------------------------ yazma
    def write(self, set_name: str, df: pd.DataFrame, period: pr.Period) -> int:
        set_name = set_name.strip()
        if not set_name:
            raise ShiftFlowError("Arşiv kümesi adı boş olamaz.")
        tbl, cols = self.set_meta(set_name)
        now = datetime.now().isoformat(timespec="seconds")
        new_cols = [{"name": str(c), "type": type_kind(df[c])} for c in df.columns]
        if any(c["name"] in META_COLS for c in new_cols):
            raise ShiftFlowError("Arşivlenecek tabloda _donem/_tarih/_vardiya adlı sütun olamaz.")
        try:
            if tbl is None:
                tbl = "d_" + hashlib.sha1(set_name.encode()).hexdigest()[:12]
                defs = ", ".join([f"{_q(c)} TEXT" for c in META_COLS] + [_q(c["name"]) for c in new_cols])
                self.db.execute(f"CREATE TABLE {_q(tbl)} ({defs})")
                self.db.execute(f"CREATE INDEX {_q('ix_' + tbl)} ON {_q(tbl)}(_donem)")
                cols = new_cols
                self.db.execute("INSERT INTO arc_sets(name, tbl, columns, created, updated) VALUES (?,?,?,?,?)",
                                (set_name, tbl, json.dumps(cols, ensure_ascii=False), now, now))
            else:
                known = {c["name"] for c in cols}
                for c in new_cols:
                    if c["name"] not in known:
                        self.db.execute(f"ALTER TABLE {_q(tbl)} ADD COLUMN {_q(c['name'])}")
                        cols.append(c)
                # tip değişirse son görülen tip esas alınır
                types = {c["name"]: c["type"] for c in new_cols}
                for c in cols:
                    c["type"] = types.get(c["name"], c["type"])
                self.db.execute("UPDATE arc_sets SET columns=?, updated=? WHERE name=?",
                                (json.dumps(cols, ensure_ascii=False), now, set_name))
            if self.has_period(set_name, period.key):
                self._to_trash("replaced", set_name, period.key, commit=False)
            self.db.execute(f"DELETE FROM {_q(tbl)} WHERE _donem=?", (period.key,))

            def cell(v):
                if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and v != v):
                    return None
                if isinstance(v, (pd.Timestamp, datetime)):
                    return pd.Timestamp(v).isoformat()
                if hasattr(v, "item"):
                    return v.item()
                return v
            names = [str(c) for c in df.columns]
            sql = (f"INSERT INTO {_q(tbl)} ({', '.join(_q(c) for c in META_COLS + tuple(names))}) "
                   f"VALUES ({', '.join('?' * (len(names) + 3))})")
            meta = (period.key, period.date.isoformat(), period.shift_label)
            self.db.executemany(sql, (meta + tuple(cell(v) for v in r) for r in df.itertuples(index=False)))
            self.db.execute("INSERT OR REPLACE INTO arc_periods(set_name, period_key, date, shift, rows, written) "
                            "VALUES (?,?,?,?,?,?)",
                            (set_name, period.key, period.date.isoformat(), period.shift_label, len(df), now))
            self.db.commit()
        except sqlite3.Error as exc:
            self.db.rollback()
            raise ShiftFlowError("Arşive yazılamadı.", detail=str(exc)) from exc
        self.version += 1
        return len(df)

    # ------------------------------------------------------------ çöp kutusu (30 gün)
    TRASH_DAYS = 30
    TRASH_KINDS = {"period": "Silinen dönem", "set": "Silinen küme", "replaced": "Değiştirilen dönem (eski hâli)"}

    def _to_trash(self, kind: str, set_name: str, key: str | None = None, commit: bool = True):
        tbl, cols = self.set_meta(set_name)
        if tbl is None:
            return
        where, args = ("WHERE _donem=?", (key,)) if key else ("", ())
        cur = self.db.execute(f"SELECT * FROM {_q(tbl)} {where} ORDER BY rowid", args)
        names = [d[0] for d in cur.description]
        rows = cur.fetchall()
        per = self.db.execute("SELECT period_key, date, shift, rows, written FROM arc_periods WHERE set_name=?"
                              + (" AND period_key=?" if key else ""), (set_name, key) if key else (set_name,)).fetchall()
        payload = json.dumps({"columns": cols, "names": names, "rows": rows, "periods": per}, ensure_ascii=False,
                             default=str)
        info = f"{len(rows)} satır" + (f", {len(per)} dönem" if not key else "")
        self.db.execute("INSERT INTO arc_trash(kind, set_name, period_key, info, payload, deleted) VALUES (?,?,?,?,?,?)",
                        (kind, set_name, key, info, payload, datetime.now().isoformat(timespec="seconds")))
        if commit:
            self.db.commit()

    def trash(self) -> list[dict]:
        rows = self.db.execute("SELECT id, kind, set_name, period_key, info, deleted FROM arc_trash "
                               "ORDER BY id DESC").fetchall()
        return [dict(zip(("id", "kind", "set", "key", "info", "deleted"), r)) for r in rows]

    def purge_trash(self, days: int | None = None):
        from datetime import timedelta as _td
        limit = (datetime.now() - _td(days=self.TRASH_DAYS if days is None else days)).isoformat(timespec="seconds")
        self.db.execute("DELETE FROM arc_trash WHERE deleted < ?", (limit,))
        self.db.commit()

    def restore(self, trash_id: int) -> str:
        """Çöp kutusundaki dönemi/kümeyi geri yükler. Aynı dönem şimdi varsa o hâli çöp kutusuna gider."""
        r = self.db.execute("SELECT kind, set_name, period_key, payload FROM arc_trash WHERE id=?",
                            (trash_id,)).fetchone()
        if r is None:
            raise ShiftFlowError("Çöp kutusunda bu kayıt yok.")
        kind, set_name, key, payload = r
        data = json.loads(payload)
        cols, names, rows, per = data["columns"], data["names"], data["rows"], data["periods"]
        try:
            tbl, cur_cols = self.set_meta(set_name)
            now = datetime.now().isoformat(timespec="seconds")
            if tbl is None:
                tbl = "d_" + hashlib.sha1(set_name.encode()).hexdigest()[:12]
                self.db.execute(f"DROP TABLE IF EXISTS {_q(tbl)}")
                self.db.execute(f"CREATE TABLE {_q(tbl)} ({', '.join(_q(n) + ' TEXT' for n in names)})")
                self.db.execute(f"CREATE INDEX {_q('ix_' + tbl)} ON {_q(tbl)}(_donem)")
                self.db.execute("INSERT INTO arc_sets(name, tbl, columns, created, updated) VALUES (?,?,?,?,?)",
                                (set_name, tbl, json.dumps(cols, ensure_ascii=False), now, now))
            else:
                have = {d[1] for d in self.db.execute(f"PRAGMA table_info({_q(tbl)})")}
                for n in names:
                    if n not in have:
                        self.db.execute(f"ALTER TABLE {_q(tbl)} ADD COLUMN {_q(n)}")
                known = {c["name"] for c in cur_cols}
                merged = cur_cols + [c for c in cols if c["name"] not in known]
                self.db.execute("UPDATE arc_sets SET columns=?, updated=? WHERE name=?",
                                (json.dumps(merged, ensure_ascii=False), now, set_name))
            for pk_, *_ in per:
                if self.has_period(set_name, pk_):
                    self._to_trash("replaced", set_name, pk_, commit=False)
                self.db.execute(f"DELETE FROM {_q(tbl)} WHERE _donem=?", (pk_,))
            self.db.executemany(f"INSERT INTO {_q(tbl)} ({', '.join(_q(n) for n in names)}) "
                                f"VALUES ({', '.join('?' * len(names))})", rows)
            self.db.executemany("INSERT OR REPLACE INTO arc_periods(set_name, period_key, date, shift, rows, written) "
                                "VALUES (?,?,?,?,?,?)", [(set_name, *p) for p in per])
            self.db.execute("DELETE FROM arc_trash WHERE id=?", (trash_id,))
            self.db.commit()
        except sqlite3.Error as exc:
            self.db.rollback()
            raise ShiftFlowError("Geri yüklenemedi.", detail=str(exc)) from exc
        self.version += 1
        return f"{set_name}" + (f" · {key}" if key else "")

    def delete_period(self, set_name: str, key: str):
        tbl, _ = self.set_meta(set_name)
        if tbl:
            self._to_trash("period", set_name, key, commit=False)
            self.db.execute(f"DELETE FROM {_q(tbl)} WHERE _donem=?", (key,))
            self.db.execute("DELETE FROM arc_periods WHERE set_name=? AND period_key=?", (set_name, key))
            self.db.commit()
            self.version += 1

    def delete_set(self, set_name: str):
        tbl, _ = self.set_meta(set_name)
        if tbl:
            self._to_trash("set", set_name, None, commit=False)
            self.db.execute(f"DROP TABLE IF EXISTS {_q(tbl)}")
            self.db.execute("DELETE FROM arc_periods WHERE set_name=?", (set_name,))
            self.db.execute("DELETE FROM arc_sets WHERE name=?", (set_name,))
            self.db.commit()
            self.version += 1

    # ------------------------------------------------------------ okuma
    def read(self, set_name: str, keys: list[str] | None = None, date_from: date | None = None,
             date_to: date | None = None) -> pd.DataFrame:
        tbl, cols = self.set_meta(set_name)
        if tbl is None:
            raise ShiftFlowError(f"Arşivde '{set_name}' adlı küme yok.")
        where, args = [], []
        if keys is not None:
            if not keys:
                where.append("0")
            else:
                where.append(f"_donem IN ({', '.join('?' * len(keys))})")
                args += keys
        if date_from:
            where.append("_tarih >= ?")
            args.append(date_from.isoformat())
        if date_to:
            where.append("_tarih <= ?")
            args.append(date_to.isoformat())
        sql = f"SELECT * FROM {_q(tbl)}" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY rowid"
        cur = self.db.execute(sql, args)
        names = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=names, dtype=object)
        out = pd.DataFrame(index=df.index)
        date_name = "Tarih" if "Tarih" not in [c["name"] for c in cols] else "Arşiv Tarihi"
        shift_name = "Vardiya" if "Vardiya" not in [c["name"] for c in cols] else "Arşiv Vardiyası"
        out[date_name] = pd.to_datetime(df["_tarih"], errors="coerce") if len(df) else pd.Series(dtype="datetime64[ns]")
        out[shift_name] = df["_vardiya"].astype(object) if len(df) else pd.Series(dtype=object)
        for c in cols:
            s = df[c["name"]] if c["name"] in df.columns else pd.Series([None] * len(df), dtype=object)
            if c["type"] == "number":
                s = pd.to_numeric(s, errors="coerce")
                if s.notna().all() and len(s) and (s % 1 == 0).all():
                    s = s.astype("int64")
            elif c["type"] == "date":
                s = pd.to_datetime(s, errors="coerce")
            out[c["name"]] = s.to_numpy() if len(df) else s
        return out.reset_index(drop=True)

    def resolve(self, spec: dict, period: pr.Period | None, shifts: list[dict]) -> tuple[pd.DataFrame, str]:
        """Arşiv kaynağı tanımını seçili döneme göre okur. (tablo, açıklama) döner."""
        set_name = spec.get("set", "")
        rng = spec.get("range") or {"type": "previous_shift"}
        t = rng.get("type", "previous_shift")
        if period is None:
            period = pr.auto_period(datetime.now(), shifts)
        if t == "previous_shift":
            p = pr.previous(period, shifts)
            return self.read(set_name, keys=[p.key]), f"önceki vardiya: {p.label}"
        if t == "same_shift_previous_day":
            p = pr.same_shift_previous_day(period, shifts)
            return self.read(set_name, keys=[p.key]), f"dünün aynı vardiyası: {p.label}"
        if t == "previous_day":
            d = period.date - timedelta(days=1)
            return self.read(set_name, date_from=d, date_to=d), f"{d:%d.%m.%Y} (tüm gün)"
        if t == "last_days":
            n = max(1, int(rng.get("days", 7)))
            d1, d0 = period.date - timedelta(days=1), period.date - timedelta(days=n)
            return self.read(set_name, date_from=d0, date_to=d1), f"önceki {n} gün: {d0:%d.%m} – {d1:%d.%m.%Y}"
        if t == "this_month":
            d0 = period.date.replace(day=1)
            return self.read(set_name, date_from=d0, date_to=period.date), f"{d0:%d.%m} – {period.date:%d.%m.%Y}"
        if t == "date_range":
            d0, d1 = date.fromisoformat(rng["from"]), date.fromisoformat(rng["to"])
            return self.read(set_name, date_from=d0, date_to=d1), f"{d0:%d.%m.%Y} – {d1:%d.%m.%Y}"
        if t == "all":
            return self.read(set_name), "tüm arşiv"
        raise ShiftFlowError(f"Bilinmeyen arşiv aralığı: {t}")


def describe_range(rng: dict | None) -> str:
    rng = rng or {"type": "previous_shift"}
    t = rng.get("type")
    if t == "last_days":
        return f"Önceki {rng.get('days', 7)} gün"
    if t == "date_range":
        return f"{rng.get('from')} – {rng.get('to')}"
    return RANGE_TYPES.get(t, t)
