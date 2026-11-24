"""Hakem ekibi (PLAN_EK etken 8).

Her hakem için iki endeks, o güne kadarki maçlardan:
    faul endeksi          = hakemin maçlarındaki toplam faul / iki takımın sezon ortalamalarından beklenen toplam faul
    serbest atış endeksi  = aynısı, serbest atış denemesi için
Beklenen değer, iki takımın (o maç dışındaki) maçlarındaki toplamların ortalamasıdır; uzatmalar
48 dakikaya indirgenir. Endeksler az maçta güçlü biçimde 1,00'e çekilir (k = config.HAKEM_K maç).
Ekip endeksi, atanan hakemlerin düzeltilmiş endekslerinin ortalamasıdır.

Etken yalnızca sayıyı, serbest atış üzerinden etkiler:
    çarpan = 1 + (oyuncunun sayılarında serbest atışın payı) × (ekibin serbest atış endeksi − 1)
Atama henüz yayımlanmadıysa veri_var = False.

Rapor ve hakem_profili tablosu:  .venv\\Scripts\\python.exe -m etkenler.hakem [YYYY-AA-GG]
"""
import sys
from collections import defaultdict

import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok


def endeksler(baglam):
    """{hakem_id: {'mac', 'faul', 'sa', 'faul_duz', 'sa_duz'}}; yalnızca o günden önceki maçlardan."""
    if "hakem" not in baglam.onbellek:
        takim = defaultdict(lambda: [0.0, 0.0, 0])                 # takım -> [faul toplamı, SA toplamı, maç]
        for ev, dep, faul, sa in baglam.mac_dudukleri.values():
            for t in (ev, dep):
                takim[t][0] += faul
                takim[t][1] += sa
                takim[t][2] += 1
        ham = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])         # hakem -> [gerçek faul, beklenen faul, gerçek SA, beklenen SA, maç]
        for mac_id, (ev, dep, faul, sa) in baglam.mac_dudukleri.items():
            hakemler = baglam.hakem_mac.get(mac_id)
            if not hakemler or takim[ev][2] < 2 or takim[dep][2] < 2:
                continue
            beklenen_faul = sum((takim[t][0] - faul) / (takim[t][2] - 1) for t in (ev, dep)) / 2
            beklenen_sa = sum((takim[t][1] - sa) / (takim[t][2] - 1) for t in (ev, dep)) / 2
            for h in hakemler:
                x = ham[h]
                x[0] += faul
                x[1] += beklenen_faul
                x[2] += sa
                x[3] += beklenen_sa
                x[4] += 1
        sonuc = {}
        for h, (gf, bf, gs, bs, n) in ham.items():
            if bf > 0 and bs > 0:
                sonuc[h] = {"mac": n, "faul": gf / bf, "sa": gs / bs,
                            "faul_duz": kucuk_orneklem(n, gf / bf, config.HAKEM_K), "sa_duz": kucuk_orneklem(n, gs / bs, config.HAKEM_K)}
        baglam.onbellek["hakem"] = sonuc
    return baglam.onbellek["hakem"]


def ekip_endeksi(baglam, mac_id):
    """Maça atanan ekibin düzeltilmiş endeksleri: {'sa', 'faul', 'hakem', 'taninan', 'en_az_mac'}; atama yoksa None.

    Daha önce maçını görmediğimiz hakem nötr (1,00) sayılır.
    """
    hakemler = baglam.hakem_mac.get(mac_id)
    if not hakemler:
        return None
    e = endeksler(baglam)
    taninan = [e[h] for h in hakemler if h in e]
    return {
        "sa": sum(e[h]["sa_duz"] if h in e else 1.0 for h in hakemler) / len(hakemler),
        "faul": sum(e[h]["faul_duz"] if h in e else 1.0 for h in hakemler) / len(hakemler),
        "hakem": len(hakemler), "taninan": len(taninan), "en_az_mac": min((x["mac"] for x in taninan), default=0),
    }


def hesapla(oyuncu, mac, istatistik, baglam):
    if istatistik != "sayi":
        return EtkenSonucu(1.0, True, 0, "bu istatistiği etkilemez")
    ekip = ekip_endeksi(baglam, mac.mac_id)
    if ekip is None:
        return veri_yok("hakem ataması yok (henüz yayımlanmadı)")
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is None or k["sayi"].sum() <= 0:
        return veri_yok("oyuncunun sayı kaydı yok")
    pay = float(k["serbest_isabet"].sum() / k["sayi"].sum())
    return EtkenSonucu(
        1.0 + pay * (ekip["sa"] - 1.0), True, ekip["en_az_mac"],
        f"ekibin serbest atış endeksi {ekip['sa']:.3f} ({ekip['taninan']}/{ekip['hakem']} hakem tanınıyor); oyuncunun sayılarında serbest atış payı %{100 * pay:.0f}",
    )


def profili_yaz(conn, baglam, tarih):
    """hakem_profili tablosunu günün görüntüsüyle değiştirir; satır sayısını döndürür."""
    import veritabani

    satirlar = [{"hakem_id": h, "hesap_tarihi": tarih, "mac_sayisi": e["mac"], "faul_endeksi": e["faul"], "serbest_atis_endeksi": e["sa"],
                 "faul_duzeltilmis": e["faul_duz"], "serbest_atis_duzeltilmis": e["sa_duz"]} for h, e in endeksler(baglam).items()]
    try:
        conn.execute("DELETE FROM hakem_profili")
        sayi = veritabani.yaz(conn, "hakem_profili", satirlar)
        conn.commit()
        return sayi
    except Exception:
        conn.rollback()
        raise


def rapor_metni(conn, baglam, tarih):
    import tahmin

    isim = {s["hakem_id"]: s["isim"] for s in conn.execute("SELECT hakem_id, isim FROM hakemler")}
    takim = {s["takim_id"]: s["kisaltma"] for s in conn.execute("SELECT takim_id, kisaltma FROM takimlar")}
    e = endeksler(baglam)
    hakemli = sum(1 for m in baglam.mac_dudukleri if baglam.hakem_mac.get(m))
    s = [f"=== Hakem raporu ({tarih} öncesi maçlar) ==="]
    s.append(f"Hakemi bilinen maç: {hakemli} / {len(baglam.mac_dudukleri)}; profili olan hakem: {len(e)}; "
             f"hakem başına maç: {min((x['mac'] for x in e.values()), default=0)}–{max((x['mac'] for x in e.values()), default=0)}")
    s.append(f"Endeks = hakemin maçlarındaki toplam / iki takımın ortalamalarından beklenen toplam; düzeltilmiş değer {config.HAKEM_K} maçlık ağırlıkla 1,00'e çekilmiştir.")
    if e:
        sirali = sorted(e.items(), key=lambda x: x[1]["sa_duz"])
        for baslik, parca in (("EN AZ SERBEST ATIŞ VEREN HAKEMLER", sirali[:5]), ("EN ÇOK SERBEST ATIŞ VEREN HAKEMLER", sirali[-5:][::-1])):
            s.append(f"\n{baslik}")
            s.append(f"  {'hakem':<26}{'maç':>5}{'SA endeksi':>12}{'düzeltilmiş':>13}{'faul endeksi':>14}{'düzeltilmiş':>13}")
            for h, x in parca:
                s.append(f"  {isim.get(h, str(h))[:26]:<26}{x['mac']:>5}{x['sa']:>12.3f}{x['sa_duz']:>13.3f}{x['faul']:>14.3f}{x['faul_duz']:>13.3f}")
    s.append("\nGÜNÜN ATAMALARI")
    maclar = tahmin.gunun_maclari(conn, tarih)
    atanan = 0
    for mac in maclar:
        ekip = ekip_endeksi(baglam, mac.mac_id)
        ad = f"{takim[mac.dep_takim_id]} @ {takim[mac.ev_takim_id]}"
        if ekip is None:
            s.append(f"  {ad:<12} atama yok")
            continue
        atanan += 1
        hakemler = ", ".join(f"{isim.get(h, str(h))} ({e[h]['sa_duz']:.3f}, {e[h]['mac']} maç)" if h in e else f"{isim.get(h, str(h))} (yeni)" for h in baglam.hakem_mac[mac.mac_id])
        s.append(f"  {ad:<12} ekibin serbest atış endeksi {ekip['sa']:.3f}, faul endeksi {ekip['faul']:.3f}: {hakemler}")
    s.append(f"Ataması olan maç: {atanan} / {len(maclar)}")
    return "\n".join(s)


if __name__ == "__main__":
    import tahmin
    import veritabani

    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    veritabani.sema_kur(baglanti)
    bag = tahmin.Baglam(baglanti, gun)
    yazilan = profili_yaz(baglanti, bag, gun)
    metin = rapor_metni(baglanti, bag, gun) + f"\n\nhakem_profili tablosuna {yazilan} satır yazıldı."
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "hakem.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
