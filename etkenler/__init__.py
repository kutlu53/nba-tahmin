"""Etken zinciri (PLAN_EK bölüm 2).

Her etken bu klasörde ayrı bir dosyadır ve şu işlevi sunar:

    def hesapla(oyuncu, mac, istatistik, baglam) -> EtkenSonucu

oyuncu bir Oyuncu, mac bir Mac, baglam ise tahmin.Baglam nesnesidir.

Hangi etkenin açık olduğu, sırası ve çarpan sınırları config.ETKENLER içindedir.
"""
import importlib
import logging
import math
from dataclasses import dataclass, replace

import config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EtkenSonucu:
    carpan: float = 1.0
    veri_var: bool = False
    orneklem: int = 0
    aciklama: str = ""


@dataclass(frozen=True)
class Oyuncu:
    oyuncu_id: int
    isim: str
    takim_id: int       # tahmin edilen maçtaki takımı
    pozisyon: str | None


@dataclass(frozen=True)
class Mac:
    mac_id: str
    tarih: str          # ABD tarihi, YYYY-AA-GG
    ev_takim_id: int
    dep_takim_id: int

    def ev_mi(self, takim_id):
        return takim_id == self.ev_takim_id

    def rakip(self, takim_id):
        return self.dep_takim_id if takim_id == self.ev_takim_id else self.ev_takim_id


@dataclass(frozen=True)
class ZincirSonucu:
    carpan: float      # toplam çarpan: temel etkenlerin çarpımı × (diğerlerinin çarpımı, genel sınır uygulanmış)
    ham_carpan: float  # genel sınırdan önceki çarpım
    etkenler: dict     # etken adı -> EtkenSonucu (kendi sınırı uygulanmış)
    dakika_carpani: float = 1.0   # "dakika" türü etkenlerin çarpımı: beklenen dakikanın düzeltmesi


def veri_yok(aciklama="veri yok"):
    """Verisi olmayan etkenin döndüreceği nötr sonuç."""
    return EtkenSonucu(1.0, False, 0, aciklama)


def sinirla(deger, alt, ust):
    return max(alt, min(ust, deger))


def kucuk_orneklem(n, deger, k, notr=1.0):
    """Küçük örneklem düzeltmesi; her etkende aynı biçim: (n × değer + k × nötr) / (n + k)."""
    return (n * deger + k * notr) / (n + k)


def beklenen_dakika(k):
    """Son 5 maçın dakika ortalaması; bu 5 maçta ilk beş / yedek rolü değiştiyse son 3 maç.

    k: oyuncunun maç kayıtları (eskiden yeniye). Döndürür: (dakika, rol_degisti).
    """
    son = k.tail(config.DAKIKA_PENCERE)
    rol_degisti = son["ilk_bes"].nunique() > 1
    if rol_degisti:
        son = k.tail(config.DAKIKA_PENCERE_ROL)
    a = config.DAKIKA_SEZON_AGIRLIK
    return float((1 - a) * son["dakika"].mean() + a * k["dakika"].mean()), bool(rol_degisti)


def agirlikli_oran_36(k, sutun):
    """36 dk başına üretim: sezon, son 10 ve son 5 maçın ağırlıklı ortalaması (config.TEMEL_AGIRLIK).

    k: oyuncunun maç kayıtları (eskiden yeniye). Her pencerede dakikalar toplanarak hesaplanır.
    Döndürür: (ağırlıklı oran, pencere oranları).
    """
    pencereler = {"sezon": k, "son10": k.tail(10), "son5": k.tail(5)}
    oranlar = {ad: config.NORMALLESTIRME_DAKIKA * p[sutun].sum() / p["dakika"].sum() for ad, p in pencereler.items()}
    return sum(config.TEMEL_AGIRLIK[ad] * o for ad, o in oranlar.items()), oranlar


def acik_etkenler(ayarlar=None):
    """Açık etkenleri zincir sırasıyla yükler: [(ad, hesapla, alt, ust, tur), ...].

    Açık işaretlenmiş bir etkenin dosyası yoksa hata verir; yazım hatası sessizce
    "etken kapalı" gibi davranmamalı.
    """
    ayarlar = config.ETKENLER if ayarlar is None else ayarlar
    liste = []
    for ad, ayar in ayarlar.items():
        if not ayar["acik"]:
            continue
        modul = importlib.import_module(f"etkenler.{ad}")
        liste.append((ad, modul.hesapla, ayar["alt"], ayar["ust"], ayar.get("tur", "carpan")))
    return liste


def uygula(oyuncu, mac, istatistik, baglam, etkenler=None, genel_sinir=None):
    """Açık etkenleri sırayla çalıştırır ve çarpanlarını birleştirir.

    - Verisi olmayan etkenin çarpanı 1,00 sayılır.
    - Her çarpan kendi alt/üst sınırına, çarpım da genel sınıra çekilir. Temel oranı yeniden
      tahmin eden ("temel") ve beklenen dakikayı düzelten ("dakika") etkenler genel sınıra girmez.
    - Hata veren etken zinciri durdurmaz: nötr sayılır, hata açıklamaya ve loga yazılır.
    """
    if etkenler is None:
        etkenler = acik_etkenler()
    alt_genel, ust_genel = config.GENEL_CARPAN_SINIRI if genel_sinir is None else genel_sinir

    sonuclar = {}
    carpimlar = {"carpan": 1.0, "temel": 1.0, "dakika": 1.0}
    for ad, hesapla, alt, ust, tur in etkenler:
        try:
            s = hesapla(oyuncu, mac, istatistik, baglam)
            if not isinstance(s, EtkenSonucu):
                raise TypeError(f"EtkenSonucu bekleniyordu, {type(s).__name__} geldi")
            if not s.veri_var:
                s = replace(s, carpan=1.0)
            elif not (math.isfinite(s.carpan) and s.carpan > 0):
                raise ValueError(f"geçersiz çarpan: {s.carpan}")
            else:
                sinirli = sinirla(s.carpan, alt, ust)
                if sinirli != s.carpan:
                    s = replace(s, carpan=sinirli, aciklama=f"{s.aciklama} [sınırlandı, ham {s.carpan:.3f}]".strip())
        except Exception as e:  # bir kaynak bozulursa yalnızca o etken devre dışı kalır
            log.exception("Etken '%s' hata verdi (oyuncu=%s, maç=%s, istatistik=%s)", ad, oyuncu, mac, istatistik)
            s = veri_yok(f"hata: {type(e).__name__}: {e}")
        sonuclar[ad] = s
        carpimlar[tur] *= s.carpan

    disi = carpimlar["temel"] * carpimlar["dakika"]          # genel sınırın dışında kalanlar
    return ZincirSonucu(carpan=disi * sinirla(carpimlar["carpan"], alt_genel, ust_genel), ham_carpan=disi * carpimlar["carpan"],
                        etkenler=sonuclar, dakika_carpani=carpimlar["dakika"])


def etken_satirlari(tahmin_id, zincir):
    """ZincirSonucu'nu tahmin_etken tablosuna yazılacak satırlara çevirir."""
    return [
        {
            "tahmin_id": tahmin_id,
            "etken": ad,
            "carpan": s.carpan,
            "veri_var": int(s.veri_var),
            "orneklem": s.orneklem,
            "aciklama": s.aciklama,
        }
        for ad, s in zincir.etkenler.items()
    ]
