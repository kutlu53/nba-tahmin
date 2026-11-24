"""Yolculuk ve dinlenme (PLAN_EK etken 7). "Arka arkaya maç" etkeninin yerini alır.

Maçın koşulları fikstürden ve salonlar tablosundan gelir (yolculuk tablosu):
arka arkaya ikinci maç, 4 günde 3. maç, uzun yolculuk, saat dilimi değişimi,
yüksek rakım deplasmanı, uzun deplasman serisi.

Her koşulun etkisi kendi verimizden öğrenilir: o koşuldaki maçlarda oyuncuların
gerçekleşen üretimi / kendi sezon üretimlerinden beklenen, koşul dışındaki maçlara
oranla. Böylece "yıldızlar arka arkaya maçlarda dinlendirilir" türü kadro farkları
orana karışmaz. Etkiler az örneklemde güçlü biçimde 1,00'e çekilir.

Kanıt karışık olduğu için çarpan sınırı dardır (config: 0,97 – 1,02). Dakika ve
dinlendirme etkisi burada değildir.
"""
import numpy as np

import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok

ISTATISTIKLER = list(config.ISTATISTIKLER)

# koşul adı: (açıklama, yolculuk satırından doğru/yanlış üreten işlev)
KOSULLAR = {
    "arka_arkaya": ("arka arkaya ikinci maç", lambda y: y["dinlenme_gunu"] == 0),
    "uc_dortte": ("4 günde 3. maç", lambda y: bool(y["uc_dortte"])),
    "uzun_yol": ("uzun yolculuk", lambda y: y["km"] >= config.YORGUNLUK_UZUN_KM),
    "saat_dilimi": ("saat dilimi değişimi", lambda y: abs(y["saat_dilimi_farki"]) >= config.YORGUNLUK_SAAT_FARKI),
    "yuksek_rakim": ("yüksek rakım deplasmanı", lambda y: not y["ev_mi"] and y["rakim_m"] >= config.YORGUNLUK_RAKIM_M),
    "deplasman_serisi": ("uzun deplasman serisi", lambda y: y["deplasman_sirasi"] >= config.YORGUNLUK_DEPLASMAN_SIRASI),
}


def mac_kosullari(baglam, takim_id, mac_id):
    """Takımın o maçta içinde olduğu koşulların adları; yolculuk verisi yoksa None."""
    y = baglam.yolculuk.get((takim_id, mac_id))
    return None if y is None else [ad for ad, (_, kural) in KOSULLAR.items() if kural(y)]


def kosul_etkileri(baglam):
    """Her koşul ve istatistik için öğrenilmiş oran: {koşul: {istatistik: (düzeltilmiş oran, oyuncu-maç sayısı, ham oran)}}"""
    if "yorgunluk" not in baglam.onbellek:
        k = baglam.kayitlar
        sonuc = {ad: {} for ad in KOSULLAR}
        if len(k):
            kosullar = [mac_kosullari(baglam, t, m) for t, m in zip(k["takim_id"], k["mac_id"])]
            toplam = k.groupby("oyuncu_id")[ISTATISTIKLER + ["dakika"]].transform("sum")
            kalan = toplam["dakika"] - k["dakika"]
            gecerli = (kalan > 0).to_numpy() & np.array([x is not None for x in kosullar])
            for ad in KOSULLAR:
                icinde = gecerli & np.array([x is not None and ad in x for x in kosullar])
                disinda = gecerli & ~icinde
                n = int(icinde.sum())
                for ist in ISTATISTIKLER:
                    beklenen = k["dakika"] * (toplam[ist] - k[ist]) / kalan.where(kalan > 0)
                    if n and beklenen[icinde].sum() > 0 and beklenen[disinda].sum() > 0 and k.loc[disinda, ist].sum() > 0:
                        ham = (k.loc[icinde, ist].sum() / beklenen[icinde].sum()) / (k.loc[disinda, ist].sum() / beklenen[disinda].sum())
                        sonuc[ad][ist] = (kucuk_orneklem(n, ham, config.YORGUNLUK_K), n, ham)
        baglam.onbellek["yorgunluk"] = sonuc
    return baglam.onbellek["yorgunluk"]


def hesapla(oyuncu, mac, istatistik, baglam):
    kosullar = mac_kosullari(baglam, oyuncu.takim_id, mac.mac_id)
    if kosullar is None:
        return veri_yok("maç için yolculuk verisi yok")
    if not kosullar:
        return EtkenSonucu(1.0, True, 0, "yorgunluk koşulu yok")
    etkiler = kosul_etkileri(baglam)
    carpan, orneklem, parcalar = 1.0, None, []
    for ad in kosullar:
        etki = etkiler[ad].get(istatistik)
        if etki is None:
            parcalar.append(f"{KOSULLAR[ad][0]} (veri yok)")
            continue
        carpan *= etki[0]
        orneklem = etki[1] if orneklem is None else min(orneklem, etki[1])
        parcalar.append(f"{KOSULLAR[ad][0]} ×{etki[0]:.3f} (ham {etki[2]:.3f}, {etki[1]} oyuncu-maç)")
    return EtkenSonucu(carpan, True, orneklem or 0, "; ".join(parcalar))
