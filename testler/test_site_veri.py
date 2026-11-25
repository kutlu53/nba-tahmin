"""Web sayfası verisi: günün üst / alt seçimleri ve geçmişte sonuçlarıyla gösterilmesi. Ağa ve veritabanına çıkmaz."""
import unittest

import pandas as pd

import config
import site_veri

ISTATISTIKLER = ("sayi", "ribaund", "asist", "ucluk", "sayi+ribaund+asist")


def satirlar(kimlik, isim, mac_id, tahmin, sezon, gercek, dakika=30.0):
    """Bir oyuncunun tahmin satırları; tahmin / sezon / gercek: istatistik -> değer (gercek None ise oynamadı)."""
    return [{"oyuncu_id": kimlik, "mac_id": mac_id, "istatistik": ist, "tahmin": tahmin[ist], "ust": tahmin[ist] * 1.5, "guven": 90.0,
             "sezon_ort": sezon.get(ist), "gerceklesen": None if gercek is None else gercek[ist], "dakika": dakika,
             "isim": isim, "takim": "AAA", "mac": "BBB @ AAA"} for ist in ISTATISTIKLER]


def ornek():
    sezon = {"sayi": 20.2, "ribaund": 6.4, "asist": 5.3, "ucluk": 2.1}
    yuksek = {"sayi": 27.0, "ribaund": 6.5, "asist": 5.5, "ucluk": 2.5, "sayi+ribaund+asist": 39.0}        # sayıda belirgin üst
    dusuk = {"sayi": 13.0, "ribaund": 6.5, "asist": 5.5, "ucluk": 2.5, "sayi+ribaund+asist": 25.0}         # sayıda belirgin alt
    oynadi = {"sayi": 30, "ribaund": 7, "asist": 5, "ucluk": 3, "sayi+ribaund+asist": 42}
    return pd.DataFrame(satirlar(1, "Oynayan Oyuncu", "M1", yuksek, sezon, oynadi)
                        + satirlar(2, "Oynamayan Oyuncu", "M1", dusuk, sezon, None)
                        + satirlar(3, "Baska Mac", "M2", dusuk, sezon, None))


class UstAltSecimTesti(unittest.TestCase):
    def test_puanli_secimler_gosterilenlerle_ayni(self):
        df = ornek()
        gosterilen = site_veri.ust_alt_secimleri(df)
        sonuclu = site_veri.ust_alt_secimleri(df, puanli=True)
        anahtar = lambda x: (x["oyuncu"], x["ist"], x["cizgi"], x["taraf"], x["olasilik"])
        self.assertEqual([anahtar(x) for x in gosterilen], [anahtar(x) for x in sonuclu])
        self.assertTrue(gosterilen and all("tuttu" not in x for x in gosterilen))

    def test_sonuc_alanlari(self):
        s = {x["oyuncu"]: x for x in site_veri.ust_alt_secimleri(ornek(), puanli=True)}
        self.assertEqual(set(s), {"Oynayan Oyuncu", "Oynamayan Oyuncu", "Baska Mac"})
        oynayan = s["Oynayan Oyuncu"]
        self.assertEqual((oynayan["taraf"], oynayan["tuttu"], oynayan["bitti"]), ("ust", 1, True))
        self.assertGreater(oynayan["gercek"], oynayan["cizgi"])
        # Maçı sonuçlanmış ama oynamamış: sonuç yok, maç bitti. Maçı henüz sonuçlanmamış: sonuç yok, maç bitmedi.
        self.assertEqual([(s[k]["gercek"], s[k]["tuttu"], s[k]["bitti"]) for k in ("Oynamayan Oyuncu", "Baska Mac")],
                         [(None, None, True), (None, None, False)])

    def test_yalniz_oynayanlar(self):
        s = site_veri.ust_alt_secimleri(ornek(), puanli=True, yalniz_oynayanlar=True)
        self.assertEqual({x["oyuncu"] for x in s}, {"Oynayan Oyuncu"})

    def test_cizgi_sezon_ortalamasindan(self):
        s = site_veri.ust_alt_secimleri(ornek())
        self.assertTrue(all(x["cizgi"] == {"sayi": 20.5, "sayi+ribaund+asist": 31.5}.get(x["ist"], x["cizgi"]) for x in s))
        self.assertTrue(all(x["olasilik"] >= 100 * site_veri.UA_MIN_OLASILIK for x in s))


def kolay_barem():
    """Üçlük baremi kendiliğinden kolay (ortalama 2,05, barem 2,5); model yalnızca sayıda sezon ortalamasından ayrılıyor."""
    sezon = {"sayi": 20.2, "ribaund": 6.4, "asist": 5.3, "ucluk": 2.05}
    tahmin = {"sayi": 19.0, "ribaund": 6.4, "asist": 5.3, "ucluk": 2.05, "sayi+ribaund+asist": 30.7}       # sayı alt %62, üçlük alt %66
    return pd.DataFrame(satirlar(1, "Oyuncu", "M1", tahmin, sezon, None))


class SiralamaTesti(unittest.TestCase):
    def test_eski_kural_en_yuksek_olasilik(self):
        s = site_veri.ust_alt_secimleri(kolay_barem(), fark_sirasi=False)
        self.assertEqual([(x["ist"], x["taraf"]) for x in s], [("ucluk", "alt")])
        self.assertEqual(s[0]["fark"], 0)                     # model üçlükte sezon ortalamasına hiçbir şey katmıyor

    def test_fark_sirasi_modelin_ayrildigi_istatistigi_secer(self):
        s = site_veri.ust_alt_secimleri(kolay_barem())
        self.assertEqual([(x["ist"], x["taraf"]) for x in s], [("sayi", "alt")])
        self.assertGreater(s[0]["fark"], 0)
        self.assertGreaterEqual(s[0]["olasilik"], 100 * site_veri.UA_MIN_OLASILIK)

    def test_farki_olmayan_aday_alinmaz(self):
        df = kolay_barem()
        df.loc[df["istatistik"].isin(["sayi", "sayi+ribaund+asist"]), "tahmin"] = [20.2, 31.9]      # model hiçbir istatistikte ayrılmıyor
        df["ust"] = df["tahmin"] * 1.5
        self.assertEqual(site_veri.ust_alt_secimleri(df), [])
        self.assertEqual(len(site_veri.ust_alt_secimleri(df, fark_sirasi=False)), 1)

    def test_baslangic_tarihi(self):
        once = "2026-11-24"
        self.assertLess(once, site_veri.UA_FARK_BASLANGIC)
        self.assertFalse(site_veri.fark_sirasi_mi(once, "canli"))                    # yayımlandığı kuralla kalır
        self.assertTrue(site_veri.fark_sirasi_mi(site_veri.UA_FARK_BASLANGIC, "canli"))
        self.assertTrue(site_veri.fark_sirasi_mi(once, "geri_test"))

    def test_barem_olasiligi_tahminden_bagimsiz(self):
        # Tahmin sezon ortalamasına eşitse baremin verdiği olasılık modelin olasılığıdır.
        self.assertAlmostEqual(site_veri.barem_olasiligi(2.05, 2.05, 0.8, 2.5), site_veri.ust_alt.ust_olasiligi(2.05, 0.8, 2.5))
        self.assertLess(site_veri.barem_olasiligi(2.05, 2.05, 0.8, 2.5), 0.42)       # yani alt en az %58: barem kendiliğinden kolay


if __name__ == "__main__":
    unittest.main()
