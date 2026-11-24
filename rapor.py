"""Günlük Excel raporu: raporlar/YYYY-AA-GG.xlsx (PLAN bölüm 9, adım 8).

Sayfalar:
- Tahminler: günün maçlarındaki her oyuncu için dakika, yedi istatistik ve birleşik değerlerin tahmini ve güven puanı
- Etken çarpanları: her tahmin (oyuncu × istatistik) için temel tahmin, sonuç ve her etkenin çarpanı
- Etken ayrıntısı: her etkenin verisi var mı, örneklemi ve açıklaması
- Sakatlık: günün sakatlık listesi (ESPN) ve kayıt gelmeyen ("veri yok") takımlar
- Sakatlık karşılaştırma: ESPN ile NBA resmi raporu yan yana; çelişen kayıtlar en üstte ve işaretli
- Savunma: takımların pozisyona göre savunma oranları (sayı)
- Dünün sonuçları: en son puanlanan günün tahminleri, gerçekleşen değerler ve hata
- Geri test: istatistik başına hata özeti (canlı tahminler ve geriye dönük deneme)
- Çalışma: bu çalıştırmanın adımları ve sonuçları

Elle çalıştırma:  .venv\\Scripts\\python.exe rapor.py [YYYY-AA-GG]
"""
import json
import sys

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import config
import geri_test
import sakatlik_karsilastir
import veritabani

ISTATISTIK_ADLARI = {
    "sayi": "Sayı", "ribaund": "Ribaund", "asist": "Asist", "ucluk": "Üçlük", "top_calma": "Top çalma", "blok": "Blok", "top_kaybi": "Top kaybı",
    "sayi+ribaund+asist": "S+R+A", "sayi+ribaund": "S+R", "sayi+asist": "S+A", "ribaund+asist": "R+A",
}
TUM_ISTATISTIKLER = list(config.ISTATISTIKLER) + list(config.BIRLESIK)


def _oku(conn, sql, parametreler=()):
    return pd.DataFrame([dict(s) for s in conn.execute(sql, parametreler)])


def tahmin_tablosu(conn, tarih, tur="canli"):
    """Oyuncu başına bir satır: maç, takım, oyuncu, pozisyon, sakatlık durumu, dakika, tahminler ve güven puanları."""
    df = _oku(conn, """
        SELECT th.mac_id, m.baslama_utc, d.kisaltma || ' @ ' || e.kisaltma AS mac, tk.kisaltma AS takim, o.isim AS oyuncu, o.pozisyon,
               (SELECT s.durum FROM sakatliklar s WHERE s.oyuncu_id = th.oyuncu_id AND s.cekim_tarihi = th.tarih AND s.kaynak = 'espn') AS durum,
               (SELECT s.durum FROM sakatliklar s WHERE s.oyuncu_id = th.oyuncu_id AND s.cekim_tarihi = th.tarih AND s.kaynak = 'nba_resmi') AS resmi,
               th.oyuncu_id, th.istatistik, th.tahmin, th.guven, th.girdiler,
               CASE th.calistirma WHEN 'mac_oncesi' THEN 'kesin' ELSE 'ön' END AS tahmin_turu
        FROM tahminler th JOIN maclar m USING (mac_id) JOIN oyuncular o USING (oyuncu_id)
        JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id
        LEFT JOIN takimlar tk ON tk.takim_id = o.takim_id
        WHERE th.tarih = ? AND th.tur = ?""", (tarih, tur))
    if df.empty:
        return df
    turler = df[df["istatistik"] == "sayi"].set_index("oyuncu_id")["tahmin_turu"]
    df[["durum", "resmi"]] = df[["durum", "resmi"]].fillna("")       # boş değer pivot anahtarında satırı düşürmesin
    anahtar = ["mac_id", "baslama_utc", "mac", "takim", "oyuncu", "pozisyon", "durum", "resmi", "oyuncu_id"]
    sayi = df[df["istatistik"] == "sayi"].set_index("oyuncu_id")["girdiler"].map(json.loads)
    tablo = df.pivot(index=anahtar, columns="istatistik", values="tahmin")[TUM_ISTATISTIKLER].rename(columns=ISTATISTIK_ADLARI)
    guven = df.pivot(index=anahtar, columns="istatistik", values="guven")[list(config.ISTATISTIKLER)].rename(columns=lambda i: f"Güven {ISTATISTIK_ADLARI[i].lower()}")
    tablo = tablo.join(guven).reset_index()
    tablo.insert(8, "Tahmin türü", tablo["oyuncu_id"].map(turler))
    tablo.insert(9, "Beklenen dk", tablo["oyuncu_id"].map(lambda i: sayi[i]["beklenen_dakika"]))
    besleme = {(s["mac_id"], s["takim_id"]) for s in conn.execute("SELECT DISTINCT mac_id, takim_id FROM ilk_bes_beklenti")}
    ilk_bes = {(s["mac_id"], s["oyuncu_id"]): ("ilk beş (kesin)" if s["durum"] == "Confirmed" else "ilk beş (beklenen)")
               for s in conn.execute("SELECT mac_id, oyuncu_id, durum FROM ilk_bes_beklenti WHERE pozisyon IS NOT NULL AND kadro_durumu = 'Active'")}
    takimlar = {s["oyuncu_id"]: s["takim_id"] for s in conn.execute("SELECT oyuncu_id, takim_id FROM oyuncular")}
    bu_gece = [ilk_bes.get((m, o), "yedek" if (m, takimlar.get(o)) in besleme else "") for m, o in zip(tablo["mac_id"], tablo["oyuncu_id"])]
    tablo.insert(10, "Düzeltilmiş dk", tablo["oyuncu_id"].map(lambda i: sayi[i].get("duzeltilmis_dakika", sayi[i]["beklenen_dakika"])))
    tablo.insert(11, "Bu gece", bu_gece)
    tablo = tablo.sort_values(["baslama_utc", "mac_id", "takim", "Düzeltilmiş dk"], ascending=[True, True, True, False])
    tablo = tablo.drop(columns=["mac_id", "baslama_utc", "oyuncu_id"]).rename(columns={"mac": "Maç", "takim": "Takım", "oyuncu": "Oyuncu", "pozisyon": "Poz", "durum": "Sakatlık (ESPN)", "resmi": "Resmi rapor"})
    return tablo.round(2)


def etken_tablolari(conn, tarih, tur="canli"):
    """(çarpan tablosu, ayrıntı tablosu): her tahmin için etken çarpanları yan yana; her etken için açıklama alt alta."""
    df = _oku(conn, """
        SELECT d.kisaltma || ' @ ' || e.kisaltma AS mac, tk.kisaltma AS takim, o.isim AS oyuncu, th.istatistik, th.tahmin_id,
               json_extract(th.girdiler, '$.temel_tahmin') AS temel, th.alt, th.tahmin, th.ust, th.guven,
               te.etken, te.carpan, te.veri_var, te.orneklem, te.aciklama
        FROM tahminler th JOIN tahmin_etken te USING (tahmin_id) JOIN maclar m USING (mac_id) JOIN oyuncular o USING (oyuncu_id)
        JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id
        LEFT JOIN takimlar tk ON tk.takim_id = o.takim_id
        WHERE th.tarih = ? AND th.tur = ? ORDER BY m.baslama_utc, th.mac_id, tk.kisaltma, o.isim, th.tahmin_id""", (tarih, tur))
    if df.empty:
        return df, df
    df["istatistik"] = df["istatistik"].map(ISTATISTIK_ADLARI)
    etkenler = [e for e in config.ETKENLER if e in set(df["etken"])]
    anahtar = ["tahmin_id", "mac", "takim", "oyuncu", "istatistik", "temel", "alt", "tahmin", "ust", "guven"]
    carpan = df.pivot(index=anahtar, columns="etken", values="carpan")[etkenler].reset_index().sort_values("tahmin_id")
    carpan.insert(9, "Toplam çarpan", carpan["tahmin"] / carpan["temel"].where(carpan["temel"] > 0))
    carpan = carpan.drop(columns="tahmin_id").rename(columns={"mac": "Maç", "takim": "Takım", "oyuncu": "Oyuncu", "istatistik": "İstatistik",
                                                              "temel": "Temel tahmin", "alt": "Alt (%10)", "tahmin": "Tahmin", "ust": "Üst (%90)", "guven": "Güven"}).round(3)
    ayrinti = df[["mac", "takim", "oyuncu", "istatistik", "etken", "carpan", "veri_var", "orneklem", "aciklama"]].copy()
    ayrinti["veri_var"] = ayrinti["veri_var"].map({1: "evet", 0: "hayır"})
    ayrinti.columns = ["Maç", "Takım", "Oyuncu", "İstatistik", "Etken", "Çarpan", "Veri var", "Örneklem", "Açıklama"]
    return carpan, ayrinti.round(3)


def sakatlik_tablosu(conn, tarih):
    df = _oku(conn, """
        SELECT t.kisaltma AS "Takım", s.isim AS "Oyuncu", s.durum AS "Durum", s.tahmini_donus AS "Tahmini dönüş (güvenilmez)", s.aciklama AS "Açıklama"
        FROM sakatliklar s JOIN takimlar t USING (takim_id) WHERE s.kaynak = 'espn' AND s.cekim_tarihi = ? ORDER BY t.kisaltma, s.durum DESC, s.isim""", (tarih,))
    veri_yok = _oku(conn, """
        SELECT t.kisaltma AS "Takım", '(kayıt gelmedi)' AS "Oyuncu", 'VERİ YOK' AS "Durum" FROM takimlar t
        WHERE NOT EXISTS (SELECT 1 FROM sakatliklar s WHERE s.takim_id = t.takim_id AND s.kaynak = 'espn' AND s.cekim_tarihi = ?) ORDER BY 1""", (tarih,))
    return pd.concat([veri_yok, df], ignore_index=True) if not df.empty else veri_yok


def savunma_tablosu(conn):
    df = _oku(conn, """
        SELECT t.kisaltma, s.pozisyon, s.duzeltilmis_oran, s.beklenene_gore_duzeltilmis FROM savunma_profili s JOIN takimlar t USING (takim_id)
        WHERE s.istatistik = 'sayi' AND s.hesap_tarihi = (SELECT MAX(hesap_tarihi) FROM savunma_profili)""")
    if df.empty:
        return df
    ham = df.pivot(index="kisaltma", columns="pozisyon", values="duzeltilmis_oran")[list(config.POZISYONLAR)].add_suffix(" ham")
    duz = df.pivot(index="kisaltma", columns="pozisyon", values="beklenene_gore_duzeltilmis")[list(config.POZISYONLAR)].add_suffix(" beklenene göre")
    return ham.join(duz).round(3).reset_index().rename(columns={"kisaltma": "Takım"})


def dunun_sonuclari(conn, tarih):
    """Bugünden önce puanlanmış en son günün canlı tahminleri."""
    return _oku(conn, """
        SELECT th.tarih AS "Tarih", d.kisaltma || ' @ ' || e.kisaltma AS "Maç", o.isim AS "Oyuncu", th.istatistik AS "İstatistik",
               ROUND(th.tahmin, 2) AS "Tahmin", th.gerceklesen AS "Gerçekleşen", ROUND(th.hata, 2) AS "Hata", ROUND(th.guven) AS "Güven"
        FROM tahminler th JOIN maclar m USING (mac_id) JOIN oyuncular o USING (oyuncu_id)
        JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id
        WHERE th.tur = 'canli' AND th.gerceklesen IS NOT NULL
          AND th.tarih = (SELECT MAX(tarih) FROM tahminler WHERE tur = 'canli' AND gerceklesen IS NOT NULL AND tarih < ?)
        ORDER BY m.baslama_utc, th.mac_id, o.isim, th.tahmin_id""", (tarih,))


def geri_test_ozeti(conn):
    """İstatistik başına hata özeti: canlı tahminler ve geriye dönük deneme alt alta."""
    parcalar = []
    for tur, ad in (("canli", "Canlı tahminler"), ("geri_test", "Geriye dönük deneme")):
        df = geri_test.tahminleri_oku(conn, tur)
        p = df[df["gerceklesen"].notna()] if not df.empty else df
        if p.empty:
            continue
        ozet = geri_test.istatistik_ozeti(p).reindex(TUM_ISTATISTIKLER).dropna(how="all").reset_index()
        ozet.insert(0, "Tür", ad)
        ozet.insert(1, "Dönem", f"{p['tarih'].min()} – {p['tarih'].max()}")
        ozet["istatistik"] = ozet["istatistik"].map(ISTATISTIK_ADLARI)
        ozet.columns = ["Tür", "Dönem", "İstatistik", "Tahmin sayısı", "Gerçekleşen ort.", "Ortalama mutlak hata", "Yanlılık", "Ölçüt hatası (sezon ort.)", "Ölçüte göre iyileşme %"]
        parcalar.append(ozet.round(3))
    return pd.concat(parcalar, ignore_index=True) if parcalar else pd.DataFrame()


def calisma_tablosu(conn, calisma_id):
    if not calisma_id:
        return pd.DataFrame()
    return _oku(conn, """
        SELECT zaman AS "Zaman (UTC)", adim AS "Adım", sonuc AS "Sonuç", ROUND(sure_sn, 1) AS "Süre (sn)", hata_iletisi AS "Hata iletisi"
        FROM calisma_kaydi WHERE calisma_id = ? ORDER BY kayit_id""", (calisma_id,))


def _bicimle(sayfa, sabit_sutun=0):
    """Başlık satırını kalın yapar, dondurur, süzgeç ekler ve sütun genişliklerini içeriğe göre ayarlar."""
    for hucre in sayfa[1]:
        hucre.font = Font(bold=True)
        hucre.fill = PatternFill("solid", fgColor="DDDDDD")
    sayfa.freeze_panes = sayfa.cell(row=2, column=sabit_sutun + 1)
    if sayfa.max_row > 1:
        sayfa.auto_filter.ref = sayfa.dimensions
    for i, sutun in enumerate(sayfa.columns, 1):
        genislik = max((len(str(h.value)) for h in sutun[:200] if h.value is not None), default=8)
        sayfa.column_dimensions[get_column_letter(i)].width = min(max(genislik + 2, 8), 70)


def excel_yaz(conn, tarih=None, calisma_id=None, klasor=None, tur="canli"):
    """Günün raporunu yazar; dosya yolunu döndürür. Aynı gün yeniden çalışırsa dosyanın üzerine yazılır."""
    tarih = tarih or veritabani.abd_bugun()
    klasor = klasor or config.RAPOR_KLASORU
    klasor.mkdir(exist_ok=True)
    yol = klasor / f"{tarih}.xlsx"
    carpan, ayrinti = etken_tablolari(conn, tarih, tur)
    sayfalar = [
        ("Tahminler", tahmin_tablosu(conn, tarih, tur), 3, "Bugün için tahmin yok."),
        ("Etken çarpanları", carpan, 4, "Etken kaydı yok."),
        ("Etken ayrıntısı", ayrinti, 5, "Etken kaydı yok."),
        ("Sakatlık", sakatlik_tablosu(conn, tarih), 2, "Sakatlık kaydı yok."),
        ("Sakatlık karşılaştırma", sakatlik_karsilastir.karsilastir(conn, tarih), 2, "Resmi sakatlık raporu kaydı yok; karşılaştırma yapılamadı."),
        ("Savunma", savunma_tablosu(conn), 1, "Savunma profili yok."),
        ("Dünün sonuçları", dunun_sonuclari(conn, tarih), 3, "Puanlanmış canlı tahmin henüz yok."),
        ("Geri test", geri_test_ozeti(conn), 3, "Puanlanmış tahmin yok."),
        ("Çalışma", calisma_tablosu(conn, calisma_id), 2, "Bu rapor elle üretildi; çalışma kaydı yok."),
    ]
    with pd.ExcelWriter(yol, engine="openpyxl") as yazici:
        for ad, tablo, sabit, bos_ileti in sayfalar:
            (tablo if not tablo.empty else pd.DataFrame({"Not": [bos_ileti]})).to_excel(yazici, sheet_name=ad, index=False)
            _bicimle(yazici.sheets[ad], sabit if not tablo.empty else 0)
    return yol


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    baglanti = veritabani.baglan()
    print("Rapor yazıldı:", excel_yaz(baglanti, sys.argv[1] if len(sys.argv) > 1 else None))
    baglanti.close()
