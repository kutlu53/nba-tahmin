"""Geri test: puanlama, birleşik değerler, isabet ölçütü ve geriye dönük denemede sızıntı olmaması."""
import logging
import unittest

import pandas as pd

import config
import etkenler
import geri_test
import tahmin
import veritabani
from testler.test_tahmin import BUGUN, MAC, OYUNCU, kur


class GeriTestTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()
        # Maç oynanmadan önce, sonucu hiç bilinmeden üretilen sayı tahmini.
        baglam = tahmin.Baglam(self.c, BUGUN)
        satirlar = tahmin.oyuncu_tahmini(baglam, OYUNCU, MAC, etkenler.acik_etkenler())
        self.onceden = next(s["tahmin"] for s in satirlar if s["istatistik"] == "sayi")
        # "Bugün"ün maçı oynanmış olsun: oyuncu 10 -> 36 dk, 25 sayı, 4 ribaund, 6 asist. Oyuncu 30 oynamadı.
        veritabani.yaz(self.c, "maclar", [{"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 2, "dep_takim_id": 1, "durum": "oynandi"}])
        veritabani.yaz(self.c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": "bugun", "takim_id": 1, "rakip_id": 2, "ev_mi": 0, "ilk_bes": 1,
                                                "dakika": 36.0, "sayi": 25, "ribaund": 4, "asist": 6, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}])

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.c.close()

    def test_geriye_donuk_deneme_ve_puanlama(self):
        gun, satir = geri_test.gecmisi_dene(self.c, "2026-11-01", BUGUN)
        # Yalnızca 10 Kasım'da tahmin üretilebilir: önceki günlerde oyuncuların 3 maçı yok.
        self.assertEqual(satir, 2 * (7 + len(config.BIRLESIK)))
        t = {(s["oyuncu_id"], s["istatistik"]): s for s in self.c.execute("SELECT * FROM tahminler WHERE tur = 'geri_test'")}
        sayi = t[(10, "sayi")]
        # Tahmin, maçın kendi sonucunu (25 sayı) görmeden üretilmiş olmalı: maçtan önce üretilenle aynı.
        self.assertAlmostEqual(sayi["tahmin"], self.onceden)
        self.assertEqual(sayi["gerceklesen"], 25)
        self.assertAlmostEqual(sayi["hata"], sayi["tahmin"] - 25)
        self.assertEqual(t[(10, "sayi+ribaund+asist")]["gerceklesen"], 35)
        self.assertEqual(t[(10, "ribaund+asist")]["gerceklesen"], 10)
        self.assertIsNone(t[(30, "sayi")]["gerceklesen"])          # oynamadı: puanlanmaz
        self.assertIsNone(t[(30, "sayi")]["hata"])

    def test_yeniden_calisinca_cogalmaz_ve_rapor_cikar(self):
        geri_test.gecmisi_dene(self.c, "2026-11-01", BUGUN)
        n1 = self.c.execute("SELECT COUNT(*) FROM tahminler").fetchone()[0]
        geri_test.gecmisi_dene(self.c, "2026-11-01", BUGUN)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tahminler").fetchone()[0], n1)
        metin = geri_test.rapor_metni(self.c)
        self.assertIn("İSTATİSTİK BAŞINA HATA", metin)
        self.assertIn("GÜVEN DİLİMLERİ", metin)
        self.assertIn("ETKEN KATKISI", metin)

    def test_etken_katkisi_kayitli_tahminle_tutarli(self):
        geri_test.gecmisi_dene(self.c, "2026-11-01", BUGUN)
        df = geri_test.tahminleri_oku(self.c)
        p = df[df["gerceklesen"].notna()]
        carpan, _ = geri_test.etken_carpanlari(self.c)
        k = geri_test.etken_katkisi(p, carpan)
        sayi = p[p["istatistik"] == "sayi"].iloc[0]
        self.assertAlmostEqual(k.loc["sayi", "hepsi açık"], abs(sayi["hata"]))
        self.assertAlmostEqual(k.loc["sayi", "hepsi kapalı"], abs(sayi["temel_tahmin"] - 25))
        # Birleşik değerin ölçütü, bileşenlerin sezon ortalamalarının toplamı: (60 + 0 + 0) / 3 maç.
        self.assertAlmostEqual(p[p["istatistik"] == "sayi+ribaund+asist"].iloc[0]["sezon_ort"], 20.0)

    def test_isabet_olcutu(self):
        tahmin = pd.Series([20.0, 20.0, 2.0, 2.0])
        hata = pd.Series([5.0, -5.1, 1.0, -1.1])
        self.assertEqual(list(geri_test.isabet(tahmin, hata)), [True, False, True, False])


if __name__ == "__main__":
    unittest.main()
