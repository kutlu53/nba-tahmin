"""Şut düzeltmesi: elle hesaplanmış yüzdeler, sayının ayrışması ve genel sınırın dışında kalması."""
import unittest

import config
import etkenler
import tahmin
import veritabani
from etkenler import Mac, Oyuncu, sut_duzeltme

BUGUN = "2026-11-10"


def kur(gecen_sezon=True):
    """Oyuncu 10 (PG): 3 maç, her biri 30 dk; toplam 2'lik 12/20, 3'lük 9/15 (sıcak seri), serbest atış 6/10.

    Sayı = 2 × 12 + 3 × 9 + 6 = 57. Geçen sezon: 3'lük 100/300, 2'lik 200/400, serbest 150/200.
    Oyuncu 20 (PG): lig ortalamasını belirleyen ikinci oyuncu; 3'lük 3/15, 2'lik 8/20, serbest 9/10.
    """
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
    veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "Sıcak Şutör", "takim_id": 1, "pozisyon": "PG"},
                                    {"oyuncu_id": 20, "isim": "Diğer", "takim_id": 2, "pozisyon": "PG"}])
    veritabani.yaz(c, "maclar", [{"mac_id": f"g{i}", "tarih": f"2026-11-0{i}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"} for i in (1, 2, 3)]
                   + [{"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])

    def kayit(oyuncu, mac, takim, rakip, iki, uc, sa):
        (im, ia), (um, ua), (sm, sd) = iki, uc, sa
        return {"oyuncu_id": oyuncu, "mac_id": mac, "takim_id": takim, "rakip_id": rakip, "ev_mi": int(takim == 1), "ilk_bes": 1, "dakika": 30.0,
                "sayi": 2 * im + 3 * um + sm, "ribaund": 0, "asist": 0, "ucluk": um, "top_calma": 0, "blok": 0, "top_kaybi": 0,
                "saha_ici_isabet": im + um, "saha_ici_deneme": ia + ua, "ucluk_deneme": ua, "serbest_isabet": sm, "serbest_deneme": sd}

    veritabani.yaz(c, "oyuncu_mac", [
        kayit(10, "g1", 1, 2, (4, 6), (3, 5), (2, 4)), kayit(10, "g2", 1, 2, (4, 7), (3, 5), (2, 3)), kayit(10, "g3", 1, 2, (4, 7), (3, 5), (2, 3)),
        kayit(20, "g1", 2, 1, (3, 7), (1, 5), (3, 4)), kayit(20, "g2", 2, 1, (3, 7), (1, 5), (3, 3)), kayit(20, "g3", 2, 1, (2, 6), (1, 5), (3, 3)),
    ])
    if gecen_sezon:
        veritabani.yaz(c, "oyuncu_sezon", [{"oyuncu_id": 10, "sezon": config.ONCEKI_SEZON, "mac_sayisi": 70, "dakika": 2100.0, "sayi": 0, "ucluk": 100,
                                            "saha_ici_isabet": 300, "saha_ici_deneme": 700, "ucluk_deneme": 300, "serbest_isabet": 150, "serbest_deneme": 200}])
    return c


OYUNCU = Oyuncu(10, "Sıcak Şutör", 1, "PG")
MAC = Mac("bugun", BUGUN, 1, 2)
LIG_UC = (9 + 3) / 30          # iki oyuncunun toplamı: 12/30


class SutDuzeltmeTesti(unittest.TestCase):
    def test_yuzdeler_elle_hesap(self):
        c = kur()
        y = sut_duzeltme.yuzdeler(tahmin.Baglam(c, BUGUN), OYUNCU)
        self.assertAlmostEqual(y["ucluk"]["guncel"], 9 / 15)
        # Ön yüzde: geçen sezon 100/300, pozisyon ortalamasına (12/30) 100 denemelik ağırlıkla çekilir.
        on = (100 + config.ON_YUZDE_K["ucluk"] * LIG_UC) / (300 + config.ON_YUZDE_K["ucluk"])
        self.assertAlmostEqual(y["ucluk"]["on"], on)
        # Düzeltilmiş: 9/15'lik sıcak seri, 300 denemelik ağırlıkla ön yüzdeye çekilir.
        self.assertAlmostEqual(y["ucluk"]["duzeltilmis"], (9 + config.SUT_K["ucluk"] * on) / (15 + config.SUT_K["ucluk"]))
        self.assertLess(y["ucluk"]["duzeltilmis"], 0.40)
        self.assertAlmostEqual(y["iki"]["guncel"], 12 / 20)
        self.assertAlmostEqual(y["serbest"]["guncel"], 6 / 10)
        c.close()

    def test_gecen_sezonu_olmayan_oyuncu_pozisyon_ortalamasina_cekilir(self):
        c = kur(gecen_sezon=False)
        y = sut_duzeltme.yuzdeler(tahmin.Baglam(c, BUGUN), OYUNCU)
        self.assertAlmostEqual(y["ucluk"]["on"], LIG_UC)
        self.assertEqual(y["ucluk"]["gecen_deneme"], 0)
        c.close()

    def test_sayi_bilesenlerin_toplami_ve_ucluk_tutarli(self):
        c = kur()
        b = tahmin.Baglam(c, BUGUN)
        y, a = sut_duzeltme.yuzdeler(b, OYUNCU), sut_duzeltme.ayristir(b, OYUNCU)
        # 90 dakikada 20 / 15 / 10 deneme: 36 dk başına 8 / 6 / 4 (üç pencere de aynı üç maç).
        self.assertAlmostEqual(a["deneme"]["iki"], 8.0)
        self.assertAlmostEqual(a["deneme"]["ucluk"], 6.0)
        self.assertAlmostEqual(a["deneme"]["serbest"], 4.0)
        beklenen_sayi = 2 * 8 * y["iki"]["duzeltilmis"] + 3 * 6 * y["ucluk"]["duzeltilmis"] + 4 * y["serbest"]["duzeltilmis"]
        self.assertAlmostEqual(a["sayi"], beklenen_sayi)

        ayar = {"sut_duzeltme": config.ETKENLER["sut_duzeltme"]}
        t = {s["istatistik"]: s for s in tahmin.oyuncu_tahmini(b, OYUNCU, MAC, etkenler.acik_etkenler(ayar))}
        # 30 dakika bekleniyor: tahmin = 30/36 × 36 dk başına ayrıştırılmış üretim.
        self.assertAlmostEqual(t["sayi"]["tahmin"], 30 / 36 * beklenen_sayi)
        self.assertAlmostEqual(t["ucluk"]["tahmin"], 30 / 36 * 6 * y["ucluk"]["duzeltilmis"])
        self.assertLess(t["sayi"]["tahmin"], 19.0)                    # ham ortalama 57 / 3 = 19 sayı; sıcak seri törpülendi
        self.assertEqual(t["ribaund"]["zincir"].etkenler["sut_duzeltme"].carpan, 1.0)   # diğer istatistikleri etkilemez
        c.close()

    def test_genel_carpan_sinirinin_disinda(self):
        def temel(*_):
            return etkenler.EtkenSonucu(2.0, True, 1, "temel oranı ikiye katlar")

        def carpan(*_):
            return etkenler.EtkenSonucu(1.2, True, 1, "çarpan")

        z = etkenler.uygula(OYUNCU, MAC, "sayi", None, [("a", temel, 0.4, 2.5, "temel"), ("b", carpan, 0.5, 2.0, "carpan"), ("c", carpan, 0.5, 2.0, "carpan")], (0.70, 1.30))
        self.assertAlmostEqual(z.carpan, 2.0 * 1.30)                  # 1,2 × 1,2 = 1,44 genel sınıra takılır; temel etken takılmaz
        self.assertAlmostEqual(z.ham_carpan, 2.0 * 1.44)


if __name__ == "__main__":
    unittest.main()
