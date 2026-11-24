"""Bu geceki ilk beş (nba.com günlük ilk beş beslemesi): beklenen dakikayı düzeltir.

Oyuncunun bu geceki rolü olağan rolünden (son 5 maçının çoğunluğu) farklıysa dakikası değişir:
yedekken ilk beşte başlayan oyuncu daha çok, ilk beşten yedeğe düşen daha az oynar. Değişimin
büyüklüğü kendi verimizden öğrenilir: geçmişte rolü değişen oyuncuların o maçtaki dakikası /
o maç için beklenen dakikası. Az örneklemde 1,00'e çekilir.

Besleme maçtan saatler önce "beklenen" (Expected) ilk beşi, maça yakın "kesin" (Confirmed) ilk beşi
verir. Maç için ilk beş bilgisi yoksa veri_var = False.
"""
import numpy as np

import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok


def rol_etkileri(baglam):
    """{1: (çarpan, oyuncu-maç, ham oran), 0: (...)}; 1 = yedekken ilk beşte başlayanlar, 0 = ilk beşten yedeğe düşenler."""
    if "ilk_bes" not in baglam.onbellek:
        a = config.DAKIKA_SEZON_AGIRLIK
        toplam = {1: [0.0, 0.0, 0], 0: [0.0, 0.0, 0]}        # [gerçekleşen dakika, beklenen dakika, oyuncu-maç]
        for k in baglam.oyuncu_kayitlari.values():
            dakika, rol = k["dakika"].to_numpy(float), k["ilk_bes"].to_numpy(float)
            for j in range(config.DAKIKA_PENCERE, len(dakika)):
                onceki = rol[j - config.DAKIKA_PENCERE:j]
                if np.isnan(rol[j]) or np.isnan(onceki).any() or bool(rol[j]) == (onceki.mean() >= 0.5):
                    continue
                x = toplam[int(rol[j])]
                x[0] += dakika[j]
                x[1] += (1 - a) * dakika[j - config.DAKIKA_PENCERE:j].mean() + a * dakika[:j].mean()
                x[2] += 1
        baglam.onbellek["ilk_bes"] = {
            r: ((kucuk_orneklem(n, g / b, config.ILK_BES_K), n, g / b) if n and b > 0 else (1.0, 0, 1.0)) for r, (g, b, n) in toplam.items()}
    return baglam.onbellek["ilk_bes"]


def hesapla(oyuncu, mac, istatistik, baglam):
    kayit = baglam.bu_gece.get((mac.mac_id, oyuncu.takim_id))
    if not kayit or len(kayit["ilk_bes"]) != 5:
        return veri_yok("bu maç için ilk beş bilgisi yok")
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is None:
        return veri_yok("oyuncunun maç kaydı yok")
    olagan = bool(k.tail(config.DAKIKA_PENCERE)["ilk_bes"].mean() >= 0.5)
    bu_gece = oyuncu.oyuncu_id in kayit["ilk_bes"]
    tur = "kesin" if kayit["kesin"] else "beklenen"
    if bu_gece == olagan:
        return EtkenSonucu(1.0, True, 0, f"rolü değişmiyor: {'ilk beş' if bu_gece else 'yedek'} ({tur} ilk beş)")
    carpan, n, ham = rol_etkileri(baglam)[int(bu_gece)]
    return EtkenSonucu(carpan, True, n, f"{'yedekken ilk beşte başlıyor' if bu_gece else 'ilk beşten yedeğe düşüyor'} ({tur} ilk beş): "
                                        f"geçmişte dakika ×{ham:.2f} ({n} oyuncu-maç)")
