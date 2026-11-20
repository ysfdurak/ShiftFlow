"""Rapor kütüphanesi ve çalıştırma geçmişi (SQLite, yerel dosya).

Konum: %LOCALAPPDATA%\\ShiftFlow\\shiftflow.db (Windows)
       ~/.shiftflow/shiftflow.db (diğer)

Saklananlar: rapor tanımları (sütun adları/tipleri, tanıma kuralları),
çalıştırma kayıtları (zaman, durum, çıktı yolu, satır sayısı, içerik
özeti), referans tablolar (kullanıcının bilerek kaydettiği sabit tablolar,
örn. lokasyon-bölge listesi) ve uygulama ayarları (vardiya tanımları).
Rapor arşivi ayrı bir dosyadadır (archive.py).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from .errors import ShiftFlowError
import uuid

import pandas as pd

from .reports import ReportDefinition
from .values import type_kind

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, data TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, workflow TEXT, status TEXT NOT NULL,
    output TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id INTEGER NOT NULL, source TEXT, report_key TEXT, fingerprint TEXT, rows INTEGER,
    status TEXT, note TEXT, FOREIGN KEY(run_id) REFERENCES runs(id));
CREATE INDEX IF NOT EXISTS ix_run_sources_key ON run_sources(report_key);
CREATE TABLE IF NOT EXISTS ref_tables (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, note TEXT, rows INTEGER, columns TEXT,
    data TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trash (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, item_id TEXT, name TEXT, payload TEXT NOT NULL,
    deleted TEXT NOT NULL);
"""
TRASH_DAYS = 30
TRASH_KINDS = {"report": "Rapor tanımı", "reference": "Referans tablo", "reference_old": "Referans tablo (eski içerik)"}


def default_db_path() -> str:
    base = os.environ.get("LOCALAPPDATA")
    folder = os.path.join(base, "ShiftFlow") if base else os.path.join(os.path.expanduser("~"), ".shiftflow")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "shiftflow.db")


class ReportLibrary:
    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False)  # tek iş parçacığı kullanır; arayüz görev sırasında kilitli
            self.db.executescript(SCHEMA)
            cols = [r[1] for r in self.db.execute("PRAGMA table_info(runs)")]
            if "period" not in cols:  # 3.2 öncesi kütüphaneler
                self.db.execute("ALTER TABLE runs ADD COLUMN period TEXT")
            self.db.commit()
            self.purge_trash()
        except sqlite3.Error as exc:
            raise ShiftFlowError("Rapor kütüphanesi açılamadı.", detail=f"{self.path}: {exc}") from exc

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ tanımlar
    def list(self) -> list[ReportDefinition]:
        rows = self.db.execute("SELECT data FROM reports ORDER BY name COLLATE NOCASE").fetchall()
        return [ReportDefinition.from_dict(json.loads(r[0])) for r in rows]

    def get(self, rid: str) -> ReportDefinition | None:
        r = self.db.execute("SELECT data FROM reports WHERE id=?", (rid,)).fetchone()
        return ReportDefinition.from_dict(json.loads(r[0])) if r else None

    def by_name(self, name: str) -> ReportDefinition | None:
        r = self.db.execute("SELECT data FROM reports WHERE name=?", (name,)).fetchone()
        return ReportDefinition.from_dict(json.loads(r[0])) if r else None

    def save(self, d: ReportDefinition, touch: bool = True) -> ReportDefinition:
        if not d.name.strip():
            raise ShiftFlowError("Rapor tanımı için bir ad girin.")
        if not d.key_columns:
            raise ShiftFlowError("Raporu tanımak için en az bir sütun seçin.")
        other = self.by_name(d.name)
        if other and other.id != d.id:
            raise ShiftFlowError(f"'{d.name}' adlı bir rapor tanımı zaten var. Farklı bir ad seçin.")
        if touch:
            d.touch()
        self.db.execute("INSERT OR REPLACE INTO reports(id, name, data, updated) VALUES (?,?,?,?)",
                        (d.id, d.name, json.dumps(d.to_dict(), ensure_ascii=False), d.updated))
        self.db.commit()
        return d

    def delete(self, rid: str):
        self._to_trash("report", "reports", rid)
        self.db.execute("DELETE FROM reports WHERE id=?", (rid,))
        self.db.commit()

    # ------------------------------------------------------------ çöp kutusu (30 gün)
    def _to_trash(self, kind: str, table: str, rid: str):
        cur = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (rid,))
        row = cur.fetchone()
        if row is None:
            return
        names = [d[0] for d in cur.description]
        rec = dict(zip(names, row))
        self.db.execute("INSERT INTO trash(kind, item_id, name, payload, deleted) VALUES (?,?,?,?,?)",
                        (kind, rid, rec.get("name"), json.dumps(rec, ensure_ascii=False),
                         datetime.now().isoformat(timespec="seconds")))

    def trash(self) -> list[dict]:
        rows = self.db.execute("SELECT id, kind, name, deleted FROM trash ORDER BY id DESC").fetchall()
        return [dict(zip(("id", "kind", "name", "deleted"), r)) for r in rows]

    def purge_trash(self, days: int = TRASH_DAYS):
        from datetime import timedelta
        limit = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        self.db.execute("DELETE FROM trash WHERE deleted < ?", (limit,))
        self.db.commit()

    def restore(self, trash_id: int) -> str:
        """Silinen rapor tanımını / referans tabloyu geri getirir. Aynı adla yenisi varsa ad sonuna ' (geri)' eklenir."""
        r = self.db.execute("SELECT kind, payload FROM trash WHERE id=?", (trash_id,)).fetchone()
        if r is None:
            raise ShiftFlowError("Çöp kutusunda bu kayıt yok.")
        kind, payload = r
        rec = json.loads(payload)
        table = "reports" if kind == "report" else "ref_tables"
        if kind == "reference_old":
            cur = self.db.execute("SELECT 1 FROM ref_tables WHERE id=?", (rec["id"],)).fetchone()
            if cur:
                self._to_trash("reference_old", "ref_tables", rec["id"])
                self.db.execute("DELETE FROM ref_tables WHERE id=?", (rec["id"],))
        name = rec["name"]
        while self.db.execute(f"SELECT 1 FROM {table} WHERE name=? AND id<>?", (name, rec["id"])).fetchone():
            name += " (geri)"
        rec["name"] = name
        if kind == "report":
            try:
                d = json.loads(rec["data"])
                d["name"] = name
                rec["data"] = json.dumps(d, ensure_ascii=False)
            except (ValueError, TypeError):
                pass
        if self.db.execute(f"SELECT 1 FROM {table} WHERE id=?", (rec["id"],)).fetchone():
            rec["id"] = uuid.uuid4().hex[:12]
        cols = list(rec)
        self.db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [rec[c] for c in cols])
        self.db.execute("DELETE FROM trash WHERE id=?", (trash_id,))
        self.db.commit()
        return name

    def merge(self, d: ReportDefinition) -> str:
        """İş akışıyla gelen tanımı kütüphaneye alır. Kütüphanedeki daha yeniyse dokunmaz.
        Dönen değer: 'added' | 'updated' | 'kept'."""
        cur = self.get(d.id)
        if cur is None:
            if self.by_name(d.name):
                d.name = f"{d.name} ({d.id[-4:]})"
            self.save(d, touch=False)
            return "added"
        if d.updated > cur.updated:
            self.save(d, touch=False)
            return "updated"
        return "kept"

    # ------------------------------------------------------------ geçmiş
    def log_run(self, workflow: str, status: str, output: str = "", message: str = "",
                sources: list[dict] | None = None, period: str | None = None) -> int:
        cur = self.db.execute("INSERT INTO runs(ts, workflow, status, output, message, period) VALUES (?,?,?,?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), workflow, status, output, message, period))
        rid = cur.lastrowid
        for s in sources or []:
            self.db.execute(
                "INSERT INTO run_sources(run_id, source, report_key, fingerprint, rows, status, note) VALUES (?,?,?,?,?,?,?)",
                (rid, s.get("source"), s.get("key"), s.get("fingerprint"), s.get("rows"), s.get("status"), s.get("note")))
        self.db.commit()
        return rid

    def last_fingerprint(self, key: str) -> tuple[str, str] | None:
        """Bu rapor için son BAŞARILI çalıştırmadaki içerik özeti ve zamanı."""
        r = self.last_use(key)
        return (r[0], r[1]) if r else None

    def last_use(self, key: str) -> tuple[str, str, str | None] | None:
        """(içerik özeti, zaman, dönem anahtarı) — son başarılı çalıştırma."""
        r = self.db.execute(
            "SELECT s.fingerprint, r.ts, r.period FROM run_sources s JOIN runs r ON r.id=s.run_id "
            "WHERE s.report_key=? AND r.status='ok' ORDER BY r.id DESC LIMIT 1", (key,)).fetchone()
        return (r[0], r[1], r[2]) if r else None

    def recent_runs(self, n: int = 50) -> list[dict]:
        rows = self.db.execute("SELECT id, ts, workflow, status, output, message FROM runs ORDER BY id DESC LIMIT ?",
                               (n,)).fetchall()
        return [dict(zip(("id", "ts", "workflow", "status", "output", "message"), r)) for r in rows]

    # ------------------------------------------------------------ ayarlar
    def get_setting(self, key: str, default=None):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_setting(self, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    # ------------------------------------------------------------ referans tablolar
    def save_reference(self, name: str, df: pd.DataFrame, note: str = "", rid: str | None = None) -> dict:
        """Sabit bir tabloyu kaydeder. `rid` verilirse o tablonun içeriği yenilenir."""
        name = name.strip()
        if not name:
            raise ShiftFlowError("Referans tablo için bir ad girin.")
        other = self.db.execute("SELECT id FROM ref_tables WHERE name=?", (name,)).fetchone()
        if other and other[0] != rid:
            raise ShiftFlowError(f"'{name}' adlı bir referans tablo zaten var.")
        if rid:
            self._to_trash("reference_old", "ref_tables", rid)  # içerik yenilenmeden önceki hâli
        rid = rid or "t_" + uuid.uuid4().hex[:10]
        types = [type_kind(df[c]) for c in df.columns]

        def cell(v):
            if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and v != v):
                return None
            if isinstance(v, pd.Timestamp):
                return v.isoformat()
            if hasattr(v, "item"):
                return v.item()
            return v
        rows = [[cell(v) for v in r] for r in df.itertuples(index=False)]
        payload = json.dumps({"columns": [str(c) for c in df.columns], "types": types, "rows": rows},
                             ensure_ascii=False, default=str)
        now = datetime.now().isoformat(timespec="seconds")
        cols = json.dumps([{"name": str(c), "type": t} for c, t in zip(df.columns, types)], ensure_ascii=False)
        self.db.execute("INSERT OR REPLACE INTO ref_tables(id, name, note, rows, columns, data, updated) "
                        "VALUES (?,?,?,?,?,?,?)", (rid, name, note, len(df), cols, payload, now))
        self.db.commit()
        return self.reference_meta(rid)

    def reference_meta(self, rid: str) -> dict | None:
        r = self.db.execute("SELECT id, name, note, rows, columns, updated FROM ref_tables WHERE id=?",
                            (rid,)).fetchone()
        if not r:
            return None
        return {"id": r[0], "name": r[1], "note": r[2], "rows": r[3], "columns": json.loads(r[4]), "updated": r[5]}

    def list_references(self) -> list[dict]:
        ids = [r[0] for r in self.db.execute("SELECT id FROM ref_tables ORDER BY name COLLATE NOCASE")]
        return [self.reference_meta(i) for i in ids]

    def reference_df(self, rid: str) -> pd.DataFrame:
        r = self.db.execute("SELECT data FROM ref_tables WHERE id=?", (rid,)).fetchone()
        if not r:
            raise ShiftFlowError("Referans tablo bu bilgisayarda yok. 'Referans tablolar' bölümünden ekleyin.")
        d = json.loads(r[0])
        df = pd.DataFrame(d["rows"], columns=d["columns"], dtype=object)
        for c, t in zip(d["columns"], d["types"]):
            if t == "number":
                df[c] = pd.to_numeric(df[c], errors="coerce")
                if df[c].notna().all() and (df[c] % 1 == 0).all():
                    df[c] = df[c].astype("int64")
            elif t == "date":
                df[c] = pd.to_datetime(df[c], errors="coerce")
        return df

    def delete_reference(self, rid: str):
        self._to_trash("reference", "ref_tables", rid)
        self.db.execute("DELETE FROM ref_tables WHERE id=?", (rid,))
        self.db.commit()
