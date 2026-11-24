"""GitHub Pages sayfasının derlenmesi (sayfa_derle.derle). Ağa çıkmaz."""
import json
import tempfile
import unittest
from pathlib import Path

import sayfa_derle


class DerleTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        kok = Path(self.gecici.name)
        self.veri, self.cikti, self.sayfa = kok / "site_veri", kok / "cikti", kok / "index.html"
        self.veri.mkdir()
        self.sayfa.write_text("<!doctype html><title>Deneme</title>", encoding="utf-8")

    def tearDown(self):
        self.gecici.cleanup()

    def yaz(self, ad, belge):
        (self.veri / ad).write_text(json.dumps(belge, ensure_ascii=False), encoding="utf-8")

    def derle(self):
        ozet = sayfa_derle.derle(self.cikti, self.veri, self.sayfa)
        return ozet, json.loads((self.cikti / "veri.json").read_text(encoding="utf-8"))

    def test_gun_ve_gecmis_tek_dosyada_toplanir(self):
        self.yaz("ozet.json", {"bugun": "2026-11-24", "model": {}})
        self.yaz("gun_2026-11-24.json", {"tarih": "2026-11-24", "maclar": [], "ust_alt": [{"oyuncu": "Şengün"}]})
        self.yaz("gun_2026-11-23.json", {"tarih": "2026-11-23", "maclar": []})        # eski günün dosyası kullanılmaz
        for tarih in ("2026-11-21", "2026-11-23", "2026-11-22"):
            self.yaz(f"gecmis_{tarih}.json", {"tarih": tarih})
        ozet, veri = self.derle()
        self.assertEqual((ozet["bugun"], ozet["gun_var"], ozet["gecmis_gun"]), ("2026-11-24", True, 3))
        self.assertEqual(veri["gun"]["tarih"], "2026-11-24")
        self.assertEqual(veri["gun"]["ust_alt"][0]["oyuncu"], "Şengün")
        self.assertEqual([g["tarih"] for g in veri["gecmis"]], ["2026-11-23", "2026-11-22", "2026-11-21"])     # yeniden eskiye
        self.assertEqual(veri["ozet"]["bugun"], "2026-11-24")
        self.assertIn("derleme", veri)
        self.assertEqual((self.cikti / "index.html").read_text(encoding="utf-8"), "<!doctype html><title>Deneme</title>")

    def test_gunun_belgesi_yoksa_bos_gecilir(self):
        self.yaz("ozet.json", {"bugun": None})
        ozet, veri = self.derle()
        self.assertEqual((ozet["gun_var"], veri["gun"], veri["gecmis"]), (False, None, []))

    def test_en_cok_kirk_gecmis_gun(self):
        self.yaz("ozet.json", {"bugun": None})
        for gun in range(1, 46):
            self.yaz(f"gecmis_2026-{1 + gun // 29:02d}-{1 + gun % 28:02d}.json", {"tarih": "x"})
        self.assertEqual(self.derle()[0]["gecmis_gun"], sayfa_derle.GECMIS_GUN)

    def test_ozet_yoksa_hata(self):
        with self.assertRaises(FileNotFoundError):
            sayfa_derle.derle(self.cikti, self.veri, self.sayfa)
        self.assertFalse((self.cikti / "veri.json").exists())

    def test_asil_sayfa_kendi_basina_tam_bir_belge(self):
        metin = sayfa_derle.SAYFA.read_text(encoding="utf-8")
        self.assertTrue(metin.startswith("<!doctype html>"))
        self.assertIn('fetch("veri.json?t="', metin)
        self.assertNotIn("window.claude", metin)                                      # Claude sayfasına özgü veri katmanı burada yok


if __name__ == "__main__":
    unittest.main()
