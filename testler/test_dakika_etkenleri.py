"""Beklenen dakikayı düzelten etkenler (fark riski, eksik arkadaş dakikası, dönüş), oran ayrıştırması ve çizgi harmanı."""
import math
import unittest

import config
import etkenler
import tahmin
import veritabani
from etkenler import Mac, Oyuncu, donus, eksik_dakika, fark_riski, tempo
from kaynak import espn
from testler import test_kullanim


class OlasilikTesti(unittest.TestCase):
    def test_buyuk_fark_olasiligi(self):
        # Fark ortalaması 0, standart sapma 12: |fark| ≥ 20 olasılığı = 2 × (1 − Φ(20/12)).
        phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
        self.assertAlmostEqual(fark_riski.buyuk_fark_olasiligi(0, 12), 2 * (1 - phi(20 / 12)))
        self.assertAlmostEqual(fark_riski.buyuk_fark_olasiligi(8, 12), fark_riski.buyuk_fark_olasiligi(-8, 12))   # yön fark etmez
        self.assertGreater(fark_riski.buyuk_fark_olasiligi(13, 12), fark_riski.buyuk_fark_olasiligi(3, 12))       # favori ne kadar netse o kadar yüksek
        self.assertAlmostEqual(fark_riski.buyuk_fark_olasiligi(20, 12), 0.5, delta=0.01)


class OranTesti(unittest.TestCase):
    def test_oran_ayristirma(self):
        o = espn._oran_ayristir({"spread": -10.5, "overUnder": 222.5, "provider": {"name": "DraftKings"}})
        self.assertEqual(o, {"handikap": -10.5, "toplam": 222.5, "saglayici": "DraftKings"})
        self.assertEqual(espn._oran_ayristir(None), {"handikap": None, "toplam": None, "saglayici": None})
        self.assertIsNone(espn._oran_ayristir({"spread": "yok"})["handikap"])


def fark_kur():
    """Takım 1'in 8 maçı: 4'ü farklı (25 sayı), 4'ü yakın (5 sayı). İlk beş oyuncusu (10) yakın maçlarda 36,
    farklı maçlarda 30 dk; yedek (11) yakın maçlarda 12, farklı maçlarda 18 dk oynar."""
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
    veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "İlk Beş", "takim_id": 1, "pozisyon": "PG"},
                                    {"oyuncu_id": 11, "isim": "Yedek", "takim_id": 1, "pozisyon": "SG"}])
    maclar, kayitlar = [], []
    for i in range(1, 9):
        farkli = i % 2 == 0
        maclar.append({"mac_id": f"g{i}", "tarih": f"2026-11-{i:02d}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi",
                       "ev_sayi": 125 if farkli else 105, "dep_sayi": 100})
        for oyuncu, ilk_bes, dakika in ((10, 1, 30.0 if farkli else 36.0), (11, 0, 18.0 if farkli else 12.0)):
            kayitlar.append({"oyuncu_id": oyuncu, "mac_id": f"g{i}", "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "ilk_bes": ilk_bes, "dakika": dakika,
                             "sayi": 10, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0})
    maclar.append({"mac_id": "bugun", "tarih": "2026-11-20", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak", "ev_sayi": None, "dep_sayi": None})
    veritabani.yaz(c, "maclar", maclar)
    veritabani.yaz(c, "oyuncu_mac", kayitlar)
    return c


class FarkRiskiTesti(unittest.TestCase):
    def setUp(self):
        self.c = fark_kur()
        self.mac = Mac("bugun", "2026-11-20", 1, 2)

    def tearDown(self):
        self.c.close()

    def test_dakika_etkisi_elle_hesap(self):
        b = tahmin.Baglam(self.c, "2026-11-20")
        etki = fark_riski.dakika_etkisi(b)
        # İlk beş: farklı maçta 30 dk oynar; alışık olduğu (diğer 7 maçın ortalaması) (3 × 30 + 4 × 36) / 7.
        # Yakın maçta 36 dk; alışık olduğu (4 × 30 + 3 × 36) / 7. Oranların oranı − 1, sonra 4 oyuncu-maçla sıfıra çekilir.
        ham = (30 / ((3 * 30 + 4 * 36) / 7)) / (36 / ((4 * 30 + 3 * 36) / 7)) - 1
        self.assertAlmostEqual(etki[1][0], 4 * ham / (4 + config.FARK_DAKIKA_K))
        self.assertEqual(etki[1][1], 4)
        self.assertLess(etki[1][0], 0)        # ilk beş kaybeder
        self.assertGreater(etki[0][0], 0)     # yedek kazanır

    def test_carpan_ve_oran_onceligi(self):
        veritabani.yaz(self.c, "oranlar", [{"mac_id": "bugun", "tur": "guncel", "cekim_zamani": veritabani.simdi_utc(), "handikap": -14.0, "toplam": 220.0}])
        b = tahmin.Baglam(self.c, "2026-11-20")
        fark, kaynak = fark_riski.beklenen_fark(b, self.mac)
        self.assertEqual((fark, kaynak), (14.0, "oran"))                # ev sahibi 14 sayı favori
        lig = fark_riski.lig_ozeti(b)
        p = fark_riski.buyuk_fark_olasiligi(14.0, lig["sigma"])
        etki = fark_riski.dakika_etkisi(b)
        ilk_bes = fark_riski.hesapla(Oyuncu(10, "İlk Beş", 1, "PG"), self.mac, "sayi", b)
        yedek = fark_riski.hesapla(Oyuncu(11, "Yedek", 1, "SG"), self.mac, "sayi", b)
        self.assertAlmostEqual(ilk_bes.carpan, (1 + p * etki[1][0]) / (1 + lig["p0"] * etki[1][0]))
        self.assertAlmostEqual(yedek.carpan, (1 + p * etki[0][0]) / (1 + lig["p0"] * etki[0][0]))

    def test_oran_yoksa_veri_yok_ya_da_kendi_tahmin(self):
        b = tahmin.Baglam(self.c, "2026-11-20")                         # oran yok, takim_mac yok
        s = fark_riski.hesapla(Oyuncu(10, "İlk Beş", 1, "PG"), self.mac, "sayi", b)
        self.assertEqual((s.carpan, s.veri_var), (1.0, False))
        # Takım kutu skorları varsa kendi fark tahminimiz devreye girer: takım 1 hep kazanmış, beklenen fark artı olmalı.
        veritabani.yaz(self.c, "takim_mac", [
            {"takim_id": t, "mac_id": f"g{i}", "rakip_id": 3 - t, "ev_mi": int(t == 1), "dakika": 240.0, "pozisyon_sayisi": 100.0, "tempo": 98.0}
            for i in range(1, 9) for t in (1, 2)])
        b = tahmin.Baglam(self.c, "2026-11-20")
        fark, kaynak = fark_riski.beklenen_fark(b, self.mac)
        self.assertEqual(kaynak, "kendi tahminimiz")
        self.assertGreater(fark, 5)

    def test_zincirde_dakika_turu_genel_sinirin_disinda(self):
        def dakika(*_):
            return etkenler.EtkenSonucu(0.9, True, 1, "dakika")

        def carpan(*_):
            return etkenler.EtkenSonucu(1.5, True, 1, "çarpan")

        z = etkenler.uygula(None, None, "sayi", None, [("a", dakika, 0.5, 1.5, "dakika"), ("b", carpan, 0.5, 2.0, "carpan")], (0.70, 1.20))
        self.assertAlmostEqual(z.dakika_carpani, 0.9)
        self.assertAlmostEqual(z.carpan, 0.9 * 1.20)


class CizgiTesti(unittest.TestCase):
    def test_takim_beklenen_sayisi(self):
        c = fark_kur()
        veritabani.yaz(c, "takim_mac", [
            {"takim_id": t, "mac_id": f"g{i}", "rakip_id": 3 - t, "ev_mi": int(t == 1), "dakika": 240.0, "pozisyon_sayisi": 100.0, "tempo": 98.0}
            for i in range(1, 9) for t in (1, 2)])
        veritabani.yaz(c, "oranlar", [{"mac_id": "bugun", "tur": "guncel", "cekim_zamani": veritabani.simdi_utc(), "handikap": -6.0, "toplam": 220.0}])
        b = tahmin.Baglam(c, "2026-11-20")
        mac = Mac("bugun", "2026-11-20", 1, 2)
        ev, dep = tempo.cizgi_carpani(b, 1, mac), tempo.cizgi_carpani(b, 2, mac)
        self.assertEqual((ev[1], dep[1]), (113.0, 107.0))               # (220 + 6) / 2 ve (220 − 6) / 2
        # Tempo iki takım için de aynı (98): tempo çarpanı 1. Sayıda çizgiyle yarı yarıya, ribaundda yalnız tempo.
        o = Oyuncu(10, "İlk Beş", 1, "PG")
        self.assertAlmostEqual(tempo.hesapla(o, mac, "sayi", b).carpan, 0.5 * 1.0 + 0.5 * ev[0])
        self.assertAlmostEqual(tempo.hesapla(o, mac, "ribaund", b).carpan, 1.0)
        c.close()


class EksikDakikaTesti(unittest.TestCase):
    def test_onsuz_dakika_farki(self):
        c = test_kullanim.kur()
        # Arkadaş (11): yıldızla 30 dk; yıldızsız maçlarını 36 dk yapalım.
        for i in (4, 5, 6):
            c.execute("UPDATE oyuncu_mac SET dakika = 36.0 WHERE oyuncu_id = 11 AND mac_id = ?", (f"g{i}",))
        c.commit()
        test_kullanim.out_yap(c)
        eski, config.KULLANIM_MIN_MAC = config.KULLANIM_MIN_MAC, 3
        eski_agirlik, config.DAKIKA_SEZON_AGIRLIK = config.DAKIKA_SEZON_AGIRLIK, 0.0     # beklenen dakika: yalnız son 5 maç
        try:
            b = tahmin.Baglam(c, test_kullanim.BUGUN)
            s = eksik_dakika.hesapla(test_kullanim.ARKADAS, test_kullanim.MAC, "sayi", b)
            # Beklenen dakika: son 5 maç (30, 30, 36, 36, 36) = 33,6. Onsuz farkı 6 dk, 3 maçla sıfıra çekilir: 6 × 3 / (3 + k).
            # Son 5 maçın 3'ü zaten yıldızsız: farkın 2/5'i eklenir.
            fark = 3 * 6.0 / (3 + config.ONSUZ_K)
            self.assertAlmostEqual(s.carpan, 1 + fark * (1 - 3 / 5) / 33.6)
            self.assertTrue(s.veri_var)
        finally:
            config.KULLANIM_MIN_MAC, config.DAKIKA_SEZON_AGIRLIK = eski, eski_agirlik
            c.close()


class DonusTesti(unittest.TestCase):
    def kur(self, oynadigi):
        """Takım 1'in 10 maçı var; oyuncu 10 verilen sıra numaralı maçlarda 30'ar dk oynamış."""
        c = veritabani.baglan(":memory:")
        veritabani.sema_kur(c)
        veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
        veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "Dönen", "takim_id": 1, "pozisyon": "PG"}])
        veritabani.yaz(c, "maclar", [{"mac_id": f"g{i:02d}", "tarih": f"2026-11-{i:02d}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"} for i in range(1, 11)])
        veritabani.yaz(c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": f"g{i:02d}", "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "ilk_bes": 1, "dakika": dk,
                                           "sayi": 10, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0} for i, dk in oynadigi.items()])
        return c

    def durum(self, oynadigi):
        c = self.kur(oynadigi)
        b = tahmin.Baglam(c, "2026-11-20")
        sonuc = donus.donus_durumu(b, Oyuncu(10, "Dönen", 1, "PG")), donus.hesapla(Oyuncu(10, "Dönen", 1, "PG"), Mac("x", "2026-11-20", 1, 2), "sayi", b), donus.donus_etkisi(b)
        c.close()
        return sonuc

    def test_donus_durumu(self):
        otuz = lambda *maclar: {i: 30.0 for i in maclar}
        self.assertIsNone(self.durum(otuz(*range(1, 11)))[0])                    # hiç maç kaçırmamış
        self.assertEqual(self.durum(otuz(1, 2, 3, 4, 5, 6, 7))[0], (1, 3))       # son 3 maçı kaçırdı: bugün ilk maçı
        self.assertIsNone(self.durum(otuz(1, 2, 3, 4, 5, 6, 7, 8))[0])           # 2 maç kaçırdı: sayılmaz
        self.assertEqual(self.durum(otuz(1, 2, 3, 4, 5, 6, 10))[0], (2, 3))      # 3 maç kaçırıp son maçta döndü: bugün ikinci maçı
        self.assertIsNone(self.durum(otuz(1, 2, 3, 4, 5, 9, 10))[0])             # dönüşün üstünden 2 maç geçti

    def test_donus_etkisi_ogrenilir(self):
        # 1–5. maçlarda 30 dk, 3 maç ara, 9. ve 10. maçlarda 20'şer dk: dönüş maçlarında %33 az.
        durum, sonuc, (etki, n, ham) = self.durum({1: 30.0, 2: 30.0, 3: 30.0, 4: 30.0, 5: 30.0, 9: 20.0, 10: 20.0})
        self.assertIsNone(durum)                                                 # bugün üçüncü maçı: kısıt yok
        self.assertEqual(sonuc.carpan, 1.0)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(ham, 20 / 30 - 1)
        self.assertAlmostEqual(etki, (2 * ham + config.DONUS_K * -config.DONUS_KAYBI_BASLANGIC) / (2 + config.DONUS_K))


if __name__ == "__main__":
    unittest.main()
