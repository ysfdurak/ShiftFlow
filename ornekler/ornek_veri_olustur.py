"""Deneme için sentetik (gerçek olmayan) depo raporları üretir.

Kullanım:
    python ornekler/ornek_veri_olustur.py            -> ornekler/veri/ klasörüne yazar
    python ornekler/ornek_veri_olustur.py --gun 2    -> ikinci günün raporu (aynı biçim, farklı değerler)
    python ornekler/ornek_veri_olustur.py --bicim-degisik
        -> 'Toplanan Adet' sütunu 'Toplanan Miktar' olarak gelir (sütun eşleme denemesi için)
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import date, timedelta

import pandas as pd

BOLGE = ["A Blok", "B Blok", "C Blok", "Soğuk Oda"]
VARDIYA = ["Gündüz", "Akşam", "Gece"]
AD = ["Ali", "Ayşe", "Mehmet", "Zeynep", "Can", "Elif", "Murat", "Selin", "Emre", "Derya", "Kaan", "İrem"]
SOYAD = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Öztürk", "Aydın", "Arslan", "Koç", "Kurt"]


def personel(n=40, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "Personel No": f"P{i:03d}",
            "Ad Soyad": f"{rnd.choice(AD)} {rnd.choice(SOYAD)}",
            "Vardiya": rnd.choice(VARDIYA),
            "Ekip Lideri": rnd.choice(["Hasan Er", "Gül Tan", "Okan Su"]),
        })
    # Bilerek: listede raporda hiç görünmeyen personel var (eşleşmeyen sağ kayıt).
    return pd.DataFrame(rows)


def toplama(gun=1, satir=1500, bicim_degisik=False):
    rnd = random.Random(100 + gun)
    d0 = date(2026, 11, 1) + timedelta(days=gun - 1)
    rows = []
    for i in range(satir):
        hedef = rnd.choice([40, 50, 60, 80])
        toplanan = max(0, int(rnd.gauss(hedef * 0.95, hedef * 0.25)))
        saat = rnd.randint(0, 24 * 60 - 1)  # gün içine yayılmış işlem zamanı (vardiya filtresi denemesi)
        rows.append({
            "Tarih": d0.strftime("%d.%m.%Y"),
            "İşlem Zamanı": f"{d0:%d.%m.%Y} {saat // 60:02d}:{saat % 60:02d}",
            # Bilerek: P041-P045 personel listesinde yok (eşleşmeyen sol kayıt).
            "Personel No": f"P{rnd.randint(1, 45):03d}",
            "Bölge": rnd.choice(BOLGE) if rnd.random() > 0.02 else None,
            "Sipariş No": f"S{gun:02d}{i:05d}",
            "Toplanan Adet": toplanan,
            "Hedef Adet": hedef if rnd.random() > 0.01 else 0,  # birkaç sıfır hedef: sıfıra bölme denemesi
            "Süre (dk)": round(rnd.uniform(20, 70), 1),
            "Hatalı Toplama": rnd.choice([0, 0, 0, 0, 1, 2]),
        })
    df = pd.DataFrame(rows)
    if bicim_degisik:
        df = df.rename(columns={"Toplanan Adet": "Toplanan Miktar"})
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gun", type=int, default=1)
    ap.add_argument("--bicim-degisik", action="store_true")
    ap.add_argument("--klasor", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri"))
    a = ap.parse_args()
    os.makedirs(a.klasor, exist_ok=True)
    rapor = os.path.join(a.klasor, f"toplama_raporu_gun{a.gun}{'_yeni_bicim' if a.bicim_degisik else ''}.xlsx")
    with pd.ExcelWriter(rapor, engine="openpyxl") as w:
        toplama(a.gun, bicim_degisik=a.bicim_degisik).to_excel(w, sheet_name="Toplama", index=False)
        pd.DataFrame({"Not": ["WMS çıktısı (sentetik)"]}).to_excel(w, sheet_name="Bilgi", index=False)
    pers = os.path.join(a.klasor, "personel_listesi.xlsx")
    personel().to_excel(pers, index=False, sheet_name="Personel")
    csv = os.path.join(a.klasor, "personel_listesi.csv")
    personel().to_csv(csv, sep=";", index=False, encoding="utf-8-sig")
    print("Oluşturuldu:\n ", rapor, "\n ", pers, "\n ", csv)


if __name__ == "__main__":
    main()
