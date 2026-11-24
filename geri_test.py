"""Geri test (PLAN bölüm 8): tahminleri gerçek sonuçla puanlar, hata ve güven dilimi raporu çıkarır.

Geriye dönük deneme: sezonun oynanmış her maç günü için yalnızca o günden önceki
veriyle tahmin üretir (tur = 'geri_test'), sonra gerçekleşen değerlerle puanlar.

Çalıştırma:
    .venv\\Scripts\\python.exe geri_test.py                 sezon başından düne kadar dene + rapor
    .venv\\Scripts\\python.exe geri_test.py 2026-11-01 2026-11-22
    .venv\\Scripts\\python.exe geri_test.py rapor            yeniden hesaplamadan rapor
"""
import logging
import sys
import time

import pandas as pd

import config
import etkenler
import tahmin
import veritabani

log = logging.getLogger("geri_test")

ISTATISTIKLER = list(config.ISTATISTIKLER)


def puanla(conn, tur=None):
    """Oynanmış maçların tahminlerine gerçekleşen değeri ve hatayı (tahmin − gerçekleşen) yazar.

    Oyuncu o maçta oynamadıysa gerçekleşen değer boş kalır: tahmin "oynarsa" koşulludur.
    Döndürür: puanlı tahmin sayısı.
    """
    kosul, parametre = ("AND tur = ?", (tur,)) if tur else ("", ())
    ifadeler = {ist: f"om.{ist}" for ist in ISTATISTIKLER}
    ifadeler.update({ad: " + ".join(f"om.{p}" for p in parcalar) for ad, parcalar in config.BIRLESIK.items()})
    with conn:
        for ist, ifade in ifadeler.items():
            conn.execute(f"""
                UPDATE tahminler SET gerceklesen = (
                    SELECT {ifade} FROM oyuncu_mac om
                    WHERE om.oyuncu_id = tahminler.oyuncu_id AND om.mac_id = tahminler.mac_id AND om.dakika > 0)
                WHERE istatistik = ? {kosul}
                  AND mac_id IN (SELECT mac_id FROM maclar WHERE durum = 'oynandi')""", (ist, *parametre))
        conn.execute(f"UPDATE tahminler SET hata = tahmin - gerceklesen, on_hata = on_tahmin - gerceklesen WHERE 1 = 1 {kosul}", parametre)
    return conn.execute(f"SELECT COUNT(*) FROM tahminler WHERE gerceklesen IS NOT NULL {kosul}", parametre).fetchone()[0]


def gecmisi_dene(conn, baslangic=None, bitis=None):
    """Aralıktaki her maç günü için geriye dönük tahmin üretir ve puanlar. Döndürür: (gün sayısı, tahmin satırı)."""
    baslangic = baslangic or config.SEZON_BASLANGIC
    bitis = bitis or veritabani.abd_bugun()
    gunler = [s[0] for s in conn.execute(
        "SELECT DISTINCT tarih FROM maclar WHERE durum = 'oynandi' AND tarih >= ? AND tarih <= ? ORDER BY tarih", (baslangic, bitis))]
    etken_listesi = etkenler.acik_etkenler()
    basla, satir = time.monotonic(), 0
    for sira, gun in enumerate(gunler, 1):
        satir += len(tahmin.gunu_tahmin_et(conn, gun, tur="geri_test", etken_listesi=etken_listesi))
        if sira % 5 == 0 or sira == len(gunler):
            log.info("Geriye dönük deneme: %d/%d gün, %d tahmin satırı, %.0f sn", sira, len(gunler), satir, time.monotonic() - basla)
    puanla(conn, "geri_test")
    return len(gunler), satir


def tahminleri_oku(conn, tur="geri_test", baslangic=None, bitis=None):
    """Puanlı ve puansız tahminler; girdilerden gereken alanlar ve gerçekleşen dakika ile."""
    df = pd.DataFrame([dict(s) for s in conn.execute("""
        SELECT th.tahmin_id, th.tarih, th.oyuncu_id, th.mac_id, th.istatistik, th.tahmin, th.guven, th.gerceklesen, th.hata,
               th.alt, th.ust, th.calistirma, th.on_tahmin, th.on_hata,
               json_extract(th.girdiler, '$.temel_tahmin') AS temel_tahmin,
               json_extract(th.girdiler, '$.sezon_ort') AS sezon_ort,
               json_extract(th.girdiler, '$.beklenen_dakika') AS beklenen_dakika,
               json_extract(th.girdiler, '$.duzeltilmis_dakika') AS duzeltilmis_dakika,
               om.dakika AS gercek_dakika
        FROM tahminler th LEFT JOIN oyuncu_mac om ON om.oyuncu_id = th.oyuncu_id AND om.mac_id = th.mac_id
        WHERE th.tur = ? AND th.tarih >= ? AND th.tarih <= ?""",
        (tur, baslangic or "0000", bitis or "9999"))])
    if df.empty:
        return df
    # Birleşik değerlerin ölçütü, bileşenlerinin sezon ortalamalarının toplamıdır.
    ort = df[df["istatistik"].isin(ISTATISTIKLER)].pivot(index=["oyuncu_id", "mac_id"], columns="istatistik", values="sezon_ort")
    anahtar = pd.MultiIndex.from_frame(df[["oyuncu_id", "mac_id"]])
    for ad, parcalar in config.BIRLESIK.items():
        secim = (df["istatistik"] == ad).to_numpy()
        df.loc[secim, "sezon_ort"] = ort[list(parcalar)].sum(axis=1).reindex(anahtar[secim]).to_numpy()
    return df


def etken_carpanlari(conn, tur="geri_test"):
    """tahmin_id × etken -> çarpan tablosu (geniş biçim)."""
    df = pd.DataFrame([dict(s) for s in conn.execute("""
        SELECT te.tahmin_id, te.etken, te.carpan, te.veri_var FROM tahmin_etken te
        JOIN tahminler th USING (tahmin_id) WHERE th.tur = ?""", (tur,))])
    if df.empty:
        return df, df
    return (df.pivot(index="tahmin_id", columns="etken", values="carpan"),
            df.pivot(index="tahmin_id", columns="etken", values="veri_var"))


def isabet(tahmin_degeri, hata):
    """|hata| ≤ max(1 birim, tahminin %25'i) ise isabet."""
    return hata.abs() <= (tahmin_degeri * config.ISABET_ORANI).clip(lower=config.ISABET_MUTLAK)


def istatistik_ozeti(p):
    """İstatistik başına: n, ortalama mutlak hata, yanlılık, sezon ortalamasıyla tahmine göre iyileşme."""
    p = p.assign(mutlak=p["hata"].abs(), olcut=(p["sezon_ort"] - p["gerceklesen"]).abs())
    g = p.groupby("istatistik", sort=False)
    ozet = g.agg(n=("hata", "size"), ort_gercek=("gerceklesen", "mean"), omh=("mutlak", "mean"), yanlilik=("hata", "mean"), olcut_omh=("olcut", "mean"))
    ozet["iyilesme"] = 100 * (1 - ozet["omh"] / ozet["olcut_omh"])
    return ozet


def guven_dilimleri(p):
    """İstatistik × güven dilimi: n, OMH, göreli hata (OMH / ortalama tahmin), isabet oranı."""
    kenarlar = list(config.GUVEN_DILIMLERI)
    etiketler = [f"{a}–{b}" for a, b in zip(kenarlar, kenarlar[1:])]
    p = p.assign(dilim=pd.cut(p["guven"], kenarlar, labels=etiketler, include_lowest=True),
                 mutlak=p["hata"].abs(), isabet=isabet(p["tahmin"], p["hata"]))
    g = p.groupby(["istatistik", "dilim"], sort=False, observed=True)
    d = g.agg(n=("hata", "size"), omh=("mutlak", "mean"), ort_tahmin=("tahmin", "mean"), isabet=("isabet", "mean"))
    d["goreli"] = d["omh"] / d["ort_tahmin"]
    return d, etiketler


def toplam_carpan(c, acik):
    """Seçilen etkenlerin toplam çarpanı; zincirdeki kuralla: temel etkenler genel sınırın dışındadır."""
    alt, ust = config.GENEL_CARPAN_SINIRI
    temel = [e for e in acik if config.ETKENLER.get(e, {}).get("tur", "carpan") != "carpan"]
    diger = [e for e in acik if e not in temel]
    return c[temel].prod(axis=1) * c[diger].prod(axis=1).clip(alt, ust)


def etken_katkisi(p, carpan):
    """Her istatistik için: tüm etkenlerle, etkensiz ve her etken tek tek çıkarıldığında OMH.

    Yeniden tahmin üretmez: kayıtlı temel tahmin ve etken çarpanlarından yeniden birleştirir.
    """
    p = p[p["istatistik"].isin(ISTATISTIKLER) & p["tahmin_id"].isin(carpan.index)]
    c = carpan.reindex(p["tahmin_id"]).fillna(1.0).set_axis(p.index)
    secenekler = {"hepsi açık": list(c.columns), "hepsi kapalı": []}
    secenekler.update({f"{e} kapalı": [x for x in c.columns if x != e] for e in c.columns})
    tablo = {}
    for ad, acik in secenekler.items():
        toplam = toplam_carpan(c, acik)
        hata = (p["temel_tahmin"] * toplam - p["gerceklesen"]).abs()
        tablo[ad] = hata.groupby(p["istatistik"], sort=False).mean()
    return pd.DataFrame(tablo).reindex(ISTATISTIKLER)


def rapor_metni(conn, tur="geri_test", baslangic=None, bitis=None):
    df = tahminleri_oku(conn, tur, baslangic, bitis)
    if df.empty:
        return f"'{tur}' türünde tahmin yok."
    p = df[df["gerceklesen"].notna()]
    s = [f"=== Geri test raporu ({tur}; {df['tarih'].min()} – {df['tarih'].max()}) ==="]
    s.append(f"{df['tarih'].nunique()} maç günü, {df['mac_id'].nunique()} maç, {len(df)} tahmin satırı; "
             f"puanlanan {len(p)} (%{100 * len(p) / len(df):.0f}). Puanlanmayanlar: oyuncu o maçta oynamadı.")
    if p.empty:
        return "\n".join(s + ["Puanlanmış tahmin yok."])
    s.append("Hata = tahmin − gerçekleşen. OMH = ortalama mutlak hata.")

    sayi = p[p["istatistik"] == "sayi"]
    dk_hata = sayi["beklenen_dakika"] - sayi["gercek_dakika"]
    duz_hata = sayi["duzeltilmis_dakika"].fillna(sayi["beklenen_dakika"]) - sayi["gercek_dakika"]
    s.append(f"\nBEKLENEN DAKİKA: {len(sayi)} oyuncu-maç; son maçların ortalaması: OMH {dk_hata.abs().mean():.2f} dk, yanlılık {dk_hata.mean():+.2f} dk; "
             f"dakika etkenleriyle düzeltilmiş: OMH {duz_hata.abs().mean():.2f} dk, yanlılık {duz_hata.mean():+.2f} dk "
             f"(gerçekleşen ortalama {sayi['gercek_dakika'].mean():.1f} dk)")

    s.append("\nİSTATİSTİK BAŞINA HATA (ölçüt = oyuncunun o güne kadarki sezon maç ortalamasını tahmin saymak)")
    s.append(f"  {'istatistik':<20}{'n':>7}{'ort.gerçek':>12}{'OMH':>8}{'yanlılık':>10}{'ölçüt OMH':>11}{'iyileşme':>10}")
    ozet = istatistik_ozeti(p).reindex(ISTATISTIKLER + list(config.BIRLESIK))
    for ist, o in ozet.iterrows():
        s.append(f"  {ist:<20}{int(o['n']):>7}{o['ort_gercek']:>12.2f}{o['omh']:>8.2f}{o['yanlilik']:>+10.2f}{o['olcut_omh']:>11.2f}{o['iyilesme']:>9.1f}%")

    d, etiketler = guven_dilimleri(p)
    s.append(f"\nGÜVEN DİLİMLERİ: göreli hata = OMH / ortalama tahmin; isabet = |hata| ≤ max({config.ISABET_MUTLAK:g}, tahminin %{100 * config.ISABET_ORANI:.0f}'i)")
    s.append(f"  {'istatistik':<12}" + "".join(f"{e:>26}" for e in etiketler) + "   yüksek güven daha isabetli mi?")
    s.append(f"  {'':<12}" + "".join(f"{'n   OMH  göreli isabet':>26}" for _ in etiketler))
    for ist in ISTATISTIKLER:
        satir, goreli = f"  {ist:<12}", []
        for e in etiketler:
            if (ist, e) in d.index:
                x = d.loc[(ist, e)]
                satir += f"{int(x['n']):>8}{x['omh']:>6.2f}{x['goreli']:>7.2f}{100 * x['isabet']:>4.0f}%"
                if x["n"] >= 30:
                    goreli.append(x["goreli"])
            else:
                satir += f"{'-':>26}"
        sirali = all(a >= b for a, b in zip(goreli, goreli[1:]))
        s.append(satir + ("   evet" if sirali and len(goreli) > 1 else "   HAYIR" if len(goreli) > 1 else "   (yetersiz veri)"))

    a = p[p["alt"].notna() & p["ust"].notna()]
    if not a.empty:
        s.append("\nARALIK KAPSAMI: gerçekleşen değerin alt (%10) – üst (%90) aralığına düşme oranı; hedef %80, altında %10, üstünde %10")
        s.append(f"  {'istatistik':<20}{'altında':>10}{'içinde':>10}{'üstünde':>10}{'ort. aralık genişliği':>24}")
        for ist in ISTATISTIKLER + list(config.BIRLESIK):
            x = a[a["istatistik"] == ist]
            if len(x):
                s.append(f"  {ist:<20}{f'%{100 * (x.gerceklesen < x.alt).mean():.0f}':>10}{f'%{100 * ((x.gerceklesen >= x.alt) & (x.gerceklesen <= x.ust)).mean():.0f}':>10}"
                         f"{f'%{100 * (x.gerceklesen > x.ust).mean():.0f}':>10}{(x.ust - x.alt).mean():>24.2f}")
    ikili = p[p["on_tahmin"].notna() & (p["calistirma"] == "mac_oncesi")]
    if not ikili.empty:
        s.append("\nÖN TAHMİN (sabah) ve KESİN TAHMİN (maç öncesi): aynı tahminlerde ortalama mutlak hata; fark, geç gelen verinin değeridir")
        for ist in ISTATISTIKLER:
            x = ikili[ikili["istatistik"] == ist]
            if len(x):
                s.append(f"  {ist:<12} n={len(x):>5}   ön {x.on_hata.abs().mean():.3f}   kesin {x.hata.abs().mean():.3f}   fark {x.hata.abs().mean() - x.on_hata.abs().mean():+.3f}")

    carpan, veri_var = etken_carpanlari(conn, tur)
    if not carpan.empty:
        k = etken_katkisi(p, carpan)
        s.append("\nETKEN KATKISI: OMH; bir etken kapatılınca hata artıyorsa o etken işe yarıyor demektir")
        s.append(f"  {'istatistik':<12}" + "".join(f"{ad:>22}" for ad in k.columns))
        for ist, satir in k.iterrows():
            s.append(f"  {ist:<12}" + "".join(f"{x:>22.4f}" for x in satir))
        hatalar = conn.execute("""
            SELECT te.etken, COUNT(*) AS n, MIN(te.aciklama) AS ornek FROM tahmin_etken te JOIN tahminler th USING (tahmin_id)
            WHERE th.tur = ? AND te.aciklama LIKE 'hata:%' GROUP BY te.etken""", (tur,)).fetchall()
        s.append("  ETKEN HATALARI: " + ("yok" if not hatalar else "; ".join(f"{h['etken']} {h['n']} tahminde hata verdi ve nötr sayıldı ({h['ornek'][:90]})" for h in hatalar)))
        temel = p[p["istatistik"].isin(ISTATISTIKLER)]
        s.append("  Verisi olan tahmin oranı: " + ", ".join(
            f"{e} %{100 * veri_var[e].reindex(temel['tahmin_id']).mean():.0f}" for e in veri_var.columns))
    return "\n".join(s)


def main(argv):
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        if argv[:1] != ["rapor"]:
            dun = pd.Timestamp(veritabani.abd_bugun()) - pd.Timedelta(days=1)
            gecmisi_dene(conn, argv[0] if argv else None, argv[1] if len(argv) > 1 else dun.strftime("%Y-%m-%d"))
        metin = rapor_metni(conn)
        config.RAPOR_KLASORU.mkdir(exist_ok=True)
        (config.RAPOR_KLASORU / "geri_test.txt").write_text(metin + "\n", encoding="utf-8")
        print(metin)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
