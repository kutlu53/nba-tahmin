"""NBA resmi sakatlık raporunun ayrıştırılması ve ESPN ile karşılaştırma kuralları. Ağa çıkmaz, Java gerektirmez."""
import unittest

import pandas as pd

import sakatlik_karsilastir
import veritabani
from kaynak import KaynakHatasi, nba_sakatlik

BUGUN = "2026-11-23"


class AyristirmaTesti(unittest.TestCase):
    def tablo(self, satirlar):
        return pd.DataFrame(satirlar, columns=["Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason"])

    def test_isim_cevir(self):
        self.assertEqual(nba_sakatlik.isim_cevir("Cunningham, Cade"), "Cade Cunningham")
        self.assertEqual(nba_sakatlik.isim_cevir("Pippen Jr., Scotty"), "Scotty Pippen Jr.")
        self.assertEqual(nba_sakatlik.isim_cevir("Holland II, Ronald"), "Ronald Holland II")
        self.assertEqual(nba_sakatlik.isim_cevir("Nene"), "Nene")

    def test_kayitlar_ve_bildirmeyen_takim(self):
        kayitlar, bildirmeyen = nba_sakatlik.rapor_ayristir(self.tablo([
            ["11/23/2026", "07:00 (ET)", "MEM@CHA", "Memphis Grizzlies", "Grant, Jerami", "Out", "Injury/Illness - Left Calf Strain"],
            ["11/23/2026", "10:00 (ET)", "UTA@LAL", "Utah Jazz", float("nan"), float("nan"), "NOT YET SUBMITTED"],
            ["11/24/2026", "07:00 (ET)", "DET@ORL", "Detroit Pistons", "Duren, Jalen", "Questionable", float("nan")],
        ]))
        self.assertEqual(kayitlar[0], {"tarih": "2026-11-23", "takim": "Memphis Grizzlies", "isim": "Jerami Grant", "durum": "Out",
                                       "neden": "Injury/Illness - Left Calf Strain"})
        self.assertEqual((kayitlar[1]["tarih"], kayitlar[1]["durum"], kayitlar[1]["neden"]), ("2026-11-24", "Questionable", None))
        self.assertEqual(bildirmeyen, [("2026-11-23", "Utah Jazz")])

    def test_bozuk_rapor_hata_verir(self):
        with self.assertRaises(KaynakHatasi):
            nba_sakatlik.rapor_ayristir(pd.DataFrame({"Team": ["x"]}))
        with self.assertRaises(KaynakHatasi):
            nba_sakatlik.rapor_ayristir(self.tablo([["23.11.2026", "", "", "Utah Jazz", "A, B", "Out", ""]]))
        with self.assertRaises(KaynakHatasi):
            nba_sakatlik.rapor_ayristir(self.tablo([["11/23/2026", "", "", "Utah Jazz", "A, B", float("nan"), "x"]]))


class KarsilastirmaTesti(unittest.TestCase):
    def setUp(self):
        self.c = veritabani.baglan(":memory:")
        veritabani.sema_kur(self.c)
        veritabani.yaz(self.c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2, 3, 4)])
        veritabani.yaz(self.c, "oyuncular", [{"oyuncu_id": i, "isim": f"Oyuncu {i}", "takim_id": 1} for i in range(1, 9)])
        veritabani.yaz(self.c, "maclar", [{"mac_id": "m1", "tarih": BUGUN, "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"},
                                           {"mac_id": "m2", "tarih": BUGUN, "ev_takim_id": 3, "dep_takim_id": 4, "durum": "oynanacak"}])
        veritabani.yaz(self.c, "tahminler", [{"tur": "canli", "tarih": BUGUN, "oyuncu_id": 2, "mac_id": "m1", "istatistik": "sayi", "tahmin": 10.0,
                                               "guven": 50.0, "olusturma": veritabani.simdi_utc()}])

    def tearDown(self):
        self.c.close()

    def yaz(self, kaynak, kayitlar):
        veritabani.goruntu_yaz(self.c, "sakatliklar", {"kaynak": kaynak, "cekim_tarihi": BUGUN}, [
            {"oyuncu_anahtari": str(kimlik if kimlik else isim), "cekim_zamani": veritabani.simdi_utc(), "oyuncu_id": kimlik, "isim": isim or f"Oyuncu {kimlik}",
             "takim_id": takim, "durum": durum, "aciklama": neden, "tahmini_donus": None} for kimlik, isim, takim, durum, neden in kayitlar])

    def isaretler(self):
        df = sakatlik_karsilastir.karsilastir(self.c, BUGUN)
        return df, {r["Oyuncu"]: r["İşaret"] for _, r in df.iterrows()}

    def test_resmi_rapor_yoksa_bos(self):
        self.yaz("espn", [(1, None, 1, "Out", None)])
        self.assertTrue(sakatlik_karsilastir.karsilastir(self.c, BUGUN).empty)
        self.assertIn("karşılaştırma yapılamadı", sakatlik_karsilastir.ozet_metni(sakatlik_karsilastir.karsilastir(self.c, BUGUN), BUGUN))

    def test_kurallar(self):
        self.yaz("espn", [(1, None, 1, "Out", None), (3, None, 1, "Out", None), (4, None, 1, "Day-To-Day", None), (5, None, 1, "Day-To-Day", None),
                          (8, None, 3, "Out", None)])
        self.yaz("nba_resmi", [
            (1, None, 1, "Out", "Injury/Illness - Diz"),                 # iki kaynak da Out: uyumlu
            (2, None, 1, "Out", "Injury/Illness - Ayak bileği"),         # resmi Out, ESPN'de yok; üstelik tahmin üretilmiş
            (3, None, 1, "Probable", "Injury/Illness - Sırt"),           # ESPN Out, resmi Probable
            (4, None, 1, "Questionable", "Injury/Illness - Kasık"),      # ESPN Day-To-Day, resmi Questionable: uyumlu
            (5, None, 1, "Available", "Injury/Illness - Parmak"),        # ESPN Day-To-Day, resmi Available: fark
            (6, None, 1, "Doubtful", "Injury/Illness - Omuz"),           # resmi Doubtful, ESPN'de yok: fark
            (7, None, 1, "Out", "G League - Two-Way"),                   # G Ligi: çelişki sayılmaz
            (None, "(rapor henüz verilmedi)", 3, sakatlik_karsilastir.BILDIRILMEDI, None),
            (None, "Takım İki Oyuncusu", 2, "Out", "Injury/Illness - Bilek"),   # takım 2'den ESPN hiç kayıt döndürmedi
        ])
        df, i = self.isaretler()
        self.assertEqual(i["Oyuncu 1"], "")
        self.assertEqual(i["Oyuncu 2"], "ÇELİŞKİ: resmi raporda Out; ESPN listesinde yok")
        self.assertEqual(i["Oyuncu 3"], "ÇELİŞKİ: ESPN Out; resmi rapor Probable")
        self.assertEqual(i["Oyuncu 4"], "")
        self.assertEqual(i["Oyuncu 5"], "fark: ESPN Day-To-Day; resmi rapor Available")
        self.assertEqual(i["Oyuncu 6"], "fark: resmi raporda Doubtful; ESPN listesinde yok")
        self.assertEqual(i["Oyuncu 7"], "G Ligi (sakatlık değil)")
        # Aynı G Ligi oyuncusuna tahmin üretilmiş olsaydı çelişki sayılırdı.
        self.assertEqual(sakatlik_karsilastir._hukum(None, "Out", "G League - Two-Way", True, True, tahmin_var=True),
                         "ÇELİŞKİ: resmi raporda Out; ESPN listesinde yok")
        self.assertEqual(i["Oyuncu 8"], "resmi rapor henüz verilmedi")                      # takım 3 raporu vermedi: karşılaştırılamaz
        self.assertEqual(i["Takım İki Oyuncusu"], "ÇELİŞKİ: resmi raporda Out; ESPN veri yok")
        self.assertEqual(i["(takım raporu henüz vermedi)"], "resmi rapor henüz verilmedi")
        # Çelişkiler en üstte; tahmin üretilmiş oyuncu işaretli.
        self.assertTrue(all(x.startswith("ÇELİŞKİ") for x in df["İşaret"].head(3)))
        self.assertEqual(df.set_index("Oyuncu").loc["Oyuncu 2", "Tahmin üretildi"], "EVET")
        ozet = sakatlik_karsilastir.ozet_metni(df, BUGUN)
        self.assertIn("ÇELİŞKİ: 3", ozet)
        self.assertIn("Resmi raporda Out olduğu halde tahmin üretilmiş oyuncu: 1: Oyuncu 2", ozet)

    def test_o_gun_oynamayan_takim_tabloya_girmez(self):
        veritabani.yaz(self.c, "takimlar", [{"takim_id": 9, "kisaltma": "T9", "isim": "Takım 9"}])
        self.yaz("nba_resmi", [(1, None, 1, "Out", "x"), (None, "Başka Takım Oyuncusu", 9, "Out", "x")])
        df, i = self.isaretler()
        self.assertNotIn("Başka Takım Oyuncusu", i)


if __name__ == "__main__":
    unittest.main()
