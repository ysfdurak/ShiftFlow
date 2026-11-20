"""Çalışma oturumu: iş akışı + yüklenmiş veriler + hesaplama + geri alma.

Arayüz yalnızca bu sınıfı kullanır; pandas veya işlem ayrıntılarını
bilmez. Böylece aynı motor ileride komut satırından, zamanlanmış
görevlerden veya RPA'dan da çalıştırılabilir.

Önemli kurallar:
- Kaynak veriler (`self.data`) hiçbir zaman yerinde değiştirilmez.
- Her değişiklik önce denenir; yeni bir hataya yol açarsa geri alınır.
- Sonuçlar imza (işlem + parametre + girdi imzaları) ile önbelleğe alınır.
  Geri al / yinele bu yüzden yeniden hesaplama gerektirmez.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import variants
from . import io as sio
from . import expression, operations, periods, reports
from .errors import Cancelled, JoinConfirmationRequired, ShiftFlowError, WorkflowError
from .values import type_kind
from .workflow import Dataset, Origin, SourceSpec, Step, Workflow

CACHE_SIZE = 48
UNDO_LIMIT = 100


@dataclass
class StepStatus:
    label: str
    rows_before: int | None = None
    rows_after: int | None = None
    cols_after: int | None = None
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: ShiftFlowError | None = None
    variants: dict = field(default_factory=dict)  # {sütun: {en_sık: [yazılışlar]}}


class StepFailure(ShiftFlowError):
    """Belirli bir veri kümesinin belirli adımında oluşan hata."""

    def __init__(self, dataset: str, index: int, label: str, cause: ShiftFlowError):
        where = "başlangıç" if index < 0 else f"{index + 1}. adım"
        super().__init__(f"{dataset} › {where} ({label}): {cause.message}", detail=cause.detail)
        self.dataset, self.index, self.label, self.cause = dataset, index, label, cause


class UpstreamFailure(ShiftFlowError):
    pass


def _h(*parts) -> str:
    m = hashlib.sha1()
    for p in parts:
        m.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode())
        m.update(b"|")
    return m.hexdigest()


class Session:
    def __init__(self):
        self.workflow = Workflow()
        self.data: dict[str, pd.DataFrame] = {}
        self._tokens: dict[str, int] = {}
        self._token_seq = 0
        self._cache: OrderedDict[str, tuple[pd.DataFrame, StepStatus]] = OrderedDict()
        self._undo: list[str] = []
        self._redo: list[str] = []
        self.dirty = False
        self.library = None  # ReportLibrary (isteğe bağlı): rapor tanımları ve geçmiş
        # Çalıştırma bağlamı: seçili dönem (tarih, vardiya, başlangıç/bitiş). Dönem
        # filtresi ve arşiv kaynakları bunu kullanır.
        self.context: dict | None = None
        self._ref_versions: dict[str, str] = {}
        self.archive = None  # Archive (isteğe bağlı): rapor arşivi
        self._arc_keys: dict[str, tuple] = {}
        self.archive_desc: dict[str, str] = {}
        # Uzun işlemler için (arayüz arka planda çalıştırırken ayarlar)
        # True iken "Raporu durdur" doğrulamaları hata verir (Rapor oluştur / Excel'e aktar sırasında)
        self.strict_validation = False
        self.cancel_event = None  # threading.Event: ayarlanınca bir sonraki adımda Cancelled
        self.progress = None  # callable(metin): hangi adımın hesaplandığını bildirir

    def _tick(self, text: str):
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            raise Cancelled()
        if self.progress is not None:
            try:
                self.progress(text)
            except Exception:  # pragma: no cover - ilerleme bildirimi hesaplamayı bozmasın
                pass

    # ================================================================ kaynaklar
    def add_source(self, name: str, df: pd.DataFrame, kind="file", path="", sheet=None, header=True,
                   report_id: str | None = None, reference_id: str | None = None,
                   archive: dict | None = None) -> str:
        name = self.workflow.unique_name(name)
        spec = SourceSpec(
            name=name, kind=kind, path=path, sheet=sheet, header=header, report_id=report_id,
            reference_id=reference_id, archive=archive,
            expected_columns=[{"name": str(c), "type": type_kind(df[c])} for c in df.columns],
        )

        def mut(wf: Workflow):
            wf.sources[name] = spec
            wf.datasets[name] = Dataset(name=name, origin=Origin(type="source", source=name))
        self._set_data(name, df)
        self._commit(mut, focus=name)
        return name

    def _set_data(self, name, df):
        self.data[name] = df
        self._token_seq += 1
        self._tokens[name] = self._token_seq

    def check_source(self, name: str, df: pd.DataFrame, column_map: dict | None = None) -> dict:
        """Yeni gelen verinin iş akışının beklediği sütunlarla uyumunu kontrol eder."""
        spec = self.workflow.sources[name]
        cmap = dict(spec.column_map)
        if spec.report_id and self.library:
            d = self.library.get(spec.report_id)
            if d:
                cmap = {**d.column_map, **cmap}
        cmap.update(column_map or {})
        return reports.compare_columns(spec.expected_columns, df, cmap)

    def bind_source(self, name: str, df: pd.DataFrame, path: str | None = None, sheet=None,
                    header: bool | None = None, column_map: dict | None = None):
        """Kaynağa yeni veri bağlar (yeni tarihli rapor). Geri alınamaz değil:
        iş akışı tanımı değişmez, yalnızca veri değişir."""
        if name not in self.workflow.sources:
            raise WorkflowError(f"'{name}' adlı kaynak yok.")
        spec = self.workflow.sources[name]
        before = (dict(spec.column_map), spec.path, spec.sheet, spec.header, spec.kind)
        if column_map:
            spec.column_map = {**spec.column_map, **column_map}
        if path is not None:
            spec.path = path
            spec.kind = "report" if spec.report_id else ("file" if path else "paste")
        if sheet is not None:
            spec.sheet = sheet
        if header is not None:
            spec.header = header
        self._set_data(name, df)
        # Yalnız veri yenilendiyse iş akışı değişmiş sayılmaz.
        if (spec.column_map, spec.path, spec.sheet, spec.header, spec.kind) != before:
            self.dirty = True

    def refresh_references(self):
        """Referans tablo kaynaklarını kütüphanedeki güncel içerikle yükler."""
        if not self.library:
            return
        for name, spec in self.workflow.sources.items():
            if not spec.reference_id:
                continue
            meta = self.library.reference_meta(spec.reference_id)
            if meta is None:
                continue
            if self._ref_versions.get(name) != meta["updated"] or name not in self.data:
                self._set_data(name, self.library.reference_df(spec.reference_id))
                self._ref_versions[name] = meta["updated"]

    # ---------------------------------------------------------------- dönem ve arşiv
    @property
    def shifts(self) -> list[dict]:
        if self.library:
            return self.library.get_setting("shifts", periods.DEFAULT_SHIFTS)
        return periods.DEFAULT_SHIFTS

    @property
    def grace_minutes(self) -> int:
        if self.library:
            return int(self.library.get_setting("shift_grace_minutes", periods.DEFAULT_GRACE_MINUTES))
        return periods.DEFAULT_GRACE_MINUTES

    def auto_period(self, now: datetime | None = None):
        mode = self.workflow.run_settings.get("period_mode", "shift")
        return periods.auto_period(now or datetime.now(), self.shifts, self.grace_minutes,
                                   "day" if mode == "day" else "shift")

    def set_period(self, period):
        """Çalıştırma dönemini ayarlar. Dönem filtresi ve arşiv kaynakları buna göre hesaplanır."""
        self.context = period.context() if period is not None else None

    @property
    def period(self):
        return periods.from_context(self.context)

    def _ensure_archive(self, name: str):
        spec = self.workflow.sources.get(name)
        if spec is None or not spec.archive or self.archive is None:
            return
        key = (json.dumps(spec.archive, sort_keys=True), (self.context or {}).get("key"), self.archive.version)
        if self._arc_keys.get(name) == key and name in self.data:
            return
        df, desc = self.archive.resolve(spec.archive, self.period, self.shifts)
        self._set_data(name, df)
        self._arc_keys[name] = key
        self.archive_desc[name] = desc

    def source_frame(self, name: str) -> pd.DataFrame:
        spec = self.workflow.sources.get(name)
        if spec is not None and spec.archive and self.archive is not None:
            self._ensure_archive(name)
        if name not in self.data and spec is not None and spec.reference_id and self.library:
            self.refresh_references()
        if name not in self.data:
            raise UpstreamFailure(f"'{name}' kaynağının verisi yüklenmedi. 'Kaynakları bağla' ile dosya seçin.")
        spec = self.workflow.sources[name]
        df = self.data[name]
        cmap = {k: v for k, v in spec.column_map.items() if k in df.columns and k != v}
        return df.rename(columns=cmap) if cmap else df

    def unbound_sources(self) -> list[str]:
        return [s for s in self.workflow.sources if s not in self.data]

    def source_paths(self) -> list[str]:
        return [s.path for s in self.workflow.sources.values() if s.path]

    # ================================================================ hesaplama
    def _origin_sig(self, ds: Dataset) -> str:
        o = ds.origin
        if o.type == "source":
            try:
                self._ensure_archive(o.source)
            except ShiftFlowError:
                pass  # hata, hesaplama sırasında kullanıcıya gösterilir
            return _h("src", o.source, self._tokens.get(o.source), self.workflow.sources[o.source].column_map)
        return _h(o.type, o.params, [self._final_sig(i) for i in o.inputs])

    def _final_sig(self, name: str) -> str:
        ds = self.workflow.dataset(name)
        sig = self._origin_sig(ds)
        for s in ds.steps:
            op = operations.REGISTRY.get(s.op)
            refs = op.refs(s.params) if op and op.refs else []
            ctx = self.context if op and op.uses_context else None
            sig = _h(sig, s.op, s.params, [self._final_sig(r) for r in refs], ctx)
        return sig

    def _cache_get(self, sig):
        if sig in self._cache:
            self._cache.move_to_end(sig)
            return self._cache[sig]
        return None

    def _cache_put(self, sig, val):
        self._cache[sig] = val
        self._cache.move_to_end(sig)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)

    def _compute(self, name: str, upto: int | None, _stack=()) -> tuple[pd.DataFrame, list[StepStatus]]:
        """Veri kümesini başlangıçtan `upto` adımına kadar hesaplar.
        upto=None tüm adımlar, -1 yalnızca başlangıç."""
        if name in _stack:
            raise WorkflowError("Döngüsel bağımlılık: " + " → ".join(_stack + (name,)))
        ds = self.workflow.dataset(name)
        statuses: list[StepStatus] = []
        o = ds.origin
        sig = self._origin_sig(ds)
        hit = self._cache_get(sig)
        if o.type == "source":
            label = f"Kaynak: {o.source}"
        else:
            label = operations.get(o.type).describe(o.params)
        if hit:
            df, st = hit
        else:
            self._tick(f"{name}: {label}")
            st = StepStatus(label=label)
            if o.type == "source":
                df = self.source_frame(o.source)
                st.messages.append(f"{len(df):,} satır × {df.shape[1]} sütun".replace(",", "."))
            else:
                inputs = []
                for i in o.inputs:
                    try:
                        inputs.append(self._compute(i, None, _stack + (name,))[0])
                    except Cancelled:
                        raise
                    except ShiftFlowError as exc:
                        raise UpstreamFailure(f"Girdi veri kümesi '{i}' hatalı: {exc.message}") from exc
                op = operations.get(o.type)
                try:
                    res = op.run(inputs, o.params, label)
                except JoinConfirmationRequired:
                    raise  # arayüz kullanıcıdan onay ister
                except ShiftFlowError as exc:
                    raise StepFailure(name, -1, label, exc) from exc
                df = res.df
                st.rows_before = sum(len(x) for x in inputs) if o.type == "append" else len(inputs[0])
                st.messages, st.warnings = res.messages, list(res.warnings)
                if inputs:
                    st.variants = variants.check(inputs[0], o.type, o.params)
                    st.warnings += variants.describe(st.variants)
            st.rows_after, st.cols_after = len(df), df.shape[1]
            self._cache_put(sig, (df, st))
        statuses.append(st)
        last = len(ds.steps) - 1 if upto is None else upto
        for idx, step in enumerate(ds.steps[: last + 1]):
            op = operations.get(step.op)
            if not step.enabled:
                sig = _h(sig, "kapalı", idx)
                statuses.append(StepStatus(label="(kapalı) " + op.describe(step.params), rows_before=len(df),
                                           rows_after=len(df), cols_after=df.shape[1],
                                           messages=["Adım kapalı; veri değişmeden sonraki adıma geçer."]))
                continue
            refs = op.refs(step.params) if op.refs else []
            ctx = self.context if op.uses_context else None
            wparams = self.parameters if op.uses_params else None
            strict = self.strict_validation if step.op == "validate" else None
            sig = _h(sig, step.op, step.params, [self._final_sig(r) for r in refs], ctx, wparams or None, strict)
            hit = self._cache_get(sig)
            if hit:
                df, st = hit
            else:
                label = op.describe(step.params)
                self._tick(f"{name} › {idx + 1}. adım: {label}")
                extra = []
                for r in refs:
                    try:
                        extra.append(self._compute(r, None, _stack + (name,))[0])
                    except Cancelled:
                        raise
                    except ShiftFlowError as exc:
                        raise StepFailure(name, idx, label, ShiftFlowError(
                            f"Başvurulan '{r}' veri kümesi hatalı: {exc.message}")) from exc
                params = dict(step.params, __context__=ctx) if ctx is not None else step.params
                if wparams:
                    params = dict(params, __params__=wparams)
                if strict:
                    params = dict(params, __strict__=True)
                try:
                    res = op.run([df] + extra, params, label)
                except ShiftFlowError as exc:
                    raise StepFailure(name, idx, label, exc) from exc
                found = variants.check(df, step.op, step.params)
                st = StepStatus(label=label, rows_before=len(df), rows_after=len(res.df),
                                cols_after=res.df.shape[1], messages=res.messages,
                                warnings=list(res.warnings) + variants.describe(found), variants=found)
                df = res.df
                self._cache_put(sig, (df, st))
            statuses.append(st)
        return df, statuses

    def result(self, name: str, upto: int | None = None) -> pd.DataFrame:
        return self._compute(name, upto)[0]

    def step_statuses(self, name: str) -> list[StepStatus]:
        """Başlangıç + her adımın durumu. Hatalı adım ve sonrası işaretlenir."""
        ds = self.workflow.dataset(name)
        labels = [self._origin_label(ds)] + [operations.get(s.op).describe(s.params) for s in ds.steps]
        try:
            return self._compute(name, None)[1]
        except StepFailure as f:
            try:
                ok = self._compute(name, f.index - 1)[1] if f.index >= 0 else []
            except ShiftFlowError:
                ok = []
            out = list(ok)
            out.append(StepStatus(label=labels[len(out)], error=f.cause))
            for lab in labels[len(out):]:
                out.append(StepStatus(label=lab, error=ShiftFlowError("Önceki adım hatalı olduğu için çalıştırılmadı.")))
            return out
        except ShiftFlowError as exc:
            return [StepStatus(label=lab, error=exc) for lab in labels]

    def _origin_label(self, ds):
        if ds.origin.type == "source":
            return f"Kaynak: {ds.origin.source}"
        return operations.get(ds.origin.type).describe(ds.origin.params)

    def run_all(self) -> dict[str, ShiftFlowError]:
        """Tüm veri kümelerini sırayla hesaplar. {veri kümesi: hata} döner."""
        errors = {}
        for name in self.workflow.topo_order():
            try:
                self._compute(name, None)
            except Cancelled:
                raise
            except ShiftFlowError as exc:
                errors[name] = exc
        return errors

    # ================================================================ değişiklikler
    def _snapshot(self) -> str:
        return self.workflow.to_json()

    def _commit(self, mutate, focus: str | None = None, check: list[str] | None = None):
        """Değişikliği uygular; yeni hata çıkarsa geri alır ve hatayı yükseltir."""
        before = self._snapshot()
        before_errors = set(self._errors_for(check or list(self.workflow.datasets)))
        trial = self.workflow.clone()
        mutate(trial)
        trial.validate()
        old = self.workflow
        self.workflow = trial
        targets = check if check is not None else ([focus] if focus else [])
        if focus and focus in trial.datasets:
            targets = list(dict.fromkeys(targets + [focus] + trial.dependents_of(focus)))
        for t in targets:
            if t not in trial.datasets or t in before_errors:
                continue
            try:
                self._compute(t, None)
            except Cancelled:
                self.workflow = old
                raise
            except ShiftFlowError as exc:
                self.workflow = old
                if t != focus and focus:
                    raise ShiftFlowError(
                        f"Bu değişiklik '{t}' veri kümesini bozuyor: {exc.message}", detail=exc.detail
                    ) from exc
                raise
        if self.cancel_event is not None and self.cancel_event.is_set():
            self.workflow = old
            raise Cancelled()
        self._undo.append(before)
        self._undo = self._undo[-UNDO_LIMIT:]
        self._redo.clear()
        self.dirty = True

    def _errors_for(self, names):
        out = []
        for n in names:
            if n not in self.workflow.datasets:
                continue
            try:
                self._compute(n, None)
            except ShiftFlowError:
                out.append(n)
        return out

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self._snapshot())
        self.workflow = Workflow.from_json(self._undo.pop())
        self.dirty = True

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self._snapshot())
        self.workflow = Workflow.from_json(self._redo.pop())
        self.dirty = True

    # ---------------------------------------------------------------- adımlar
    def add_step(self, dataset: str, op: str, params: dict, position: int | None = None) -> str:
        o = operations.get(op)
        if o.inputs != "1" or o.new_dataset:
            raise ShiftFlowError(f"'{o.label}' yeni veri kümesi oluşturur; adım olarak eklenemez.")
        step = Step(op=op, params=params)

        def mut(wf):
            steps = wf.dataset(dataset).steps
            steps.insert(len(steps) if position is None else position, step)
        self._commit(mut, focus=dataset)
        return step.id

    def edit_step(self, dataset: str, index: int, params: dict):
        def mut(wf):
            wf.dataset(dataset).steps[index].params = params
        self._commit(mut, focus=dataset)

    def delete_step(self, dataset: str, index: int):
        def mut(wf):
            del wf.dataset(dataset).steps[index]
        self._commit(mut, focus=dataset)

    def move_step(self, dataset: str, index: int, delta: int):
        steps = self.workflow.dataset(dataset).steps
        new = index + delta
        if not 0 <= new < len(steps):
            return index

        def mut(wf):
            st = wf.dataset(dataset).steps
            st.insert(new, st.pop(index))
        self._commit(mut, focus=dataset)
        return new

    def excel_formulas(self, dataset: str, df=None) -> dict:
        """Çıktıda Excel formülü olarak yazılacak sütunlar: {sütun: şablon}."""
        out = {}
        if dataset not in self.workflow.datasets:
            return out
        for st in self.workflow.dataset(dataset).steps:
            if st.op == "excel_formula" and st.enabled:
                out[st.params["name"]] = st.params["template"]
            elif st.op in ("rename",):
                m = st.params.get("mapping") or {}
                out = {m.get(k, k): v for k, v in out.items()}
        if df is not None:
            out = {k: v for k, v in out.items() if k in df.columns}
        return out

    def add_formula_steps(self, dataset: str, steps: list[dict]) -> int:
        """Excel'deki formüllü sütunları tek seferde 'Hesaplanan sütun' adımı olarak ekler.

        Bu sütunlar artık ShiftFlow'da hesaplandığı için kaynağın beklenen sütunlarından çıkarılır:
        ertesi günkü ham raporda bulunmamaları "sütun eksik" uyarısı vermez."""
        names = {p["name"] for p in steps}

        def mut(wf):
            ds = wf.dataset(dataset)
            if ds.origin.type == "source" and not any(
                    st.op == "drop_empty_rows" for st in ds.steps[:1]):
                # Excel'de formüller veri bittikten sonra da aşağı çekilmiş olabilir: o satırlar atılır,
                # formüller yalnız dolu satır sayısı kadar uygulanır.
                ds.steps.insert(0, Step(op="drop_empty_rows", params={"ignore": sorted(names)},
                                        note="Excel'de formülün aşağı çekildiği boş satırlar"))
            for p in steps:
                p = dict(p)
                op = p.pop("_op", "calc")
                note = "Excel formülünden alındı" if op == "calc" else "Excel'de hesaplanır (çıktıya formül yazılır)"
                ds.steps.append(Step(op=op, params=p, note=note))
            if ds.origin.type == "source":
                spec = wf.sources[ds.origin.source]
                spec.expected_columns = [c for c in spec.expected_columns if c.get("name") not in names]
        self._commit(mut, focus=dataset)
        return len(steps)

    def set_step_enabled(self, dataset: str, index: int, enabled: bool):
        def mut(wf):
            wf.dataset(dataset).steps[index].enabled = bool(enabled)
        self._commit(mut, focus=dataset)

    def set_step_note(self, dataset: str, index: int, note: str):
        def mut(wf):
            wf.dataset(dataset).steps[index].note = (note or "").strip()
        self._commit(mut, focus=dataset)

    def duplicate_step(self, dataset: str, index: int) -> int:
        """Adımın kopyasını hemen arkasına ekler; yeni adımın sırasını döndürür."""
        src = self.workflow.dataset(dataset).steps[index]
        params = json.loads(json.dumps(src.params))
        if src.op in ("calc", "conditional", "rules") and params.get("name") and not params.get("replace"):
            try:
                cols = set(map(str, self.result(dataset, index).columns))
            except ShiftFlowError:
                cols = set()
            base, k = f"{params['name']} (kopya)", 2
            name = base
            while name in cols:
                name, k = f"{base} {k}", k + 1
            params["name"] = name  # aynı adlı sütun çakışmasın

        def mut(wf):
            wf.dataset(dataset).steps.insert(index + 1, Step(op=src.op, params=params,
                                                              note=src.note, enabled=src.enabled))
        self._commit(mut, focus=dataset)
        return index + 1

    def variants_at(self, dataset: str, index: int) -> dict:
        """Adımın (index=-1: başlangıç) bulduğu farklı yazılışlar."""
        try:
            sts = self._compute(dataset, index)[1]
        except ShiftFlowError:
            return {}
        return sts[-1].variants if sts else {}

    def fix_variants(self, dataset: str, index: int, columns: list[str]):
        """Farklı yazılışları birleştiren adımı, sorunu bulan adımın önüne ekler.

        index=-1 (gruplama/pivot gibi başlangıç işlemi) için girdi veri kümesinin sonuna eklenir.
        Hemen önünde zaten bir "Yazımı birleştir" adımı varsa sütunlar ona eklenir."""
        ds = self.workflow.dataset(dataset)
        if index < 0:
            if not ds.origin.inputs:
                raise ShiftFlowError("Bu veri kümesinin girdisi yok.")
            target, pos = ds.origin.inputs[0], None
        else:
            target, pos = dataset, index
        tds = self.workflow.dataset(target)
        prev_i = (len(tds.steps) if pos is None else pos) - 1

        def mut(wf):
            steps = wf.dataset(target).steps
            if prev_i >= 0 and steps[prev_i].op == "unify":
                cols = list(steps[prev_i].params.get("columns", []))
                cols += [c for c in columns if c not in cols]
                steps[prev_i].params = dict(steps[prev_i].params, columns=cols)
            else:
                steps.insert(len(steps) if pos is None else pos, Step(op="unify", params={"columns": list(columns)}))
        self._commit(mut, focus=dataset)

    def ignore_variants(self, dataset: str, index: int):
        """Bu adım için farklı yazılış uyarısını kapatır."""
        def mut(wf):
            ds = wf.dataset(dataset)
            target = ds.origin if index < 0 else ds.steps[index]
            target.params = dict(target.params, ignore_variants=True)
        self._commit(mut, focus=dataset)

    # ---------------------------------------------------------------- veri kümeleri
    def add_derived(self, name: str, op: str, inputs: list[str], params: dict) -> str:
        """Birleştirme, alt alta ekleme, gruplama, pivot veya kopya ile yeni veri kümesi."""
        o = operations.get(op)
        if not o.new_dataset:
            raise ShiftFlowError(f"'{o.label}' yeni veri kümesi oluşturmaz.")
        for i in inputs:
            self.workflow.dataset(i)
        name = self.workflow.unique_name(name)

        def mut(wf):
            wf.datasets[name] = Dataset(name=name, origin=Origin(type=op, inputs=list(inputs), params=params))
        self._commit(mut, focus=name)
        return name

    def edit_origin(self, dataset: str, params: dict, inputs: list[str] | None = None):
        def mut(wf):
            ds = wf.dataset(dataset)
            if ds.origin.type == "source":
                raise ShiftFlowError("Kaynak başlangıcı düzenlenemez; 'Kaynakları bağla' ile yeni dosya seçin.")
            ds.origin.params = params
            if inputs is not None:
                if dataset in inputs or any(dataset in wf.inputs_of(i) for i in inputs):
                    pass  # validate() döngüyü yakalar
                ds.origin.inputs = list(inputs)
        self._commit(mut, focus=dataset)

    def rename_dataset(self, old: str, new: str):
        new = new.strip()
        if not new:
            raise ShiftFlowError("Ad boş olamaz.")
        if new == old:
            return
        if new in self.workflow.datasets:
            raise ShiftFlowError(f"'{new}' adı zaten kullanılıyor.")

        def mut(wf):
            items = list(wf.datasets.items())
            wf.datasets = {(new if k == old else k): v for k, v in items}
            wf.datasets[new].name = new
            for d in wf.datasets.values():
                d.origin.inputs = [new if i == old else i for i in d.origin.inputs]
                if d.origin.type == "append" and d.origin.params.get("labels"):
                    d.origin.params["labels"] = [new if x == old else x for x in d.origin.params["labels"]]
                if d.origin.type == "join" and d.origin.params.get("right_label") == old:
                    d.origin.params["right_label"] = new
                for st in d.steps:
                    if st.op == "lookup" and st.params.get("table") == old:
                        st.params["table"] = new
                    rn = lambda e: expression.rename_table(e, old, new) if isinstance(e, str) else e  # noqa: E731
                    for k in ("formula", "then", "else", "default"):
                        if k in st.params:
                            st.params[k] = rn(st.params[k])
                    for rule in st.params.get("rules", []) or []:
                        rule["value"] = rn(rule.get("value", ""))
            for o in wf.outputs:
                if o.get("dataset") == old:
                    o["dataset"] = new
        self._commit(mut, check=[])

    def delete_dataset(self, name: str):
        deps = self.workflow.dependents_of(name)
        if deps:
            raise ShiftFlowError(
                f"'{name}' silinemez; şu veri kümeleri onu kullanıyor: {', '.join(deps)}. Önce onları silin."
            )

        def mut(wf):
            ds = wf.datasets.pop(name)
            if ds.origin.type == "source":
                still = any(d.origin.source == ds.origin.source for d in wf.datasets.values())
                if not still:
                    wf.sources.pop(ds.origin.source, None)
            wf.outputs = [o for o in wf.outputs if o.get("dataset") != name]
        self._commit(mut, check=[])

    @property
    def parameters(self) -> dict:
        """İş akışı parametreleri: formülde {Ad} ile kullanılır (Excel'deki $H$1 gibi sabit hücreler)."""
        return dict(self.workflow.run_settings.get("parameters") or {})

    def set_parameters(self, params: dict):
        """{ad: değer}. Ad boş olamaz; '{', '}' içeremez. Sayı gibi yazılan değerler sayı olarak saklanır."""
        from .values import _parse_number_text
        clean = {}
        for k, v in (params or {}).items():
            k = str(k).strip()
            if not k:
                continue
            if "{" in k or "}" in k:
                raise ShiftFlowError(f"Parametre adında süslü parantez olamaz: {k}")
            if isinstance(v, str):
                num = _parse_number_text(v.strip()) if v.strip() else None
                v = num if num is not None else v
            clean[k] = v

        def mut(wf):
            rs = dict(wf.run_settings)
            if clean:
                rs["parameters"] = clean
            else:
                rs.pop("parameters", None)
            wf.run_settings = rs
        self._commit(mut, check=list(self.workflow.datasets))

    @property
    def parameter_cells(self) -> dict:
        """Excel'deki sabit hücre → parametre adı ({"H1": "Hedef Oran"}); çevirici bunları {Ad} yapar."""
        return dict(self.workflow.run_settings.get("parameter_cells") or {})

    def define_parameters_from_cells(self, cells: dict, values: dict):
        """cells: {"H1": "Hedef Oran"}, values: {"Hedef Oran": 0.95}. Var olan parametrelere eklenir."""
        params = self.parameters
        params.update(values)
        self.set_parameters(params)
        pc = self.parameter_cells
        pc.update({k.replace("$", "").upper(): v for k, v in cells.items()})

        def mut(wf):
            wf.run_settings = dict(wf.run_settings, parameter_cells=pc)
        self._commit(mut, check=[])

    def set_run_settings(self, settings: dict):
        def mut(wf):
            wf.run_settings = dict(settings)
        self._commit(mut, check=[])

    def set_outputs(self, outputs: list[dict]):
        def mut(wf):
            wf.outputs = [dict(o) for o in outputs]
        self._commit(mut, check=[])

    # ================================================================ kayıt / çıktı
    def link_report(self, source: str, report_id: str | None):
        """Kaynağı bir rapor tanımına bağlar (veya bağı kaldırır)."""
        def mut(wf):
            spec = wf.sources[source]
            spec.report_id = report_id
            if report_id and spec.kind == "paste":
                spec.kind = "report"
        self._commit(mut, check=[])

    def embed_reports(self):
        """Kullanılan rapor tanımlarını iş akışına kopyalar (taşınabilirlik)."""
        if not self.library:
            return
        used = {s.report_id for s in self.workflow.sources.values() if s.report_id}
        emb = {}
        for rid in used:
            d = self.library.get(rid)
            if d:
                emb[rid] = d.to_dict()
            elif rid in self.workflow.reports:
                emb[rid] = self.workflow.reports[rid]
        self.workflow.reports = emb

    def save_workflow(self, path: str):
        self.embed_reports()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.workflow.to_json())
        self.dirty = False

    def load_workflow(self, path: str) -> Workflow:
        try:
            with open(path, encoding="utf-8") as fh:
                wf = Workflow.from_json(fh.read())
        except OSError as exc:
            raise WorkflowError("İş akışı dosyası açılamadı.", detail=str(exc)) from exc
        # Göreli kaynak yolları iş akışı dosyasının klasörüne göre çözülür
        # (iş akışı ve raporlar birlikte taşınabilsin diye).
        base = os.path.dirname(os.path.abspath(path))
        for spec in wf.sources.values():
            if spec.path and not os.path.isabs(spec.path):
                spec.path = os.path.normpath(os.path.join(base, spec.path))
        if self.library:
            for d in wf.reports.values():
                self.library.merge(reports.ReportDefinition.from_dict(d))
        self.workflow = wf
        self.data.clear()
        self._cache.clear()
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        return wf

    def load_source_file(self, name: str) -> pd.DataFrame:
        spec = self.workflow.sources[name]
        return sio.read_source(spec.path, spec.sheet, spec.header)

    def export(self, path: str, items: list | None = None, context: dict | None = None,
               warnings: list | None = None) -> list[str]:
        """items: [(veri kümesi, sayfa adı)] veya [(veri kümesi, sayfa adı, seçenekler)].
        Verilmezse kayıtlı çıktı listesi (grafik ve şablon ayarlarıyla) kullanılır."""
        if items is None:
            items = [(o["dataset"], o.get("sheet") or o["dataset"], o) for o in self.workflow.outputs]
        if not items:
            items = [(n, n) for n in self.workflow.datasets]
        with self.strict():
            return self._export(path, items, context, warnings)

    def strict(self):
        """Bu blok içinde 'Raporu durdur' doğrulamaları çıktıyı engeller."""
        from contextlib import contextmanager

        @contextmanager
        def cm():
            old = self.strict_validation
            self.strict_validation = True
            try:
                yield
            finally:
                self.strict_validation = old
        return cm()

    def _export(self, path, items, context, warnings):
        sheets = []
        for it in items:
            ds, sheet = it[0], it[1]
            opts = it[2] if len(it) > 2 else {}
            try:
                df = self.result(ds)
                f = self.excel_formulas(ds, df)
                if f:
                    opts = dict(opts, formulas=f)
                if opts.get("rules"):  # kural değeri parametre olabilir: {Hedef Oran}
                    pr = {k.lower(): v for k, v in self.parameters.items()}
                    opts = dict(opts, rules=[dict(r, value=pr.get(str(r.get("value", "")).strip()[1:-1].lower(),
                                                                  r.get("value")))
                                             if str(r.get("value", "")).strip().startswith("{") else r
                                             for r in opts["rules"]])
                sheets.append((sheet, df, opts))
            except ShiftFlowError as exc:
                raise ShiftFlowError(f"'{ds}' hesaplanamadığı için dışa aktarılamadı: {exc.message}") from exc
        rs = self.workflow.run_settings
        protected = self.source_paths() + ([rs["template"]["path"]] if rs.get("template", {}).get("path") else [])
        return sio.write_excel(path, sheets, protected_paths=protected, template=rs.get("template"),
                               context=context, warnings=warnings)
