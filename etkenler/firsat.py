"""Fırsat verileri (PLAN_EK etken 6): asist ve ribaundu takip verisinden yeniden tahmin eder.

    asist   = 36 dk başına olası asist     × dönüşüm oranı × rakip ayarı
    ribaund = 36 dk başına ribaund fırsatı × dönüşüm oranı × rakip ayarı

- Fırsatlar (olası asist, ribaund fırsatı) hacimdir; sezon / son 10 / son 5 maç ağırlıklı ortalamasıyla tahmin edilir.
- Dönüşüm oranı (asist / olası asist, ribaund / ribaund fırsatı) şansa açıktır; oyuncunun kendi oranı,
  pozisyonunun lig ortalamasına çekilir: (gerçekleşen + k × lig oranı) / (fırsat + k).
- Rakip ayarı tempodan bağımsızdır (tempo ayrı etkendir):
  asistte rakibin izin verdiği şut yüzdesi / lig ortalaması (hafifçe: karekökü);
  ribaundda bu maçta beklenen kaçan şut oranı / takımın maçlarındaki olağan kaçan şut oranı.
- Takip verisi yoksa ya da oyuncunun kaydı yetersizse veri_var = False; PLAN'daki doğrudan ortalama kullanılır.

Etken yalnızca asist ve ribaundu etkiler; temel oranın yeniden tahminidir.

Rapor:  .venv\\Scripts\\python.exe -m etkenler.firsat [YYYY-AA-GG]
"""
import sys

import config
from etkenler import EtkenSonucu, agirlikli_oran_36, kucuk_orneklem, veri_yok

# istatistik: (fırsat sütunu, Türkçe ad)
TURLER = {"asist": ("olasi_asist", "olası asist"), "ribaund": ("ribaund_firsati", "ribaund fırsatı")}


def lig_donusumu(baglam):
    """O güne kadarki lig dönüşüm oranları: {(pozisyon, istatistik): oran}; pozisyon None = tüm lig."""
    if "firsat_lig" not in baglam.onbellek:
        sonuc = {}
        k = baglam.kayitlar
        if len(k):
            pozisyon = k["oyuncu_id"].map(lambda kimlik: (baglam.oyuncular.get(kimlik) or {}).get("pozisyon"))
            for ist, (firsat, _) in TURLER.items():
                v = k[k[firsat].notna()]
                if v[firsat].sum() > 0:
                    sonuc[(None, ist)] = v[ist].sum() / v[firsat].sum()
                for p, s in v.groupby(pozisyon[v.index])[[ist, firsat]].sum().iterrows():
                    if s[firsat] > 0:
                        sonuc[(p, ist)] = s[ist] / s[firsat]
        baglam.onbellek["firsat_lig"] = sonuc
    return baglam.onbellek["firsat_lig"]


def oyuncu_verisi(baglam, oyuncu, istatistik):
    """Oyuncunun fırsat hacmi ve dönüşüm oranı; takip verisi yetersizse None.

    Döndürür: {'hacim_36', 'firsat', 'gerceklesen', 'guncel', 'lig', 'donusum', 'mac'}
    """
    anahtar = ("firsat", oyuncu.oyuncu_id, istatistik)
    if anahtar not in baglam.onbellek:
        sutun = TURLER[istatistik][0]
        k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
        lig = lig_donusumu(baglam)
        lig_orani = lig.get((oyuncu.pozisyon, istatistik), lig.get((None, istatistik)))
        sonuc = None
        if k is not None and lig_orani is not None:
            t = k[k[sutun].notna()]
            if len(t) >= config.FIRSAT_MIN_MAC:
                firsat, gerceklesen = float(t[sutun].sum()), float(t[istatistik].sum())
                sonuc = {
                    "hacim_36": agirlikli_oran_36(t, sutun)[0], "firsat": firsat, "gerceklesen": gerceklesen,
                    "guncel": gerceklesen / firsat if firsat else None, "lig": lig_orani,
                    "donusum": (gerceklesen + config.FIRSAT_K[istatistik] * lig_orani) / (firsat + config.FIRSAT_K[istatistik]),
                    "mac": len(t),
                }
        baglam.onbellek[anahtar] = sonuc
    return baglam.onbellek[anahtar]


def takim_sut_oranlari(baglam, takim_id):
    """Takımın kendi şut yüzdesi ve izin verdiği şut yüzdesi, az maçta lig ortalamasına çekilmiş; veri yoksa None.

    Döndürür: (kendi yüzdesi, izin verilen yüzde, lig yüzdesi, maç sayısı).
    """
    anahtar = ("sut_orani", takim_id)
    if anahtar not in baglam.onbellek:
        satirlar = baglam.takim_sut.get(takim_id)
        tum = [s for liste in baglam.takim_sut.values() for s in liste]
        if not satirlar or not tum:
            baglam.onbellek[anahtar] = None
        else:
            lig = sum(s[0] for s in tum) / sum(s[1] for s in tum)
            n = len(satirlar)
            kendi = sum(s[0] for s in satirlar) / sum(s[1] for s in satirlar)
            izin = sum(s[2] for s in satirlar) / sum(s[3] for s in satirlar)
            k = config.FIRSAT_RAKIP_K
            baglam.onbellek[anahtar] = (kucuk_orneklem(n, kendi, k, notr=lig), kucuk_orneklem(n, izin, k, notr=lig), lig, n)
    return baglam.onbellek[anahtar]


def rakip_ayari(baglam, oyuncu, mac, istatistik):
    """Rakibe göre ayar çarpanı ve açıklaması; takım şut verisi yoksa (1.0, None)."""
    takim, rakip = takim_sut_oranlari(baglam, oyuncu.takim_id), takim_sut_oranlari(baglam, mac.rakip(oyuncu.takim_id))
    if takim is None or rakip is None:
        return 1.0, None
    lig = takim[2]
    if istatistik == "asist":
        # Rakip şutları ne kadar soktuyor? Asist, pasın şutla sonuçlanmasına bağlıdır.
        return (rakip[1] / lig) ** config.FIRSAT_RAKIP_USSU, f"rakibin izin verdiği şut %{100 * rakip[1]:.1f} (lig %{100 * lig:.1f})"
    # Ribaund: bu maçta beklenen kaçan şut oranı / takımın maçlarındaki olağan kaçan şut oranı.
    kacan = lambda yuzde: 1.0 - yuzde
    bizim_kacan = kacan(takim[0]) * kacan(rakip[1]) / kacan(lig)      # bizim şutlarımız, rakibin savunmasına karşı
    onlarin_kacan = kacan(rakip[0]) * kacan(takim[1]) / kacan(lig)    # rakibin şutları, bizim savunmamıza karşı
    olagan = (kacan(takim[0]) + kacan(takim[1])) / 2
    beklenen = (bizim_kacan + onlarin_kacan) / 2
    return beklenen / olagan, f"beklenen kaçan şut oranı %{100 * beklenen:.1f} (takımın maçlarında %{100 * olagan:.1f})"


def hesapla(oyuncu, mac, istatistik, baglam):
    if istatistik not in TURLER:
        return EtkenSonucu(1.0, True, 0, "bu istatistiği etkilemez")
    v = oyuncu_verisi(baglam, oyuncu, istatistik)
    if v is None:
        return veri_yok("takip verisi yok ya da yetersiz")
    temel, _ = agirlikli_oran_36(baglam.oyuncu_kayitlari[oyuncu.oyuncu_id], istatistik)
    if temel <= 0:
        return veri_yok("temel üretim sıfır; çarpanla düzeltilemez")
    ayar, ayar_aciklamasi = rakip_ayari(baglam, oyuncu, mac, istatistik)
    yeni = v["hacim_36"] * v["donusum"] * ayar
    aciklama = (f"36 dk başına {TURLER[istatistik][1]} {v['hacim_36']:.1f}; dönüşüm "
                + (f"%{100 * v['guncel']:.0f} → " if v["guncel"] is not None else "") + f"%{100 * v['donusum']:.0f} (lig %{100 * v['lig']:.0f}, {v['firsat']:.0f} fırsat)"
                + (f"; {ayar_aciklamasi}: ×{ayar:.3f}" if ayar_aciklamasi else ""))
    return EtkenSonucu(yeni / temel, True, round(v["firsat"]), aciklama)


def rapor_metni(conn, baglam, tarih):
    """Takip verisinin kapsamı, lig dönüşüm oranları, en çok düzeltilen oyuncular ve top dokunuşu izleme listesi."""
    import pandas as pd
    import tahmin

    s = [f"=== Fırsat verileri raporu ({tarih} öncesi maçlar) ==="]
    kapsam = conn.execute("""
        SELECT COUNT(*) AS satir, COUNT(t.olasi_asist) AS asist, COUNT(t.ribaund_firsati) AS ribaund, COUNT(t.top_dokunusu) AS dokunus,
               COUNT(DISTINCT om.mac_id) AS mac, COUNT(DISTINCT CASE WHEN t.oyuncu_id IS NOT NULL THEN om.mac_id END) AS takipli_mac
        FROM oyuncu_mac om JOIN maclar m USING (mac_id) LEFT JOIN takip_mac t ON t.oyuncu_id = om.oyuncu_id AND t.mac_id = om.mac_id
        WHERE om.dakika > 0 AND m.tarih < ?""", (tarih,)).fetchone()
    if not kapsam["satir"] or not kapsam["takipli_mac"]:
        return "\n".join(s + ["TAKİP VERİSİ ALINAMADI: takip_mac tablosu boş. Fırsat etkeni devre dışı (veri_var = False); asist ve ribaund doğrudan ortalamayla tahmin ediliyor."])
    s.append(f"Takip verisi: {kapsam['mac']} maçın {kapsam['takipli_mac']} tanesinde var; {kapsam['satir']} oyuncu-maç satırının "
             f"olası asist %{100 * kapsam['asist'] / kapsam['satir']:.1f}, ribaund fırsatı %{100 * kapsam['ribaund'] / kapsam['satir']:.1f}, "
             f"top dokunuşu %{100 * kapsam['dokunus'] / kapsam['satir']:.1f} oranında dolu")

    lig = lig_donusumu(baglam)
    s.append("\nLİG DÖNÜŞÜM ORANLARI (pozisyona göre)")
    s.append(f"  {'':<28}" + "".join(f"{p:>8}" for p in config.POZISYONLAR) + f"{'tümü':>8}")
    for ist, ad in (("asist", "asist / olası asist"), ("ribaund", "ribaund / ribaund fırsatı")):
        s.append(f"  {ad:<28}" + "".join(f"{f'%{100 * lig[(p, ist)]:.1f}' if (p, ist) in lig else '-':>8}" for p in config.POZISYONLAR)
                 + f"{f'%{100 * lig[(None, ist)]:.1f}':>8}")

    satirlar = []
    for mac in tahmin.gunun_maclari(conn, tarih):
        for o in tahmin.tahmin_edilecekler(baglam, mac):
            k = baglam.oyuncu_kayitlari.get(o.oyuncu_id)
            if k is None or len(k) < config.TAHMIN_MIN_MAC:
                continue
            dakika, _ = tahmin.beklenen_dakika(k)
            if dakika < config.TAHMIN_MIN_DAKIKA:
                continue
            satir = {"isim": o.isim, "dakika": dakika}
            for ist in TURLER:
                v, sonuc = oyuncu_verisi(baglam, o, ist), hesapla(o, mac, ist, baglam)
                temel = dakika * agirlikli_oran_36(k, ist)[0] / 36
                satir.update({f"{ist}_veri": sonuc.veri_var, f"{ist}_temel": temel, f"{ist}_yeni": temel * sonuc.carpan,
                              f"{ist}_guncel": v["guncel"] if v else None, f"{ist}_donusum": v["donusum"] if v else None, f"{ist}_firsat": v["firsat"] if v else None})
            t = k[k["top_dokunusu"].notna()]
            if len(t) >= 8 and t.tail(5)["dakika"].sum() > 0:
                satir["dokunus_sezon"] = 36 * t["top_dokunusu"].sum() / t["dakika"].sum()
                satir["dokunus_son5"] = 36 * t.tail(5)["top_dokunusu"].sum() / t.tail(5)["dakika"].sum()
                satir["sayi_sezon"] = 36 * t["sayi"].sum() / t["dakika"].sum()
                satir["sayi_son5"] = 36 * t.tail(5)["sayi"].sum() / t.tail(5)["dakika"].sum()
            satirlar.append(satir)
    if not satirlar:
        return "\n".join(s + ["Günün tahmin edilecek oyuncusu yok."])
    d = pd.DataFrame(satirlar)
    s.append(f"\nGÜNÜN OYUNCULARI ({len(d)}): takip verisiyle düzeltilen asist {int(d['asist_veri'].sum())}, ribaund {int(d['ribaund_veri'].sum())}")
    for ist, ad in (("asist", "ASİST"), ("ribaund", "RİBAUND")):
        v = d[d[f"{ist}_veri"] & (d[f"{ist}_firsat"] >= 30)].assign(fark=lambda x: x[f"{ist}_yeni"] - x[f"{ist}_temel"])
        s.append(f"  {ad}: toplam {v[f'{ist}_temel'].sum():.0f} → {v[f'{ist}_yeni'].sum():.0f}; en çok aşağı ve yukarı çekilenler")
        s.append(f"    {'oyuncu':<24}{'fırsat':>8}{'dönüşüm':>18}{'tahmin':>16}")
        for _, r in pd.concat([v.nsmallest(3, "fark"), v.nlargest(3, "fark")]).iterrows():
            s.append(f"    {r['isim'][:24]:<24}{r[f'{ist}_firsat']:>8.0f}{f'%{100 * r[f'{ist}_guncel']:.0f} → %{100 * r[f'{ist}_donusum']:.0f}':>18}"
                     f"{f'{r[f'{ist}_temel']:.1f} → {r[f'{ist}_yeni']:.1f}':>16}")

    if "dokunus_sezon" in d:
        v = d[d["dokunus_sezon"].notna()].assign(degisim=lambda x: x["dokunus_son5"] / x["dokunus_sezon"] - 1, sayi_degisim=lambda x: x["sayi_son5"] / x["sayi_sezon"] - 1)
        izleme = v[(v["degisim"] >= 0.15) & (v["sayi_degisim"] < 0.05)].nlargest(6, "degisim")
        s.append(f"\nTOP DOKUNUŞU İZLEME LİSTESİ: son 5 maçta 36 dk başına dokunuşu sezona göre %15+ artmış, sayısı henüz artmamış oyuncular ({len(izleme)})")
        for _, r in izleme.iterrows():
            s.append(f"    {r['isim'][:24]:<24} dokunuş {r['dokunus_sezon']:.0f} → {r['dokunus_son5']:.0f} (%{100 * r['degisim']:+.0f}); sayı / 36 dk {r['sayi_sezon']:.1f} → {r['sayi_son5']:.1f}")
    return "\n".join(s)


if __name__ == "__main__":
    import tahmin
    import veritabani

    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    veritabani.sema_kur(baglanti)
    metin = rapor_metni(baglanti, tahmin.Baglam(baglanti, gun), gun)
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "firsat.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
