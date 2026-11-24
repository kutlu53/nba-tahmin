"""Sezon başından bugüne veri doldurma (PLAN adım 2).

Çalıştırma:  .venv\\Scripts\\python.exe ilk_kurulum.py
Yeniden çalıştırılabilir: var olan satırlar güncellenir, kutu skoru alınmış
maçlar yeniden çekilmez. Sonunda veriyi kendi içinde ve nba.com ile karşılaştırır.
"""
import random
import sys
import uuid

import config
import veritabani
import yolculuk
import yukle
from kaynak import nba_stats

DOGRULAMA_MAC_SAYISI = 3
KARSILASTIRILAN = ("sayi", "ribaund", "asist", "ucluk", "top_calma", "blok", "top_kaybi")


def dogrula(conn, mac_sayisi=DOGRULAMA_MAC_SAYISI):
    """Veriyi kendi içinde ve nba.com ile karşılaştırır. Sorun yoksa True döner."""
    sorunlar = []
    tek = lambda sql: conn.execute(sql).fetchone()[0]

    oynanan = tek("SELECT COUNT(*) FROM maclar WHERE durum = 'oynandi'")
    kayitli = tek("SELECT COUNT(DISTINCT mac_id) FROM oyuncu_mac")
    aralik = conn.execute("SELECT MIN(tarih), MAX(tarih) FROM maclar WHERE durum = 'oynandi'").fetchone()
    print(f"\n=== Doğrulama ===\nOynanan maç: fikstürde {oynanan}, maç kaydında {kayitli} ({aralik[0]} – {aralik[1]})")
    print(f"Oyuncu-maç satırı: {tek('SELECT COUNT(*) FROM oyuncu_mac')}, oyuncu: {tek('SELECT COUNT(*) FROM oyuncular')}")
    if oynanan != kayitli:
        sorunlar.append(f"oynanan maç sayısı tutmuyor: fikstür {oynanan}, maç kaydı {kayitli}")

    # Her maçta oyuncu sayılarının toplamı, fikstürdeki maç skoruna eşit olmalı.
    skor = conn.execute("""
        SELECT COUNT(*) AS takim_mac,
               SUM(toplam <> CASE WHEN ev_mi = 1 THEN ev_sayi ELSE dep_sayi END) AS tutmayan
        FROM (SELECT om.mac_id, om.ev_mi, SUM(om.sayi) AS toplam, m.ev_sayi, m.dep_sayi
              FROM oyuncu_mac om JOIN maclar m USING (mac_id) GROUP BY om.mac_id, om.ev_mi)
    """).fetchone()
    print(f"Skor denetimi: {skor['takim_mac']} takım-maçın {skor['takim_mac'] - skor['tutmayan']} tanesinde oyuncu sayıları toplamı = maç skoru")
    if skor["tutmayan"]:
        sorunlar.append(f"{skor['tutmayan']} takım-maçta oyuncu sayıları toplamı maç skorunu tutmuyor")

    ilk_bes = conn.execute("""
        SELECT SUM(n = 5) AS bes, SUM(n <> 5) AS farkli, SUM(eksik > 0) AS eksik
        FROM (SELECT SUM(ilk_bes) AS n, SUM(ilk_bes IS NULL) AS eksik FROM oyuncu_mac GROUP BY mac_id, takim_id)
        """).fetchone()
    print(f"İlk beş denetimi: {ilk_bes['bes']} takım-maçta tam 5 ilk beş oyuncusu; bilgisi eksik takım-maç: {ilk_bes['eksik']}")
    if ilk_bes["farkli"] or ilk_bes["eksik"]:
        sorunlar.append(f"ilk beş bilgisi eksik ya da 5'ten farklı olan takım-maç: {(ilk_bes['farkli'] or 0) + (ilk_bes['eksik'] or 0)}")

    # Rastgele maçlar: oyuncu oyuncu nba.com kutu skoruyla karşılaştır.
    adaylar = [s[0] for s in conn.execute("SELECT DISTINCT mac_id FROM oyuncu_mac ORDER BY mac_id")]
    for mac_id in random.sample(adaylar, min(mac_sayisi, len(adaylar))):
        m = conn.execute("""
            SELECT m.tarih, e.kisaltma AS ev, d.kisaltma AS dep, m.ev_sayi, m.dep_sayi
            FROM maclar m JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id
            WHERE m.mac_id = ?""", (mac_id,)).fetchone()
        bizim = {s["oyuncu_id"]: s for s in conn.execute(
            "SELECT om.*, o.isim FROM oyuncu_mac om JOIN oyuncular o USING (oyuncu_id) WHERE om.mac_id = ?", (mac_id,))}
        nba = nba_stats.nba_com_kutu_skoru(mac_id)
        onlar = {**nba["ev"]["oyuncular"], **nba["dep"]["oyuncular"]}
        farklar = []
        if (m["ev_sayi"], m["dep_sayi"]) != (nba["ev"]["sayi"], nba["dep"]["sayi"]):
            farklar.append(f"skor: bizde {m['ev_sayi']}-{m['dep_sayi']}, nba.com {nba['ev']['sayi']}-{nba['dep']['sayi']}")
        # Maç kaydında 0 dakikalı satır olabilir; nba.com'da "oynadı" sayılmayanları ayırma.
        for pid in set(bizim) ^ set(onlar):
            ad = bizim[pid]["isim"] if pid in bizim else onlar[pid]["isim"]
            if pid in bizim and not bizim[pid]["dakika"]:
                continue
            farklar.append(f"{ad}: yalnızca {'bizde' if pid in bizim else 'nba.com’da'} var")
        for pid in set(bizim) & set(onlar):
            b, o = bizim[pid], onlar[pid]
            for alan in KARSILASTIRILAN + ("ilk_bes",):
                if b[alan] != o[alan]:
                    farklar.append(f"{b['isim']} {alan}: bizde {b[alan]}, nba.com {o[alan]}")
            if abs(b["dakika"] - o["dakika"]) > 0.02:
                farklar.append(f"{b['isim']} dakika: bizde {b['dakika']:.2f}, nba.com {o['dakika']:.2f}")

        print(f"\n{m['tarih']}  {m['dep']} {m['dep_sayi']} @ {m['ev']} {m['ev_sayi']}   https://www.nba.com/game/{mac_id}/box-score")
        print(f"  {len(set(bizim) & set(onlar))} oyuncu × {len(KARSILASTIRILAN) + 2} alan karşılaştırıldı: " + ("hepsi aynı" if not farklar else f"{len(farklar)} FARK"))
        for f in farklar:
            print("   FARK:", f)
        for s in sorted(bizim.values(), key=lambda s: -s["sayi"])[:3]:
            print(f"   {s['isim']:<26} {s['dakika']:5.1f} dk  {s['sayi']:>2} sayı  {s['ribaund']:>2} rib  {s['asist']:>2} ast  {s['ucluk']} üçlük  {s['top_calma']} tç  {s['blok']} blok  {s['top_kaybi']} tk")
        sorunlar += [f"{mac_id}: {f}" for f in farklar]

    print("\nSONUÇ: " + ("sorun yok" if not sorunlar else f"{len(sorunlar)} sorun"))
    for s in sorunlar:
        print("  -", s)
    return not sorunlar


def main():
    yukle.log_kur("ilk_kurulum")
    calisma_id = f"ilk_kurulum-{uuid.uuid4().hex[:8]}"
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        yukle.adim(conn, calisma_id, "takimlar", lambda: yukle.takimlari_yukle(conn))
        yukle.adim(conn, calisma_id, "fikstur", lambda: yukle.fiksturu_yukle(conn))
        yukle.adim(conn, calisma_id, "mac_kayitlari", lambda: yukle.mac_kayitlarini_yukle(conn, tarihten=config.SEZON_BASLANGIC))
        yukle.adim(conn, calisma_id, "gecen_sezon", lambda: yukle.gecen_sezonu_yukle(conn))
        yukle.adim(conn, calisma_id, "takim_mac", lambda: yukle.takim_kayitlarini_yukle(conn, tarihten=config.SEZON_BASLANGIC))
        yukle.adim(conn, calisma_id, "yolculuk", lambda: yolculuk.yolculugu_yaz(conn))
        yukle.adim(conn, calisma_id, "hakemler", lambda: yukle.hakemleri_yukle(conn))
        yukle.adim(conn, calisma_id, "takip", lambda: yukle.takip_verisini_yukle(conn))
        yukle.adim(conn, calisma_id, "gecmis_oranlar", lambda: yukle.gecmis_oranlari_yukle(conn))
        yukle.adim(conn, calisma_id, "kullanim", lambda: yukle.kullanim_oranlarini_yaz(conn))
        return 0 if yukle.adim(conn, calisma_id, "dogrulama", lambda: dogrula(conn)) else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
