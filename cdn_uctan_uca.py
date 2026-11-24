"""Uçtan uca deneme: veritabanının bir kopyasında maç verisini silip nba.com sayfa dosyalarından (cdn kaynağı) yeniden
yükler, sonra tabloları asıl veritabanıyla (stats.nba.com'dan yüklenmiş) satır satır karşılaştırır.

Asıl veritabanına dokunmaz. Sezonun bütün maçlarını indirdiği için 10–15 dakika sürer.

Çalıştırma:  .venv\\Scripts\\python.exe cdn_uctan_uca.py <kopyanın yazılacağı klasör>
"""
import logging
import pathlib
import sqlite3
import sys

import pandas as pd

import config

TABLOLAR = {      # tablo: (anahtar sütunlar, karşılaştırılmayan sütunlar)
    "maclar": (["mac_id"], []),
    "oyuncu_mac": (["mac_id", "oyuncu_id"], []),
    "takim_mac": (["mac_id", "takim_id"], []),
    "oyuncular": (["oyuncu_id"], ["guncelleme"]),
}


def oku(yol, tablo):
    with sqlite3.connect(yol) as c:
        return pd.read_sql_query(f"SELECT * FROM {tablo}", c)


def karsilastir(tablo, asil, kopya):
    anahtar, atla = TABLOLAR[tablo]
    sutunlar = [s for s in asil.columns if s not in anahtar + atla]
    a, b = asil.set_index(anahtar)[sutunlar], kopya.set_index(anahtar)[sutunlar]
    yalniz_a, yalniz_b = a.index.difference(b.index), b.index.difference(a.index)
    ortak = a.index.intersection(b.index)
    x, y = a.loc[ortak], b.loc[ortak]
    sayisal = [s for s in sutunlar if pd.api.types.is_float_dtype(x[s]) or pd.api.types.is_float_dtype(y[s])]
    esit = (x == y) | (x.isna() & y.isna())
    for s in sayisal:                                   # kayan noktalı sütunlarda yuvarlama farkı sayılmaz
        esit[s] = esit[s] | ((x[s] - y[s]).abs() < 1e-9)
    farkli = ~esit
    satir = farkli.any(axis=1)
    print(f"{tablo}: asıl {len(a)} satır, cdn'den yüklenen {len(b)} satır; yalnız asılda {len(yalniz_a)}, yalnız kopyada {len(yalniz_b)}, "
          f"değeri farklı {int(satir.sum())} satır" + (f" (sütun başına: {farkli.sum()[farkli.sum() > 0].to_dict()})" if satir.any() else ""))
    for k in list(yalniz_a)[:5]:
        print(f"    yalnız asılda: {k}")
    for k in list(ortak[satir])[:5]:
        print(f"    farklı: {k} " + ", ".join(f"{s}: asıl {x.loc[k, s]} / cdn {y.loc[k, s]}" for s in sutunlar if farkli.loc[k, s]))
    return len(yalniz_a) + len(yalniz_b) + int(satir.sum())


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    asil_yol = config.DB_YOLU
    kopya_yol = pathlib.Path(argv[0]) / "nba_cdn_deneme.db"
    kopya_yol.parent.mkdir(parents=True, exist_ok=True)
    kopya_yol.unlink(missing_ok=True)
    with sqlite3.connect(asil_yol) as kaynak_db, sqlite3.connect(kopya_yol) as hedef_db:
        kaynak_db.backup(hedef_db)                      # asıl veritabanı o sırada yazılıyor olsa da tutarlı kopya
    asil = {t: oku(kopya_yol, t) for t in TABLOLAR}     # karşılaştırma kopyanın alındığı andaki hale göre yapılır

    config.DB_YOLU, config.VERI_KAYNAGI = kopya_yol, "cdn"
    import kadro
    import veritabani
    import yukle
    from kaynak import nba_cdn

    conn = veritabani.baglan()
    with conn:
        conn.execute("DELETE FROM oyuncu_mac")
        conn.execute("DELETE FROM takim_mac")
        conn.execute("UPDATE maclar SET durum = 'oynanacak', ev_sayi = NULL, dep_sayi = NULL")
        conn.execute("UPDATE oyuncular SET takim_id = NULL, aktif = 0")
    print("kopyada maç verisi silindi; nba.com sayfa dosyalarından yeniden yükleniyor...", flush=True)
    yukle.fiksturu_yukle(conn)
    yazilan, cekilen, alinamayan = yukle.mac_kayitlarini_yukle(conn)
    yukle.takim_kayitlarini_yukle(conn)
    yukle.kullanim_oranlarini_yaz(conn)
    kadro.kadrolari_yukle(conn)
    conn.close()
    print(f"yüklendi: {yazilan} oyuncu-maç satırı, {cekilen} maçın kutu skoru; alınamayan: {alinamayan}; "
          f"kutu skoru kaynağı: maç sayfası {nba_cdn.kutu_kaynaklari['sayfa']}, canlı besleme {nba_cdn.kutu_kaynaklari['canli']}\n")
    toplam = sum(karsilastir(t, asil[t], oku(kopya_yol, t)) for t in TABLOLAR)
    print(f"\ntoplam fark: {toplam}")
    return 0 if toplam == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
