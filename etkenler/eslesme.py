"""Rakibe göre düzeltilmiş pozisyon savunması (PLAN_EK etken 1).

Rakip takıma karşı oynayan, oyuncuyla aynı pozisyondaki oyuncuların gerçekleşen
üretimi, kendi sezon üretimlerinden beklenenin kaç katı? Beklenen üretim maçın
temposuna göre ölçeklendiği için bu oran tempodan arındırılmıştır; tempo ayrı bir
etkendir. Hesap savunma.py içindedir; ham sürüm etkenler/eslesme_ham.py dosyasında durur.
"""
from etkenler import EtkenSonucu, veri_yok


def hesapla(oyuncu, mac, istatistik, baglam):
    if not oyuncu.pozisyon:
        return veri_yok("oyuncunun pozisyonu bilinmiyor")
    s = baglam.savunma.get((mac.rakip(oyuncu.takim_id), oyuncu.pozisyon, istatistik))
    if s is None or s["beklenene_gore_duzeltilmis"] is None:
        return veri_yok("rakibin savunma profili yok")
    return EtkenSonucu(
        s["beklenene_gore_duzeltilmis"], True, round(s["oyuncu_dakika"]),
        f"rakibin {oyuncu.pozisyon} pozisyonuna verdiği: beklenene göre {s['beklenene_gore_oran']:.2f} "
        f"(ham {s['oran']:.2f}), {s['oyuncu_dakika']:.0f} oyuncu-dakikası",
    )
