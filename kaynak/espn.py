"""ESPN çağrıları: takımlar ve sakatlıklar (kadro ve pozisyon 4. adımda eklenecek).

ESPN uç noktaları belgesizdir. Beklenen alanlar yoksa hata verilir; sessizce boş
veri dönülmez.
"""
import logging
import re
import time

import requests

import config
from kaynak import KaynakHatasi

log = logging.getLogger(__name__)

_BASLIKLAR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _json_al(url, ad):
    son_hata = None
    for deneme in range(1, config.DENEME_SAYISI + 1):
        try:
            yanit = requests.get(url, headers=_BASLIKLAR, timeout=config.ZAMAN_ASIMI_SN)
            yanit.raise_for_status()
            return yanit.json()
        except (requests.RequestException, ValueError) as e:
            son_hata = e
            log.warning("%s: deneme %d/%d başarısız: %s: %s", ad, deneme, config.DENEME_SAYISI, type(e).__name__, e)
            if deneme < config.DENEME_SAYISI:
                time.sleep(3 * deneme)
    raise KaynakHatasi(f"{ad}: {config.DENEME_SAYISI} denemede alınamadı ({type(son_hata).__name__}: {son_hata})")


def takimlar():
    """30 takım: [{'espn_id', 'espn_kisaltma', 'isim', 'takma_ad'}, ...]"""
    veri = _json_al(config.ESPN_TAKIMLAR_URL, "ESPN takımlar")
    try:
        ham = veri["sports"][0]["leagues"][0]["teams"]
        liste = [
            {"espn_id": int(t["team"]["id"]), "espn_kisaltma": t["team"]["abbreviation"],
             "isim": t["team"]["displayName"], "takma_ad": t["team"]["name"]}
            for t in ham
        ]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"ESPN takımlar: beklenen yapı yok ({type(e).__name__}: {e})") from e
    if len(liste) != 30:
        raise KaynakHatasi(f"ESPN takımlar: 30 takım bekleniyordu, {len(liste)} geldi")
    return liste


POZISYON_SIRASI = ("PG", "SG", "SF", "PF", "C")


def kadro(espn_takim_id):
    """Bir takımın kadrosu: [{'espn_oyuncu_id', 'isim'}, ...]. Pozisyon burada yalnızca G/F/C gelir, kullanılmaz."""
    ad = f"ESPN kadro {espn_takim_id}"
    veri = _json_al(config.ESPN_KADRO_URL.format(espn_id=espn_takim_id), ad)
    try:
        liste = [{"espn_oyuncu_id": int(o["id"]), "isim": o["fullName"]} for o in veri["athletes"]]
    except (KeyError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
    if not 10 <= len(liste) <= 25:
        raise KaynakHatasi(f"{ad}: 10–25 oyuncu bekleniyordu, {len(liste)} geldi")
    return liste


def birincil_pozisyonlar(yuvalar):
    """Derinlik çizelgesinden her oyuncunun birincil pozisyonunu çıkarır.

    yuvalar: {'PG': [oyuncu kimlikleri, sıralı], 'SG': [...], ...}
    Kural: oyuncunun en üst sırada göründüğü yuva; eşitlikte PG → C sırasındaki ilk yuva.
    Döndürür: {oyuncu kimliği: (pozisyon, sıra)}
    """
    sonuc = {}
    for pozisyon in POZISYON_SIRASI:
        for sira, kimlik in enumerate(yuvalar[pozisyon]):
            if kimlik not in sonuc or sira < sonuc[kimlik][1]:
                sonuc[kimlik] = (pozisyon, sira)
    return sonuc


def derinlik(espn_takim_id):
    """Bir takımın derinlik çizelgesi: {espn_oyuncu_id: (pozisyon, sıra)}"""
    ad = f"ESPN derinlik {espn_takim_id}"
    veri = _json_al(config.ESPN_DERINLIK_URL.format(espn_id=espn_takim_id), ad)
    try:
        ham = veri["depthchart"][0]["positions"]
        yuvalar = {p: [int(o["id"]) for o in ham[p.lower()]["athletes"]] for p in POZISYON_SIRASI}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
    if any(not liste for liste in yuvalar.values()):
        raise KaynakHatasi(f"{ad}: boş pozisyon yuvası var: {[p for p, l in yuvalar.items() if not l]}")
    return birincil_pozisyonlar(yuvalar)


ESPN_MAC_ORANI_URL = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{kimlik}/competitions/{kimlik}/odds"


def _oran_ayristir(oran):
    """ESPN oran kaydı -> {'handikap', 'toplam', 'saglayici'}. 'spread' alanı ev sahibinin çizgisidir (eksi: ev sahibi favori)."""
    def sayi(deger):
        try:
            return float(deger)
        except (TypeError, ValueError):
            return None

    oran = oran or {}
    return {"handikap": sayi(oran.get("spread")), "toplam": sayi(oran.get("overUnder")), "saglayici": (oran.get("provider") or {}).get("name")}


def skor_tablosu(tarih):
    """Bir günün (ABD tarihi, YYYY-AA-GG) maçları ve varsa oranları.

    Döndürür: [{'espn_mac_id', 'ev_espn_id', 'dep_espn_id', 'handikap', 'toplam', 'saglayici'}, ...]
    Biten maçlarda oran alanı boş gelir; onlar için mac_orani() kullanılır.
    """
    ad = f"ESPN skor tablosu {tarih}"
    veri = _json_al(f"{config.ESPN_TABAN}/scoreboard?dates={tarih.replace('-', '')}", ad)
    try:
        sonuc = []
        for e in veri["events"]:
            karsilasma = e["competitions"][0]
            taraf = {x["homeAway"]: int(x["team"]["id"]) for x in karsilasma["competitors"]}
            sonuc.append({"espn_mac_id": int(e["id"]), "ev_espn_id": taraf["home"], "dep_espn_id": taraf["away"],
                          **_oran_ayristir((karsilasma.get("odds") or [None])[0])})
    except (KeyError, IndexError, TypeError, ValueError) as hata:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(hata).__name__}: {hata})") from hata
    return sonuc


def mac_orani(espn_mac_id):
    """Tek bir maçın oranı (biten maçlarda kapanış çizgisi); kayıt yoksa alanları None olan sözlük."""
    veri = _json_al(ESPN_MAC_ORANI_URL.format(kimlik=espn_mac_id), f"ESPN maç oranı {espn_mac_id}")
    ogeler = veri.get("items") if isinstance(veri, dict) else None
    return _oran_ayristir(ogeler[0] if ogeler else None)


def _oyuncu_kimligi(oyuncu):
    """ESPN oyuncu kimliği. Beslemede 'id' alanı boş geliyor; kimlik oyuncu sayfası bağlantısından okunur."""
    if oyuncu.get("id"):
        return int(oyuncu["id"])
    for baglanti in oyuncu.get("links") or []:
        m = re.search(r"/id/(\d+)", baglanti.get("href") or "")
        if m:
            return int(m.group(1))
    return None


def _aciklama(kayit):
    """'Hip, Inflammation, Right — Landale (hip) won't play Sunday...' biçiminde tek satır."""
    d = kayit.get("details") or {}
    ayrinti = ", ".join(x for x in (d.get("type"), d.get("detail"), d.get("side")) if x and x != "Not Specified")
    return " — ".join(x for x in (ayrinti, kayit.get("shortComment")) if x) or None


def sakatlik_ayristir(veri):
    """Sakatlık beslemesini düz kayıt listesine çevirir.

    Döndürür: [{'espn_takim_id', 'espn_oyuncu_id', 'isim', 'durum', 'aciklama',
    'tahmini_donus'}, ...]. Hiç kaydı olmayan takım listede yer almaz; bu "sakat
    yok" değil "veri yok" anlamına gelir.
    """
    takim_listesi = veri.get("injuries") if isinstance(veri, dict) else None
    if not isinstance(takim_listesi, list) or not takim_listesi:
        raise KaynakHatasi("ESPN sakatlık: 'injuries' listesi yok ya da boş")
    kayitlar = []
    try:
        for takim in takim_listesi:
            for k in takim["injuries"]:
                oyuncu = k["athlete"]
                kayitlar.append({
                    "espn_takim_id": int(takim["id"]),
                    "espn_oyuncu_id": _oyuncu_kimligi(oyuncu),
                    "isim": oyuncu["displayName"],
                    "durum": k["status"],
                    "aciklama": _aciklama(k),
                    "tahmini_donus": (k.get("details") or {}).get("returnDate"),
                })
    except (KeyError, TypeError, ValueError) as e:
        raise KaynakHatasi(f"ESPN sakatlık: beklenen alan yok ({type(e).__name__}: {e})") from e
    if not kayitlar:
        raise KaynakHatasi("ESPN sakatlık: hiç kayıt yok")
    return kayitlar


def sakatliklar():
    return sakatlik_ayristir(_json_al(config.ESPN_SAKATLIK_URL, "ESPN sakatlık"))
