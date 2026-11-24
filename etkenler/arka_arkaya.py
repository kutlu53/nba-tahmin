"""Arka arkaya ikinci maç.

Takım bir gün önce de oynadıysa, ligde arka arkaya ikinci maçlardaki 36 dk başına
üretimin genel üretime oranı uygulanır (kendi verimizden, 1,00'e çekilerek).
Dakika üzerindeki etki burada değildir.
"""
from datetime import date, timedelta

import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok


def hesapla(oyuncu, mac, istatistik, baglam):
    dun = (date.fromisoformat(mac.tarih) - timedelta(days=1)).isoformat()
    if dun not in baglam.takim_tarihleri.get(oyuncu.takim_id, ()):
        return EtkenSonucu(1.0, True, 0, "arka arkaya maç değil")
    lig = baglam.lig_arka_arkaya.get(istatistik)
    if lig is None:
        return veri_yok("ligde arka arkaya maç verisi yok")
    oran, takim_mac = lig
    return EtkenSonucu(
        kucuk_orneklem(takim_mac, oran, config.ARKA_ARKAYA_K), True, takim_mac,
        f"arka arkaya ikinci maç: lig oranı {oran:.3f} ({takim_mac} takım-maç)",
    )
