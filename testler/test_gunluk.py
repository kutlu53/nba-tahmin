"""Günlük akışın adım yürütücüsü ve Excel raporu. Ağa çıkmaz."""
import logging
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

import config
import gunluk
import rapor
import tahmin
import veritabani
from testler.test_tahmin import BUGUN, kur


class AkisTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.c = kur()
        self.klasor = tempfile.TemporaryDirectory()
        self.eski_klasor, config.RAPOR_KLASORU = config.RAPOR_KLASORU, Path(self.klasor.name)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        config.RAPOR_KLASORU = self.eski_klasor
        self.c.close()
        self.klasor.cleanup()

    def adimlar(self, bozuk=None, kritik_bozuk=False):
        def patla(_):
            raise RuntimeError("kaynak yanıt vermedi")

        return [("veri", kritik_bozuk, patla if bozuk == "veri" else lambda c: 1),
                ("ek_veri", False, patla if bozuk == "ek_veri" else lambda c: 1),
                ("tahmin", True, lambda c: len(tahmin.gunu_tahmin_et(c, BUGUN)))]

    def kayitlar(self):
        return [(s["adim"], s["sonuc"]) for s in self.c.execute("SELECT adim, sonuc FROM calisma_kaydi ORDER BY kayit_id")]

    def test_hepsi_tamam(self):
        kod, basarisiz, yol = gunluk.calistir("sabah", self.adimlar(), BUGUN, self.c)
        self.assertEqual((kod, basarisiz), (0, []))
        self.assertEqual(self.kayitlar(), [("veri", "tamam"), ("ek_veri", "tamam"), ("tahmin", "tamam"), ("rapor", "tamam")])
        self.assertTrue(yol.exists())

    def test_kritik_olmayan_adim_bozulursa_akis_surer(self):
        kod, basarisiz, yol = gunluk.calistir("sabah", self.adimlar(bozuk="ek_veri"), BUGUN, self.c)
        self.assertEqual((kod, basarisiz), (2, ["ek_veri"]))
        self.assertEqual(self.kayitlar(), [("veri", "tamam"), ("ek_veri", "hata"), ("tahmin", "tamam"), ("rapor", "tamam")])
        self.assertGreater(self.c.execute("SELECT COUNT(*) FROM tahminler").fetchone()[0], 0)      # tahminler yine de üretildi
        calisma = load_workbook(yol)["Çalışma"]
        satirlar = [[h.value for h in satir] for satir in calisma.iter_rows(min_row=2)]
        self.assertIn("kaynak yanıt vermedi", " ".join(str(x) for x in satirlar[1]))               # hata raporda görünüyor

    def test_kritik_adim_bozulursa_akis_durur(self):
        kod, basarisiz, _ = gunluk.calistir("sabah", self.adimlar(bozuk="veri", kritik_bozuk=True), BUGUN, self.c)
        self.assertEqual((kod, basarisiz), (1, ["veri"]))
        self.assertEqual(self.kayitlar(), [("veri", "hata"), ("rapor", "tamam")])                  # sonraki adımlar çalışmadı
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tahminler").fetchone()[0], 0)

    def test_iki_kez_calisinca_veri_cogalmaz(self):
        gunluk.calistir("sabah", self.adimlar(), BUGUN, self.c)
        once = {t: n for t, n in veritabani.ozet(self.c).items() if t != "calisma_kaydi"}
        gunluk.calistir("sabah", self.adimlar(), BUGUN, self.c)
        self.assertEqual({t: n for t, n in veritabani.ozet(self.c).items() if t != "calisma_kaydi"}, once)
        self.assertEqual(len(list(config.RAPOR_KLASORU.glob("*.xlsx"))), 1)                        # rapor dosyası da tek


class RaporTesti(unittest.TestCase):
    def test_sayfalar_ve_icerik(self):
        logging.disable(logging.CRITICAL)
        c = kur()
        try:
            tahmin.gunu_tahmin_et(c, BUGUN)
            with tempfile.TemporaryDirectory() as d:
                yol = rapor.excel_yaz(c, BUGUN, klasor=Path(d))
                kitap = load_workbook(yol)
                self.assertEqual(kitap.sheetnames, ["Tahminler", "Etken çarpanları", "Etken ayrıntısı", "Sakatlık", "Sakatlık karşılaştırma", "Savunma", "Dünün sonuçları", "Geri test", "Çalışma"])
                t = kitap["Tahminler"]
                basliklar = [h.value for h in t[1]]
                self.assertEqual(basliklar[:8], ["Maç", "Takım", "Oyuncu", "Poz", "Sakatlık (ESPN)", "Resmi rapor", "Tahmin türü", "Beklenen dk"])
                self.assertEqual(t.cell(row=2, column=7).value, "ön")
                self.assertIn("S+R+A", basliklar)
                self.assertIn("Güven sayı", basliklar)
                self.assertEqual(t.max_row, 1 + 2)                                                # iki oyuncu
                e = kitap["Etken çarpanları"]
                e_basliklar = [h.value for h in e[1]]
                for etken in (ad for ad, a in config.ETKENLER.items() if a["acik"]):
                    self.assertIn(etken, e_basliklar)                                             # her açık etkenin çarpanı bir sütun
                self.assertEqual(e.max_row, 1 + 2 * 7)                                            # oyuncu × 7 istatistik
                self.assertEqual(kitap["Sakatlık"].cell(row=2, column=3).value, "VERİ YOK")       # hiçbir takımdan kayıt gelmedi
                kitap.close()
        finally:
            c.close()
            logging.disable(logging.NOTSET)


if __name__ == "__main__":
    unittest.main()
