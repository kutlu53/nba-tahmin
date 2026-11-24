"""Rakibin pozisyona göre savunması, HAM hesap (PLAN bölüm 5).

Karşılaştırma için saklanır; varsayılan olarak kapalıdır. Kime karşı oynandığını
ve tempoyu hesaba katmaz. Yerini etkenler/eslesme.py almıştır.
"""
from etkenler import EtkenSonucu, veri_yok


def hesapla(oyuncu, mac, istatistik, baglam):
    if not oyuncu.pozisyon:
        return veri_yok("oyuncunun pozisyonu bilinmiyor")
    s = baglam.savunma.get((mac.rakip(oyuncu.takim_id), oyuncu.pozisyon, istatistik))
    if s is None or s["duzeltilmis_oran"] is None:
        return veri_yok("rakibin savunma profili yok")
    return EtkenSonucu(
        s["duzeltilmis_oran"], True, s["mac_sayisi"],
        f"rakibin {oyuncu.pozisyon} pozisyonuna verdiği: ham oran {s['oran']:.2f}, {s['mac_sayisi']} maç",
    )
