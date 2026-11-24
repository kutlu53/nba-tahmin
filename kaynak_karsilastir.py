"""İki maç verisi kaynağını karşılaştırır: stats.nba.com (nba_stats) ve cdn.nba.com (nba_cdn).

Her iki kaynağa da ulaşılabilen bir makinede (bu bilgisayar) çalıştırılır. Fikstürü, oyuncu listesini, oyuncu ve takım
maç kayıtlarını iki kaynaktan çeker ve farkları yazar; cdn kutu skorundaki dakika ve ilk beş bilgisini veritabanında
kayıtlı olanla (stats'tan alınmış) karşılaştırır. Veritabanına yazmaz.

Çalıştırma:  .venv\\Scripts\\python.exe kaynak_karsilastir.py [tarihten] [tarihe]      (varsayılan: sezonun tamamı)
"""
import logging
import sys

import pandas as pd

import config
import veritabani
from kaynak import nba_cdn, nba_stats

OYUNCU_SUTUNLARI = [s for s in nba_stats.MAC_KAYDI_SUTUNLARI if s not in ("PLAYER_NAME", "MATCHUP")]


def fark_say(ad, a, b, anahtar, sutunlar, goster=5):
    """İki tabloyu anahtar üzerinden birleştirir; yalnız birinde olan ve değeri farklı satırları sayar ve yazar."""
    a, b = a.set_index(anahtar)[sutunlar], b.set_index(anahtar)[sutunlar]
    yalniz_a, yalniz_b = a.index.difference(b.index), b.index.difference(a.index)
    ortak = a.index.intersection(b.index)
    x, y = a.loc[ortak], b.loc[ortak]
    farkli = ~((x == y) | (x.isna() & y.isna()))
    satir = farkli.any(axis=1)
    print(f"{ad}: stats {len(a)} satır, cdn {len(b)} satır; yalnız stats'ta {len(yalniz_a)}, yalnız cdn'de {len(yalniz_b)}, "
          f"değeri farklı {int(satir.sum())} satır" + (f" (sütun başına: {farkli.sum()[farkli.sum() > 0].to_dict()})" if satir.any() else ""))
    for etiket, dizin, tablo in (("yalnız stats", yalniz_a, a), ("yalnız cdn", yalniz_b, b)):
        for k in list(dizin)[:goster]:
            print(f"    {etiket}: {k} {tablo.loc[k].to_dict()}")
    for k in list(ortak[satir])[:goster]:
        print(f"    farklı: {k} " + ", ".join(f"{s}: stats {x.loc[k, s]} / cdn {y.loc[k, s]}" for s in sutunlar if farkli.loc[k, s]))
    return len(yalniz_a) + len(yalniz_b) + int(satir.sum())


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    tarihten, tarihe = (argv + [None, None])[:2]
    print(f"aralık: {tarihten or config.SEZON_BASLANGIC} .. {tarihe or 'bugün'}\n")
    toplam = 0

    s_mac, s_belirsiz = nba_stats.fikstur()
    c_mac, c_belirsiz = nba_cdn.fikstur()
    toplam += fark_say("fikstür", pd.DataFrame(s_mac), pd.DataFrame(c_mac), "mac_id", [k for k in s_mac[0] if k != "mac_id"])
    print(f"    takımı belirsiz maçlar aynı mı: {sorted(s_belirsiz) == sorted(c_belirsiz)} ({len(s_belirsiz)} / {len(c_belirsiz)})")
    toplam += sorted(s_belirsiz) != sorted(c_belirsiz)

    toplam += fark_say("oyuncu listesi", pd.DataFrame(nba_stats.oyuncu_listesi()), pd.DataFrame(nba_cdn.oyuncu_listesi()), "oyuncu_id", ["isim", "takim_id"])

    s_oyuncu = nba_stats.oyuncu_mac_kayitlari(tarihten=tarihten, tarihe=tarihe)
    c_oyuncu = nba_cdn.oyuncu_mac_kayitlari(tarihten=tarihten, tarihe=tarihe)
    s_oyuncu["GAME_DATE"] = s_oyuncu["GAME_DATE"].str[:10]
    sutunlar = [s for s in OYUNCU_SUTUNLARI if s not in ("PLAYER_ID", "GAME_ID")]
    toplam += fark_say("oyuncu maç kayıtları", s_oyuncu, c_oyuncu, ["GAME_ID", "PLAYER_ID"], sutunlar)
    print(f"    maç sayısı: stats {s_oyuncu['GAME_ID'].nunique()}, cdn {c_oyuncu['GAME_ID'].nunique()}")

    s_takim = nba_stats.takim_mac_kayitlari(tarihten=tarihten, tarihe=tarihe)
    c_takim = nba_cdn.takim_mac_kayitlari(tarihten=tarihten, tarihe=tarihe)
    # stats'ta tek takımın dakikası eksik gelebiliyor; yükleyici maçın süresi olarak iki satırın büyüğünü alır, burada da öyle.
    for df in (s_takim, c_takim):
        df["MIN"] = df.groupby("GAME_ID")["MIN"].transform("max").astype(int)
    toplam += fark_say("takım maç kayıtları", s_takim, c_takim, ["GAME_ID", "TEAM_ID"], [s for s in nba_stats.TAKIM_KAYDI_SUTUNLARI if s not in ("TEAM_ID", "GAME_ID")])

    conn = veritabani.baglan()
    kayitli = pd.DataFrame([dict(s) for s in conn.execute("""
        SELECT om.mac_id, om.oyuncu_id, om.takim_id, om.ilk_bes, om.dakika FROM oyuncu_mac om JOIN maclar m USING (mac_id)
        WHERE om.ilk_bes IS NOT NULL AND m.tarih >= ? AND m.tarih <= ?""", (tarihten or "0", tarihe or "9"))])
    conn.close()
    cdn_kutu = pd.DataFrame([{"mac_id": mac_id, "oyuncu_id": kimlik, **k} for mac_id in sorted(c_oyuncu["GAME_ID"].unique())
                             for kimlik, k in nba_cdn.kutu_skoru(mac_id).items()])
    kayitli = kayitli[kayitli["dakika"] > 0]            # veritabanında süre almamış oyuncu satırı da olabilir; kutu skorunda olmaz
    for df in (kayitli, cdn_kutu):
        df["dakika"] = df["dakika"].round(3)
    toplam += fark_say("kutu skoru: dakika ve ilk beş (stats = veritabanı)", kayitli, cdn_kutu, ["mac_id", "oyuncu_id"], ["takim_id", "ilk_bes", "dakika"])

    print(f"\ntoplam fark: {toplam}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
