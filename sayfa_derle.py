"""GitHub Pages sayfasını derler: sayfa/index.html ile site_veri/ klasöründeki JSON dosyalarını bir klasörde toplar.

    python sayfa_derle.py <çıktı klasörü>

Çıktı klasörüne iki dosya yazar:
    index.html   sayfa/index.html dosyasının kopyası
    veri.json    {"derleme": zaman, "ozet": ..., "gun": günün belgesi ya da null, "gecmis": [yeniden eskiye günler]}

site_veri/ klasörünü site_veri.py hazırlar (gunluk.py ve mac_oncesi.py her çalıştırmada çağırır). Sayfa yalnızca
veri.json dosyasını okur; böylece bir güncelleme ya bütünüyle görünür ya hiç görünmez.

Yalnızca standart kitaplığı kullanır.
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import config

VERI_KLASORU = config.KOK / "site_veri"
SAYFA = config.KOK / "sayfa" / "index.html"
GECMIS_GUN = 40


def derle(cikti, veri_klasoru=None, sayfa=None):
    """Döndürür: özet sözlüğü {'bugun', 'gun_var', 'gecmis_gun', 'bayt'}. ozet.json yoksa FileNotFoundError verir."""
    veri_klasoru, sayfa, cikti = Path(veri_klasoru or VERI_KLASORU), Path(sayfa or SAYFA), Path(cikti)
    oku = lambda yol: json.loads(yol.read_text(encoding="utf-8"))
    ozet = oku(veri_klasoru / "ozet.json")
    gun_yolu = veri_klasoru / f"gun_{ozet.get('bugun')}.json"
    gun = oku(gun_yolu) if gun_yolu.exists() else None
    gecmis = [oku(yol) for yol in sorted(veri_klasoru.glob("gecmis_*.json"), reverse=True)[:GECMIS_GUN]]
    veri = {"derleme": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ozet": ozet, "gun": gun, "gecmis": gecmis}
    cikti.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sayfa, cikti / "index.html")
    metin = json.dumps(veri, ensure_ascii=False, separators=(",", ":"))
    (cikti / "veri.json").write_text(metin, encoding="utf-8", newline="\n")
    return {"bugun": ozet.get("bugun"), "gun_var": gun is not None, "gecmis_gun": len(gecmis), "bayt": len(metin.encode("utf-8"))}


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        o = derle(argv[0])
    except FileNotFoundError as e:
        print(f"sayfa derlenemedi: {e}")
        return 1
    print(f"sayfa derlendi: {argv[0]} (gün {o['bugun']}{'' if o['gun_var'] else ', günün belgesi yok'}; {o['gecmis_gun']} geçmiş gün; veri.json {o['bayt']} bayt)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
