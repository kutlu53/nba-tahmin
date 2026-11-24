"""Bulut zamanlayıcısının kararı (bulut.karar). Ağa çıkmaz; saatler config.py'deki varsayılanlara göredir."""
import unittest
from datetime import datetime, timezone

import bulut
import config
import veritabani

GUN = "2026-11-24"          # salı; ABD doğu saati UTC−5, Türkiye UTC+3
PAZARTESI = "2026-11-23"


def utc(tarih, saat):
    return datetime.fromisoformat(f"{tarih}T{saat}:00+00:00")


class KararTesti(unittest.TestCase):
    def setUp(self):
        self.c = veritabani.baglan(":memory:")
        veritabani.sema_kur(self.c)
        veritabani.yaz(self.c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
        self.saatler = (config.SABAH_SAATI, config.MAC_ONCESI_SAATI, config.MAC_YAKLASAN_DK, config.HAFTALIK_GUN, config.HAFTALIK_SAATI)
        config.SABAH_SAATI, config.MAC_ONCESI_SAATI, config.MAC_YAKLASAN_DK, config.HAFTALIK_GUN, config.HAFTALIK_SAATI = \
            "10:00", "20:30", 40, "Monday", "11:00"

    def tearDown(self):
        config.SABAH_SAATI, config.MAC_ONCESI_SAATI, config.MAC_YAKLASAN_DK, config.HAFTALIK_GUN, config.HAFTALIK_SAATI = self.saatler
        self.c.close()

    def calisma(self, ad, tarih, tahmin="tamam", sira=1):
        kimlik = f"{ad}-{tarih}-{sira:08d}"
        veritabani.kayit_yaz(self.c, kimlik, "fikstur", "tamam", None, 1.0)
        if tahmin:
            veritabani.kayit_yaz(self.c, kimlik, "tahmin", tahmin, None if tahmin == "tamam" else "RuntimeError: x", 1.0)

    def mac(self, baslama_utc, durum="oynanacak", tarih=GUN):
        veritabani.yaz(self.c, "maclar", [{"mac_id": f"m{baslama_utc}", "tarih": tarih, "baslama_utc": baslama_utc,
                                           "ev_takim_id": 1, "dep_takim_id": 2, "durum": durum}])

    def kip(self, tarih, saat):
        return bulut.karar(self.c, utc(tarih, saat))[0]

    def test_sabah_saatinden_once_is_yok(self):
        self.calisma("sabah", "2026-11-23")
        self.calisma("mac_oncesi", "2026-11-23")
        bulut.kaydet(self.c, "haftalik", 0, 400.0, simdi=utc(PAZARTESI, "08:15"))
        self.assertEqual(self.kip(GUN, "04:59"), "yok")       # ABD'de hâlâ 23 Kasım (23:59): o günün işleri bitmiş
        self.assertEqual(self.kip(GUN, "05:30"), "yok")       # ABD'de 24 Kasım başladı, Türkiye'de 08:30
        self.assertEqual(self.kip(GUN, "06:59"), "yok")       # Türkiye'de 09:59

    def test_sabah_saatinde_ve_gecikince_sabah_akisi(self):
        self.assertEqual(self.kip(GUN, "07:00"), "sabah")     # Türkiye'de 10:00
        self.assertEqual(self.kip(GUN, "15:22"), "sabah")     # tetikleme saatlerce gecikse de yapılır
        self.assertEqual(self.kip(GUN, "18:00"), "sabah")     # akşam saati geçmiş olsa da önce sabah akışı

    def test_sabah_tamamlaninca_yinelenmez(self):
        self.calisma("sabah", GUN)
        self.assertEqual(self.kip(GUN, "07:22"), "yok")
        self.assertEqual(self.kip(GUN, "17:29"), "yok")       # Türkiye'de 20:29

    def test_tamamlanamayan_sabah_akisi_sinirli_sayida_denenir(self):
        self.calisma("sabah", GUN, tahmin=None, sira=1)       # kritik adımda durmuş: tahmin satırı yok
        self.calisma("sabah", GUN, tahmin="hata", sira=2)
        self.assertEqual(self.kip(GUN, "07:37"), "sabah")
        self.calisma("sabah", GUN, tahmin="hata", sira=3)
        kip, gerekce = bulut.karar(self.c, utc(GUN, "07:52"))
        self.assertEqual(kip, "yok")
        self.assertIn("3 kez denendi", gerekce)
        self.assertEqual(self.kip(GUN, "18:00"), "yok")       # sabah akışı olmadan akşam akışı da çalışmaz

    def test_mac_oncesi_saatinde_bir_kez(self):
        self.calisma("sabah", GUN)
        self.assertEqual(self.kip(GUN, "17:30"), "mac_oncesi")          # Türkiye'de 20:30
        self.assertEqual(self.kip("2026-11-25", "04:30"), "mac_oncesi")  # ABD'de hâlâ 24 Kasım 23:30
        self.calisma("mac_oncesi", GUN)
        self.assertEqual(self.kip(GUN, "17:52"), "yok")

    def test_baska_gunun_calismasi_sayilmaz(self):
        self.calisma("sabah", "2026-11-23")
        self.calisma("mac_oncesi", "2026-11-23")
        self.assertEqual(self.kip(GUN, "07:07"), "sabah")

    def test_yaklasan_mac(self):
        self.calisma("sabah", GUN)
        self.calisma("mac_oncesi", GUN)
        self.mac("2026-11-25T00:00:00Z")
        self.assertEqual(self.kip(GUN, "23:07"), "yok")       # 53 dakika var
        self.assertEqual(self.kip(GUN, "23:22"), "yaklasan")  # 38 dakika var
        self.assertEqual(self.kip(GUN, "23:59"), "yaklasan")
        self.assertEqual(self.kip("2026-11-25", "00:07"), "yok")   # başladı

    def test_baslamis_ya_da_ertelenmis_mac_yaklasan_sayilmaz(self):
        self.calisma("sabah", GUN)
        self.calisma("mac_oncesi", GUN)
        self.mac("2026-11-25T00:00:00Z", durum="ertelendi")
        self.assertEqual(self.kip(GUN, "23:30"), "yok")

    def test_yaklasan_mac_aksam_akisindan_once_de_yakalanir(self):
        self.calisma("sabah", GUN)
        self.mac("2026-11-24T17:00:00Z")                      # erken maç: Türkiye'de 20:00
        self.assertEqual(self.kip(GUN, "16:37"), "yaklasan")
        self.assertEqual(self.kip(GUN, "17:37"), "mac_oncesi")

    def test_haftalik_pazartesi_sabah_akisindan_sonra_bir_kez(self):
        self.assertEqual(self.kip(PAZARTESI, "08:07"), "sabah")         # Türkiye'de 11:07 ama sabah akışı yapılmamış
        self.calisma("sabah", PAZARTESI)
        self.assertEqual(self.kip(PAZARTESI, "07:52"), "yok")           # Türkiye'de 10:52
        self.assertEqual(self.kip(PAZARTESI, "08:07"), "haftalik")
        bulut.kaydet(self.c, "haftalik", 1, 400.0, simdi=utc(PAZARTESI, "08:15"))
        self.assertEqual(self.kip(PAZARTESI, "08:22"), "yok")           # başarısız olsa da o gün yinelenmez
        satir = self.c.execute("SELECT calisma_id, adim, sonuc, hata_iletisi FROM calisma_kaydi WHERE adim = 'haftalik'").fetchone()
        self.assertEqual((satir["calisma_id"][:19], satir["sonuc"], satir["hata_iletisi"]), (f"haftalik-{PAZARTESI}", "hata", "çıkış kodu 1"))

    def test_haftalik_baska_gun_calismaz(self):
        self.calisma("sabah", GUN)
        self.assertEqual(self.kip(GUN, "08:07"), "yok")

    def test_yaklasan_sorgusu_mac_oncesi_ile_ayni(self):
        import inspect

        import mac_oncesi
        sorgu = "SELECT COUNT(*) FROM maclar WHERE tarih = ? AND durum = 'oynanacak' AND baslama_utc > ? AND baslama_utc <= ?"
        self.assertIn(sorgu, inspect.getsource(mac_oncesi.yaklasan_mac_sayisi))
        self.assertIn(sorgu, inspect.getsource(bulut.yaklasan_mac_sayisi))


class KomutTesti(unittest.TestCase):
    def test_elle_secilen_kip_veritabanina_bakmadan_doner(self):
        import contextlib
        import io
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = bulut.main(["karar", "mac_oncesi"])
        self.assertEqual((kod, cikti.getvalue()), (0, "kip=mac_oncesi\ngerekce=elle seçildi\n"))
        with contextlib.redirect_stdout(io.StringIO()) as cikti:
            self.assertEqual(bulut.main(["karar", "sayfa"]), 0)
        self.assertEqual(cikti.getvalue().splitlines()[0], "kip=sayfa")

    def test_bilinmeyen_komut(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bulut.main(["karar", "herhangi"]), 2)
            self.assertEqual(bulut.main([]), 2)


if __name__ == "__main__":
    unittest.main()
