"""official.nba.com: günün hakem atamaları.

Sayfa maç günleri yaklaşık 09:00 ET'de (Türkiye saatiyle 17:00) güncellenir; o saate kadar
önceki günün atamalarını gösterir. Bu yüzden sayfadaki tarih mutlaka döndürülür ve
çağıran taraf bugünün tarihiyle karşılaştırır.
"""
import html
import logging
import re
import time
from datetime import datetime

import requests

import config
from kaynak import KaynakHatasi

log = logging.getLogger(__name__)

HAKEM_ATAMA_URL = "https://official.nba.com/referee-assignments/"
_BASLIKLAR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
GOREVLER = ("bas_hakem", "hakem", "yardimci")      # sayfadaki Crew Chief, Referee, Umpire sütunları


def _metin(parca):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", parca))).strip()


def atama_ayristir(sayfa):
    """Atama sayfasının HTML'ini ayrıştırır.

    Döndürür: {'tarih': 'YYYY-AA-GG', 'maclar': [{'mac': 'Memphis @ Charlotte', 'hakemler': [(isim, forma_no, görev), ...]}, ...]}
    Beklenen başlıklar ya da tarih yoksa hata verir. Maç listesi boş olabilir (maçsız gün).
    """
    bolum = re.search(r"NBA Referee Assignments(.*?)(?:G League Referee Assignments|$)", sayfa, re.S)
    if not bolum:
        raise KaynakHatasi("hakem atamaları: 'NBA Referee Assignments' bölümü bulunamadı")
    tarih = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4})", _metin(bolum.group(1)[:3000]))
    if not tarih:
        raise KaynakHatasi("hakem atamaları: sayfada tarih bulunamadı")
    gun = datetime.strptime(tarih.group(1), "%B %d, %Y").date().isoformat()
    tablo = re.search(r"<table.*?</table>", bolum.group(1), re.S)
    if not tablo:
        return {"tarih": gun, "maclar": []}
    basliklar = [_metin(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", tablo.group(0), re.S)]
    if basliklar[:4] != ["Game", "Crew Chief", "Referee", "Umpire"]:
        raise KaynakHatasi(f"hakem atamaları: beklenmeyen tablo başlıkları {basliklar}")
    maclar = []
    for satir in re.findall(r"<tr[^>]*>(.*?)</tr>", tablo.group(0), re.S):
        hucreler = [_metin(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", satir, re.S)]
        if len(hucreler) < 4 or "@" not in hucreler[0]:
            continue
        hakemler = []
        for gorev, hucre in zip(GOREVLER, hucreler[1:4]):
            m = re.fullmatch(r"(.+?)\s*\(#(\d+)\)", hucre)
            if m:
                hakemler.append((m.group(1).strip(), int(m.group(2)), gorev))
            elif hucre:
                raise KaynakHatasi(f"hakem atamaları: hakem hücresi tanınmadı: {hucre!r}")
        maclar.append({"mac": hucreler[0], "hakemler": hakemler})
    return {"tarih": gun, "maclar": maclar}


def hakem_atamalari():
    """Atama sayfasını çeker ve ayrıştırır."""
    son_hata = None
    for deneme in range(1, config.DENEME_SAYISI + 1):
        try:
            yanit = requests.get(HAKEM_ATAMA_URL, headers=_BASLIKLAR, timeout=config.ZAMAN_ASIMI_SN)
            yanit.raise_for_status()
            return atama_ayristir(yanit.text)
        except requests.RequestException as e:
            son_hata = e
            log.warning("hakem atamaları: deneme %d/%d başarısız: %s: %s", deneme, config.DENEME_SAYISI, type(e).__name__, e)
            if deneme < config.DENEME_SAYISI:
                time.sleep(3 * deneme)
    raise KaynakHatasi(f"hakem atamaları: {config.DENEME_SAYISI} denemede alınamadı ({type(son_hata).__name__}: {son_hata})")
