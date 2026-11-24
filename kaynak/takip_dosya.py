"""Takip verisinin dosya kaynağı (olası asist, pas, ribaund fırsatı, top dokunuşu).

Takip verisi yalnızca stats.nba.com sorgularından alınabiliyor ve bu sorgular bulut makinelerine yanıt vermiyor.
O yüzden stats.nba.com'a ulaşabilen bilgisayar her maç gününü bir dosyaya yazar (takip_aktar.py), ulaşamayan
makine oradan okur. Dosya: <config.TAKIP_KLASORU>/YYYY-AA-GG.json

    {"tarih": "2026-11-22", "sutunlar": ["olasi_asist", "pas", "ribaund_firsati", "top_dokunusu"],
     "oyuncular": {"203999": [18, 71, 22, 96], ...}}

takip_gunu, nba_stats.takip_gunu ile aynı biçimde döner; kaynak.takip_kaynagi() ikisinden birini seçer.
"""
import json

import config
from kaynak import KaynakHatasi

SUTUNLAR = ["olasi_asist", "pas", "ribaund_firsati", "top_dokunusu"]


def dosya_yolu(tarih):
    return config.TAKIP_KLASORU / f"{tarih}.json"


def takip_gunu(tarih, sezon=None):
    """Bir günün (ABD tarihi) oyuncu takip verisi: {oyuncu_id: {'olasi_asist', 'pas', 'ribaund_firsati', 'top_dokunusu'}}

    Dosya yoksa (bilgisayar o günü henüz göndermemişse) ya da beklenen biçimde değilse KaynakHatasi verir.
    """
    yol = dosya_yolu(tarih)
    ad = f"takip dosyası {yol.name}"
    if not yol.exists():
        raise KaynakHatasi(f"{ad}: dosya yok (takip verisini çeken bilgisayar bu günü henüz göndermemiş)")
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
        if veri["tarih"] != tarih or veri["sutunlar"] != SUTUNLAR:
            raise ValueError(f"tarih ya da sütunlar beklenenden farklı: {veri['tarih']!r}, {veri['sutunlar']!r}")
        sonuc = {}
        for kimlik, degerler in veri["oyuncular"].items():
            if len(degerler) != len(SUTUNLAR):
                raise ValueError(f"oyuncu {kimlik}: {len(SUTUNLAR)} değer bekleniyordu, {len(degerler)} geldi")
            sonuc[int(kimlik)] = {sutun: None if deger is None else int(deger) for sutun, deger in zip(SUTUNLAR, degerler)}
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise KaynakHatasi(f"{ad}: beklenen yapı yok ({type(e).__name__}: {e})") from e
    if not sonuc:
        raise KaynakHatasi(f"{ad}: oyuncu yok")
    return sonuc


def gunu_yaz(tarih, veri):
    """takip_gunu biçimindeki veriyi dosyaya yazar. Döndürür: dosyanın içeriği değişti mi (yeni dosya da değişiklik sayılır)."""
    icerik = json.dumps({"tarih": tarih, "sutunlar": SUTUNLAR,
                         "oyuncular": {str(kimlik): [veri[kimlik][sutun] for sutun in SUTUNLAR] for kimlik in sorted(veri)}},
                        ensure_ascii=False, separators=(",", ":")) + "\n"
    yol = dosya_yolu(tarih)
    if yol.exists() and yol.read_text(encoding="utf-8") == icerik:
        return False
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(icerik, encoding="utf-8", newline="\n")
    return True
