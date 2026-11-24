"""Etken katkı testi (PLAN_EK bölüm 11, adım E11).

Her etken için "açıkken hata − kapalıyken hata" tablosunu, yüzde 95 güven aralığıyla çıkarır.
Hatayı düşürdüğü kanıtlanmayan etken kapatılmaya adaydır.

Yöntem:
- Sezonun oynanmış her maç günü için yalnızca o günden önceki veriyle, TÜM etkenler (kapalı olanlar
  dahil) hesaplanır ve her tahminin temel değeri ile etken çarpanları bellekte toplanır.
- Bir etkeni kapatmak, o etkenin çarpanını 1 saymaktır; etkenler birbirinden bağımsız hesaplandığı
  için bu, geriye dönük denemeyi o etken kapalıyken yeniden çalıştırmakla aynı sonucu verir
  (rapor bunu kayıtlı geri test sonucuyla karşılaştırarak doğrular).
- Güven aralığı: farkların gün bazında kümelenmiş standart hatası × 1,96 (aynı günün tahminleri bağımsız değildir).

Sakatlık listesine bağlı etkenler (kullanim, eksik_dakika, eksik_arkadas): geçmiş günlerin sakatlık
listesi elimizde yoktur. Bu etkenler için o gün kimin oynamadığı kutu skorundan alınır; yani
sakatlık listesinin kusursuz bilindiği varsayılır. Bu bir üst sınırdır ve raporda ayrı gösterilir.

Çalıştırma:  .venv\\Scripts\\python.exe katki_testi.py        (yaklaşık 5 dakika; veri tabanına yazmaz)
"""
import copy
import logging
import sys
import time

import numpy as np
import pandas as pd

import config
import etkenler
import geri_test
import tahmin
import veritabani

log = logging.getLogger("katki_testi")

ISTATISTIKLER = list(config.ISTATISTIKLER)
SAKATLIGA_BAGLI = ("kullanim", "eksik_dakika", "eksik_arkadas")


def carpanlari_topla(conn, ayarlar, vekil_eksik=False, kanca=None):
    """Geriye dönük denemeyi bellekte çalıştırır; her puanlanabilir tahmin için temel değer ve etken çarpanlarını döndürür.

    kanca(baglam, maclar): her gün için bağlam kurulduktan sonra çağrılır (deneysel bilgi eklemek için).
    """
    gunler = [s[0] for s in conn.execute("SELECT DISTINCT tarih FROM maclar WHERE durum = 'oynandi' ORDER BY tarih")]
    gercek = {(s["oyuncu_id"], s["mac_id"]): dict(s) for s in conn.execute(
        f"SELECT oyuncu_id, mac_id, {', '.join(ISTATISTIKLER)} FROM oyuncu_mac WHERE dakika > 0")}
    liste = etkenler.acik_etkenler(ayarlar)
    satirlar = []
    for gun in gunler:
        b = tahmin.Baglam(conn, gun, gecmis=True)
        maclar = tahmin.gunun_maclari(conn, gun, "oynandi")
        if kanca is not None:
            kanca(b, maclar)
        if vekil_eksik:     # takımının son 5 maçında oynamış ama o günkü maçta oynamamış oyuncular "Out" sayılır
            for m in maclar:
                for takim in (m.ev_takim_id, m.dep_takim_id):
                    b.sakatlik_takimlari.add(takim)
                    son = b.takim_maclari[takim][-config.ROTASYON_PENCERE:]
                    for kimlik, o in b.oyuncular.items():
                        if o["takim_id"] == takim and any((kimlik, x) in b.dakika for x in son) and (kimlik, m.mac_id) not in gercek:
                            b.sakatlik[kimlik] = "Out"
        for m in maclar:
            for o in tahmin.tahmin_edilecekler(b, m):
                g = gercek.get((o.oyuncu_id, m.mac_id))
                if g is None:
                    continue
                for t in tahmin.oyuncu_tahmini(b, o, m, liste):
                    if t["zincir"] is not None:
                        satirlar.append({"tarih": gun, "oyuncu_id": o.oyuncu_id, "mac_id": m.mac_id, "istatistik": t["istatistik"],
                                         "beklenen_dakika": t["girdiler"]["beklenen_dakika"],
                                         "temel": t["girdiler"]["temel_tahmin"], "gercek": g[t["istatistik"]], "sezon_ort": t["girdiler"]["sezon_ort"],
                                         **{ad: s.carpan for ad, s in t["zincir"].etkenler.items()}})
    return pd.DataFrame(satirlar)


def hata(df, acik):
    """Verilen etkenler açıkken her tahminin mutlak hatası."""
    return (df["temel"] * geri_test.toplam_carpan(df, [e for e in acik if e in df.columns]) - df["gercek"]).abs()


def fark_ve_aralik(fark, tarih):
    """(ortalama fark, yüzde 95 yarı aralık): gün bazında kümelenmiş."""
    gun = fark.groupby(tarih).sum()
    se = np.sqrt(len(gun) / (len(gun) - 1) * ((gun - gun.mean()) ** 2).sum()) / len(fark)
    return float(fark.mean()), float(1.96 * se)


def karsilastir(df, acik_a, acik_b):
    """{istatistik: (A hatası − B hatası, yarı aralık, B hatası, A hatası)}"""
    a, b = hata(df, acik_a), hata(df, acik_b)
    sonuc = {}
    for ist in ISTATISTIKLER:
        s = df["istatistik"] == ist
        ort, yari = fark_ve_aralik((a - b)[s], df["tarih"][s])
        sonuc[ist] = (ort, yari, float(b[s].mean()), float(a[s].mean()))
    return sonuc


def hukum(sonuc):
    """'yararlı': en az bir istatistikte hata kanıtlanmış biçimde düşüyor ve hiçbirinde kanıtlanmış biçimde artmıyor."""
    duser = [i for i, (o, y, _, _) in sonuc.items() if o + y < 0]
    artar = [i for i, (o, y, _, _) in sonuc.items() if o - y > 0]
    if artar and not duser:
        return "zararlı", duser, artar
    if duser and not artar:
        return "yararlı", duser, artar
    if duser and artar:
        return "karışık", duser, artar
    return "etkisiz", duser, artar


def tablo_satirlari(ad, sonuc):
    h, duser, artar = hukum(sonuc)
    hucreler = "".join(f"{(f'{sonuc[i][0]:+.4f}±{sonuc[i][1]:.4f}' if sonuc[i][0] or sonuc[i][1] else '·'):>17}" for i in ISTATISTIKLER)
    return f"  {ad:<15}{hucreler}   {h}" + (f" ({', '.join(duser)})" if duser else "") + (f" [artıyor: {', '.join(artar)}]" if artar else "")


def degisken_ayarla(degisiklik):
    """config değerlerini geçici olarak değiştirir; eski değerleri döndürür."""
    eski = {ad: copy.deepcopy(getattr(config, ad)) for ad in degisiklik}
    for ad, deger in degisiklik.items():
        setattr(config, ad, deger)
    return eski


def duyarlilik(conn, ad, istatistikler, degisiklikler):
    """Tek bir etken için farklı k / sınır değerlerinde hata. Döndürür: {etiket: {istatistik: (fark, yarı aralık)}}; fark = değişik − şimdiki."""
    ayar = {ad: {**config.ETKENLER[ad], "acik": True}}
    temel = carpanlari_topla(conn, ayar)
    simdiki = hata(temel, [ad])
    sonuc = {}
    for etiket, degisiklik in degisiklikler.items():
        eski = degisken_ayarla(degisiklik)
        try:
            df = carpanlari_topla(conn, {ad: {**config.ETKENLER[ad], "acik": True}})
        finally:
            degisken_ayarla(eski)
        yeni = hata(df, [ad])
        sonuc[etiket] = {i: fark_ve_aralik((yeni - simdiki)[temel["istatistik"] == i], temel["tarih"][temel["istatistik"] == i]) for i in istatistikler}
    return sonuc


def rapor(conn):
    t0 = time.monotonic()
    acik = [ad for ad, a in config.ETKENLER.items() if a["acik"]]
    kapali = [ad for ad, a in config.ETKENLER.items() if not a["acik"]]
    hepsi = {ad: {**a, "acik": True} for ad, a in config.ETKENLER.items()}
    df = carpanlari_topla(conn, hepsi, vekil_eksik=True)
    log.info("Çarpanlar toplandı: %d tahmin, %.0f sn", len(df), time.monotonic() - t0)

    s = [f"=== Etken katkı testi ({veritabani.abd_bugun()}) ==="]
    s.append(f"{df['tarih'].nunique()} maç günü ({df['tarih'].min()} – {df['tarih'].max()}), {len(df) // len(ISTATISTIKLER)} oyuncu-maç, istatistik başına {len(df) // len(ISTATISTIKLER)} tahmin.")
    s.append("Değerler: ortalama mutlak hatadaki değişim ± yüzde 95 aralık. Eksi değer hatanın düştüğünü gösterir; '·' etkenin o istatistiğe dokunmadığını.")
    s.append("Hüküm: yararlı = en az bir istatistikte aralığın tamamı sıfırın altında ve hiçbirinde tamamı sıfırın üstünde değil.")
    s.append("Dikkat: tabloda yaklaşık 100 karşılaştırma var; yüzde 95 aralıkla bunların birkaçı yalnızca şans eseri 'anlamlı' görünür.")
    s.append("Hüküm sütunu mekanik bir etikettir; binde birkaçlık etkiler tek başına karar gerekçesi sayılmamalı.")

    # Doğrulama: sakatlığa bağlı olmayan açık etkenlerle yeniden birleştirilen hata, kayıtlı geri test hatasına eşit olmalı.
    kayitli = geri_test.tahminleri_oku(conn)
    kayitli = kayitli[kayitli["gerceklesen"].notna() & kayitli["istatistik"].isin(ISTATISTIKLER)]
    bagimsiz = [e for e in acik if e not in SAKATLIGA_BAGLI]
    yeniden = hata(df, bagimsiz).groupby(df["istatistik"]).mean()
    kayit = kayitli["hata"].abs().groupby(kayitli["istatistik"]).mean()
    s.append(f"Doğrulama: yeniden birleştirilen hata ile kayıtlı geriye dönük deneme arasındaki en büyük fark {float((yeniden - kayit).abs().max()):.1e} "
             f"(sıfıra yakınsa 'etkeni kapatıp yeniden çalıştırmak' ile bu hesap aynı sonucu veriyor demektir).")

    baslik = f"  {'etken':<15}" + "".join(f"{i:>17}" for i in ISTATISTIKLER) + "   hüküm"
    sonuclar = {}
    s.append("\nAÇIK ETKENLER: açıkken hata − kapalıyken hata (diğer açık etkenler yerinde)")
    s.append(baslik)
    for ad in acik:
        sonuclar[ad] = karsilastir(df, acik, [e for e in acik if e != ad])
        s.append(tablo_satirlari(ad, sonuclar[ad]) + ("   *" if ad in SAKATLIGA_BAGLI else ""))
    s.append("\nKAPALI ETKENLER: açılırsa hata ne olur (açık etkenlerin üstüne eklenince)")
    s.append(baslik)
    for ad in kapali:
        sonuclar[ad] = karsilastir(df, acik + [ad], acik)
        s.append(tablo_satirlari(ad, sonuclar[ad]) + ("   *" if ad in SAKATLIGA_BAGLI else ""))
    s.append("  * sakatlık listesine bağlı etken: o gün kimin oynamadığı kutu skorundan alındı (liste kusursuz biliniyor varsayımı; üst sınır).")

    s.append("\nMODEL ve ÖLÇÜT (oyuncunun o güne kadarki sezon maç ortalaması): model hatası − ölçüt hatası")
    olcut = (df["sezon_ort"] - df["gercek"]).abs()
    yararli = [ad for ad in acik if hukum(sonuclar[ad])[0] == "yararlı"]
    for etiket, kume in (("şimdiki açık etkenler", acik), ("yalnız yararlı bulunanlar", yararli), ("hiç etken yok", [])):
        h = hata(df, kume)
        parcalar = []
        for ist in ISTATISTIKLER:
            x = df["istatistik"] == ist
            ort, yari = fark_ve_aralik((h - olcut)[x], df["tarih"][x])
            parcalar.append(f"{ist} {ort:+.3f}±{yari:.3f} (%{100 * (1 - h[x].mean() / olcut[x].mean()):+.1f})")
        s.append(f"  {etiket:<28}" + "  ".join(parcalar))
    s.append(f"  yararlı bulunan etkenler: {', '.join(yararli) or '-'}")

    s.append("\nSINIR ve k DUYARLILIĞI (yalnız yararlı bulunan etkenler; değer = değişik ayar − şimdiki ayar, tek başına o etkenle)")
    denemeler = {
        "sut_duzeltme": (("sayi", "ucluk"), {
            "k yarıya": {"SUT_K": {a: b / 2 for a, b in config.SUT_K.items()}},
            "k iki katına": {"SUT_K": {a: b * 2 for a, b in config.SUT_K.items()}},
            "sınırsız": {"ETKENLER": {**config.ETKENLER, "sut_duzeltme": {**config.ETKENLER["sut_duzeltme"], "alt": 0.01, "ust": 100.0}}}}),
        "firsat": (("asist", "ribaund"), {
            "k yarıya": {"FIRSAT_K": {a: b / 2 for a, b in config.FIRSAT_K.items()}},
            "k iki katına": {"FIRSAT_K": {a: b * 2 for a, b in config.FIRSAT_K.items()}},
            "sınırsız": {"ETKENLER": {**config.ETKENLER, "firsat": {**config.ETKENLER["firsat"], "alt": 0.01, "ust": 100.0}}}}),
        "tempo": (("sayi", "ribaund", "asist"), {
            "sınırsız": {"ETKENLER": {**config.ETKENLER, "tempo": {**config.ETKENLER["tempo"], "alt": 0.01, "ust": 100.0}}},
            "çizgi harmanı kapalı": {"TOPLAM_CIZGISI_HARMAN": False}}),
    }
    for ad, (istatistikler, degisiklikler) in denemeler.items():
        if ad not in yararli:
            continue
        for etiket, deger in duyarlilik(conn, ad, istatistikler, degisiklikler).items():
            s.append(f"  {ad:<14}{etiket:<24}" + "  ".join(f"{i} {o:+.4f}±{y:.4f}" for i, (o, y) in deger.items()))
        log.info("Duyarlılık: %s tamam, %.0f sn", ad, time.monotonic() - t0)
    return "\n".join(s), sonuclar


def main():
    for akis in (sys.stdout, sys.stderr):
        if akis is not None:
            akis.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("etkenler").setLevel(logging.CRITICAL)
    conn = veritabani.baglan()
    try:
        metin, _ = rapor(conn)
        config.RAPOR_KLASORU.mkdir(exist_ok=True)
        (config.RAPOR_KLASORU / "etken_katki_testi.txt").write_text(metin + "\n", encoding="utf-8")
        print(metin)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
