"""Üst / alt seçimlerinin analizi: kalibrasyon ve kayıp nedenleri. Veritabanını salt okunur açar; hiçbir şey yazmaz.

    .venv\\Scripts\\python.exe ua_analiz.py            (yaklaşık 20 saniye)

Seçim kuralı sayfadakiyle aynıdır (site_veri.ust_alt_secimleri); burada ayrıca seçilmeyen adaylar da tutulur
(daha büyük örneklem). Bölümler:
    0  canlı ve geriye dönük günlerin ayrı toplamı
    1  kalibrasyon: modelin söylediği yüzde ile gerçekleşen yüzde, taraf ve güven bandına göre; yapısal eğilim
    2  kayıp nedenleri: oynanan dakikanın beklenene oranı, kıl payı sonuçlar
    3  istatistik türü, barem düzeyi ve veri sağlamlığına göre döküm
    4  kural denemeleri: farklı olasılık eşikleriyle seçim sayısı ve tutma oranı (örneklem içi; yön gösterir, kanıt değildir)
    5  beklenen ve oynanan dakika

İlk çalıştırma 24 Kasım 2026: alt seçimleri kalibreli (söylenen %76,6, gerçekleşen %76,0; 171 seçim), üst seçimleri
5 puan iyimser (%62,9'a karşı %57,9; 114 seçim); üstte kayıpların çoğu oyuncunun beklenenden az oynadığı maçlardan.
O gün ayar değiştirilmedi; 8–10 canlı gün birikince yeniden bakılacak.

25 Kasım 2026: seçimler artık modelin kattığı farka göre sıralanıyor (gerekçe ve ölçümler site_veri.py içinde); yukarıdaki
sayılar eski sıralamaya (en yüksek olasılık) aittir. Satırlardaki "barem kendiliğinden", model sezon ortalamasına hiçbir
şey katmasaydı aynı seçimlerin tutma olasılığıdır.
"""
import math
import sqlite3
import sys

import pandas as pd

import config
import site_veri as sv
import ust_alt

BANTLAR = ((0.50, 0.58), (0.58, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 1.01))
AZ, COK = 0.85, 1.15          # oynanan / beklenen dakika: altı "az oynadı", üstü "çok oynadı"


def adaylar(df, tarih, tur):
    """O günün bütün adayları (taraf olasılığı >= 0,5). Süzmeler site_veri.ust_alt_secimleri ile aynı.

    Geriye dönük günde yalnızca oynayanlar adaydır. Canlı günde oynamayan oyuncu da adaydır (sayfada o gün seçilmiş
    olabilir); onun 'tuttu' değeri None kalır ve sayımlara girmez.
    """
    if tur != "canli" and not df.empty:
        df = df[df["gerceklesen"].notna()]
    if df.empty:
        return []
    t, u, g, so, gr = (df.pivot(index="oyuncu_id", columns="istatistik", values=k) for k in ("tahmin", "ust", "guven", "sezon_ort", "gerceklesen"))
    bilgi = df[df["istatistik"] == "sayi"].set_index("oyuncu_id")
    cikti = []
    for kimlik in bilgi.index:
        b = bilgi.loc[kimlik]
        if pd.isna(b["dakika"]) or b["dakika"] < sv.UA_MIN_DAKIKA:
            continue
        for ist, en_kucuk in sv.UA_ISTATISTIKLERI.items():
            sezon = sum(so.loc[kimlik, p] for p in config.BIRLESIK.get(ist, (ist,)))
            if pd.isna(sezon) or pd.isna(u.loc[kimlik, ist]) or g.loc[kimlik, ist] < sv.UA_MIN_GUVEN:
                continue
            cizgi = math.floor(sezon) + 0.5
            if cizgi < en_kucuk:
                continue
            tahmin = float(t.loc[kimlik, ist])
            sapma = (float(u.loc[kimlik, ist]) - tahmin) / config.ARALIK_Z
            p = ust_alt.ust_olasiligi(tahmin, sapma, cizgi)
            p0 = sv.barem_olasiligi(sezon, tahmin, sapma, cizgi)
            taraf, olasilik, olasilik0 = ("ust", p, p0) if p >= 0.5 else ("alt", 1 - p, 1 - p0)
            oynadi = not pd.isna(gr.loc[kimlik, ist])
            gercek = float(gr.loc[kimlik, ist]) if oynadi else None
            cikti.append({"tarih": tarih, "tur": tur, "kimlik": int(kimlik), "oyuncu": b["isim"], "mac_id": b["mac_id"], "ist": ist, "cizgi": cizgi,
                          "taraf": taraf, "p": olasilik, "p0": olasilik0, "fark": olasilik - olasilik0, "tahmin": tahmin, "sezon": float(sezon), "guven": float(g.loc[kimlik, ist]),
                          "bdk": float(b["dakika"]), "gercek": gercek, "ust_oldu": int(gercek > cizgi) if oynadi else None,
                          "tuttu": int((gercek > cizgi) == (taraf == "ust")) if oynadi else None})
    return cikti


def sec(gunluk, esik=None, adet=None):
    """Sayfadaki seçim: taraf başına en çok 'adet' oyuncu, olasılık eşiğin üstünde. esik: {'ust': x, 'alt': y}

    Sıralama o günün kuralıyladır (site_veri.fark_sirasi_mi): modelin kattığı fark ya da, 25 Kasım 2026'dan önceki canlı
    günlerde, en yüksek olasılık. Döndürülen liste yalnızca sonuçlanmış seçimleri içerir (seçilip de oynamayan oyuncu
    yer tutar ama sayılmaz).
    """
    esik = esik or {"ust": sv.UA_MIN_OLASILIK, "alt": sv.UA_MIN_OLASILIK}
    fark_sirasi = bool(gunluk) and sv.fark_sirasi_mi(gunluk[0]["tarih"], gunluk[0]["tur"])
    olcut = "fark" if fark_sirasi else "p"
    secilen = []
    for taraf in ("ust", "alt"):
        gorulen = set()
        for a in sorted((a for a in gunluk if a["taraf"] == taraf and a["p"] >= esik[taraf] and (a["fark"] > 0 or not fark_sirasi)), key=lambda a: -a[olcut]):
            if a["kimlik"] not in gorulen:
                gorulen.add(a["kimlik"])
                secilen.append(a)
                if len(gorulen) == (adet or sv.UA_ADET):
                    break
    return [a for a in secilen if a["tuttu"] is not None]


def wilson(k, n, z=1.96):
    """Oranın %95 güven aralığı."""
    p = k / n
    orta, yari = (p + z * z / (2 * n)) / (1 + z * z / n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return orta - yari, orta + yari


def satir(ad, x):
    n, k = len(x), sum(a["tuttu"] for a in x)
    if not n:
        return f"  {ad:<26} {'-':>5}"
    alt, ust = wilson(k, n)
    soylenen = sum(a["p"] for a in x) / n
    return (f"  {ad:<26} {n:>5}  söylenen %{100 * soylenen:4.1f}  gerçekleşen %{100 * k / n:4.1f}  "
            f"({k}/{n}; %95 aralık {100 * alt:.0f}–{100 * ust:.0f})  fark {100 * (k / n - soylenen):+5.1f}"
            f"  barem kendiliğinden %{100 * sum(a['p0'] for a in x) / n:4.1f}")


def dk_sinifi(a):
    if a["odk"] is None or not a["bdk"]:
        return "bilinmiyor"
    oran = a["odk"] / a["bdk"]
    return "az oynadı" if oran < AZ else "çok oynadı" if oran > COK else "beklenen kadar"


def veriyi_topla(conn):
    """Döndürür: (tarihler, {tarih: adaylar}). Günler sayfadaki Geçmiş sekmesiyle aynı; oynamayan oyuncular sayılmaz."""
    gunler = {}
    for tur in ("geri_test", "canli"):           # canlı tahmini olan günde canlı olan kullanılır
        for s in conn.execute("SELECT DISTINCT tarih FROM tahminler WHERE tur = ? AND gerceklesen IS NOT NULL", (tur,)):
            gunler[s[0]] = tur
    tarihler = sorted(gunler)[-sv.GECMIS_GUN:]
    dakika = {(s["oyuncu_id"], s["mac_id"]): s["dakika"] for s in conn.execute("SELECT oyuncu_id, mac_id, dakika FROM oyuncu_mac")}
    gun_adaylari = {}
    for tarih in tarihler:
        gun_adaylari[tarih] = adaylar(sv._tahminler(conn, tarih, gunler[tarih]), tarih, gunler[tarih])
        for a in gun_adaylari[tarih]:
            a["odk"] = dakika.get((a["kimlik"], a["mac_id"]))
    return tarihler, gun_adaylari


def rapor(conn, yaz=print):
    tarihler, gun_adaylari = veriyi_topla(conn)
    hepsi = [a for t in tarihler for a in gun_adaylari[t] if a["tuttu"] is not None]
    secilenler = [a for t in tarihler for a in sec(gun_adaylari[t])]
    if not secilenler:
        yaz("Sonuçlanmış seçim yok.")
        return
    oran = lambda x: f"{sum(a['tuttu'] for a in x)}/{len(x)}" + (f" (%{100 * sum(a['tuttu'] for a in x) / len(x):.1f})" if x else "")
    yaz(f"gün: {len(tarihler)} ({tarihler[0]} .. {tarihler[-1]}); aday: {len(hepsi)}; sayfada gösterilen seçim: {oran(secilenler)}")

    yaz("\n0) CANLI ve GERİYE DÖNÜK GÜNLER — sayfada gösterilen seçimler")
    for ad, tur in (("canlı (maçtan önce yayımlanan)", "canli"), ("geriye dönük", "geri_test")):
        x = [a for a in secilenler if a["tur"] == tur]
        yaz(f"  {ad:<32} {len({a['tarih'] for a in x}):>3} gün; hepsi {oran(x)}; üst {oran([a for a in x if a['taraf'] == 'ust'])}; alt {oran([a for a in x if a['taraf'] == 'alt'])}")

    for baslik, kume in (("1a) KALİBRASYON — sayfada gösterilen seçimler", secilenler), ("1b) KALİBRASYON — bütün adaylar (seçilmeyenler dahil)", hepsi)):
        yaz(f"\n{baslik}")
        for taraf in ("ust", "alt"):
            yaz(f" {taraf.upper()}")
            for alt, ust in BANTLAR:
                x = [a for a in kume if a["taraf"] == taraf and alt <= a["p"] < ust]
                if x:
                    yaz(satir(f"%{100 * alt:.0f}–{100 * ust - 1:.0f}", x))
            yaz(satir("toplam", [a for a in kume if a["taraf"] == taraf]))

    yaz("\n1c) YAPISAL EĞİLİM — bütün adaylarda, modelden bağımsız: gerçek değerin baremin (sezon ort., buçuklu) üstünde kalma oranı")
    for ist in list(sv.UA_ISTATISTIKLERI) + [None]:
        x = [a for a in hepsi if ist is None or a["ist"] == ist]
        if x:
            yaz(f"  {ist or 'hepsi':<20} {len(x):>5} aday; üst oldu %{100 * sum(a['ust_oldu'] for a in x) / len(x):.1f}; modelin üst dediği %{100 * sum(a['taraf'] == 'ust' for a in x) / len(x):.1f}")
    yaz(f"  'her zaman alt' deseydik tutma oranı: %{100 * (1 - sum(a['ust_oldu'] for a in hepsi) / len(hepsi)):.1f}; modelin daha olası bulduğu taraf: %{100 * sum(a['tuttu'] for a in hepsi) / len(hepsi):.1f}")
    for taraf in ("ust", "alt"):
        x = [a for a in secilenler if a["taraf"] == taraf]
        if x:
            yaz(f"  seçilen {taraf}: tahmin / sezon ortalaması {sum(a['tahmin'] / a['sezon'] for a in x) / len(x):.2f}; gerçekleşen / sezon ortalaması {sum(a['gercek'] / a['sezon'] for a in x) / len(x):.2f}")

    yaz("\n2) KAYIP NEDENLERİ — sayfada gösterilen seçimler")
    for taraf in ("ust", "alt"):
        x = [a for a in secilenler if a["taraf"] == taraf]
        kayip = [a for a in x if not a["tuttu"]]
        yaz(f" {taraf.upper()}: {len(x)} seçim, {len(kayip)} kayıp")
        for sinif in ("az oynadı", "beklenen kadar", "çok oynadı"):
            y = [a for a in x if dk_sinifi(a) == sinif]
            if y:
                yaz(f"   dakika {sinif:<16} {len(y):>4} seçim (%{100 * len(y) / len(x):.0f}); tutan {oran(y)}")
        kil = [a for a in kayip if abs(a["gercek"] - a["cizgi"]) <= 0.5]
        kil_kazanc = [a for a in x if a["tuttu"] and abs(a["gercek"] - a["cizgi"]) <= 0.5]
        aleyhe = "az oynadı" if taraf == "ust" else "çok oynadı"
        dk_kayip = [a for a in kayip if dk_sinifi(a) == aleyhe]
        ikisi = [a for a in kil if dk_sinifi(a) == aleyhe]
        yaz(f"   kayıpların dökümü: kıl payı (yarım fark) {len(kil)}; aleyhe dakika sapması ({aleyhe}) {len(dk_kayip)}; ikisi birden {len(ikisi)}; "
            f"ikisi de değil {len(kayip) - len(kil) - len(dk_kayip) + len(ikisi)}")
        yaz(f"   karşılaştırma: kıl payı tutanlar {len(kil_kazanc)} (kıl payı kayıp {len(kil)})")

    yaz("\n3) İSTATİSTİK TÜRÜ, BAREM DÜZEYİ, VERİ SAĞLAMLIĞI — sayfada gösterilen seçimler")
    gruplar = [(ist, lambda a, ist=ist: a["ist"] == ist) for ist in sv.UA_ISTATISTIKLERI] + [
        ("barem 1,5–2,5", lambda a: a["cizgi"] <= 2.5), ("barem 3,5–9,5", lambda a: 2.5 < a["cizgi"] < 10), ("barem 10,5 ve üstü", lambda a: a["cizgi"] > 10),
        ("veri sağlamlığı 60–69", lambda a: a["guven"] < 70), ("veri sağlamlığı 70–79", lambda a: 70 <= a["guven"] < 80), ("veri sağlamlığı 80+", lambda a: a["guven"] >= 80)]
    for taraf in ("ust", "alt"):
        yaz(f" {taraf.upper()}")
        for ad, f in gruplar:
            x = [a for a in secilenler if a["taraf"] == taraf and f(a)]
            if x:
                yaz(satir(ad, x))

    yaz("\n4) KURAL DENEMELERİ — aynı veriyle (örneklem içi; yön gösterir, kanıt değildir). Günlerin ilk ve ikinci yarısı ayrı")
    yari = len(tarihler) // 2
    simdiki = sv.UA_MIN_OLASILIK
    for ad, esik in ((f"şimdiki kural (üst {simdiki} / alt {simdiki})", {"ust": simdiki, "alt": simdiki}), ("üst eşiği 0,65", {"ust": 0.65, "alt": simdiki}),
                     ("üst eşiği 0,70", {"ust": 0.70, "alt": simdiki}), ("üst eşiği 0,75", {"ust": 0.75, "alt": simdiki}), ("üst yok", {"ust": 1.01, "alt": simdiki}),
                     ("üst 0,70 / alt 0,70", {"ust": 0.70, "alt": 0.70}), ("üst 0,75 / alt 0,75", {"ust": 0.75, "alt": 0.75})):
        parcalar = []
        for dilim in (tarihler, tarihler[:yari], tarihler[yari:]):
            x = [a for t in dilim for a in sec(gun_adaylari[t], esik)]
            parcalar.append(f"{oran(x)}, üst {oran([a for a in x if a['taraf'] == 'ust'])}")
        yaz(f"  {ad:<34} hepsi {parcalar[0]} | ilk yarı {parcalar[1]} | ikinci yarı {parcalar[2]}")

    yaz("\n5) BEKLENEN ve OYNANAN DAKİKA")
    for ad, kume in (("seçilen üst", [a for a in secilenler if a["taraf"] == "ust"]), ("seçilen alt", [a for a in secilenler if a["taraf"] == "alt"]),
                     ("bütün adaylar (oyuncu-maç başına bir kez)", list({(a["kimlik"], a["mac_id"]): a for a in hepsi}.values()))):
        x = [a for a in kume if a["odk"] is not None]
        if x:
            siniflar = [dk_sinifi(a) for a in x]
            yaz(f"  {ad:<44} {len(x):>5}; beklenen {sum(a['bdk'] for a in x) / len(x):.1f} dk, oynanan {sum(a['odk'] for a in x) / len(x):.1f} dk; "
                f"az oynayan %{100 * siniflar.count('az oynadı') / len(x):.0f}, çok oynayan %{100 * siniflar.count('çok oynadı') / len(x):.0f}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    conn = sqlite3.connect(f"file:{config.DB_YOLU.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rapor(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
