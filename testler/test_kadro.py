"""İsim sadeleştirme, oyuncu eşlemesi, birincil pozisyon ve elle düzeltme dosyası. Ağa çıkmaz."""
import tempfile
import unittest
from pathlib import Path

import kadro
from kaynak import KaynakHatasi, espn


class IsimTesti(unittest.TestCase):
    def test_aksan_ek_ve_noktalama(self):
        self.assertEqual(kadro.sade_isim("Luka Dončić"), "luka doncic")
        self.assertEqual(kadro.sade_isim("Nikola Jokić"), kadro.sade_isim("Nikola Jokic"))
        self.assertEqual(kadro.sade_isim("Ron Harper Jr."), "ron harper")
        self.assertEqual(kadro.sade_isim("Ronald Holland II"), "ronald holland")
        self.assertEqual(kadro.sade_isim("P.J. Washington"), kadro.sade_isim("PJ Washington"))
        self.assertEqual(kadro.sade_isim("De'Aaron Fox"), "deaaron fox")
        self.assertEqual(kadro.sade_isim("Shai Gilgeous-Alexander"), "shai gilgeous alexander")


class EslemeTesti(unittest.TestCase):
    NBA = {
        1: {"isim": "Hugo González", "takim_id": 10},
        2: {"isim": "Jalen Williams", "takim_id": 20},
        3: {"isim": "Jalen Williams", "takim_id": 30},   # aynı isimde iki oyuncu
        4: {"isim": "Blake Wesley", "takim_id": None},   # NBA'e göre takımsız
        5: {"isim": "Eski Eslesme", "takim_id": 10},
    }

    def test_esleme_sirasi(self):
        espn_oyunculari = {
            101: {"isim": "Hugo Gonzalez", "takim_id": 10},      # aksan farkı, aynı takım
            102: {"isim": "Jalen Williams", "takim_id": 30},     # isim iki kişide, takım ayırır
            103: {"isim": "Blake Wesley", "takim_id": 40},       # takım farklı ama isim tek
            104: {"isim": "Bambaska Bir Isim", "takim_id": 10},  # bilinen kimlikle eşleşir
            105: {"isim": "AK Okereke", "takim_id": 50},         # NBA listesinde yok
            106: {"isim": "Jalen Williams", "takim_id": 60},     # isim iki kişide, takım tutmuyor
        }
        eslesme, takimi_farkli, eslesmeyen = kadro.oyuncu_esle(espn_oyunculari, self.NBA, {104: 5})
        self.assertEqual(eslesme, {101: 1, 102: 3, 103: 4, 104: 5})
        self.assertEqual(takimi_farkli, [103])
        self.assertEqual(eslesmeyen, [105, 106])

    def test_iki_espn_oyuncusu_ayni_nba_oyuncusuna_dusmez(self):
        cift = {201: {"isim": "Hugo Gonzalez", "takim_id": 10}, 202: {"isim": "Hugo González", "takim_id": 10}}
        with self.assertRaises(KaynakHatasi):
            kadro.oyuncu_esle(cift, self.NBA, {})


class PozisyonTesti(unittest.TestCase):
    def test_en_ust_sira_esitlikte_ilk_yuva(self):
        yuvalar = {"PG": [1, 2], "SG": [3, 1, 2], "SF": [4, 3], "PF": [5, 4, 6], "C": [7, 6, 5]}
        self.assertEqual(espn.birincil_pozisyonlar(yuvalar), {
            1: ("PG", 0), 2: ("PG", 1),   # 2: PG'de 2. sıra, SG'de 3. sıra
            3: ("SG", 0), 4: ("SF", 0), 5: ("PF", 0),
            6: ("C", 1),                  # PF'de 3. sıra, C'de 2. sıra
            7: ("C", 0),
        })
        esit = {"PG": [9], "SG": [8, 9], "SF": [8], "PF": [8], "C": [8]}
        self.assertEqual(espn.birincil_pozisyonlar(esit)[8], ("SG", 0))  # dört yuvada da ilk sırada: ilk yuva


class DuzeltmeTesti(unittest.TestCase):
    def oku(self, icerik):
        with tempfile.TemporaryDirectory() as d:
            yol = Path(d) / "pozisyon_duzeltme.csv"
            yol.write_text(icerik, encoding="utf-8")
            return kadro.duzeltmeleri_oku(yol)

    def test_okuma(self):
        self.assertEqual(self.oku("oyuncu_id,isim,pozisyon\n"), {})
        self.assertEqual(self.oku("oyuncu_id,isim,pozisyon\n1642450,Daniss Jenkins,pg\n,,\n202331,Paul George, SF \n"), {1642450: "PG", 202331: "SF"})
        self.assertEqual(kadro.duzeltmeleri_oku(Path("olmayan_dosya.csv")), {})

    def test_gecersiz_kayit_hata_verir(self):
        for bozuk in ("oyuncu_id,isim,pozisyon\n1,x,G\n", "oyuncu_id,isim,pozisyon\nabc,x,PG\n", "isim,pozisyon\nx,PG\n"):
            with self.assertRaises(ValueError):
                self.oku(bozuk)


if __name__ == "__main__":
    unittest.main()
