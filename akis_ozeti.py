"""Son çalıştırmaların adım adım sonucunu (calisma_kaydi) Markdown tablo olarak yazar. GitHub iş akışının özet sayfası içindir.

Çalıştırma:  python akis_ozeti.py [çalıştırma sayısı]        (verilmezse son 1 çalıştırma)
"""
import sqlite3
import sys

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
adet = int(sys.argv[1]) if len(sys.argv) > 1 else 1
conn = sqlite3.connect(config.DB_YOLU)
conn.row_factory = sqlite3.Row
calismalar = [s[0] for s in conn.execute("SELECT calisma_id FROM calisma_kaydi GROUP BY calisma_id ORDER BY MAX(kayit_id) DESC LIMIT ?", (adet,))][::-1]
print(f"Veri kaynağı: `{config.VERI_KAYNAGI}`\n")
for calisma in calismalar:
    print(f"### {calisma}\n\n| adım | sonuç | süre (sn) | hata |\n|---|---|---:|---|")
    for s in conn.execute("SELECT adim, sonuc, sure_sn, hata_iletisi FROM calisma_kaydi WHERE calisma_id = ? ORDER BY kayit_id", (calisma,)):
        print(f"| {s['adim']} | {s['sonuc']} | {s['sure_sn']:.1f} | {(s['hata_iletisi'] or '').replace('|', '/')[:200]} |")
    print()
tarih = conn.execute("SELECT MAX(tarih) FROM tahminler WHERE tur = 'canli'").fetchone()[0]
print(f"Canlı tahmin ({tarih}): " + ", ".join(f"{s[0]} {s[1]} satır" for s in conn.execute(
    "SELECT calistirma, COUNT(*) FROM tahminler WHERE tur = 'canli' AND tarih = ? GROUP BY calistirma", (tarih,))))
takipli = conn.execute("SELECT MAX(m.tarih) FROM takip_mac t JOIN maclar m USING (mac_id)").fetchone()[0]
oynanan = conn.execute("SELECT MAX(tarih) FROM maclar WHERE durum = 'oynandi'").fetchone()[0]
print(f"\nTakip verisi olan son maç günü: {takipli}; oynanmış son maç günü: {oynanan}")
