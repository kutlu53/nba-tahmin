"""Fırsat etkeni: elle hesaplanmış dönüşüm oranı, rakip ayarı ve takip verisi yokken davranış. Ağa çıkmaz."""
import unittest

import config
import etkenler
import tahmin
import veritabani
from etkenler import Mac, Oyuncu, firsat

BUGUN = "2026-11-10"


def kur(takip=True, takim_sutlari=False):
    """Oyuncu 10 (PG, takım 1): 3 maç, 30'ar dk; her maçta 10 olası asistten 8 asist (dönüşüm %80, şanslı),
    10 ribaund fırsatından 4 ribaund. Oyuncu 20 (PG, takım 2): her maçta 10 olası asistten 4 asist, 10 fırsattan 6 ribaund.
    Lig (PG) dönüşümü: asist (24 + 12) / 60 = %60; ribaund (12 + 18) / 60 = %50."""
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
    veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "Pasör", "takim_id": 1, "pozisyon": "PG"},
                                    {"oyuncu_id": 20, "isim": "Diğer", "takim_id": 2, "pozisyon": "PG"}])
    veritabani.yaz(c, "maclar", [{"mac_id": f"g{i}", "tarih": f"2026-11-0{i}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"} for i in (1, 2, 3)]
                   + [{"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])
    kayitlar, takipler = [], []
    for i in (1, 2, 3):
        for oyuncu, takim, asist, ribaund in ((10, 1, 8, 4), (20, 2, 4, 6)):
            kayitlar.append({"oyuncu_id": oyuncu, "mac_id": f"g{i}", "takim_id": takim, "rakip_id": 3 - takim, "ev_mi": int(takim == 1), "ilk_bes": 1,
                             "dakika": 30.0, "sayi": 10, "ribaund": ribaund, "asist": asist, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0})
            takipler.append({"oyuncu_id": oyuncu, "mac_id": f"g{i}", "olasi_asist": 10, "pas": 40, "ribaund_firsati": 10, "top_dokunusu": 60})
    veritabani.yaz(c, "oyuncu_mac", kayitlar)
    if takip:
        veritabani.yaz(c, "takip_mac", takipler)
    if takim_sutlari:
        # Takım 1: 40/80 atar; takım 2: 36/90 atar. Yani takım 2 rakibine %50, takım 1 rakibine %40 izin veriyor; lig 76/170.
        veritabani.yaz(c, "takim_mac", [
            {"takim_id": t, "mac_id": f"g{i}", "rakip_id": 3 - t, "ev_mi": int(t == 1), "dakika": 240.0, "tempo": 98.0, "pozisyon_sayisi": 100.0,
             "saha_ici_isabet": 40 if t == 1 else 36, "saha_ici_deneme": 80 if t == 1 else 90}
            for i in (1, 2, 3) for t in (1, 2)])
    return c


PASOR = Oyuncu(10, "Pasör", 1, "PG")
MAC = Mac("bugun", BUGUN, 1, 2)


class FirsatTesti(unittest.TestCase):
    def test_donusum_orani_elle_hesap(self):
        c = kur()
        b = tahmin.Baglam(c, BUGUN)
        self.assertAlmostEqual(firsat.lig_donusumu(b)[("PG", "asist")], 36 / 60)
        self.assertAlmostEqual(firsat.lig_donusumu(b)[("PG", "ribaund")], 30 / 60)
        v = firsat.oyuncu_verisi(b, PASOR, "asist")
        self.assertAlmostEqual(v["hacim_36"], 12.0)                    # 90 dk'da 30 olası asist
        self.assertAlmostEqual(v["guncel"], 0.8)
        k = config.FIRSAT_K["asist"]
        self.assertAlmostEqual(v["donusum"], (24 + k * 0.6) / (30 + k))   # %80, %60'a doğru çekilir
        s = firsat.hesapla(PASOR, MAC, "asist", b)
        # Temel asist oranı 36 dk başına 9,6 (90 dk'da 24); yeni tahmin 12 × düzeltilmiş dönüşüm. Takım şut verisi yok: ayar 1.
        self.assertAlmostEqual(s.carpan, 12.0 * v["donusum"] / 9.6)
        self.assertLess(s.carpan, 1.0)                                 # şanslı dönüşüm törpülenir
        r = firsat.hesapla(PASOR, MAC, "ribaund", b)
        kr = config.FIRSAT_K["ribaund"]
        self.assertAlmostEqual(r.carpan, 12.0 * ((12 + kr * 0.5) / (30 + kr)) / 4.8)
        self.assertGreater(r.carpan, 1.0)                              # şanssız ribaund dönüşümü yukarı çekilir
        self.assertEqual(firsat.hesapla(PASOR, MAC, "sayi", b).carpan, 1.0)
        c.close()

    def test_takip_verisi_yoksa_devre_disi(self):
        c = kur(takip=False)
        b = tahmin.Baglam(c, BUGUN)
        s = firsat.hesapla(PASOR, MAC, "asist", b)
        self.assertEqual((s.carpan, s.veri_var), (1.0, False))
        # Tahmin, PLAN'daki doğrudan ortalamaya düşer: 30 dk × 9,6 / 36 = 8 asist.
        t = {x["istatistik"]: x for x in tahmin.oyuncu_tahmini(b, PASOR, MAC, etkenler.acik_etkenler({"firsat": config.ETKENLER["firsat"]}))}
        self.assertAlmostEqual(t["asist"]["tahmin"], 8.0)
        self.assertIn("TAKİP VERİSİ ALINAMADI", firsat.rapor_metni(c, b, BUGUN))
        c.close()

    def test_rakip_ayari(self):
        c = kur(takim_sutlari=True)
        b = tahmin.Baglam(c, BUGUN)
        kn = config.FIRSAT_RAKIP_K
        lig = 228 / 510                                                # (3 × 40 + 3 × 36) / (3 × 80 + 3 × 90)
        cek = lambda deger: (3 * deger + kn * lig) / (3 + kn)          # 3 maç: lig ortalamasına çekilir
        t1_kendi, t1_izin, t2_kendi, t2_izin = cek(0.5), cek(0.4), cek(0.4), cek(0.5)
        ayar, _ = firsat.rakip_ayari(b, PASOR, MAC, "asist")
        self.assertAlmostEqual(ayar, (t2_izin / lig) ** config.FIRSAT_RAKIP_USSU)   # rakip (takım 2) ortalamadan fazla şut yediriyor
        self.assertGreater(ayar, 1.0)
        ayar_r, _ = firsat.rakip_ayari(b, PASOR, MAC, "ribaund")
        beklenen = ((1 - t1_kendi) * (1 - t2_izin) / (1 - lig) + (1 - t2_kendi) * (1 - t1_izin) / (1 - lig)) / 2
        olagan = ((1 - t1_kendi) + (1 - t1_izin)) / 2
        self.assertAlmostEqual(ayar_r, beklenen / olagan)
        c.close()

    def test_takipli_mac_sayisi_azsa_devre_disi(self):
        c = kur()
        c.execute("DELETE FROM takip_mac WHERE mac_id = 'g1'")
        c.commit()
        b = tahmin.Baglam(c, BUGUN)
        self.assertFalse(firsat.hesapla(PASOR, MAC, "asist", b).veri_var)   # yalnızca 2 maçta takip verisi var
        c.close()


if __name__ == "__main__":
    unittest.main()
