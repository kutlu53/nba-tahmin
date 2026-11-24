"""nba.com sayfa dosyalarından veri okuma (kaynak/nba_cdn.py) ve kaynak seçimi. Ağa çıkmaz: indirme işlevleri taklit edilir."""
import json
import logging
import unittest

import config
import kaynak
from kaynak import KaynakHatasi, nba_cdn, nba_stats

EV, DEP = 1610612737, 1610612765
ISTATISTIK = {"fieldGoalsMade": 4, "fieldGoalsAttempted": 9, "threePointersMade": 1, "threePointersAttempted": 3, "freeThrowsMade": 2,
              "freeThrowsAttempted": 2, "reboundsOffensive": 1, "reboundsDefensive": 4, "reboundsTotal": 5, "assists": 3, "steals": 1,
              "blocks": 0, "turnovers": 2, "foulsPersonal": 3, "points": 11}


def mac(kimlik, tarih, durum=3, ertelendi="N", ev=EV, dep=DEP):
    return {"gameId": kimlik, "gameStatus": durum, "postponedStatus": ertelendi, "gameDateEst": f"{tarih}T00:00:00Z",
            "gameDateTimeUTC": f"{tarih}T23:30:00Z", "arenaCity": " Atlanta ",
            "homeTeam": {"teamId": ev, "teamTricode": "ATL", "score": 107}, "awayTeam": {"teamId": dep, "teamTricode": "DET", "score": 97}}


def fikstur_dosyasi(maclar, sezon=None):
    return json.dumps({"leagueSchedule": {"seasonYear": sezon or config.SEZON, "gameDates": [{"gameDate": "x", "games": maclar}]}})


def sayfa(mac_id, durum=3, sure="16:29", takim_suresi="240:00"):
    """Maç sayfası: takım başına 5 ilk beş (40:00), 1 yedek (süresi parametre) ve 1 oynamayan oyuncu."""
    def takim(kimlik, taban):
        oyuncular = [{"personId": taban + i, "firstName": "Ad", "familyName": f"Soyad{i}", "position": "G" if i < 5 else "",
                      "statistics": {**ISTATISTIK, "minutes": "40:00" if i < 5 else sure}} for i in range(6)]
        oyuncular.append({"personId": taban + 9, "firstName": "Oynamayan", "familyName": "Biri", "position": "", "comment": "DNP",
                          "statistics": {k: None for k in ISTATISTIK} | {"minutes": ""}})
        return {"teamId": kimlik, "players": oyuncular, "statistics": {**ISTATISTIK, "turnovers": 12, "points": 107, "minutes": takim_suresi}}

    oyun = {"gameId": mac_id, "gameStatus": durum, "homeTeam": takim(EV, 100), "awayTeam": takim(DEP, 200),
            "postgameCharts": {"homeTeam": {"statistics": {"turnoversTotal": 14}}, "awayTeam": {"statistics": {"turnoversTotal": 13}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"game": oyun}}})}</script></html>'


def canli(mac_id):
    def takim(kimlik, taban):
        return {"teamId": kimlik, "statistics": {**ISTATISTIK, "turnovers": 12, "turnoversTotal": 15, "minutes": "PT240M00.00S"},
                "players": [{"personId": taban + i, "name": f"Canli {i}", "starter": "1" if i < 5 else "0", "played": "1" if i < 6 else "0",
                             "statistics": {**ISTATISTIK, "minutes": "PT40M00.00S" if i < 5 else "PT16M31.00S"}} for i in range(7)]}

    return {"gameId": mac_id, "gameStatus": 3, "homeTeam": takim(EV, 100), "awayTeam": takim(DEP, 200)}


class NbaCdnTesti(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.eski = (nba_cdn._indir, nba_cdn._cagir)
        nba_cdn._fikstur_onbellek = (0.0, None)
        nba_cdn._kutu_onbellek.clear()
        self.dosyalar = {nba_cdn.FIKSTUR_URL: fikstur_dosyasi([mac("0022600001", "2026-11-20"), mac("0022600002", "2026-11-22")])}
        nba_cdn._indir = lambda url, ad, basliklar=None: self.indir(url)
        nba_cdn._cagir = lambda ad, islev, bekleme=None: self.canli_kutu()      # yalnızca canlı besleme bu yoldan çağrılır

    def tearDown(self):
        nba_cdn._indir, nba_cdn._cagir = self.eski
        nba_cdn._fikstur_onbellek = (0.0, None)
        nba_cdn._kutu_onbellek.clear()
        logging.disable(logging.NOTSET)

    def indir(self, url):
        if url not in self.dosyalar:
            raise KaynakHatasi(f"alınamadı: {url}")
        return self.dosyalar[url]

    def canli_kutu(self):
        raise KaynakHatasi("canlı besleme de yok")

    def sayfa_koy(self, mac_id, **kw):
        self.dosyalar[nba_cdn.MAC_SAYFASI_URL.format(mac_id=mac_id)] = sayfa(mac_id, **kw)

    def test_fikstur(self):
        self.dosyalar[nba_cdn.FIKSTUR_URL] = fikstur_dosyasi([
            mac("0022600001", "2026-11-20"), mac("0022600002", "2026-11-25", durum=1), mac("0022600003", "2026-11-26", durum=1, ertelendi="Y"),
            mac("0022600004", "2026-12-15", durum=1, ev=0), mac("0012600001", "2026-10-05")])            # sonuncusu hazırlık maçı
        maclar, belirsiz = nba_cdn.fikstur()
        self.assertEqual([(m["mac_id"], m["durum"], m["ev_sayi"]) for m in maclar],
                         [("0022600001", "oynandi", 107), ("0022600002", "oynanacak", None), ("0022600003", "ertelendi", None)])
        self.assertEqual(belirsiz, ["0022600004"])
        self.assertEqual(maclar[0], {"mac_id": "0022600001", "tarih": "2026-11-20", "baslama_utc": "2026-11-20T23:30:00Z", "ev_takim_id": EV,
                                     "dep_takim_id": DEP, "durum": "oynandi", "ev_sayi": 107, "dep_sayi": 97, "salon_sehri": "Atlanta"})

    def test_baska_sezon_reddedilir(self):
        with self.assertRaises(KaynakHatasi):
            nba_cdn.fikstur(sezon=config.ONCEKI_SEZON)
        self.dosyalar[nba_cdn.FIKSTUR_URL] = fikstur_dosyasi([mac("0022500001", "2025-11-20")], sezon=config.ONCEKI_SEZON)
        with self.assertRaises(KaynakHatasi):
            nba_cdn.fikstur()

    def test_oyuncu_listesi(self):
        satirlar = [[i, f"Soyad{i}", "Ad", 0 if i == 3 else EV] for i in range(1, 451)]
        satirlar[0] = [1, "Bogdanović", "Bogdan", EV]
        self.dosyalar[nba_cdn.OYUNCU_LISTESI_URL] = json.dumps({"parameters": {"Season": config.SEZON}, "resultSets": [
            {"headers": ["PERSON_ID", "PLAYER_LAST_NAME", "PLAYER_FIRST_NAME", "TEAM_ID"], "rowSet": satirlar}]}, ensure_ascii=False)
        liste = nba_cdn.oyuncu_listesi()
        self.assertEqual(liste[0], {"oyuncu_id": 1, "isim": "Bogdan Bogdanović", "takim_id": EV})
        self.assertIsNone(liste[2]["takim_id"])                              # takımı olmayan oyuncu
        self.dosyalar[nba_cdn.OYUNCU_LISTESI_URL] = json.dumps({"parameters": {"Season": config.SEZON}, "resultSets": [
            {"headers": ["PERSON_ID", "PLAYER_LAST_NAME", "PLAYER_FIRST_NAME", "TEAM_ID"], "rowSet": satirlar[:50]}]})
        with self.assertRaises(KaynakHatasi):                                # eksik liste yazılmaz
            nba_cdn.oyuncu_listesi()

    def test_mac_kayitlari_sayfadan(self):
        self.sayfa_koy("0022600001")
        self.sayfa_koy("0022600002", sure="16:30")
        once = dict(nba_cdn.kutu_kaynaklari)
        df = nba_cdn.oyuncu_mac_kayitlari(tarihten="2026-11-20", tarihe="2026-11-22")
        self.assertEqual(list(df.columns[:len(nba_stats.MAC_KAYDI_SUTUNLARI)]), nba_stats.MAC_KAYDI_SUTUNLARI)
        self.assertEqual(len(df), 24)                                        # 2 maç × 2 takım × 6 oynayan; oynamayan yok
        yedek = df[df["PLAYER_ID"] == 105].set_index("GAME_ID")
        self.assertEqual(yedek["MIN"].to_dict(), {"0022600001": 16, "0022600002": 17})     # 16:29 aşağı, 16:30 yukarı yuvarlanır
        s = yedek.loc["0022600001"]
        self.assertEqual((s["PLAYER_NAME"], s["TEAM_ID"], s["GAME_DATE"], s["MATCHUP"], s["PTS"], s["REB"], s["FG3M"], s["TOV"]),
                         ("Ad Soyad5", EV, "2026-11-20", "ATL vs. DET", 11, 5, 1, 2))
        self.assertEqual(len(nba_cdn.oyuncu_mac_kayitlari(tarihten="2026-11-21")), 12)
        self.assertTrue(nba_cdn.oyuncu_mac_kayitlari(tarihten="2026-11-23", bos_olabilir=True).empty)
        self.assertEqual(nba_cdn.kutu_kaynaklari, {"sayfa": once["sayfa"] + 2, "canli": once["canli"]})      # iki maç da sayfadan, birer kez

    def test_takim_kayitlari_ve_kutu_skoru(self):
        self.sayfa_koy("0022600001")
        self.sayfa_koy("0022600002")
        df = nba_cdn.takim_mac_kayitlari(tarihe="2026-11-20")
        self.assertEqual(list(df.columns), nba_stats.TAKIM_KAYDI_SUTUNLARI)
        self.assertEqual(df.set_index("TEAM_ID")[["MIN", "PTS", "TOV", "OREB", "DREB"]].to_dict("index"),
                         {EV: {"MIN": 240, "PTS": 107, "TOV": 14, "OREB": 1, "DREB": 4},      # top kaybı: takıma yazılanlar dahil toplam
                          DEP: {"MIN": 240, "PTS": 107, "TOV": 13, "OREB": 1, "DREB": 4}})
        kutu = nba_cdn.kutu_skoru("0022600001")
        self.assertEqual(len(kutu), 12)
        self.assertEqual(kutu[100], {"takim_id": EV, "ilk_bes": 1, "dakika": 40.0})
        self.assertEqual(kutu[205], {"takim_id": DEP, "ilk_bes": 0, "dakika": 16 + 29 / 60})
        self.assertNotIn(109, kutu)

    def test_bozuk_takim_dakikasi_oyunculardan_tamamlanir(self):
        # Takım satırında 60:00 yazıyor; oyuncu dakikaları 5 × 40 + 40 = 240 ediyor.
        self.sayfa_koy("0022600001", sure="40:00", takim_suresi="60:00")
        self.assertEqual(set(nba_cdn.takim_mac_kayitlari(tarihe="2026-11-20")["MIN"]), {240})
        # Oyuncu toplamı da geçerli bir süre vermiyorsa kaynaktaki değer kalır; yükleyici bunu hata olarak görür.
        self.sayfa_koy("0022600002", sure="16:29", takim_suresi="60:00")
        self.assertEqual(set(nba_cdn.takim_mac_kayitlari(tarihten="2026-11-22")["MIN"]), {60})

    def test_sayfa_yoksa_canli_besleme(self):
        self.canli_kutu = lambda: canli("0022600001")
        once = dict(nba_cdn.kutu_kaynaklari)
        kutu = nba_cdn.kutu_skoru("0022600001")
        self.assertEqual((kutu[105]["ilk_bes"], round(kutu[105]["dakika"], 4)), (0, round(16 + 31 / 60, 4)))
        self.assertEqual(nba_cdn.kutu_kaynaklari["canli"], once["canli"] + 1)
        df = nba_cdn.takim_mac_kayitlari(tarihe="2026-11-20")
        self.assertEqual(set(df["TOV"]), {15})                               # canlı beslemede toplam top kaybı kendi alanından

    def test_bitmemis_mac_ve_eksik_ilk_bes(self):
        self.sayfa_koy("0022600001", durum=2)
        with self.assertRaises(KaynakHatasi):                                # sayfa "bitmedi" diyor, canlı besleme de yok
            nba_cdn.kutu_skoru("0022600001")
        bozuk = json.loads(sayfa("0022600002").split('json">')[1].split("</script>")[0])
        bozuk["props"]["pageProps"]["game"]["homeTeam"]["players"][0]["position"] = ""
        self.dosyalar[nba_cdn.MAC_SAYFASI_URL.format(mac_id="0022600002")] = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(bozuk)}</script>'
        with self.assertRaises(KaynakHatasi):                                # ev sahibinde 4 ilk beş
            nba_cdn.kutu_skoru("0022600002")


class KaynakSecimiTesti(unittest.TestCase):
    def test_varsayilan_stats_ve_secim(self):
        eski = config.VERI_KAYNAGI
        try:
            config.VERI_KAYNAGI = "stats"
            self.assertIs(kaynak.mac_kaynagi(), nba_stats)
            config.VERI_KAYNAGI = "cdn"
            self.assertIs(kaynak.mac_kaynagi(), nba_cdn)
            config.VERI_KAYNAGI = "baska"
            with self.assertRaises(KaynakHatasi):
                kaynak.mac_kaynagi()
        finally:
            config.VERI_KAYNAGI = eski

    def test_iki_kaynak_ayni_islevleri_sunar(self):
        for ad in ("fikstur", "oyuncu_listesi", "oyuncu_mac_kayitlari", "takim_mac_kayitlari", "kutu_skoru"):
            self.assertTrue(callable(getattr(nba_cdn, ad)) and callable(getattr(nba_stats, ad)), ad)


if __name__ == "__main__":
    unittest.main()
