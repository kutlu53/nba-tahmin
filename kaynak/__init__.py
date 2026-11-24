class KaynakHatasi(RuntimeError):
    """Kaynak yanıt vermedi ya da beklenen biçimde veri dönmedi."""


def mac_kaynagi():
    """Fikstür, oyuncu listesi ve maç kutu skorlarının alındığı modül (config.VERI_KAYNAGI: 'stats' ya da 'cdn').

    İki modül de aynı işlevleri aynı biçimde sunar: fikstur, oyuncu_listesi, oyuncu_mac_kayitlari, takim_mac_kayitlari, kutu_skoru.
    """
    import config
    from kaynak import nba_cdn, nba_stats

    if config.VERI_KAYNAGI not in ("stats", "cdn"):
        raise KaynakHatasi(f"config.VERI_KAYNAGI 'stats' ya da 'cdn' olmalı, gelen: {config.VERI_KAYNAGI!r}")
    return nba_cdn if config.VERI_KAYNAGI == "cdn" else nba_stats


def takip_kaynagi():
    """Takip verisinin alındığı modül: 'stats' kipinde stats.nba.com (nba_stats), 'cdn' kipinde bilgisayarın yazdığı dosyalar (takip_dosya).

    İkisi de takip_gunu(tarih) işlevini aynı biçimde sunar.
    """
    from kaynak import nba_stats, takip_dosya

    return takip_dosya if mac_kaynagi() is not nba_stats else nba_stats
