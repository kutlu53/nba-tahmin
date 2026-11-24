"""Farklı maç riski (PLAN_EK etken 4): beklenen dakikayı düzeltir.

- Maçın beklenen farkı bahis handikapından gelir; yoksa iki takımın 100 pozisyon başına
  sayı farkından ve iç saha avantajından kendi tahminimiz kullanılır.
- Farklı maç olasılığı: son farkın mutlak değeri ≥ 20 olma olasılığı; fark normal dağılımlı
  kabul edilir (ortalama = beklenen fark, standart sapma kendi verimizden).
- Dakika etkisi kendi verimizden öğrenilir: farklı biten maçlarda ilk beş oyuncuları
  alışık olduklarından yüzde kaç az, yedekler yüzde kaç fazla oynamış.
- Oyuncunun dakika ortalaması ligdeki olağan farklı maç oranını zaten içerir; çarpan bu
  yüzden olağan orana göre hesaplanır: (1 + p × etki) / (1 + p0 × etki).

Rapor:  .venv\\Scripts\\python.exe -m etkenler.fark_riski [YYYY-AA-GG]
"""
import math
import sys

import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok


def buyuk_fark_olasiligi(beklenen_fark, sigma, esik=None):
    """Son farkın mutlak değerinin eşiği aşma olasılığı (normal dağılım)."""
    esik = config.BUYUK_FARK_ESIGI if esik is None else esik
    phi = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    return (1.0 - phi((esik - beklenen_fark) / sigma)) + phi((-esik - beklenen_fark) / sigma)


def lig_ozeti(baglam):
    """O güne kadarki maçlardan: fark dağılımının standart sapması, iç saha avantajı, farklı maç oranı.

    Her biri az maçta başlangıç değerine çekilir. Döndürür: {'sigma', 'sigma_mac', 'ic_saha', 'p0', 'mac', 'buyuk_fark'}
    """
    if "fark_lig" not in baglam.onbellek:
        farklar = list(baglam.mac_farki.values())
        n = len(farklar)
        sapmalar = [fark + baglam.oranlar[m]["handikap"] for m, fark in baglam.mac_farki.items()
                    if m in baglam.oranlar and baglam.oranlar[m]["handikap"] is not None]       # gerçek fark − beklenen fark (−handikap)
        varyans = sum(s * s for s in sapmalar) / len(sapmalar) if sapmalar else 0.0
        k = config.FARK_K_MAC
        buyuk = sum(abs(f) >= config.BUYUK_FARK_ESIGI for f in farklar)
        baglam.onbellek["fark_lig"] = {
            "sigma": math.sqrt(kucuk_orneklem(len(sapmalar), varyans, k, notr=config.FARK_SIGMA_BASLANGIC ** 2)),
            "sigma_mac": len(sapmalar),
            "ic_saha": kucuk_orneklem(n, sum(farklar) / n if n else 0.0, k, notr=config.IC_SAHA_BASLANGIC),
            "p0": kucuk_orneklem(n, buyuk / n if n else 0.0, k, notr=config.BUYUK_FARK_ORANI_BASLANGIC),
            "mac": n, "buyuk_fark": buyuk,
        }
    return baglam.onbellek["fark_lig"]


def net_guc(baglam, takim_id):
    """Takımın 100 pozisyon başına sayı farkı, az maçta sıfıra çekilmiş; maçı yoksa None."""
    skorlar = [s for s in baglam.takim_skorlari.get(takim_id, []) if s[2]]
    if not skorlar:
        return None
    net = 100.0 * sum(a - y for a, y, _ in skorlar) / sum(p for _, _, p in skorlar)
    return kucuk_orneklem(len(skorlar), net, config.NET_K, notr=0.0)


def kendi_fark_tahmini(baglam, mac):
    """Ev sahibinin beklenen farkı: (ev net gücü − deplasman net gücü) × maç başına pozisyon / 100 + iç saha avantajı."""
    ev, dep = net_guc(baglam, mac.ev_takim_id), net_guc(baglam, mac.dep_takim_id)
    if ev is None or dep is None:
        return None
    pozisyonlar = [p for skorlar in baglam.takim_skorlari.values() for _, _, p in skorlar if p]
    return (ev - dep) * (sum(pozisyonlar) / len(pozisyonlar)) / 100.0 + lig_ozeti(baglam)["ic_saha"]


def beklenen_fark(baglam, mac):
    """Ev sahibinin beklenen farkı ve kaynağı ('oran' ya da 'kendi tahminimiz'); hiçbiri yoksa (None, None)."""
    oran = baglam.oranlar.get(mac.mac_id)
    if oran and oran["handikap"] is not None:
        return -oran["handikap"], "oran"
    kendi = kendi_fark_tahmini(baglam, mac)
    return (kendi, "kendi tahminimiz") if kendi is not None else (None, None)


def dakika_etkisi(baglam):
    """Farklı biten maçlarda dakikanın, oyuncunun alışık olduğu dakikaya oranı; olağan maçlara göre.

    Alışık olunan dakika: oyuncunun aynı roldeki (ilk beş / yedek) DİĞER maçlarının ortalaması (en az 3 maç).
    Döndürür: {1: (ilk beş etkisi, oyuncu-maç sayısı), 0: (yedek etkisi, oyuncu-maç sayısı)}; etki −0,08 = %8 az.
    Az örneklemde etki sıfıra çekilir.
    """
    if "fark_dakika" not in baglam.onbellek:
        k = baglam.kayitlar[["oyuncu_id", "mac_id", "ilk_bes", "dakika"]].dropna(subset=["ilk_bes"])
        sonuc = {1: (0.0, 0), 0: (0.0, 0)}
        if len(k):
            grup = k.groupby(["oyuncu_id", "ilk_bes"])["dakika"]
            adet, toplam = grup.transform("count"), grup.transform("sum")
            k = k.assign(alisik=(toplam - k["dakika"]) / (adet - 1), fark=k["mac_id"].map(baglam.mac_farki).abs())
            k = k[(adet >= 4) & k["fark"].notna()]
            buyuk = k["fark"] >= config.BUYUK_FARK_ESIGI
            for rol in (1, 0):
                a, b = k[buyuk & (k["ilk_bes"] == rol)], k[~buyuk & (k["ilk_bes"] == rol)]
                if len(a) and len(b) and a["alisik"].sum() > 0 and b["alisik"].sum() > 0:
                    ham = (a["dakika"].sum() / a["alisik"].sum()) / (b["dakika"].sum() / b["alisik"].sum()) - 1.0
                    sonuc[rol] = (kucuk_orneklem(len(a), ham, config.FARK_DAKIKA_K, notr=0.0), len(a))
        baglam.onbellek["fark_dakika"] = sonuc
    return baglam.onbellek["fark_dakika"]


def hesapla(oyuncu, mac, istatistik, baglam):
    fark, kaynak = beklenen_fark(baglam, mac)
    if fark is None:
        return veri_yok("handikap yok ve kendi fark tahminimiz üretilemedi")
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is None:
        return veri_yok("oyuncunun maç kaydı yok")
    lig = lig_ozeti(baglam)
    p = buyuk_fark_olasiligi(fark, lig["sigma"])
    rol = int(k.tail(config.DAKIKA_PENCERE)["ilk_bes"].mean() >= 0.5)
    etki, n = dakika_etkisi(baglam)[rol]
    return EtkenSonucu(
        (1.0 + p * etki) / (1.0 + lig["p0"] * etki), True, n,
        f"beklenen fark {fark:+.1f} ({kaynak}); farklı maç olasılığı %{100 * p:.0f} (lig %{100 * lig['p0']:.0f}); "
        f"{'ilk beş' if rol else 'yedek'} dakika etkisi %{100 * etki:+.1f}",
    )


def rapor_metni(conn, baglam, tarih):
    import tahmin

    takim = {s["takim_id"]: s["kisaltma"] for s in conn.execute("SELECT takim_id, kisaltma FROM takimlar")}
    lig, etki = lig_ozeti(baglam), dakika_etkisi(baglam)
    s = [f"=== Fark riski raporu ({tarih} öncesi maçlar) ==="]
    s.append(f"Oynanan maç: {lig['mac']}; son farkı {config.BUYUK_FARK_ESIGI} ve üstü olan: {lig['buyuk_fark']} "
             f"(%{100 * lig['buyuk_fark'] / max(lig['mac'], 1):.1f}; düzeltilmiş olağan oran %{100 * lig['p0']:.1f})")
    s.append(f"İç saha avantajı: {lig['ic_saha']:+.2f} sayı. Fark dağılımının standart sapması (gerçek fark − handikap): {lig['sigma']:.1f} ({lig['sigma_mac']} oranlı maç)")

    s.append("\nFARKLI MAÇLARDA DAKİKA (kendi verimizden): oyuncunun aynı roldeki diğer maçlarının ortalamasına göre")
    k = baglam.kayitlar[["oyuncu_id", "mac_id", "ilk_bes", "dakika"]].dropna(subset=["ilk_bes"])
    grup = k.groupby(["oyuncu_id", "ilk_bes"])["dakika"]
    adet, toplam = grup.transform("count"), grup.transform("sum")
    k = k.assign(alisik=(toplam - k["dakika"]) / (adet - 1), fark=k["mac_id"].map(baglam.mac_farki).abs())[adet >= 4]
    s.append(f"  {'rol':<10}{'maç türü':<22}{'oyuncu-maç':>11}{'oynanan dk':>12}{'alışık dk':>11}{'oran':>8}")
    for rol, ad in ((1, "ilk beş"), (0, "yedek")):
        for baslik, parca in ((f"fark ≥ {config.BUYUK_FARK_ESIGI}", k[(k["ilk_bes"] == rol) & (k["fark"] >= config.BUYUK_FARK_ESIGI)]),
                              (f"fark < {config.BUYUK_FARK_ESIGI}", k[(k["ilk_bes"] == rol) & (k["fark"] < config.BUYUK_FARK_ESIGI)])):
            s.append(f"  {ad:<10}{baslik:<22}{len(parca):>11}{parca['dakika'].mean():>12.1f}{parca['alisik'].mean():>11.1f}"
                     f"{parca['dakika'].sum() / parca['alisik'].sum():>8.3f}")
    s.append(f"  İlk beş dakika kaybı: %{-100 * etki[1][0]:.1f} ({etki[1][1]} oyuncu-maç); yedek dakika artışı: %{100 * etki[0][0]:+.1f} ({etki[0][1]} oyuncu-maç)")
    s.append(f"  (az örneklem için sıfıra çekilmiş değerler; k = {config.FARK_DAKIKA_K} oyuncu-maç)")

    # Fark tahminlerinin isabeti: handikap ve kendi tahminimiz, o güne kadarki bilgiyle.
    s.append("\nGÜNÜN MAÇLARI")
    s.append(f"  {'maç':<12}{'handikap':>10}{'toplam':>8}{'beklenen fark':>15}{'kaynak':>18}{'farklı maç olasılığı':>22}{'ilk beş çarpanı':>17}{'yedek çarpanı':>15}")
    for mac in tahmin.gunun_maclari(conn, tarih):
        oran = baglam.oranlar.get(mac.mac_id) or {}
        fark, kaynak = beklenen_fark(baglam, mac)
        if fark is None:
            s.append(f"  {takim[mac.dep_takim_id]} @ {takim[mac.ev_takim_id]:<6} veri yok")
            continue
        p = buyuk_fark_olasiligi(fark, lig["sigma"])
        carpan = {rol: (1 + p * etki[rol][0]) / (1 + lig["p0"] * etki[rol][0]) for rol in (1, 0)}
        s.append(f"  {takim[mac.dep_takim_id] + ' @ ' + takim[mac.ev_takim_id]:<12}{oran.get('handikap') if oran.get('handikap') is not None else '-':>10}"
                 f"{oran.get('toplam') if oran.get('toplam') is not None else '-':>8}{fark:>+15.1f}{kaynak:>18}{f'%{100 * p:.0f}':>22}{carpan[1]:>17.3f}{carpan[0]:>15.3f}")
    return "\n".join(s)


if __name__ == "__main__":
    import tahmin
    import veritabani

    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    metin = rapor_metni(baglanti, tahmin.Baglam(baglanti, gun), gun)
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "fark_riski.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
