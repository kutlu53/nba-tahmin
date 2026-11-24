"""Etken zincirinin sınamaları. Çalıştırma: python -m unittest discover -s testler -t ."""
import logging
import sys
import types
import unittest

import etkenler
import veritabani
from etkenler import EtkenSonucu

SINIRSIZ = (0.0, 100.0)


def sahte_etken(ad, carpan, veri_var=True, orneklem=10, hata=None):
    """etkenler/<ad>.py dosyası varmış gibi davranan sahte modül kaydeder."""
    cagri = []

    def hesapla(oyuncu, mac, istatistik, baglam):
        cagri.append((oyuncu, mac, istatistik))
        if hata:
            raise hata
        return EtkenSonucu(carpan, veri_var, orneklem, f"sahte {ad}")

    sys.modules[f"etkenler.{ad}"] = types.SimpleNamespace(hesapla=hesapla)
    return cagri


def ayar(acik=True, alt=0.0, ust=100.0):
    return {"acik": acik, "alt": alt, "ust": ust}


def calistir(ayarlar, genel_sinir=SINIRSIZ):
    return etkenler.uygula(1, "0022600001", "sayi", {}, etkenler.acik_etkenler(ayarlar), genel_sinir)


class ZincirTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        for ad in [a for a in sys.modules if a.startswith("etkenler.sahte_")]:
            del sys.modules[ad]

    def test_etken_yokken_tahmin_degismez(self):
        z = etkenler.uygula(1, "m", "sayi", {}, etkenler=[])
        temel = 23.7
        self.assertEqual(temel * z.carpan, temel)

    def test_zincir_dogrudan_carpimla_ayni(self):
        sahte_etken("sahte_a", 1.08)
        sahte_etken("sahte_b", 0.95)
        sahte_etken("sahte_c", 1.02)
        z = calistir({"sahte_a": ayar(), "sahte_b": ayar(), "sahte_c": ayar()})
        self.assertEqual(z.carpan, 1.08 * 0.95 * 1.02)
        self.assertEqual(list(z.etkenler), ["sahte_a", "sahte_b", "sahte_c"])

    def test_kapali_etken_cagrilmaz(self):
        a = sahte_etken("sahte_a", 1.10)
        b = sahte_etken("sahte_b", 0.90)
        z = calistir({"sahte_a": ayar(), "sahte_b": ayar(acik=False)})
        self.assertEqual((len(a), len(b)), (1, 0))
        self.assertEqual(z.carpan, 1.10)
        self.assertNotIn("sahte_b", z.etkenler)

    def test_etken_siniri(self):
        sahte_etken("sahte_a", 1.40)
        sahte_etken("sahte_b", 0.50)
        z = calistir({"sahte_a": ayar(alt=0.90, ust=1.10), "sahte_b": ayar(alt=0.94, ust=1.06)})
        self.assertEqual(z.etkenler["sahte_a"].carpan, 1.10)
        self.assertEqual(z.etkenler["sahte_b"].carpan, 0.94)
        self.assertIn("ham 1.400", z.etkenler["sahte_a"].aciklama)

    def test_genel_sinir(self):
        sahte_etken("sahte_a", 1.30)
        sahte_etken("sahte_b", 1.30)
        z = calistir({"sahte_a": ayar(), "sahte_b": ayar()}, genel_sinir=(0.70, 1.45))
        self.assertAlmostEqual(z.ham_carpan, 1.69)
        self.assertEqual(z.carpan, 1.45)

    def test_veri_yoksa_carpan_bir(self):
        sahte_etken("sahte_a", 1.25, veri_var=False)
        z = calistir({"sahte_a": ayar()})
        self.assertEqual(z.carpan, 1.0)
        self.assertFalse(z.etkenler["sahte_a"].veri_var)

    def test_hata_veren_etken_zinciri_durdurmaz(self):
        sahte_etken("sahte_a", 1.0, hata=RuntimeError("kaynak bozuk"))
        sahte_etken("sahte_b", 1.05)
        z = calistir({"sahte_a": ayar(), "sahte_b": ayar()})
        self.assertEqual(z.carpan, 1.05)
        self.assertFalse(z.etkenler["sahte_a"].veri_var)
        self.assertIn("kaynak bozuk", z.etkenler["sahte_a"].aciklama)

    def test_gecersiz_carpan_notr_sayilir(self):
        for kotu in (float("nan"), float("inf"), 0.0, -1.2):
            sahte_etken("sahte_a", kotu)
            z = calistir({"sahte_a": ayar()})
            self.assertEqual(z.carpan, 1.0, kotu)
            self.assertFalse(z.etkenler["sahte_a"].veri_var, kotu)

    def test_acik_ama_dosyasi_olmayan_etken_hata_verir(self):
        with self.assertRaises(ModuleNotFoundError):
            etkenler.acik_etkenler({"sahte_olmayan": ayar()})

    def test_kucuk_orneklem(self):
        self.assertEqual(etkenler.kucuk_orneklem(0, 1.30, 10), 1.0)
        self.assertAlmostEqual(etkenler.kucuk_orneklem(10, 1.30, 10), 1.15)
        self.assertAlmostEqual(etkenler.kucuk_orneklem(90, 1.30, 10), 1.27)

    def test_tahmin_etken_tablosuna_yazim(self):
        c = veritabani.baglan(":memory:")
        veritabani.sema_kur(c)
        veritabani.yaz(c, "takimlar", [{"takim_id": 1, "kisaltma": "AAA", "isim": "A"}, {"takim_id": 2, "kisaltma": "BBB", "isim": "B"}])
        veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 7, "isim": "Deneme Oyuncu", "takim_id": 1}])
        veritabani.yaz(c, "maclar", [{"mac_id": "m1", "tarih": "2026-11-23", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])
        tahmin = {"tarih": "2026-11-23", "oyuncu_id": 7, "mac_id": "m1", "istatistik": "sayi", "tur": "canli",
                  "tahmin": 20.0, "guven": 50.0, "olusturma": veritabani.simdi_utc()}
        sahte_etken("sahte_a", 1.08, orneklem=12)
        sahte_etken("sahte_b", 1.0, veri_var=False)
        z = calistir({"sahte_a": ayar(), "sahte_b": ayar()})
        for _ in range(2):  # aynı tahmin iki kez yazılınca satır çoğalmamalı
            veritabani.yaz(c, "tahminler", [tahmin])
            tid = c.execute("SELECT tahmin_id FROM tahminler").fetchone()[0]
            veritabani.yaz(c, "tahmin_etken", etkenler.etken_satirlari(tid, z))
        satirlar = [tuple(s) for s in c.execute("SELECT etken, carpan, veri_var, orneklem FROM tahmin_etken ORDER BY etken")]
        self.assertEqual(satirlar, [("sahte_a", 1.08, 1, 12), ("sahte_b", 1.0, 0, 10)])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM tahminler").fetchone()[0], 1)
        c.close()


if __name__ == "__main__":
    unittest.main()
