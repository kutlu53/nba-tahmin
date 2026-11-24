"""Kullanım oranı ve "onsuz" verisi (PLAN_EK etken 3).

Bugün "Out" olan her önemli takım arkadaşı için: oyuncunun, o arkadaş oynamadığı
maçlardaki 36 dk başına üretimi / oynadığı maçlardaki üretimi. Kimin oynamadığı
kutu skorlarından çıkar. Onsuz maç sayısı azken oran, genel dağıtım tahminine çekilir;
3 maçtan azsa yalnızca genel dağıtım kullanılır.

Genel dağıtım: eksik oyuncunun kullanım payı, sahada olduğu sürede kalanlara
orantılı dağılır; yerine giren oyuncu lig ortalaması kadar pay alır. Yalnızca
kullanım payıyla ölçeklenen istatistiklere (sayı, üçlük, top kaybı) uygulanır.

Önemli takım arkadaşı: kullanım oranı %20 ve üstü (ve maç başına en az 15 dk)
ya da maç başına 28 dakika ve üstü.

Çift sayma önlemi: arkadaş son maçlarda zaten oynamadıysa, oyuncunun temel oranı
onun yokluğunu kısmen içerir; çarpan o ölçüde küçültülür. Dakika artışı burada
değil, beklenen dakika tarafındadır.

Rapor ve onsuz_etkisi tablosu:  .venv\\Scripts\\python.exe -m etkenler.kullanim [YYYY-AA-GG]
"""
import sys

import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok

KULLANIM_ISTATISTIKLERI = ("sayi", "ucluk", "top_kaybi")   # kullanım payıyla doğrudan ölçeklenenler
ISTATISTIKLER = list(config.ISTATISTIKLER)


def _kullanim_ort(k):
    """Dakikayla ağırlıklı kullanım oranı; kullanım verisi yoksa None."""
    v = k[k["kullanim"].notna()]
    return float((v["kullanim"] * v["dakika"]).sum() / v["dakika"].sum()) if len(v) and v["dakika"].sum() > 0 else None


def onemli_oyuncular(baglam, takim_id):
    """Takımın önemli oyuncuları: {oyuncu_id: {'isim', 'kullanim', 'dakika_ort', 'mac'}}"""
    anahtar = ("onemli", takim_id)
    if anahtar not in baglam.onbellek:
        sonuc = {}
        for kimlik, o in baglam.oyuncular.items():
            k = baglam.oyuncu_kayitlari.get(kimlik) if o["takim_id"] == takim_id else None
            if k is None:
                continue
            k = k[k["takim_id"] == takim_id]
            if len(k) < config.KULLANIM_MIN_MAC:
                continue
            dakika, kullanim = float(k["dakika"].mean()), _kullanim_ort(k)
            if dakika >= config.KULLANIM_ONEMLI_DAKIKA or (
                    kullanim is not None and kullanim >= config.KULLANIM_ONEMLI_ORAN and dakika >= config.KULLANIM_ONEMLI_MIN_DAKIKA):
                sonuc[kimlik] = {"isim": o["isim"], "kullanim": kullanim, "dakika_ort": dakika, "mac": len(k)}
        baglam.onbellek[anahtar] = sonuc
    return baglam.onbellek[anahtar]


def onsuz(baglam, oyuncu_id, takim_id, arkadas_id):
    """Oyuncunun, arkadaşı oynarken ve oynamazken üretimi (aynı takımdaki ortak dönemde); veri yoksa None.

    Döndürür: {'onunla_mac', 'onsuz_mac', 'onunla_dakika', 'onsuz_dakika', 'oran': {ist: (onunla_36, onsuz_36)},
               'kullanim': (onunla, onsuz), 'temelde_onsuz': temel oranın ne kadarının zaten onsuz maçlardan geldiği (0–1)}
    """
    anahtar = ("onsuz", oyuncu_id, arkadas_id)
    if anahtar not in baglam.onbellek:
        baglam.onbellek[anahtar] = _onsuz_hesapla(baglam, oyuncu_id, takim_id, arkadas_id)
    return baglam.onbellek[anahtar]


def _onsuz_hesapla(baglam, oyuncu_id, takim_id, arkadas_id):
    tum, a = baglam.oyuncu_kayitlari.get(oyuncu_id), baglam.oyuncu_kayitlari.get(arkadas_id)
    if tum is None or a is None:
        return None
    a = a[a["takim_id"] == takim_id]
    k = tum[tum["takim_id"] == takim_id]
    if a.empty or k.empty:
        return None
    k = k[k["tarih"] >= a["tarih"].iloc[0]]          # arkadaşın bu takımdaki ilk maçından itibaren
    oynadi = k["mac_id"].isin(set(a["mac_id"]))
    onunla, ons = k[oynadi], k[~oynadi]

    def oran36(parca, ist):
        return float(36 * parca[ist].sum() / parca["dakika"].sum()) if len(parca) else None

    # Temel oran (sezon / son 10 / son 5 ağırlıklı) içinde onsuz maçların dakika payı.
    onsuz_maclar = set(ons["mac_id"])
    temelde = 0.0
    for ad, pencere in (("sezon", tum), ("son10", tum.tail(10)), ("son5", tum.tail(5))):
        temelde += config.TEMEL_AGIRLIK[ad] * pencere.loc[pencere["mac_id"].isin(onsuz_maclar), "dakika"].sum() / pencere["dakika"].sum()

    return {
        "onunla_mac": len(onunla), "onsuz_mac": len(ons),
        "onunla_dakika": float(onunla["dakika"].mean()) if len(onunla) else None,
        "onsuz_dakika": float(ons["dakika"].mean()) if len(ons) else None,
        "oran": {ist: (oran36(onunla, ist), oran36(ons, ist)) for ist in ISTATISTIKLER},
        "kullanim": (_kullanim_ort(onunla), _kullanim_ort(ons)),
        "temelde_onsuz": float(temelde),
        "onsuz_maclar": onsuz_maclar,
    }


def genel_dagitim(arkadas):
    """Eksik oyuncunun kullanım payı kalanlara orantılı dağılırsa, kalanların kullanımı kaç katına çıkar?

    Arkadaş sahadayken diğer dört oyuncu (100 − onun payı) kadar pay alır; o yokken yerine giren
    oyuncu lig ortalaması kadar pay aldığından diğerlerine (100 − lig ortalaması) kalır. Etki,
    arkadaşın sahada olduğu süreyle (dakika / 48) orantılıdır.
    """
    pay = min(arkadas["kullanim"] if arkadas["kullanim"] is not None else config.KULLANIM_LIG_ORT, 45.0)
    sure = min(1.0, arkadas["dakika_ort"] / 48.0)
    return 1.0 + sure * ((100.0 - config.KULLANIM_LIG_ORT) / (100.0 - pay) - 1.0)


def arkadas_carpani(baglam, oyuncu_id, takim_id, arkadas_id, arkadas, istatistik):
    """Tek bir eksik arkadaşın çarpanı. Döndürür: (çarpan, onsuz maç sayısı, ham oran ya da None, nötr değer)."""
    notr = genel_dagitim(arkadas) if istatistik in KULLANIM_ISTATISTIKLERI else 1.0
    veri = onsuz(baglam, oyuncu_id, takim_id, arkadas_id)
    carpan, n, ham, temelde = notr, 0, None, 0.0
    if veri is not None:
        temelde = veri["temelde_onsuz"]
        onunla36, onsuz36 = veri["oran"][istatistik]
        if min(veri["onunla_mac"], veri["onsuz_mac"]) >= config.ONSUZ_MIN_MAC and onunla36:
            n, ham = veri["onsuz_mac"], onsuz36 / onunla36
            carpan = kucuk_orneklem(n, ham, config.ONSUZ_K, notr)
    # Temel oran zaten kısmen onsuz maçlardan geliyorsa çarpanı o ölçüde küçült.
    return carpan / (1.0 + temelde * (carpan - 1.0)), n, ham, notr


def hesapla(oyuncu, mac, istatistik, baglam):
    eksik = baglam.takim_eksikleri(oyuncu.takim_id)
    if not eksik["veri_var"]:
        return veri_yok("takım için sakatlık verisi yok")
    onemli = onemli_oyuncular(baglam, oyuncu.takim_id)
    carpan, orneklem, parcalar = 1.0, 0, []
    for kimlik, isim, _ in eksik["out"]:
        if kimlik == oyuncu.oyuncu_id or kimlik not in onemli:
            continue
        c, n, ham, notr = arkadas_carpani(baglam, oyuncu.oyuncu_id, oyuncu.takim_id, kimlik, onemli[kimlik], istatistik)
        carpan *= c
        orneklem += n
        parcalar.append(f"{isim} yok: ×{c:.3f} (" + (f"onsuz/onunla {ham:.2f}, {n} maç" if ham is not None else f"genel dağıtım {notr:.3f}") + ")")
    if not parcalar:
        return EtkenSonucu(1.0, True, 0, "eksik önemli takım arkadaşı yok")
    return EtkenSonucu(carpan, True, orneklem, "; ".join(parcalar))


def tablo_satirlari(baglam, tarih):
    """onsuz_etkisi tablosu için satırlar: her takımın her önemli oyuncusu × takım arkadaşları × istatistik (+ kullanım)."""
    satirlar = []
    takimlar = {o["takim_id"] for o in baglam.oyuncular.values() if o["takim_id"] and o["aktif"]}
    for takim_id in sorted(takimlar):
        kadro = [kimlik for kimlik, o in baglam.oyuncular.items() if o["takim_id"] == takim_id and kimlik in baglam.oyuncu_kayitlari]
        for arkadas_id in onemli_oyuncular(baglam, takim_id):
            for oyuncu_id in kadro:
                veri = onsuz(baglam, oyuncu_id, takim_id, arkadas_id) if oyuncu_id != arkadas_id else None
                if veri is None or veri["onunla_mac"] + veri["onsuz_mac"] == 0:
                    continue
                ortak = {"oyuncu_id": oyuncu_id, "arkadas_id": arkadas_id, "hesap_tarihi": tarih,
                         "onunla_mac": veri["onunla_mac"], "onsuz_mac": veri["onsuz_mac"],
                         "onunla_dakika": veri["onunla_dakika"], "onsuz_dakika": veri["onsuz_dakika"]}
                for ist, (onunla36, onsuz36) in veri["oran"].items():
                    satirlar.append({**ortak, "istatistik": ist, "onunla_36": onunla36, "onsuz_36": onsuz36})
                satirlar.append({**ortak, "istatistik": "kullanim", "onunla_36": veri["kullanim"][0], "onsuz_36": veri["kullanim"][1]})
    return satirlar


def tabloyu_yaz(conn, baglam, tarih):
    """onsuz_etkisi tablosunu günün görüntüsüyle değiştirir; yazılan satır sayısını döndürür."""
    import veritabani

    satirlar = tablo_satirlari(baglam, tarih)
    try:
        conn.execute("DELETE FROM onsuz_etkisi")
        sayi = veritabani.yaz(conn, "onsuz_etkisi", satirlar)
        conn.commit()
        return sayi
    except Exception:
        conn.rollback()
        raise


def rapor_metni(conn, baglam, tarih, yildiz_sayisi=8):
    """Yıldız oyuncu eksikken takım arkadaşlarının kullanımı, sayısı ve dakikası nasıl değişmiş?"""
    takim_adi = {s["takim_id"]: s["kisaltma"] for s in conn.execute("SELECT takim_id, kisaltma FROM takimlar")}
    adaylar = []
    for takim_id in takim_adi:
        for kimlik, a in onemli_oyuncular(baglam, takim_id).items():
            ilk = baglam.oyuncu_kayitlari[kimlik].query("takim_id == @takim_id")["mac_id"].iloc[0]
            maclar = baglam.takim_maclari[takim_id]
            kacirilan = len(maclar) - maclar.index(ilk) - a["mac"]
            if kacirilan >= config.ONSUZ_MIN_MAC and a["mac"] >= config.ONSUZ_MIN_MAC and a["kullanim"] is not None:
                adaylar.append((a["kullanim"], takim_id, kimlik, a, kacirilan))
    adaylar.sort(reverse=True)

    s = [f"=== Kullanım ve \"onsuz\" raporu ({tarih} öncesi maçlar) ==="]
    onemli_sayisi = sum(len(onemli_oyuncular(baglam, t)) for t in takim_adi)
    s.append(f"Önemli oyuncu (kullanım ≥ %{config.KULLANIM_ONEMLI_ORAN:.0f} ya da ≥ {config.KULLANIM_ONEMLI_DAKIKA:.0f} dk/maç): {onemli_sayisi}; "
             f"bunlardan en az {config.ONSUZ_MIN_MAC} maç kaçırmış olan: {len(adaylar)}")
    s.append("Aşağıda, en yüksek kullanım oranlı ve en az 3 maç kaçırmış oyuncular eksikken takım arkadaşlarına ne olduğu görülüyor.")
    s.append("çarpan = sayı için etkenin uygulayacağı değer (küçük örneklem düzeltmesi sonrası; temel oran payı düşülmeden önce).")
    for kullanim, takim_id, kimlik, a, kacirilan in adaylar[:yildiz_sayisi]:
        s.append(f"\n{a['isim']} ({takim_adi[takim_id]}): kullanım %{kullanim:.1f}, {a['dakika_ort']:.1f} dk/maç; oynadığı {a['mac']} maç, kaçırdığı {kacirilan} maç; "
                 f"genel dağıtım tahmini ×{genel_dagitim(a):.3f}")
        s.append(f"  {'takım arkadaşı':<24}{'maç (onunla/onsuz)':>20}{'dakika':>16}{'kullanım %':>16}{'sayı / 36 dk':>16}{'çarpan':>9}")
        satirlar = []
        for oyuncu_id, o in baglam.oyuncular.items():
            if o["takim_id"] != takim_id or oyuncu_id == kimlik:
                continue
            veri = onsuz(baglam, oyuncu_id, takim_id, kimlik)
            if veri is None or min(veri["onunla_mac"], veri["onsuz_mac"]) < config.ONSUZ_MIN_MAC:
                continue
            _, n, ham, notr = arkadas_carpani(baglam, oyuncu_id, takim_id, kimlik, a, "sayi")
            satirlar.append((veri["onsuz_dakika"], o["isim"], veri, kucuk_orneklem(n, ham, config.ONSUZ_K, notr) if ham is not None else notr))
        for _, isim, veri, carpan in sorted(satirlar, key=lambda x: -x[0])[:6]:
            ku, sy = veri["kullanim"], veri["oran"]["sayi"]
            s.append(f"  {isim[:24]:<24}{f'{veri['onunla_mac']} / {veri['onsuz_mac']}':>20}{f'{veri['onunla_dakika']:.1f} → {veri['onsuz_dakika']:.1f}':>16}"
                     f"{(f'{ku[0]:.1f} → {ku[1]:.1f}' if None not in ku else '-'):>16}{f'{sy[0]:.1f} → {sy[1]:.1f}':>16}{carpan:>9.3f}")
    return "\n".join(s)


if __name__ == "__main__":
    import tahmin
    import veritabani

    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    veritabani.sema_kur(baglanti)
    bag = tahmin.Baglam(baglanti, gun)
    yazilan = tabloyu_yaz(baglanti, bag, gun)
    metin = rapor_metni(baglanti, bag, gun) + f"\n\nonsuz_etkisi tablosuna {yazilan} satır yazıldı."
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "kullanim_onsuz.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
