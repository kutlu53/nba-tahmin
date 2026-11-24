"""Veritabanındaki takip verisini günlük dosyalara yazar (config.TAKIP_KLASORU/YYYY-AA-GG.json).

stats.nba.com'a ulaşabilen bilgisayarda, sabah çalıştırmasından sonra çalıştırılır. Dosyalar, takip verisini
kendisi çekemeyen makineye (config.VERI_KAYNAGI = "cdn") gönderilir; o makine yukle.takip_verisini_yukle ile okur.
Yalnızca yeni ya da içeriği değişen dosyalar yazılır; veritabanına dokunulmaz.

Çalıştırma:  .venv\\Scripts\\python.exe takip_aktar.py [tarihten]        (tarihten: YYYY-AA-GG; verilmezse bütün sezon)
"""
import sys

import config
import veritabani
from kaynak import takip_dosya


def aktar(conn, tarihten=None):
    """Döndürür: (takip verisi olan gün sayısı, yazılan dosyaların tarihleri)."""
    gunler = {}
    for s in conn.execute(f"""
            SELECT m.tarih, t.oyuncu_id, {', '.join('t.' + sutun for sutun in takip_dosya.SUTUNLAR)}
            FROM takip_mac t JOIN maclar m USING (mac_id) WHERE m.tarih >= ? ORDER BY m.tarih, t.oyuncu_id""",
            (tarihten or config.SEZON_BASLANGIC,)):
        gunler.setdefault(s["tarih"], {})[s["oyuncu_id"]] = {sutun: s[sutun] for sutun in takip_dosya.SUTUNLAR}
    return len(gunler), [tarih for tarih, veri in gunler.items() if takip_dosya.gunu_yaz(tarih, veri)]


def main(argv):
    if len(argv) > 1:
        print(__doc__)
        return 2
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    conn = veritabani.baglan()
    try:
        gun, yazilan = aktar(conn, argv[0] if argv else None)
    finally:
        conn.close()
    print(f"takip verisi: {gun} günün {len(yazilan)} tanesinin dosyası yazıldı ({config.TAKIP_KLASORU})"
          + (f": {yazilan[0]} .. {yazilan[-1]}" if yazilan else "; hepsi günceldi"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
