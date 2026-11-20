"""Rapor paketleri: birden çok iş akışını aynı dönem için sırayla çalıştırma.

Paket dosyası (.sfpaket.json) yalnız iş akışı dosyalarının yollarını ve paket ayarlarını tutar;
iş akışlarının kendisi değişmez. Her iş akışı ayrı bir oturumda açılır, açık raporlar/dosyalar
bulunur (ReportBuilder.plan) ve sorunsuzsa çıktı oluşturulur. Çözülmesi gereken kaynağı olan
(sütun eşleme, iki aday rapor, bulunamayan rapor, aynı veri) iş akışı atlanır ve özette bildirilir;
bu kararlar kullanıcıya bırakılır, tahminle geçilmez.

Mail: paket ayarında birleşik mail açıksa tüm çıktılar tek taslağa eklenir (gönderim yine
kullanıcı onayıyla). Kapalıysa her iş akışının kendi mail ayarı kullanılır.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .errors import ShiftFlowError, WorkflowError

FORMAT_ID = "shiftflow-paket"
EXT = ".sfpaket.json"


@dataclass
class ReportPackage:
    name: str = "Rapor paketi"
    workflows: list[str] = field(default_factory=list)  # iş akışı dosya yolları (sırayla)
    stop_on_error: bool = False  # bir iş akışı oluşturulamazsa kalanları çalıştırma
    archive_mode: str = "replace"  # dönem arşivde varsa: replace | skip
    mail: dict = field(default_factory=dict)  # birleşik mail: {"enabled", "to", "cc", "subject", "body"}

    def to_json(self, base: str | None = None) -> str:
        paths = []
        for p in self.workflows:
            if base:
                try:
                    rel = os.path.relpath(p, base)
                    p = rel if not rel.startswith("..") or os.path.splitdrive(p)[0] == os.path.splitdrive(base)[0] \
                        else p
                except ValueError:  # farklı sürücü (Windows)
                    pass
            paths.append(p)
        return json.dumps({"format": FORMAT_ID, "version": 1, "name": self.name, "workflows": paths,
                           "stop_on_error": self.stop_on_error, "archive_mode": self.archive_mode,
                           "mail": self.mail}, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str, base: str | None = None) -> "ReportPackage":
        try:
            d = json.loads(text)
        except ValueError as exc:
            raise WorkflowError("Paket dosyası okunamadı (bozuk).") from exc
        if not isinstance(d, dict) or d.get("format") != FORMAT_ID:
            raise WorkflowError("Bu dosya bir ShiftFlow rapor paketi değil.")
        wfs = [p if os.path.isabs(p) or not base else os.path.normpath(os.path.join(base, p))
               for p in d.get("workflows", [])]
        return cls(name=d.get("name", "Rapor paketi"), workflows=wfs, stop_on_error=bool(d.get("stop_on_error")),
                   archive_mode=d.get("archive_mode", "replace"), mail=dict(d.get("mail") or {}))

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json(os.path.dirname(os.path.abspath(path))))

    @classmethod
    def load(cls, path: str) -> "ReportPackage":
        try:
            with open(path, encoding="utf-8") as fh:
                return cls.from_json(fh.read(), os.path.dirname(os.path.abspath(path)))
        except OSError as exc:
            raise WorkflowError("Paket dosyası açılamadı.", detail=str(exc)) from exc


@dataclass
class PackageItemResult:
    workflow: str  # dosya yolu
    name: str
    status: str  # ok | skipped | error | not_run
    path: str = ""
    message: str = ""
    notes: list[str] = field(default_factory=list)
    draft: object = None  # iş akışının kendi mail taslağı (birleşik mail kapalıysa)

    @property
    def label(self) -> str:
        return {"ok": "✓ Oluşturuldu", "skipped": "⚠ Atlandı", "error": "✖ Hata",
                "not_run": "— Çalıştırılmadı"}[self.status]


def run_package(pkg: ReportPackage, library, provider, archive, period, progress=None) -> list[PackageItemResult]:
    """Paketi çalıştırır. progress(i, n, metin) her iş akışından önce çağrılır."""
    from .autorun import STATUS_LABELS, ReportBuilder, mail_draft
    from .session import Session
    results: list[PackageItemResult] = []
    stop = False
    for i, path in enumerate(pkg.workflows):
        name = os.path.splitext(os.path.basename(path))[0]
        if stop:
            results.append(PackageItemResult(path, name, "not_run", message="Önceki iş akışı hatalı olduğu için."))
            continue
        if progress:
            progress(i, len(pkg.workflows), name)
        s = Session()
        s.library, s.archive = library, archive
        try:
            wf = s.load_workflow(path)
            name = wf.name or name
            s.archive = archive
            b = ReportBuilder(s, library, provider, archive, period)
            plans = b.plan()
            blocking = [p for p in plans if p.blocking]
            if blocking:
                results.append(PackageItemResult(
                    path, name, "skipped",
                    message="Çözülmesi gereken kaynak var: " + ", ".join(
                        f"{p.source} ({STATUS_LABELS[p.status]})" for p in blocking)
                    + ". Bu iş akışını ayrıca açıp Rapor oluştur'u çalıştırın.",
                    notes=[m for p in blocking for m in p.messages][:6]))
                stop = pkg.stop_on_error
                continue
            write_arc = not (pkg.archive_mode == "skip" and b.archive_conflicts())
            res = b.build(plans, archive=write_arc)
        except ShiftFlowError as exc:
            results.append(PackageItemResult(path, name, "error", message=exc.message))
            stop = pkg.stop_on_error
            continue
        if not res.ok:
            msg = "; ".join(f"{k}: {v.message}" for k, v in res.errors.items())
            results.append(PackageItemResult(path, name, "error", message=msg[:500], notes=res.notes))
            stop = pkg.stop_on_error
            continue
        item = PackageItemResult(path, name, "ok", path=res.path, notes=res.notes)
        if not write_arc:
            item.notes = item.notes + ["Dönem arşivde vardı; arşive yazılmadı (paket ayarı)."]
        if not (pkg.mail or {}).get("enabled"):
            try:
                item.draft = mail_draft(b, res)
            except ShiftFlowError as exc:
                item.notes.append("Mail hazırlanamadı: " + exc.message)
        results.append(item)
    return results


def combined_draft(pkg: ReportPackage, results: list[PackageItemResult], period=None):
    """Birleşik mail taslağı: oluşturulan tüm dosyalar ek olarak. Göndermez."""
    from . import mailer
    ms = dict(pkg.mail or {})
    if not ms.get("enabled"):
        return None
    files = [r.path for r in results if r.status == "ok" and r.path]
    if not files:
        return None
    from datetime import datetime
    now = datetime.now()
    ctx = {"akis": pkg.name, "tarih": (period.date if period else now.date()).strftime("%d.%m.%Y"),
           "vardiya": period.shift_label if period else "", "donem": period.label if period else "",
           "saat": now.strftime("%H:%M"), "olusturma": now.strftime("%d.%m.%Y %H:%M")}
    lines = [f"{r.name}: {r.label}" + (f" — {r.message}" if r.message else "") for r in results]
    ms.setdefault("subject", "{akis} — {tarih} {vardiya}")
    ms.setdefault("include_notes", True)
    draft = mailer.build_draft(ms, ctx, files[0], None, lines)
    draft.attachments = files
    return draft
