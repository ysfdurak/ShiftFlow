"""Komut satırı modu: pencere açmadan rapor paketi veya tek iş akışı çalıştırır.

    ShiftFlow.exe --paket "Vardiya sonu.sfpaket.json" --donem otomatik --mail outlook
    ShiftFlow.exe --akis "Toplama.json" --donem 2026-11-10:Gece --mail eml

Windows Görev Zamanlayıcı ile vardiya sonlarında çalıştırmak için tasarlandı.

* Dönem "otomatik" ise saatten hesaplanır: vardiya bitiminden sonraki 2 saat içinde biten vardiya seçilir.
* Mail asla gönderilmez: `outlook` taslağı Outlook'un Taslaklar klasörüne kaydeder, `eml` dosya olarak
  çıktının yanına yazar, `yok` hiç hazırlamaz.
* Karar gerektiren durumlarda (sütun adı değişmiş, rapor bulunamadı, aynı veri…) o akış atlanır.
  Atlanan veya hatalı akış varsa bir "ShiftFlow uyarısı" taslağı da hazırlanır.
* Her çalıştırma %LOCALAPPDATA%\\ShiftFlow\\calistirma_gunlugu.txt dosyasına yazılır (hücre değerleri yazılmaz).
* Çıkış kodu: 0 hepsi oluşturuldu, 1 bazıları atlandı/hatalı, 2 çalıştırılamadı.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

FLAGS = ("--paket", "--akis")


def wants_cli(argv) -> bool:
    return any(a in FLAGS or a.startswith(tuple(f + "=" for f in FLAGS)) for a in argv)


def _appdir() -> str:
    base = os.environ.get("LOCALAPPDATA")
    d = os.path.join(base, "ShiftFlow") if base else os.path.join(os.path.expanduser("~"), ".shiftflow")
    os.makedirs(d, exist_ok=True)
    return d


def log_path() -> str:
    return os.path.join(_appdir(), "calistirma_gunlugu.txt")


def _log(lines: list[str]) -> str:
    path = log_path()
    try:
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:  # 2 MB'ı geçince eskisini sakla
            os.replace(path, path + ".eski")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n\n")
    except OSError:
        pass
    return path


class _Lock:
    """Aynı anda iki zamanlanmış çalıştırma olmasın (önceki uzun sürdüyse)."""

    def __init__(self):
        self.path = os.path.join(_appdir(), "calistirma.kilit")
        self.ok = False

    def __enter__(self):
        if os.path.exists(self.path):
            try:
                age = datetime.now().timestamp() - os.path.getmtime(self.path)
            except OSError:
                age = 0
            if age < 3 * 3600:  # 3 saatten eski kilit: önceki çalıştırma yarıda kalmış sayılır
                return self
        with open(self.path, "w") as fh:
            fh.write(str(os.getpid()))
        self.ok = True
        return self

    def __exit__(self, *exc):
        if self.ok:
            try:
                os.remove(self.path)
            except OSError:
                pass


def parse_period(text: str, session, now: datetime | None = None):
    """'otomatik' | '2026-11-10' | '2026-11-10:Gece' | '10.11.2026:Gece'"""
    from .engine import periods as pr
    text = (text or "otomatik").strip()
    if text.lower() in ("otomatik", "auto"):
        return session.auto_period(now)
    day, _, shift = text.partition(":")
    try:
        d = date.fromisoformat(day) if "-" in day else datetime.strptime(day, "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValueError(f"Dönem anlaşılamadı: {text} (örn. otomatik, 2026-11-10:Gece, 10.11.2026)") from exc
    names = [s["name"] for s in session.shifts]
    if shift and shift not in names:
        raise ValueError(f"Vardiya bulunamadı: {shift}. Tanımlı vardiyalar: {', '.join(names)}")
    return pr.make_period(d, shift or None, session.shifts)


def run(argv=None, provider=None, library=None, archive=None, outlook=None, now: datetime | None = None) -> int:
    from .engine import mailer
    from .engine import package as pk
    from .engine.errors import ShiftFlowError
    from .engine.session import Session

    ap = argparse.ArgumentParser(prog="ShiftFlow",
                                 description="Rapor paketini veya iş akışını pencere açmadan çalıştırır.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--paket", help="rapor paketi dosyası (.sfpaket.json)")
    g.add_argument("--akis", help="iş akışı dosyası (.json)")
    ap.add_argument("--donem", default="otomatik", help="otomatik | 2026-11-10 | 2026-11-10:Gece")
    ap.add_argument("--mail", choices=("outlook", "eml", "yok"), default="eml",
                    help="outlook: Taslaklar'a kaydet · eml: dosya olarak · yok (mail asla gönderilmez)")
    a = ap.parse_args(argv)

    started = now or datetime.now()
    head = f"=== {started:%d.%m.%Y %H:%M:%S} · {'paket' if a.paket else 'akış'}: {a.paket or a.akis}"
    try:
        if a.paket:
            pkg = pk.ReportPackage.load(a.paket)
        else:
            if not os.path.exists(a.akis):
                raise ShiftFlowError(f"İş akışı dosyası bulunamadı: {a.akis}")
            pkg = pk.ReportPackage(name=os.path.splitext(os.path.basename(a.akis))[0],
                                   workflows=[os.path.abspath(a.akis)])
        if not pkg.workflows:
            raise ShiftFlowError("Pakette iş akışı yok.")
        if library is None:
            from .engine.library import ReportLibrary
            library = ReportLibrary()
        if archive is None:
            from .engine.archive import Archive
            try:
                archive = Archive()
            except ShiftFlowError:
                archive = None
        if provider is None:
            from .engine.excel_live import default_provider
            provider = default_provider()
        s0 = Session()  # vardiya tanımı ve dönem kipi ilk iş akışından
        s0.library = library
        if os.path.exists(pkg.workflows[0]):
            try:
                s0.load_workflow(pkg.workflows[0])
            except ShiftFlowError:
                pass
        period = parse_period(a.donem, s0, now)
    except (ShiftFlowError, ValueError) as exc:
        msg = exc.message if isinstance(exc, ShiftFlowError) else str(exc)
        _log([head, "ÇALIŞTIRILAMADI: " + msg])
        print("ÇALIŞTIRILAMADI:", msg, file=sys.stderr)
        return 2

    lines = [head, f"Dönem: {period.label}"]
    with _Lock() as lock:
        if not lock.ok:
            _log(lines + ["Atlandı: başka bir ShiftFlow çalıştırması sürüyor."])
            return 1
        results = pk.run_package(pkg, library, provider, archive, period)
        drafts = []
        for r in results:
            lines.append(f"{r.label}: {r.name}" + (f" → {r.path}" if r.path else "")
                         + (f" · {r.message}" if r.message else ""))
            if r.draft is not None:
                drafts.append((r.draft, r.path))
        comb = pk.combined_draft(pkg, results, period)
        if comb is not None:
            drafts = [(comb, next((r.path for r in results if r.path), ""))]
        problems = [r for r in results if r.status != "ok"]
        if problems:
            text = "\n".join(f"{r.name}: {r.label} — {r.message}" for r in problems)
            warn = mailer.MailDraft(to=mailer.split_addresses((pkg.mail or {}).get("to")),
                                    subject=f"ShiftFlow uyarısı: {len(problems)} rapor oluşturulamadı ({period.label})",
                                    html="<pre>" + text.replace("<", "&lt;") + "</pre>", text=text)
            drafts.append((warn, None))
        out_dir = next((os.path.dirname(r.path) for r in results if r.path), _appdir())
        mail_mode = a.mail
        if mail_mode == "outlook" and outlook is None and not mailer.OutlookMailer().has_profile():
            # Profilsiz Outlook kurulum sihirbazını açar ve görev orada takılır; .eml'e geçilir.
            lines.append("Outlook'ta e-posta hesabı yok; taslaklar .eml dosyası olarak kaydedildi.")
            mail_mode = "eml"
        if mail_mode != "yok":
            for d, ref_path in drafts:
                try:
                    if mail_mode == "outlook":
                        (outlook or mailer.OutlookMailer()).save_draft(d)
                        lines.append(f"Mail taslağı Outlook Taslaklar klasörüne kaydedildi: {d.subject}")
                    else:
                        base = os.path.splitext(ref_path)[0] if ref_path else os.path.join(
                            out_dir, f"ShiftFlow_uyari_{started:%Y%m%d_%H%M}")
                        lines.append(f"Mail taslağı: {mailer.save_eml(d, base + '.eml')}")
                except ShiftFlowError as exc:
                    lines.append(f"Mail hazırlanamadı: {exc.message}")
    path = _log(lines)
    print("\n".join(lines))
    print(f"Günlük: {path}")
    return 0 if not problems else 1


def main(argv=None) -> int:
    return run(argv)
