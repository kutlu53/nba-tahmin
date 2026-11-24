"""Bulut (GitHub Actions) çalıştırmasının zamanlayıcısı: her tetiklemede sırası gelen akışı seçer.

Bilgisayarda Görev Zamanlayıcı dört görevi kendi saatinde başlatır (gorev_kur.py). GitHub'ın zamanlanmış
tetiklemeleri ise gecikebilir ya da atlanabilir. O yüzden orada tek bir iş akışı 15 dakikada bir tetiklenir ve
bu betik veritabanındaki calisma_kaydi tablosuna bakıp yapılmamış işi seçer; geciken ya da atlanan bir
tetiklemenin işini sonraki tetikleme yapar. Saatler bilgisayardakiyle aynıdır (config.py, Türkiye saati):

    sabah        gunluk.py: günün (ABD tarihi) sabah akışı henüz tamamlanmadıysa, SABAH_SAATI'nden sonra
    haftalik     haftalik.py: HAFTALIK_GUN günü HAFTALIK_SAATI'nden sonra, o gün çalışmadıysa
    mac_oncesi   mac_oncesi.py: akşam akışı henüz tamamlanmadıysa, MAC_ONCESI_SAATI'nden sonra
    yaklasan     mac_oncesi.py --yaklasan: MAC_YAKLASAN_DK dakika içinde başlayacak maç varsa
    yok          yapılacak iş yok

Tamamlanamayan sabah ve akşam akışı günde en çok DENEME_SINIRI kez denenir.

    python bulut.py karar [otomatik|sabah|mac_oncesi|yaklasan|haftalik]   "kip=..." ve "gerekce=..." satırlarını yazar
    python bulut.py kaydet haftalik <çıkış kodu> <süre sn>                haftalik.py sonucunu calisma_kaydi tablosuna yazar

Yalnızca standart kitaplığı kullanır: iş akışında bağımlılıklar kurulmadan önce çalışır.
"""
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import veritabani

TR = ZoneInfo("Europe/Istanbul")          # config.py'deki çalıştırma saatleri Türkiye saatidir
GUN_ADLARI = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
KIPLER = ("sabah", "haftalik", "mac_oncesi", "yaklasan", "yok")
DENEME_SINIRI = 3


def _esik(gun, saat):
    """O günün Türkiye saatiyle verilen saati."""
    return datetime.combine(gun, time.fromisoformat(saat), TR)


def _calismalar(conn, ad, tarih):
    """(o günkü deneme sayısı, tahmin adımı tamamlanan deneme var mı)"""
    on_ek = f"{ad}-{tarih}-"
    deneme, tamam = conn.execute(
        "SELECT COUNT(DISTINCT calisma_id), COALESCE(MAX(adim = 'tahmin' AND sonuc = 'tamam'), 0) "
        "FROM calisma_kaydi WHERE substr(calisma_id, 1, ?) = ?", (len(on_ek), on_ek)).fetchone()
    return deneme, bool(tamam)


def yaklasan_mac_sayisi(conn, tarih, simdi, pencere_dk):
    """mac_oncesi.yaklasan_mac_sayisi ile aynı sorgu (o modül bağımlılık istediği için burada yinelenir)."""
    bicim = "%Y-%m-%dT%H:%M:%SZ"
    return conn.execute("SELECT COUNT(*) FROM maclar WHERE tarih = ? AND durum = 'oynanacak' AND baslama_utc > ? AND baslama_utc <= ?",
                        (tarih, simdi.strftime(bicim), (simdi + timedelta(minutes=pencere_dk)).strftime(bicim))).fetchone()[0]


def karar(conn, simdi):
    """Döndürür: (kip, gerekçe). simdi: saat dilimi bilgili zaman."""
    simdi = simdi.astimezone(timezone.utc)
    gun = simdi.astimezone(ZoneInfo(config.MAC_SAAT_DILIMI)).date()      # maç günü ABD tarihiyle belirlenir
    tarih = gun.isoformat()

    deneme, tamam = _calismalar(conn, "sabah", tarih)
    if not tamam:
        if simdi < _esik(gun, config.SABAH_SAATI):
            return "yok", f"{tarih} sabah akışının saati ({config.SABAH_SAATI}) henüz gelmedi"
        if deneme >= DENEME_SINIRI:
            return "yok", f"{tarih} sabah akışı {deneme} kez denendi, tamamlanamadı; elle bakılmalı"
        return "sabah", f"{tarih} sabah akışı henüz tamamlanmadı ({deneme + 1}. deneme)"

    if GUN_ADLARI[gun.weekday()] == config.HAFTALIK_GUN and simdi >= _esik(gun, config.HAFTALIK_SAATI) \
            and not _calismalar(conn, "haftalik", tarih)[0]:
        return "haftalik", f"{tarih} haftalık raporu henüz yazılmadı"

    deneme, tamam = _calismalar(conn, "mac_oncesi", tarih)
    if not tamam and simdi >= _esik(gun, config.MAC_ONCESI_SAATI) and deneme < DENEME_SINIRI:
        return "mac_oncesi", f"{tarih} maç öncesi akışı henüz tamamlanmadı ({deneme + 1}. deneme)"

    yaklasan = yaklasan_mac_sayisi(conn, tarih, simdi, config.MAC_YAKLASAN_DK)
    if yaklasan:
        return "yaklasan", f"{config.MAC_YAKLASAN_DK} dakika içinde başlayacak {yaklasan} maç var"
    return "yok", "sırası gelen akış yok"


def kaydet(conn, ad, cikis_kodu, sure_sn, simdi=None):
    """calisma_kaydi tablosuna kendisi yazmayan bir betiğin (haftalik.py) sonucunu ekler."""
    tarih = (simdi or datetime.now(timezone.utc)).astimezone(ZoneInfo(config.MAC_SAAT_DILIMI)).date().isoformat()
    veritabani.kayit_yaz(conn, f"{ad}-{tarih}-{uuid.uuid4().hex[:8]}", ad, "tamam" if cikis_kodu == 0 else "hata",
                         None if cikis_kodu == 0 else f"çıkış kodu {cikis_kodu}", sure_sn)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    komut, *gerisi = argv or [""]
    if komut == "karar" and len(gerisi) <= 1 and (gerisi or ["otomatik"])[0] in ("otomatik",) + KIPLER[:-1]:
        istenen = (gerisi or ["otomatik"])[0]
        if istenen != "otomatik":
            kip, gerekce = istenen, "elle seçildi"
        else:
            conn = veritabani.baglan()
            try:
                kip, gerekce = karar(conn, datetime.now(timezone.utc))
            finally:
                conn.close()
        print(f"kip={kip}\ngerekce={gerekce}")
        return 0
    if komut == "kaydet" and len(gerisi) == 3 and gerisi[0] == "haftalik" and gerisi[1].isdigit() and gerisi[2].isdigit():
        conn = veritabani.baglan()
        try:
            kaydet(conn, gerisi[0], int(gerisi[1]), float(gerisi[2]))
        finally:
            conn.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
