"""Tahmin motoru: elle hesaplanmış küçük bir örnek, etken aç/kapa, referansla eşdeğerlik, yazım."""
import logging
import unittest

import config
import etkenler
import tahmin
import veritabani
from etkenler import Mac, Oyuncu
from testler.referans_tahmin import ESKI_ETKENLER, karsilastir, referans_tahmin

# Elle hesaplanmış örnekler PLAN bölüm 6'daki dört etkenle (ham eşleşme dahil) çalışır.
ESKI_AYAR = {ad: {**a, "acik": ad in ESKI_ETKENLER} for ad, a in config.ETKENLER.items()}

BUGUN = "2026-11-10"


def kur():
    """Takım 1 (oyuncumuzun takımı) bugün takım 2'ye deplasmana gidiyor.

    Oyuncu 10 (PG, takım 1): 3 maç -> 30 dk 20 sayı (ev), 30 dk 10 sayı (takım 2'ye deplasman), 40 dk 30 sayı (ev).
    Oyuncu 20 (PG, takım 3): takım 1'e deplasmanda iki maç, 30'ar dk 15'er sayı (lig ortalaması için).
    """
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2, 3)])
    veritabani.yaz(c, "oyuncular", [
        {"oyuncu_id": 10, "isim": "Bizim Oyuncu", "takim_id": 1, "pozisyon": "PG"},
        {"oyuncu_id": 20, "isim": "Rakip Oyuncu", "takim_id": 3, "pozisyon": "PG"},
        {"oyuncu_id": 30, "isim": "Sakat Arkadas", "takim_id": 1, "pozisyon": "SF"},
    ])
    veritabani.yaz(c, "maclar", [
        {"mac_id": "g1", "tarih": "2026-11-01", "ev_takim_id": 1, "dep_takim_id": 3, "durum": "oynandi"},
        {"mac_id": "g2", "tarih": "2026-11-03", "ev_takim_id": 2, "dep_takim_id": 1, "durum": "oynandi"},
        {"mac_id": "g3", "tarih": "2026-11-05", "ev_takim_id": 1, "dep_takim_id": 3, "durum": "oynandi"},
        {"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 2, "dep_takim_id": 1, "durum": "oynanacak"},
    ])

    def kayit(oyuncu, mac, takim, rakip, ev_mi, dakika, sayi, ilk_bes=1):
        return {"oyuncu_id": oyuncu, "mac_id": mac, "takim_id": takim, "rakip_id": rakip, "ev_mi": ev_mi, "ilk_bes": ilk_bes,
                "dakika": dakika, "sayi": sayi, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}

    veritabani.yaz(c, "oyuncu_mac", [
        kayit(10, "g1", 1, 3, 1, 30.0, 20), kayit(10, "g2", 1, 2, 0, 30.0, 10), kayit(10, "g3", 1, 3, 1, 40.0, 30),
        kayit(20, "g1", 3, 1, 0, 30.0, 15), kayit(20, "g3", 3, 1, 0, 30.0, 15),
        kayit(30, "g1", 1, 3, 1, 24.0, 8), kayit(30, "g2", 1, 2, 0, 24.0, 8), kayit(30, "g3", 1, 3, 1, 24.0, 8),
    ])
    return c


OYUNCU = Oyuncu(10, "Bizim Oyuncu", 1, "PG")
MAC = Mac("bugun", BUGUN, 2, 1)

# Elle hesap (yalnızca PG kayıtları ve 10 dk üstü): takım 2'nin PG'lere verdiği 10 sayı / 30 dk;
# lig PG ortalaması (60 + 30) sayı / (100 + 60) dk; takım 2'nin 1 maçı var, k = 10.
TEMEL = (100 / 3) * (36 * 60 / 100) / 36                               # = 20 sayı
ESLESME = (1 * ((10 / 30) / (90 / 160)) + 10) / 11                      # ≈ 0,963
# Deplasman: oyuncunun oranı (10/30) / (60/100), 1 maç; lig deplasman oranı sakat arkadaş dahil tüm kayıtlardan:
# deplasman (10 + 15 + 15 + 8) / (30 + 30 + 30 + 24), genel (60 + 30 + 24) / (100 + 60 + 72); k = 20 -> alt sınır 0,95'e takılır.
EV_DEPLASMAN = 0.95


class TahminTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.c.close()

    def sayi(self, ayarlar=None):
        baglam = tahmin.Baglam(self.c, BUGUN)
        satirlar = tahmin.oyuncu_tahmini(baglam, OYUNCU, MAC, etkenler.acik_etkenler(ESKI_AYAR if ayarlar is None else ayarlar))
        return next(s for s in satirlar if s["istatistik"] == "sayi")

    def test_etkenler_kapaliyken_temel_tahmin(self):
        kapali = {ad: {**a, "acik": False} for ad, a in config.ETKENLER.items()}
        s = self.sayi(kapali)
        self.assertAlmostEqual(s["tahmin"], 20.0)
        self.assertAlmostEqual(s["tahmin"], TEMEL)
        self.assertEqual(s["zincir"].etkenler, {})

    def test_elle_hesapla_ayni(self):
        s = self.sayi()
        z = s["zincir"].etkenler
        self.assertAlmostEqual(z["eslesme_ham"].carpan, ESLESME)
        self.assertEqual(set(z), set(ESKI_ETKENLER))
        self.assertAlmostEqual(z["ev_deplasman"].carpan, EV_DEPLASMAN)
        self.assertEqual(z["arka_arkaya"].carpan, 1.0)                 # dün maç yok
        self.assertFalse(z["eksik_arkadas"].veri_var)                  # sakatlık verisi yok
        self.assertAlmostEqual(s["tahmin"], TEMEL * ESLESME * EV_DEPLASMAN)

    def test_her_etken_tek_tek_kapatilabilir(self):
        tam = self.sayi()["tahmin"]
        for ad, beklenen in (("eslesme_ham", TEMEL * EV_DEPLASMAN), ("ev_deplasman", TEMEL * ESLESME), ("arka_arkaya", tam), ("eksik_arkadas", tam)):
            ayarlar = {a: ({**v, "acik": False} if a == ad else v) for a, v in ESKI_AYAR.items()}
            s = self.sayi(ayarlar)
            self.assertAlmostEqual(s["tahmin"], beklenen, msg=ad)
            self.assertNotIn(ad, s["zincir"].etkenler)

    def test_arka_arkaya_ve_eksik_arkadas(self):
        # Dün de maç olsun ve arkadaşı (son 3 maçta 24'er dk) bugün "Out" olsun.
        veritabani.yaz(self.c, "maclar", [{"mac_id": "dun", "tarih": "2026-11-09", "ev_takim_id": 1, "dep_takim_id": 3, "durum": "oynandi"}])
        veritabani.yaz(self.c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": "dun", "takim_id": 1, "rakip_id": 3, "ev_mi": 1, "ilk_bes": 1,
                                                "dakika": 30.0, "sayi": 18, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}])
        veritabani.goruntu_yaz(self.c, "sakatliklar", {"kaynak": "espn", "cekim_tarihi": BUGUN}, [
            {"oyuncu_anahtari": "30", "cekim_zamani": veritabani.simdi_utc(), "oyuncu_id": 30, "isim": "Sakat Arkadas", "takim_id": 1,
             "durum": "Out", "aciklama": None, "tahmini_donus": None}])
        s = self.sayi()
        z = s["zincir"].etkenler
        bosalan = (24.0 * 3) / 4                                       # takımın son 4 maçının 3'ünde 24'er dk
        self.assertAlmostEqual(z["eksik_arkadas"].carpan, 240 / (240 - bosalan))
        self.assertFalse(z["arka_arkaya"].veri_var)                    # ligde henüz arka arkaya maç kaydı yok -> veri yok
        self.assertEqual(z["arka_arkaya"].carpan, 1.0)
        ref = referans_tahmin(self.c, 10, 1, "PG", "bugun", "sayi", BUGUN)
        self.assertAlmostEqual(s["tahmin"], ref)
        baglam = tahmin.Baglam(self.c, BUGUN)
        self.assertNotIn(30, [o.oyuncu_id for o in tahmin.tahmin_edilecekler(baglam, MAC)])   # "Out" oyuncuya tahmin yok

    def test_referansla_esdeger_ve_iki_kez_yazinca_cogalmaz(self):
        for _ in range(2):
            sonuc = tahmin.gunu_tahmin_et(self.c, BUGUN)
        n_tahmin = self.c.execute("SELECT COUNT(*) FROM tahminler").fetchone()[0]
        self.assertEqual(n_tahmin, len(sonuc))
        self.assertEqual(n_tahmin, 2 * (7 + len(config.BIRLESIK)))     # oyuncu 10 ve 30; oyuncu 20'nin 2 maçı var, yetmez
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tahmin_etken").fetchone()[0], 2 * 7 * len(etkenler.acik_etkenler()))
        n, en_buyuk, farkli = karsilastir(self.c, BUGUN)
        self.assertEqual((n, farkli), (14, []))
        self.assertLess(en_buyuk, 1e-12)

    def test_kapatilan_etkenin_eski_kayitlari_silinir(self):
        tahmin.gunu_tahmin_et(self.c, BUGUN, etken_listesi=etkenler.acik_etkenler(ESKI_AYAR))
        self.assertEqual(self.c.execute("SELECT COUNT(DISTINCT etken) FROM tahmin_etken").fetchone()[0], 4)
        tek = {ad: {**a, "acik": ad == "ev_deplasman"} for ad, a in config.ETKENLER.items()}
        tahmin.gunu_tahmin_et(self.c, BUGUN, etken_listesi=etkenler.acik_etkenler(tek))
        self.assertEqual([s[0] for s in self.c.execute("SELECT DISTINCT etken FROM tahmin_etken")], ["ev_deplasman"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tahmin_etken").fetchone()[0], 2 * 7)

    def test_bugunun_ve_sonrasinin_verisi_kullanilmaz(self):
        once = self.sayi()["tahmin"]
        # Bugünün maçı oynanmış ve sonucu yazılmış olsa bile bugünün tahmini değişmemeli.
        veritabani.yaz(self.c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": "bugun", "takim_id": 1, "rakip_id": 2, "ev_mi": 0, "ilk_bes": 1,
                                                "dakika": 48.0, "sayi": 70, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}])
        self.assertEqual(self.sayi()["tahmin"], once)

    def test_guven_puani_sinirlar_icinde(self):
        s = self.sayi()
        self.assertTrue(0 <= s["guven"] <= 100)
        b = s["girdiler"]["guven"]
        self.assertAlmostEqual(b["orneklem"], config.GUVEN_AGIRLIK["orneklem"] * 3 / 15)
        self.assertAlmostEqual(sum(b.values()), s["guven"], delta=0.3)


if __name__ == "__main__":
    unittest.main()
