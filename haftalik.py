"""Haftalık rapor (PLAN bölüm 8) ve etken katkı testinin yenilenmesi (PLAN_EK E11).

Çalıştırma:  .venv\\Scripts\\python.exe haftalik.py        (yaklaşık 7 dakika)

1. Geriye dönük denemeyi güncel veriyle yeniden çalıştırır (yeni oynanan maçlar dahil).
2. raporlar/haftalik_YYYY-AA-GG.txt: canlı tahminlerin ve geriye dönük denemenin hata, güven dilimi,
   aralık kapsamı ve ön / kesin tahmin özeti.
3. raporlar/etken_katki_testi.txt: her etkenin açıkken ve kapalıyken hatası. Kapalı bir etken
   "yararlı" görünmeye başlarsa ya da açık bir etken "zararlı" olursa config.py elle güncellenir;
   bu betik ayarları kendiliğinden değiştirmez.
"""
import logging
import sys

import config
import geri_test
import katki_testi
import veritabani
import yukle

log = logging.getLogger("haftalik")


def main():
    tarih = veritabani.abd_bugun()
    yukle.log_kur(f"haftalik_{tarih}")
    logging.getLogger("etkenler").setLevel(logging.CRITICAL)
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        geri_test.puanla(conn, "canli")
        geri_test.gecmisi_dene(conn)
        parcalar = [geri_test.rapor_metni(conn, "canli"), geri_test.rapor_metni(conn, "geri_test")]
        config.RAPOR_KLASORU.mkdir(exist_ok=True)
        (config.RAPOR_KLASORU / f"haftalik_{tarih}.txt").write_text("\n\n\n".join(parcalar) + "\n", encoding="utf-8")
        log.info("Haftalık rapor yazıldı")
        metin, _ = katki_testi.rapor(conn)
        (config.RAPOR_KLASORU / "etken_katki_testi.txt").write_text(metin + "\n", encoding="utf-8")
        log.info("Etken katkı testi yazıldı")
        return 0
    except Exception:
        log.exception("Haftalık çalıştırma başarısız")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
