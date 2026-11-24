"""Üst / alt olasılığı: dağılım hesabı ve oyuncu araması. Ağa çıkmaz."""
import logging
import math
import unittest

import tahmin
import ust_alt
from testler.test_tahmin import BUGUN, kur


class OlasilikTesti(unittest.TestCase):
    def test_poisson_elle_hesap(self):
        # Ortalama 2, varyans ≤ ortalama: Poisson. P(X > 1,5) = 1 − e⁻²(1 + 2).
        self.assertAlmostEqual(ust_alt.ust_olasiligi(2.0, 1.0, 1.5), 1 - math.exp(-2) * 3)
        self.assertAlmostEqual(ust_alt.ust_olasiligi(2.0, 1.0, 2.0), ust_alt.ust_olasiligi(2.0, 1.0, 2.5))    # tam sayı çizgide eşitlik "alt" sayılır

    def test_negatif_binom_ortalamayi_ve_varyansi_tutar(self):
        ort, sapma = 15.0, 7.0
        # Üst olasılıklarının toplamı ortalamayı verir: E[X] = Σ P(X > k).
        self.assertAlmostEqual(sum(ust_alt.ust_olasiligi(ort, sapma, k) for k in range(400)), ort, places=6)
        # E[X²] = Σ (2k + 1) P(X > k)  ->  varyans = sapma².
        ikinci = sum((2 * k + 1) * ust_alt.ust_olasiligi(ort, sapma, k) for k in range(400))
        self.assertAlmostEqual(ikinci - ort ** 2, sapma ** 2, places=5)

    def test_cizgi_yukseldikce_ust_olasiligi_duser(self):
        degerler = [ust_alt.ust_olasiligi(14.1, 7.6, c) for c in (5.5, 9.5, 13.5, 17.5, 25.5)]
        self.assertEqual(degerler, sorted(degerler, reverse=True))
        self.assertTrue(all(0 <= d <= 1 for d in degerler))
        self.assertEqual(ust_alt.ust_olasiligi(0.0, 1.0, 0.5), 0.0)

    def test_taraf(self):
        self.assertEqual((ust_alt.taraf(0.62), ust_alt.taraf(0.31), ust_alt.taraf(0.52)), ("ÜST", "ALT", "kararsız"))


class AramaTesti(unittest.TestCase):
    def test_oyuncu_bulunur(self):
        logging.disable(logging.CRITICAL)
        c = kur()
        try:
            tahmin.gunu_tahmin_et(c, BUGUN)
            adaylar, tarih = ust_alt.oyuncu_tahmini(c, "bizim", "sayi")
            self.assertEqual((tarih, [s["isim"] for s in adaylar]), (BUGUN, ["Bizim Oyuncu"]))
            s = adaylar[0]
            p = ust_alt.ust_olasiligi(s["tahmin"], ust_alt.sapma(s["tahmin"], s["ust"]), s["tahmin"] - 0.01)
            self.assertTrue(0.3 < p < 0.7)                              # çizgi tahminin kendisindeyken yarı yarıya yakın
            self.assertEqual(ust_alt.oyuncu_tahmini(c, "olmayan biri", "sayi")[0], [])
            self.assertEqual(len(ust_alt.oyuncu_tahmini(c, "bizim", "sayi+ribaund+asist")[0]), 1)
        finally:
            c.close()
            logging.disable(logging.NOTSET)


if __name__ == "__main__":
    unittest.main()
