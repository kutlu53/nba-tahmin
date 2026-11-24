"""Eksik takım arkadaşlarının boşalttığı dakika (kaba dağıtım).

Bugün "Out" olan takım arkadaşlarının, takımın son maçlarında aldığı dakika
kalan oyunculara orantılı dağıtılır: çarpan = 240 / (240 − boşalan dakika).
Boşalan dakika, beklenen dakikanın hesaplandığı pencerede (takımın son 5 maçı)
ölçülür: o maçlarda zaten oynamamış oyuncunun yokluğu kalanların dakikasına
yansımıştır, yeniden eklenmez.

Kullanım payının dağıtımı bu kaba sürümde yoktur.
"""
from etkenler import EtkenSonucu, veri_yok

TAKIM_DAKIKASI = 240.0


def hesapla(oyuncu, mac, istatistik, baglam):
    eksik = baglam.takim_eksikleri(oyuncu.takim_id)
    if not eksik["veri_var"]:
        return veri_yok("takım için sakatlık verisi yok")
    disarida = [(isim, dk) for kimlik, isim, dk in eksik["out"] if kimlik != oyuncu.oyuncu_id]
    bosalan = sum(dk for _, dk in disarida)
    if bosalan <= 0:
        return EtkenSonucu(1.0, True, eksik["mac"], "boşalan dakika yok")
    isimler = ", ".join(isim for isim, dk in disarida if dk > 0)
    return EtkenSonucu(
        TAKIM_DAKIKASI / (TAKIM_DAKIKASI - bosalan), True, eksik["mac"],
        f"eksik: {isimler}; boşalan {bosalan:.1f} dk/maç",
    )
