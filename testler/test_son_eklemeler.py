"""Resmi raporun tahminde kullanılması, ilk beş beslemesi ve etkeni, yaklaşan maç kipi. Ağa çıkmaz."""
import logging
import unittest
from datetime import datetime, timedelta, timezone

import config
import mac_oncesi
import tahmin
import veritabani
from etkenler import Mac, Oyuncu, ilk_bes
from kaynak import KaynakHatasi, nba_stats
from testler.test_tahmin import BUGUN, MAC, kur


def sakatlik_yaz(c, kaynak, kayitlar):
    veritabani.goruntu_yaz(c, "sakatliklar", {"kaynak": kaynak, "cekim_tarihi": BUGUN}, [
        {"oyuncu_anahtari": str(kimlik), "cekim_zamani": veritabani.simdi_utc(), "oyuncu_id": kimlik, "isim": f"Oyuncu {kimlik}", "takim_id": 1,
         "durum": durum, "aciklama": None, "tahmini_donus": None} for kimlik, durum in kayitlar])


class ResmiRaporTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.c.close()

    def tahmin_edilenler(self):
        return {o.oyuncu_id for o in tahmin.tahmin_edilecekler(tahmin.Baglam(self.c, BUGUN), MAC)}

    def test_resmi_out_tahmini_engeller(self):
        self.assertEqual(self.tahmin_edilenler(), {10, 30})
        sakatlik_yaz(self.c, "nba_resmi", [(10, "Out")])                 # ESPN'de yok, resmi raporda Out
        self.assertEqual(self.tahmin_edilenler(), {30})

    def test_espn_out_resmi_probable_ise_tahmin_uretilir(self):
        sakatlik_yaz(self.c, "espn", [(10, "Out"), (30, "Out")])
        self.assertEqual(self.tahmin_edilenler(), set())
        sakatlik_yaz(self.c, "nba_resmi", [(10, "Probable")])            # resmi rapor: oynaması bekleniyor
        b = tahmin.Baglam(self.c, BUGUN)
        self.assertEqual(self.tahmin_edilenler(), {10})
        self.assertNotIn(10, b.sakatlik)
        self.assertEqual(b.sakatlik[30], "Out")                          # resmi raporda olmayan oyuncuda ESPN geçerli kalır

    def test_questionable_belirsiz_sayilir_ve_ayar_kapatilabilir(self):
        sakatlik_yaz(self.c, "nba_resmi", [(10, "Questionable"), (30, "Out")])
        b = tahmin.Baglam(self.c, BUGUN)
        self.assertEqual((b.sakatlik[10], b.sakatlik[30]), ("Day-To-Day", "Out"))
        self.assertIn(1, b.sakatlik_takimlari)                           # takım için sakatlık verisi var sayılır
        eski, config.RESMI_RAPOR_KULLAN = config.RESMI_RAPOR_KULLAN, False
        try:
            self.assertEqual(tahmin.Baglam(self.c, BUGUN).sakatlik, {})
        finally:
            config.RESMI_RAPOR_KULLAN = eski


class IlkBesTesti(unittest.TestCase):
    def test_besleme_ayristirma(self):
        veri = {"games": [{"gameId": "0022600287", "homeTeam": {"teamId": 1, "players": [
            {"personId": 11, "lineupStatus": "Confirmed", "position": "PG", "rosterStatus": "Active"},
            {"personId": 12, "lineupStatus": "Confirmed", "position": "", "rosterStatus": "Inactive"}]},
            "awayTeam": {"teamId": 2, "players": []}}]}
        k = nba_stats.ilk_bes_ayristir(veri)
        self.assertEqual(k[0], {"mac_id": "0022600287", "takim_id": 1, "oyuncu_id": 11, "pozisyon": "PG", "durum": "Confirmed", "kadro_durumu": "Active"})
        self.assertEqual((k[1]["pozisyon"], k[1]["kadro_durumu"]), (None, "Inactive"))
        with self.assertRaises(KaynakHatasi):
            nba_stats.ilk_bes_ayristir({"oyunlar": []})

    def kur(self):
        """Oyuncu 10 beş maç yedek (10'ar dk) oynar, altıncı maçta ilk beşte başlar (30 dk). Bugün yine ilk beşte."""
        c = veritabani.baglan(":memory:")
        veritabani.sema_kur(c)
        veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
        veritabani.yaz(c, "oyuncular", [{"oyuncu_id": i, "isim": f"Oyuncu {i}", "takim_id": 1, "pozisyon": "PG"} for i in (10, 11, 12, 13, 14, 15)])
        veritabani.yaz(c, "maclar", [{"mac_id": f"g{i}", "tarih": f"2026-11-0{i}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"} for i in range(1, 7)]
                       + [{"mac_id": "bugun", "tarih": BUGUN, "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])
        veritabani.yaz(c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": f"g{i}", "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "ilk_bes": int(i == 6),
                                           "dakika": 30.0 if i == 6 else 10.0, "sayi": 5, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0}
                                          for i in range(1, 7)])
        return c

    def besleme_yaz(self, c, ilk_bes_oyunculari, durum="Expected", kadro_disi=()):
        veritabani.goruntu_yaz(c, "ilk_bes_beklenti", {"mac_id": "bugun"}, [
            {"oyuncu_id": o, "takim_id": 1, "pozisyon": "PG", "durum": durum, "kadro_durumu": "Active", "cekim_zamani": veritabani.simdi_utc()} for o in ilk_bes_oyunculari]
            + [{"oyuncu_id": o, "takim_id": 1, "pozisyon": None, "durum": durum, "kadro_durumu": "Inactive", "cekim_zamani": veritabani.simdi_utc()} for o in kadro_disi])

    def test_etken(self):
        c = self.kur()
        oyuncu, mac = Oyuncu(10, "Oyuncu 10", 1, "PG"), Mac("bugun", BUGUN, 1, 2)
        s = ilk_bes.hesapla(oyuncu, mac, "sayi", tahmin.Baglam(c, BUGUN))
        self.assertEqual((s.carpan, s.veri_var), (1.0, False))                       # besleme yok
        self.besleme_yaz(c, [10, 11, 12, 13, 14])
        b = tahmin.Baglam(c, BUGUN)
        # Geçmişte tek rol değişimi var: 6. maçta beklenen (1 − a) × 10 + a × 10 = 10 dk, gerçekleşen 30 dk -> ham 3,0.
        carpan, n, ham = ilk_bes.rol_etkileri(b)[1]
        self.assertEqual((n, ham), (1, 3.0))
        self.assertAlmostEqual(carpan, (1 * 3.0 + config.ILK_BES_K) / (1 + config.ILK_BES_K))
        s = ilk_bes.hesapla(oyuncu, mac, "sayi", b)
        self.assertAlmostEqual(s.carpan, carpan)                                     # olağan rolü yedek, bu gece ilk beş
        self.assertIn("beklenen ilk beş", s.aciklama)
        self.besleme_yaz(c, [11, 12, 13, 14, 15], durum="Confirmed")                 # bu gece yedek: olağan rolüyle aynı
        s = ilk_bes.hesapla(oyuncu, mac, "sayi", tahmin.Baglam(c, BUGUN))
        self.assertEqual(s.carpan, 1.0)
        self.assertIn("kesin ilk beş", s.aciklama)
        self.besleme_yaz(c, [11, 12, 13, 14])                                        # eksik ilk beş: kullanılmaz
        self.assertFalse(ilk_bes.hesapla(oyuncu, mac, "sayi", tahmin.Baglam(c, BUGUN)).veri_var)
        c.close()

    def test_kadro_disi_bildirilen_oyuncu_out_sayilir(self):
        c = self.kur()
        self.besleme_yaz(c, [11, 12, 13, 14, 15], kadro_disi=[10])
        self.assertEqual(tahmin.Baglam(c, BUGUN).sakatlik.get(10), "Out")
        c.close()


class YaklasanTesti(unittest.TestCase):
    def test_pencere(self):
        logging.disable(logging.CRITICAL)
        c = kur()
        try:
            bicim = "%Y-%m-%dT%H:%M:%SZ"
            simdi = datetime.now(timezone.utc)
            def basla(dakika):
                c.execute("UPDATE maclar SET baslama_utc = ? WHERE mac_id = 'bugun'", ((simdi + timedelta(minutes=dakika)).strftime(bicim),))
                c.commit()
            basla(30)
            self.assertEqual(mac_oncesi.yaklasan_mac_sayisi(c, BUGUN, 40), 1)
            self.assertEqual(len(tahmin.gunun_maclari(c, BUGUN, yalniz_baslamamis=True, pencere_dk=40)), 1)
            basla(90)                                                                # henüz erken
            self.assertEqual(mac_oncesi.yaklasan_mac_sayisi(c, BUGUN, 40), 0)
            self.assertEqual(tahmin.gunun_maclari(c, BUGUN, yalniz_baslamamis=True, pencere_dk=40), [])
            self.assertEqual(len(tahmin.gunun_maclari(c, BUGUN, yalniz_baslamamis=True)), 1)   # akşam çalıştırması yine görür
            basla(-5)                                                                # başlamış
            self.assertEqual(mac_oncesi.yaklasan_mac_sayisi(c, BUGUN, 40), 0)
            adlar = [ad for ad, _, _ in mac_oncesi.aksam_adimlari(BUGUN, pencere_dk=40)]
            self.assertEqual(adlar, ["sakatlik", "resmi_sakatlik", "oranlar", "atamalar", "ilk_besler", "tahmin", "site_veri"])
        finally:
            c.close()
            logging.disable(logging.NOTSET)


if __name__ == "__main__":
    unittest.main()
