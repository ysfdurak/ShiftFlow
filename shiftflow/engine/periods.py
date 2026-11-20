"""Vardiya tanımları ve rapor dönemi (tarih + vardiya).

Kurallar:
- Vardiyalar bir kez tanımlanır (ad, başlangıç, bitiş). Gece yarısını geçen
  vardiya (22:00–06:00) desteklenir.
- Bir vardiyanın TARİHİ, başladığı gündür. 22:00–06:00 vardiyası 03:00'te
  hâlâ bir önceki günün vardiyasıdır.
- Dönem kullanıcı tarafından seçilir. Varsayılan değer saatten hesaplanır:
  şu anki vardiyanın başlangıcından bu yana "tolerans" süresinden az zaman
  geçtiyse rapor biten (önceki) vardiya içindir; aksi hâlde şu anki vardiya.
  Örnek: 16:00'da başlayan vardiyada saat 16:40 ise varsayılan 08:00–16:00
  vardiyasıdır, çünkü vardiya sonu raporu biten vardiya için hazırlanır.
- Vardiya yerine "Tüm gün" de seçilebilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .errors import ShiftFlowError

DEFAULT_SHIFTS = [
    {"name": "Gece", "start": "00:00", "end": "08:00"},
    {"name": "Gündüz", "start": "08:00", "end": "16:00"},
    {"name": "Akşam", "start": "16:00", "end": "00:00"},
]
DEFAULT_GRACE_MINUTES = 120
WHOLE_DAY = "Tüm gün"


def _t(s: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(s))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ShiftFlowError(f"Saat '{s}' anlaşılamadı. SS:DD biçiminde yazın (örn. 08:00).")
    return time(int(m.group(1)), int(m.group(2)))


def window(shift: dict, d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, _t(shift["start"]))
    end = datetime.combine(d, _t(shift["end"]))
    if end <= start:
        end += timedelta(days=1)
    return start, end


def validate_shifts(shifts: list[dict]) -> list[dict]:
    if not shifts:
        raise ShiftFlowError("En az bir vardiya tanımlayın.")
    names = [s.get("name", "").strip() for s in shifts]
    if any(not n for n in names):
        raise ShiftFlowError("Her vardiyanın bir adı olmalı.")
    if len(set(n.lower() for n in names)) != len(names):
        raise ShiftFlowError("Vardiya adları farklı olmalı.")
    if WHOLE_DAY.lower() in (n.lower() for n in names):
        raise ShiftFlowError(f"'{WHOLE_DAY}' ayrılmış bir addır.")
    d0 = date(2026, 1, 5)
    wins = []
    for s in shifts:
        a, b = window(s, d0)
        if b - a > timedelta(hours=24):
            raise ShiftFlowError(f"{s['name']}: vardiya 24 saatten uzun olamaz.")
        wins.append((a, b, s["name"]))
    # Çakışma: her vardiyayı ardışık iki gün için karşılaştır.
    for i, (a1, b1, n1) in enumerate(wins):
        for j, s2 in enumerate(shifts):
            if i == j:
                continue
            for off in (-1, 0, 1):
                a2, b2 = window(s2, d0 + timedelta(days=off))
                if a1 < b2 and a2 < b1:
                    raise ShiftFlowError(f"'{n1}' ve '{s2['name']}' vardiyalarının saatleri çakışıyor.")
    return [{"name": n, "start": _t(s["start"]).strftime("%H:%M"), "end": _t(s["end"]).strftime("%H:%M")}
            for n, s in zip(names, shifts)]


@dataclass
class Period:
    date: date
    shift: str | None  # None: tüm gün
    start: datetime
    end: datetime
    auto: bool = False

    @property
    def shift_label(self) -> str:
        return self.shift or WHOLE_DAY

    @property
    def key(self) -> str:
        return f"{self.date.isoformat()}|{self.shift_label}"

    @property
    def label(self) -> str:
        span = f"{self.start:%H:%M}–{self.end:%H:%M}"
        return f"{self.date:%d.%m.%Y} · {self.shift_label} ({span})"

    def context(self) -> dict:
        return {"date": self.date.isoformat(), "shift": self.shift_label, "start": self.start.isoformat(),
                "end": self.end.isoformat(), "key": self.key}


def make_period(d: date, shift_name: str | None, shifts: list[dict], auto=False) -> Period:
    if not shift_name or shift_name == WHOLE_DAY:
        start = datetime.combine(d, time(0, 0))
        return Period(d, None, start, start + timedelta(days=1), auto)
    for s in shifts:
        if s["name"] == shift_name:
            a, b = window(s, d)
            return Period(d, shift_name, a, b, auto)
    raise ShiftFlowError(f"'{shift_name}' adlı vardiya tanımlı değil.")


def current(now: datetime, shifts: list[dict]) -> Period | None:
    for off in (0, -1):
        d = (now + timedelta(days=off)).date()
        for s in shifts:
            a, b = window(s, d)
            if a <= now < b:
                return Period(d, s["name"], a, b)
    return None


def previous(p: Period, shifts: list[dict]) -> Period:
    """Bir önceki vardiya (bitişi bu vardiyanın başlangıcına en yakın olan)."""
    if p.shift is None:
        return make_period(p.date - timedelta(days=1), None, shifts)
    best = None
    for off in (0, -1, -2):
        d = p.date + timedelta(days=off)
        for s in shifts:
            a, b = window(s, d)
            if b <= p.start and (best is None or b > best.end or (b == best.end and a > best.start)):
                best = Period(d, s["name"], a, b)
    if best is None:  # pragma: no cover - en az bir vardiya varken olmaz
        raise ShiftFlowError("Önceki vardiya bulunamadı.")
    return best


def same_shift_previous_day(p: Period, shifts: list[dict]) -> Period:
    return make_period(p.date - timedelta(days=1), p.shift, shifts)


def auto_period(now: datetime, shifts: list[dict], grace_minutes: int = DEFAULT_GRACE_MINUTES,
                mode: str = "shift") -> Period:
    """Saatten varsayılan dönemi hesaplar (kullanıcı değiştirebilir)."""
    if mode == "day":
        return make_period(now.date(), None, shifts, auto=True)
    cur = current(now, shifts)
    if cur is None:  # vardiyalar günü kapsamıyorsa: son biten vardiya
        probe = Period(now.date(), "__", now, now)
        p = previous(probe, shifts)
    elif now - cur.start < timedelta(minutes=grace_minutes):
        p = previous(cur, shifts)
    else:
        p = cur
    p.auto = True
    return p


def from_context(ctx: dict | None) -> Period | None:
    if not ctx:
        return None
    return Period(date.fromisoformat(ctx["date"]), None if ctx["shift"] == WHOLE_DAY else ctx["shift"],
                  datetime.fromisoformat(ctx["start"]), datetime.fromisoformat(ctx["end"]))
