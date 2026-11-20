"""'Rapor oluştur': açık raporları bul, kontrol et, iş akışını çalıştır, çıktıyı yaz.

Akış iki aşamalıdır:

1. `plan()`  — Her kaynak için veriyi bulur ve kontrol eder; hiçbir şeyi
               değiştirmez. Her kaynağın bir durumu olur:
                 ok            hazır
                 changed       değişiklik var ama iş akışını etkilemiyor (yeni sütun, sıra)
                 needs_mapping beklenen sütun yok → kullanıcı eşlemeli
                 ambiguous     tanıma uyan birden çok açık rapor var → kullanıcı seçmeli
                 not_found     açık rapor bulunamadı
                 stale         veri son başarılı çalıştırmayla birebir aynı (dünkü rapor?)
                 error         okunamadı
2. `build()` — Engelleyici durum kalmadıysa verileri bağlar, iş akışını
               çalıştırır, Excel çıktısını yazar ve geçmişe kaydeder.
               Herhangi bir veri kümesi hatalıysa dosya YAZILMAZ: eksik
               veya yanlış rapor dağıtılmasın.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import io as sio
from . import reports as rp
from .errors import ShiftFlowError

BLOCKING = {"needs_mapping", "ambiguous", "not_found", "stale", "error"}
STATUS_LABELS = {
    "ok": "Hazır", "changed": "Hazır (değişiklik var)", "needs_mapping": "Sütun eşleme gerekli",
    "ambiguous": "Birden çok uygun rapor", "not_found": "Açık rapor bulunamadı",
    "stale": "Son çalıştırmayla aynı veri", "error": "Okunamadı",
}
DEFAULT_FILE_NAME = "{akis} {tarih} {vardiya}"


@dataclass
class SourcePlan:
    source: str
    mode: str  # report | file | session
    status: str = "ok"
    report_id: str | None = None
    report_name: str = ""
    candidates: list[rp.Candidate] = field(default_factory=list)
    chosen: rp.Candidate | None = None
    path: str = ""
    df: pd.DataFrame | None = None
    changes: dict = field(default_factory=dict)
    column_map: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    stale_since: str = ""
    accept_stale: bool = False

    @property
    def blocking(self) -> bool:
        if self.status == "stale" and self.accept_stale:
            return False
        return self.status in BLOCKING

    @property
    def where(self) -> str:
        if self.mode == "reference":
            return f"Referans: {self.report_name}"
        if self.mode == "archive":
            return self.report_name or "Arşiv"
        if self.chosen:
            return self.chosen.label
        if self.path:
            return os.path.basename(self.path)
        return "—"

    @property
    def key(self) -> str:
        return self.report_id or (f"file:{os.path.normcase(os.path.abspath(self.path))}" if self.path else f"src:{self.source}")


@dataclass
class BuildResult:
    ok: bool
    path: str = ""
    sheets: list[str] = field(default_factory=list)
    errors: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class ReportBuilder:
    def __init__(self, session, library, provider=None, archive=None, period=None):
        self.session, self.library, self.provider = session, library, provider
        self.archive = archive if archive is not None else getattr(session, "archive", None)
        self.period = period
        self.workbooks = []
        self.scan_error = ""

    # ------------------------------------------------------------ planlama
    def scan(self):
        self.workbooks, self.scan_error = [], ""
        if self.provider is None:
            return
        ok, msg = self.provider.available()
        if not ok:
            self.scan_error = msg
            return
        try:
            self.workbooks = self.provider.list_workbooks()
        except ShiftFlowError as exc:
            self.scan_error = exc.message

    def plan(self) -> list[SourcePlan]:
        wf = self.session.workflow
        if not wf.sources:
            raise ShiftFlowError("İş akışında kaynak yok. Önce rapor veya dosya ekleyin.")
        if self.period is None:
            self.period = self.session.period or self.session.auto_period()
        self.session.set_period(self.period)
        if any(s.report_id for s in wf.sources.values()):
            self.scan()
        return [self._plan_source(name) for name in wf.sources]

    def _definition(self, rid):
        d = self.library.get(rid) if self.library else None
        if d is None and rid in self.session.workflow.reports:
            d = rp.ReportDefinition.from_dict(self.session.workflow.reports[rid])
        return d

    def _plan_source(self, name: str) -> SourcePlan:
        spec = self.session.workflow.sources[name]
        if spec.archive:
            sp = SourcePlan(source=name, mode="archive")
            sp.report_name = f"Arşiv: {spec.archive.get('set', '?')}"
            if self.archive is None:
                sp.status = "error"
                sp.messages.append("Rapor arşivi açılamadı.")
                return sp
            try:
                sp.df, desc = self.archive.resolve(spec.archive, self.period, self.session.shifts)
            except ShiftFlowError as exc:
                sp.status = "error"
                sp.messages.append(exc.message)
                return sp
            sp.messages.append(f"Arşivden {desc} · {len(sp.df):,} satır".replace(",", "."))
            if sp.df.empty:
                sp.messages.append("Arşivde bu döneme ait kayıt yok; boş tablo kullanılacak.")
            sp.status = "changed" if sp.df.empty else "ok"
            return sp
        if spec.reference_id:
            sp = SourcePlan(source=name, mode="reference")
            meta = self.library.reference_meta(spec.reference_id) if self.library else None
            if meta is None:
                sp.status = "error"
                sp.messages.append("Referans tablo bu bilgisayarda yok. 'Referans tablolar' bölümünden ekleyin "
                                   "veya kaynağı başka bir tabloya bağlayın.")
                return sp
            sp.report_name = meta["name"]
            sp.df = self.library.reference_df(spec.reference_id)
            sp.messages.append(f"Referans tablo · son güncelleme {meta['updated'].replace('T', ' ')[:16]}")
            self._check(sp)
            return sp
        if spec.report_id:
            sp = SourcePlan(source=name, mode="report", report_id=spec.report_id)
            d = self._definition(spec.report_id)
            if d is None:
                sp.status = "error"
                sp.messages.append("Bağlı rapor tanımı bulunamadı. Kaynağı bir rapor tanımına yeniden bağlayın.")
                return sp
            sp.report_name = d.name
            sp.candidates = rp.match_definition(d, self.workbooks)
            if not sp.candidates:
                sp.status = "not_found"
                hint = f" ({self.scan_error})" if self.scan_error else ""
                sp.messages.append(f"'{d.name}' raporu açık kitaplarda bulunamadı{hint}. "
                                   "WMS'ten raporu açıp 'Yeniden tara'ya basın veya bir dosya seçin.")
                if spec.path and os.path.exists(spec.path):
                    sp.messages.append(f"Son kullanılan dosya: {spec.path}")
                return sp
            if rp.is_ambiguous(sp.candidates):
                sp.status = "ambiguous"
                sp.messages.append("Tanıma uyan birden çok açık rapor var: "
                                   + "; ".join(c.label for c in sp.candidates[:4]) + ". Hangisinin kullanılacağını seçin.")
                return sp
            self.choose(sp, sp.candidates[0])
            return sp
        if spec.path:
            sp = SourcePlan(source=name, mode="file", path=spec.path)
            self.use_file(sp, spec.path, spec.sheet, spec.header)
            return sp
        sp = SourcePlan(source=name, mode="session")
        if name in self.session.data:
            sp.df = self.session.data[name]
            sp.messages.append("Yapıştırılmış veri; bu oturumdaki veri kullanılacak.")
            self._check(sp)
        else:
            sp.status = "not_found"
            sp.messages.append("Yapıştırma ile eklenmiş kaynak; veri yok. Yapıştırın, dosya seçin veya bir rapor tanımına bağlayın.")
        return sp

    def choose(self, sp: SourcePlan, cand: rp.Candidate):
        """Belirli bir açık raporu kullanır, okur ve kontrol eder."""
        sp.chosen, sp.messages = cand, []
        try:
            rows = self.provider.read(cand.workbook_id, cand.sheet)
            sp.df = sio.frame_from_rows(rows, cand.header_row)
        except ShiftFlowError as exc:
            sp.status, sp.df = "error", None
            sp.messages.append(exc.message)
            return
        if cand.header_row:
            sp.messages.append(f"Başlık {cand.header_row + 1}. satırda bulundu; üstteki satırlar atlandı.")
        self._check(sp)

    def use_file(self, sp: SourcePlan, path: str, sheet=None, header=True):
        sp.path, sp.chosen, sp.messages = path, None, []
        try:
            sp.df = sio.read_source(path, sheet, header)
        except ShiftFlowError as exc:
            sp.status, sp.df = ("not_found" if not (os.path.exists(path) or sio.is_pattern(path)) else "error"), None
            sp.messages.append(exc.message)
            return
        if sio.is_pattern(path):
            files = sio.folder_files(path)
            sp.messages.append(f"Klasör: {len(files)} dosya ({os.path.basename(path)})")
            sp.messages += [n for n in sp.df.attrs.get("notes", [])[1:]]
        else:
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d.%m.%Y %H:%M")
            sp.messages.append(f"Dosya: {os.path.basename(path)} (son değişiklik {mtime})")
        self._check(sp)

    def _check(self, sp: SourcePlan):
        ch = self.session.check_source(sp.source, sp.df, sp.column_map)
        sp.changes = ch
        sp.column_map = dict(ch["column_map"])
        sp.messages.extend(rp.describe_changes(ch))
        if ch["missing"]:
            sp.status = "needs_mapping"
            return
        sp.status = "changed" if (ch["extra"] or ch["type_changes"] or ch["order_changed"] or ch["auto_mapped"]) else "ok"
        if self.library is not None and sp.mode not in ("reference", "archive"):
            last = self.library.last_use(sp.key)
            if last and last[0] == rp.fingerprint(sp.df) and self._looks_stale(sp.source, last[2]):
                sp.status, sp.stale_since = "stale", last[1]
                when = sp.stale_since.replace("T", " ")[:16]
                sp.messages.append(f"Bu veri {when} tarihli çalıştırmada (başka bir dönem için) kullanılanla "
                                   "birebir aynı. Rapor güncellenmemiş olabilir.")

    def _looks_stale(self, source: str, last_period: str | None) -> bool:
        """Aynı içerik daha önce kullanıldıysa bu bir sorun mu?

        - Aynı dönem yeniden oluşturuluyorsa: sorun değil.
        - Başka bir GÜN için kullanıldıysa: büyük olasılıkla rapor yenilenmemiş.
        - Aynı gün başka bir vardiya için kullanıldıysa: kaynak dönem filtresiyle
          vardiyalara bölünüyorsa (günlük tek rapor) sorun değil; bölünmüyorsa
          her vardiyanın kendi raporu olmalı, yani yenilenmemiş.
        """
        cur = self.period
        if cur is None or not last_period:
            return True
        if last_period == cur.key:
            return False
        if last_period.split("|")[0] != cur.date.isoformat():
            return True
        return not self._filtered_by_period(source)

    def _filtered_by_period(self, source: str) -> bool:
        wf = self.session.workflow
        for d in wf.datasets.values():
            if d.origin.type == "source" and d.origin.source == source:
                if any(st.op == "period_filter" for st in d.steps):
                    return True
        return False

    def apply_mapping(self, sp: SourcePlan, mapping: dict, learn: bool = True):
        """Kullanıcının eşlemesini uygular; isteğe bağlı rapor tanımına da öğretir."""
        sp.column_map.update(mapping)
        if learn and sp.report_id and self.library:
            d = self.library.get(sp.report_id)
            if d:
                d.column_map.update(mapping)
                self.library.save(d)
        sp.messages = [m for m in sp.messages if not m.startswith(("Eksik sütun", "Yeni sütun", "Tipi", "Yazımı", "Sütun sırası"))]
        self._check(sp)
        where = " (rapor tanımına kaydedildi)" if learn and sp.report_id else ""
        sp.messages.append("Eşleme uygulandı: " + ", ".join(f"{a} → {b}" for a, b in mapping.items()) + where)

    # ------------------------------------------------------------ çıktı
    def output_path(self, now: datetime | None = None) -> str:
        wf = self.session.workflow
        rs = wf.run_settings
        folder = rs.get("output_dir") or os.path.join(os.path.expanduser("~"), "Documents", "ShiftFlow Raporları")
        template = rs.get("file_name") or DEFAULT_FILE_NAME
        name = format_file_name(template, wf.name or "Rapor", now or datetime.now(), self.period)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name + ".xlsx")
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{name} ({n}).xlsx")
            n += 1
        return path

    # ------------------------------------------------------------ arşiv
    def archive_targets(self) -> list[tuple[str, str]]:
        """[(veri kümesi, arşiv kümesi adı)] — arşivleme açıksa."""
        wf = self.session.workflow
        a = wf.run_settings.get("archive") or {}
        if not a.get("enabled"):
            return []
        sets = a.get("sets") or {}
        names = list(sets) if sets else [o["dataset"] for o in wf.outputs] or list(wf.datasets)
        base = wf.name or "İş akışı"
        return [(n, sets.get(n) or f"{base} / {n}") for n in names if n in wf.datasets]

    def archive_conflicts(self) -> list[str]:
        """Bu dönem için zaten arşivlenmiş kümeler (yeniden oluşturulursa değiştirilecek)."""
        if self.archive is None or self.period is None:
            return []
        return [s for _, s in self.archive_targets() if self.archive.has_period(s, self.period.key)]

    def write_archive(self) -> list[str]:
        if self.archive is None or self.period is None:
            return []
        notes = []
        for ds, set_name in self.archive_targets():
            replaced = self.archive.has_period(set_name, self.period.key)
            n = self.archive.write(set_name, self.session.result(ds), self.period)
            notes.append(f"Arşive yazıldı: {set_name} · {n:,} satır".replace(",", ".")
                         + (" (bu dönemin önceki kaydı değiştirildi)" if replaced else ""))
        return notes

    def placeholders(self) -> dict:
        p = self.period
        now = datetime.now()
        return {"akis": self.session.workflow.name or "Rapor",
                "tarih": (p.date if p else now.date()).strftime("%d.%m.%Y"),
                "vardiya": p.shift_label if p else "", "donem": p.label if p else "",
                "saat": now.strftime("%H:%M"), "olusturma": now.strftime("%d.%m.%Y %H:%M")}

    def build(self, plans: list[SourcePlan], path: str | None = None, archive: bool = True) -> BuildResult:
        blocking = [p for p in plans if p.blocking]
        if blocking:
            raise ShiftFlowError("Rapor oluşturulamadı; çözülmesi gereken kaynaklar var: "
                                 + ", ".join(f"{p.source} ({STATUS_LABELS[p.status]})" for p in blocking))
        self.session.set_period(self.period)
        for p in plans:
            if p.mode == "archive":
                continue  # arşiv kaynakları oturumda dönemden kendiliğinden okunur
            if p.mode == "session" and p.df is self.session.data.get(p.source):
                if p.column_map:
                    self.session.bind_source(p.source, p.df, column_map=p.column_map)
                continue
            kw = {}
            if p.mode == "report" and p.chosen:
                kw = {"path": p.chosen.path if p.chosen.saved else "", "sheet": p.chosen.sheet}
            elif p.mode == "file":
                kw = {"path": p.path}
            self.session.bind_source(p.source, p.df, column_map=p.column_map, **kw)
        with self.session.strict():
            errors = self.session.run_all()
        wfname = self.session.workflow.name or "İş akışı"
        src_log = [{"source": p.source, "key": p.key, "fingerprint": rp.fingerprint(p.df), "rows": len(p.df),
                    "status": p.status, "note": p.where} for p in plans]
        if errors:
            msg = "; ".join(f"{k}: {v.message}" for k, v in errors.items())
            if self.library:
                self.library.log_run(wfname, "error", "", msg[:2000], src_log,
                                     period=self.period.key if self.period else None)
            return BuildResult(ok=False, errors=errors,
                               notes=["Hatalı veri kümeleri olduğu için çıktı dosyası oluşturulmadı."])
        path = path or self.output_path()
        export_warnings: list[str] = []
        sheets = self.session.export(path, context=self.placeholders(), warnings=export_warnings)
        notes = []
        if self.period is not None:
            notes.append(f"Dönem: {self.period.label}")
        notes += [f"{p.source}: {p.where} · {len(p.df):,} satır".replace(",", ".") for p in plans]
        if archive:
            notes += self.write_archive()
        notes += [f"{p.source}: {m}" for p in plans for m in rp.describe_changes(p.changes)]
        notes += ["Çıktı: " + w for w in export_warnings]
        if any(p.status == "stale" for p in plans):
            notes.append("Uyarı: en az bir kaynak önceki çalıştırmayla aynı veriyle kullanıldı (onaylandı).")
        if self.library:
            self.library.log_run(wfname, "ok", path, self.period.label if self.period else "", src_log,
                                 period=self.period.key if self.period else None)
        return BuildResult(ok=True, path=path, sheets=sheets, notes=notes)


def mail_draft(builder, result: "BuildResult"):
    """Başarılı çalıştırma için mail taslağı (ayarlar açıksa). Göndermez."""
    from . import mailer
    ms = builder.session.workflow.run_settings.get("mail") or {}
    if not ms.get("enabled") or not result.ok:
        return None
    summary = None
    if ms.get("summary_dataset") in builder.session.workflow.datasets:
        summary = builder.session.result(ms["summary_dataset"])
    return mailer.build_draft(ms, builder.placeholders(), result.path, summary, result.notes)


def format_file_name(template: str, workflow_name: str, now: datetime, period=None) -> str:
    """{akis} {tarih} {vardiya} {saat} {gun} {ay} {yil} yer tutucularını doldurur.

    {tarih}, {gun}, {ay}, {yil} seçili dönemin tarihidir (yoksa bugün); {saat} oluşturma saatidir.
    """
    d = period.date if period is not None else now.date()
    values = {
        "akis": workflow_name, "tarih": d.strftime("%Y-%m-%d"), "saat": now.strftime("%H%M"),
        "gun": d.strftime("%d"), "ay": d.strftime("%m"), "yil": d.strftime("%Y"),
        "vardiya": period.shift_label if period is not None else "",
    }
    out = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)
    out = re.sub(r'[<>:"/\\|?*]', "_", out).strip() or "Rapor"
    return out[:150]
