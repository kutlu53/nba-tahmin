"""Takip verisini çeker ve GitHub deposuna gönderir. Bilgisayarda çalışır (Görev Zamanlayıcı: NBA-TakipGonder).

    .venv\\Scripts\\python.exe takip_gonder.py

GitHub'ın makineleri takip verisini (olası asist, ribaund fırsatı) kendileri çekemez: stats.nba.com onlara yanıt
vermiyor. Bu betik o veriyi bilgisayardan depoya taşır; depoya gelen dosyaları oradaki akış veritabanına işler.

1. takip          Veritabanında takip verisi eksik maç günlerini stats.nba.com'dan çeker (sabah akışındaki adımın
                  aynısı; önceki gecenin verisi sabah 10:00'da henüz yayımlanmamış olduğu için burada yeniden denenir).
2. takip_aktar    Veritabanındaki takip verisini günlük dosyalara yazar (takip_verisi/YYYY-AA-GG.json).
3. depoya_gonder  Depo kopyasını günceller, yeni ya da değişen dosyaları oraya kopyalar, işler ve gönderir.

Bir adım başarısız olursa sonrakiler yine denenir (veri çekilemese de eldeki dosyalar gönderilir). Yeniden
çalıştırılabilir: gönderilecek yeni dosya yoksa hiçbir şey göndermez.
Çıktı log/takip_gonder_<tarih>.log dosyasına ve calisma_kaydi tablosuna yazılır.
Çıkış kodu: 0 hepsi tamam, 2 bir adım başarısız.
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
    if not degisen:
        log.info("Depoya gönderilecek yeni takip dosyası yok")
        return []
    gunler = sorted(ad.removesuffix(".json") for ad in degisen)
    git(depo, "commit", "--quiet", "-m", "Takip verisi: " + (gunler[0] if len(gunler) == 1 else f"{gunler[0]} .. {gunler[-1]} ({len(gunler)} gün)"),
        "--", "takip_verisi")
    git(depo, "push", "--quiet", "origin", f"HEAD:{DAL}")
    log.info("Depoya gönderildi: %s", ", ".join(degisen))
    return degisen


def main():
    tarih = veritabani.abd_bugun()
    yukle.log_kur(f"takip_gonder_{tarih}")
    calisma_id = f"takip_gonder-{tarih}-{uuid.uuid4().hex[:8]}"
    conn = veritabani.baglan()
    basarisiz = []
    try:
        veritabani.sema_kur(conn)
        for ad, islev in (("takip", lambda: yukle.takip_verisini_yukle(conn)),
                          ("takip_aktar", lambda: takip_aktar.aktar(conn)),
                          ("depoya_gonder", depoya_gonder)):
            try:
                yukle.adim(conn, calisma_id, ad, islev)
            except Exception:
                log.exception("Adım başarısız: %s", ad)
                basarisiz.append(ad)
    finally:
        conn.close()
    log.info("takip_gonder bitti; başarısız adımlar: %s", ", ".join(basarisiz) or "-")
    return 2 if basarisiz else 0


if __name__ == "__main__":
    sys.exit(main())
