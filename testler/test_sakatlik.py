"""ESPN sakatlık ayrıştırması ve günlük görüntü yazımı. Ağa çıkmaz."""
import unittest

import veritabani
from kaynak import KaynakHatasi, espn


def kayit(isim, durum="Out", kimlik=None, baglanti=None, **ayrinti):
    oyuncu = {"displayName": isim}
    if kimlik:
        oyuncu["id"] = kimlik
    if baglanti:
        oyuncu["links"] = [{"href": baglanti}]
    return {"status": durum, "shortComment": f"{isim} not", "athlete": oyuncu, "details": ayrinti}


class AyristirmaTesti(unittest.TestCase):
    def test_kimlik_baglantidan_okunur(self):
        veri = {"injuries": [{"id": "1", "injuries": [
            kayit("Jock Landale", baglanti="https://www.espn.com/nba/player/_/id/3146557/jock-landale",
                  type="Hip", detail="Inflammation", side="Right", returnDate="2026-11-27"),
            kayit("Kimliksiz Oyuncu", durum="Day-To-Day"),
        ]}]}
        a, b = espn.sakatlik_ayristir(veri)
        self.assertEqual((a["espn_takim_id"], a["espn_oyuncu_id"], a["durum"], a["tahmini_donus"]), (1, 3146557, "Out", "2026-11-27"))
        self.assertEqual(a["aciklama"], "Hip, Inflammation, Right — Jock Landale not")
        self.assertIsNone(b["espn_oyuncu_id"])
        self.assertEqual(b["durum"], "Day-To-Day")

    def test_bozuk_veri_hata_verir(self):
        for bozuk in ({}, {"injuries": []}, {"injuries": [{"id": "1", "injuries": []}]},
                      {"injuries": [{"id": "1", "injuries": [{"athlete": {"displayName": "x"}}]}]}):
            with self.assertRaises(KaynakHatasi):
                espn.sakatlik_ayristir(bozuk)


class GoruntuTesti(unittest.TestCase):
    def setUp(self):
        self.c = veritabani.baglan(":memory:")
        veritabani.sema_kur(self.c)
        veritabani.yaz(self.c, "takimlar", [{"takim_id": 1, "kisaltma": "AAA", "isim": "A"}])

    def tearDown(self):
        self.c.close()

    def satir(self, anahtar, durum="Out"):
        return {"oyuncu_anahtari": anahtar, "cekim_zamani": veritabani.simdi_utc(), "oyuncu_id": None,
                "isim": anahtar, "takim_id": 1, "durum": durum, "aciklama": None, "tahmini_donus": None}

    def say(self):
        return [tuple(s) for s in self.c.execute("SELECT cekim_tarihi, oyuncu_anahtari, durum FROM sakatliklar ORDER BY 1, 2")]

    def test_ayni_gun_ikinci_cekim_goruntuyu_degistirir(self):
        gun1 = {"kaynak": "espn", "cekim_tarihi": "2026-11-23"}
        veritabani.goruntu_yaz(self.c, "sakatliklar", gun1, [self.satir("a"), self.satir("b")])
        veritabani.goruntu_yaz(self.c, "sakatliklar", gun1, [self.satir("a", "Day-To-Day"), self.satir("c")])  # b listeden çıktı
        veritabani.goruntu_yaz(self.c, "sakatliklar", {"kaynak": "espn", "cekim_tarihi": "2026-11-24"}, [self.satir("a")])
        self.assertEqual(self.say(), [("2026-11-23", "a", "Day-To-Day"), ("2026-11-23", "c", "Out"), ("2026-11-24", "a", "Out")])

    def test_yazma_basarisiz_olursa_eski_goruntu_kalir(self):
        gun = {"kaynak": "espn", "cekim_tarihi": "2026-11-23"}
        veritabani.goruntu_yaz(self.c, "sakatliklar", gun, [self.satir("a")])
        with self.assertRaises(Exception):
            veritabani.goruntu_yaz(self.c, "sakatliklar", gun, [{**self.satir("b"), "takim_id": 999}])  # olmayan takım
        self.assertEqual(self.say(), [("2026-11-23", "a", "Out")])


if __name__ == "__main__":
    unittest.main()
