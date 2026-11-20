"""ornekler/ornek_is_akisi.json dosyasını sentetik verilerden üretir.

Önce: python ornekler/ornek_veri_olustur.py
Sonra: python ornekler/ornek_akis_olustur.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from shiftflow.engine import Session  # noqa: E402
from shiftflow.engine import io as sio  # noqa: E402
from shiftflow.engine import reports as rp  # noqa: E402
from shiftflow.engine.library import ReportLibrary  # noqa: E402

V = os.path.join(HERE, "veri")
import tempfile  # noqa: E402

# Rapor tanımları geçici bir kütüphanede oluşturulur ve iş akışına gömülür.
# İş akışını uygulamada açtığınızda tanımlar sizin kütüphanenize eklenir.
lib = ReportLibrary(os.path.join(tempfile.mkdtemp(), "ornek.db"))
s = Session()
s.library = lib
s.add_source("Toplama", sio.read_source(os.path.join(V, "toplama_raporu_gun1.xlsx"), "Toplama"),
             path="veri/toplama_raporu_gun1.xlsx", sheet="Toplama")
s.add_source("Personel", sio.read_source(os.path.join(V, "personel_listesi.xlsx"), "Personel"),
             path="veri/personel_listesi.xlsx", sheet="Personel")
t_df = s.data["Toplama"]
p_df = s.data["Personel"]
d1 = lib.save(rp.ReportDefinition(name="WMS Toplama Performans Raporu", columns=rp.columns_of(t_df),
                                  key_columns=[str(c) for c in t_df.columns],
                                  description="Örnek: WMS > Raporlar > Toplama Performansı (sentetik)"))
d2 = lib.save(rp.ReportDefinition(name="Personel Listesi", columns=rp.columns_of(p_df),
                                  key_columns=["Personel No", "Ad Soyad", "Vardiya", "Ekip Lideri"]))
s.link_report("Toplama", d1.id)
s.link_report("Personel", d2.id)
s.add_step("Toplama", "filter", {"conditions": [{"column": "Bölge", "op": "not_empty"}], "mode": "and"})
s.add_step("Toplama", "calc", {"name": "Gerçekleşme %", "formula": "[Toplanan Adet] / [Hedef Adet] * 100"})
s.add_step("Toplama", "conditional", {
    "name": "Performans", "conditions": [{"column": "Gerçekleşme %", "op": "ge", "value": "100"}],
    "mode": "and", "then": "Hedefte", "else": "Hedef altı"})
s.add_step("Personel", "select", {"columns": ["Personel No", "Ad Soyad", "Vardiya", "Ekip Lideri"]})
s.add_derived("Detay", "join", ["Toplama", "Personel"], {
    "how": "left", "left_keys": ["Personel No"], "right_keys": ["Personel No"],
    "right_label": "Personel", "add_match_column": True})
s.add_derived("Vardiya x Bölge", "pivot", ["Detay"], {
    "rows": ["Vardiya"], "columns": ["Bölge"], "values": [{"column": "Toplanan Adet", "func": "sum"}], "totals": True})
s.add_derived("Ekip Özeti", "group", ["Detay"], {"by": ["Ekip Lideri", "Vardiya"], "values": [
    {"column": "Toplanan Adet", "func": "sum"}, {"column": "Hedef Adet", "func": "sum"},
    {"column": "Hatalı Toplama", "func": "sum"}, {"column": "Sipariş No", "func": "count", "name": "Sipariş Sayısı"}]})
s.add_step("Ekip Özeti", "calc", {"name": "Gerçekleşme %", "formula":
                                  "[Toplanan Adet (Toplam)] / [Hedef Adet (Toplam)] * 100"})
s.add_step("Ekip Özeti", "sort", {"keys": [{"column": "Gerçekleşme %", "ascending": False}]})
s.add_derived("Eşleşmeyenler", "copy", ["Detay"], {})
s.add_step("Eşleşmeyenler", "filter", {"conditions": [{"column": "Eşleşme Durumu", "op": "eq", "value": "Yalnız solda"}]})
s.set_outputs([{"dataset": "Detay", "sheet": "Detay"}, {"dataset": "Vardiya x Bölge", "sheet": "Vardiya Bölge"},
               {"dataset": "Ekip Özeti", "sheet": "Ekip Özeti"}, {"dataset": "Eşleşmeyenler", "sheet": "Kontrol"}])
s.workflow.name = "Günlük toplama raporu"
s.workflow.run_settings = {"output_dir": "", "file_name": "{akis} {tarih} {saat}", "open_after": True}
s.save_workflow(os.path.join(HERE, "ornek_is_akisi.json"))
print("Kaydedildi: ornekler/ornek_is_akisi.json")


# ---------------------------------------------------------------- 2. örnek: vardiya sonu raporu
# Dönem filtresi + DÜŞEYARA + kural tablosu + önceki vardiya karşılaştırması (arşivden) + grafik + mail taslağı.
v = Session()
v.library = lib
from datetime import date  # noqa: E402

from shiftflow.engine import periods as pr  # noqa: E402

v.set_period(pr.make_period(date(2026, 11, 1), "Gündüz", pr.DEFAULT_SHIFTS))  # örnek verinin günü
v.add_source("Toplama", sio.read_source(os.path.join(V, "toplama_raporu_gun1.xlsx"), "Toplama"),
             path="veri/toplama_raporu_gun1.xlsx", sheet="Toplama")
v.add_source("Personel", sio.read_source(os.path.join(V, "personel_listesi.xlsx"), "Personel"),
             path="veri/personel_listesi.xlsx", sheet="Personel")
v.link_report("Toplama", d1.id)
v.link_report("Personel", d2.id)
v.add_step("Toplama", "period_filter", {"column": "İşlem Zamanı"})
v.add_step("Toplama", "lookup", {"table": "Personel", "keys": [["Personel No", "Personel No"]],
                                 "columns": [{"column": "Ad Soyad"}, {"column": "Ekip Lideri"}],
                                 "if_missing": "Tanımsız", "on_duplicate": "first"})
v.add_step("Toplama", "calc", {"name": "Gerçekleşme %",
                               "formula": "EĞERHATA(YUVARLA([Toplanan Adet] / [Hedef Adet] * 100; 1); 0)"})
v.add_step("Toplama", "rules", {"name": "Performans", "default": "Normal", "rules": [
    {"conditions": [{"column": "Hedef Adet", "op": "eq", "value": "0"}], "mode": "and", "value": "Hedef yok"},
    {"conditions": [{"column": "Gerçekleşme %", "op": "ge", "value": "110"}], "mode": "and", "value": "Yüksek"},
    {"conditions": [{"column": "Gerçekleşme %", "op": "lt", "value": "80"},
                    {"column": "Hatalı Toplama", "op": "gt", "value": "0"}], "mode": "and", "value": "Kontrol et"},
]})
v.add_derived("Ekip Özeti", "group", ["Toplama"], {"by": ["Ekip Lideri"], "values": [
    {"column": "Toplanan Adet", "func": "sum", "name": "Toplanan"}, {"column": "Hedef Adet", "func": "sum", "name": "Hedef"},
    {"column": "Hatalı Toplama", "func": "sum", "name": "Hatalı"}]})
v.add_step("Ekip Özeti", "calc", {"name": "Gerçekleşme %", "formula": "EĞERHATA(YUVARLA([Toplanan] / [Hedef] * 100; 1); 0)"})
v.add_derived("Performans Dağılımı", "pivot", ["Toplama"], {
    "rows": ["Ekip Lideri"], "columns": ["Performans"], "values": [{"column": "Sipariş No", "func": "count"}], "totals": True})
v.set_outputs([
    {"dataset": "Ekip Özeti", "sheet": "Ekip Özeti",
     "chart": {"type": "col", "category": "Ekip Lideri", "values": ["Toplanan", "Hedef"], "title": "Ekiplere göre toplama"}},
    {"dataset": "Performans Dağılımı", "sheet": "Performans", "chart": {"type": "bar", "category": "Ekip Lideri", "values": []}},
    {"dataset": "Toplama", "sheet": "Detay"},
])
v.workflow.name = "Vardiya sonu raporu"
v.workflow.run_settings = {
    "output_dir": "", "file_name": "{akis} {tarih} {vardiya}", "open_after": True, "period_mode": "shift",
    "archive": {"enabled": True, "sets": {"Ekip Özeti": "Vardiya sonu / Ekip Özeti"}},
    "mail": {"enabled": True, "to": "vardiya.amiri@example.com; depo.mudur@example.com", "cc": "",
             "subject": "{akis} – {vardiya} {tarih}",
             "intro": "Merhaba,\n\n{donem} vardiya sonu raporu ektedir.\n\nİyi çalışmalar.",
             "summary_dataset": "Ekip Özeti", "summary_rows": 20, "attach": True,
             "per_shift": {"Gece": {"to": "gece.lideri@example.com", "cc": ""}}},
}
v.save_workflow(os.path.join(HERE, "ornek_vardiya_akisi.json"))
print("Kaydedildi: ornekler/ornek_vardiya_akisi.json")
