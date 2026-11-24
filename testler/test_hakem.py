"""Hakem atama sayfasının ayrıştırılması, takım adı eşlemesi, hakem endeksleri ve etken. Ağa çıkmaz."""
import unittest

import config
import tahmin
import veritabani
import yukle
from etkenler import Mac, Oyuncu, hakem
from kaynak import KaynakHatasi, nba_resmi

SAYFA = """
<html><body><h1>NBA Referee Assignments</h1>
<div class="entry-meta">November 23, 2026</div><p>Referee assignments are posted at approximately 9:00am ET each game day.</p>
<table class="table"><thead><tr><th class="tableTitle">Game</th><th class="tableTitle">Crew Chief</th><th class="tableTitle">Referee</th>
<th class="tableTitle">Umpire</th><th class="tableTitle">Alternate</th></tr></thead><tbody>
<tr><td>Memphis @ Charlotte</td><td> <a href="#">James Williams</a> (#60) </td><td><a href="#">Tre Maddox</a> (#23)</td><td><a href="#">JP Primm</a> (#82)</td><td></td></tr>
<tr><td>Utah @ L.A. Lakers</td><td>Scott Foster (#48)</td><td>Sha&#039;Rae Mitchell (#98)</td><td>Agon Abazi (#88)</td><td></td></tr>
</tbody></table>
<h1>G League Referee Assignments</h1><div>November 23, 2026</div>
<table class="table"><thead><tr><th>Game</th><th>Crew Chief</th><th>Referee</th><th>Umpire</th><th>Alternate</th></tr></thead>
<tbody><tr><td>Salt Lake City @ Stockton</td><td>Evan Singletary (#65)</td><td>Billy McClatchy (#31)</td><td>Reihen Knysh (#47)</td><td></td></tr></tbody></table>
</body></html>"""


class AtamaTesti(unittest.TestCase):
    def test_ayristirma(self):
        a = nba_resmi.atama_ayristir(SAYFA)
        self.assertEqual(a["tarih"], "2026-11-23")
        self.assertEqual([m["mac"] for m in a["maclar"]], ["Memphis @ Charlotte", "Utah @ L.A. Lakers"])     # G League tablosu alınmaz
        self.assertEqual(a["maclar"][0]["hakemler"], [("James Williams", 60, "bas_hakem"), ("Tre Maddox", 23, "hakem"), ("JP Primm", 82, "yardimci")])
        self.assertEqual(a["maclar"][1]["hakemler"][1], ("Sha'Rae Mitchell", 98, "hakem"))

    def test_bozuk_sayfa_hata_verir(self):
        with self.assertRaises(KaynakHatasi):
            nba_resmi.atama_ayristir("<html><body>bakımdayız</body></html>")
        with self.assertRaises(KaynakHatasi):
            nba_resmi.atama_ayristir(SAYFA.replace("Crew Chief", "Chief"))
        self.assertEqual(nba_resmi.atama_ayristir("<h1>NBA Referee Assignments</h1> November 24, 2026 <p>No games.</p>"), {"tarih": "2026-11-24", "maclar": []})

    def test_takim_adlari(self):
        c = veritabani.baglan(":memory:")
        veritabani.sema_kur(c)
        veritabani.yaz(c, "takimlar", [{"takim_id": i, "kisaltma": k, "isim": ad} for i, (k, ad) in enumerate((
            ("LAL", "Los Angeles Lakers"), ("LAC", "Los Angeles Clippers"), ("POR", "Portland Trail Blazers"), ("GSW", "Golden State Warriors"),
            ("UTA", "Utah Jazz"), ("NYK", "New York Knicks"), ("OKC", "Oklahoma City Thunder")), 1)])
        adlar = yukle._takim_adlari(c)
        self.assertEqual((adlar["la lakers"], adlar["la clippers"], adlar["portland"], adlar["golden state"], adlar["utah"], adlar["new york"], adlar["oklahoma city"]),
                         (1, 2, 3, 4, 5, 6, 7))
        c.close()


def kur():
    """Takım 1–2 dört maç oynar. Hakem 100 ilk iki maçı yönetir (60'ar serbest atış, 50'şer faul), hakem 200 son iki maçı (40'ar SA, 30'ar faul)."""
    c = veritabani.baglan(":memory:")
    veritabani.sema_kur(c)
    veritabani.yaz(c, "takimlar", [{"takim_id": t, "kisaltma": f"T{t}", "isim": f"Takım {t}"} for t in (1, 2)])
    veritabani.yaz(c, "oyuncular", [{"oyuncu_id": 10, "isim": "Çizgiye Giden", "takim_id": 1, "pozisyon": "PG"}])
    veritabani.yaz(c, "hakemler", [{"hakem_id": 100, "isim": "Düdüğü Bol", "forma_no": 1}, {"hakem_id": 200, "isim": "Düdüğü Kıt", "forma_no": 2},
                                   {"hakem_id": 300, "isim": "Yeni Hakem", "forma_no": 3}])
    veritabani.yaz(c, "maclar", [{"mac_id": f"g{i}", "tarih": f"2026-11-0{i}", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynandi"} for i in range(1, 5)]
                   + [{"mac_id": "bugun", "tarih": "2026-11-10", "ev_takim_id": 1, "dep_takim_id": 2, "durum": "oynanacak"}])
    for i in range(1, 5):
        sa, faul = (30, 25) if i <= 2 else (20, 15)                  # takım başına; maç toplamı iki katı
        veritabani.yaz(c, "takim_mac", [{"takim_id": t, "mac_id": f"g{i}", "rakip_id": 3 - t, "ev_mi": int(t == 1), "dakika": 240.0,
                                          "serbest_deneme": sa, "faul": faul} for t in (1, 2)])
        veritabani.yaz(c, "hakem_mac", [{"mac_id": f"g{i}", "hakem_id": 100 if i <= 2 else 200, "gorev": "bas_hakem", "kaynak": "kutu_skoru"}])
        veritabani.yaz(c, "oyuncu_mac", [{"oyuncu_id": 10, "mac_id": f"g{i}", "takim_id": 1, "rakip_id": 2, "ev_mi": 1, "ilk_bes": 1, "dakika": 30.0,
                                           "sayi": 20, "ribaund": 0, "asist": 0, "ucluk": 0, "top_calma": 0, "blok": 0, "top_kaybi": 0,
                                           "saha_ici_isabet": 6, "saha_ici_deneme": 12, "ucluk_deneme": 0, "serbest_isabet": 8, "serbest_deneme": 10}])
    return c


class HakemEtkeniTesti(unittest.TestCase):
    def setUp(self):
        self.c = kur()
        self.oyuncu, self.mac = Oyuncu(10, "Çizgiye Giden", 1, "PG"), Mac("bugun", "2026-11-10", 1, 2)

    def tearDown(self):
        self.c.close()

    def test_endeksler_elle_hesap(self):
        e = hakem.endeksler(tahmin.Baglam(self.c, "2026-11-10"))
        # Hakem 100'ün maçlarında 60 SA; her maç için beklenen = diğer üç maçın ortalaması = (60 + 40 + 40) / 3.
        self.assertAlmostEqual(e[100]["sa"], 120 / (2 * 140 / 3))
        self.assertAlmostEqual(e[200]["sa"], 80 / (2 * 160 / 3))
        self.assertAlmostEqual(e[100]["faul"], 100 / (2 * (50 + 30 + 30) / 3))
        self.assertEqual(e[100]["mac"], 2)
        k = config.HAKEM_K
        self.assertAlmostEqual(e[100]["sa_duz"], (2 * e[100]["sa"] + k) / (2 + k))        # 2 maç: 1,00'e güçlü biçimde çekilir
        self.assertNotIn(300, e)

    def test_carpan(self):
        veritabani.yaz(self.c, "hakem_mac", [{"mac_id": "bugun", "hakem_id": h, "gorev": "hakem", "kaynak": "atama"} for h in (100, 300)])
        b = tahmin.Baglam(self.c, "2026-11-10")
        e = hakem.endeksler(b)
        ekip = (e[100]["sa_duz"] + 1.0) / 2                                              # yeni hakem nötr sayılır
        s = hakem.hesapla(self.oyuncu, self.mac, "sayi", b)
        self.assertAlmostEqual(s.carpan, 1 + (32 / 80) * (ekip - 1))                     # sayılarının %40'ı serbest atıştan
        self.assertGreater(s.carpan, 1.0)
        self.assertEqual(hakem.hesapla(self.oyuncu, self.mac, "ribaund", b).carpan, 1.0)

    def test_atama_yoksa_veri_yok(self):
        s = hakem.hesapla(self.oyuncu, self.mac, "sayi", tahmin.Baglam(self.c, "2026-11-10"))
        self.assertEqual((s.carpan, s.veri_var), (1.0, False))

    def test_sonraki_maclar_endekse_girmez(self):
        e = hakem.endeksler(tahmin.Baglam(self.c, "2026-11-03"))                          # yalnızca g1 ve g2 görülür
        self.assertEqual(set(e), {100})
        self.assertAlmostEqual(e[100]["sa"], 1.0)                                         # iki maç da aynı: beklenenle eşit

    def test_profil_tablosu(self):
        b = tahmin.Baglam(self.c, "2026-11-10")
        for _ in range(2):
            n = hakem.profili_yaz(self.c, b, "2026-11-10")
        self.assertEqual((n, self.c.execute("SELECT COUNT(*) FROM hakem_profili").fetchone()[0]), (2, 2))


if __name__ == "__main__":
    unittest.main()
