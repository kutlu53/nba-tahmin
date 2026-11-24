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


if __name__ == "__main__":
    unittest.main()
