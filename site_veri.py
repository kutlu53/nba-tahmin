"""Paylaşılan web sayfası (Claude Artifact) için veriyi hazırlar: site_veri/ klasörüne JSON dosyaları yazar.

Sayfanın veritabanına bu dosyaları Claude aktarır (sayfa claude.ai üzerinde durur; bilgisayardaki
betikler oraya doğrudan yazamaz). Dosyalar:
    ozet.json               -> site/ozet           günün tarihi, güncelleme zamanı, modelin ölçüte göre durumu
    gun_YYYY-AA-GG.json     -> gunler/YYYY-AA-GG   günün üst / alt seçimleri ve bütün tahminler (maç maç)
    gecmis_YYYY-AA-GG.json  -> gecmis/YYYY-AA-GG   o günün üst / alt seçimleri, gerçekleşen değerler ve hata özeti
    yazilacaklar.json       aktarılacak belgelerin listesi

"Günün üst / alt seçimleri": modelin en emin olduğu üst ve alt tarafları (aşağıdaki UA_ ayarları). Canlı bir günün
geçmiş belgesinde, o gün sayfada gösterilen seçimlerin aynısı sonuçlarıyla yer alır (oynamayan oyuncu "oynamadı" görünür).

Çalıştırma:  .venv\\Scripts\\python.exe site_veri.py
"""
import json
import math
import sys

import pandas as pd

import config
import ust_alt
import veritabani

KLASOR = config.KOK / "site_veri"
OZET_ISTATISTIKLERI = ("sayi", "ribaund", "asist", "ucluk")       # hata özeti verilen istatistikler
GECMIS_GUN = 40

# Günün üst / alt seçimleri. Elimizde bahis çizgisi yoktur; çizgi olarak oyuncunun sezon maç ortalaması (buçuklu) alınır.
UA_ISTATISTIKLERI = {"sayi": 8.5, "ribaund": 3.5, "asist": 2.5, "ucluk": 1.5, "sayi+ribaund+asist": 15.5}   # istatistik: en küçük çizgi
UA_MIN_DAKIKA, UA_MIN_GUVEN, UA_MIN_OLASILIK, UA_ADET = 20, 60, 0.58, 6          # taraf başına en çok UA_ADET seçim, oyuncu başına bir


UA_BANTLARI = (58, 65, 75, 101)      # güven yüzdesi bantları: 58–64, 65–74, 75 ve üstü


def ua_bandi(olasilik):
    return max(i for i, alt in enumerate(UA_BANTLARI[:-1]) if olasilik >= alt)


def ust_alt_secimleri(df, puanli=False, yalniz_oynayanlar=False):
    """Modelin en emin olduğu üst ve alt seçimleri.

    puanli=True ise her seçime sonuç eklenir: 'gercek' (gerçekleşen değer), 'tuttu' (1 / 0) ve 'bitti' (maçın sonucu
    işlendi mi). Oyuncu oynamadıysa 'gercek' ve 'tuttu' None kalır. yalniz_oynayanlar=True seçimi yalnızca gerçekleşen
    değeri olan oyuncular arasından yapar: geriye dönük günlerde o gün kimin oynamayacağı (sakatlık) bilgisi
    tahminde yoktur, canlı günde ise vardır; bu süzme ikisini benzer kılar.
    """
    if yalniz_oynayanlar and not df.empty:
        df = df[df["gerceklesen"].notna()]
    if df.empty:
        return []
    t, u, g, so, gr = (df.pivot(index="oyuncu_id", columns="istatistik", values=k) for k in ("tahmin", "ust", "guven", "sezon_ort", "gerceklesen"))
    bilgi = df[df["istatistik"] == "sayi"].set_index("oyuncu_id")
    biten_maclar = set(df.loc[df["gerceklesen"].notna(), "mac_id"])
    adaylar = []
    for kimlik in bilgi.index:
        b = bilgi.loc[kimlik]
        if pd.isna(b["dakika"]) or b["dakika"] < UA_MIN_DAKIKA:
            continue
        for ist, en_kucuk in UA_ISTATISTIKLERI.items():
            sezon = sum(so.loc[kimlik, p] for p in config.BIRLESIK.get(ist, (ist,)))
            if pd.isna(sezon) or pd.isna(u.loc[kimlik, ist]) or g.loc[kimlik, ist] < UA_MIN_GUVEN:
                continue
            cizgi = math.floor(sezon) + 0.5
            if cizgi < en_kucuk:
                continue
            tahmin = float(t.loc[kimlik, ist])
            p = ust_alt.ust_olasiligi(tahmin, (float(u.loc[kimlik, ist]) - tahmin) / config.ARALIK_Z, cizgi)
            taraf, olasilik = ("ust", p) if p >= 0.5 else ("alt", 1 - p)
            kayit = {"oyuncu": b["isim"], "takim": b["takim"], "mac": b["mac"], "ist": ist, "cizgi": cizgi, "taraf": taraf,
                     "olasilik": round(100 * olasilik), "tahmin": round(tahmin, 1), "guven": round(float(g.loc[kimlik, ist]))}
            if puanli:
                gercek = gr.loc[kimlik, ist]
                oynadi = not pd.isna(gercek)
                kayit.update({"gercek": int(gercek) if oynadi else None, "bitti": b["mac_id"] in biten_maclar,
                              "tuttu": int((float(gercek) > cizgi) == (taraf == "ust")) if oynadi else None})
            adaylar.append((olasilik, kimlik, kayit))
    secilen = []
    for taraf in ("ust", "alt"):
        gorulen = set()
        for olasilik, kimlik, kayit in sorted((a for a in adaylar if a[2]["taraf"] == taraf and a[0] >= UA_MIN_OLASILIK), key=lambda a: -a[0]):
            if kimlik not in gorulen:
                gorulen.add(kimlik)
                secilen.append(kayit)
                if len(gorulen) == UA_ADET:
                    break
    return secilen


def _tahminler(conn, tarih, tur):
    return pd.DataFrame([dict(s) for s in conn.execute("""
        SELECT th.oyuncu_id, th.mac_id, th.istatistik, th.tahmin, th.alt, th.ust, th.guven, th.gerceklesen, th.calistirma,
               json_extract(th.girdiler, '$.duzeltilmis_dakika') AS dakika, json_extract(th.girdiler, '$.sezon_ort') AS sezon_ort,
               o.isim, o.pozisyon, tk.kisaltma AS takim, d.kisaltma || ' @ ' || e.kisaltma AS mac, m.baslama_utc
        FROM tahminler th JOIN oyuncular o USING (oyuncu_id) JOIN maclar m USING (mac_id)
        JOIN takimlar e ON e.takim_id = m.ev_takim_id JOIN takimlar d ON d.takim_id = m.dep_takim_id
        LEFT JOIN takimlar tk ON tk.takim_id = o.takim_id
        WHERE th.tarih = ? AND th.tur = ?""", (tarih, tur))])


def gun_belgesi(conn, tarih):
    df = _tahminler(conn, tarih, "canli")
    if df.empty:
        return None
    ilk_bes = {(s["mac_id"], s["oyuncu_id"]): s["durum"] for s in conn.execute(
        "SELECT mac_id, oyuncu_id, durum FROM ilk_bes_beklenti WHERE pozisyon IS NOT NULL AND kadro_durumu = 'Active'")}
    durum = {s["oyuncu_id"]: s["durum"] for s in conn.execute("SELECT oyuncu_id, durum FROM sakatliklar WHERE cekim_tarihi = ? AND oyuncu_id IS NOT NULL ORDER BY kaynak", (tarih,))}
    maclar = []
    for (mac_id, mac, basla), g in df.groupby(["mac_id", "mac", "baslama_utc"], sort=False):
        t = g.pivot(index="oyuncu_id", columns="istatistik", values="tahmin")
        u = g.pivot(index="oyuncu_id", columns="istatistik", values="ust")
        sapma = lambda kimlik, k: round(float((u.loc[kimlik, k] - t.loc[kimlik, k]) / config.ARALIK_Z), 2)     # üst / alt hesabı için
        bilgi = g[g["istatistik"] == "sayi"].set_index("oyuncu_id")
        oyuncular = []
        for kimlik in bilgi.sort_values(["takim", "dakika"], ascending=[True, False]).index:
            b = bilgi.loc[kimlik]
            oyuncular.append({
                "isim": b["isim"], "takim": b["takim"], "poz": b["pozisyon"] or "", "dk": round(b["dakika"], 1), "guven": round(b["guven"]),
                **{k: round(float(t.loc[kimlik, k]), 1) for k in config.ISTATISTIKLER},
                "sp": {k: sapma(kimlik, k) for k in config.ISTATISTIKLER},                                   # standart sapmalar
                "b": {k: [round(float(t.loc[kimlik, k]), 1), sapma(kimlik, k)] for k in config.BIRLESIK},    # birleşik değerler: [tahmin, sapma]
                "not": " · ".join(x for x in (("ilk beş" + (" (kesin)" if ilk_bes[(mac_id, kimlik)] == "Confirmed" else "")) if (mac_id, kimlik) in ilk_bes else "",
                                              durum.get(kimlik, "")) if x)})
        maclar.append({"mac_id": mac_id, "mac": mac, "baslama_utc": basla, "tur": "kesin" if (g["calistirma"] == "mac_oncesi").all() else "ön",
                       "oyuncular": oyuncular})
    maclar.sort(key=lambda m: (m["baslama_utc"] or "", m["mac_id"]))
    return {"tarih": tarih, "guncelleme": veritabani.simdi_utc(), "oyuncu_sayisi": int(df["oyuncu_id"].nunique()),
            "ust_alt": ust_alt_secimleri(df), "maclar": maclar}


def gecmis_ust_alt(conn, tarih, tur):
    """O günün üst / alt seçimleri sonuçlarıyla. Canlı günde sayfada gösterilen seçimlerin aynısıdır (bütün tahminler arasından)."""
    return ust_alt_secimleri(_tahminler(conn, tarih, tur), puanli=True, yalniz_oynayanlar=(tur != "canli"))


def gecmis_belgesi(conn, tarih, tur, ua=None):
    df = _tahminler(conn, tarih, tur)
    p = df[df["gerceklesen"].notna()] if not df.empty else df
    if p.empty:
        return None
    hata = {}
    for ist in OZET_ISTATISTIKLERI:
        x = p[p["istatistik"] == ist]
        hata[ist] = [round(float((x["tahmin"] - x["gerceklesen"]).abs().mean()), 2), round(float((x["sezon_ort"] - x["gerceklesen"]).abs().mean()), 2)]
    ua = gecmis_ust_alt(conn, tarih, tur) if ua is None else ua
    puanli = [x for x in ua if x["tuttu"] is not None]
    return {"tarih": tarih, "tur": tur, "oyuncu_sayisi": int(p["oyuncu_id"].nunique()), "mac_sayisi": int(p["mac_id"].nunique()), "hata": hata,
            "ust_alt": ua, "ua_puanli": len(puanli), "ua_tutan": sum(x["tuttu"] for x in puanli)}


def hazirla(conn):
    """Dosyaları yazar; aktarılacak belgelerin listesini döndürür: [{'collection', 'doc_id', 'dosya'}, ...]"""
    KLASOR.mkdir(exist_ok=True)
    yazilacak = []

    def yaz(ad, collection, doc_id, belge):
        yol = KLASOR / ad
        yol.write_text(json.dumps(belge, ensure_ascii=False), encoding="utf-8")
        yazilacak.append({"collection": collection, "doc_id": doc_id, "dosya": str(yol)})

    bugun = conn.execute("SELECT MAX(tarih) FROM tahminler WHERE tur = 'canli'").fetchone()[0]

    gunler = {}
    for tur in ("geri_test", "canli"):           # canlı tahmini olan günde canlı olan kullanılır
        for s in conn.execute("SELECT DISTINCT tarih FROM tahminler WHERE tur = ? AND gerceklesen IS NOT NULL", (tur,)):
            gunler[s[0]] = tur
    ua_gecmis = {"ust": [0, 0], "alt": [0, 0], "gun": 0}          # taraf: [sonuçlanan seçim sayısı, tutan]
    ua_bant = {}                                                   # (taraf, güven bandı): [sonuçlanan seçim sayısı, tutan]
    for tarih in sorted(gunler)[-GECMIS_GUN:]:
        ua = gecmis_ust_alt(conn, tarih, gunler[tarih])
        puanli = [x for x in ua if x["tuttu"] is not None]         # oynamayan oyuncunun seçimi sayılmaz
        ua_gecmis["gun"] += bool(puanli)
        for x in puanli:
            ua_gecmis[x["taraf"]][0] += 1
            ua_gecmis[x["taraf"]][1] += x["tuttu"]
            b = ua_bant.setdefault((x["taraf"], ua_bandi(x["olasilik"])), [0, 0])
            b[0] += 1
            b[1] += x["tuttu"]
        belge = gecmis_belgesi(conn, tarih, gunler[tarih], ua)
        if belge:
            yaz(f"gecmis_{tarih}.json", "gecmis", tarih, belge)

    # Bugünün her üst / alt seçimine, geçmişte aynı tarafta ve aynı güven bandındaki seçimlerin tutma oranını ekle.
    gun = gun_belgesi(conn, bugun) if bugun else None
    if gun:
        for x in gun["ust_alt"]:
            n, tutan = ua_bant.get((x["taraf"], ua_bandi(x["olasilik"])), (0, 0))
            x["gecmis_n"], x["gecmis_oran"] = n, (round(100 * tutan / n) if n >= 15 else None)
        yaz(f"gun_{bugun}.json", "gunler", bugun, gun)
    ua_gecmis["bantlar"] = [{"taraf": t, "alt": UA_BANTLARI[b], "ust": UA_BANTLARI[b + 1] - 1, "secim": n, "tutan": k} for (t, b), (n, k) in sorted(ua_bant.items())]

    model = {}
    for ist in OZET_ISTATISTIKLERI:
        r = conn.execute("""
            SELECT AVG(ABS(hata)) AS m, AVG(ABS(json_extract(girdiler, '$.sezon_ort') - gerceklesen)) AS o, COUNT(*) AS n
            FROM tahminler WHERE tur = 'geri_test' AND istatistik = ? AND gerceklesen IS NOT NULL""", (ist,)).fetchone()
        if r["n"]:
            model[ist] = {"hata": round(r["m"], 2), "olcut": round(r["o"], 2), "iyilesme": round(100 * (1 - r["m"] / r["o"]), 1), "n": r["n"]}
    yaz("ozet.json", "site", "ozet", {
        "bugun": bugun, "guncelleme": veritabani.simdi_utc(), "model": model,
        "gecmis": {"gun": len(gunler)},
        "ust_alt_gecmis": ua_gecmis,
        "acik_etkenler": [ad for ad, a in config.ETKENLER.items() if a["acik"]]})
    (KLASOR / "yazilacaklar.json").write_text(json.dumps(yazilacak, ensure_ascii=False, indent=1), encoding="utf-8")
    return yazilacak


if __name__ == "__main__":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    baglanti = veritabani.baglan()
    liste = hazirla(baglanti)
    baglanti.close()
    print(f"{len(liste)} belge hazırlandı: {KLASOR}")
