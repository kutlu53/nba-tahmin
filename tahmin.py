"""Tahmin motoru ve güven puanı (PLAN bölüm 6–7, PLAN_EK bölüm 2).

    tahmin = beklenen dakika × (36 dk başına temel oran / 36) × etken zincirinin çarpanı

Çalıştırma:  .venv\\Scripts\\python.exe tahmin.py [YYYY-AA-GG]
"""
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd

import config
import etkenler
import savunma
import veritabani
from etkenler import Mac, Oyuncu, fark_riski

log = logging.getLogger("tahmin")

ISTATISTIKLER = list(config.ISTATISTIKLER)
SUT_SUTUNLARI = ["saha_ici_isabet", "saha_ici_deneme", "ucluk_deneme", "serbest_isabet", "serbest_deneme"]
EK_SUTUNLAR = SUT_SUTUNLARI + ["kullanim", "faul"]
TAKIP_SUTUNLARI = ["olasi_asist", "ribaund_firsati", "top_dokunusu"]


class Baglam:
    """Bir tarih itibarıyla tahmin için gereken veri. Yalnızca `tarih`ten ÖNCEKİ maçları içerir.

    Etkenler veriye buradan ulaşır; böylece geriye dönük denemede o günün ve
    sonrasının sonuçları hiçbir hesaba giremez. Fikstür (kim, ne zaman oynuyor)
    önceden bilinen bilgi olduğu için tamamı yüklenir.

    gecmis=True (geriye dönük deneme): oyuncunun takımı, bugünkü kadro yerine o
    tarihten önceki son maçında oynadığı takım sayılır.
    """

    def __init__(self, conn, tarih, gecmis=False):
        self.tarih = tarih

        self.takim_tarihleri = defaultdict(set)   # takım -> maç günleri (oynanmış ve oynanacak)
        for s in conn.execute("SELECT tarih, ev_takim_id, dep_takim_id FROM maclar WHERE durum <> 'ertelendi'"):
            self.takim_tarihleri[s["ev_takim_id"]].add(s["tarih"])
            self.takim_tarihleri[s["dep_takim_id"]].add(s["tarih"])

        sutunlar = ["oyuncu_id", "mac_id", "tarih", "takim_id", "rakip_id", "ev_mi", "ilk_bes", "dakika"] + ISTATISTIKLER + EK_SUTUNLAR + TAKIP_SUTUNLARI
        satirlar = conn.execute(f"""
            SELECT om.oyuncu_id, om.mac_id, m.tarih, om.takim_id, om.rakip_id, om.ev_mi, om.ilk_bes, om.dakika,
                   {', '.join('om.' + s for s in ISTATISTIKLER + EK_SUTUNLAR)}, {', '.join('tk.' + s for s in TAKIP_SUTUNLARI)}
            FROM oyuncu_mac om JOIN maclar m USING (mac_id)
            LEFT JOIN takip_mac tk ON tk.oyuncu_id = om.oyuncu_id AND tk.mac_id = om.mac_id
            WHERE m.tarih < ? AND om.dakika > 0
            ORDER BY m.tarih, om.mac_id""", (tarih,)).fetchall()
        k = pd.DataFrame([tuple(s) for s in satirlar], columns=sutunlar)
        dun = (pd.to_datetime(k["tarih"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
        k["arka_arkaya"] = [d in self.takim_tarihleri[t] for d, t in zip(dun, k["takim_id"])]
        k[SUT_SUTUNLARI] = k[SUT_SUTUNLARI].fillna(0)
        k["kullanim"] = k["kullanim"].astype(float)
        k[TAKIP_SUTUNLARI] = k[TAKIP_SUTUNLARI].astype(float)
        k["iki_isabet"] = k["saha_ici_isabet"] - k["ucluk"]
        k["iki_deneme"] = k["saha_ici_deneme"] - k["ucluk_deneme"]
        self.kayitlar = k
        self.oyuncu_kayitlari = {kimlik: g for kimlik, g in k.groupby("oyuncu_id", sort=False)}
        self.dakika = dict(zip(zip(k["oyuncu_id"], k["mac_id"]), k["dakika"]))

        self.takim_maclari = defaultdict(list)    # takım -> oynanmış maç kimlikleri, eskiden yeniye
        for s in conn.execute("SELECT mac_id, ev_takim_id, dep_takim_id FROM maclar WHERE durum = 'oynandi' AND tarih < ? ORDER BY tarih, mac_id", (tarih,)):
            self.takim_maclari[s["ev_takim_id"]].append(s["mac_id"])
            self.takim_maclari[s["dep_takim_id"]].append(s["mac_id"])

        self.oyuncular = {s["oyuncu_id"]: dict(s) for s in conn.execute("SELECT oyuncu_id, isim, takim_id, pozisyon, aktif FROM oyuncular")}
        if gecmis:
            son_takim = k.groupby("oyuncu_id")["takim_id"].last().to_dict()
            for kimlik, o in self.oyuncular.items():
                o["takim_id"], o["aktif"] = son_takim.get(kimlik), int(kimlik in son_takim)
        self.savunma = {(s["takim_id"], s["pozisyon"], s["istatistik"]): s for s in savunma.profil_hesapla(conn, tarih)}

        # Lig geneli oranlar (dakika başına üretim üzerinden).
        self.lig_ev_orani = {}      # (istatistik, ev_mi) -> o sahadaki üretim / genel üretim
        self.lig_arka_arkaya = {}   # istatistik -> (arka arkaya maçlardaki üretim / genel üretim, takım-maç sayısı)
        if len(k):
            genel = k[ISTATISTIKLER].sum() / k["dakika"].sum()
            saha = k.groupby("ev_mi")[ISTATISTIKLER + ["dakika"]].sum()
            aa = k[k["arka_arkaya"]]
            aa_takim_mac = len(aa[["takim_id", "mac_id"]].drop_duplicates())
            for ist in ISTATISTIKLER:
                if genel[ist] <= 0:
                    continue
                for ev_mi in saha.index:
                    self.lig_ev_orani[(ist, int(ev_mi))] = (saha.loc[ev_mi, ist] / saha.loc[ev_mi, "dakika"]) / genel[ist]
                if aa_takim_mac:
                    self.lig_arka_arkaya[ist] = ((aa[ist].sum() / aa["dakika"].sum()) / genel[ist], aa_takim_mac)

        # Geçen sezonun oyuncu toplamları (ön bilgi).
        self.onceki_sezon = {}
        for s in conn.execute("SELECT * FROM oyuncu_sezon WHERE sezon = ?", (config.ONCEKI_SEZON,)):
            g = dict(s)
            g["iki_isabet"] = (g["saha_ici_isabet"] or 0) - (g["ucluk"] or 0)
            g["iki_deneme"] = (g["saha_ici_deneme"] or 0) - (g["ucluk_deneme"] or 0)
            for ad in ("ucluk", "ucluk_deneme", "serbest_isabet", "serbest_deneme"):
                g[ad] = g[ad] or 0
            self.onceki_sezon[g["oyuncu_id"]] = g

        # Takımların maç tempoları (eskiden yeniye) ve lig ortalaması.
        self.takim_tempolari = defaultdict(list)
        for s in conn.execute("""
                SELECT tm.takim_id, tm.tempo FROM takim_mac tm JOIN maclar m USING (mac_id)
                WHERE m.tarih < ? AND tm.tempo IS NOT NULL ORDER BY m.tarih, tm.mac_id""", (tarih,)):
            self.takim_tempolari[s["takim_id"]].append(s["tempo"])
        tum = [t for liste in self.takim_tempolari.values() for t in liste]
        self.lig_tempo = sum(tum) / len(tum) if tum else None
        self.onbellek = {}          # etkenlerin takım düzeyindeki ara sonuçları için

        # Oynanmış maçların ev sahibi farkı ve takımların maç skorları (o günden önce).
        self.mac_farki = {}
        self.takim_skorlari = defaultdict(list)     # takım -> [(atılan, yenen, pozisyon sayısı)], eskiden yeniye
        for s in conn.execute("""
                SELECT m.mac_id, m.ev_sayi, m.dep_sayi, tm.takim_id, tm.ev_mi, tm.pozisyon_sayisi
                FROM maclar m LEFT JOIN takim_mac tm USING (mac_id)
                WHERE m.durum = 'oynandi' AND m.tarih < ? AND m.ev_sayi IS NOT NULL ORDER BY m.tarih, m.mac_id""", (tarih,)):
            self.mac_farki[s["mac_id"]] = s["ev_sayi"] - s["dep_sayi"]
            if s["takim_id"] is not None:
                atilan, yenen = (s["ev_sayi"], s["dep_sayi"]) if s["ev_mi"] else (s["dep_sayi"], s["ev_sayi"])
                self.takim_skorlari[s["takim_id"]].append((atilan, yenen, s["pozisyon_sayisi"]))

        # Takımların maç maç şutları: (kendi isabet, kendi deneme, rakibin isabeti, rakibin denemesi).
        self.takim_sut = defaultdict(list)
        for s in conn.execute("""
                SELECT a.takim_id, a.saha_ici_isabet, a.saha_ici_deneme, b.saha_ici_isabet AS r_isabet, b.saha_ici_deneme AS r_deneme
                FROM takim_mac a JOIN takim_mac b ON b.mac_id = a.mac_id AND b.takim_id = a.rakip_id JOIN maclar m ON m.mac_id = a.mac_id
                WHERE m.tarih < ? AND a.saha_ici_deneme > 0 AND b.saha_ici_deneme > 0 ORDER BY m.tarih, a.mac_id""", (tarih,)):
            self.takim_sut[s["takim_id"]].append((s["saha_ici_isabet"], s["saha_ici_deneme"], s["r_isabet"], s["r_deneme"]))

        # Hakemler: atamalar maç öncesi yayımlanır (bilinen bilgi). Düdük toplamları yalnızca o günden önceki maçlardan.
        self.hakem_mac = defaultdict(list)
        for s in conn.execute("SELECT mac_id, hakem_id FROM hakem_mac ORDER BY mac_id, hakem_id"):
            self.hakem_mac[s["mac_id"]].append(s["hakem_id"])
        self.mac_dudukleri = {}     # mac_id -> (ev takımı, deplasman takımı, toplam faul, toplam SA denemesi); 48 dakikaya indirgenmiş
        for s in conn.execute("""
                SELECT a.mac_id, a.takim_id AS ev, a.rakip_id AS dep, a.faul + b.faul AS faul, a.serbest_deneme + b.serbest_deneme AS sa, a.dakika
                FROM takim_mac a JOIN takim_mac b ON b.mac_id = a.mac_id AND b.takim_id = a.rakip_id JOIN maclar m ON m.mac_id = a.mac_id
                WHERE a.ev_mi = 1 AND m.tarih < ? AND a.faul IS NOT NULL AND b.faul IS NOT NULL""", (tarih,)):
            olcek = 240.0 / s["dakika"]
            self.mac_dudukleri[s["mac_id"]] = (s["ev"], s["dep"], s["faul"] * olcek, s["sa"] * olcek)

        # Yolculuk ve dinlenme: fikstürden hesaplanır, önceden bilinen bilgidir (oynanmamış maçlar dahil).
        self.yolculuk = {(s["takim_id"], s["mac_id"]): dict(s) for s in conn.execute("SELECT * FROM yolculuk")}

        # Bahis çizgileri: maç öncesi bilgidir. Canlı tahminde güncel çekim, geriye dönük denemede kapanış çizgisi önceliklidir.
        self.oranlar = {}
        oncelik = "kapanis" if gecmis else "guncel"
        for s in conn.execute("SELECT mac_id, tur, handikap, toplam FROM oranlar"):
            if s["mac_id"] not in self.oranlar or s["tur"] == oncelik:
                self.oranlar[s["mac_id"]] = {"handikap": s["handikap"], "toplam": s["toplam"]}

        # O günün sakatlık görüntüsü. Kaydı olmayan takım "veri yok" sayılır.
        self.sakatlik = {}
        self.sakatlik_takimlari = set()
        for s in conn.execute("SELECT oyuncu_id, takim_id, durum FROM sakatliklar WHERE kaynak = 'espn' AND cekim_tarihi = ?", (tarih,)):
            self.sakatlik_takimlari.add(s["takim_id"])
            if s["oyuncu_id"] is not None:
                self.sakatlik[s["oyuncu_id"]] = s["durum"]

        # NBA resmi raporu ESPN'in önüne geçer: "Out" ise oyuncu dışarıdadır; "Questionable" / "Doubtful" belirsizdir
        # ("Day-To-Day" gibi ele alınır); "Probable" / "Available" ise ESPN ne derse desin oynaması beklenir.
        self.resmi = {}
        if config.RESMI_RAPOR_KULLAN:
            for s in conn.execute("SELECT oyuncu_id, takim_id, durum FROM sakatliklar WHERE kaynak = 'nba_resmi' AND cekim_tarihi = ?", (tarih,)):
                if s["durum"] == "BILDIRILMEDI":
                    continue
                self.sakatlik_takimlari.add(s["takim_id"])
                if s["oyuncu_id"] is None:
                    continue
                self.resmi[s["oyuncu_id"]] = s["durum"]
                if s["durum"] == "Out":
                    self.sakatlik[s["oyuncu_id"]] = "Out"
                elif s["durum"] in ("Questionable", "Doubtful"):
                    self.sakatlik[s["oyuncu_id"]] = "Day-To-Day"
                else:
                    self.sakatlik.pop(s["oyuncu_id"], None)

        # Bu gecenin ilk beşleri (nba.com beslemesi): (maç, takım) -> {'ilk_bes': oyuncu kimlikleri, 'kesin': hepsi "Confirmed" mi}.
        # Beslemenin kadro dışı (Inactive) bildirdiği oyuncu "Out" sayılır.
        self.bu_gece = {}
        for s in conn.execute("SELECT b.* FROM ilk_bes_beklenti b JOIN maclar m USING (mac_id) WHERE m.tarih = ?", (tarih,)):
            kayit = self.bu_gece.setdefault((s["mac_id"], s["takim_id"]), {"ilk_bes": set(), "kesin": True})
            if s["kadro_durumu"] and s["kadro_durumu"] != "Active":
                self.sakatlik[s["oyuncu_id"]] = "Out"
            elif s["pozisyon"]:
                kayit["ilk_bes"].add(s["oyuncu_id"])
                kayit["kesin"] = kayit["kesin"] and s["durum"] == "Confirmed"
        self._eksik = {}

    def son_maclarda_dakika(self, oyuncu_id, takim_id, pencere):
        """Oyuncunun, takımın son `pencere` maçında maç başına aldığı dakika (oynamadığı maç 0 sayılır)."""
        maclar = self.takim_maclari[takim_id][-pencere:]
        if not maclar:
            return 0.0, 0
        return sum(self.dakika.get((oyuncu_id, m), 0.0) for m in maclar) / len(maclar), len(maclar)

    def takim_eksikleri(self, takim_id):
        """Takımın bugünkü sakatları: {'veri_var', 'mac', 'out': [(kimlik, isim, dk/maç)], 'gunluk': [...]}"""
        if takim_id not in self._eksik:
            sonuc = {"veri_var": takim_id in self.sakatlik_takimlari, "mac": 0, "out": [], "gunluk": []}
            for kimlik, durum in self.sakatlik.items():
                o = self.oyuncular.get(kimlik)
                if o is None or o["takim_id"] != takim_id:
                    continue
                dk, sonuc["mac"] = self.son_maclarda_dakika(kimlik, takim_id, config.EKSIK_ARKADAS_PENCERE)
                sonuc["out" if durum == "Out" else "gunluk"].append((kimlik, o["isim"], dk))
            self._eksik[takim_id] = sonuc
        return self._eksik[takim_id]


def temel_oran_36(k, istatistik):
    """36 dk başına temel üretim: sezon, son 10 ve son 5 maçın ağırlıklı ortalaması.

    Her pencerede dakikalar toplanarak hesaplanır. Döndürür: (ağırlıklı oran, pencere oranları).
    """
    return etkenler.agirlikli_oran_36(k, istatistik)


def beklenen_dakika(k):
    """Son 5 maçın dakika ortalaması; bu 5 maçta ilk beş / yedek rolü değiştiyse son 3 maç.

    Döndürür: (dakika, rol_degisti).
    """
    return etkenler.beklenen_dakika(k)


def _dogrusal(deger, tam, sifir):
    """`tam` ve altında 1, `sifir` ve üstünde 0, arada doğrusal."""
    if deger <= tam:
        return 1.0
    if deger >= sifir:
        return 0.0
    return (sifir - deger) / (sifir - tam)


SANS_ETKENLERI = {"sayi": "sut_duzeltme", "ucluk": "sut_duzeltme", "asist": "firsat", "ribaund": "firsat"}


def guven_puani(baglam, oyuncu, mac, istatistik, k, zincir):
    """0–100 güven puanı ve bileşenleri (PLAN_EK bölüm 8)."""
    a = config.GUVEN_AGIRLIK
    e = zincir.etkenler

    orneklem = min(1.0, len(k) / config.GUVEN_TAM_PUAN_MAC)

    ort = k[istatistik].mean()
    cv = k[istatistik].std(ddof=0) / ort if ort > 0 else math.inf
    istikrar = _dogrusal(cv, *config.GUVEN_ISTIKRAR_CV)

    # Dakika sabitliği: son maçlardaki oynaklık × takımın son maçlarına katılım × faul eğilimi.
    oynaklik = _dogrusal(k.tail(config.DAKIKA_PENCERE)["dakika"].std(ddof=0), *config.GUVEN_DAKIKA_SS)
    son_maclar = baglam.takim_maclari[oyuncu.takim_id][-config.ROTASYON_PENCERE:]
    katilim = sum((oyuncu.oyuncu_id, m) in baglam.dakika for m in son_maclar) / len(son_maclar) if son_maclar else 0.0
    faul_36 = config.NORMALLESTIRME_DAKIKA * k["faul"].sum() / k["dakika"].sum()
    faul = 1.0 - 0.4 * (1.0 - _dogrusal(faul_36, *config.GUVEN_FAUL_36))
    dakika = oynaklik * katilim * faul

    # Veri bütünlüğü: açık etkenlerin kaçında veri var.
    butunluk = sum(s.veri_var for s in e.values()) / len(e) if e else 1.0

    # Sakatlık belirsizliği: oyuncu ya da önemli arkadaşları "Day-To-Day" mi; oyuncu uzun aradan mı dönüyor.
    eksik = baglam.takim_eksikleri(oyuncu.takim_id)
    if not eksik["veri_var"]:
        sakatlik = 0.5          # takım için veri yok: belirsiz
    elif any(kimlik == oyuncu.oyuncu_id for kimlik, _, _ in eksik["gunluk"]):
        sakatlik = 0.0          # oyuncunun kendisi "Day-To-Day"
    else:
        belirsiz = sum(dk >= config.GUVEN_ROTASYON_DAKIKA for _, _, dk in eksik["gunluk"])
        sakatlik = max(0.2, 1.0 - 0.25 * belirsiz)
    if "donus" in e and e["donus"].carpan < 1.0:
        sakatlik *= 0.5         # uzun aradan dönüyor: dakikası belirsiz

    # Fark riski: farklı maç olasılığı düşükse tam puan; beklenen fark bilinmiyorsa yarım.
    fark, _ = fark_riski.beklenen_fark(baglam, mac)
    if fark is None:
        fark_puani = 0.5
    else:
        fark_puani = _dogrusal(fark_riski.buyuk_fark_olasiligi(fark, fark_riski.lig_ozeti(baglam)["sigma"]), *config.GUVEN_FARK_OLASILIGI)

    # Şut şansı farkı: güncel yüzde (ya da dönüşüm) düzeltilmiş değerden uzaksa "sıcak / soğuk seri" var demektir.
    sans_etkeni = SANS_ETKENLERI.get(istatistik)
    if sans_etkeni is None or sans_etkeni not in e:
        sans = 1.0              # bu istatistikte şans düzeltmesi yapılmıyor (ya da etken kapalı)
    elif not e[sans_etkeni].veri_var:
        sans = 0.5
    else:
        sans = _dogrusal(abs(e[sans_etkeni].carpan - 1.0), *config.GUVEN_SANS_UZAKLIGI)

    # Eşleşme netliği: rakibin düzeltilmiş savunma oranının örneklemi.
    s = baglam.savunma.get((mac.rakip(oyuncu.takim_id), oyuncu.pozisyon, istatistik))
    eslesme = 0.0 if s is None or s["beklenene_gore_duzeltilmis"] is None else min(1.0, s["oyuncu_dakika"] / config.GUVEN_ESLESME_DAKIKA)

    bilesenler = {
        "orneklem": a["orneklem"] * orneklem,
        "istikrar": a["istikrar"] * istikrar,
        "dakika_sabitligi": a["dakika_sabitligi"] * dakika,
        "veri_butunlugu": a["veri_butunlugu"] * butunluk,
        "sakatlik_belirsizligi": a["sakatlik_belirsizligi"] * sakatlik,
        "fark_riski": a["fark_riski"] * fark_puani,
        "sut_sansi": a["sut_sansi"] * sans,
        "eslesme_netligi": a["eslesme_netligi"] * eslesme,
    }
    return sum(bilesenler.values()), bilesenler


def lig_oynakligi(baglam):
    """İstatistik başına ligin olağan oynaklığı: oyuncuların maç değerlerinin varyans / ortalama oranının ortancası."""
    if "oynaklik" not in baglam.onbellek:
        sonuc = {}
        k = baglam.kayitlar
        if len(k):
            grup = k.groupby("oyuncu_id")[ISTATISTIKLER]
            adet, ort, varyans = grup.count(), grup.mean(), grup.var(ddof=1)
            for ist in ISTATISTIKLER:
                secim = (adet[ist] >= 8) & (ort[ist] > 0)
                if secim.any():
                    sonuc[ist] = float((varyans[ist][secim] / ort[ist][secim]).median())
        baglam.onbellek["oynaklik"] = sonuc
    return baglam.onbellek["oynaklik"]


def standart_sapma(baglam, k, istatistik, tahmin_degeri):
    """Tahminin beklenen standart sapması: sayım verisinde varyans ≈ oynaklık × ortalama.

    Oynaklık (varyans / ortalama) oyuncunun kendi maçlarından hesaplanır ve lig geneline çekilir.
    """
    lig = lig_oynakligi(baglam).get(istatistik, 1.0)
    oynaklik, ort = lig, k[istatistik].mean()
    if len(k) >= config.ARALIK_MIN_MAC and ort > 0:
        oynaklik = etkenler.kucuk_orneklem(len(k), k[istatistik].var(ddof=1) / ort, config.ARALIK_K, notr=lig)
    return config.ARALIK_OLCEK.get(istatistik, 1.0) * math.sqrt(max(oynaklik * tahmin_degeri, 0.0))


def aralik(tahmin_degeri, sapma):
    """(alt %10, üst %90): tahmin ∓ z × standart sapma; alt sıfırın altına inmez."""
    return max(0.0, tahmin_degeri - config.ARALIK_Z * sapma), tahmin_degeri + config.ARALIK_Z * sapma


def oyuncu_tahmini(baglam, oyuncu, mac, etken_listesi):
    """Bir oyuncunun bir maçtaki tüm istatistikleri için tahmin satırları; tahmin üretilemezse boş liste.

    Her satır: {'istatistik', 'tahmin', 'alt', 'ust', 'guven', 'girdiler', 'zincir'} ('zincir' birleşik değerlerde None).
    tahmin orta (%50) değerdir; alt ve ust %10 ve %90'lık değerlerdir.
    """
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is None or len(k) < config.TAHMIN_MIN_MAC:
        return []
    dakika, rol_degisti = beklenen_dakika(k)
    if dakika < config.TAHMIN_MIN_DAKIKA:
        return []

    satirlar = {}
    for ist in ISTATISTIKLER:
        oran, pencereler = temel_oran_36(k, ist)
        zincir = etkenler.uygula(oyuncu, mac, ist, baglam, etken_listesi)
        guven, bilesenler = guven_puani(baglam, oyuncu, mac, ist, k, zincir)
        temel = dakika * oran / config.NORMALLESTIRME_DAKIKA
        sapma = standart_sapma(baglam, k, ist, temel * zincir.carpan)
        alt, ust = aralik(temel * zincir.carpan, sapma)
        satirlar[ist] = {
            "istatistik": ist,
            "tahmin": temel * zincir.carpan,
            "alt": alt, "ust": ust, "sapma": sapma,
            "guven": guven,
            "zincir": zincir,
            "girdiler": {
                "beklenen_dakika": round(dakika, 2),
                "duzeltilmis_dakika": round(dakika * zincir.dakika_carpani, 2),   # dakika türü etkenlerden sonra
                "rol_degisti": rol_degisti,
                "temel_oran_36": round(oran, 4),
                "pencereler": {ad: round(o, 4) for ad, o in pencereler.items()},
                "mac_sayisi": len(k),
                "temel_tahmin": temel,                     # etkenler uygulanmadan önceki tahmin
                "sezon_ort": float(k[ist].mean()),         # karşılaştırma ölçütü: sezon maç ortalaması
                "carpan": round(zincir.carpan, 4),
                "guven": {ad: round(p, 1) for ad, p in bilesenler.items()},
            },
        }
    if config.BIRLESIK_TAHMIN:
        for ad, parcalar in config.BIRLESIK.items():
            toplam = sum(satirlar[p]["tahmin"] for p in parcalar)
            # Bileşenler bağımsız sayılır; aralarındaki bağ (ortak dakika) ölçek katsayısıyla karşılanır.
            sapma = config.ARALIK_OLCEK.get(ad, 1.0) * math.sqrt(sum(satirlar[p]["sapma"] ** 2 for p in parcalar))
            alt, ust = aralik(toplam, sapma)
            satirlar[ad] = {
                "istatistik": ad,
                "tahmin": toplam,
                "alt": alt, "ust": ust, "sapma": sapma,
                "guven": min(satirlar[p]["guven"] for p in parcalar),   # en zayıf bileşen kadar güvenilir
                "zincir": None,
                "girdiler": {"beklenen_dakika": round(dakika, 2), "bilesenler": list(parcalar)},
            }
    return list(satirlar.values())


def tahmin_edilecekler(baglam, mac):
    """Maçta tahmin üretilecek oyuncular: kadroda, "Out" değil, takımının son maçlarında oynamış."""
    liste = []
    for takim_id in (mac.ev_takim_id, mac.dep_takim_id):
        son_maclar = baglam.takim_maclari[takim_id][-config.ROTASYON_PENCERE:]
        for o in baglam.oyuncular.values():
            if o["takim_id"] != takim_id or not o["aktif"] or baglam.sakatlik.get(o["oyuncu_id"]) == "Out":
                continue
            if not any((o["oyuncu_id"], m) in baglam.dakika for m in son_maclar):
                continue
            liste.append(Oyuncu(o["oyuncu_id"], o["isim"], takim_id, o["pozisyon"]))
    return liste


def gunun_maclari(conn, tarih, durum="oynanacak", yalniz_baslamamis=False, pencere_dk=None):
    """Günün maçları. yalniz_baslamamis=True ise başlama saati geçmiş olanlar alınmaz;
    pencere_dk verilirse yalnızca o kadar dakika içinde başlayacak olanlar alınır."""
    bicim = "%Y-%m-%dT%H:%M:%SZ"
    simdi = datetime.now(timezone.utc)
    alt = simdi.strftime(bicim) if yalniz_baslamamis else ""
    ust = (simdi + timedelta(minutes=pencere_dk)).strftime(bicim) if pencere_dk is not None else "9"
    return [Mac(s["mac_id"], s["tarih"], s["ev_takim_id"], s["dep_takim_id"]) for s in conn.execute(
        """SELECT mac_id, tarih, ev_takim_id, dep_takim_id FROM maclar
           WHERE tarih = ? AND durum = ? AND COALESCE(baslama_utc, '8') > ? AND COALESCE(baslama_utc, '8') <= ? ORDER BY baslama_utc, mac_id""",
        (tarih, durum, alt, ust))]


def gunu_tahmin_et(conn, tarih=None, tur="canli", etken_listesi=None, calistirma="sabah", yalniz_baslamamis=False, pencere_dk=None):
    """Günün maçları için tahmin üretir, tahminler ve tahmin_etken tablolarına yazar.

    tur='canli': günün oynanacak maçları, bugünkü kadro ve sakatlık listesiyle.
    tur='geri_test': o gün oynanmış maçlar, yalnızca o günden önceki veriyle (geriye dönük deneme).

    calistirma: 'sabah' (ön tahmin) ya da 'mac_oncesi' (kesin tahmin). Sabah çalıştırması tahmini ayrıca on_tahmin
    sütununa yazar; maç öncesi çalıştırma o sütuna dokunmaz, böylece ikisi sonradan ayrı ayrı puanlanabilir.
    yalniz_baslamamis: başlama saati geçmiş maçlar yenilenmez (tahminleri olduğu gibi kalır).

    Aynı gün yeniden çalışırsa tahminler güncellenir; artık tahmin edilmeyen
    (örneğin sonradan "Out" olan) oyuncuların eski tahminleri silinir.
    Döndürür: yazılan tahmin satırları (rapor için).
    """
    tarih = tarih or veritabani.abd_bugun()
    gecmis = tur == "geri_test"
    baglam = Baglam(conn, tarih, gecmis=gecmis)
    if etken_listesi is None:
        etken_listesi = etkenler.acik_etkenler()
    maclar = gunun_maclari(conn, tarih, "oynandi" if gecmis else "oynanacak", yalniz_baslamamis, pencere_dk)
    calistirma = "geri_test" if gecmis else calistirma
    simdi = veritabani.simdi_utc()

    sonuc = []
    for mac in maclar:
        for oyuncu in tahmin_edilecekler(baglam, mac):
            for t in oyuncu_tahmini(baglam, oyuncu, mac, etken_listesi):
                sonuc.append({**t, "oyuncu": oyuncu, "mac": mac})

    veritabani.yaz(conn, "tahminler", [{
        "tur": tur, "tarih": t["mac"].tarih, "oyuncu_id": t["oyuncu"].oyuncu_id, "mac_id": t["mac"].mac_id,
        "istatistik": t["istatistik"], "tahmin": t["tahmin"], "alt": t["alt"], "ust": t["ust"], "guven": t["guven"],
        "girdiler": json.dumps(t["girdiler"], ensure_ascii=False), "olusturma": simdi, "calistirma": calistirma,
        **({"on_tahmin": t["tahmin"], "on_guven": t["guven"]} if calistirma == "sabah" else {}),
    } for t in sonuc])

    if maclar:
        yer = ",".join("?" * len(maclar))
        mac_kimlikleri = [m.mac_id for m in maclar]
        with conn:  # bu çalıştırmada yeniden üretilmeyen eski tahminler
            # Canlı tahminde puanlanmış satırlara dokunulmaz; geriye dönük denemede hepsi yeniden üretilir.
            conn.execute(f"DELETE FROM tahminler WHERE tur = ? AND olusturma <> ? AND mac_id IN ({yer})"
                         + ("" if gecmis else " AND gerceklesen IS NULL"), (tur, simdi, *mac_kimlikleri))
        kimlik = {(s["oyuncu_id"], s["mac_id"], s["istatistik"]): s["tahmin_id"] for s in conn.execute(
            f"SELECT tahmin_id, oyuncu_id, mac_id, istatistik FROM tahminler WHERE tur = ? AND mac_id IN ({yer})", (tur, *mac_kimlikleri))}
        etken_satirlari = []
        for t in sonuc:
            if t["zincir"] is not None:
                etken_satirlari += etkenler.etken_satirlari(kimlik[(t["oyuncu"].oyuncu_id, t["mac"].mac_id, t["istatistik"])], t["zincir"])
        # Bu maçların eski etken kayıtlarını sil: kapatılmış bir etkenin çarpanı tabloda kalmasın.
        conn.execute(f"DELETE FROM tahmin_etken WHERE tahmin_id IN (SELECT tahmin_id FROM tahminler WHERE tur = ? AND mac_id IN ({yer}))",
                     (tur, *mac_kimlikleri))
        veritabani.yaz(conn, "tahmin_etken", etken_satirlari)
        conn.commit()

    log.log(logging.DEBUG if gecmis else logging.INFO, "Tahmin (%s): %d maç, %d oyuncu, %d tahmin satırı", tarih, len(maclar),
             len({(t["oyuncu"].oyuncu_id, t["mac"].mac_id) for t in sonuc}), len(sonuc))
    return sonuc


def rapor_metni(conn, sonuc, tarih):
    takim = {s["takim_id"]: s["kisaltma"] for s in conn.execute("SELECT takim_id, kisaltma FROM takimlar")}
    oyuncu_sayisi = len({(t["oyuncu"].oyuncu_id, t["mac"].mac_id) for t in sonuc})
    s = [f"=== Tahminler ({tarih}) ===",
         f"{len({t['mac'].mac_id for t in sonuc})} maç, {oyuncu_sayisi} oyuncu, {len(sonuc)} tahmin satırı",
         "Sütunlar: beklenen dakika, sayı, ribaund, asist, üçlük, top çalma, blok, top kaybı; G = sayı tahmininin güven puanı; çarpan = sayıdaki toplam etken çarpanı"]
    tablo = defaultdict(dict)
    for t in sonuc:
        tablo[(t["mac"].mac_id, t["oyuncu"].oyuncu_id)][t["istatistik"]] = t
    onceki_mac = None
    for (mac_id, _), satir in sorted(tablo.items(), key=lambda x: (x[0][0], x[1]["sayi"]["oyuncu"].takim_id, -x[1]["sayi"]["girdiler"]["beklenen_dakika"])):
        t = satir["sayi"]
        if mac_id != onceki_mac:
            onceki_mac = mac_id
            s.append(f"\n{takim[t['mac'].dep_takim_id]} @ {takim[t['mac'].ev_takim_id]}")
            s.append(f"  {'oyuncu':<24} {'tk':<4}{'poz':<4}{'dk':>5}{'sayı':>6}{'rib':>6}{'ast':>6}{'3lük':>6}{'tç':>5}{'blk':>5}{'tk':>5}{'G':>5}  çarpan")
        o = t["oyuncu"]
        s.append(f"  {o.isim[:24]:<24} {takim[o.takim_id]:<4}{o.pozisyon or '-':<4}{t['girdiler']['beklenen_dakika']:>5.1f}"
                 + "".join(f"{satir[i]['tahmin']:>{g}.1f}" for i, g in zip(ISTATISTIKLER, (6, 6, 6, 6, 5, 5, 5)))
                 + f"{t['guven']:>5.0f}  {t['girdiler']['carpan']:.3f}")
    return "\n".join(s)


def main(argv):
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tarih = argv[0] if argv else veritabani.abd_bugun()
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        sonuc = gunu_tahmin_et(conn, tarih)
        metin = rapor_metni(conn, sonuc, tarih)
        config.RAPOR_KLASORU.mkdir(exist_ok=True)
        (config.RAPOR_KLASORU / f"tahmin_{tarih}.txt").write_text(metin + "\n", encoding="utf-8")
        print(metin)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
