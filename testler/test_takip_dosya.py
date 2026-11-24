"""Takip verisinin dosya kaynağı (kaynak/takip_dosya.py), dışa aktarma (takip_aktar.py) ve 'cdn' kipinde yükleme. Ağa çıkmaz."""
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import kaynak
import takip_aktar
import yukle
from kaynak import KaynakHatasi, nba_stats, takip_dosya
from testler.test_firsat import kur

GUN = {10: {"olasi_asist": 7, "pas": 31, "ribaund_firsati": 12, "top_dokunusu": 55},
       20: {"olasi_asist": 0, "pas": 9, "ribaund_firsati": 3, "top_dokunusu": 14}}


class TakipDosyaTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.klasor = tempfile.TemporaryDirectory()
        self.eski = config.TAKIP_KLASORU, config.VERI_KAYNAGI
        config.TAKIP_KLASORU = Path(self.klasor.name) / "takip_verisi"

    def tearDown(self):
        logging.disable(logging.NOTSET)
        config.TAKIP_KLASORU, config.VERI_KAYNAGI = self.eski
        self.klasor.cleanup()

    def test_yazilan_gun_ayni_okunur(self):
        self.assertTrue(takip_dosya.gunu_yaz("2026-11-01", GUN))
        self.assertEqual(takip_dosya.takip_gunu("2026-11-01"), GUN)
        self.assertFalse(takip_dosya.gunu_yaz("2026-11-01", GUN))             # içerik aynı: yeniden yazılmaz
        self.assertTrue(takip_dosya.gunu_yaz("2026-11-01", {10: GUN[10]}))    # içerik değişti

    def test_dosya_yoksa_ya_da_bozuksa_hata(self):
        with self.assertRaises(KaynakHatasi):
            takip_dosya.takip_gunu("2026-11-01")
        takip_dosya.gunu_yaz("2026-11-01", GUN)
        yol = takip_dosya.dosya_yolu("2026-11-02")
        yol.write_text(takip_dosya.dosya_yolu("2026-11-01").read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(KaynakHatasi):                                 # dosyanın içindeki tarih başka gün
            takip_dosya.takip_gunu("2026-11-02")
        yol.write_text('{"tarih": "2026-11-02", "sutunlar": ["olasi_asist"], "oyuncular": {"10": [1]}}', encoding="utf-8")
        with self.assertRaises(KaynakHatasi):                                 # sütunlar eksik
            takip_dosya.takip_gunu("2026-11-02")
        yol.write_text("{bozuk", encoding="utf-8")
        with self.assertRaises(KaynakHatasi):
            takip_dosya.takip_gunu("2026-11-02")

    def test_kaynak_secimi(self):
        config.VERI_KAYNAGI = "stats"
        self.assertIs(kaynak.takip_kaynagi(), nba_stats)
        config.VERI_KAYNAGI = "cdn"
        self.assertIs(kaynak.takip_kaynagi(), takip_dosya)

    def test_aktarilan_veri_cdn_kipinde_ayni_yuklenir(self):
        """Bilgisayarın veritabanından dosyaya, dosyadan öbür makinenin veritabanına: takip_mac tablosu birebir aynı çıkar."""
        oku = lambda c: [tuple(s) for s in c.execute("SELECT * FROM takip_mac ORDER BY mac_id, oyuncu_id")]
        bilgisayar, bulut = kur(), kur(takip=False)
        gun, yazilan = takip_aktar.aktar(bilgisayar)
        self.assertEqual((gun, yazilan), (3, ["2026-11-01", "2026-11-02", "2026-11-03"]))
        self.assertEqual(takip_aktar.aktar(bilgisayar), (3, []))              # ikinci kez: değişen dosya yok
        self.assertEqual(takip_aktar.aktar(bilgisayar, "2026-11-03")[0], 1)

        config.VERI_KAYNAGI = "cdn"
        takip_dosya.dosya_yolu("2026-11-02").unlink()                         # bir gün henüz gönderilmemiş
        with mock.patch.object(nba_stats, "takip_gunu", side_effect=AssertionError("cdn kipinde stats.nba.com'a gidilmemeli")):
            ozet = yukle.takip_verisini_yukle(bulut)
            self.assertEqual((ozet["gun"], ozet["alinan"], ozet["alinamayan"], ozet["yazilan"]), (3, 2, ["2026-11-02"], 4))
            takip_aktar.aktar(bilgisayar)                                     # eksik gün gönderildi
            ozet = yukle.takip_verisini_yukle(bulut)                          # yalnızca eksik gün yeniden denenir
            self.assertEqual((ozet["gun"], ozet["alinan"], ozet["alinamayan"], ozet["yazilan"]), (1, 1, [], 2))
        self.assertEqual(oku(bulut), oku(bilgisayar))
        bilgisayar.close(), bulut.close()


if __name__ == "__main__":
    unittest.main()
