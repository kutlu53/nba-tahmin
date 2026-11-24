"""Etken zincirinden bağımsız, "eski usul" tahmin hesabı (PLAN bölüm 6).

Tek bir işlev, her şeyi doğrudan veri tabanından SQL ile hesaplar: Baglam'ı,
etkenler/ klasörünü ve savunma.py'yi kullanmaz. E1 kabul ölçütü ("eski ve yeni
tahminler aynı sonucu veriyor") için zincirin sonucu bununla karşılaştırılır.

Gerçek veri üzerinde karşılaştırma:  .venv\\Scripts\\python.exe -m testler.referans_tahmin [YYYY-AA-GG]
"""
import sys

import config


def _sinir(deger, ad):
    return max(config.ETKENLER[ad]["alt"], min(config.ETKENLER[ad]["ust"], deger))


def referans_tahmin(conn, oyuncu_id, takim_id, pozisyon, mac_id, ist, tarih):
    """Bir oyuncu, maç ve istatistik için tahmin; tahmin üretilmeyecekse None."""
    mac = conn.execute("SELECT ev_takim_id, dep_takim_id FROM maclar WHERE mac_id = ?", (mac_id,)).fetchone()
    ev_mi = int(takim_id == mac["ev_takim_id"])
    rakip = mac["dep_takim_id"] if ev_mi else mac["ev_takim_id"]

    # --- Oyuncunun formu: temel oran ve beklenen dakika ---
    k = conn.execute(f"""
        SELECT om.dakika, om.ev_mi, om.ilk_bes, om.{ist} AS deger
        FROM oyuncu_mac om JOIN maclar m USING (mac_id)
        WHERE om.oyuncu_id = ? AND m.tarih < ? AND om.dakika > 0 ORDER BY m.tarih, om.mac_id""", (oyuncu_id, tarih)).fetchall()
    if len(k) < config.TAHMIN_MIN_MAC:
        return None
    oran36 = lambda s: 36 * sum(x["deger"] for x in s) / sum(x["dakika"] for x in s)
    temel = 0.40 * oran36(k) + 0.35 * oran36(k[-10:]) + 0.25 * oran36(k[-5:])
    son5 = k[-5:]
    rol_degisti = len({x["ilk_bes"] for x in son5 if x["ilk_bes"] is not None}) > 1
    pencere = k[-3:] if rol_degisti else son5
    dakika = sum(x["dakika"] for x in pencere) / len(pencere)
    if dakika < config.TAHMIN_MIN_DAKIKA:
        return None

    # --- 1) Rakibin pozisyona göre savunması ---
    c_eslesme = 1.0
    if pozisyon:
        sav = conn.execute(f"""
            SELECT SUM(CASE WHEN om.rakip_id = :rakip THEN om.{ist} END) AS t_deger,
                   SUM(CASE WHEN om.rakip_id = :rakip THEN om.dakika END) AS t_dakika,
                   COUNT(DISTINCT CASE WHEN om.rakip_id = :rakip THEN om.mac_id END) AS n,
                   SUM(om.{ist}) AS l_deger, SUM(om.dakika) AS l_dakika
            FROM oyuncu_mac om JOIN oyuncular o USING (oyuncu_id) JOIN maclar m USING (mac_id)
            WHERE m.tarih < :tarih AND om.dakika >= 10 AND o.pozisyon = :poz""",
            {"rakip": rakip, "tarih": tarih, "poz": pozisyon}).fetchone()
        if sav["n"] and sav["l_deger"]:
            oran = (sav["t_deger"] / sav["t_dakika"]) / (sav["l_deger"] / sav["l_dakika"])
            c_eslesme = _sinir((sav["n"] * oran + 10 * 1.0) / (sav["n"] + 10), "eslesme_ham")

    # --- 2) Ev sahibi / deplasman ---
    lig = conn.execute(f"""
        SELECT SUM(CASE WHEN om.ev_mi = :ev THEN om.{ist} END) AS s_deger, SUM(CASE WHEN om.ev_mi = :ev THEN om.dakika END) AS s_dakika,
               SUM(om.{ist}) AS deger, SUM(om.dakika) AS dakika
        FROM oyuncu_mac om JOIN maclar m USING (mac_id) WHERE m.tarih < :tarih AND om.dakika > 0""", {"ev": ev_mi, "tarih": tarih}).fetchone()
    c_ev = 1.0
    if lig["deger"] and lig["s_dakika"]:
        lig_orani = (lig["s_deger"] / lig["s_dakika"]) / (lig["deger"] / lig["dakika"])
        saha = [x for x in k if x["ev_mi"] == ev_mi]
        genel = sum(x["deger"] for x in k) / sum(x["dakika"] for x in k)
        n, oyuncu_orani = 0, lig_orani
        if saha and genel > 0:
            n = len(saha)
            oyuncu_orani = (sum(x["deger"] for x in saha) / sum(x["dakika"] for x in saha)) / genel
        c_ev = _sinir((n * oyuncu_orani + 20 * lig_orani) / (n + 20), "ev_deplasman")

    # --- 3) Arka arkaya ikinci maç ---
    dun_oynadi = """EXISTS (SELECT 1 FROM maclar d WHERE d.tarih = date({tarih}, '-1 day') AND d.durum <> 'ertelendi'
                            AND {takim} IN (d.ev_takim_id, d.dep_takim_id))"""
    c_aa = 1.0
    if conn.execute("SELECT " + dun_oynadi.format(tarih="?", takim="?"), (tarih, takim_id)).fetchone()[0]:
        aa = conn.execute(f"""
            SELECT SUM(CASE WHEN aa THEN deger END) AS a_deger, SUM(CASE WHEN aa THEN dakika END) AS a_dakika,
                   COUNT(DISTINCT CASE WHEN aa THEN takim_id || '-' || mac_id END) AS n, SUM(deger) AS deger, SUM(dakika) AS dakika
            FROM (SELECT om.{ist} AS deger, om.dakika, om.takim_id, om.mac_id,
                         {dun_oynadi.format(tarih="m.tarih", takim="om.takim_id")} AS aa
                  FROM oyuncu_mac om JOIN maclar m USING (mac_id) WHERE m.tarih < ? AND om.dakika > 0)""", (tarih,)).fetchone()
        if aa["n"] and aa["deger"]:
            oran = (aa["a_deger"] / aa["a_dakika"]) / (aa["deger"] / aa["dakika"])
            c_aa = _sinir((aa["n"] * oran + 60 * 1.0) / (aa["n"] + 60), "arka_arkaya")

    # --- 4) "Out" takım arkadaşlarının boşalttığı dakika ---
    c_eksik = 1.0
    veri_var = conn.execute("SELECT COUNT(*) FROM sakatliklar WHERE kaynak = 'espn' AND cekim_tarihi = ? AND takim_id = ?", (tarih, takim_id)).fetchone()[0]
    son_maclar = [s[0] for s in conn.execute("""
        SELECT mac_id FROM maclar WHERE durum = 'oynandi' AND tarih < ? AND ? IN (ev_takim_id, dep_takim_id)
        ORDER BY tarih DESC, mac_id DESC LIMIT 5""", (tarih, takim_id))]
    if veri_var and son_maclar:
        bosalan = conn.execute(f"""
            SELECT COALESCE(SUM(om.dakika), 0) FROM oyuncu_mac om
            WHERE om.mac_id IN ({','.join('?' * len(son_maclar))}) AND om.oyuncu_id <> ? AND om.oyuncu_id IN (
                SELECT s.oyuncu_id FROM sakatliklar s JOIN oyuncular o USING (oyuncu_id)
                WHERE s.kaynak = 'espn' AND s.cekim_tarihi = ? AND s.durum = 'Out' AND o.takim_id = ?)""",
            (*son_maclar, oyuncu_id, tarih, takim_id)).fetchone()[0] / len(son_maclar)
        if bosalan > 0:
            c_eksik = _sinir(240 / (240 - bosalan), "eksik_arkadas")

    alt, ust = config.GENEL_CARPAN_SINIRI
    carpan = max(alt, min(ust, c_eslesme * c_ev * c_aa * c_eksik))
    return dakika * temel / 36 * carpan


ESKI_ETKENLER = ("eslesme_ham", "ev_deplasman", "arka_arkaya", "eksik_arkadas")   # PLAN bölüm 6'daki girdiler


def karsilastir(conn, tarih):
    """Günün oynanacak maçları için zinciri (yalnızca PLAN bölüm 6'daki dört etkenle) referansla karşılaştırır.

    Sonradan eklenen etkenler (tempo vb.) bu karşılaştırmanın dışındadır: referans "eski" modeldir.
    Döndürür: (satır sayısı, en büyük fark, farklı satırlar).
    """
    import etkenler
    import tahmin

    baglam = tahmin.Baglam(conn, tarih)
    liste = etkenler.acik_etkenler({ad: {**config.ETKENLER[ad], "acik": True} for ad in ESKI_ETKENLER})
    n, en_buyuk, farkli = 0, 0.0, []
    for mac in tahmin.gunun_maclari(conn, tarih):
        for oyuncu in tahmin.tahmin_edilecekler(baglam, mac):
            for t in tahmin.oyuncu_tahmini(baglam, oyuncu, mac, liste):
                if t["istatistik"] not in config.ISTATISTIKLER:
                    continue
                ref = referans_tahmin(conn, oyuncu.oyuncu_id, oyuncu.takim_id, oyuncu.pozisyon, mac.mac_id, t["istatistik"], tarih)
                fark = abs(ref - t["tahmin"]) if ref is not None else float("inf")
                n, en_buyuk = n + 1, max(en_buyuk, fark)
                if fark > 1e-9:
                    farkli.append((oyuncu.isim, t["istatistik"], t["tahmin"], ref))
    return n, en_buyuk, farkli


if __name__ == "__main__":
    import veritabani
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    n, en_buyuk, farkli = karsilastir(baglanti, gun)
    print(f"{gun}: {n} tahmin karşılaştırıldı (7 istatistik); zincir ile referans arasındaki en büyük fark: {en_buyuk:.2e}")
    print(f"Farklı çıkan satır (1e-9 üstü): {len(farkli)}")
    for f in farkli[:20]:
        print("  ", f)
    baglanti.close()
    sys.exit(1 if farkli or not n else 0)
