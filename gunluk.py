"""Günlük akış, tek giriş noktası (PLAN bölüm 9, PLAN_EK bölüm 10: sabah çalıştırması).

Çalıştırma:  .venv\\Scripts\\python.exe gunluk.py

Sırayla: fikstür, dünkü maç kayıtları, takım kutu skorları, kullanım oranları, takip verisi, hakemler,
kapanış oranları, kadro ve pozisyonlar, sakatlıklar, günün oranları, hakem atamaları, yolculuk, savunma
profili, onsuz ve hakem tabloları, dünkü tahminlerin puanlanması, bugünün tahminleri, Excel raporu.

- Her adımın sonucu calisma_kaydi tablosuna ve log/ klasörüne yazılır.
- "Kritik" bir adım (fikstür, maç kayıtları, tahmin) başarısız olursa akış durur.
- Diğer adımlar başarısız olursa akış sürer; ilgili etken o gün "veri yok" ile devre dışı kalır ve rapora not düşülür.
- Yeniden çalıştırılabilir: aynı gün ikinci kez çalışınca veri çoğalmaz, tahminler ve rapor güncellenir.

Çıkış kodu: 0 hepsi tamam, 2 kritik olmayan adım(lar) başarısız, 1 kritik adım başarısız.
"""
import logging
import sys
import uuid
from datetime import date, timedelta

import config
import geri_test
import kadro
import rapor
import savunma
import site_veri
import tahmin
import veritabani
import yolculuk
import yukle
from etkenler import hakem, kullanim

log = logging.getLogger("gunluk")

GERIYE_GUN = 4      # maç kayıtları bu kadar gün geriden yeniden okunur (geç gelen istatistik düzeltmeleri için)


def _tablolari_yaz(conn, tarih):
    """Bağlama dayanan görüntü tabloları: onsuz_etkisi ve hakem_profili."""
    baglam = tahmin.Baglam(conn, tarih)
    return kullanim.tabloyu_yaz(conn, baglam, tarih), hakem.profili_yaz(conn, baglam, tarih)


def sabah_adimlari(tarih):
    """[(adım adı, kritik mi, işlev(conn)), ...]"""
    geriden = (date.fromisoformat(tarih) - timedelta(days=GERIYE_GUN)).isoformat()
    return [
        ("fikstur", True, yukle.fiksturu_yukle),
        ("mac_kayitlari", True, lambda c: yukle.mac_kayitlarini_yukle(c, tarihten=geriden)),
        ("takim_mac", False, lambda c: yukle.takim_kayitlarini_yukle(c, tarihten=geriden)),
        ("kullanim", False, yukle.kullanim_oranlarini_yaz),
        ("takip", False, yukle.takip_verisini_yukle),
        ("hakemler", False, yukle.hakemleri_yukle),
        ("gecmis_oranlar", False, yukle.gecmis_oranlari_yukle),
        ("kadro", False, kadro.kadrolari_yukle),
        ("sakatlik", False, yukle.sakatliklari_yukle),
        ("resmi_sakatlik", False, lambda c: yukle.resmi_sakatliklari_yukle(c, tarih)),
        ("oranlar", False, lambda c: yukle.oranlari_yukle(c, tarih)),
        ("atamalar", False, lambda c: yukle.atamalari_yukle(c, tarih)),
        ("ilk_besler", False, lambda c: yukle.ilk_besleri_yukle(c, tarih)),
        ("yolculuk", False, yolculuk.yolculugu_yaz),
        ("savunma_profili", False, lambda c: savunma.profili_yaz(c, tarih)),
        ("onsuz_ve_hakem_tablolari", False, lambda c: _tablolari_yaz(c, tarih)),
        ("puanlama", False, lambda c: geri_test.puanla(c, "canli")),
        ("tahmin", True, lambda c: len(tahmin.gunu_tahmin_et(c, tarih, calistirma="sabah"))),
        ("site_veri", False, lambda c: len(site_veri.hazirla(c))),      # paylaşılan web sayfası için JSON dosyaları
    ]


def calistir(ad, adimlar, tarih, conn=None):
    """Adımları sırayla çalıştırır, sonunda raporu yazar. Döndürür: (çıkış kodu, başarısız adımlar, rapor yolu)."""
    kendi_baglantisi = conn is None
    conn = conn or veritabani.baglan()
    calisma_id = f"{ad}-{tarih}-{uuid.uuid4().hex[:8]}"
    basarisiz, kritik_hata, rapor_yolu = [], False, None
    try:
        veritabani.sema_kur(conn)
        log.info("%s çalıştırması başladı (%s, %s)", ad, tarih, calisma_id)
        for adim_adi, kritik, islev in adimlar:
            try:
                yukle.adim(conn, calisma_id, adim_adi, lambda: islev(conn))
            except Exception as e:
                log.exception("Adım başarısız: %s", adim_adi)
                basarisiz.append(adim_adi)
                if kritik:
                    kritik_hata = True
                    log.error("Kritik adım başarısız olduğu için akış durduruldu: %s (%s: %s)", adim_adi, type(e).__name__, e)
                    break
        try:
            rapor_yolu = yukle.adim(conn, calisma_id, "rapor", lambda: rapor.excel_yaz(conn, tarih, calisma_id))
        except Exception:
            log.exception("Rapor yazılamadı")
            basarisiz.append("rapor")
        kod = 1 if kritik_hata else 2 if basarisiz else 0
        log.info("%s çalıştırması bitti: %s; başarısız adımlar: %s; rapor: %s", ad,
                 "KRİTİK HATA" if kritik_hata else "tamam" if not basarisiz else "eksikle tamam", ", ".join(basarisiz) or "-", rapor_yolu or "-")
        return kod, basarisiz, rapor_yolu
    finally:
        if kendi_baglantisi:
            conn.close()


def main():
    tarih = veritabani.abd_bugun()
    yukle.log_kur(f"gunluk_{tarih}")
    kod, basarisiz, rapor_yolu = calistir("sabah", sabah_adimlari(tarih), tarih)
    return kod


if __name__ == "__main__":
    sys.exit(main())
