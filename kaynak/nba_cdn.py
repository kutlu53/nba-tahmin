"""nba.com'un kendi sayfalarının kullandığı dosyalar: fikstür, oyuncu listesi ve maç kutu skorları.

stats.nba.com'un istatistik sorguları bulut makinelerinden (GitHub Actions) yanıt vermiyor; bu modül aynı veriyi
oradan da ulaşılabilen adreslerden alır. İşlevler nba_stats'takilerle aynı ada, aynı parametrelere ve aynı dönüş
biçimine sahiptir; hangisinin kullanılacağını config.VERI_KAYNAGI belirler (bkz. kaynak.mac_kaynagi).

Kutu skoru iki yerden alınabilir:
  1. Maç sayfası (www.nba.com/game/<kimlik>/box-score): sonradan yapılan resmî istatistik düzeltmelerini içerir,
     stats.nba.com ile aynı değerleri verir. Birincil kaynaktır.
  2. Canlı besleme dosyası (cdn.nba.com/.../boxscore_<kimlik>.json): maç bittiği andaki haliyle kalır, düzeltme almaz
     (24 Kasım 2026 ölçümü: oyuncu-maç satırlarının %1,4'ünde bir istatistik 1–2 farklı). Maç sayfası alınamazsa kullanılır.

Farklar: yalnızca içinde bulunulan sezon vardır ve maç kayıtları tek çağrı yerine maç başına bir istekle toplanır.
Takip verisi (olası asist, ribaund fırsatı) bu kaynakta yoktur.
"""
import json
import logging
import re
import time

import pandas as pd
import requests
from nba_api.live.nba.endpoints import boxscore as canli_boxscore
from nba_api.live.nba.library.http import NBALiveHTTP

import config
from kaynak import KaynakHatasi
from kaynak.nba_stats import MAC_KAYDI_SUTUNLARI, NORMAL_SEZON_ON_EKI, TAKIM_KAYDI_SUTUNLARI, _cagir, _dakika, _dogrula, _iso_dakika

log = logging.getLogger(__name__)

FIKSTUR_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
OYUNCU_LISTESI_URL = "https://cdn.nba.com/static/json/staticData/playerIndex.json"
MAC_SAYFASI_URL = "https://www.nba.com/game/{mac_id}/box-score"
_SAYFA_BASLIKLARI = {"User-Agent": NBALiveHTTP.headers["User-Agent"], "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
ONBELLEK_SN = 600                 # fikstür dosyası büyüktür (7 MB); aynı çalıştırmada bir kez indirilir
_fikstur_onbellek = (0.0, None)
_kutu_onbellek = {}               # mac_id -> bitmiş maçın kutu skoru (ortak biçimde)
kutu_kaynaklari = {"sayfa": 0, "canli": 0}      # bu çalıştırmada hangi kaynaktan kaç maç alındı

# kutu skoru alanı -> LeagueGameLog sütunu (iki kutu skoru kaynağında ve oyuncu / takım için ortak olanlar)
ALANLAR = {
    "fieldGoalsMade": "FGM", "fieldGoalsAttempted": "FGA", "threePointersMade": "FG3M", "threePointersAttempted": "FG3A",
    "freeThrowsMade": "FTM", "freeThrowsAttempted": "FTA", "reboundsOffensive": "OREB", "reboundsDefensive": "DREB", "reboundsTotal": "REB",
    "assists": "AST", "steals": "STL", "blocks": "BLK", "turnovers": "TOV", "foulsPersonal": "PF", "points": "PTS",
}


def _indir(url, ad, basliklar=None):
    def cek():
        yanit = requests.get(url, headers=basliklar or dict(NBALiveHTTP.headers), timeout=config.ZAMAN_ASIMI_SN)     # yalın başlıklar 403 alır
        yanit.raise_for_status()
        return yanit.content.decode("utf-8")      # sunucu karakter kümesini bildirmiyor; içerik UTF-8

    return _cagir(ad, cek, bekleme=config.CDN_BEKLEME_SN)


def _json(url, ad):
    try:
        return json.loads(_indir(url, ad))
    except ValueError as e:
        raise KaynakHatasi(f"{ad}: JSON okunamadı ({e})") from e


def _sezon_denetle(sezon, ad):
    if (sezon or config.SEZON) != config.SEZON:
        raise KaynakHatasi(f"{ad}: nba.com dosyaları yalnızca içinde bulunulan sezonu ({config.SEZON}) verir, istenen {sezon}")


def _fikstur_ham():
    """Normal sezon maçları, dosyadaki haliyle (sözlük listesi)."""
    global _fikstur_onbellek
    zaman, maclar = _fikstur_onbellek
    if maclar is None or time.monotonic() - zaman > ONBELLEK_SN:
        ad = f"cdn fikstür {config.SEZON}"
        veri = _json(FIKSTUR_URL, ad)
        try:
            lig = veri["leagueSchedule"]
            if lig["seasonYear"] != config.SEZON:
                raise KaynakHatasi(f"{ad}: dosya {lig['seasonYear']} sezonuna ait")
            maclar = [m for gun in lig["gameDates"] for m in gun["games"] if str(m["gameId"]).startswith(NORMAL_SEZON_ON_EKI)]
        except (KeyError, TypeError) as e:
            raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
        if not maclar:
            raise KaynakHatasi(f"{ad}: normal sezon maçı yok")
        _fikstur_onbellek = (time.monotonic(), maclar)
    return maclar


def fikstur(sezon=None):
    """Normal sezon fikstürü; nba_stats.fikstur ile aynı biçim: (maclar tablosu satırları, takımı belirsiz maç kimlikleri)."""
    _sezon_denetle(sezon, "cdn fikstür")
    maclar, belirsiz = [], []
    for m in _fikstur_ham():
        try:
            ev, dep = m["homeTeam"], m["awayTeam"]
            if not ev.get("teamId") or not dep.get("teamId"):
                belirsiz.append(m["gameId"])
                continue
            oynandi = m["gameStatus"] == 3
            if m["postponedStatus"] != "N" and not oynandi:
                durum = "ertelendi"
            else:
                durum = "oynandi" if oynandi else "oynanacak"
            maclar.append({
                "mac_id": m["gameId"],
                "tarih": m["gameDateEst"][:10],
                "baslama_utc": m["gameDateTimeUTC"],
                "ev_takim_id": int(ev["teamId"]),
                "dep_takim_id": int(dep["teamId"]),
                "durum": durum,
                "ev_sayi": int(ev["score"]) if oynandi else None,
                "dep_sayi": int(dep["score"]) if oynandi else None,
                "salon_sehri": (m.get("arenaCity") or "").strip() or None,
            })
        except (KeyError, TypeError, ValueError) as e:
            raise KaynakHatasi(f"cdn fikstür: {m.get('gameId')} maçında beklenen alan yok ({type(e).__name__}: {e})") from e
    return maclar, belirsiz


def oyuncu_listesi(sezon=None):
    """Sezonun tüm oyuncuları ve güncel takımları; nba_stats.oyuncu_listesi ile aynı biçim."""
    _sezon_denetle(sezon, "cdn oyuncu listesi")
    ad = f"cdn oyuncu listesi {config.SEZON}"
    veri = _json(OYUNCU_LISTESI_URL, ad)
    try:
        if veri["parameters"]["Season"] != config.SEZON:
            raise KaynakHatasi(f"{ad}: dosya {veri['parameters']['Season']} sezonuna ait")
        tablo = veri["resultSets"][0]
        df = pd.DataFrame(tablo["rowSet"], columns=tablo["headers"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
    df = _dogrula(df, ["PERSON_ID", "PLAYER_FIRST_NAME", "PLAYER_LAST_NAME", "TEAM_ID"], ad)
    if len(df) < 400:
        raise KaynakHatasi(f"{ad}: en az 400 oyuncu bekleniyordu, {len(df)} geldi")
    return [{"oyuncu_id": int(s.PERSON_ID), "isim": f"{s.PLAYER_FIRST_NAME or ''} {s.PLAYER_LAST_NAME or ''}".strip(),
             "takim_id": int(s.TEAM_ID) or None} for s in df.itertuples(index=False)]


# --- Kutu skoru: iki kaynak tek biçime çevrilir ---
# {'kaynak': 'sayfa' | 'canli', 'takimlar': [ev, deplasman]}; takım: {'takim_id', 'dakika', 'istatistik', 'oyuncular'};
# oyuncu (yalnızca süre alanlar): {'oyuncu_id', 'isim', 'ilk_bes', 'dakika', 'istatistik'}; istatistik: LeagueGameLog sütun adlarıyla.

def _istatistik(kaynak):
    return {sutun: int(kaynak[alan]) for alan, sutun in ALANLAR.items()}


def _sayfa_kutusu(mac_id):
    ad = f"nba.com maç sayfası {mac_id}"
    metin = _indir(MAC_SAYFASI_URL.format(mac_id=mac_id), ad, _SAYFA_BASLIKLARI)
    bulunan = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', metin, flags=re.S)
    try:
        if not bulunan:
            raise KaynakHatasi(f"{ad}: sayfada veri bölümü (__NEXT_DATA__) yok")
        mac = json.loads(bulunan.group(1))["props"]["pageProps"]["game"]
        if mac["gameId"] != mac_id or mac["gameStatus"] != 3:
            raise KaynakHatasi(f"{ad}: maç henüz bitmemiş ya da başka bir maç geldi ({mac.get('gameId')}, durum {mac.get('gameStatus')})")
        takimlar = []
        for anahtar in ("homeTeam", "awayTeam"):
            t = mac[anahtar]
            oyuncular = []
            for o in t["players"]:
                dakika = _dakika(o["statistics"].get("minutes"))        # oynamayanlarda boş
                if dakika is None:
                    continue
                oyuncular.append({"oyuncu_id": int(o["personId"]), "isim": f"{o.get('firstName') or ''} {o.get('familyName') or ''}".strip(),
                                  "ilk_bes": int(bool((o.get("position") or "").strip())), "dakika": dakika, "istatistik": _istatistik(o["statistics"])})
            # Takım top kaybı LeagueGameLog'da takıma yazılan top kayıplarını da içerir; sayfadaki takım satırı yalnızca oyuncuların
            # toplamıdır, toplam değer maç sonu karşılaştırma bölümünde (postgameCharts) durur.
            toplam_top_kaybi = int(mac["postgameCharts"][anahtar]["statistics"]["turnoversTotal"])
            takimlar.append({"takim_id": int(t["teamId"]), "dakika": _dakika(t["statistics"]["minutes"]),
                             "istatistik": {**_istatistik(t["statistics"]), "TOV": toplam_top_kaybi}, "oyuncular": oyuncular})
    except (KeyError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
    return {"kaynak": "sayfa", "takimlar": takimlar}


def _canli_kutu(mac_id):
    ad = f"cdn kutu skoru {mac_id}"
    mac = _cagir(ad, lambda: canli_boxscore.BoxScore(mac_id, timeout=config.ZAMAN_ASIMI_SN).get_dict()["game"], bekleme=config.CDN_BEKLEME_SN)
    try:
        if mac["gameStatus"] != 3:
            raise KaynakHatasi(f"{ad}: maç henüz bitmemiş (durum {mac['gameStatus']})")
        takimlar = []
        for anahtar in ("homeTeam", "awayTeam"):
            t = mac[anahtar]
            oyuncular = [{"oyuncu_id": int(o["personId"]), "isim": o["name"], "ilk_bes": int(o.get("starter") == "1"),
                          "dakika": _iso_dakika(o["statistics"]["minutes"]), "istatistik": _istatistik(o["statistics"])}
                         for o in t["players"] if o.get("played") == "1"]
            takimlar.append({"takim_id": int(t["teamId"]), "dakika": _iso_dakika(t["statistics"]["minutes"]),
                             "istatistik": {**_istatistik(t["statistics"]), "TOV": int(t["statistics"]["turnoversTotal"])}, "oyuncular": oyuncular})
    except (KeyError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
    return {"kaynak": "canli", "takimlar": takimlar}


def _gecerli_sure(dakika):
    """Takım dakikası 240 ya da uzatma başına 25 fazlası olmalıdır."""
    return dakika is not None and dakika >= 240 and (dakika - 240) % 25 == 0


def _takim_dakikasi(takim):
    """Takımın maçtaki toplam dakikası. Kaynaktaki takım satırı bazen bozuk gelir (0 ya da 60 gibi); o zaman
    oyuncu dakikalarının toplamı kullanılır. İkisi de geçerli değilse kaynaktaki değer olduğu gibi kalır."""
    if _gecerli_sure(takim["dakika"]):
        return takim["dakika"]
    toplam = sum(o["dakika"] for o in takim["oyuncular"])
    if abs(toplam - round(toplam)) < 0.5 and _gecerli_sure(float(round(toplam))):
        return float(round(toplam))
    return takim["dakika"] if takim["dakika"] is not None else toplam


def _kutu(mac_id):
    """Bitmiş bir maçın kutu skoru, ortak biçimde. Önce maç sayfası, alınamazsa canlı besleme dosyası."""
    if mac_id not in _kutu_onbellek:
        try:
            kutu = _sayfa_kutusu(mac_id)
        except KaynakHatasi as e:
            log.warning("Maç sayfası alınamadı, canlı besleme dosyası kullanılıyor (istatistik düzeltmeleri eksik olabilir): %s", e)
            kutu = _canli_kutu(mac_id)
        for t in kutu["takimlar"]:
            if any(o["dakika"] is None for o in t["oyuncular"]) or len(t["oyuncular"]) < 5:
                raise KaynakHatasi(f"kutu skoru {mac_id} ({kutu['kaynak']}): takım {t['takim_id']} için dakika ya da oyuncu eksik")
            t["dakika"] = _takim_dakikasi(t)
        kutu_kaynaklari[kutu["kaynak"]] += 1
        _kutu_onbellek[mac_id] = kutu
    return _kutu_onbellek[mac_id]


def _biten_maclar(tarihten, tarihe):
    """[(mac_id, tarih, ev kısaltması, deplasman kısaltması), ...]: tarih aralığındaki (ikisi de dahil) bitmiş maçlar."""
    return [(m["gameId"], m["gameDateEst"][:10], m["homeTeam"]["teamTricode"], m["awayTeam"]["teamTricode"]) for m in _fikstur_ham()
            if m["gameStatus"] == 3 and (not tarihten or m["gameDateEst"][:10] >= tarihten) and (not tarihe or m["gameDateEst"][:10] <= tarihe)]


def oyuncu_mac_kayitlari(sezon=None, tarihten=None, tarihe=None, bos_olabilir=False):
    """Oyuncu maç kayıtları, LeagueGameLog (oyuncu) sütunlarıyla; maç başına bir kutu skorundan toplanır.

    Yalnızca maçta süre almış oyuncular yer alır. MIN tam dakikaya yuvarlanmıştır; LeagueGameLog'daki değerle satırların
    yaklaşık %0,4'ünde 1 dakika ayrışır (orada yuvarlama saniyenin kesirlerine göre yapılıyor). Kesin süre kutu_skoru'ndadır.
    """
    ad = f"nba.com oyuncu maç kayıtları {tarihten or ''}..{tarihe or ''}"
    _sezon_denetle(sezon, ad)
    satirlar = []
    for mac_id, tarih, ev, dep in _biten_maclar(tarihten, tarihe):
        for t, eslesme in zip(_kutu(mac_id)["takimlar"], (f"{ev} vs. {dep}", f"{dep} @ {ev}")):
            satirlar += [{"PLAYER_ID": o["oyuncu_id"], "PLAYER_NAME": o["isim"], "TEAM_ID": t["takim_id"], "GAME_ID": mac_id, "GAME_DATE": tarih,
                          "MATCHUP": eslesme, "MIN": int(o["dakika"] + 0.5), **o["istatistik"]} for o in t["oyuncular"]]
    return _dogrula(pd.DataFrame(satirlar, columns=MAC_KAYDI_SUTUNLARI + ["DREB"]), MAC_KAYDI_SUTUNLARI, ad, bos_olabilir)


def takim_mac_kayitlari(sezon=None, tarihten=None, tarihe=None, bos_olabilir=False):
    """Takım maç kutu skorları, LeagueGameLog (takım) sütunlarıyla."""
    ad = f"nba.com takım maç kayıtları {tarihten or ''}..{tarihe or ''}"
    _sezon_denetle(sezon, ad)
    satirlar = [{"TEAM_ID": t["takim_id"], "GAME_ID": mac_id, "MIN": int(round(t["dakika"])), **t["istatistik"]}
                for mac_id, _, _, _ in _biten_maclar(tarihten, tarihe) for t in _kutu(mac_id)["takimlar"]]
    return _dogrula(pd.DataFrame(satirlar, columns=TAKIM_KAYDI_SUTUNLARI), TAKIM_KAYDI_SUTUNLARI, ad, bos_olabilir)


def kutu_skoru(mac_id):
    """Bir maçta oynayan oyuncuların ilk beş bilgisi ve saniyesine kadar dakikası; nba_stats.kutu_skoru ile aynı biçim."""
    kutu = _kutu(mac_id)
    sonuc = {o["oyuncu_id"]: {"takim_id": t["takim_id"], "ilk_bes": o["ilk_bes"], "dakika": o["dakika"]} for t in kutu["takimlar"] for o in t["oyuncular"]}
    ilk_bes_sayisi = {t["takim_id"]: sum(o["ilk_bes"] for o in t["oyuncular"]) for t in kutu["takimlar"]}
    if len(ilk_bes_sayisi) != 2 or any(n != 5 for n in ilk_bes_sayisi.values()):
        raise KaynakHatasi(f"kutu skoru {mac_id} ({kutu['kaynak']}): takım başına 5 ilk beş oyuncusu bekleniyordu, gelen: {ilk_bes_sayisi}")
    return sonuc
