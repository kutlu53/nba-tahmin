"""Şut şansı ve ortalamaya dönüş (PLAN_EK etken 5).

Sayı doğrudan tahmin edilmez, ayrıştırılır:

    sayı = 2 × (2'lik deneme × 2'lik %) + 3 × (3'lük deneme × 3'lük %) + (serbest atış denemesi × SA %)

Denemeler hacimdir; sezon / son 10 / son 5 maç ağırlıklı ortalamasıyla tahmin edilir.
Yüzdeler şansa açıktır; oyuncunun ön yüzdesine doğru çekilir:

    düzeltilmiş % = (isabet + k × ön yüzde) / (deneme + k)

Ön yüzde, oyuncunun geçen sezonki yüzdesidir; geçen sezon denemesi azsa (ya da yoksa)
pozisyonunun bu sezonki lig ortalamasına çekilir. Son maçlara ağırlık yalnızca
denemelere uygulanır, yüzdelere değil.

Etken yalnızca sayı ve üçlük isabetini etkiler; çarpan = ayrıştırılmış 36 dk başına
üretim / temel orandır.

Rapor:  .venv\\Scripts\\python.exe -m etkenler.sut_duzeltme [YYYY-AA-GG]
"""
import sys

import config
from etkenler import EtkenSonucu, agirlikli_oran_36, veri_yok

# tür: (isabet sütunu, deneme sütunu, sayı değeri, Türkçe ad)
TURLER = {
    "iki": ("iki_isabet", "iki_deneme", 2, "2'lik"),
    "ucluk": ("ucluk", "ucluk_deneme", 3, "3'lük"),
    "serbest": ("serbest_isabet", "serbest_deneme", 1, "serbest atış"),
}


def pozisyon_yuzdeleri(baglam):
    """Bu sezonun (o güne kadarki) lig yüzdeleri: {(pozisyon, tür): yüzde}; pozisyon None = tüm lig."""
    if "sut_lig" not in baglam.onbellek:
        k = baglam.kayitlar
        sonuc = {}
        if len(k):
            pozisyon = k["oyuncu_id"].map(lambda kimlik: (baglam.oyuncular.get(kimlik) or {}).get("pozisyon"))
            for tur, (isabet, deneme, _, _) in TURLER.items():
                if k[deneme].sum() > 0:
                    sonuc[(None, tur)] = k[isabet].sum() / k[deneme].sum()
                toplam = k.groupby(pozisyon)[[isabet, deneme]].sum()
                for p, s in toplam.iterrows():
                    if s[deneme] > 0:
                        sonuc[(p, tur)] = s[isabet] / s[deneme]
        baglam.onbellek["sut_lig"] = sonuc
    return baglam.onbellek["sut_lig"]


def yuzdeler(baglam, oyuncu):
    """Oyuncunun her şut türü için güncel, ön ve düzeltilmiş yüzdesi; kaydı ya da lig verisi yoksa None.

    Döndürür: {tür: {'isabet', 'deneme', 'guncel', 'on', 'gecen_deneme', 'duzeltilmis'}}
    """
    anahtar = ("sut", oyuncu.oyuncu_id)
    if anahtar not in baglam.onbellek:
        k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
        lig = pozisyon_yuzdeleri(baglam)
        gecen = baglam.onceki_sezon.get(oyuncu.oyuncu_id)
        sonuc = {}
        for tur, (isabet_s, deneme_s, _, _) in TURLER.items():
            lig_yuzdesi = lig.get((oyuncu.pozisyon, tur), lig.get((None, tur)))
            if k is None or lig_yuzdesi is None:
                sonuc = None
                break
            g_isabet, g_deneme = (gecen[isabet_s], gecen[deneme_s]) if gecen else (0, 0)
            on = (g_isabet + config.ON_YUZDE_K[tur] * lig_yuzdesi) / (g_deneme + config.ON_YUZDE_K[tur])
            isabet, deneme = float(k[isabet_s].sum()), float(k[deneme_s].sum())
            sonuc[tur] = {
                "isabet": isabet, "deneme": deneme,
                "guncel": isabet / deneme if deneme else None,
                "on": on, "gecen_deneme": g_deneme,
                "duzeltilmis": (isabet + config.SUT_K[tur] * on) / (deneme + config.SUT_K[tur]),
            }
        baglam.onbellek[anahtar] = sonuc
    return baglam.onbellek[anahtar]


def ayristir(baglam, oyuncu):
    """36 dakika başına ayrıştırılmış üretim; veri yoksa None.

    Döndürür: {'deneme': {tür: 36 dk başına deneme}, 'isabet': {tür: 36 dk başına beklenen isabet}, 'sayi': 36 dk başına sayı}
    """
    y = yuzdeler(baglam, oyuncu)
    if y is None:
        return None
    k = baglam.oyuncu_kayitlari[oyuncu.oyuncu_id]
    deneme = {tur: agirlikli_oran_36(k, TURLER[tur][1])[0] for tur in TURLER}
    isabet = {tur: deneme[tur] * y[tur]["duzeltilmis"] for tur in TURLER}
    return {"deneme": deneme, "isabet": isabet, "sayi": sum(TURLER[tur][2] * isabet[tur] for tur in TURLER)}


def hesapla(oyuncu, mac, istatistik, baglam):
    if istatistik not in ("sayi", "ucluk"):
        return EtkenSonucu(1.0, True, 0, "bu istatistiği etkilemez")
    a = ayristir(baglam, oyuncu)
    if a is None:
        return veri_yok("oyuncunun şut kaydı ya da lig yüzdesi yok")
    temel, _ = agirlikli_oran_36(baglam.oyuncu_kayitlari[oyuncu.oyuncu_id], istatistik)
    if temel <= 0:
        return veri_yok("temel üretim sıfır; çarpanla düzeltilemez")
    y = yuzdeler(baglam, oyuncu)
    if istatistik == "ucluk":
        yeni, turler, orneklem = a["isabet"]["ucluk"], ("ucluk",), y["ucluk"]["deneme"]
    else:
        yeni, turler, orneklem = a["sayi"], tuple(TURLER), sum(y[t]["deneme"] for t in TURLER)
    ozet = "; ".join(
        f"{TURLER[t][3]} %{100 * y[t]['guncel']:.1f} → %{100 * y[t]['duzeltilmis']:.1f} ({y[t]['deneme']:.0f} deneme, ön %{100 * y[t]['on']:.1f})"
        for t in turler if y[t]["guncel"] is not None)
    return EtkenSonucu(yeni / temel, True, round(orneklem), ozet or "bu sezon denemesi yok")


def rapor_metni(conn, tarih):
    """Günün tahmin edilen oyuncuları için: yüzdelerin aralığı, en çok düzeltilenler ve sayı = bileşenler denetimi."""
    import tahmin
    import pandas as pd

    baglam = tahmin.Baglam(conn, tarih)
    satirlar = []
    for mac in tahmin.gunun_maclari(conn, tarih):
        for o in tahmin.tahmin_edilecekler(baglam, mac):
            k = baglam.oyuncu_kayitlari.get(o.oyuncu_id)
            a, y = ayristir(baglam, o), yuzdeler(baglam, o)
            if k is None or len(k) < config.TAHMIN_MIN_MAC or a is None:
                continue
            dakika, _ = tahmin.beklenen_dakika(k)
            if dakika < config.TAHMIN_MIN_DAKIKA:
                continue
            temel = {i: dakika * agirlikli_oran_36(k, i)[0] / 36 for i in ("sayi", "ucluk")}
            carpan = {i: hesapla(o, mac, i, baglam) for i in ("sayi", "ucluk")}
            satir = {"isim": o.isim, "dakika": dakika, "temel_sayi": temel["sayi"], "temel_ucluk": temel["ucluk"],
                     "sayi": temel["sayi"] * carpan["sayi"].carpan, "ucluk_tahmin": temel["ucluk"] * carpan["ucluk"].carpan,
                     "sayi_veri": carpan["sayi"].veri_var, "ucluk_veri": carpan["ucluk"].veri_var}
            for tur in TURLER:
                satir[f"{tur}_isabet"] = dakika * a["isabet"][tur] / 36
                satir.update({f"{tur}_{ad}": y[tur][ad] for ad in ("guncel", "on", "duzeltilmis", "deneme", "gecen_deneme")})
            satir["bilesen_toplami"] = sum(TURLER[tur][2] * satir[f"{tur}_isabet"] for tur in TURLER)
            satirlar.append(satir)
    if not satirlar:
        return f"{tarih}: tahmin edilecek oyuncu yok."
    d = pd.DataFrame(satirlar)
    s = [f"=== Şut düzeltmesi raporu ({tarih}; {len(d)} oyuncu) ==="]

    s.append("\nSAYI = BİLEŞENLERİN TOPLAMI (2 × 2'lik isabet + 3 × 3'lük isabet + serbest atış isabeti)")
    v = d[d["sayi_veri"]]
    s.append(f"  {len(v)} oyuncuda en büyük |sayı tahmini − bileşen toplamı| = {(v['sayi'] - v['bilesen_toplami']).abs().max():.2e}")
    u = d[d["ucluk_veri"]]
    s.append(f"  {len(u)} oyuncuda en büyük |üçlük tahmini − 3'lük bileşeni| = {(u['ucluk_tahmin'] - u['ucluk_isabet']).abs().max():.2e}")
    s.append(f"  Çarpanla düzeltilemeyen (temel üretimi sıfır): sayı {int((~d['sayi_veri']).sum())}, üçlük {int((~d['ucluk_veri']).sum())} oyuncu")
    s.append(f"  Düzeltmenin toplam etkisi: sayı {v['temel_sayi'].sum():.0f} → {v['sayi'].sum():.0f}, üçlük {u['temel_ucluk'].sum():.1f} → {u['ucluk_tahmin'].sum():.1f}")

    s.append("\nYÜZDELERİN ARALIĞI (bu sezon en az 20 denemesi olanlar)")
    s.append(f"  {'tür':<14}{'oyuncu':>7}{'güncel: en az–en çok':>24}{'düzeltilmiş: en az–en çok':>28}{'ön yüzde ort.':>15}")
    for tur, (_, _, _, ad) in TURLER.items():
        y = d[d[f"{tur}_deneme"] >= 20]
        s.append(f"  {ad:<14}{len(y):>7}{f'%{100 * y[f'{tur}_guncel'].min():.1f} – %{100 * y[f'{tur}_guncel'].max():.1f}':>24}"
                 f"{f'%{100 * y[f'{tur}_duzeltilmis'].min():.1f} – %{100 * y[f'{tur}_duzeltilmis'].max():.1f}':>28}{f'%{100 * y[f'{tur}_on'].mean():.1f}':>15}")

    y = d[d["ucluk_deneme"] >= 20].assign(fark=lambda x: x["ucluk_guncel"] - x["ucluk_duzeltilmis"])
    for baslik, parca in (("3'LÜKTE EN ÇOK AŞAĞI ÇEKİLENLER (sıcak seri)", y.nlargest(5, "fark")), ("3'LÜKTE EN ÇOK YUKARI ÇEKİLENLER (soğuk seri)", y.nsmallest(5, "fark"))):
        s.append(f"\n{baslik}")
        s.append(f"  {'oyuncu':<24}{'bu sezon':>16}{'güncel':>9}{'ön':>8}{'geçen sezon deneme':>20}{'düzeltilmiş':>13}{'3lük tahmini':>20}")
        for _, r in parca.iterrows():
            s.append(f"  {r['isim'][:24]:<24}{f'{r.ucluk_guncel * r.ucluk_deneme:.0f}/{r.ucluk_deneme:.0f}':>16}{f'%{100 * r.ucluk_guncel:.1f}':>9}"
                     f"{f'%{100 * r.ucluk_on:.1f}':>8}{r.ucluk_gecen_deneme:>20.0f}{f'%{100 * r.ucluk_duzeltilmis:.1f}':>13}"
                     f"{f'{r.temel_ucluk:.2f} → {r.ucluk_tahmin:.2f}':>20}")
    return "\n".join(s)


if __name__ == "__main__":
    import veritabani

    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    metin = rapor_metni(baglanti, gun)
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "sut_duzeltme.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
