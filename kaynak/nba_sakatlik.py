"""NBA resmi sakatlık raporu (PLAN bölüm 3.3, adım 10). nbainjuries paketi PDF raporu tabloya çevirir (Java gerektirir).

Rapor gün içinde 15 dakikada bir yayımlanır; en son yayımlanan rapor aranır. Takımlar raporu maçtan
önceki gün 17:00'ye (arka arkaya maçta maç günü 13:00'e) kadar verir; vermemiş takım raporda
"NOT YET SUBMITTED" satırıyla görünür.
"""
import contextlib
import io
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from kaynak import KaynakHatasi

log = logging.getLogger(__name__)

BEKLENEN_SUTUNLAR = ["Game Date", "Matchup", "Team", "Player Name", "Current Status", "Reason"]
ARALIK_DK = 15
GERIYE_ADIM = 32          # en çok 8 saat geriye bakılır


def isim_cevir(metin):
    """'Pippen Jr., Scotty' -> 'Scotty Pippen Jr.'"""
    soyad, virgul, ad = metin.partition(",")
    return f"{ad.strip()} {soyad.strip()}".strip() if virgul else metin.strip()


def _sessiz(islev, *arg, **kw):
    """nbainjuries her çağrıda ekrana satır basar; onu yutar."""
    with contextlib.redirect_stdout(io.StringIO()):
        return islev(*arg, **kw)


def son_rapor_zamani(simdi=None):
    """En son yayımlanmış raporun zamanı (ET, saat dilimi bilgisiz datetime); bulunamazsa None."""
    from nbainjuries import injury

    simdi = simdi or datetime.now(ZoneInfo(config.MAC_SAAT_DILIMI)).replace(tzinfo=None)
    aday = simdi.replace(second=0, microsecond=0) - timedelta(minutes=simdi.minute % ARALIK_DK)
    for _ in range(GERIYE_ADIM):
        try:
            if _sessiz(injury.check_reportvalid, aday):
                return aday
        except Exception:      # paket, olmayan rapor için hata fırlatabiliyor
            pass
        aday -= timedelta(minutes=ARALIK_DK)
    return None


def rapor_ayristir(df):
    """Rapor tablosunu düz kayıtlara çevirir.

    Döndürür: (kayıtlar, bildirmeyenler)
      kayıtlar: [{'tarih': 'YYYY-AA-GG', 'takim': 'Detroit Pistons', 'isim': 'Cade Cunningham', 'durum': 'Out', 'neden': ...}]
      bildirmeyenler: [(tarih, takım)] raporu henüz vermemiş takımlar
    """
    eksik = [s for s in BEKLENEN_SUTUNLAR if s not in df.columns]
    if eksik:
        raise KaynakHatasi(f"resmi sakatlık raporu: beklenen sütunlar yok: {eksik}")
    kayitlar, bildirmeyen = [], []
    for s in df.to_dict("records"):
        try:
            tarih = datetime.strptime(str(s["Game Date"]).strip(), "%m/%d/%Y").date().isoformat()
        except ValueError as e:
            raise KaynakHatasi(f"resmi sakatlık raporu: tarih tanınmadı: {s['Game Date']!r}") from e
        takim = str(s["Team"]).strip()
        isim, durum, neden = s["Player Name"], s["Current Status"], s["Reason"]
        bos = lambda x: x is None or x != x or not str(x).strip()        # None, NaN ya da boş metin
        if bos(isim):
            if not bos(neden) and "NOT YET SUBMITTED" in str(neden).upper():
                bildirmeyen.append((tarih, takim))
            continue
        if bos(durum):
            raise KaynakHatasi(f"resmi sakatlık raporu: durumu boş kayıt: {isim!r}")
        kayitlar.append({"tarih": tarih, "takim": takim, "isim": isim_cevir(str(isim)), "durum": str(durum).strip(),
                         "neden": None if bos(neden) else str(neden).strip()})
    return kayitlar, bildirmeyen


def resmi_rapor():
    """En son resmi raporu çeker. Döndürür: {'rapor_zamani': 'YYYY-AA-GG SS:DD (ET)', 'kayitlar': [...], 'bildirmeyen': [...]}"""
    try:
        from nbainjuries import injury
    except ImportError as e:
        raise KaynakHatasi("nbainjuries paketi kurulu değil (pip install -r requirements.txt)") from e
    zaman = son_rapor_zamani()
    if zaman is None:
        raise KaynakHatasi(f"resmi sakatlık raporu: son {GERIYE_ADIM * ARALIK_DK // 60} saatte yayımlanmış rapor bulunamadı")
    try:
        df = _sessiz(injury.get_reportdata, zaman, return_df=True)
    except Exception as e:
        raise KaynakHatasi(f"resmi sakatlık raporu okunamadı ({zaman}): {type(e).__name__}: {e}") from e
    kayitlar, bildirmeyen = rapor_ayristir(df)
    return {"rapor_zamani": zaman.strftime("%Y-%m-%d %H:%M (ET)"), "kayitlar": kayitlar, "bildirmeyen": bildirmeyen}
