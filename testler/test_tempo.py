"""Tempo: pozisyon sayısı, maç temposu ve tempo etkeninin çarpanı (elle hesaplanmış örnek). Ağa çıkmaz."""
import unittest

import config
import tahmin
import veritabani
import yukle
from etkenler import Mac, Oyuncu, tempo


def kur(maclar):
    """maclar: [(mac_id, tarih, ev, dep, tempo), ...]; her maç için iki takim_mac satırı yazar."""
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2, 3)])
    veritabani.yaz(c, "maclar", [{"mac_id": m, "tarih": t, "ev_takim_id": ev, "dep_takim_id": dep, "durum": "oynandi"} for m, t, ev, dep, _ in maclar])
    satirlar = []
    for m, _, ev, dep, hiz in maclar:
        satirlar.append({"takim_id": ev, "mac_id": m, "rakip_id": dep, "ev_mi": 1, "dakika": 240.0, "tempo": hiz})
        satirlar.append({"takim_id": dep, "mac_id": m, "rakip_id": ev, "ev_mi": 0, "dakika": 240.0, "tempo": hiz})
    veritabani.yaz(c, "takim_mac", satirlar)
    return c


class PozisyonTesti(unittest.TestCase):
    def test_pozisyon_sayisi(self):
        # 88 şut − 12 hücum ribaundu + 14 top kaybı + 0,44 × 21 serbest atış
        self.assertAlmostEqual(yukle.pozisyon_sayisi(88, 12, 14, 21), 99.24)


class TempoEtkeniTesti(unittest.TestCase):
    def setUp(self):
        # Takım 1 hızlı (iki maçı da 104), takım 2'nin maçları 104 ve 96, takım 3 yavaş (96).
        self.c = kur([("m1", "2026-11-01", 1, 2, 104.0), ("m2", "2026-11-03", 2, 3, 96.0),
                      ("m3", "2026-11-05", 1, 2, 104.0), ("m4", "2026-11-07", 3, 2, 96.0)])
        self.b = tahmin.Baglam(self.c, "2026-11-10")

    def tearDown(self):
        self.c.close()

    def test_takim_ve_lig_temposu(self):
        self.assertAlmostEqual(self.b.lig_tempo, 100.0)               # 8 satır: 4 × 104 ve 4 × 96
        k = config.TEMPO_K
        duzeltilmis, sezon, n = tempo.takim_temposu(self.b, 1)
        self.assertEqual((sezon, n), (104.0, 2))
        self.assertAlmostEqual(duzeltilmis, (2 * 104 + k * 100) / (2 + k))   # 2 maç: lig ortalamasına çekilir
        self.assertAlmostEqual(tempo.takim_temposu(self.b, 2)[0], 100.0)      # dört maçının ortalaması zaten 100
        self.assertIsNone(tempo.takim_temposu(self.b, 99))

    def test_carpan(self):
        k = config.TEMPO_K
        t1 = (2 * 104 + k * 100) / (2 + k)
        t3 = (2 * 96 + k * 100) / (2 + k)
        mac = Mac("bugun", "2026-11-10", 1, 3)
        hizli = tempo.hesapla(Oyuncu(10, "Hızlı takımın oyuncusu", 1, "PG"), mac, "sayi", self.b)
        yavas = tempo.hesapla(Oyuncu(30, "Yavaş takımın oyuncusu", 3, "PG"), mac, "sayi", self.b)
        beklenen = t1 * t3 / 100.0
        self.assertAlmostEqual(hizli.carpan, beklenen / 104.0)        # alışık olduğundan yavaş bir maç: çarpan < 1
        self.assertAlmostEqual(yavas.carpan, beklenen / 96.0)         # alışık olduğundan hızlı bir maç: çarpan > 1
        self.assertLess(hizli.carpan, 1.0)
        self.assertGreater(yavas.carpan, 1.0)
        self.assertEqual((hizli.veri_var, hizli.orneklem), (True, 2))

    def test_veri_yoksa_notr_ve_sonraki_maclar_kullanilmaz(self):
        erken = tahmin.Baglam(self.c, "2026-11-01")                   # hiç maç oynanmadan önce
        s = tempo.hesapla(Oyuncu(10, "x", 1, "PG"), Mac("m1", "2026-11-01", 1, 2), "sayi", erken)
        self.assertEqual((s.carpan, s.veri_var), (1.0, False))
        ara = tahmin.Baglam(self.c, "2026-11-05")                     # yalnızca m1 ve m2 görülür
        self.assertEqual(tempo.takim_temposu(ara, 1)[2], 1)
        self.assertEqual(tempo.takim_temposu(ara, 2)[2], 2)


if __name__ == "__main__":
    unittest.main()
