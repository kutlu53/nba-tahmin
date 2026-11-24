"""Üst / alt: bir oyuncunun bir istatistikte verilen çizginin üstünde mi altında mı kalacağı.

    .venv\\Scripts\\python.exe ust_alt.py "LeBron James" sayi 13.5
    .venv\\Scripts\\python.exe ust_alt.py "lebron" ribaund 6.5
    .venv\\Scripts\\python.exe ust_alt.py "lebron" sayi+ribaund+asist 27.5

İstatistikler: sayi, ribaund, asist, ucluk, top_calma, blok, top_kaybi ve birleşikler
(sayi+ribaund+asist, sayi+ribaund, sayi+asist, ribaund+asist).

Olasılık, günün tahmininden (orta değer) ve tahminin standart sapmasından kurulan sayım
dağılımından hesaplanır: varyans ortalamadan büyükse negatif binom, değilse Poisson.
"Üst" çizgiden büyük, "alt" çizgiye eşit ya da küçük değerdir (çizgiler genellikle buçukludur).
Tahmin "oyuncu oynarsa" koşulludur.
"""
import math
import sys

import config
import kadro
import veritabani

KARARSIZ = 0.05      # olasılık %50'ye bu kadar yakınsa taraf söylenmez


def ust_olasiligi(tahmin, sapma, cizgi):
    """Gerçekleşen değerin çizgiden BÜYÜK olma olasılığı."""
    if tahmin is None or tahmin <= 0:
        return 0.0
    varyans = (sapma or 0.0) ** 2
    if varyans > tahmin * 1.0001:                       # negatif binom: ortalama = tahmin, varyans = sapma²
        r = tahmin * tahmin / (varyans - tahmin)
        q = tahmin / (r + tahmin)
        olasilik, carpan = (1.0 - q) ** r, lambda i: (i + r) / (i + 1) * q
    else:                                               # Poisson
        olasilik, carpan = math.exp(-tahmin), lambda i: tahmin / (i + 1)
    birikimli = 0.0
    for i in range(int(math.floor(cizgi)) + 1):         # P(X ≤ ⌊çizgi⌋)
        birikimli += olasilik
        olasilik *= carpan(i)
    return min(1.0, max(0.0, 1.0 - birikimli))


def taraf(olasilik):
    if abs(olasilik - 0.5) < KARARSIZ:
        return "kararsız"
    return "ÜST" if olasilik > 0.5 else "ALT"


def sapma(tahmin, ust):
    """Tahminin standart sapması, kayıtlı üst (%90) değerinden."""
    return (ust - tahmin) / config.ARALIK_Z if ust is not None else None


def oyuncu_tahmini(conn, isim, istatistik, tarih=None):
    """Günün canlı tahminlerinden oyuncunun satırı; bulunamazsa None. İsim, adın bir parçası olabilir (aksansız, küçük harf)."""
    tarih = tarih or conn.execute("SELECT MAX(tarih) FROM tahminler WHERE tur = 'canli'").fetchone()[0]
    aranan = kadro.sade_isim(isim)
    adaylar = [s for s in conn.execute("""
        SELECT o.isim, tk.kisaltma AS takim, d.kisaltma || ' @ ' || e.kisaltma AS mac, th.tarih, th.tahmin, th.alt, th.ust, th.guven
        FROM tahminler th JOIN oyuncular o USING (oyuncu_id) JOIN maclar m USING (mac_id)
        JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id
        LEFT JOIN takimlar tk ON tk.takim_id = o.takim_id
        WHERE th.tur = 'canli' AND th.tarih = ? AND th.istatistik = ?""", (tarih, istatistik)) if aranan in kadro.sade_isim(s["isim"])]
    tam = [s for s in adaylar if kadro.sade_isim(s["isim"]) == aranan]
    return (tam or adaylar), tarih


def main(argv):
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    gecerli = list(config.ISTATISTIKLER) + list(config.BIRLESIK)
    if len(argv) != 3 or argv[1] not in gecerli:
        print(__doc__)
        return 2
    isim, istatistik = argv[0], argv[1]
    try:
        cizgi = float(argv[2].replace(",", "."))
    except ValueError:
        print(f"Çizgi sayı olmalı: {argv[2]}")
        return 2
    conn = veritabani.baglan()
    try:
        adaylar, tarih = oyuncu_tahmini(conn, isim, istatistik)
    finally:
        conn.close()
    if not adaylar:
        print(f"{tarih} tahminlerinde '{isim}' bulunamadı (oynamıyor, 'Out' ya da tahmin koşullarını sağlamıyor olabilir).")
        return 1
    if len(adaylar) > 1:
        print("Birden fazla oyuncu eşleşti; adı daha açık yaz: " + ", ".join(s["isim"] for s in adaylar))
        return 1
    s = adaylar[0]
    p = ust_olasiligi(s["tahmin"], sapma(s["tahmin"], s["ust"]), cizgi)
    print(f"{s['isim']} ({s['takim']}), {s['mac']}, {s['tarih']}: {istatistik} çizgisi {cizgi:g}")
    print(f"  tahmin {s['tahmin']:.1f} (beklenen aralık {s['alt']:.1f} – {s['ust']:.1f}); veri sağlamlığı {s['guven']:.0f}")
    print(f"  ÜST %{100 * p:.0f}  |  ALT %{100 * (1 - p):.0f}   →  {taraf(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
