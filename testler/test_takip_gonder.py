"""Takip dosyalarının depoya gönderilmesi (takip_gonder.depoya_gonder). Ağa çıkmaz: uzak depo geçici bir klasördür."""
import logging
import subprocess
import tempfile
import unittest
from pathlib import Path

import takip_gonder


def git(klasor, *arg):
    return subprocess.run(["git", "-C", str(klasor), *arg], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


class DepoyaGonderTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.gecici = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        kok = Path(self.gecici.name)
        self.uzak, self.depo, self.klasor = kok / "uzak.git", kok / "depo", kok / "takip_verisi"
        self.klasor.mkdir()
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(self.uzak)], check=True, capture_output=True)
        subprocess.run(["git", "clone", "--quiet", str(self.uzak), str(self.depo)], check=True, capture_output=True)
        for anahtar, deger in (("user.name", "deneme"), ("user.email", "deneme@example.invalid"), ("core.autocrlf", "false"), ("commit.gpgsign", "false")):
            git(self.depo, "config", anahtar, deger)
        (self.depo / "README.md").write_text("deneme\n", encoding="utf-8")
        git(self.depo, "checkout", "--quiet", "-B", "main")
        git(self.depo, "add", "README.md")
        git(self.depo, "commit", "--quiet", "-m", "ilk")
        git(self.depo, "push", "--quiet", "origin", "HEAD:main")

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self.gecici.cleanup()

    def dosya(self, tarih, icerik="{}"):
        (self.klasor / f"{tarih}.json").write_text(icerik + "\n", encoding="utf-8", newline="\n")

    def uzaktaki(self):
        return sorted(git(self.uzak, "ls-tree", "-r", "--name-only", "main").splitlines())

    def test_yeni_dosyalar_gonderilir_yinelenince_bir_sey_gonderilmez(self):
        self.dosya("2026-11-22")
        self.dosya("2026-11-23")
        self.assertEqual(takip_gonder.depoya_gonder(self.depo, self.klasor), ["2026-11-22.json", "2026-11-23.json"])
        self.assertEqual(self.uzaktaki(), ["README.md", "takip_verisi/2026-11-22.json", "takip_verisi/2026-11-23.json"])
        self.assertEqual(git(self.uzak, "log", "-1", "--format=%s", "main"), "Takip verisi: 2026-11-22 .. 2026-11-23 (2 gün)")
        self.assertEqual(takip_gonder.depoya_gonder(self.depo, self.klasor), [])
        self.assertEqual(git(self.uzak, "rev-list", "--count", "main"), "2")

    def test_degisen_dosya_yeniden_gonderilir(self):
        self.dosya("2026-11-22")
        takip_gonder.depoya_gonder(self.depo, self.klasor)
        self.dosya("2026-11-22", '{"tarih": "2026-11-22"}')
        self.assertEqual(takip_gonder.depoya_gonder(self.depo, self.klasor), ["2026-11-22.json"])
        self.assertEqual(git(self.uzak, "log", "-1", "--format=%s", "main"), "Takip verisi: 2026-11-22")
        self.assertEqual(git(self.uzak, "show", "main:takip_verisi/2026-11-22.json"), '{"tarih": "2026-11-22"}')

    def test_depodaki_baska_degisikliklere_dokunulmaz(self):
        (self.depo / "README.md").write_text("yarım kalmış bir düzenleme\n", encoding="utf-8")
        (self.depo / "yeni.py").write_text("x = 1\n", encoding="utf-8")
        self.dosya("2026-11-22")
        takip_gonder.depoya_gonder(self.depo, self.klasor)
        self.assertEqual(self.uzaktaki(), ["README.md", "takip_verisi/2026-11-22.json"])
        self.assertEqual(git(self.uzak, "show", "main:README.md"), "deneme")
        self.assertEqual((self.depo / "README.md").read_text(encoding="utf-8"), "yarım kalmış bir düzenleme\n")     # yerelde duruyor

    def test_uzaktaki_yeni_islemeler_once_alinir(self):
        baska = Path(self.gecici.name) / "baska"
        subprocess.run(["git", "clone", "--quiet", str(self.uzak), str(baska)], check=True, capture_output=True)
        for anahtar, deger in (("user.name", "deneme"), ("user.email", "deneme@example.invalid"), ("commit.gpgsign", "false")):
            git(baska, "config", anahtar, deger)
        (baska / "kod.py").write_text("y = 2\n", encoding="utf-8")
        git(baska, "add", "kod.py")
        git(baska, "commit", "--quiet", "-m", "başka yerden")
        git(baska, "push", "--quiet", "origin", "HEAD:main")
        self.dosya("2026-11-22")
        takip_gonder.depoya_gonder(self.depo, self.klasor)
        self.assertEqual(self.uzaktaki(), ["README.md", "kod.py", "takip_verisi/2026-11-22.json"])

    def test_depo_kopyasi_yoksa_hata(self):
        with self.assertRaises(RuntimeError):
            takip_gonder.depoya_gonder(Path(self.gecici.name) / "olmayan", self.klasor)

    def test_gonderilememis_isleme_sonraki_calistirmada_gonderilir(self):
        self.dosya("2026-11-22")
        (self.depo / "takip_verisi").mkdir()
        (self.depo / "takip_verisi" / "2026-11-22.json").write_text("{}\n", encoding="utf-8", newline="\n")
        git(self.depo, "add", "--", "takip_verisi")
        git(self.depo, "commit", "--quiet", "-m", "Takip verisi: 2026-11-22")          # işlendi ama gönderilemedi (ağ kesildi)
        self.assertTrue(takip_gonder.bekleyen_isleme_var(self.depo))
        self.assertEqual(takip_gonder.depoya_gonder(self.depo, self.klasor), [])       # yeni dosya yok ...
        self.assertEqual(self.uzaktaki(), ["README.md", "takip_verisi/2026-11-22.json"])   # ... ama bekleyen işleme gönderildi
        self.assertFalse(takip_gonder.bekleyen_isleme_var(self.depo))


class BekleyenIsTesti(unittest.TestCase):
    """Yapılacak iş olup olmadığı veritabanından ve depo kopyasından, ağa çıkmadan anlaşılır."""

    def setUp(self):
        import veritabani
        self.gecici = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.depo = Path(self.gecici.name)
        (self.depo / "takip_verisi").mkdir()
        self.c = veritabani.baglan(":memory:")
        veritabani.sema_kur(self.c)
        veritabani.yaz(self.c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
        veritabani.yaz(self.c, "oyuncular", [{"oyuncu_id": 10, "isim": "Oyuncu", "takim_id": 1, "pozisyon": "PG"}])
        veritabani.yaz(self.c, "maclar", [
            {"mac_id": "a", "tarih": "2026-11-22", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"},
            {"mac_id": "b", "tarih": "2026-11-23", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"},
            {"mac_id": "c", "tarih": "2026-11-24", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])
        veritabani.yaz(self.c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": mac, "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "ilk_bes": 1, "dakika": 30.0,
                                                "sayi": 10, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0} for mac in ("a", "b")])
        veritabani.yaz(self.c, "takip_mac", [{"oyuncu_id": 10, "mac_id": "a", "olasi_asist": 5, "pas": 40, "ribaund_firsati": 8, "top_dokunusu": 60}])

    def tearDown(self):
        self.c.close()
        self.gecici.cleanup()

    def test_eksik_ve_gonderilmemis_gunler(self):
        import veritabani
        self.assertEqual(takip_gonder.eksik_gunler(self.c), ["2026-11-23"])                   # oynandı, takip verisi yok
        self.assertEqual(takip_gonder.gonderilmemis_gunler(self.c, self.depo), ["2026-11-22"])  # verisi var, dosyası depoda yok
        (self.depo / "takip_verisi" / "2026-11-22.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(takip_gonder.gonderilmemis_gunler(self.c, self.depo), [])
        veritabani.yaz(self.c, "takip_mac", [{"oyuncu_id": 10, "mac_id": "b", "olasi_asist": 3, "pas": 30, "ribaund_firsati": 6, "top_dokunusu": 50}])
        self.assertEqual(takip_gonder.eksik_gunler(self.c), [])
        self.assertEqual(takip_gonder.gonderilmemis_gunler(self.c, self.depo), ["2026-11-23"])

    def test_eksik_gun_sorgusu_yukleyiciyle_ayni(self):
        import inspect

        import yukle
        duz = lambda metin: " ".join(metin.split())
        sorgu = duz("""SELECT DISTINCT m.tarih FROM maclar m JOIN oyuncu_mac om USING (mac_id)
            WHERE m.durum = 'oynandi' AND m.tarih >= ? AND om.dakika > 0
              AND NOT EXISTS (SELECT 1 FROM takip_mac t JOIN maclar m2 USING (mac_id) WHERE m2.tarih = m.tarih)
            ORDER BY m.tarih""")
        self.assertIn(sorgu, duz(inspect.getsource(yukle.takip_verisini_yukle)))
        self.assertIn(sorgu, duz(inspect.getsource(takip_gonder.eksik_gunler)))

    def test_git_deposu_olmayan_klasorde_bekleyen_isleme_yok_sayilir(self):
        self.assertFalse(takip_gonder.bekleyen_isleme_var(self.depo))


if __name__ == "__main__":
    unittest.main()
