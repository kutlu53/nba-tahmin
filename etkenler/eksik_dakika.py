"""Eksik takım arkadaşlarından gelen dakika artışı (PLAN_EK bölüm 6, 2. halka): beklenen dakikayı düzeltir.

Bugün "Out" olan her önemli takım arkadaşı için, oyuncunun o arkadaş oynamadığı
maçlardaki dakika ortalaması ile oynadığı maçlardaki ortalaması arasındaki fark
eklenir. Fark, onsuz maç sayısı azken sıfıra çekilir. Oyuncunun son maçları zaten
arkadaşsız oynandıysa, o maçlar beklenen dakikaya yansımıştır; fark o ölçüde küçültülür.

Kaba dağıtımın (etkenler/eksik_arkadas.py) yerini alır.
"""
import config
from etkenler import EtkenSonucu, beklenen_dakika, kucuk_orneklem, veri_yok
from etkenler import kullanim


def hesapla(oyuncu, mac, istatistik, baglam):
    eksik = baglam.takim_eksikleri(oyuncu.takim_id)
    if not eksik["veri_var"]:
        return veri_yok("takım için sakatlık verisi yok")
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is None:
        return veri_yok("oyuncunun maç kaydı yok")
    taban, rol_degisti = beklenen_dakika(k)
    pencere = set(k.tail(config.DAKIKA_PENCERE_ROL if rol_degisti else config.DAKIKA_PENCERE)["mac_id"])
    onemli = kullanim.onemli_oyuncular(baglam, oyuncu.takim_id)

    ek, orneklem, parcalar = 0.0, 0, []
    for kimlik, isim, _ in eksik["out"]:
        if kimlik == oyuncu.oyuncu_id or kimlik not in onemli:
            continue
        veri = kullanim.onsuz(baglam, oyuncu.oyuncu_id, oyuncu.takim_id, kimlik)
        if veri is None or min(veri["onunla_mac"], veri["onsuz_mac"]) < config.ONSUZ_MIN_MAC:
            continue
        fark = kucuk_orneklem(veri["onsuz_mac"], veri["onsuz_dakika"] - veri["onunla_dakika"], config.ONSUZ_K, notr=0.0)
        zaten = len(pencere & veri["onsuz_maclar"]) / len(pencere)      # beklenen dakika penceresinin onsuz oynanmış payı
        ek += fark * (1.0 - zaten)
        orneklem += veri["onsuz_mac"]
        parcalar.append(f"{isim} yok: {veri['onunla_dakika']:.1f} → {veri['onsuz_dakika']:.1f} dk ({veri['onsuz_mac']} maç)")
    if not parcalar:
        return EtkenSonucu(1.0, True, 0, "dakikayı değiştiren eksik önemli takım arkadaşı yok")
    return EtkenSonucu(1.0 + ek / taban, True, orneklem, "; ".join(parcalar) + f"; beklenen dakika {taban:.1f} → {taban + ek:.1f}")
