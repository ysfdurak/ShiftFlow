"""Otomatik kayıt ve çökme sonrası kurtarma.

Kaydedilmemiş iş akışı birkaç saniyede bir bu bilgisayardaki gizli bir klasöre yazılır:
%LOCALAPPDATA%\\ShiftFlow\\kurtarma (Windows). Kaynak verisi de (yapıştırılan veya açık
Excel'den alınan tablolar dosyadan yeniden okunamayacağı için) yerel olarak saklanır.
Hiçbir şey ağa veya buluta gönderilmez.

Kullanıcı iş akışını kaydedince, yenisini açınca veya kaydetmeden çıkmayı seçince
kurtarma dosyaları silinir. Uygulama çökerse dosyalar kalır; bir sonraki açılışta
"kurtarılmış iş akışı" önerilir.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime

import pandas as pd

from .workflow import Workflow

VERSION = 1


def default_dir() -> str:
    base = os.environ.get("LOCALAPPDATA")
    root = os.path.join(base, "ShiftFlow") if base else os.path.join(os.path.expanduser("~"), ".shiftflow")
    return os.path.join(root, "kurtarma")


def _atomic_write(path: str, text: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


class Recovery:
    def __init__(self, folder: str | None = None):
        self.folder = folder or default_dir()
        self._written_tokens: dict[str, int] = {}
        self._last_json: str | None = None

    @property
    def meta_path(self):
        return os.path.join(self.folder, "kurtarma.json")

    # ------------------------------------------------------------------ yazma
    def save(self, session, workflow_path: str | None = None) -> bool:
        """Değişiklik varsa yazar. Yazdıysa True."""
        wf_json = session.workflow.to_json()
        tokens = {n: session._tokens.get(n) for n in session.data}
        if wf_json == self._last_json and tokens == self._written_tokens:
            return False
        os.makedirs(self.folder, exist_ok=True)
        files = {}
        for name, df in session.data.items():
            spec = session.workflow.sources.get(name)
            if spec is None or spec.archive or spec.reference_id:
                continue  # arşiv ve referans tablolar yeniden okunur
            fname = "veri_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:12] + ".pkl"
            files[name] = fname
            if self._written_tokens.get(name) != tokens.get(name) or not os.path.exists(
                    os.path.join(self.folder, fname)):
                tmp = os.path.join(self.folder, fname + ".tmp")
                df.to_pickle(tmp)
                os.replace(tmp, os.path.join(self.folder, fname))
        _atomic_write(os.path.join(self.folder, "is_akisi.json"), wf_json)
        meta = {"version": VERSION, "saved_at": datetime.now().isoformat(timespec="seconds"),
                "workflow_path": workflow_path, "workflow_name": session.workflow.name,
                "datasets": len(session.workflow.datasets), "data": files}
        _atomic_write(self.meta_path, json.dumps(meta, ensure_ascii=False, indent=1))
        self._last_json, self._written_tokens = wf_json, tokens
        return True

    def clear(self):
        self._last_json, self._written_tokens = None, {}
        if os.path.isdir(self.folder):
            shutil.rmtree(self.folder, ignore_errors=True)

    # ------------------------------------------------------------------ okuma
    def pending(self) -> dict | None:
        """Kurtarılabilir bir oturum varsa bilgisini döndürür."""
        try:
            with open(self.meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            return None
        if meta.get("version") != VERSION or not meta.get("datasets"):
            return None
        if not os.path.exists(os.path.join(self.folder, "is_akisi.json")):
            return None
        return meta

    def restore(self, session) -> list[str]:
        """İş akışını ve saklanan verileri oturuma yükler. Verisi gelmeyen kaynakları döndürür."""
        meta = self.pending()
        if meta is None:
            return []
        with open(os.path.join(self.folder, "is_akisi.json"), encoding="utf-8") as fh:
            wf = Workflow.from_json(fh.read())
        session.workflow = wf
        session.data.clear()
        session._cache.clear()
        session._undo.clear()
        session._redo.clear()
        for name, fname in (meta.get("data") or {}).items():
            path = os.path.join(self.folder, fname)
            if name in wf.sources and os.path.exists(path):
                try:
                    session._set_data(name, pd.read_pickle(path))  # yalnız bu uygulamanın yazdığı dosya
                except Exception:  # noqa: BLE001 - bozuk dosya: kaynak bağlanmamış kalır
                    pass
        session.dirty = True
        return [n for n in session.unbound_sources()
                if not (wf.sources[n].archive or wf.sources[n].reference_id)]
