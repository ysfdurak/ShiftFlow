"""Vardiya/rapor maili: taslak hazırla, kullanıcı onaylarsa gönder.

Kural: Kullanıcı onayı olmadan e-posta GÖNDERİLMEZ. Bu modül yalnızca
taslak üretir; gönderim, arayüzde kullanıcının "Gönder"e basıp onaylamasıyla
`OutlookMailer.send` üzerinden yapılır.

İki yol:
- `OutlookMailer` (Windows + Outlook, pywin32): Kullanıcının kendi Outlook
  hesabıyla taslak açar veya gönderir. Parola saklanmaz.
- `save_eml`: Taslağı .eml dosyası olarak yazar. Dosyada "X-Unsent: 1"
  olduğu için Outlook onu gönderilmemiş, düzenlenebilir taslak olarak açar.
  Outlook'a COM ile erişilemezse kullanılır.

Mail ayarları (iş akışında, run_settings["mail"]):
    {"enabled": true,
     "to": "vardiya.amiri@firma.com; depo.mudur@firma.com",
     "cc": "", "bcc": "",
     "per_shift": {"Gece": {"to": "gece.lideri@firma.com", "cc": ""}},   # vardiyaya göre EK alıcılar
     "subject": "{akis} – {vardiya} vardiyası {tarih}",
     "intro": "Merhaba,\\n{donem} raporu ektedir.",
     "summary_dataset": "Ekip Özeti", "summary_rows": 30,
     "attach": true}
"""

from __future__ import annotations

import html
import mimetypes
import os
import re
import sys
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate

import pandas as pd

from .errors import ShiftFlowError
from .excel_out import fill_placeholders

EMAIL_RE = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+$")
DEFAULT_SUBJECT = "{akis} – {vardiya} {tarih}"
DEFAULT_INTRO = "Merhaba,\n\n{donem} raporu ektedir.\n\nİyi çalışmalar."


def split_addresses(text: str | list | None) -> list[str]:
    if not text:
        return []
    if isinstance(text, list):
        text = ";".join(text)
    parts = [p.strip() for p in re.split(r"[;,\n]", text) if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def invalid_addresses(addrs: list[str]) -> list[str]:
    return [a for a in addrs if not EMAIL_RE.match(a)]


@dataclass
class MailDraft:
    to: list[str]
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject: str = ""
    html: str = ""
    text: str = ""
    attachments: list[str] = field(default_factory=list)

    def validate(self):
        if not self.to:
            raise ShiftFlowError("Mailin en az bir alıcısı olmalı (Kime).")
        bad = invalid_addresses(self.to + self.cc + self.bcc)
        if bad:
            raise ShiftFlowError("Geçersiz e-posta adresi: " + ", ".join(bad))
        for a in self.attachments:
            if not os.path.exists(a):
                raise ShiftFlowError(f"Ek dosya bulunamadı: {a}")


def _fmt(v) -> str:
    if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return f"{int(v):,}".replace(",", ".")
        return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d.%m.%Y %H:%M") if (v.hour or v.minute) else v.strftime("%d.%m.%Y")
    return str(v)


def table_html(df: pd.DataFrame, max_rows: int = 30) -> str:
    """Outlook'ta düzgün görünen, satır içi stilli basit HTML tablo."""
    th = "border:1px solid #c9d0d6;background:#dde7f0;padding:4px 8px;text-align:left;font-weight:bold"
    td = "border:1px solid #d9dee3;padding:4px 8px"
    head = "".join(f'<th style="{th}">{html.escape(str(c))}</th>' for c in df.columns)
    rows = []
    shown = df.head(max_rows)
    # Bir sütunda ondalıklı değer varsa sütunun tamamı 2 ondalıkla yazılır (50 ile 48,50 karışmasın).
    decimal_cols = {j for j, c in enumerate(shown.columns)
                    if any(isinstance(v, float) and v == v and not v.is_integer() for v in shown[c].tolist())}
    for r in shown.itertuples(index=False):
        cells = []
        for j, v in enumerate(r):
            align = "right" if isinstance(v, (int, float)) and not isinstance(v, bool) else "left"
            text = _fmt(v)
            if j in decimal_cols and isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                text = f"{float(v):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
            cells.append(f'<td style="{td};text-align:{align}">{html.escape(text)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    more = ""
    if len(df) > max_rows:
        more = f'<p style="color:#666;font-size:12px">… ilk {max_rows} satır gösterildi ({len(df)} satır var; tamamı ekte).</p>'
    return (f'<table style="border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px">'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>{more}")


def build_draft(settings: dict, context: dict, attachment: str | None = None,
                summary: pd.DataFrame | None = None, notes: list[str] | None = None) -> MailDraft:
    shift = context.get("vardiya", "")
    extra = (settings.get("per_shift") or {}).get(shift, {})
    to = split_addresses(settings.get("to")) + split_addresses(extra.get("to"))
    cc = split_addresses(settings.get("cc")) + split_addresses(extra.get("cc"))
    bcc = split_addresses(settings.get("bcc"))
    to = list(dict.fromkeys(to))
    cc = [a for a in dict.fromkeys(cc) if a not in to]
    subject = fill_placeholders(settings.get("subject") or DEFAULT_SUBJECT, context).strip(" –-")
    intro = fill_placeholders(settings.get("intro") or DEFAULT_INTRO, context)
    parts = [f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px">'
             + "<br>".join(html.escape(line) for line in intro.splitlines()) + "</div>"]
    text = [intro]
    if summary is not None and len(summary.columns):
        title = settings.get("summary_title") or settings.get("summary_dataset") or "Özet"
        parts.append(f'<h3 style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;margin:16px 0 6px">'
                     f"{html.escape(str(title))}</h3>")
        parts.append(table_html(summary, int(settings.get("summary_rows", 30))))
        text.append(summary.head(int(settings.get("summary_rows", 30))).to_string(index=False))
    if settings.get("include_notes") and notes:
        parts.append('<p style="color:#666;font-size:12px;font-family:Segoe UI,Arial,sans-serif">'
                     + "<br>".join(html.escape(n) for n in notes) + "</p>")
    parts.append('<p style="color:#999;font-size:11px;font-family:Segoe UI,Arial,sans-serif">'
                 "Bu mail ShiftFlow Data Studio ile hazırlandı.</p>")
    attachments = [attachment] if attachment and settings.get("attach", True) else []
    return MailDraft(to=to, cc=cc, bcc=bcc, subject=subject, html="\n".join(parts),
                     text="\n\n".join(text), attachments=attachments)


def save_eml(draft: MailDraft, path: str) -> str:
    """Taslağı .eml olarak kaydeder (Outlook bunu gönderilmemiş taslak olarak açar)."""
    msg = EmailMessage()
    msg["To"] = ", ".join(draft.to)
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    if draft.bcc:
        msg["Bcc"] = ", ".join(draft.bcc)
    msg["Subject"] = draft.subject
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"
    msg.set_content(draft.text)
    msg.add_alternative(f"<html><body>{draft.html}</body></html>", subtype="html")
    for a in draft.attachments:
        ctype, _ = mimetypes.guess_type(a)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(a, "rb") as fh:
            msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(a))
    if not path.lower().endswith(".eml"):
        path += ".eml"
    with open(path, "wb") as fh:
        fh.write(bytes(msg))
    return path


NO_PROFILE = ("Outlook'ta tanımlı bir e-posta hesabı yok. Outlook'u bir kez açıp hesabınızı ekleyin; "
              "o zamana kadar mail taslağı .eml dosyası olarak kaydedilir.")


class OutlookMailer:
    """Outlook (COM) ile taslak açma / onaylı gönderim. `app_factory` testler içindir."""

    def __init__(self, app_factory=None):
        self._factory = app_factory

    def available(self) -> tuple[bool, str]:
        if self._factory is not None:
            return True, ""
        if sys.platform != "win32":
            return False, "Outlook bağlantısı yalnızca Windows'ta çalışır."
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            return False, "pywin32 kurulu değil."
        if not _outlook_registered():
            return False, "Outlook bu bilgisayarda kurulu değil. Mail'i .eml dosyası olarak kaydedebilirsiniz."
        return True, ""

    def has_profile(self) -> bool:
        """Outlook'ta en az bir posta profili var mı?

        Profil yoksa Outlook.Application çağrısı "Outlook'a hoş geldiniz" kurulum sihirbazını açar
        ve zamanlanmış (pencerisiz) çalıştırma orada sonsuza dek bekler. Kayıt defterine bakılır;
        okunamıyorsa engellemez (True)."""
        if self._factory is not None or sys.platform != "win32":
            return True
        try:  # pragma: no cover - yalnız Windows
            import winreg
            for ver in ("16.0", "15.0"):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        rf"Software\Microsoft\Office\{ver}\Outlook\Profiles") as k:
                        if winreg.QueryInfoKey(k)[0] > 0:
                            return True
                except OSError:
                    continue
            return False  # hiç profil yok: Outlook ilk açılış sihirbazını gösterirdi
        except Exception:
            return True

    def _app(self):
        if self._factory is not None:
            return self._factory()
        if not self.has_profile():
            raise ShiftFlowError(NO_PROFILE)
        import win32com.client  # pragma: no cover - yalnız Windows
        try:
            return win32com.client.Dispatch("Outlook.Application")
        except Exception as exc:
            raise ShiftFlowError("Outlook'a bağlanılamadı. Outlook kurulu mu? Kurulu değilse 'E-posta dosyası "
                                 "(.eml) olarak kaydet' seçeneğini kullanın.", detail=str(exc)) from exc

    def _item(self, d: MailDraft, need_to: bool = True):
        if need_to or d.to:
            d.validate()
        try:
            item = self._app().CreateItem(0)  # 0 = olMailItem
            item.To = "; ".join(d.to)
            item.CC = "; ".join(d.cc)
            item.BCC = "; ".join(d.bcc)
            item.Subject = d.subject
            item.HTMLBody = f"<html><body>{d.html}</body></html>"
            for a in d.attachments:
                item.Attachments.Add(os.path.abspath(a))
            return item
        except ShiftFlowError:
            raise
        except Exception as exc:
            raise ShiftFlowError("Outlook maili hazırlanamadı.", detail=str(exc)) from exc

    def display(self, d: MailDraft):
        """Taslağı Outlook penceresinde açar; kullanıcı kendisi gönderir."""
        self._item(d).Display(False)

    def save_draft(self, d: MailDraft):
        """Taslağı Outlook'un Taslaklar klasörüne kaydeder (gönderilmez). Zamanlanmış çalıştırmalar için."""
        item = self._item(d, need_to=False)
        try:
            item.Save()
        except Exception as exc:
            raise ShiftFlowError("Outlook taslağı kaydedilemedi.", detail=str(exc)) from exc

    def send(self, d: MailDraft):
        """YALNIZCA kullanıcı arayüzde onay verdikten sonra çağrılır."""
        item = self._item(d)
        try:
            item.Send()
        except Exception as exc:
            raise ShiftFlowError("Mail gönderilemedi.", detail=str(exc)) from exc


def _outlook_registered() -> bool:
    """Outlook.Application COM sınıfı kayıtlı mı? Okunamazsa engellemez (True)."""
    if sys.platform != "win32":
        return False
    try:  # pragma: no cover - yalnız Windows
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return True
