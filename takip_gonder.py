"""Takip verisini çeker ve GitHub deposuna gönderir. Bilgisayarda çalışır (Görev Zamanlayıcı: NBA-TakipGonder).

    .venv\\Scripts\\python.exe takip_gonder.py

GitHub'ın makineleri takip verisini (olası asist, ribaund fırsatı) kendileri çekemez: stats.nba.com onlara yanıt
vermiyor. Bu betik o veriyi bilgisayardan depoya taşır; depoya gelen dosyaları oradaki akış veritabanına işler.

Sık aralıklarla (config.TAKIP_GONDER_ARALIK_DK) çalıştırılmak içindir: yapılacak iş yoksa hiçbir kaynağa gitmeden
ve kayıt bırakmadan bir saniyede çıkar. Yapılacak iş: takip verisi eksik bir maç günü, dosyası henüz depoda
olmayan bir gün ya da gönderilememiş bir işleme. Böylece veri yayımlanır yayımlanmaz ve bilgisayar stats.nba.com'a
ulaşabildiği ilk anda (bazı ağlar bu bağlantıya izin vermiyor) gönderilir.

1. takip          Veritabanında takip verisi eksik maç günlerini stats.nba.com'dan çeker (sabah akışındaki adımın
                  aynısı; önceki gecenin verisi sabah 10:00'da henüz yayımlanmamış olduğu için burada yeniden denenir).
2. takip_aktar    Veritabanındaki takip verisini günlük dosyalara yazar (takip_verisi/YYYY-AA-GG.json).
3. depoya_gonder  Depo kopyasını günceller, yeni ya da değişen dosyaları oraya kopyalar, işler ve gönderir.

Veri çekilemezse ve gönderilecek bir şey de yoksa 2. ve 3. adım atlanır. Bir adım başarısız olursa sonraki yine
denenir. Çıktı log/takip_gonder_<tarih>.log dosyasına ve calisma_kaydi tablosuna yazılır.
Çıkış kodu: 0 tamam (ya da yapılacak iş yok), 2 bir adım başarısız.
"""
import logging
import os
import shutil
import subprocess
import sys
import uuid

import config
import takip_aktar
import veritabani
import yukle

log = logging.getLogger("takip_gonder")

DEPO = config.KOK / "github_depo"        # GitHub deposunun bu bilgisayardaki kopyası
DAL = "main"


def git(depo, *arg):
    """Depo kopyasında bir git komutu çalıştırır; çıktısını döndürür, başarısızsa RuntimeError verir. Hiçbir zaman soru sormaz."""
    ortam = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    s = subprocess.run(["git", "-C", str(depo), *arg], capture_output=True, text=True, encoding="utf-8", errors="replace", env=ortam,
                       timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if s.returncode:
        raise RuntimeError(f"git {' '.join(arg)} başarısız: {(s.stderr or s.stdout).strip()[:400]}")
    return s.stdout.strip()


def eksik_gunler(conn):
    """Oynanmış ama takip verisi henüz yazılmamış maç günleri (yukle.takip_verisini_yukle'nin çekmeyi deneyeceği günler)."""
    return [s[0] for s in conn.execute("""
        SELECT DISTINCT m.tarih FROM maclar m JOIN oyuncu_mac om USING (mac_id)
        WHERE m.durum = 'oynandi' AND m.tarih >= ? AND om.dakika > 0
          AND NOT EXISTS (SELECT 1 FROM takip_mac t JOIN maclar m2 USING (mac_id) WHERE m2.tarih = m.tarih)
        ORDER BY m.tarih""", (config.SEZON_BASLANGIC,))]


def gonderilmemis_gunler(conn, depo=None):
    """Veritabanında takip verisi olup depo kopyasında dosyası bulunmayan günler."""
    depo = depo or DEPO
    return [s[0] for s in conn.execute("SELECT DISTINCT m.tarih FROM takip_mac t JOIN maclar m USING (mac_id) WHERE m.tarih >= ? ORDER BY m.tarih",
                                       (config.SEZON_BASLANGIC,)) if not (depo / "takip_verisi" / f"{s[0]}.json").exists()]


def bekleyen_isleme_var(depo=None):
    """Depo kopyasında gönderilememiş işleme var mı (önceki gönderim yarıda kaldıysa). Ağa çıkmaz."""
    try:
        return git(depo or DEPO, "rev-list", "--count", f"origin/{DAL}..HEAD") != "0"
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return False


def depoya_gonder(depo=None, klasor=None):
    """Takip dosyalarını depo kopyasına taşıyıp gönderir. Döndürür: gönderilen dosya adları (yeni bir şey yoksa boş liste).

    Yalnızca takip_verisi/ altındaki dosyalar işlenir; depo kopyasında bekleyen başka değişiklik varsa ona dokunulmaz.
    """
    depo, klasor = depo or DEPO, klasor or config.TAKIP_KLASORU
    if not (depo / ".git").exists():
        raise RuntimeError(f"depo kopyası bulunamadı: {depo}")
    git(depo, "pull", "--ff-only", "--quiet", "origin", DAL)
    hedef = depo / "takip_verisi"
    hedef.mkdir(exist_ok=True)
    for yol in sorted(klasor.glob("*.json")):
        if not (hedef / yol.name).exists() or (hedef / yol.name).read_bytes() != yol.read_bytes():
            shutil.copyfile(yol, hedef / yol.name)
    git(depo, "add", "--", "takip_verisi")
    degisen = [ad.split("/")[-1] for ad in git(depo, "diff", "--cached", "--name-only", "--", "takip_verisi").splitlines() if ad]
    if degisen:
        gunler = sorted(ad.removesuffix(".json") for ad in degisen)
        git(depo, "commit", "--quiet", "-m", "Takip verisi: " + (gunler[0] if len(gunler) == 1 else f"{gunler[0]} .. {gunler[-1]} ({len(gunler)} gün)"),
            "--", "takip_verisi")
    if degisen or bekleyen_isleme_var(depo):
        git(depo, "push", "--quiet", "origin", f"HEAD:{DAL}")
    log.info("Depoya gönderildi: %s", ", ".join(degisen) if degisen else "yeni takip dosyası yok")
    return degisen


def main():
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        eksik, gonderilmemis = eksik_gunler(conn), gonderilmemis_gunler(conn)
        if not eksik and not gonderilmemis and not bekleyen_isleme_var():
            return 0                    # yapılacak iş yok
        tarih = veritabani.abd_bugun()
        yukle.log_kur(f"takip_gonder_{tarih}")
        calisma_id = f"takip_gonder-{tarih}-{uuid.uuid4().hex[:8]}"
        log.info("takip_gonder başladı (%s): takip verisi eksik günler: %s; depoda dosyası olmayan günler: %s",
                 calisma_id, ", ".join(eksik) or "-", ", ".join(gonderilmemis) or "-")
        basarisiz = []

        def adim(ad, islev):
            try:
                return yukle.adim(conn, calisma_id, ad, islev)
            except Exception:
                log.exception("Adım başarısız: %s", ad)
                basarisiz.append(ad)

        if eksik:
            adim("takip", lambda: yukle.takip_verisini_yukle(conn))
        if gonderilmemis_gunler(conn) or bekleyen_isleme_var():
            adim("takip_aktar", lambda: takip_aktar.aktar(conn))
            adim("depoya_gonder", depoya_gonder)
        else:
            log.info("Yeni takip verisi alınamadı (henüz yayımlanmamış ya da kaynağa ulaşılamıyor); gönderilecek bir şey yok")
        log.info("takip_gonder bitti; başarısız adımlar: %s", ", ".join(basarisiz) or "-")
        return 2 if basarisiz else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
