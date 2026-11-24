"""İki veritabanını tablo tablo, satır satır karşılaştırır (örneğin 'stats' ve 'cdn' kipinde yapılmış iki çalıştırma).

Çekim zamanı gibi çalıştırmaya özgü sütunlar ile çalışma kaydı karşılaştırılmaz. Hiçbirine yazmaz.

Çalıştırma:  .venv\\Scripts\\python.exe db_karsilastir.py <a.db> <b.db> [tahmin tarihi]
             Tarih verilirse o günün canlı tahminlerinin farkı ayrıca özetlenir.
Çıkış kodu:  0 fark yok, 1 fark var.
"""
import sqlite3
import sys

import pandas as pd

import veritabani

ZAMAN_SUTUNLARI = {"cekim_zamani", "guncelleme", "olusturma", "tahmin_id"}
TAHMIN_ANAHTARI = ["tur", "oyuncu_id", "mac_id", "istatistik"]
SORGULAR = {      # doğal anahtarı başka tabloda duran tablolar
    "tahmin_etken": ("SELECT t.tur, t.oyuncu_id, t.mac_id, t.istatistik, e.etken, e.carpan, e.veri_var, e.orneklem, e.aciklama "
                     "FROM tahmin_etken e JOIN tahminler t USING (tahmin_id)", TAHMIN_ANAHTARI + ["etken"]),
}


def oku(yol, tablo):
    sorgu, anahtar = SORGULAR.get(tablo, (f'SELECT * FROM "{tablo}"', list(veritabani.ANAHTARLAR[tablo])))
    with sqlite3.connect(f"file:{yol}?mode=ro", uri=True) as c:
        df = pd.read_sql_query(sorgu, c)
    return df.drop(columns=[s for s in df.columns if s in ZAMAN_SUTUNLARI]).set_index(anahtar).sort_index()


def farklar(a, b):
    """Döndürür: (yalnız a'daki anahtarlar, yalnız b'deki anahtarlar, ortak satırlarda farklı hücrelerin tablosu [bool])."""
    ortak = a.index.intersection(b.index)
    x, y = a.loc[ortak], b.loc[ortak]
    esit = (x == y) | (x.isna() & y.isna())
    for s in x.columns:                                  # kayan noktalı sütunlarda yuvarlama farkı sayılmaz
        if pd.api.types.is_float_dtype(x[s]) or pd.api.types.is_float_dtype(y[s]):
            esit[s] = esit[s] | ((pd.to_numeric(x[s], errors="coerce") - pd.to_numeric(y[s], errors="coerce")).abs() < 1e-9)
    return a.index.difference(b.index), b.index.difference(a.index), ~esit


def tablo_karsilastir(tablo, yol_a, yol_b, ornek=4):
    a, b = oku(yol_a, tablo), oku(yol_b, tablo)
    yalniz_a, yalniz_b, farkli = farklar(a, b)
    satir = farkli.any(axis=1)
    toplam = len(yalniz_a) + len(yalniz_b) + int(satir.sum())
    print(f"{tablo:<18} a {len(a):>7}  b {len(b):>7}  yalnız a {len(yalniz_a):>5}  yalnız b {len(yalniz_b):>5}  değeri farklı {int(satir.sum()):>5}"
          + (f"   sütunlar: {farkli.sum()[farkli.sum() > 0].to_dict()}" if satir.any() else ""))
    for ad, anahtarlar in (("yalnız a", yalniz_a), ("yalnız b", yalniz_b)):
        for k in list(anahtarlar)[:ornek]:
            print(f"      {ad}: {k}")
    for k in list(farkli.index[satir])[:ornek]:
        print(f"      farklı: {k} " + ", ".join(f"{s}: {a.loc[k, s]!r} / {b.loc[k, s]!r}" for s in farkli.columns if farkli.loc[k, s])[:300])
    return toplam


def tahmin_ozeti(yol_a, yol_b, tarih):
    a, b = (oku(yol, "tahminler") for yol in (yol_a, yol_b))
    a, b = (df[(df["tarih"] == tarih) & (df.index.get_level_values("tur") == "canli")] for df in (a, b))
    ortak = a.index.intersection(b.index)
    print(f"\n{tarih} canlı tahminleri: a {len(a)}, b {len(b)}, ortak {len(ortak)}")
    for sutun in ("tahmin", "guven", "alt", "ust", "on_tahmin"):
        fark = (a.loc[ortak, sutun] - b.loc[ortak, sutun]).abs()
        print(f"    {sutun:<10} farklı satır {int((fark > 1e-9).sum()):>5}   en büyük fark {fark.max() if len(fark) else 0:.6f}")


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    yol_a, yol_b = argv[:2]
    print(f"a = {yol_a}\nb = {yol_b}\n")
    toplam = sum(tablo_karsilastir(tablo, yol_a, yol_b) for tablo in veritabani.ANAHTARLAR)
    if len(argv) == 3:
        tahmin_ozeti(yol_a, yol_b, argv[2])
    print(f"\ntoplam fark: {toplam}")
    return 0 if toplam == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
