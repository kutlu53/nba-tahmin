"""nba_api çağrıları: takımlar, fikstür, oyuncu maç kayıtları, kutu skoru.

stats.nba.com belgesiz bir kaynaktır. Bu yüzden her çağrı beklemeli ve yeniden
denemelidir; dönen tabloda beklenen sütun yoksa ya da tablo boşsa hata verilir,
sessizce boş veri yazılmaz.
"""
import logging
import re
import time

from nba_api.live.nba.endpoints import boxscore as canli_boxscore
from nba_api.stats import endpoints
from nba_api.stats.static import teams as statik_takimlar

import config
from kaynak import KaynakHatasi

log = logging.getLogger(__name__)

NORMAL_SEZON_ON_EKI = "002"  # maç kimliğinin ilk üç hanesi; 001 hazırlık, 006 kupa finali
_son_istek = 0.0


def _cagir(ad, islev, bekleme=None):
    """İstekler arasında bekler; hata olursa artan beklemeyle yeniden dener."""
    global _son_istek
    son_hata = None
    bekleme = config.ISTEK_BEKLEME_SN if bekleme is None else bekleme
    for deneme in range(1, config.DENEME_SAYISI + 1):
        bekle = bekleme - (time.monotonic() - _son_istek)
        if bekle > 0:
            time.sleep(bekle)
        try:
            return islev()
        except Exception as e:  # ağ hatası, zaman aşımı, bozuk JSON
            son_hata = e
            log.warning("%s: deneme %d/%d başarısız: %s: %s", ad, deneme, config.DENEME_SAYISI, type(e).__name__, e)
            if deneme < config.DENEME_SAYISI:
                time.sleep(5 * deneme)
        finally:
            _son_istek = time.monotonic()
    raise KaynakHatasi(f"{ad}: {config.DENEME_SAYISI} denemede alınamadı ({type(son_hata).__name__}: {son_hata})")


def _dogrula(df, sutunlar, ad, bos_olabilir=False):
    eksik = [s for s in sutunlar if s not in df.columns]
    if eksik:
        raise KaynakHatasi(f"{ad}: beklenen sütunlar yok: {eksik}")
    if df.empty and not bos_olabilir:
        raise KaynakHatasi(f"{ad}: tablo boş döndü")
    return df


def takimlar():
    """30 takım: [{'takim_id', 'kisaltma', 'isim'}, ...] (nba_api içindeki sabit liste)."""
    liste = [{"takim_id": t["id"], "kisaltma": t["abbreviation"], "isim": t["full_name"]} for t in statik_takimlar.get_teams()]
    if len(liste) != 30:
        raise KaynakHatasi(f"takımlar: 30 takım bekleniyordu, {len(liste)} geldi")
    return liste


def oyuncu_listesi(sezon=None):
    """Sezonun tüm oyuncuları ve güncel takımları (PlayerIndex, tek çağrı).

    Döndürür: [{'oyuncu_id', 'isim', 'takim_id'}, ...]; takımı olmayan (serbest
    kalmış) oyuncuda takim_id None olur.
    """
    sezon = sezon or config.SEZON
    ad = f"PlayerIndex {sezon}"
    df = _cagir(ad, lambda: endpoints.PlayerIndex(season=sezon, timeout=config.ZAMAN_ASIMI_SN).get_data_frames()[0])
    df = _dogrula(df, ["PERSON_ID", "PLAYER_FIRST_NAME", "PLAYER_LAST_NAME", "TEAM_ID"], ad)
    if len(df) < 400:
        raise KaynakHatasi(f"{ad}: en az 400 oyuncu bekleniyordu, {len(df)} geldi")
    return [
        {
            "oyuncu_id": int(s.PERSON_ID),
            "isim": f"{s.PLAYER_FIRST_NAME or ''} {s.PLAYER_LAST_NAME or ''}".strip(),
            "takim_id": int(s.TEAM_ID) or None,
        }
        for s in df.itertuples(index=False)
    ]


FIKSTUR_SUTUNLARI = [
    "gameId", "gameDateEst", "gameDateTimeUTC", "gameStatus", "postponedStatus",
    "homeTeam_teamId", "awayTeam_teamId", "homeTeam_score", "awayTeam_score", "arenaCity",
]


def fikstur(sezon=None):
    """Normal sezon fikstürü; maclar tablosunun sütun adlarıyla sözlük listesi.

    Takımı henüz belli olmayan maçlar (kupa eleme turları) ikinci liste olarak döner.
    """
    sezon = sezon or config.SEZON
    ad = f"ScheduleLeagueV2 {sezon}"
    df = _cagir(ad, lambda: endpoints.ScheduleLeagueV2(season=sezon, timeout=config.ZAMAN_ASIMI_SN).get_data_frames()[0])
    df = _dogrula(df, FIKSTUR_SUTUNLARI, ad)
    df = df[df["gameId"].str.startswith(NORMAL_SEZON_ON_EKI)]
    if df.empty:
        raise KaynakHatasi(f"{ad}: normal sezon maçı yok")

    maclar, belirsiz = [], []
    for s in df.itertuples(index=False):
        if not s.homeTeam_teamId or not s.awayTeam_teamId:
            belirsiz.append(s.gameId)
            continue
        oynandi = s.gameStatus == 3
        if s.postponedStatus != "N" and not oynandi:
            durum = "ertelendi"
        else:
            durum = "oynandi" if oynandi else "oynanacak"
        maclar.append({
            "mac_id": s.gameId,
            "tarih": s.gameDateEst[:10],
            "baslama_utc": s.gameDateTimeUTC,
            "ev_takim_id": int(s.homeTeam_teamId),
            "dep_takim_id": int(s.awayTeam_teamId),
            "durum": durum,
            "ev_sayi": int(s.homeTeam_score) if oynandi else None,
            "dep_sayi": int(s.awayTeam_score) if oynandi else None,
            "salon_sehri": (s.arenaCity or "").strip() or None,
        })
    return maclar, belirsiz


MAC_KAYDI_SUTUNLARI = [
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "MIN",
    "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "REB", "AST", "STL", "BLK", "TOV", "PF", "PTS",
]


def oyuncu_mac_kayitlari(sezon=None, tarihten=None, tarihe=None, bos_olabilir=False):
    """Tüm ligin oyuncu maç kayıtları tek çağrıda (LeagueGameLog, oyuncu modu).

    tarihten / tarihe: 'YYYY-AA-GG' (ABD tarihi), ikisi de dahil.
    """
    sezon = sezon or config.SEZON
    cevir = lambda t: f"{t[5:7]}/{t[8:10]}/{t[:4]}" if t else ""
    ad = f"LeagueGameLog oyuncu {sezon} {tarihten or ''}..{tarihe or ''}"
    df = _cagir(ad, lambda: endpoints.LeagueGameLog(
        season=sezon,
        season_type_all_star=config.SEZON_TURU,
        player_or_team_abbreviation="P",
        date_from_nullable=cevir(tarihten),
        date_to_nullable=cevir(tarihe),
        timeout=config.ZAMAN_ASIMI_SN,
    ).get_data_frames()[0])
    return _dogrula(df, MAC_KAYDI_SUTUNLARI, ad, bos_olabilir)


TAKIM_KAYDI_SUTUNLARI = [
    "TEAM_ID", "GAME_ID", "MIN", "PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "TOV", "PF",
]


def takim_mac_kayitlari(sezon=None, tarihten=None, tarihe=None, bos_olabilir=False):
    """Tüm ligin takım maç kutu skorları tek çağrıda (LeagueGameLog, takım modu)."""
    sezon = sezon or config.SEZON
    cevir = lambda t: f"{t[5:7]}/{t[8:10]}/{t[:4]}" if t else ""
    ad = f"LeagueGameLog takım {sezon} {tarihten or ''}..{tarihe or ''}"
    df = _cagir(ad, lambda: endpoints.LeagueGameLog(
        season=sezon,
        season_type_all_star=config.SEZON_TURU,
        player_or_team_abbreviation="T",
        date_from_nullable=cevir(tarihten),
        date_to_nullable=cevir(tarihe),
        timeout=config.ZAMAN_ASIMI_SN,
    ).get_data_frames()[0])
    return _dogrula(df, TAKIM_KAYDI_SUTUNLARI, ad, bos_olabilir)


def nba_com_tempo(sezon=None):
    """nba.com takım tempo değerleri (PACE). Yalnızca doğrulama içindir: {takim_id: (tempo, maç sayısı)}"""
    sezon = sezon or config.SEZON
    ad = f"LeagueDashTeamStats Advanced {sezon}"
    df = _cagir(ad, lambda: endpoints.LeagueDashTeamStats(
        season=sezon, season_type_all_star=config.SEZON_TURU,
        measure_type_detailed_defense="Advanced", per_mode_detailed="PerGame", timeout=config.ZAMAN_ASIMI_SN,
    ).get_data_frames()[0])
    df = _dogrula(df, ["TEAM_ID", "PACE", "GP"], ad)
    return {int(s.TEAM_ID): (float(s.PACE), int(s.GP)) for s in df.itertuples(index=False)}


TAKIP_OLCULERI = {  # ölçü türü: {uç nokta sütunu: bizim sütunumuz}
    "Passing": {"POTENTIAL_AST": "olasi_asist", "PASSES_MADE": "pas"},
    "Rebounding": {"REB_CHANCES": "ribaund_firsati"},
    "Possessions": {"TOUCHES": "top_dokunusu"},
}


def takip_gunu(tarih, sezon=None):
    """Bir günün (ABD tarihi) oyuncu takip verisi: {oyuncu_id: {'olasi_asist', 'pas', 'ribaund_firsati', 'top_dokunusu'}}

    LeagueDashPtStats tek günlük tarih aralığıyla çağrılır; oyuncu günde en çok bir maç oynadığı için
    değerler maç bazındadır. Üç ölçü için üç çağrı yapılır. Bir ölçüde hiç fırsatı olmayan oyuncu o
    tabloda yer almaz; öbür ölçülerde varsa değeri 0 sayılır.
    """
    sezon = sezon or config.SEZON
    gun = f"{tarih[5:7]}/{tarih[8:10]}/{tarih[:4]}"
    sonuc = {}
    for olcu, sutunlar in TAKIP_OLCULERI.items():
        ad = f"LeagueDashPtStats {olcu} {tarih}"
        df = _cagir(ad, lambda: endpoints.LeagueDashPtStats(
            season=sezon, season_type_all_star=config.SEZON_TURU, player_or_team="Player", pt_measure_type=olcu,
            per_mode_simple="Totals", date_from_nullable=gun, date_to_nullable=gun, timeout=config.ZAMAN_ASIMI_SN,
        ).get_data_frames()[0])
        df = _dogrula(df, ["PLAYER_ID"] + list(sutunlar), ad)
        for s in df.to_dict("records"):
            sonuc.setdefault(int(s["PLAYER_ID"]), {}).update({bizim: int(s[kaynak]) for kaynak, bizim in sutunlar.items()})
    tum_sutunlar = [bizim for sutunlar in TAKIP_OLCULERI.values() for bizim in sutunlar.values()]
    return {kimlik: {sutun: degerler.get(sutun, 0) for sutun in tum_sutunlar} for kimlik, degerler in sonuc.items()}


ILK_BES_URL = "https://stats.nba.com/js/data/leaders/00_daily_lineups_{gun}.json"


def ilk_bes_ayristir(veri):
    """Günlük ilk beş beslemesini düz kayıtlara çevirir: [{'mac_id', 'takim_id', 'oyuncu_id', 'pozisyon', 'durum', 'kadro_durumu'}, ...]"""
    try:
        kayitlar = []
        for mac in veri["games"]:
            for taraf in ("homeTeam", "awayTeam"):
                for o in mac[taraf]["players"]:
                    kayitlar.append({"mac_id": str(mac["gameId"]), "takim_id": int(mac[taraf]["teamId"]), "oyuncu_id": int(o["personId"]),
                                     "pozisyon": (o.get("position") or "").strip() or None, "durum": o.get("lineupStatus"),
                                     "kadro_durumu": o.get("rosterStatus")})
    except (KeyError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"günlük ilk beş beslemesi: beklenen yapı yok ({type(e).__name__}: {e})") from e
    return kayitlar


def gunluk_ilk_besler(tarih):
    """nba.com'un günlük ilk beş beslemesi (tarih: ABD tarihi, YYYY-AA-GG). Maçtan saatler önce beklenen,
    maça yakın kesin ilk beşleri ve varsa kadro dışı (Inactive) oyuncuları verir."""
    import requests

    ad = f"günlük ilk beş {tarih}"
    basliklar = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/", "Accept": "application/json"}

    def cek():
        yanit = requests.get(ILK_BES_URL.format(gun=tarih.replace("-", "")), headers=basliklar, timeout=config.ZAMAN_ASIMI_SN)
        yanit.raise_for_status()
        return yanit.json()

    return ilk_bes_ayristir(_cagir(ad, cek, bekleme=config.CDN_BEKLEME_SN))


HAKEM_GOREVLERI = {"OFFICIAL1": "bas_hakem", "OFFICIAL2": "hakem", "OFFICIAL3": "yardimci"}


def mac_hakemleri(mac_id):
    """Oynanmış bir maçın hakemleri (nba.com maç beslemesi): [{'hakem_id', 'isim', 'forma_no', 'gorev'}, ...]"""
    ad = f"nba.com hakemler {mac_id}"
    mac = _cagir(ad, lambda: canli_boxscore.BoxScore(mac_id, timeout=config.ZAMAN_ASIMI_SN).get_dict()["game"], bekleme=config.CDN_BEKLEME_SN)
    try:
        liste = [{"hakem_id": int(h["personId"]), "isim": h["name"].strip(),
                  "forma_no": int(h["jerseyNum"]) if str(h.get("jerseyNum", "")).strip().isdigit() else None,
                  "gorev": HAKEM_GOREVLERI.get(h.get("assignment"))} for h in mac.get("officials") or []]
    except (KeyError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"{ad}: beklenen alan yok ({type(e).__name__}: {e})") from e
    if not liste:
        raise KaynakHatasi(f"{ad}: hakem listesi boş")
    return liste


def _dakika(metin):
    """'33:15' -> 33.25; boşsa None."""
    if not metin:
        return None
    m = re.fullmatch(r"(\d+):(\d{1,2})", metin.strip())
    if not m:
        raise KaynakHatasi(f"dakika biçimi tanınmadı: {metin!r}")
    return int(m.group(1)) + int(m.group(2)) / 60


def kutu_skoru(mac_id):
    """Bir maçta oynayan oyuncuların ilk beş bilgisi ve saniyesine kadar dakikası.

    Döndürür: {oyuncu_id: {'takim_id', 'ilk_bes', 'dakika'}}. Oynamayanlar yer almaz.
    İlk beş, kutu skorunda pozisyonu yazılı olan oyunculardır; takım başına tam 5
    çıkmazsa hata verilir.
    """
    ad = f"BoxScoreTraditionalV3 {mac_id}"
    df = _cagir(ad, lambda: endpoints.BoxScoreTraditionalV3(game_id=mac_id, timeout=config.ZAMAN_ASIMI_SN).get_data_frames()[0])
    df = _dogrula(df, ["teamId", "personId", "position", "minutes"], ad)
    sonuc, ilk_bes_sayisi = {}, {}
    for s in df.itertuples(index=False):
        dakika = _dakika(s.minutes)
        ilk_bes = bool(s.position and s.position.strip())
        ilk_bes_sayisi[s.teamId] = ilk_bes_sayisi.get(s.teamId, 0) + ilk_bes
        if dakika is None:
            continue
        sonuc[int(s.personId)] = {"takim_id": int(s.teamId), "ilk_bes": int(ilk_bes), "dakika": dakika}
    if len(ilk_bes_sayisi) != 2 or any(n != 5 for n in ilk_bes_sayisi.values()):
        raise KaynakHatasi(f"{ad}: takım başına 5 ilk beş oyuncusu bekleniyordu, gelen: {ilk_bes_sayisi}")
    return sonuc


def _iso_dakika(metin):
    """'PT33M15.00S' -> 33.25"""
    m = re.fullmatch(r"PT(\d+)M([\d.]+)S", metin or "")
    return int(m.group(1)) + float(m.group(2)) / 60 if m else None


def nba_com_kutu_skoru(mac_id):
    """nba.com maç sayfasının kullandığı besleme (cdn.nba.com). Yalnızca doğrulama içindir.

    Döndürür: {'ev': {...}, 'dep': {...}}; her biri 'takim_id', 'sayi' ve
    'oyuncular' ({oyuncu_id: istatistik sözlüğü}, yalnızca oynayanlar) içerir.
    """
    ad = f"nba.com kutu skoru {mac_id}"
    mac = _cagir(ad, lambda: canli_boxscore.BoxScore(mac_id, timeout=config.ZAMAN_ASIMI_SN).get_dict()["game"])
    sonuc = {}
    for taraf, anahtar in (("ev", "homeTeam"), ("dep", "awayTeam")):
        t = mac[anahtar]
        oyuncular = {}
        for o in t["players"]:
            if o.get("played") != "1":
                continue
            i = o["statistics"]
            oyuncular[int(o["personId"])] = {
                "isim": o["name"],
                "ilk_bes": int(o["starter"] == "1"),
                "dakika": _iso_dakika(i["minutes"]),
                "sayi": i["points"],
                "ribaund": i["reboundsTotal"],
                "asist": i["assists"],
                "ucluk": i["threePointersMade"],
                "top_calma": i["steals"],
                "blok": i["blocks"],
                "top_kaybi": i["turnovers"],
            }
        sonuc[taraf] = {"takim_id": int(t["teamId"]), "sayi": int(t["score"]), "oyuncular": oyuncular}
    return sonuc
