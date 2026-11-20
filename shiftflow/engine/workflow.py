"""İş akışı tanımı (veriden bağımsız) ve JSON biçimi.

Yapı:
    Kaynak (Source)   : Dosya/yapıştırma tanımı. Verinin kendisi saklanmaz.
    Veri kümesi       : Bir başlangıç (kaynak veya birleştirme/pivot gibi
                        birden çok girdili işlem) + doğrusal adım listesi.
    Bağımlılıklar     : Veri kümeleri başka veri kümelerini girdi alabilir.
                        Bu, veri kümeleri düzeyinde yönlendirilmiş döngüsüz
                        bir grafik (DAG) oluşturur. Döngüye izin verilmez.

Bir veri kümesine yeni adım eklendiğinde, ona bağlı pivot/birleştirme
otomatik olarak güncel sonucu görür; çünkü girdiler adım kimliğine değil
veri kümesi adına bağlıdır.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import operations
from .errors import WorkflowError

FORMAT_ID = "shiftflow-workflow"
SCHEMA_VERSION = 3


def new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class SourceSpec:
    name: str
    kind: str = "file"  # "file" | "paste" | "report" | "reference" | "archive"
    path: str = ""
    sheet: str | None = None
    header: bool = True
    expected_columns: list[dict] = field(default_factory=list)  # [{"name":..,"type":..}]
    column_map: dict = field(default_factory=dict)  # gelen ad -> beklenen ad
    report_id: str | None = None  # bağlı rapor tanımı (açık raporlardan otomatik bulunur)
    reference_id: str | None = None  # kütüphanedeki referans tablo (sabit veri)
    archive: dict | None = None  # arşiv kaynağı: {"set":..., "range": {...}}


@dataclass
class Step:
    op: str
    params: dict
    id: str = field(default_factory=new_id)
    note: str = ""
    enabled: bool = True  # kapalı adım atlanır (silmeden etkisini görmek için)


@dataclass
class Origin:
    type: str  # "source" veya çok girdili işlem anahtarı (join, append, group, pivot, copy)
    source: str | None = None
    inputs: list[str] = field(default_factory=list)  # veri kümesi adları
    params: dict = field(default_factory=dict)


@dataclass
class Dataset:
    name: str
    origin: Origin
    steps: list[Step] = field(default_factory=list)


@dataclass
class Workflow:
    name: str = "Yeni iş akışı"
    sources: dict[str, SourceSpec] = field(default_factory=dict)
    datasets: dict[str, Dataset] = field(default_factory=dict)  # ekleme sırası korunur
    outputs: list[dict] = field(default_factory=list)  # [{"dataset":..,"sheet":..}]
    # Çıktı ayarları: {"output_dir":.., "file_name":.., "open_after": bool}
    run_settings: dict = field(default_factory=dict)
    # Kullanılan rapor tanımlarının kopyası: iş akışı başka bilgisayara
    # taşındığında tanımlar da gelsin diye. {rapor_id: tanım sözlüğü}
    reports: dict = field(default_factory=dict)

    # ------------------------------------------------------------ sorgular
    def dataset(self, name: str) -> Dataset:
        if name not in self.datasets:
            raise WorkflowError(f"'{name}' adlı veri kümesi yok.")
        return self.datasets[name]

    def inputs_of(self, name: str) -> list[str]:
        return list(self.dataset(name).origin.inputs)

    def deps(self, name: str) -> list[str]:
        """Veri kümesinin okuduğu tüm veri kümeleri: başlangıç girdileri + adımların
        başvurduğu tablolar (örn. DÜŞEYARA arama tablosu)."""
        ds = self.datasets[name]
        out = list(ds.origin.inputs)
        for st in ds.steps:
            op = operations.REGISTRY.get(st.op)
            if op and op.refs:
                out.extend(r for r in op.refs(st.params) if r not in out)
        return out

    def dependents_of(self, name: str) -> list[str]:
        """`name` veri kümesini doğrudan veya dolaylı kullanan veri kümeleri."""
        out, frontier = [], [name]
        while frontier:
            cur = frontier.pop()
            for d in self.datasets.values():
                if cur in self.deps(d.name) and d.name not in out:
                    out.append(d.name)
                    frontier.append(d.name)
        return out

    def topo_order(self) -> list[str]:
        """Bağımlılık sırası. Döngü varsa açıklayıcı hata verir."""
        state, order = {}, []

        def visit(n, path):
            if state.get(n) == 2:
                return
            if state.get(n) == 1:
                cyc = " → ".join(path[path.index(n):] + [n])
                raise WorkflowError(f"İş akışında döngüsel bağımlılık var: {cyc}")
            if n not in self.datasets:
                raise WorkflowError(f"'{path[-1] if path else n}' veri kümesi olmayan '{n}' kümesine bağlı.")
            state[n] = 1
            for i in self.deps(n):
                visit(i, path + [n])
            state[n] = 2
            order.append(n)

        for n in self.datasets:
            visit(n, [])
        return order

    def unique_name(self, base: str) -> str:
        base = base.strip() or "Veri"
        name, n = base, 1
        while name in self.datasets or name in self.sources:
            n += 1
            name = f"{base} {n}"
        return name

    # ------------------------------------------------------------ JSON
    def to_dict(self) -> dict:
        return {
            "format": FORMAT_ID,
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "sources": [asdict(s) for s in self.sources.values()],
            "datasets": [
                {
                    "name": d.name,
                    "origin": asdict(d.origin),
                    "steps": [asdict(s) for s in d.steps],
                }
                for d in self.datasets.values()
            ],
            "outputs": copy.deepcopy(self.outputs),
            "run_settings": copy.deepcopy(self.run_settings),
            "reports": copy.deepcopy(self.reports),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "Workflow":
        if not isinstance(data, dict) or data.get("format") != FORMAT_ID:
            raise WorkflowError("Bu dosya bir ShiftFlow iş akışı değil.")
        ver = data.get("schema_version", 1)
        if ver > SCHEMA_VERSION:
            raise WorkflowError(
                f"İş akışı daha yeni bir ShiftFlow sürümüyle kaydedilmiş (biçim {ver}). Uygulamayı güncelleyin."
            )
        data = migrate(data)
        try:
            wf = cls(name=data.get("name", "İş akışı"))
            for s in data.get("sources", []):
                wf.sources[s["name"]] = SourceSpec(**s)
            for d in data.get("datasets", []):
                o = d["origin"]
                ds = Dataset(
                    name=d["name"],
                    origin=Origin(**o),
                    steps=[Step(**s) for s in d.get("steps", [])],
                )
                wf.datasets[ds.name] = ds
            wf.outputs = list(data.get("outputs", []))
            wf.run_settings = dict(data.get("run_settings", {}))
            wf.reports = dict(data.get("reports", {}))
        except (KeyError, TypeError) as exc:
            raise WorkflowError("İş akışı dosyası eksik veya bozuk.", detail=str(exc)) from exc
        wf.validate()
        return wf

    @classmethod
    def from_json(cls, text: str) -> "Workflow":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowError("İş akışı dosyası okunamadı (geçersiz JSON).", detail=str(exc)) from exc
        return cls.from_dict(data)

    def validate(self):
        for d in self.datasets.values():
            o = d.origin
            if o.type == "source":
                if o.source not in self.sources:
                    raise WorkflowError(f"'{d.name}' tanımsız '{o.source}' kaynağına bağlı.")
            else:
                operations.get(o.type)
            for s in d.steps:
                op = operations.get(s.op)
                if op.inputs != "1" or op.new_dataset:
                    raise WorkflowError(f"'{d.name}' içindeki '{op.label}' adımı adım listesinde kullanılamaz.")
        self.topo_order()
        for out in self.outputs:
            if out.get("dataset") not in self.datasets:
                raise WorkflowError(f"Çıktı listesinde olmayan veri kümesi var: {out.get('dataset')}")

    def clone(self) -> "Workflow":
        return Workflow.from_dict(json.loads(self.to_json()))


# Sürüm geçişleri: {eski_sürüm: fonksiyon(dict)->dict}. Biçim değiştiğinde
# buraya bir dönüştürücü eklenir; eski iş akışları açılmaya devam eder.
def _v1_to_v2(data: dict) -> dict:
    """Sürüm 2: rapor tanımı bağlantısı, çıktı ayarları, gömülü tanımlar."""
    data = copy.deepcopy(data)
    for s in data.get("sources", []):
        s.setdefault("report_id", None)
    data.setdefault("run_settings", {})
    data.setdefault("reports", {})
    data["schema_version"] = 2
    return data


def _v2_to_v3(data: dict) -> dict:
    """Sürüm 3: referans tablo ve arşiv kaynakları."""
    data = copy.deepcopy(data)
    for s in data.get("sources", []):
        s.setdefault("reference_id", None)
        s.setdefault("archive", None)
    data["schema_version"] = 3
    return data


MIGRATIONS: dict[int, callable] = {1: _v1_to_v2, 2: _v2_to_v3}


def migrate(data: dict) -> dict:
    ver = data.get("schema_version", SCHEMA_VERSION)
    while ver < SCHEMA_VERSION:
        fn = MIGRATIONS.get(ver)
        if fn is None:
            raise WorkflowError(f"İş akışı biçimi {ver} desteklenmiyor.")
        data = fn(data)
        ver = data["schema_version"]
    return data


def _run_copy(inputs, p, label):
    return operations.OpResult(inputs[0].copy())


operations.register(operations.Operation(
    "copy", "Kopya", _run_copy, lambda p: "Kopya", inputs="1", new_dataset=True,
))
