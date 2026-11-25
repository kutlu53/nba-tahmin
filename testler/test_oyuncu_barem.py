"""Bahis sitesinin oyuncu baremleri (ESPN propBets): ayrıştırma ve günde bir kez yazma. Ağa çıkmaz."""
import logging
import unittest
from unittest import mock

import config
import yukle
from kaynak import KaynakHatasi, espn
from testler.test_tahmin import BUGUN, kur


def kayit(oyuncu, pazar, cizgi, oran, acilis_cizgi=None, acilis_oran=None, guncelleme="2026-11-10T12:00Z"):
    """Beslemedeki tek bir kayıt (bir oyuncunun bir pazarında bir taraf)."""
    return {"athlete": {"$ref": f"http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2027/athletes/{oyuncu}?lang=en"},
            "type": {"id": "1", "name": pazar}, "lastUpdated": guncelleme,
            "odds": {"decimal": {"value": str(oran), "open": str(acilis_oran or oran)}, "total": {"value": str(cizgi), "open": str(acilis_cizgi or cizgi)}}}


ORNEK = [
    kayit(9010, "Total Points", 18.5, 1.84, acilis_cizgi=17.5, acilis_oran=1.81), kayit(9010, "Total Points", 18.5, 1.93, acilis_cizgi=17.5, guncelleme="2026-11-10T13:00Z"),
    kayit(9010, "Total 3-Point Field Goals", 1.5, 2.32), kayit(9010, "Total 3-Point Field Goals", 1.5, 1.57),
    kayit(9010, "Total Points, Rebounds, and Assists", 32.5, 1.80), kayit(9010, "Total Points, Rebounds, and Assists", 32.5, 1.94),
    kayit(9999, "Total Assists", 6.5, 1.90), kayit(9999, "Total Assists", 6.5, 1.86),            # oyuncular tablosunda olmayan oyuncu
    kayit(9010, "Points Milestones", 20, 2.10), kayit(9010, "Points Milestones", 25, 3.40),      # kademeli pazar: alınmaz
    kayit(9010, "Total Rebounds", 7.5, 1.90),                                                    # tek kayıt: atlanır
    kayit(9999, "Total Points", 20.5, 1.90), kayit(9999, "Total Points", 21.5, 1.90),            # iki ayrı barem: atlanır
    {"type": {"name": "Team Total Points"}, "odds": {"total": {"value": "118.5"}}},              # oyuncusuz pazar
]


class AyristirmaTesti(unittest.TestCase):
    def test_oyuncu_ve_pazar_basina_tek_satir(self):
        satirlar, atlanan = espn.barem_ayristir(ORNEK)
        s = {(x["espn_oyuncu_id"], x["istatistik"]): x for x in satirlar}
        self.assertEqual(set(s), {(9010, "sayi"), (9010, "ucluk"), (9010, "sayi+ribaund+asist"), (9999, "asist")})
        self.assertEqual(atlanan, 2)
        sayi = s[(9010, "sayi")]
        self.assertEqual((sayi["cizgi"], sayi["acilis_cizgi"]), (18.5, 17.5))
        self.assertEqual((sayi["oran_1"], sayi["oran_2"], sayi["acilis_oran_1"]), (1.84, 1.93, 1.81))       # beslemedeki sırayla
        self.assertEqual(sayi["guncelleme"], "2026-11-10T13:00Z")

    def test_bos_besleme(self):
        self.assertEqual(espn.barem_ayristir([]), ([], 0))

    def test_sayfalar_birlestirilir_ve_barem_yoksa_bos_doner(self):
        oran = {"items": [{"provider": {"id": "100", "name": "DraftKings"}, "propBets": {"$ref": "http://..."}}]}
        sayfalar = [oran, {"items": ORNEK[:2], "pageCount": 2}, {"items": ORNEK[2:4], "pageCount": 2}]
        with mock.patch.object(espn, "_json_al", side_effect=sayfalar) as istek:
            saglayici, satirlar, atlanan = espn.oyuncu_baremleri(401)
        self.assertEqual((saglayici, len(satirlar), atlanan), ("DraftKings", 2, 0))
        self.assertEqual(istek.call_count, 3)
        self.assertIn("/odds/100/propBets?limit=1000&page=2", istek.call_args_list[2].args[0])
        for bos in ({"items": []}, {"items": [{"provider": {"id": "100", "name": "DraftKings"}}]}):
            with mock.patch.object(espn, "_json_al", return_value=bos):
                self.assertEqual(espn.oyuncu_baremleri(401), (None, [], 0))


class YuklemeTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()
        self.c.execute("UPDATE takimlar SET espn_id = takim_id + 100")
        self.c.execute("UPDATE oyuncular SET espn_id = 9010 WHERE oyuncu_id = 10")
        self.c.execute("UPDATE maclar SET baslama_utc = '2099-01-01T00:00:00Z' WHERE mac_id = 'bugun'")
        self.c.commit()
        self.eski_bekleme, config.ESPN_BEKLEME_SN = config.ESPN_BEKLEME_SN, 0
        self.skor = mock.patch.object(espn, "skor_tablosu", return_value=[{"espn_mac_id": 401, "ev_espn_id": 102, "dep_espn_id": 101}]).start()
        self.barem = mock.patch.object(espn, "oyuncu_baremleri", return_value=("DraftKings",) + espn.barem_ayristir(ORNEK)).start()

    def tearDown(self):
        mock.patch.stopall()
        config.ESPN_BEKLEME_SN = self.eski_bekleme
        logging.disable(logging.NOTSET)
        self.c.close()

    def satirlar(self):
        return {(s["espn_oyuncu_id"], s["istatistik"]): dict(s) for s in self.c.execute("SELECT * FROM oyuncu_barem")}

    def test_yazilir_ve_oyuncu_eslenir(self):
        self.assertEqual(yukle.oyuncu_baremlerini_yukle(self.c, BUGUN), (1, 4, 1))
        s = self.satirlar()
        self.assertEqual(len(s), 4)
        sayi = s[(9010, "sayi")]
        self.assertEqual((sayi["mac_id"], sayi["tarih"], sayi["oyuncu_id"], sayi["cizgi"], sayi["oran_1"], sayi["saglayici"]),
                         ("bugun", BUGUN, 10, 18.5, 1.84, "DraftKings"))
        self.assertIsNone(s[(9999, "asist")]["oyuncu_id"])                       # eşlenemeyen oyuncu da saklanır

    def test_gunde_bir_kez(self):
        yukle.oyuncu_baremlerini_yukle(self.c, BUGUN)
        self.assertEqual(yukle.oyuncu_baremlerini_yukle(self.c, BUGUN), (0, 0, 0))      # ikinci çalıştırma kaynağa gitmez
        self.assertEqual((self.barem.call_count, self.skor.call_count), (1, 1))

    def test_yeniden_cekim_eskisinin_yerine_gecer(self):
        yukle.oyuncu_baremlerini_yukle(self.c, BUGUN)
        self.barem.return_value = ("DraftKings",) + espn.barem_ayristir([kayit(9010, "Total Points", 19.5, 1.90), kayit(9010, "Total Points", 19.5, 1.90)])
        self.assertEqual(yukle.oyuncu_baremlerini_yukle(self.c, BUGUN, yeniden=True), (1, 1, 0))
        self.assertEqual({k: v["cizgi"] for k, v in self.satirlar().items()}, {(9010, "sayi"): 19.5})

    def test_baslamis_mac_cekilmez(self):
        self.c.execute("UPDATE maclar SET baslama_utc = '2020-01-01T00:00:00Z' WHERE mac_id = 'bugun'")
        self.c.commit()
        self.assertEqual(yukle.oyuncu_baremlerini_yukle(self.c, BUGUN), (0, 0, 0))
        self.barem.assert_not_called()
        self.skor.assert_not_called()

    def test_barem_acilmamis_mac(self):
        self.barem.return_value = (None, [], 0)
        self.assertEqual(yukle.oyuncu_baremlerini_yukle(self.c, BUGUN), (0, 0, 0))
        self.assertEqual(self.satirlar(), {})

    def test_alinamayan_mac_hata_olarak_bildirilir(self):
        self.barem.side_effect = KaynakHatasi("yanıt yok")
        with self.assertRaises(KaynakHatasi):
            yukle.oyuncu_baremlerini_yukle(self.c, BUGUN)
        self.assertEqual(self.satirlar(), {})


if __name__ == "__main__":
    unittest.main()
