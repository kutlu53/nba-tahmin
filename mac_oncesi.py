"""Maç öncesi çalıştırma (PLAN_EK bölüm 10).

    .venv\\Scripts\\python.exe mac_oncesi.py                 akşam: henüz başlamamış bütün maçlar yenilenir
    .venv\\Scripts\\python.exe mac_oncesi.py --yaklasan 40   yalnızca 40 dakika içinde başlayacak maçlar yenilenir

Sabah çalıştırmasının göremediği, gün içinde netleşen veriler yeniden çekilir: sakatlıklar (ESPN ve
NBA resmi raporu), bahis çizgileri, hakem atamaları, ilk beşler. Ardından yalnızca HENÜZ BAŞLAMAMIŞ
maçların tahminleri yenilenir ve "kesin tahmin" olarak işaretlenir. Başlamış maçların tahmini olduğu
gibi kalır.

--yaklasan kipi sık aralıklarla (örneğin 15 dakikada bir) çalıştırılmak içindir: yaklaşan maç yoksa
hiçbir kaynağa gitmeden hemen çıkar; varsa kesin ilk beşleri ve son sakatlık durumunu yakalar.
Sabah tahmini on_tahmin sütununda saklandığı için ön ve kesin tahmin sonradan ayrı ayrı puanlanır.

Çıkış kodu: 0 hepsi tamam (ya da yapılacak iş yok), 2 kritik olmayan adım(lar) başarısız, 1 kritik adım başarısız.
"""
import sys
from datetime import datetime, timedelta, timezone

import gunluk
import site_veri
import tahmin
import veritabani
import yukle


def aksam_adimlari(tarih, pencere_dk=None):
    """[(adım adı, kritik mi, işlev(conn)), ...]; pencere_dk verilirse yalnızca o kadar dakika içinde başlayacak maçlar tahmin edilir."""
    adimlar = [
        ("sakatlik", False, yukle.sakatliklari_yukle),
        ("resmi_sakatlik", False, lambda c: yukle.resmi_sakatliklari_yukle(c, tarih)),
        ("oranlar", False, lambda c: yukle.oranlari_yukle(c, tarih)),
        ("atamalar", False, lambda c: yukle.atamalari_yukle(c, tarih)),
        ("ilk_besler", False, lambda c: yukle.ilk_besleri_yukle(c, tarih)),
    ]
    if pencere_dk is None:
        adimlar.append(("onsuz_ve_hakem_tablolari", False, lambda c: gunluk._tablolari_yaz(c, tarih)))
    adimlar.append(("tahmin", True, lambda c: len(tahmin.gunu_tahmin_et(c, tarih, calistirma="mac_oncesi", yalniz_baslamamis=True, pencere_dk=pencere_dk))))
    adimlar.append(("site_veri", False, lambda c: len(site_veri.hazirla(c))))      # paylaşılan web sayfası için JSON dosyaları
    return adimlar


def yaklasan_mac_sayisi(conn, tarih, pencere_dk):
    """Şu andan itibaren pencere_dk dakika içinde başlayacak, henüz başlamamış maç sayısı."""
    simdi = datetime.now(timezone.utc)
    bicim = "%Y-%m-%dT%H:%M:%SZ"
    return conn.execute("SELECT COUNT(*) FROM maclar WHERE tarih = ? AND durum = 'oynanacak' AND baslama_utc > ? AND baslama_utc <= ?",
                        (tarih, simdi.strftime(bicim), (simdi + timedelta(minutes=pencere_dk)).strftime(bicim))).fetchone()[0]


def main(argv):
    pencere_dk = None
    if argv[:1] == ["--yaklasan"] and len(argv) == 2 and argv[1].isdigit():
        pencere_dk = int(argv[1])
    elif argv:
        print(__doc__)
        return 2
    tarih = veritabani.abd_bugun()
    if pencere_dk is not None:
        conn = veritabani.baglan()
        try:
            if not yaklasan_mac_sayisi(conn, tarih, pencere_dk):
                return 0            # yaklaşan maç yok: yapılacak iş yok
        finally:
            conn.close()
    yukle.log_kur(f"mac_oncesi_{tarih}")
    kod, basarisiz, rapor_yolu = gunluk.calistir("mac_yaklasan" if pencere_dk is not None else "mac_oncesi", aksam_adimlari(tarih, pencere_dk), tarih)
    return kod


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
