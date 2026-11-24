"""Yolculuk / dinlenme hesabı ve yorgunluk etkeni. Ağa çıkmaz."""
import unittest

import config
import tahmin
import veritabani
import yolculuk
from etkenler import Mac, Oyuncu, yorgunluk


class HesapTesti(unittest.TestCase):
    def test_mesafe(self):
        # New York (Madison Square Garden) – Los Angeles (Crypto.com Arena): yaklaşık 3.940 km.
        self.assertAlmostEqual(yolculuk.mesafe_km(40.7505, -73.9934, 34.0430, -118.2673), 3940, delta=40)
        self.assertEqual(yolculuk.mesafe_km(10, 20, 10, 20), 0)

    def test_saat_farki(self):
        self.assertEqual(yolculuk.saat_farki("America/Los_Angeles", "America/New_York", "2026-11-23"), 3)     # doğuya: artı
        self.assertEqual(yolculuk.saat_farki("America/New_York", "America/Los_Angeles", "2026-11-23"), -3)
        # Phoenix yaz saati uygulamaz: kışın Denver ile aynı, mart ortasından sonra bir saat geride.
        self.assertEqual(yolculuk.saat_farki("America/Phoenix", "America/Denver", "2026-11-23"), 0)
        self.assertEqual(yolculuk.saat_farki("America/Phoenix", "America/Denver", "2027-03-20"), 1)

    def test_salonlar_dosyasi(self):
        satirlar = yolculuk.salonlari_oku()
        self.assertEqual(sum(s["takim"] is not None for s in satirlar), 30)         # 30 takımın ev şehri
        self.assertEqual(len({s["sehir"] for s in satirlar}), len(satirlar))
        self.assertTrue(all(-90 <= s["enlem"] <= 90 and -180 <= s["boylam"] <= 180 and 0 <= s["rakim_m"] < 3000 for s in satirlar))
        self.assertEqual({s["takim"] for s in satirlar if s["rakim_m"] >= config.YORGUNLUK_RAKIM_M and s["takim"]}, {"DEN", "UTA"})


def kur():
    """Takım 1 (New York) dört gün içinde üç maç oynar: evde, ertesi gün Los Angeles'ta, iki gün sonra Denver'da."""
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": 1, "kisaltma": "NYK", "isim": "New York"}, {"takim_id": 2, "kisaltma": "LAL", "isim": "Los Angeles"},
                                   {"takim_id": 3, "kisaltma": "DEN", "isim": "Denver"}])
    yolculuk.salonlari_yukle(c)
    veritabani.yaz(c, "maclar", [
        {"mac_id": "g1", "tarih": "2026-11-01", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi", "salon_sehri": "New York"},
        {"mac_id": "g2", "tarih": "2026-11-02", "ev_takim_id": 2, "dep_takim_id": 1, "durum": "oynandi", "salon_sehri": "Los Angeles"},
        {"mac_id": "g3", "tarih": "2026-11-04", "ev_takim_id": 3, "dep_takim_id": 1, "durum": "oynanacak", "salon_sehri": "Denver"},
    ])
    return c


class YolculukTesti(unittest.TestCase):
    def setUp(self):
        self.c = kur()
        yolculuk.yolculugu_yaz(self.c)
        self.y = {(s["takim_id"], s["mac_id"]): dict(s) for s in self.c.execute("SELECT * FROM yolculuk")}

    def tearDown(self):
        self.c.close()

    def test_takim_1in_uc_maci(self):
        g1, g2, g3 = self.y[(1, "g1")], self.y[(1, "g2")], self.y[(1, "g3")]
        self.assertEqual((g1["dinlenme_gunu"], g1["km"], g1["deplasman_sirasi"]), (None, 0.0, 0))      # sezonun ilk maçı, evde
        self.assertEqual((g2["dinlenme_gunu"], g2["saat_dilimi_farki"], g2["deplasman_sirasi"]), (0, -3.0, 1))   # arka arkaya, batıya
        self.assertAlmostEqual(g2["km"], 3940, delta=40)
        self.assertEqual((g3["dinlenme_gunu"], g3["uc_dortte"], g3["dort_altida"], g3["deplasman_sirasi"], g3["rakim_m"]), (1, 1, 0, 2, 1609.0))
        self.assertEqual(g3["saat_dilimi_farki"], 1.0)                                                 # Los Angeles'tan Denver'a: doğuya 1 saat

    def test_deplasman_takimi_ilk_macta_kendi_sehrinden_gelir(self):
        self.assertAlmostEqual(self.y[(2, "g1")]["km"], 3940, delta=40)       # Los Angeles'tan New York'a
        self.assertEqual(self.y[(2, "g1")]["saat_dilimi_farki"], 3.0)

    def test_bilinmeyen_sehir_hata_verir(self):
        self.c.execute("UPDATE maclar SET salon_sehri = 'Atlantis' WHERE mac_id = 'g3'")
        with self.assertRaises(ValueError):
            yolculuk.yolculuk_hesapla(self.c)

    def test_kosullar_ve_etken(self):
        b = tahmin.Baglam(self.c, "2026-11-04")
        self.assertEqual(yorgunluk.mac_kosullari(b, 1, "g1"), [])
        self.assertEqual(yorgunluk.mac_kosullari(b, 1, "g2"), ["arka_arkaya", "uzun_yol", "saat_dilimi"])
        self.assertEqual(yorgunluk.mac_kosullari(b, 1, "g3"), ["uc_dortte", "yuksek_rakim"])
        self.assertEqual(yorgunluk.mac_kosullari(b, 3, "g3"), [])                # ev sahibi için rakım koşulu yok
        self.assertIsNone(yorgunluk.mac_kosullari(b, 1, "olmayan"))
        # Öğrenilecek maç kaydı yok: koşullar var ama etkileri bilinmiyor -> çarpan 1.
        s = yorgunluk.hesapla(Oyuncu(10, "x", 1, "PG"), Mac("g3", "2026-11-04", 3, 1), "sayi", b)
        self.assertEqual((s.carpan, s.veri_var), (1.0, True))
        s = yorgunluk.hesapla(Oyuncu(10, "x", 1, "PG"), Mac("olmayan", "2026-11-04", 3, 1), "sayi", b)
        self.assertFalse(s.veri_var)


class EtkiTesti(unittest.TestCase):
    def test_kosul_etkisi_oyuncunun_kendi_ortalamasina_gore_ogrenilir(self):
        c = kur()
        veritabani.yaz(c, "maclar", [{"mac_id": "g0", "tarih": "2026-10-28", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi", "salon_sehri": "New York"}])
        yolculuk.yolculugu_yaz(c)
        veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "x", "takim_id": 1, "pozisyon": "PG"}])
        # Olağan iki maçta 30 dk'da 20'şer sayı; arka arkaya maçta (g2) 30 dk'da 10 sayı.
        veritabani.yaz(c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": m, "takim_id": 1, "rakip_id": 2, "ev_mi": int(m != "g2"), "ilk_bes": 1, "dakika": 30.0,
                                           "sayi": s, "ribaund": 5, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}
                                          for m, s in (("g0", 20), ("g1", 20), ("g2", 10))])
        b = tahmin.Baglam(c, "2026-11-04")
        etki = yorgunluk.kosul_etkileri(b)["arka_arkaya"]
        # Koşulda: gerçekleşen 10, diğer iki maçtan beklenen 20 -> 0,5. Koşul dışında: gerçekleşen 40; beklenen 2 × (30 sayı / 60 dk × 30 dk) = 30 -> 1,333.
        self.assertAlmostEqual(etki["sayi"][2], 0.5 / (40 / 30))
        self.assertAlmostEqual(etki["sayi"][0], (1 * etki["sayi"][2] + config.YORGUNLUK_K) / (1 + config.YORGUNLUK_K))   # tek maç: neredeyse 1'e çekilir
        self.assertAlmostEqual(etki["ribaund"][2], 1.0)
        c.close()


if __name__ == "__main__":
    unittest.main()
