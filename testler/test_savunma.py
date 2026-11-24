"""Savunma profili hesabı: küçük, elle doğrulanabilir bir veri tabanı üzerinde."""
import unittest

import config
import savunma
import veritabani


def kur():
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2, 3)])
    veritabani.yaz(c, "oyuncular", [
        {"oyuncu_id": 11, "isim": "PG bir", "takim_id": 1, "pozisyon": "PG"},
        {"oyuncu_id": 12, "isim": "PG iki", "takim_id": 2, "pozisyon": "PG"},
        {"oyuncu_id": 13, "isim": "Pozisyonsuz", "takim_id": 1, "pozisyon": None},
    ])
    veritabani.yaz(c, "maclar", [
        {"mac_id": "m1", "tarih": "2026-11-01", "ev_takim_id": 3, "dep_takim_id": 1, "durum": "oynandi"},
        {"mac_id": "m2", "tarih": "2026-11-02", "ev_takim_id": 3, "dep_takim_id": 2, "durum": "oynandi"},
        {"mac_id": "m3", "tarih": "2026-11-03", "ev_takim_id": 2, "dep_takim_id": 1, "durum": "oynandi"},
        {"mac_id": "m4", "tarih": "2026-11-05", "ev_takim_id": 3, "dep_takim_id": 1, "durum": "oynandi"},
    ])

    def kayit(oyuncu, mac, takim, rakip, dakika, sayi):
        return {"oyuncu_id": oyuncu, "mac_id": mac, "takim_id": takim, "rakip_id": rakip, "ev_mi": 0, "dakika": dakika,
                "sayi": sayi, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}

    veritabani.yaz(c, "oyuncu_mac", [
        kayit(11, "m1", 1, 3, 30.0, 30),   # takım 3'e karşı
        kayit(12, "m2", 2, 3, 20.0, 10),   # takım 3'e karşı
        kayit(11, "m3", 1, 2, 40.0, 20),   # takım 2'ye karşı
        kayit(13, "m1", 1, 3, 30.0, 99),   # pozisyonu yok: sayılmaz
        kayit(12, "m3", 2, 1, 9.9, 50),    # 10 dakikanın altı: sayılmaz
        kayit(11, "m4", 1, 3, 30.0, 60),   # 5 Kasım: 5 Kasım hesabına girmez
    ])
    return c


class SavunmaTesti(unittest.TestCase):
    def setUp(self):
        self.c = kur()

    def tearDown(self):
        self.c.close()

    def sayi(self, tarih):
        return {s["takim_id"]: s for s in savunma.profil_hesapla(self.c, tarih) if s["istatistik"] == "sayi" and s["pozisyon"] == "PG"}

    def test_oran_dakika_agirlikli_ve_tarih_oncesi(self):
        p = self.sayi("2026-11-05")
        # Takım 3: (30 + 10) sayı / 50 dk; takım 2: 20 sayı / 40 dk; lig: 60 sayı / 90 dk.
        self.assertEqual(set(p), {2, 3})
        self.assertAlmostEqual(p[3]["verilen_ort"], 36 * 40 / 50)
        self.assertAlmostEqual(p[2]["verilen_ort"], 36 * 20 / 40)
        self.assertAlmostEqual(p[3]["lig_ort"], 36 * 60 / 90)
        self.assertAlmostEqual(p[3]["oran"], (40 / 50) / (60 / 90))
        self.assertAlmostEqual(p[2]["oran"], (20 / 40) / (60 / 90))
        self.assertEqual((p[3]["mac_sayisi"], p[2]["mac_sayisi"]), (2, 1))

    def test_kucuk_orneklem_duzeltmesi_ve_sira(self):
        p = self.sayi("2026-11-05")
        k = config.KUCUK_ORNEKLEM_K
        self.assertAlmostEqual(p[3]["duzeltilmis_oran"], (2 * p[3]["oran"] + k) / (2 + k))
        self.assertAlmostEqual(p[2]["duzeltilmis_oran"], (1 * p[2]["oran"] + k) / (1 + k))
        self.assertEqual((p[2]["sira"], p[3]["sira"]), (1, 2))  # 1 = en az veren

    def test_sonraki_maclar_hesaba_sizmaz(self):
        once = self.sayi("2026-11-05")[3]
        sonra = self.sayi("2026-11-06")[3]
        self.assertEqual(once["mac_sayisi"], 2)
        self.assertEqual(sonra["mac_sayisi"], 3)
        self.assertGreater(sonra["verilen_ort"], once["verilen_ort"])
        self.assertEqual(savunma.profil_hesapla(self.c, "2026-11-01"), [])  # sezonun ilk günü: veri yok

    def test_beklenene_gore_oran(self):
        p = self.sayi("2026-11-05")
        k = config.ESLESME_K_DAKIKA
        # Takım 2'ye karşı: oyuncu 11, 40 dk'da 20 sayı. Diğer maçı (m1): 30 dk'da 30 sayı -> beklenen 40 sayı.
        self.assertAlmostEqual(p[2]["beklenene_gore_oran"], 20 / 40)
        self.assertAlmostEqual(p[2]["oyuncu_dakika"], 40.0)
        self.assertAlmostEqual(p[2]["beklenene_gore_duzeltilmis"], (40 * 0.5 + k) / (40 + k))
        # Takım 3'e karşı: oyuncu 11 (30 dk, 30 sayı; beklenen 30 × 20/40 = 15) ve oyuncu 12 (20 dk, 10 sayı;
        # beklenen 20 × 50/9,9; 10 dakikanın altındaki maçı da kendi üretim hızına girer).
        self.assertAlmostEqual(p[3]["beklenene_gore_oran"], (30 + 10) / (15 + 20 * 50 / 9.9))
        self.assertAlmostEqual(p[3]["oyuncu_dakika"], 50.0)
        self.assertEqual((p[3]["beklenene_gore_sira"], p[2]["beklenene_gore_sira"]), (1, 2))

    def test_beklenen_uretim_tempoya_gore_olceklenir(self):
        # m1 hızlı (110), m3 yavaş (90) oynanmış olsun; ortalama 100.
        veritabani.yaz(self.c, "takim_mac", [
            {"takim_id": t, "mac_id": m, "rakip_id": r, "ev_mi": e, "dakika": 240.0, "tempo": hiz}
            for m, hiz, (t, r, e) in (("m1", 110.0, (1, 3, 0)), ("m1", 110.0, (3, 1, 1)), ("m3", 90.0, (1, 2, 0)), ("m3", 90.0, (2, 1, 1)))])
        p = self.sayi("2026-11-05")
        # Oyuncu 11: m1'de 30 dk × 1,1 = 33 "tempolu dakika"da 30 sayı. m3'te 40 dk × 0,9 = 36 tempolu dakika:
        # beklenen 36 × 30/33. Yavaş maçta beklenti düştüğü için oran, tempoyu saymayan 0,50'den yüksek çıkar.
        self.assertAlmostEqual(p[2]["beklenene_gore_oran"], 20 / (36 * 30 / 33))
        self.assertGreater(p[2]["beklenene_gore_oran"], 0.5)
        self.assertAlmostEqual(p[2]["oran"], (20 / 40) / (60 / 90))     # ham oran tempodan etkilenmez

    def test_iki_kez_yazinca_cogalmaz(self):
        n1 = savunma.profili_yaz(self.c, "2026-11-05")
        n2 = savunma.profili_yaz(self.c, "2026-11-05")
        self.assertEqual(n1, n2)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM savunma_profili").fetchone()[0], n1)


if __name__ == "__main__":
    unittest.main()
