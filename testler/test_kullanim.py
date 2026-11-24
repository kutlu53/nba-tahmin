"""Kullanım oranı ve "onsuz" etkeni: elle hesaplanmış örnek. Ağa çıkmaz."""
import unittest

import config
import tahmin
import veritabani
import yukle
from etkenler import Mac, Oyuncu, kullanim

BUGUN = "2026-11-20"


def kur():
    """Takım 1: yıldız (10) ilk 3 maçta oynar, sonraki 3 maçı kaçırır. Oyuncu 11 altı maçta da 30 dk oynar:
    yıldızla 10'ar sayı, yıldızsız 20'şer sayı; ribaundu hep 5."""
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
    veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "Yıldız", "takim_id": 1, "pozisyon": "PG"},
                                    {"oyuncu_id": 11, "isim": "Arkadaş", "takim_id": 1, "pozisyon": "SG"}])
    veritabani.yaz(c, "maclar", [{"mac_id": f"g{i}", "tarih": f"2026-11-{i:02d}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"} for i in range(1, 7)]
                   + [{"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])

    def kayit(oyuncu, i, dakika, sayi, kul):
        return {"oyuncu_id": oyuncu, "mac_id": f"g{i}", "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "ilk_bes": 1, "dakika": dakika, "sayi": sayi,
                "ribaund": 5, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0, "kullanim": kul}

    veritabani.yaz(c, "oyuncu_mac", [kayit(10, i, 36.0, 30, 30.0) for i in (1, 2, 3)]
                   + [kayit(11, i, 30.0, 10, 15.0) for i in (1, 2, 3)] + [kayit(11, i, 30.0, 20, 25.0) for i in (4, 5, 6)])
    return c


def out_yap(c, tarih=BUGUN):
    veritabani.goruntu_yaz(c, "sakatliklar", {"kaynak": "espn", "cekim_tarihi": tarih}, [
        {"oyuncu_anahtari": "10", "cekim_zamani": veritabani.simdi_utc(), "oyuncu_id": 10, "isim": "Yıldız", "takim_id": 1,
         "durum": "Out", "aciklama": None, "tahmini_donus": None}])


ARKADAS = Oyuncu(11, "Arkadaş", 1, "SG")
MAC = Mac("bugun", BUGUN, 1, 2)
GENEL = 1.0 + (36.0 / 48.0) * ((100.0 - 20.0) / (100.0 - 30.0) - 1.0)     # yıldız: %30 kullanım, 36 dk -> ≈ 1,107


class KullanimOraniTesti(unittest.TestCase):
    def test_kullanim_orani_formulu(self):
        c = kur()
        veritabani.yaz(c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": "g1", "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "dakika": 24.0,
                                           "saha_ici_deneme": 10, "serbest_deneme": 5, "top_kaybi": 2}])
        veritabani.yaz(c, "takim_mac", [{"takim_id": 1, "mac_id": "g1", "rakip_id": 2, "ev_mi": 1, "dakika": 240.0,
                                          "saha_ici_deneme": 80, "serbest_deneme": 20, "top_kaybi": 12}])
        yukle.kullanim_oranlarini_yaz(c)
        deger = c.execute("SELECT kullanim FROM oyuncu_mac WHERE oyuncu_id = 10 AND mac_id = 'g1'").fetchone()[0]
        # 100 × (10 + 0,44 × 5 + 2) × (240 / 5) / (24 × (80 + 0,44 × 20 + 12))
        self.assertAlmostEqual(deger, 100 * 14.2 * 48 / (24 * 100.8))
        c.close()


class OnsuzTesti(unittest.TestCase):
    def setUp(self):
        self.c = kur()

    def tearDown(self):
        self.c.close()

    def test_onemli_oyuncu_ve_onsuz_verisi(self):
        b = tahmin.Baglam(self.c, BUGUN)
        onemli = kullanim.onemli_oyuncular(b, 1)
        self.assertNotIn(10, onemli)                                   # yıldızın yalnızca 3 maçı var: KULLANIM_MIN_MAC altında
        config_min, config.KULLANIM_MIN_MAC = config.KULLANIM_MIN_MAC, 3
        try:
            b = tahmin.Baglam(self.c, BUGUN)
            self.assertEqual(set(kullanim.onemli_oyuncular(b, 1)), {10, 11})   # 11 de maç başına 30 dk ile önemli
            v = kullanim.onsuz(b, 11, 1, 10)
            self.assertEqual((v["onunla_mac"], v["onsuz_mac"]), (3, 3))
            self.assertEqual(v["oran"]["sayi"], (12.0, 24.0))          # 30 dk'da 10 ve 20 sayı
            self.assertEqual(v["kullanim"], (15.0, 25.0))
            # Temel oranda onsuz maçların payı: sezon 3/6, son 10 3/6, son 5 3/5.
            self.assertAlmostEqual(v["temelde_onsuz"], 0.40 * 0.5 + 0.35 * 0.5 + 0.25 * 0.6)
        finally:
            config.KULLANIM_MIN_MAC = config_min

    def test_carpan_elle_hesap(self):
        config_min, config.KULLANIM_MIN_MAC = config.KULLANIM_MIN_MAC, 3
        try:
            out_yap(self.c)
            b = tahmin.Baglam(self.c, BUGUN)
            sayi = kullanim.hesapla(ARKADAS, MAC, "sayi", b)
            duzeltilmis = (3 * 2.0 + config.ONSUZ_K * GENEL) / (3 + config.ONSUZ_K)    # onsuz/onunla = 24/12, 3 maç
            temelde = 0.40 * 0.5 + 0.35 * 0.5 + 0.25 * 0.6
            self.assertAlmostEqual(sayi.carpan, duzeltilmis / (1 + temelde * (duzeltilmis - 1)))
            self.assertEqual((sayi.veri_var, sayi.orneklem), (True, 3))
            ribaund = kullanim.hesapla(ARKADAS, MAC, "ribaund", b)
            self.assertAlmostEqual(ribaund.carpan, 1.0)                # ribaund değişmemiş, nötr değeri de 1
        finally:
            config.KULLANIM_MIN_MAC = config_min

    def test_onsuz_mac_azsa_genel_dagitim(self):
        config_min, config.KULLANIM_MIN_MAC = config.KULLANIM_MIN_MAC, 3
        try:
            out_yap(self.c, "2026-11-06")                              # 6 Kasım sabahı: yıldız yalnızca 2 maç kaçırmış
            b = tahmin.Baglam(self.c, "2026-11-06")
            s = kullanim.hesapla(ARKADAS, Mac("g6", "2026-11-06", 1, 2), "sayi", b)
            temelde = kullanim.onsuz(b, 11, 1, 10)["temelde_onsuz"]
            self.assertAlmostEqual(s.carpan, GENEL / (1 + temelde * (GENEL - 1)))
            self.assertEqual(s.orneklem, 0)
            self.assertIn("genel dağıtım", s.aciklama)
            self.assertEqual(kullanim.hesapla(ARKADAS, Mac("g6", "2026-11-06", 1, 2), "blok", b).carpan, 1.0)
        finally:
            config.KULLANIM_MIN_MAC = config_min

    def test_eksik_yoksa_ve_veri_yoksa(self):
        b = tahmin.Baglam(self.c, BUGUN)                               # sakatlık görüntüsü yok
        s = kullanim.hesapla(ARKADAS, MAC, "sayi", b)
        self.assertEqual((s.carpan, s.veri_var), (1.0, False))
        veritabani.goruntu_yaz(self.c, "sakatliklar", {"kaynak": "espn", "cekim_tarihi": BUGUN}, [
            {"oyuncu_anahtari": "x", "cekim_zamani": veritabani.simdi_utc(), "oyuncu_id": None, "isim": "Kadroda olmayan biri", "takim_id": 1,
             "durum": "Out", "aciklama": None, "tahmini_donus": None}])
        s = kullanim.hesapla(ARKADAS, MAC, "sayi", tahmin.Baglam(self.c, BUGUN))
        self.assertEqual((s.carpan, s.veri_var), (1.0, True))          # veri var, eksik önemli arkadaş yok

    def test_tablo_satirlari(self):
        config_min, config.KULLANIM_MIN_MAC = config.KULLANIM_MIN_MAC, 3
        try:
            b = tahmin.Baglam(self.c, BUGUN)
            for _ in range(2):
                n = kullanim.tabloyu_yaz(self.c, b, BUGUN)
            self.assertEqual(self.c.execute("SELECT COUNT(*) FROM onsuz_etkisi").fetchone()[0], n)
            s = self.c.execute("SELECT * FROM onsuz_etkisi WHERE oyuncu_id = 11 AND arkadas_id = 10 AND istatistik = 'sayi'").fetchone()
            self.assertEqual((s["onunla_36"], s["onsuz_36"], s["onunla_mac"], s["onsuz_mac"]), (12.0, 24.0, 3, 3))
        finally:
            config.KULLANIM_MIN_MAC = config_min


if __name__ == "__main__":
    unittest.main()
