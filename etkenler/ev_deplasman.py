"""Ev sahibi / deplasman farkı.

Oyuncunun o sahadaki (ev ya da deplasman) 36 dk başına üretiminin kendi genel
üretimine oranı; maç sayısı azken ligin ev/deplasman oranına çekilir.
"""
import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok


def hesapla(oyuncu, mac, istatistik, baglam):
    ev_mi = int(mac.ev_mi(oyuncu.takim_id))
    lig_orani = baglam.lig_ev_orani.get((istatistik, ev_mi))
    if lig_orani is None:
        return veri_yok("lig ev/deplasman verisi yok")

    n, oyuncu_orani = 0, lig_orani
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is not None:
        saha = k[k["ev_mi"] == ev_mi]
        genel = k[istatistik].sum() / k["dakika"].sum()
        if len(saha) and genel > 0:
            n = len(saha)
            oyuncu_orani = (saha[istatistik].sum() / saha["dakika"].sum()) / genel
    carpan = kucuk_orneklem(n, oyuncu_orani, config.EV_DEPLASMAN_K, notr=lig_orani)
    return EtkenSonucu(
        carpan, True, n,
        f"{'ev' if ev_mi else 'deplasman'}: oyuncunun oranı {oyuncu_orani:.2f} ({n} maç), lig {lig_orani:.3f}",
    )
