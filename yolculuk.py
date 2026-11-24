"""Salonlar ve yolculuk / dinlenme hesabı (PLAN_EK etken 7'nin verisi).

salonlar.csv elle hazırlanmış sabit tablodur: her maç şehri için enlem, boylam, saat dilimi, rakım.
Koordinatlar yaklaşıktır (şehir düzeyinde doğru); fikstürdeki her maç şehri bu dosyada olmalıdır.

Her takım-maç için fikstürden hesaplananlar (yolculuk tablosu):
- dinlenme_gunu: önceki maçtan bu yana aradaki boş gün sayısı (arka arkaya maçta 0; sezonun ilk maçında boş)
- km: önceki maçın oynandığı şehirden bu maçın şehrine kuş uçuşu mesafe (sezonun ilk maçında kendi şehrinden)
- saat_dilimi_farki: bu şehrin saati − önceki şehrin saati (artı: doğuya gidildi)
- rakim_m: maçın oynandığı şehrin rakımı
- son 4 günde 3. maç mı, son 6 günde 4. maç mı, deplasman serisinin kaçıncı maçı

Fikstür önceden bilindiği için oynanmamış maçlar da hesaplanır.

Çalıştırma:  .venv\\Scripts\\python.exe yolculuk.py
"""
import csv
import math
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import config
import veritabani

SALON_SUTUNLARI = ("sehir", "takim", "salon", "enlem", "boylam", "saat_dilimi", "rakim_m")


def salonlari_oku(yol=None):
    """salonlar.csv -> satır listesi. Eksik sütun, bozuk sayı ya da bilinmeyen saat dilimi hata verir."""
    yol = yol or config.SALONLAR_YOLU
    satirlar = []
    with open(yol, encoding="utf-8-sig", newline="") as f:
        okuyucu = csv.DictReader(f)
        if set(SALON_SUTUNLARI) - set(okuyucu.fieldnames or []):
            raise ValueError(f"{yol.name}: sütunlar {SALON_SUTUNLARI} olmalı")
        for no, s in enumerate(okuyucu, 2):
            try:
                ZoneInfo(s["saat_dilimi"])
                satirlar.append({"sehir": s["sehir"].strip(), "takim": s["takim"].strip() or None, "salon": s["salon"].strip(),
                                 "enlem": float(s["enlem"]), "boylam": float(s["boylam"]), "saat_dilimi": s["saat_dilimi"].strip(),
                                 "rakim_m": float(s["rakim_m"])})
            except Exception as e:
                raise ValueError(f"{yol.name} satır {no}: geçersiz kayıt ({type(e).__name__}: {e})") from e
    return satirlar


def salonlari_yukle(conn):
    """salonlar.csv dosyasını salonlar tablosuna yazar; satır sayısını döndürür."""
    return veritabani.yaz(conn, "salonlar", salonlari_oku())


def mesafe_km(enlem1, boylam1, enlem2, boylam2):
    """İki nokta arasındaki kuş uçuşu mesafe (haversine)."""
    f1, f2 = math.radians(enlem1), math.radians(enlem2)
    a = math.sin((f2 - f1) / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(math.radians(boylam2 - boylam1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def saat_farki(dilim1, dilim2, tarih):
    """dilim2'nin saati − dilim1'in saati (saat cinsinden), verilen günün öğlesinde. Artı: dilim2 daha doğuda."""
    ogle = datetime.fromisoformat(tarih + "T12:00:00")
    fark = ogle.replace(tzinfo=ZoneInfo(dilim2)).utcoffset() - ogle.replace(tzinfo=ZoneInfo(dilim1)).utcoffset()
    return fark.total_seconds() / 3600


def yolculuk_hesapla(conn):
    """Fikstürdeki her takım-maç için yolculuk ve dinlenme bilgisini hesaplar; yolculuk tablosunun satırlarını döndürür.

    Şehri salonlar tablosunda olmayan bir maç varsa hata verir.
    """
    salon = {s["sehir"]: s for s in conn.execute("SELECT * FROM salonlar")}
    ev_sehri = {s["takim_id"]: s["sehir"] for s in conn.execute("SELECT t.takim_id, s.sehir FROM salonlar s JOIN takimlar t ON t.kisaltma = s.takim")}
    maclar = conn.execute("SELECT mac_id, tarih, ev_takim_id, dep_takim_id, salon_sehri FROM maclar WHERE durum <> 'ertelendi' ORDER BY tarih, mac_id").fetchall()
    bilinmeyen = sorted({m["salon_sehri"] for m in maclar if m["salon_sehri"] not in salon} - {None})
    eksik = [m["mac_id"] for m in maclar if m["salon_sehri"] is None]
    if bilinmeyen or eksik:
        raise ValueError(f"salonlar.csv dosyasında olmayan maç şehirleri: {bilinmeyen}; şehri boş maç sayısı: {len(eksik)} (önce 'yukle.py fikstur' çalıştırılmalı)")

    satirlar, gecmis = [], {}                     # gecmis: takım -> [(tarih, şehir, ev mi)]
    for m in maclar:
        for takim_id, ev_mi in ((m["ev_takim_id"], 1), (m["dep_takim_id"], 0)):
            onceki = gecmis.setdefault(takim_id, [])
            sehir, gun = m["salon_sehri"], date.fromisoformat(m["tarih"])
            nereden = onceki[-1][1] if onceki else ev_sehri[takim_id]
            a, b = salon[nereden], salon[sehir]
            gunler = [date.fromisoformat(t) for t, _, _ in onceki]
            deplasman_sirasi = 0
            if not ev_mi:
                deplasman_sirasi = 1
                for _, _, onceki_ev in reversed(onceki):
                    if onceki_ev:
                        break
                    deplasman_sirasi += 1
            satirlar.append({
                "takim_id": takim_id, "mac_id": m["mac_id"], "ev_mi": ev_mi,
                "dinlenme_gunu": (gun - gunler[-1]).days - 1 if gunler else None,
                "km": mesafe_km(a["enlem"], a["boylam"], b["enlem"], b["boylam"]),
                "saat_dilimi_farki": saat_farki(a["saat_dilimi"], b["saat_dilimi"], m["tarih"]),
                "rakim_m": b["rakim_m"],
                "uc_dortte": int(sum((gun - g).days <= 3 for g in gunler) >= 2),      # son 4 günde 3. maç
                "dort_altida": int(sum((gun - g).days <= 5 for g in gunler) >= 3),    # son 6 günde 4. maç
                "deplasman_sirasi": deplasman_sirasi,
            })
            onceki.append((m["tarih"], sehir, ev_mi))
    return satirlar


def yolculugu_yaz(conn):
    """Salonları ve yolculuk tablosunu yeniden yazar; yolculuk satır sayısını döndürür."""
    salonlari_yukle(conn)
    return veritabani.yaz(conn, "yolculuk", yolculuk_hesapla(conn))


def rapor_metni(conn):
    tek = lambda sql: conn.execute(sql).fetchone()[0]
    s = ["=== Yolculuk ve dinlenme raporu ==="]
    s.append(f"Salon: {tek('SELECT COUNT(*) FROM salonlar')} şehir. Maç: {tek('SELECT COUNT(*) FROM maclar')}; "
             f"yolculuk satırı: {tek('SELECT COUNT(*) FROM yolculuk')} (her maç için iki takım); "
             f"km, saat dilimi farkı ya da rakımı boş satır: {tek('SELECT COUNT(*) FROM yolculuk WHERE km IS NULL OR saat_dilimi_farki IS NULL OR rakim_m IS NULL')}; "
             f"dinlenme günü boş (sezonun ilk maçı): {tek('SELECT COUNT(*) FROM yolculuk WHERE dinlenme_gunu IS NULL')}")
    o = conn.execute("""
        SELECT AVG(km) AS km, MAX(km) AS en_uzun, AVG(dinlenme_gunu = 0) AS aa, AVG(uc_dortte) AS uc, AVG(dort_altida) AS dort,
               AVG(ABS(saat_dilimi_farki) >= 2) AS saat, AVG(ev_mi = 0 AND rakim_m >= 1200) AS rakim, AVG(deplasman_sirasi >= 4) AS seri
        FROM yolculuk""").fetchone()
    s.append(f"Maç başına ortalama yol {o['km']:.0f} km (en uzun {o['en_uzun']:.0f} km). Takım-maçların "
             f"%{100 * o['aa']:.1f}'i arka arkaya ikinci maç, %{100 * o['uc']:.1f}'i 4 günde 3. maç, %{100 * o['dort']:.1f}'i 6 günde 4. maç, "
             f"%{100 * o['saat']:.1f}'inde 2+ saat dilimi farkı, %{100 * o['rakim']:.1f}'i yüksek rakım deplasmanı, %{100 * o['seri']:.1f}'i deplasman serisinin 4.+ maçı.")
    s.append("\nTakım başına sezon boyu toplam yol (km): en çok ve en az gezen beşer takım")
    takimlar = conn.execute("SELECT t.kisaltma, SUM(y.km) AS km, SUM(y.dinlenme_gunu = 0) AS aa FROM yolculuk y JOIN takimlar t USING (takim_id) GROUP BY 1 ORDER BY km DESC").fetchall()
    s.append("  " + ", ".join(f"{t['kisaltma']} {t['km']:,.0f} ({t['aa']} arka arkaya)" for t in takimlar[:5]))
    s.append("  " + ", ".join(f"{t['kisaltma']} {t['km']:,.0f} ({t['aa']} arka arkaya)" for t in takimlar[-5:]))
    for baslik, kosul in (("BUGÜNÜN MAÇLARI", f"m.tarih = '{veritabani.abd_bugun()}'"), ("EN UZUN YOLCULUKLAR", "1 = 1 ORDER BY y.km DESC LIMIT 6")):
        s.append(f"\n{baslik}")
        s.append(f"  {'tarih':<12}{'takım':<6}{'maç':<12}{'şehir':<16}{'dinlenme':>9}{'km':>8}{'saat farkı':>12}{'rakım m':>9}{'4 günde 3':>11}{'6 günde 4':>11}{'dep. serisi':>12}")
        for r in conn.execute(f"""
                SELECT m.tarih, t.kisaltma, e.kisaltma AS ev, d.kisaltma AS dep, m.salon_sehri, y.* FROM yolculuk y
                JOIN maclar m USING (mac_id) JOIN takimlar t ON t.takim_id = y.takim_id
                JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id WHERE {kosul}"""):
            s.append(f"  {r['tarih']:<12}{r['kisaltma']:<6}{r['dep'] + ' @ ' + r['ev']:<12}{r['salon_sehri'][:15]:<16}"
                     f"{r['dinlenme_gunu'] if r['dinlenme_gunu'] is not None else '-':>9}{r['km']:>8.0f}{r['saat_dilimi_farki']:>+12.0f}{r['rakim_m']:>9.0f}"
                     f"{'evet' if r['uc_dortte'] else '':>11}{'evet' if r['dort_altida'] else '':>11}{r['deplasman_sirasi'] or '':>12}")
    return "\n".join(s)


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    baglanti = veritabani.baglan()
    veritabani.sema_kur(baglanti)
    yolculugu_yaz(baglanti)
    metin = rapor_metni(baglanti)
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "yolculuk.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
