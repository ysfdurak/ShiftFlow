"""Kullanıcıya gösterilecek, anlaşılır hata sınıfları.

Kural: Her hata mesajı teknik kod değil, operasyon kullanıcısının
anlayacağı Türkçe bir cümledir. Teknik ayrıntı gerekiyorsa `detail`
alanına konur ve arayüzde "Ayrıntılar" altında gösterilir.
"""

from __future__ import annotations


class ShiftFlowError(Exception):
    """Tüm ShiftFlow hatalarının ortak atası."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - basit
        return self.message


def suggest_column(name, available) -> str | None:
    """Yazım hatasına en yakın sütun adı (harf/boşluk farkı, eksik kelime): 'Toplanan' → 'Toplanan Adet'."""
    import difflib
    tr = str.maketrans("İIŞĞÜÖÇ", "iışğüöç")

    def norm(x):
        return " ".join(str(x).translate(tr).lower().split())
    n = norm(name)
    pool = {norm(a): str(a) for a in available}
    if n in pool:
        return pool[n]
    starts = [a for k, a in pool.items() if k.startswith(n) or n.startswith(k)]
    if len(starts) == 1:
        return starts[0]
    m = difflib.get_close_matches(n, list(pool), n=1, cutoff=0.75)
    return pool[m[0]] if m else None


class MissingColumnError(ShiftFlowError):
    def __init__(self, columns, available, step_label: str = ""):
        self.columns = list(columns)
        self.available = list(available)
        names = ", ".join(f"'{c}'" for c in self.columns)
        where = f" ({step_label})" if step_label else ""
        msg = (
            f"Sütun bulunamadı{where}: {names}. "
            "Rapor biçimi değişmiş olabilir; sütun adının yeni dosyada farklı "
            "yazılıp yazılmadığını kontrol edin."
        )
        self.suggestions = {c: suggest_column(c, self.available) for c in self.columns}
        hints = [f"[{c}] yerine [{s}]" for c, s in self.suggestions.items() if s]
        if hints:
            msg += " Bunu mu demek istediniz: " + ", ".join(hints) + "?"
        avail = ", ".join(self.available[:30])
        super().__init__(msg, detail=f"Mevcut sütunlar: {avail}")


class TypeMismatchError(ShiftFlowError):
    pass


class JoinConfirmationRequired(ShiftFlowError):
    """Çoktan-çoğa birleştirme gibi riskli durumlarda kullanıcı onayı ister."""

    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


class WorkflowError(ShiftFlowError):
    pass


class DataImportError(ShiftFlowError):
    pass


class ExportError(ShiftFlowError):
    pass


class Cancelled(ShiftFlowError):
    """Kullanıcı uzun süren işlemi iptal etti. Yarım kalan değişiklik geri alınır."""

    def __init__(self, message: str = "İşlem iptal edildi; değişiklik uygulanmadı."):
        super().__init__(message)
