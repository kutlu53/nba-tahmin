"""Pozisyona göre savunma profili (PLAN bölüm 5 ve PLAN_EK etken 1).

Her takım T, pozisyon P ve istatistik S için iki oran hesaplanır:

HAM (PLAN bölüm 5): T'ye karşı oynayan P pozisyonundaki oyuncuların 36 dakika başına
S üretimi / ligin P pozisyonu ortalaması. Kime karşı oynandığını hesaba katmaz.

BEKLENENE GÖRE (PLAN_EK etken 1, "rakibe göre düzeltilmiş"): aynı oyuncuların T'ye
karşı gerçekleşen üretimi / kendi sezon üretimlerinden beklenen üretim. Beklenen
üretim, oyuncunun o maç dışındaki maçlarındaki üretim hızı × o maçtaki dakikası ×
o maçın temposudur. Böylece oran, T'nin karşısına çıkan oyuncuların gücünden ve
maçın temposundan arındırılmış olur (tempo ayrı bir etkendir, iki kez sayılmaz).

İki oranda da 1,00 üstü, T'nin o pozisyona ortalamadan fazla verdiği anlamına gelir.

Çalıştırma:  .venv\\Scripts\\python.exe savunma.py [YYYY-AA-GG]
"""
import sys

import pandas as pd

import config
import veritabani

ISTATISTIKLER = list(config.ISTATISTIKLER)


def tum_kayitlar(conn, tarih):
    """Verilen tarihten ÖNCE oynanmış maçlardaki tüm oyuncu kayıtları (dakikası olanlar).

    takim_id sütunu savunan takımdır (oyuncunun o maçtaki rakibi); tempo maçın temposudur.
    """
    sutunlar = ["oyuncu_id", "takim_id", "pozisyon", "mac_id", "dakika", "tempo"] + ISTATISTIKLER
    satirlar = conn.execute(f"""
        SELECT om.oyuncu_id, om.rakip_id, o.pozisyon, om.mac_id, om.dakika, tm.tempo, {', '.join('om.' + s for s in ISTATISTIKLER)}
        FROM oyuncu_mac om
        JOIN oyuncular o USING (oyuncu_id)
        JOIN maclar m USING (mac_id)
        LEFT JOIN takim_mac tm ON tm.mac_id = om.mac_id AND tm.takim_id = om.takim_id
        WHERE m.tarih < ? AND om.dakika > 0""", (tarih,)).fetchall()
    df = pd.DataFrame([tuple(s) for s in satirlar], columns=sutunlar)
    df["tempo"] = df["tempo"].astype(float)
    return df


def kayitlari_oku(conn, tarih):
    """Savunma hesabına giren kayıtlar: pozisyonu bilinen ve yeterli dakika almış oyuncular."""
    df = tum_kayitlar(conn, tarih)
    return df[(df["dakika"] >= config.SAVUNMA_MIN_DAKIKA) & df["pozisyon"].notna()]


def beklenen_uretim(df):
    """Her kayıt için, oyuncunun o maç DIŞINDAKİ maçlarından beklenen üretimi ekler (bek_<istatistik> sütunları).

    Üretim hızı "tempoya göre ölçeklenmiş dakika" başına ölçülür: hızlı bir maçta aynı
    dakikada daha çok pozisyon oynanır. Oyuncunun başka maçı yoksa beklenen değer boş kalır.
    """
    ort_tempo = df["tempo"].mean()
    tempo_orani = (df["tempo"] / ort_tempo).fillna(1.0) if pd.notna(ort_tempo) else 1.0
    df = df.assign(maruziyet=df["dakika"] * tempo_orani)
    toplam = df.groupby("oyuncu_id")[ISTATISTIKLER + ["maruziyet"]].transform("sum")
    kalan = toplam["maruziyet"] - df["maruziyet"]
    for ist in ISTATISTIKLER:
        df[f"bek_{ist}"] = (df["maruziyet"] * (toplam[ist] - df[ist]) / kalan).where(kalan > 0)
    return df


def profil_hesapla(conn, tarih=None):
    """Savunma profilini hesaplar; savunma_profili tablosunun sütunlarıyla satır listesi döndürür.

    Yalnızca `tarih`ten önceki maçlar kullanılır (varsayılan: bugünün ABD tarihi), böylece
    geriye dönük denemede o günün ve sonrasının verisi hesaba sızmaz.

    Ham oran:
    - verilen_ort, lig_ort: 36 dakika başına; dakikalar toplanarak hesaplanır.
    - duzeltilmis_oran: (n × oran + k × 1,00) / (n + k); n takımın maç sayısı, k = config.KUCUK_ORNEKLEM_K.
    - sira: düzeltilmiş orana göre; 1 = o pozisyona o istatistiği en az veren takım.

    Beklenene göre oran:
    - beklenene_gore_oran: gerçekleşen toplam / beklenen toplam.
    - beklenene_gore_duzeltilmis: (dk × oran + k × 1,00) / (dk + k); dk hesaba giren oyuncu-dakikası,
      k = config.ESLESME_K_DAKIKA.
    - beklenene_gore_sira: 1 = en az veren.
    """
    tarih = tarih or veritabani.abd_bugun()
    tum = tum_kayitlar(conn, tarih)
    if tum.empty:
        return []
    tum = beklenen_uretim(tum)
    df = tum[(tum["dakika"] >= config.SAVUNMA_MIN_DAKIKA) & tum["pozisyon"].notna()]
    if df.empty:
        return []
    anahtar = ["takim_id", "pozisyon"]

    takim = df.groupby(anahtar)
    toplam = takim[ISTATISTIKLER + ["dakika"]].sum()
    mac_sayisi = takim["mac_id"].nunique()
    lig = df.groupby("pozisyon")[ISTATISTIKLER + ["dakika"]].sum()
    lig_dakika = lig["dakika"].reindex(toplam.index, level="pozisyon")

    # Beklenen üretimi olan kayıtlar (oyuncunun başka maçı da var).
    b = df[df[f"bek_{ISTATISTIKLER[0]}"].notna()]
    b_toplam = b.groupby(anahtar)[ISTATISTIKLER + [f"bek_{i}" for i in ISTATISTIKLER] + ["dakika"]].sum().reindex(toplam.index)

    k_mac, k_dakika = config.KUCUK_ORNEKLEM_K, config.ESLESME_K_DAKIKA
    satirlar = []
    for ist in ISTATISTIKLER:
        verilen = config.NORMALLESTIRME_DAKIKA * toplam[ist] / toplam["dakika"]
        lig_ort = config.NORMALLESTIRME_DAKIKA * lig[ist].reindex(toplam.index, level="pozisyon") / lig_dakika
        oran = (verilen / lig_ort).where(lig_ort > 0)
        duzeltilmis = (mac_sayisi * oran + k_mac * 1.0) / (mac_sayisi + k_mac)
        sira = duzeltilmis.groupby(level="pozisyon").rank(method="first")

        beklenen = b_toplam[f"bek_{ist}"]
        b_oran = (b_toplam[ist] / beklenen).where(beklenen > 0)
        b_dakika = b_toplam["dakika"].fillna(0.0)
        b_duzeltilmis = (b_dakika * b_oran + k_dakika * 1.0) / (b_dakika + k_dakika)
        b_sira = b_duzeltilmis.groupby(level="pozisyon").rank(method="first")

        for (takim_id, pozisyon), o in oran.items():
            i = (takim_id, pozisyon)
            bos, b_bos = pd.isna(o), pd.isna(b_oran[i])
            satirlar.append({
                "takim_id": int(takim_id),
                "pozisyon": pozisyon,
                "istatistik": ist,
                "hesap_tarihi": tarih,
                "verilen_ort": float(verilen[i]),
                "lig_ort": float(lig_ort[i]),
                "oran": None if bos else float(o),
                "duzeltilmis_oran": None if bos else float(duzeltilmis[i]),
                "sira": None if bos else int(sira[i]),
                "mac_sayisi": int(mac_sayisi[i]),
                "beklenene_gore_oran": None if b_bos else float(b_oran[i]),
                "beklenene_gore_duzeltilmis": None if b_bos else float(b_duzeltilmis[i]),
                "beklenene_gore_sira": None if b_bos else int(b_sira[i]),
                "oyuncu_dakika": float(b_dakika[i]),
            })
    return satirlar


def profili_yaz(conn, tarih=None):
    """Profili hesaplar ve savunma_profili tablosuna yazar; yazılan satır sayısını döndürür."""
    return veritabani.yaz(conn, "savunma_profili", profil_hesapla(conn, tarih))


def rapor_metni(conn, tarih):
    """Sayı için ham ve beklenene göre oranlar yan yana; en çok yer değiştiren takım-pozisyonlar ve nedeni."""
    df = pd.DataFrame([dict(s) for s in conn.execute("""
        SELECT t.kisaltma, s.* FROM savunma_profili s JOIN takimlar t USING (takim_id) WHERE s.hesap_tarihi = ?""", (tarih,))])
    if df.empty:
        return f"{tarih} için savunma profili yok."
    pozisyonlar = list(config.POZISYONLAR)
    s = [f"=== Savunma profili ({tarih} öncesi maçlar) ==="]
    s.append(f"Satır: {len(df)} = {df['takim_id'].nunique()} takım × {df['pozisyon'].nunique()} pozisyon × {df['istatistik'].nunique()} istatistik; "
             f"boş ham oran: {int(df['oran'].isna().sum())}, boş beklenene göre oran: {int(df['beklenene_gore_oran'].isna().sum())}; "
             f"takım başına maç: {df['mac_sayisi'].min()}–{df['mac_sayisi'].max()}")
    s.append("HAM oran = takımın o pozisyona verdiği / lig ortalaması (36 dk başına).")
    s.append("BEKLENENE GÖRE oran = gerçekleşen / o oyuncuların kendi sezon üretiminden beklenen (rakip gücünden ve tempodan arındırılmış).")
    s.append(f"İkisi de küçük örneklem için 1,00'e çekilmiştir (ham: k = {config.KUCUK_ORNEKLEM_K} maç; beklenene göre: k = {config.ESLESME_K_DAKIKA} oyuncu-dakikası).")
    s.append("1,00 üstü: ortalamadan fazla veriyor. Sıra 1 = en az veren.\n")

    sayi = df[df["istatistik"] == "sayi"]
    tablo = {ad: sayi.pivot(index="kisaltma", columns="pozisyon", values=ad)[pozisyonlar]
             for ad in ("duzeltilmis_oran", "sira", "beklenene_gore_duzeltilmis", "beklenene_gore_sira")}
    s.append("SAYI: her pozisyonda  ham oran (sıra) → beklenene göre oran (sıra);  takımlar beklenene göre ortalamaya göre sıralı")
    s.append("       " + "".join(f"{p:>26}" for p in pozisyonlar))
    for takim in tablo["beklenene_gore_duzeltilmis"].mean(axis=1).sort_values().index:
        s.append(f"  {takim:<5}" + "".join(
            f"   {tablo['duzeltilmis_oran'].loc[takim, p]:.2f} ({int(tablo['sira'].loc[takim, p]):>2}) → "
            f"{tablo['beklenene_gore_duzeltilmis'].loc[takim, p]:.2f} ({int(tablo['beklenene_gore_sira'].loc[takim, p]):>2})" for p in pozisyonlar))

    # Ham / beklenene göre = karşılaşılan oyuncuların beklenen üretimi / lig ortalaması: farkın açıklaması budur.
    sayi = sayi.assign(sira_farki=sayi["beklenene_gore_sira"] - sayi["sira"], fikstur=sayi["oran"] / sayi["beklenene_gore_oran"])
    tempo = pd.Series({r["kisaltma"]: r["oran"] for r in conn.execute("""
        SELECT t.kisaltma, AVG(tm.tempo) / (SELECT AVG(tm2.tempo) FROM takim_mac tm2 JOIN maclar m2 USING (mac_id) WHERE m2.tarih < :t) AS oran
        FROM takim_mac tm JOIN maclar m USING (mac_id) JOIN takimlar t USING (takim_id) WHERE m.tarih < :t GROUP BY t.takim_id""", {"t": tarih})})
    s.append(f"\nSıra korelasyonu (sayı, ham ile beklenene göre): {sayi['sira'].corr(sayi['beklenene_gore_sira']):.2f}")
    s.append("En çok yer değiştiren takım-pozisyonlar ve nedeni")
    s.append("  (karşılaşılan = o takıma karşı oynayan oyuncuların kendi üretimlerinden beklenen sayı / lig ortalaması; tempo = takımın maç temposu / lig)")
    for _, r in sayi.reindex(sayi["sira_farki"].abs().sort_values(ascending=False).index).head(10).iterrows():
        yon = "daha iyi savunuyor görünüyor" if r["sira_farki"] < 0 else "daha kötü savunuyor görünüyor"
        s.append(f"  {r['kisaltma']:<4}{r['pozisyon']:<3} ham {r['oran']:.2f} (sıra {int(r['sira']):>2}) → beklenene göre {r['beklenene_gore_oran']:.2f} "
                 f"(sıra {int(r['beklenene_gore_sira']):>2}): karşılaşılan {r['fikstur']:.2f}, tempo {tempo.get(r['kisaltma'], float('nan')):.2f}; düzeltince {yon}")

    s.append("\nHer istatistikte en az ve en çok veren takım-pozisyon (beklenene göre, düzeltilmiş; parantez içinde ham düzeltilmiş oran):")
    for ist in ISTATISTIKLER:
        d = df[df["istatistik"] == ist].sort_values("beklenene_gore_duzeltilmis")
        az, cok = d.iloc[0], d.iloc[-1]
        s.append(f"  {ist:<10} en az: {az['kisaltma']} {az['pozisyon']:<2} {az['beklenene_gore_duzeltilmis']:.2f} ({az['duzeltilmis_oran']:.2f})"
                 f"   en çok: {cok['kisaltma']} {cok['pozisyon']:<2} {cok['beklenene_gore_duzeltilmis']:.2f} ({cok['duzeltilmis_oran']:.2f})"
                 f"   sıra korelasyonu {d['sira'].corr(d['beklenene_gore_sira']):.2f}")
    return "\n".join(s)


def main(argv):
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    tarih = argv[0] if argv else veritabani.abd_bugun()
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        profili_yaz(conn, tarih)
        metin = rapor_metni(conn, tarih)
        config.RAPOR_KLASORU.mkdir(exist_ok=True)
        (config.RAPOR_KLASORU / "savunma_profili.txt").write_text(metin + "\n", encoding="utf-8")
        print(metin)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
