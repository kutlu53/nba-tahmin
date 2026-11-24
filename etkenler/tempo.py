"""Tempo (PLAN_EK etken 2).

Maçın beklenen temposu = takım temposu × rakip temposu / lig temposu.
Çarpan = beklenen tempo / takımın sezon temposu: oyuncunun üretimi takımının
bugüne kadarki maç temposunda birikti; bu maç daha hızlı ya da yavaş bekleniyorsa
üretim de o oranda ölçeklenir.

Takım temposu, sezon ve son 10 maç ortalamasının karışımıdır; maç sayısı azken
lig ortalamasına çekilir.

Sayı ve üçlükte, bahis çizgisinden çıkan takım sayı beklentisi de kullanılır:
takımın beklenen sayısı = (toplam ∓ handikap) / 2. Bu, tempoyla kısmen aynı bilgiyi
taşıdığı için çarpılmaz; tempo çarpanıyla yarı yarıya harmanlanır (PLAN_EK bölüm 7).
"""
import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok

CIZGI_ISTATISTIKLERI = ("sayi", "ucluk")


def takim_temposu(baglam, takim_id):
    """(harmanlanmış ve düzeltilmiş tempo, sezon ortalaması, maç sayısı); takımın maçı yoksa None."""
    anahtar = ("tempo", takim_id)
    if anahtar not in baglam.onbellek:
        tempolar = baglam.takim_tempolari.get(takim_id)
        if not tempolar:
            baglam.onbellek[anahtar] = None
        else:
            sezon = sum(tempolar) / len(tempolar)
            son = tempolar[-10:]
            a = config.TEMPO_SON10_AGIRLIK
            harman = (1 - a) * sezon + a * sum(son) / len(son)
            baglam.onbellek[anahtar] = (kucuk_orneklem(len(tempolar), harman, config.TEMPO_K, notr=baglam.lig_tempo), sezon, len(tempolar))
    return baglam.onbellek[anahtar]


def beklenen_tempo(baglam, takim_id, rakip_id):
    """Maçın beklenen temposu; iki takımdan birinin verisi yoksa None."""
    takim, rakip = takim_temposu(baglam, takim_id), takim_temposu(baglam, rakip_id)
    if takim is None or rakip is None:
        return None
    return takim[0] * rakip[0] / baglam.lig_tempo


def cizgi_carpani(baglam, takim_id, mac):
    """Bahis çizgisinden takımın beklenen sayısı / takımın sezon sayı ortalaması; veri yoksa None.

    Döndürür: (çarpan, beklenen sayı, sezon ortalaması).
    """
    oran = baglam.oranlar.get(mac.mac_id)
    skorlar = baglam.takim_skorlari.get(takim_id)
    if not oran or oran["handikap"] is None or oran["toplam"] is None or not skorlar:
        return None
    # handikap ev sahibinin çizgisidir: −5 ise ev sahibi 5 sayı farkla favori.
    beklenen = (oran["toplam"] - oran["handikap"]) / 2 if mac.ev_mi(takim_id) else (oran["toplam"] + oran["handikap"]) / 2
    tum = [a for liste in baglam.takim_skorlari.values() for a, _, _ in liste]
    ortalama = kucuk_orneklem(len(skorlar), sum(a for a, _, _ in skorlar) / len(skorlar), config.TEMPO_K, notr=sum(tum) / len(tum))
    return beklenen / ortalama, beklenen, ortalama


def hesapla(oyuncu, mac, istatistik, baglam):
    rakip_id = mac.rakip(oyuncu.takim_id)
    beklenen = beklenen_tempo(baglam, oyuncu.takim_id, rakip_id)
    if beklenen is None:
        return veri_yok("takım ya da rakip için tempo verisi yok")
    _, sezon, n_takim = takim_temposu(baglam, oyuncu.takim_id)
    rakip, _, n_rakip = takim_temposu(baglam, rakip_id)
    carpan = beklenen / sezon
    aciklama = f"beklenen tempo {beklenen:.1f}; takımın sezon temposu {sezon:.1f}, rakip {rakip:.1f}, lig {baglam.lig_tempo:.1f}"
    if config.TOPLAM_CIZGISI_HARMAN and istatistik in CIZGI_ISTATISTIKLERI:
        cizgi = cizgi_carpani(baglam, oyuncu.takim_id, mac)
        if cizgi is not None:
            aciklama += f"; tempo çarpanı {carpan:.3f}, çizgiden beklenen sayı {cizgi[1]:.1f} (sezon ort. {cizgi[2]:.1f}) çarpanı {cizgi[0]:.3f}: yarı yarıya"
            carpan = 0.5 * carpan + 0.5 * cizgi[0]
    return EtkenSonucu(carpan, True, min(n_takim, n_rakip), aciklama)
