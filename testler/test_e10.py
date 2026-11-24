"""E10: yeni güven puanı, alt/orta/üst aralığı, ön ve kesin tahmin, maç öncesi çalıştırma. Ağa çıkmaz."""
import logging
import math
import unittest

import config
import etkenler
import geri_test
import mac_oncesi
import tahmin
import veritabani
from etkenler import EtkenSonucu
from testler.test_tahmin import BUGUN, MAC, OYUNCU, kur


class GuvenTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()
        self.b = tahmin.Baglam(self.c, BUGUN)
        self.k = self.b.oyuncu_kayitlari[10]

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.c.close()

    def zincir(self, **etkenler_):
        return etkenler.ZincirSonucu(1.0, 1.0, etkenler_)

    def test_agirliklar_100_eder(self):
        self.assertEqual(sum(config.GUVEN_AGIRLIK.values()), 100)
        self.assertEqual(len(config.GUVEN_AGIRLIK), 8)

    def test_veri_butunlugu_ve_sut_sansi(self):
        a = config.GUVEN_AGIRLIK
        tam = self.zincir(tempo=EtkenSonucu(1.0, True), sut_duzeltme=EtkenSonucu(1.0, True))
        _, b = tahmin.guven_puani(self.b, OYUNCU, MAC, "sayi", self.k, tam)
        self.assertEqual((b["veri_butunlugu"], b["sut_sansi"]), (a["veri_butunlugu"], a["sut_sansi"]))
        # İki etkenden birinde veri yok: bütünlük yarıya iner. Şut çarpanı 1'den çok uzak (sıcak seri): şans puanı sıfır.
        eksik = self.zincir(tempo=EtkenSonucu(1.0, False), sut_duzeltme=EtkenSonucu(0.70, True))
        _, b = tahmin.guven_puani(self.b, OYUNCU, MAC, "sayi", self.k, eksik)
        self.assertEqual((b["veri_butunlugu"], b["sut_sansi"]), (a["veri_butunlugu"] / 2, 0.0))
        # Top çalmada şans düzeltmesi yok: tam puan.
        _, b = tahmin.guven_puani(self.b, OYUNCU, MAC, "top_calma", self.k, eksik)
        self.assertEqual(b["sut_sansi"], a["sut_sansi"])

    def test_donus_ve_faul_guveni_dusurur(self):
        a = config.GUVEN_AGIRLIK
        _, olagan = tahmin.guven_puani(self.b, OYUNCU, MAC, "sayi", self.k, self.zincir(donus=EtkenSonucu(1.0, True)))
        _, donen = tahmin.guven_puani(self.b, OYUNCU, MAC, "sayi", self.k, self.zincir(donus=EtkenSonucu(0.9, True)))
        self.assertAlmostEqual(donen["sakatlik_belirsizligi"], olagan["sakatlik_belirsizligi"] / 2)
        self.c.execute("UPDATE oyuncu_mac SET faul = 6 WHERE oyuncu_id = 10")           # 100 dk'da 18 faul: 36 dk başına 6,5
        self.c.commit()
        b2 = tahmin.Baglam(self.c, BUGUN)
        _, faullu = tahmin.guven_puani(b2, OYUNCU, MAC, "sayi", b2.oyuncu_kayitlari[10], self.zincir())
        self.assertAlmostEqual(faullu["dakika_sabitligi"], olagan["dakika_sabitligi"] * 0.6)
        self.assertLessEqual(sum(olagan.values()), 100)
        self.assertEqual(set(olagan), set(a))


class AralikTesti(unittest.TestCase):
    def test_aralik(self):
        alt, ust = tahmin.aralik(20.0, 5.0)
        self.assertAlmostEqual(alt, 20 - config.ARALIK_Z * 5)
        self.assertAlmostEqual(ust, 20 + config.ARALIK_Z * 5)
        self.assertEqual(tahmin.aralik(1.0, 2.0)[0], 0.0)                                # alt sıfırın altına inmez

    def test_tahmin_satirlarinda_alt_orta_ust(self):
        logging.disable(logging.CRITICAL)
        c = kur()
        try:
            b = tahmin.Baglam(c, BUGUN)
            t = {s["istatistik"]: s for s in tahmin.oyuncu_tahmini(b, OYUNCU, MAC, [])}
            for s in t.values():
                self.assertLessEqual(s["alt"], s["tahmin"])
                self.assertGreaterEqual(s["ust"], s["tahmin"])
            # Sayı: 20, 10, 30 -> ortalama 20, varyans 100; lig oynaklığı yok (8 maçlı oyuncu yok) -> nötr 1.
            # Oyuncunun 3 maçı ARALIK_MIN_MAC altında: lig değeri (1,0) kullanılır -> sapma = √20.
            self.assertAlmostEqual(t["sayi"]["sapma"], config.ARALIK_OLCEK["sayi"] * math.sqrt(20.0))
            # Birleşik değerde varyanslar toplanır.
            self.assertAlmostEqual(t["sayi+ribaund+asist"]["sapma"],
                                   config.ARALIK_OLCEK["sayi+ribaund+asist"] * math.sqrt(sum(t[p]["sapma"] ** 2 for p in ("sayi", "ribaund", "asist"))))
        finally:
            c.close()
            logging.disable(logging.NOTSET)


class OnKesinTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.c.close()

    def sayi(self):
        return dict(self.c.execute("SELECT tahmin, alt, ust, calistirma, on_tahmin, on_hata, hata FROM tahminler WHERE oyuncu_id = 10 AND istatistik = 'sayi'").fetchone())

    def test_sabah_sonra_mac_oncesi(self):
        tahmin.gunu_tahmin_et(self.c, BUGUN, calistirma="sabah")
        sabah = self.sayi()
        self.assertEqual((sabah["calistirma"], sabah["on_tahmin"]), ("sabah", sabah["tahmin"]))
        self.assertLess(sabah["alt"], sabah["ust"])
        # Akşam bilgisi değişsin: oyuncunun tek maçını daha eklemiş gibi yapalım (tahmin değişir), sonra maç öncesi çalıştır.
        self.c.execute("UPDATE oyuncu_mac SET sayi = 40 WHERE oyuncu_id = 10 AND mac_id = 'g3'")
        self.c.commit()
        tahmin.gunu_tahmin_et(self.c, BUGUN, calistirma="mac_oncesi", yalniz_baslamamis=True)
        aksam = self.sayi()
        self.assertEqual(aksam["calistirma"], "mac_oncesi")
        self.assertNotAlmostEqual(aksam["tahmin"], sabah["tahmin"])
        self.assertEqual(aksam["on_tahmin"], sabah["tahmin"])                            # ön tahmin korunur
        # Maç oynansın ve puanlansın: ön ve kesin tahminin hatası ayrı ayrı yazılır.
        veritabani.yaz(self.c, "maclar", [{"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 2, "dep_takim_id": 1, "durum": "oynandi"}])
        veritabani.yaz(self.c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": "bugun", "takim_id": 1, "rakip_id": 2, "ev_mi": 0, "ilk_bes": 1, "dakika": 36.0,
                                                "sayi": 25, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}])
        geri_test.puanla(self.c, "canli")
        son = self.sayi()
        self.assertAlmostEqual(son["hata"], aksam["tahmin"] - 25)
        self.assertAlmostEqual(son["on_hata"], sabah["tahmin"] - 25)
        self.assertIn("ÖN TAHMİN", geri_test.rapor_metni(self.c, "canli"))

    def test_baslamis_mac_yenilenmez(self):
        tahmin.gunu_tahmin_et(self.c, BUGUN, calistirma="sabah")
        self.c.execute("UPDATE maclar SET baslama_utc = '2020-01-01T00:00:00Z' WHERE mac_id = 'bugun'")     # maç çoktan başlamış
        self.c.execute("UPDATE oyuncu_mac SET sayi = 40 WHERE oyuncu_id = 10 AND mac_id = 'g3'")
        self.c.commit()
        yazilan = tahmin.gunu_tahmin_et(self.c, BUGUN, calistirma="mac_oncesi", yalniz_baslamamis=True)
        self.assertEqual(yazilan, [])
        self.assertEqual(self.sayi()["calistirma"], "sabah")                             # ön tahmin olarak kaldı
        self.c.execute("UPDATE maclar SET baslama_utc = '2099-01-01T00:00:00Z' WHERE mac_id = 'bugun'")     # henüz başlamamış
        self.c.commit()
        self.assertGreater(len(tahmin.gunu_tahmin_et(self.c, BUGUN, calistirma="mac_oncesi", yalniz_baslamamis=True)), 0)
        self.assertEqual(self.sayi()["calistirma"], "mac_oncesi")

    def test_aksam_adimlari(self):
        adlar = [ad for ad, _, _ in mac_oncesi.aksam_adimlari(BUGUN)]
        self.assertEqual(adlar, ["sakatlik", "resmi_sakatlik", "oranlar", "atamalar", "ilk_besler", "onsuz_ve_hakem_tablolari", "tahmin", "site_veri"])


if __name__ == "__main__":
    unittest.main()
