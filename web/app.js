// ShiftFlow tarayıcı demosu — arayüz.
// Hesaplamanın tamamı Python motorunda (sfweb.py → shiftflow.engine) yapılır.
// Bu dosya yalnızca ekranı çizer ve motora komut gönderir.
//
// İki arka uç vardır:
//   PyodideBackend : yayındaki sürüm; Python tarayıcının içinde çalışır, ağ yok.
//   DevBackend     : yalnız geliştirme/test (?dev=1); aynı sfweb.py yerel test sunucusunda çalışır.

const $ = (s, el = document) => el.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

// ================================================================ arka uçlar
class PyodideBackend {
  async init(progress) {
    const manifest = await (await fetch("manifest.json", { cache: "no-cache" })).json();
    // Pyodide ve paketleri bu sitenin pyodide/ klasöründen gelir; dış adrese istek yok.
    const indexURL = new URL("pyodide/", location.href).href;
    progress("Python (Pyodide) yükleniyor…");
    await new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = indexURL + "pyodide.js";
      s.onload = resolve;
      s.onerror = () => reject(new Error("Pyodide yüklenemedi. Sayfayı yenileyin; sorun sürerse bağlantınızı kontrol edin."));
      document.head.appendChild(s);
    });
    this.py = await globalThis.loadPyodide({ indexURL });
    progress("pandas ve numpy yükleniyor…");
    await this.py.loadPackage(manifest.packages, { checkIntegrity: true });
    progress("Excel kitaplığı (openpyxl) yükleniyor…");
    const wheels = manifest.wheels.map((w) => new URL(w, location.href).href);
    await this.py.loadPackage(wheels);
    progress("ShiftFlow motoru yükleniyor…");
    const zip = await (await fetch(manifest.engine)).arrayBuffer();
    this.py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/sf" });
    this.py.runPython("import sys; sys.path.insert(0, '/home/pyodide/sf'); import os; os.environ['SFWEB_DIR'] = '/tmp/sfweb'");
    this.api = this.py.pyimport("sfweb");
  }
  async call(name, args) {
    return JSON.parse(this.api.dispatch(name, JSON.stringify(args ?? null)));
  }
  async putFile(name, bytes) {
    this.py.FS.mkdirTree("/tmp/upload");
    const path = "/tmp/upload/" + name.replace(/[\\/]/g, "_");
    this.py.FS.writeFile(path, bytes);
    return path;
  }
  async getFile(path) {
    return this.py.FS.readFile(path);
  }
}

class DevBackend {
  async init(progress) {
    progress("Geliştirme sunucusuna bağlanılıyor…");
  }
  async call(name, args) {
    const r = await fetch("/api", { method: "POST", body: JSON.stringify({ name, args: args ?? null }) });
    return r.json();
  }
  async putFile(name, bytes) {
    const r = await fetch("/put?name=" + encodeURIComponent(name), { method: "POST", body: bytes });
    return (await r.json()).path;
  }
  async getFile(path) {
    const r = await fetch("/get?path=" + encodeURIComponent(path));
    return new Uint8Array(await r.arrayBuffer());
  }
}

const backend = new URLSearchParams(location.search).get("dev") === "1" ? new DevBackend() : new PyodideBackend();

// ================================================================ durum
const ui = { meta: null, focus: null, upto: null, st: null, busy: 0 };

async function cmd(name, args, { quiet = false } = {}) {
  ui.busy++;
  const t = setTimeout(() => ($("#busy").hidden = false), 250);
  await nextFrame();
  try {
    const res = await backend.call(name, args);
    if (!res.ok && !quiet) showError(res.error, res.detail);
    return res;
  } catch (e) {
    showError("Arayüz hatası: " + e.message);
    return { ok: false, error: e.message };
  } finally {
    clearTimeout(t);
    if (--ui.busy === 0) $("#busy").hidden = true;
  }
}

let toastTimer;
function toast(text, ms = 4000) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), ms);
}

let pendingError = null;
function showError(msg, detail, title = "Değişiklik uygulanmadı.") {
  pendingError = { msg, detail, title };
  renderNotice();
}

// ================================================================ çizim
const KIND = { source: "Kaynak", pivot: "Pivot", group: "Grupla", join: "Birleştir", append: "Alt alta", copy: "Kopya" };

async function refresh(extra = {}) {
  if (extra.focus !== undefined) { ui.focus = extra.focus; ui.upto = null; }
  if (extra.upto !== undefined) ui.upto = extra.upto;
  const st = await cmd("state", { dataset: ui.focus, upto: ui.upto });
  if (!st.ok) return;
  ui.st = st;
  ui.focus = st.focus;
  ui.upto = st.upto;
  const has = st.datasets.length > 0;
  $("#work").hidden = !has;
  $("#welcome").classList.toggle("compact", has);
  renderDatasets();
  renderSteps();
  renderPreview();
  renderNotice();
}

function renderDatasets() {
  const ul = $("#ds-list");
  ul.innerHTML = "";
  for (const d of ui.st.datasets) {
    const li = document.createElement("li");
    li.className = d.name === ui.focus ? "active" : "";
    li.tabIndex = 0;
    li.innerHTML = `<span class="ds-name" title="${esc(d.name)}">${esc(d.name)}</span>
      <span class="ds-kind">${esc(KIND[d.origin] || d.origin)}${d.steps ? " · " + d.steps : ""}</span>
      ${d.origin !== "source" ? `<button class="link-btn" data-del="${esc(d.name)}" title="Veri kümesini sil" aria-label="Sil">✕</button>` : ""}`;
    li.onclick = (e) => {
      if (e.target.dataset.del) return;
      pendingError = null;
      refresh({ focus: d.name });
    };
    li.onkeydown = (e) => e.key === "Enter" && li.click();
    ul.appendChild(li);
  }
  ul.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm(`'${b.dataset.del}' silinsin mi?`)) return;
    const r = await cmd("delete_dataset", { dataset: b.dataset.del });
    if (r.ok) refresh({ focus: null });
  }));
  $("[data-act=undo]").disabled = !ui.st.undo;
  $("[data-act=redo]").disabled = !ui.st.redo;
}

function stepIcon(s) {
  if (s.error) return ["st-err", "✕"];
  if (!s.enabled) return ["st-off", "–"];
  if (s.warnings.length) return ["st-warn", "!"];
  return ["st-ok", "✓"];
}

function rowsText(s) {
  if (s.rows_after == null) return "";
  const n = (x) => x.toLocaleString("tr-TR");
  if (s.rows_before != null && s.rows_before !== s.rows_after) return `${n(s.rows_before)} → ${n(s.rows_after)} satır`;
  return `${n(s.rows_after)} satır · ${s.cols_after} sütun`;
}

function renderSteps() {
  const ol = $("#step-list");
  ol.innerHTML = "";
  $("#steps-title").textContent = `Adımlar — ${ui.focus}`;
  const steps = ui.st.steps || [];
  const last = steps.length - 2;
  for (const s of steps) {
    const li = document.createElement("li");
    li.className = "step" + (s.index === ui.upto ? " active" : "") + (s.enabled ? "" : " off");
    const [cls, ic] = stepIcon(s);
    const num = s.index < 0 ? "" : `<span class="step-num">${s.index + 1}.</span>`;
    const msgs = [];
    if (s.error) msgs.push(`<div class="step-msg err">${esc(s.error)}</div>`);
    else for (const w of s.warnings.slice(0, 2)) msgs.push(`<div class="step-msg warn">${esc(w)}</div>`);
    li.innerHTML = `<div class="step-row"><span class="step-icon ${cls}" aria-hidden="true">${ic}</span>
        <span class="step-label">${num}${esc(s.label)}</span></div>
      <div class="step-meta">${esc(rowsText(s))}</div>${msgs.join("")}
      ${s.index >= 0 ? `<div class="step-tools">
        <button class="link-btn" data-t="toggle" title="Adımı silmeden kapat/aç">${s.enabled ? "Kapat" : "Aç"}</button>
        <button class="link-btn" data-t="up" ${s.index === 0 ? "disabled" : ""} title="Yukarı taşı">↑</button>
        <button class="link-btn" data-t="down" ${s.index === last ? "disabled" : ""} title="Aşağı taşı">↓</button>
        <button class="link-btn" data-t="del" title="Adımı sil">Sil</button></div>` : ""}`;
    li.onclick = (e) => {
      const t = e.target.dataset.t;
      if (t) return stepTool(t, s.index);
      pendingError = null;
      refresh({ upto: s.index });
    };
    ol.appendChild(li);
  }
}

async function stepTool(t, index) {
  const ds = ui.focus;
  let r;
  if (t === "toggle") r = await cmd("toggle_step", { dataset: ds, index });
  if (t === "up") r = await cmd("move_step", { dataset: ds, index, delta: -1 });
  if (t === "down") r = await cmd("move_step", { dataset: ds, index, delta: 1 });
  if (t === "del") r = await cmd("delete_step", { dataset: ds, index });
  if (r && r.ok) { pendingError = null; refresh({ upto: null }); }
}

function fmt(v, type) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v.toLocaleString("tr-TR", { maximumFractionDigits: 2 });
  if (typeof v === "boolean") return v ? "DOĞRU" : "YANLIŞ";
  return String(v);
}

// Baştaki/sondaki ve çift boşluklar görünür yapılır ('A Blok ' ile 'A Blok' ayırt edilsin).
function showSpaces(t) {
  const m = /^(\s*)(.*?)(\s*)$/s.exec(t);
  const mark = (w) => w ? `<span class="ws" title="${w.length} boşluk">${"·".repeat(w.length)}</span>` : "";
  return mark(m[1]) + esc(m[2]).replace(/ {2,}/g, (w) => mark(w)) + mark(m[3]);
}

const TYPE_LABEL = { number: "123", date: "tarih", text: "abc" };

function renderPreview() {
  const grid = $("#grid");
  const p = ui.st.preview;
  const cur = (ui.st.steps || []).find((s) => s.index === ui.upto);
  $("#preview-title").textContent = cur ? `Önizleme — ${cur.index < 0 ? "başlangıç" : cur.index + 1 + ". adımdan sonra"}` : "Önizleme";
  if (!p) {
    grid.innerHTML = `<tr><td class="empty-state">${esc(ui.st.preview_error || "Bu adımda önizleme yok.")}</td></tr>`;
    $("#preview-count").textContent = "";
    return;
  }
  $("#preview-count").textContent = p.total > p.rows.length
    ? `${p.total.toLocaleString("tr-TR")} satırın ilk ${p.rows.length} satırı`
    : `${p.total.toLocaleString("tr-TR")} satır`;
  const head = `<thead><tr><th class="rownum">#</th>${p.columns.map((c) =>
    `<th>${esc(c.name)}<span class="type">${TYPE_LABEL[c.type] || ""}</span></th>`).join("")}</tr></thead>`;
  const body = p.rows.map((r, i) => {
    const total = typeof r[0] === "string" && r[0] === "Genel Toplam";
    return `<tr${total ? ' class="total"' : ""}><td class="rownum">${i + 1}</td>${r.map((v, j) => {
      const t = fmt(v, p.columns[j].type);
      const num = typeof v === "number";
      return t === null ? `<td class="empty">—</td>` : `<td${num ? ' class="num"' : ""}>${num ? esc(t) : showSpaces(t)}</td>`;
    }).join("")}</tr>`;
  }).join("");
  grid.innerHTML = head + `<tbody>${body}</tbody>`;
}

function renderNotice() {
  const box = $("#notice");
  box.innerHTML = "";
  if (pendingError) {
    const d = document.createElement("div");
    d.className = "notice err";
    d.innerHTML = `<strong>${esc(pendingError.title)}</strong> ${esc(pendingError.msg)}
      ${pendingError.detail ? `<span class="detail">${esc(pendingError.detail)}</span>` : ""}
      <div class="actions"><button class="btn small" data-x="close">Tamam</button></div>`;
    d.querySelector("[data-x=close]").onclick = () => { pendingError = null; renderNotice(); };
    box.appendChild(d);
  }
  if (!ui.st || !ui.st.steps) return;
  // Farklı yazılış uyarısı: kullanıcıya sorulur, sessizce düzeltilmez.
  const s = ui.st.steps.find((x) => x.enabled && Object.keys(x.variants || {}).length);
  if (!s) return;
  const cols = Object.keys(s.variants);
  const parts = cols.map((c) => {
    const g = s.variants[c][0];
    return `<b>${esc(c)}</b> sütununda ${g.forms.map((f) => `'${esc(f)}'`).join(", ")}`;
  });
  const where = s.index < 0 ? "Bu özet" : `${s.index + 1}. adım`;
  const d = document.createElement("div");
  d.className = "notice warn";
  d.innerHTML = `<strong>Aynı değerin farklı yazılışları var.</strong> ${parts.join("; ")} ayrı değer sayılıyor. ${where} bunları ayrı gruplar olarak hesaplar.
    <div class="actions"><button class="btn small primary" data-x="fix">Düzelt (yazımı birleştir)</button>
    <button class="btn small" data-x="ignore">Bu adım için sorma</button></div>`;
  d.querySelector("[data-x=fix]").onclick = async () => {
    const r = await cmd("fix_variants", { dataset: ui.focus, index: s.index, columns: cols });
    if (r.ok) { toast("Önüne 'Yazımı birleştir' adımı eklendi. Geri almak için ↶."); refresh({ upto: null }); }
  };
  d.querySelector("[data-x=ignore]").onclick = async () => {
    const r = await cmd("ignore_variants", { dataset: ui.focus, index: s.index });
    if (r.ok) refresh({});
  };
  box.appendChild(d);
}

// ================================================================ adım formları
// Her işlem: hangi alanları sorduğu + bu alanlardan motor parametresini nasıl kurduğu.
const OPS = [
  { group: "Temizle ve düzenle" },
  { op: "filter", title: "Filtre", help: "Koşulu sağlayan satırları tutar.",
    fields: [{ k: "cond", type: "cond" }],
    build: (v) => ({ conditions: [v.cond], mode: "and" }) },
  { op: "sort", title: "Sırala",
    fields: [{ k: "column", type: "column", label: "Sütun" },
      { k: "dir", type: "select", label: "Yön", options: { asc: "Artan (A→Z, küçükten büyüğe)", desc: "Azalan (Z→A, büyükten küçüğe)" } }],
    build: (v) => ({ keys: [{ column: v.column, ascending: v.dir === "asc" }] }) },
  { op: "text_clean", title: "Metin temizle", help: "Baştaki/sondaki ve çift boşlukları siler; isterseniz harf biçimini değiştirir.",
    fields: [{ k: "columns", type: "columns", label: "Sütunlar", only: "text" },
      { k: "case", type: "select", label: "Harf biçimi", options: () => ui.meta.cases }],
    build: (v) => ({ columns: v.columns, case: v.case, trim: true, collapse_spaces: true }) },
  { op: "unify", title: "Yazımı birleştir", help: "'A Blok', 'A Blok ' ve 'a blok' gibi yazılışları en sık geçen yazılışta birleştirir.",
    fields: [{ k: "columns", type: "columns", label: "Sütunlar", only: "text" }],
    build: (v) => ({ columns: v.columns }) },
  { op: "remove", title: "Sütun kaldır",
    fields: [{ k: "columns", type: "columns", label: "Kaldırılacak sütunlar" }],
    build: (v) => ({ columns: v.columns }) },
  { op: "dedupe", title: "Tekrarları kaldır", help: "Seçilen sütunlarda aynı olan satırlardan ilkini tutar. Hiçbiri seçilmezse tüm sütunlara bakılır.",
    fields: [{ k: "columns", type: "columns", label: "Karşılaştırılacak sütunlar", optional: true }],
    build: (v) => ({ columns: v.columns, keep: "first" }) },
  { group: "Hesapla" },
  { op: "calc", title: "Hesaplanan sütun", help: "Excel'e benzer formül: [Sütun] başvurusu, ; ile ayrılan Türkçe fonksiyonlar. Örn. YUVARLA([Toplanan Adet] / [Süre (dk)] * 60; 1)",
    fields: [{ k: "name", type: "text", label: "Yeni sütunun adı" }, { k: "formula", type: "formula", label: "Formül" }],
    build: (v) => ({ name: v.name, formula: v.formula }) },
  { op: "conditional", title: "Koşullu sütun (EĞER)",
    fields: [{ k: "name", type: "text", label: "Yeni sütunun adı" }, { k: "cond", type: "cond", label: "Koşul" },
      { k: "then", type: "text", label: "Koşul doğruysa", placeholder: 'Metin, sayı veya formül: "Hedefte"' },
      { k: "else", type: "text", label: "Değilse", placeholder: '"Hedef altı"', optional: true }],
    build: (v) => ({ name: v.name, conditions: [v.cond], mode: "and", then: quoteText(v.then), else: quoteText(v.else) }) },
  { group: "Eşleştir ve kontrol et" },
  { op: "lookup", title: "Eşleştir (DÜŞEYARA)", help: "Başka bir tablodan sütun getirir. Satır sayısı değişmez; bulunamayanlar uyarı olarak gösterilir.",
    fields: [{ k: "table", type: "dataset", label: "Arama tablosu" },
      { k: "key", type: "column", label: "Bu tablodaki anahtar" },
      { k: "key2", type: "tcolumn", label: "Arama tablosundaki anahtar" },
      { k: "bring", type: "tcolumns", label: "Getirilecek sütunlar" },
      { k: "missing", type: "text", label: "Bulunamazsa yazılacak", optional: true, placeholder: "boş bırakılabilir" }],
    build: (v) => ({ table: v.table, keys: [[v.key, v.key2]], columns: v.bring.map((c) => ({ column: c, as: c })),
      if_missing: v.missing, on_duplicate: "first" }) },
  { op: "validate", title: "Doğrula", help: "Veriyi değiştirmez. 'Durdur' seçilirse kural sağlanmadığında Excel çıktısı üretilmez.",
    fields: [{ k: "check", type: "select", label: "Kontrol", options: () => ({
        not_empty: ui.meta.checks.not_empty, unique: ui.meta.checks.unique, range: ui.meta.checks.range, formula: ui.meta.checks.formula }) },
      { k: "column", type: "column", label: "Sütun", showIf: (v) => v.check !== "formula" },
      { k: "min", type: "text", label: "En az", optional: true, showIf: (v) => v.check === "range" },
      { k: "max", type: "text", label: "En çok", optional: true, showIf: (v) => v.check === "range" },
      { k: "formula", type: "formula", label: "Her satırda doğru olması gereken formül", showIf: (v) => v.check === "formula" },
      { k: "on_fail", type: "select", label: "Sağlanmazsa", options: { warn: "Uyar, devam et", stop: "Raporu durdur" } }],
    build: (v) => ({ checks: [{ check: v.check, column: v.check === "formula" ? undefined : v.column, min: v.min, max: v.max,
      formula: v.formula, on_fail: v.on_fail }] }) },
  { group: "Özetle (yeni veri kümesi)" },
  { op: "group", title: "Grupla", derived: true, help: "Seçilen sütunlara göre gruplar ve toplam/adet/ortalama hesaplar.",
    fields: [{ k: "dname", type: "text", label: "Yeni veri kümesinin adı", default: () => `${ui.focus} grup` },
      { k: "by", type: "columns", label: "Gruplanacak sütunlar" },
      { k: "vcol", type: "column", label: "Hesaplanacak sütun" },
      { k: "func", type: "select", label: "Hesaplama", options: () => ui.meta.aggs }],
    build: (v) => ({ by: v.by, values: [{ column: v.vcol, func: v.func }] }) },
  { op: "pivot", title: "Pivot", derived: true, help: "Excel pivot tablosu gibi: satır alanı × sütun alanı, genel toplamlarla.",
    fields: [{ k: "dname", type: "text", label: "Yeni veri kümesinin adı", default: () => `${ui.focus} pivot` },
      { k: "rows", type: "column", label: "Satır alanı" },
      { k: "cols", type: "column", label: "Sütun alanı", optional: true, blank: "(yok)" },
      { k: "vcol", type: "column", label: "Değer alanı" },
      { k: "func", type: "select", label: "Hesaplama", options: () => ui.meta.aggs }],
    build: (v) => ({ rows: [v.rows], columns: v.cols ? [v.cols] : [], values: [{ column: v.vcol, func: v.func }], totals: true }) },
];

function quoteText(t) {
  t = (t ?? "").trim();
  if (!t) return "";
  if (/^".*"$/.test(t) || /[\[\]();]/.test(t) || /^-?\d+([.,]\d+)?$/.test(t)) return t;
  return `"${t.replace(/"/g, '""')}"`;
}

function buildMenu() {
  const m = $("#add-menu");
  m.innerHTML = OPS.map((o, i) => o.group ? `<h5>${esc(o.group)}</h5>`
    : `<button type="button" data-i="${i}">${esc(o.title)}${o.help ? `<small>${esc(o.help.split(".")[0])}.</small>` : ""}</button>`).join("");
  m.querySelectorAll("button").forEach((b) => (b.onclick = () => { m.hidden = true; openForm(OPS[+b.dataset.i]); }));
}

let form = null; // {def, cols, tcols, values}

async function openForm(def) {
  const res = await cmd("columns", { dataset: ui.focus, upto: ui.upto });
  if (!res.ok) return;
  form = { def, cols: res.columns, tcols: [], values: {} };
  for (const f of def.fields) {
    if (f.default) form.values[f.k] = f.default();
  }
  $("#modal-title").textContent = def.title + (ui.upto != null && ui.st.steps && ui.upto < ui.st.steps.length - 2
    ? ` — ${ui.upto < 0 ? "başa" : ui.upto + 1 + ". adımın arkasına"} eklenecek` : "");
  $("#modal-help").textContent = def.help || "";
  $("#modal-form button[type=submit]").textContent = def.derived ? "Oluştur" : "Ekle";
  $("#modal-error").hidden = true;
  await renderForm();
  $("#modal").hidden = false;
  const first = $("#modal-body input, #modal-body select, #modal-body textarea");
  if (first) first.focus();
}

function opts(map, sel) {
  return Object.entries(map).map(([k, v]) => `<option value="${esc(k)}"${k === sel ? " selected" : ""}>${esc(v)}</option>`).join("");
}
function colOpts(cols, sel, blank) {
  return (blank !== undefined ? `<option value="">${esc(blank)}</option>` : "") +
    cols.map((c) => `<option${c.name === sel ? " selected" : ""}>${esc(c.name)}</option>`).join("");
}

async function renderForm() {
  const { def, cols, values } = form;
  // Arama tablosunun sütunları (DÜŞEYARA formu)
  const tf = def.fields.find((f) => f.type === "dataset");
  if (tf) {
    const others = ui.st.datasets.map((d) => d.name).filter((n) => n !== ui.focus);
    if (!values[tf.k] || !others.includes(values[tf.k])) values[tf.k] = others[0];
    if (values[tf.k] && form.tname !== values[tf.k]) {
      const r = await cmd("columns", { dataset: values[tf.k] });
      form.tcols = r.ok ? r.columns : [];
      form.tname = values[tf.k];
      const k1 = values.key || cols[0]?.name;
      values.key2 = form.tcols.some((c) => c.name === k1) ? k1 : form.tcols[0]?.name;
      values.bring = [];
    }
  }
  const html = [];
  for (const f of def.fields) {
    if (f.showIf && !f.showIf(values)) continue;
    const id = "f_" + f.k;
    const lab = f.label ? `<label for="${id}">${esc(f.label)}${f.optional ? ' <span class="muted">(isteğe bağlı)</span>' : ""}</label>` : "";
    const v = values[f.k];
    if (f.type === "text") {
      html.push(`<div class="field">${lab}<input type="text" id="${id}" data-k="${f.k}" value="${esc(v ?? "")}" placeholder="${esc(f.placeholder || "")}"></div>`);
    } else if (f.type === "formula") {
      html.push(`<div class="field">${lab}<textarea id="${id}" data-k="${f.k}" spellcheck="false">${esc(v ?? "")}</textarea>
        <div class="chips">${cols.map((c) => `<button type="button" class="chip" data-ins="${esc(c.name)}">${esc(c.name)}</button>`).join("")}</div>
        <div class="hint">Sütun adına tıklayınca formüle eklenir. Fonksiyonlar: YUVARLA, EĞER, VE, YADA, EĞERHATA, SOLDAN, BİRLEŞTİR, YIL, AY, GÜN…</div></div>`);
    } else if (f.type === "select") {
      const map = typeof f.options === "function" ? f.options() : f.options;
      if (v === undefined) values[f.k] = Object.keys(map)[0];
      html.push(`<div class="field">${lab}<select id="${id}" data-k="${f.k}">${opts(map, values[f.k])}</select></div>`);
    } else if (f.type === "column" || f.type === "tcolumn") {
      const list = f.type === "tcolumn" ? form.tcols : cols;
      if (v === undefined && f.blank === undefined) values[f.k] = list[0]?.name;
      html.push(`<div class="field">${lab}<select id="${id}" data-k="${f.k}">${colOpts(list, values[f.k], f.blank)}</select></div>`);
    } else if (f.type === "columns" || f.type === "tcolumns") {
      const list = (f.type === "tcolumns" ? form.tcols.filter((c) => c.name !== values.key2) : cols)
        .filter((c) => !f.only || c.type === f.only);
      const sel = new Set(values[f.k] || []);
      html.push(`<div class="field"><span class="flabel">${esc(f.label)}${f.optional ? ' <span class="muted">(isteğe bağlı)</span>' : ""}</span>
        <div class="checks">${list.map((c) => `<label><input type="checkbox" data-multi="${f.k}" value="${esc(c.name)}"${sel.has(c.name) ? " checked" : ""}>${esc(c.name)}</label>`).join("") || '<span class="muted small">Uygun sütun yok.</span>'}</div></div>`);
    } else if (f.type === "dataset") {
      const others = ui.st.datasets.map((d) => d.name).filter((n) => n !== ui.focus);
      html.push(`<div class="field">${lab}<select id="${id}" data-k="${f.k}" data-rerender="1">${others.map((n) => `<option${n === v ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>
        ${others.length ? "" : '<div class="hint">Eşleştirme için önce ikinci bir tablo ekleyin.</div>'}</div>`);
    } else if (f.type === "cond") {
      const c = values[f.k] || (values[f.k] = { column: cols[0]?.name, op: "eq", value: "" });
      const noVal = ui.meta.no_value.includes(c.op);
      html.push(`<div class="field"><span class="flabel">${esc(f.label || "Koşul")}</span><div class="row">
        <select data-cond="${f.k}" data-part="column" aria-label="Sütun">${colOpts(cols, c.column)}</select>
        <select data-cond="${f.k}" data-part="op" aria-label="Koşul">${opts(Object.fromEntries(Object.entries(ui.meta.conditions).filter(([k]) => k !== "in_list")), c.op)}</select>
        ${noVal ? "" : `<input type="text" data-cond="${f.k}" data-part="value" aria-label="Değer" value="${esc(c.value ?? "")}" placeholder="değer">`}</div></div>`);
    }
  }
  const body = $("#modal-body");
  body.innerHTML = html.join("");
  body.querySelectorAll("[data-k]").forEach((el) => {
    el.oninput = el.onchange = () => {
      values[el.dataset.k] = el.value;
      if (el.tagName === "SELECT") renderForm();
    };
  });
  body.querySelectorAll("[data-multi]").forEach((el) => (el.onchange = () => {
    values[el.dataset.multi] = [...body.querySelectorAll(`[data-multi="${el.dataset.multi}"]:checked`)].map((x) => x.value);
  }));
  body.querySelectorAll("[data-cond]").forEach((el) => {
    el.oninput = el.onchange = () => {
      values[el.dataset.cond][el.dataset.part] = el.value;
      if (el.dataset.part === "op") renderForm();
    };
  });
  body.querySelectorAll("[data-ins]").forEach((b) => (b.onclick = () => {
    const ta = b.closest(".field").querySelector("textarea");
    const ins = `[${b.dataset.ins}]`;
    const s = ta.selectionStart ?? ta.value.length, e = ta.selectionEnd ?? s;
    ta.value = ta.value.slice(0, s) + ins + ta.value.slice(e);
    values[ta.dataset.k] = ta.value;
    ta.focus();
    ta.selectionStart = ta.selectionEnd = s + ins.length;
  }));
}

function formProblem() {
  const { def, values } = form;
  for (const f of def.fields) {
    if (f.optional || (f.showIf && !f.showIf(values))) continue;
    const v = values[f.k];
    if (f.type === "columns" || f.type === "tcolumns") { if (!v || !v.length) return `'${f.label}' için en az bir sütun seçin.`; }
    else if (f.type === "cond") { if (!ui.meta.no_value.includes(v.op) && String(v.value ?? "").trim() === "") return "Koşul için bir değer yazın."; }
    else if (v === undefined || v === null || String(v).trim() === "") return `'${f.label}' alanını doldurun.`;
  }
  return null;
}

async function submitForm(e) {
  e.preventDefault();
  const problem = formProblem();
  const errBox = $("#modal-error");
  if (problem) { errBox.textContent = problem; errBox.hidden = false; return; }
  const { def, values } = form;
  const params = def.build(values);
  let r;
  if (def.derived) {
    r = await cmd("add_derived", { name: values.dname, op: def.op, inputs: [ui.focus], params }, { quiet: true });
  } else {
    const steps = ui.st.steps || [];
    const atEnd = ui.upto == null || ui.upto >= steps.length - 2;
    r = await cmd("add_step", { dataset: ui.focus, op: def.op, params, position: atEnd ? null : ui.upto + 1 }, { quiet: true });
  }
  if (!r.ok) {
    // Motor değişikliği uygulamadı (geri alındı); kullanıcı formu düzeltip yeniden dener.
    errBox.innerHTML = `${esc(r.error)}${r.detail ? `<br><span class="small">${esc(r.detail)}</span>` : ""}`;
    errBox.hidden = false;
    return;
  }
  closeForm();
  pendingError = null;
  if (def.derived) await refresh({ focus: r.focus });
  else {
    const atEnd = ui.upto == null || ui.upto >= (ui.st.steps || []).length - 2;
    await refresh({ upto: atEnd ? null : ui.upto + 1 });
  }
}

function closeForm() {
  $("#modal").hidden = true;
  form = null;
}

// ================================================================ dosya
async function uploadFile(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  if (file.size > 30 * 1024 * 1024) return showErrorTop("Demo en fazla 30 MB dosya kabul eder.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const path = await backend.putFile(file.name, bytes);
  let sheet = null;
  if (/\.xls[xm]$/i.test(file.name)) {
    const sh = await cmd("sheets", { path });
    if (!sh.ok) return showErrorTop(sh.error);
    if (sh.sheets.length > 1) {
      const pick = prompt(`Hangi sayfa okunsun?\n${sh.sheets.map((s, i) => `${i + 1}. ${s}`).join("\n")}`, "1");
      if (pick === null) return;
      sheet = sh.sheets[Math.max(0, Math.min(sh.sheets.length - 1, (parseInt(pick, 10) || 1) - 1))];
    }
  }
  const name = file.name.replace(/\.[^.]+$/, "");
  const r = await cmd("load_file", { path, name, sheet }, { quiet: true });
  if (!r.ok) return showErrorTop(r.error, r.detail);
  pendingError = null;
  toast(`'${r.focus}' yüklendi. Dosya bu bilgisayardan çıkmadı.`);
  await refresh({ focus: r.focus });
}

function showErrorTop(msg, detail) {
  if ($("#work").hidden) { alert(msg + (detail ? "\n\n" + detail : "")); return; }
  showError(msg, detail);
}

function download(bytes, name, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ================================================================ eylemler
const hasWork = () => ui.st && ui.st.datasets.length > 0;
const ACTIONS = {
  async demo() {
    if (hasWork() && !confirm("Örnek akış kurulursa mevcut veri ve adımlar silinir. Devam edilsin mi?")) return;
    const r = await cmd("build_demo_flow");
    if (r.ok) {
      pendingError = null;
      await refresh({ focus: r.focus });
      toast("Örnek akış kuruldu: 'Vardiya verisi' üzerinde 6 adım ve iki özet tablo. Uyarıya bakın ↑", 6000);
    }
  },
  async sample() {
    if (hasWork() && !confirm("Mevcut veri ve adımlar silinir. Devam edilsin mi?")) return;
    const r = await cmd("load_sample");
    if (r.ok) { pendingError = null; await refresh({ focus: r.focus }); }
  },
  async "sample-add"() { await ACTIONS.sample(); },
  async nextday() {
    const r = await cmd("next_day");
    if (!r.ok) return;
    $("#day-info").textContent = `Şu an: ${r.date} verisi`;
    await refresh({ upto: null });
    toast(`${r.date} günün verisi yüklendi; aynı adımlar yeni veriyle yeniden çalıştı.`, 5000);
  },
  async undo() { const r = await cmd("undo"); if (r.ok) refresh({ upto: null }); },
  async redo() { const r = await cmd("redo"); if (r.ok) refresh({ upto: null }); },
  "add-menu"() { const m = $("#add-menu"); m.hidden = !m.hidden; },
  "modal-cancel"() { closeForm(); },
  async export() {
    const r = await cmd("export", null, { quiet: true });
    if (!r.ok) return showError(r.error, r.detail, "Excel dosyası oluşturulmadı.");
    const bytes = await backend.getFile(r.path);
    download(bytes, r.file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    toast(r.warnings.length ? "Excel indirildi. Uyarılar: " + r.warnings.join(" ") : "Excel dosyası indirildi (her veri kümesi ayrı sayfada).");
  },
  async "flow-json"() {
    const r = await cmd("workflow_json");
    if (r.ok) download(new TextEncoder().encode(r.json), "ShiftFlow_akis.json", "application/json");
  },
};

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (b && ACTIONS[b.dataset.act]) { e.preventDefault(); ACTIONS[b.dataset.act](); return; }
  const m = $("#add-menu");
  if (!m.hidden && !e.target.closest(".add-step")) m.hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { if (!$("#modal").hidden) closeForm(); $("#add-menu").hidden = true; }
  if ((e.ctrlKey || e.metaKey) && !$("#work").hidden && $("#modal").hidden && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
    if (e.key === "z") { e.preventDefault(); ACTIONS.undo(); }
    if (e.key === "y") { e.preventDefault(); ACTIONS.redo(); }
  }
});
$("#modal-form").addEventListener("submit", submitForm);
$("#file").addEventListener("change", (e) => uploadFile(e.target));
$("#file2").addEventListener("change", (e) => uploadFile(e.target));

// ================================================================ başlat
(async () => {
  try {
    await backend.init((t) => ($("#loader-step").textContent = t));
    const m = await backend.call("meta");
    if (!m.ok) throw new Error(m.error);
    ui.meta = m;
    $("#ver").textContent = "motor sürümü " + m.version;
    buildMenu();
    $("#loader").hidden = true;
    $("#app").hidden = false;
    window.__sfReady = true;
  } catch (e) {
    $("#loader").classList.add("failed");
    $("#loader h2").textContent = "Demo başlatılamadı";
    $("#loader-step").textContent = e.message;
    console.error(e);
  }
})();
