"""Windows Görev Zamanlayıcı görevlerini kurar, kaldırır ya da durumunu gösterir (PLAN adım 9, PLAN_EK bölüm 10).

    .venv\\Scripts\\python.exe gorev_kur.py           görevleri kurar (varsa günceller)
    .venv\\Scripts\\python.exe gorev_kur.py durum     görevlerin durumunu gösterir
    .venv\\Scripts\\python.exe gorev_kur.py kaldir    görevleri kaldırır

Kurulan görevler (saatler config.py içinden; bilgisayarın yerel saati, yani Türkiye saati):
    NBA-Sabah        her gün config.SABAH_SAATI        gunluk.py                    veri toplama ve ön tahmin
    NBA-MacOncesi    her gün config.MAC_ONCESI_SAATI   mac_oncesi.py                sakatlık, oran, hakem, ilk beş; kesin tahmin
    NBA-MacYaklasan  config.YAKLASAN_ARALIK_DK dakikada bir   mac_oncesi.py --yaklasan N   yalnızca N dakika içinde başlayacak maçlar
    NBA-Haftalik     config.HAFTALIK_GUN günleri config.HAFTALIK_SAATI   haftalik.py       haftalık rapor ve etken katkı testi
    NBA-TakipGonder  her gün config.TAKIP_GONDER_SAATI takip_gonder.py              takip verisini çekip GitHub deposuna gönderir

Görevler oturum açmış kullanıcının adına, penceresiz (pythonw.exe) çalışır. Bilgisayar o saatte
kapalıysa ya da oturum açık değilse görev, ilk fırsatta (açılışta / oturum açılınca) çalışır.
NBA-MacYaklasan yaklaşan maç yoksa bir saniyede çıkar. Bilgisayar uykudayken çalışmaz; uyandırması
istenirse config.GOREV_UYANDIR = True yapılıp bu betik yeniden çalıştırılır.
Çıktı log/ klasörüne ve calisma_kaydi tablosuna yazılır.
"""
import subprocess
import sys

import config

GUNLUK = "New-ScheduledTaskTrigger -Daily -At '{saat}'"
# 15 dakikada bir, gün boyu: günlük tetikleyiciye yineleme eklenir.
YINELENEN = ("$t = New-ScheduledTaskTrigger -Daily -At '00:00'; "
             "$t.Repetition = (New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes {aralik}) "
             "-RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 59)).Repetition; $t")
HAFTALIK = "New-ScheduledTaskTrigger -Weekly -DaysOfWeek {gun} -At '{saat}'"

# ad: (tetikleyici, betik ve argümanları, açıklama, zaman açıklaması, uyandırabilir mi)
GOREVLER = {
    "NBA-Sabah": (GUNLUK.format(saat=config.SABAH_SAATI), "gunluk.py", "NBA tahmin sistemi: sabah veri toplama ve ön tahmin",
                  f"her gün {config.SABAH_SAATI}", False),
    "NBA-MacOncesi": (GUNLUK.format(saat=config.MAC_ONCESI_SAATI), "mac_oncesi.py", "NBA tahmin sistemi: maç öncesi güncelleme ve kesin tahmin",
                      f"her gün {config.MAC_ONCESI_SAATI}", False),
    "NBA-MacYaklasan": (YINELENEN.format(aralik=config.YAKLASAN_ARALIK_DK), f"mac_oncesi.py --yaklasan {config.MAC_YAKLASAN_DK}",
                        "NBA tahmin sistemi: yakında başlayacak maçların tahminini kesin ilk beşle yeniler",
                        f"{config.YAKLASAN_ARALIK_DK} dakikada bir", True),
    "NBA-Haftalik": (HAFTALIK.format(gun=config.HAFTALIK_GUN, saat=config.HAFTALIK_SAATI), "haftalik.py",
                     "NBA tahmin sistemi: haftalık rapor ve etken katkı testi", f"{config.HAFTALIK_GUN} günleri {config.HAFTALIK_SAATI}", False),
    "NBA-TakipGonder": (GUNLUK.format(saat=config.TAKIP_GONDER_SAATI), "takip_gonder.py", "NBA tahmin sistemi: takip verisini çekip GitHub deposuna gönderir",
                        f"her gün {config.TAKIP_GONDER_SAATI}", False),
}
PYTHONW = config.KOK / ".venv" / "Scripts" / "pythonw.exe"


def powershell(komut):
    sonuc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", komut], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return sonuc.returncode, (sonuc.stdout + sonuc.stderr).strip()


def kur():
    if not PYTHONW.exists():
        print(f"Bulunamadı: {PYTHONW}")
        return 1
    kod = 0
    for ad, (tetik, betik, aciklama, zaman, uyandirabilir) in GOREVLER.items():
        uyandir = " -WakeToRun" if uyandirabilir and config.GOREV_UYANDIR else ""
        komut = f"""
            $eylem = New-ScheduledTaskAction -Execute '{PYTHONW}' -Argument '{betik}' -WorkingDirectory '{config.KOK}'
            $tetik = {tetik}
            $ayar = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1){uyandir}
            Register-ScheduledTask -TaskName '{ad}' -Action $eylem -Trigger $tetik -Settings $ayar -Description '{aciklama}' -Force -ErrorAction Stop | Out-Null
            'kuruldu'"""
        sonuc, cikti = powershell(komut)
        print(f"{ad}: {zaman} -> {betik}: {'kuruldu' if sonuc == 0 else 'KURULAMADI'}" + (" (bilgisayarı uyandırır)" if uyandir else "")
              + ("" if sonuc == 0 else f"\n  {cikti}"))
        kod = kod or sonuc
    return kod


def durum():
    kod = 0
    for ad in GOREVLER:
        komut = f"""
            $g = Get-ScheduledTask -TaskName '{ad}' -ErrorAction Stop; $b = $g | Get-ScheduledTaskInfo
            '{ad}: durum ' + $g.State + '; sonraki çalışma ' + $b.NextRunTime + '; son çalışma ' + $b.LastRunTime + '; son sonuç kodu ' + $b.LastTaskResult
            '  komut: ' + $g.Actions[0].Execute + ' ' + $g.Actions[0].Arguments + ' (klasör ' + $g.Actions[0].WorkingDirectory + ')'"""
        sonuc, cikti = powershell(komut)
        print(cikti if sonuc == 0 else f"{ad}: kurulu değil")
        kod = kod or sonuc
    return kod


def kaldir():
    for ad in GOREVLER:
        sonuc, cikti = powershell(f"Unregister-ScheduledTask -TaskName '{ad}' -Confirm:$false -ErrorAction Stop")
        print(f"{ad}: {'kaldırıldı' if sonuc == 0 else 'kaldırılamadı (kurulu olmayabilir)'}")
    return 0


if __name__ == "__main__":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    islem = sys.argv[1] if len(sys.argv) > 1 else "kur"
    if islem not in ("kur", "durum", "kaldir"):
        print(__doc__)
        sys.exit(2)
    sys.exit({"kur": kur, "durum": durum, "kaldir": kaldir}[islem]())
