"""Kaynaklardan veri çekip veri tabanına yazan adımlar.

ilk_kurulum.py ve (ileride) gunluk.py bu işlevleri kullanır. Tek bir adımı elle
çalıştırmak için:  .venv\\Scripts\\python.exe yukle.py sakatlik
"""
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

import pandas as pd

import config
import kadro
import veritabani
from kaynak import KaynakHatasi, espn, mac_kaynagi, nba_resmi, nba_sakatlik, nba_stats, takip_kaynagi

log = logging.getLogger("yukle")

# LeagueGameLog sütunu -> oyuncu_mac sütunu
SUTUN_ESLEME = {
    "PTS": "sayi", "REB": "ribaund", "AST": "asist", "FG3M": "ucluk", "STL": "top_calma",
    "BLK": "blok", "TOV": "top_kaybi", "FGM": "saha_ici_isabet", "FGA": "saha_ici_deneme",
    "FG3A": "ucluk_deneme", "FTM": "serbest_isabet", "FTA": "serbest_deneme", "PF": "faul",
}


def _tam(deger):
    return None if pd.isna(deger) else int(deger)


def log_kur(ad):
    """Konsola ve log/<ad>.log dosyasına yazar."""
    # Çıktı dosyaya ya da Görev Zamanlayıcı'ya yönlendirildiğinde aksanlı isimler hata vermesin.
    # Görev Zamanlayıcı betiği penceresiz (pythonw.exe) çalıştırır; o durumda konsol akışları yoktur.
    for akis in (sys.stdout, sys.stderr):
        if akis is not None:
            akis.reconfigure(encoding="utf-8", errors="replace")
    config.LOG_KLASORU.mkdir(exist_ok=True)
    yazicilar = [logging.FileHandler(config.LOG_KLASORU / f"{ad}.log", encoding="utf-8")]
    if sys.stderr is not None:
        yazicilar.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=yazicilar)


def adim(conn, calisma_id, ad, islev):
    """Bir adımı çalıştırır ve sonucunu calisma_kaydi tablosuna yazar."""
    basla = time.monotonic()
    try:
        sonuc = islev()
    except Exception as e:
        veritabani.kayit_yaz(conn, calisma_id, ad, "hata", f"{type(e).__name__}: {e}", time.monotonic() - basla)
        raise
    veritabani.kayit_yaz(conn, calisma_id, ad, "tamam", None, time.monotonic() - basla)
    return sonuc


def takimlari_yukle(conn):
    """NBA takımlarını yazar ve ESPN kimlikleriyle eşler (takma ad üzerinden: Hawks, 76ers ...)."""
    nba = nba_stats.takimlar()
    satirlar = []
    for e in espn.takimlar():
        eslesen = [t for t in nba if t["isim"].endswith(" " + e["takma_ad"])]
        if len(eslesen) != 1:
            raise KaynakHatasi(f"ESPN takımı NBA takımıyla eşleşmedi: {e['isim']} ({len(eslesen)} aday)")
        satirlar.append({**eslesen[0], "espn_id": e["espn_id"], "espn_kisaltma": e["espn_kisaltma"]})
    if len({s["takim_id"] for s in satirlar}) != 30:
        raise KaynakHatasi("ESPN–NBA takım eşlemesi 30 ayrı takım vermedi")
    return veritabani.yaz(conn, "takimlar", satirlar)


def fiksturu_yukle(conn):
    maclar, belirsiz = mac_kaynagi().fikstur()
    veritabani.yaz(conn, "maclar", maclar)
    oynanan = sum(m["durum"] == "oynandi" for m in maclar)
    log.info("Fikstür: %d maç yazıldı (%d oynandı), %d maçın takımı henüz belli değil", len(maclar), oynanan, len(belirsiz))
    return len(maclar)


def mac_kayitlarini_yukle(conn, tarihten=None, tarihe=None):
    """Oyuncu maç kayıtlarını çeker; yeni maçlar için kutu skorundan ilk beş ve dakikayı ekler.

    Döndürür: (yazılan satır, kutu skoru alınan maç, kutu skoru alınamayan maç listesi).
    """
    # Tarih süzgeciyle çağrıldığında (günlük akış) o aralıkta maç olmayabilir; bu hata değildir.
    df = mac_kaynagi().oyuncu_mac_kayitlari(tarihten=tarihten, tarihe=tarihe, bos_olabilir=tarihten is not None)
    if df.empty:
        log.info("Maç kayıtları: %s tarihinden beri oynanmış maç yok", tarihten)
        return 0, 0, []
    maclar = {s["mac_id"]: s for s in conn.execute("SELECT mac_id, ev_takim_id, dep_takim_id FROM maclar")}
    bilinmeyen = sorted(set(df["GAME_ID"]) - set(maclar))
    if bilinmeyen:
        raise KaynakHatasi(f"Maç kaydında fikstürde olmayan maçlar var: {bilinmeyen[:5]}")

    # Yeni oyuncuları ekle. Var olan oyuncunun takımına dokunma: o, kadro adımının işi.
    kayitli = {s[0] for s in conn.execute("SELECT oyuncu_id FROM oyuncular")}
    son_mac = df.sort_values("GAME_DATE").groupby("PLAYER_ID").tail(1)
    yeni = [
        {"oyuncu_id": int(s.PLAYER_ID), "isim": s.PLAYER_NAME, "takim_id": int(s.TEAM_ID), "guncelleme": veritabani.simdi_utc()}
        for s in son_mac.itertuples(index=False)
        if int(s.PLAYER_ID) not in kayitli
    ]
    veritabani.yaz(conn, "oyuncular", yeni)
    log.info("Oyuncular: %d yeni oyuncu eklendi (maç kaydında %d oyuncu)", len(yeni), df["PLAYER_ID"].nunique())

    # Kutu skoru daha önce alınmış maçlar: hiçbir satırında ilk_bes boş değil.
    tamam = {s[0] for s in conn.execute("SELECT mac_id FROM oyuncu_mac GROUP BY mac_id HAVING SUM(ilk_bes IS NULL) = 0")}

    yazilan, cekilen, alinamayan = 0, 0, []
    gruplar = list(df.groupby("GAME_ID", sort=True))
    for sira, (mac_id, grup) in enumerate(gruplar, 1):
        mac = maclar[mac_id]
        satirlar = []
        for s in grup.to_dict("records"):
            takim = int(s["TEAM_ID"])
            if takim not in (mac["ev_takim_id"], mac["dep_takim_id"]):
                raise KaynakHatasi(f"{mac_id}: {s['PLAYER_NAME']} bu maçın takımlarından birinde değil ({takim})")
            ev_mi = takim == mac["ev_takim_id"]
            satir = {
                "oyuncu_id": int(s["PLAYER_ID"]),
                "mac_id": mac_id,
                "takim_id": takim,
                "rakip_id": mac["dep_takim_id"] if ev_mi else mac["ev_takim_id"],
                "ev_mi": int(ev_mi),
            }
            satir.update({hedef: _tam(s[kaynak]) for kaynak, hedef in SUTUN_ESLEME.items()})
            satirlar.append((satir, _tam(s["MIN"])))

        if mac_id in tamam:
            # İstatistik düzeltmeleri güncellensin; kutu skorundan gelen dakika ve ilk beş korunur.
            yazilan += veritabani.yaz(conn, "oyuncu_mac", [satir for satir, _ in satirlar])
            continue

        try:
            kutu = mac_kaynagi().kutu_skoru(mac_id)
            for satir, yuvarlak_dakika in satirlar:
                k = kutu.get(satir["oyuncu_id"])
                if k is None:
                    if yuvarlak_dakika:
                        raise KaynakHatasi(f"{mac_id}: oyuncu {satir['oyuncu_id']} kutu skorunda yok")
                    k = {"ilk_bes": 0, "dakika": 0.0}
                satir["dakika"], satir["ilk_bes"] = k["dakika"], k["ilk_bes"]
            cekilen += 1
        except KaynakHatasi as e:
            # Maç kaydını yine de yaz; ilk_bes boş kaldığı için sonraki çalıştırmada yeniden denenir.
            log.warning("Kutu skoru alınamadı, yuvarlak dakika yazılıyor: %s", e)
            alinamayan.append(mac_id)
            for satir, yuvarlak_dakika in satirlar:
                satir["dakika"], satir["ilk_bes"] = yuvarlak_dakika, None
        yazilan += veritabani.yaz(conn, "oyuncu_mac", [satir for satir, _ in satirlar])
        if sira % 25 == 0 or sira == len(gruplar):
            log.info("Maç kayıtları: %d/%d maç işlendi", sira, len(gruplar))

    log.info("Maç kayıtları: %d satır yazıldı, %d maçın kutu skoru çekildi, %d maçınki alınamadı", yazilan, cekilen, len(alinamayan))
    return yazilan, cekilen, alinamayan


def gecen_sezonu_yukle(conn, sezon=None):
    """Geçen sezonun oyuncu maç kayıtlarını çeker, oyuncu başına toplayıp oyuncu_sezon tablosuna yazar.

    Maç maç saklanmaz: yalnızca ön bilgi (şut yüzdeleri vb.) için sezon toplamları gerekir ve bu
    sezonun hesapları geçen sezonun maçlarıyla karışmaz. Döndürür: yazılan oyuncu sayısı.
    """
    sezon = sezon or config.ONCEKI_SEZON
    df = nba_stats.oyuncu_mac_kayitlari(sezon=sezon)
    toplam = df.groupby("PLAYER_ID")[["MIN"] + list(SUTUN_ESLEME)].sum()
    mac = df.groupby("PLAYER_ID")["GAME_ID"].nunique()
    satirlar = []
    for oyuncu_id, s in toplam.iterrows():
        satir = {"oyuncu_id": int(oyuncu_id), "sezon": sezon, "mac_sayisi": int(mac[oyuncu_id]), "dakika": float(s["MIN"])}
        satir.update({hedef: int(s[kaynak]) for kaynak, hedef in SUTUN_ESLEME.items()})
        satirlar.append(satir)
    veritabani.yaz(conn, "oyuncu_sezon", satirlar)
    log.info("Geçen sezon (%s): %d oyuncunun sezon toplamı yazıldı (%d maç)", sezon, len(satirlar), df["GAME_ID"].nunique())
    return len(satirlar)


# LeagueGameLog (takım) sütunu -> takim_mac sütunu
TAKIM_SUTUN_ESLEME = {
    "PTS": "sayi", "FGM": "saha_ici_isabet", "FGA": "saha_ici_deneme", "FG3M": "ucluk_isabet", "FG3A": "ucluk_deneme",
    "FTM": "serbest_isabet", "FTA": "serbest_deneme", "OREB": "hucum_ribaund", "DREB": "savunma_ribaund",
    "AST": "asist", "STL": "top_calma", "BLK": "blok", "TOV": "top_kaybi", "PF": "faul",
}


def pozisyon_sayisi(sut_deneme, hucum_ribaundu, top_kaybi, serbest_deneme):
    """Bir takımın bir maçtaki pozisyon sayısı tahmini (PLAN_EK etken 2)."""
    return sut_deneme - hucum_ribaundu + top_kaybi + 0.44 * serbest_deneme


def takim_kayitlarini_yukle(conn, tarihten=None, tarihe=None):
    """Takım maç kutu skorlarını çeker; her maç için pozisyon sayısını ve tempoyu hesaplayıp yazar.

    Tempo maçın 48 dakikaya ölçeklenmiş pozisyon sayısıdır: iki takımın pozisyon
    ortalaması alınır, uzatmalar dakikaya bölünerek düzeltilir. Döndürür: yazılan satır sayısı.
    """
    df = mac_kaynagi().takim_mac_kayitlari(tarihten=tarihten, tarihe=tarihe, bos_olabilir=tarihten is not None)
    maclar = {s["mac_id"]: s for s in conn.execute("SELECT mac_id, ev_takim_id, dep_takim_id FROM maclar")}
    satirlar = []
    for mac_id, grup in df.groupby("GAME_ID", sort=True):
        mac = maclar.get(mac_id)
        if mac is None or len(grup) != 2 or set(grup["TEAM_ID"]) != {mac["ev_takim_id"], mac["dep_takim_id"]}:
            raise KaynakHatasi(f"Takım maç kaydı fikstürle tutmuyor: {mac_id} ({len(grup)} satır)")
        # Kaynakta tek takımın dakikası eksik gelebiliyor; maçın süresi iki satırın büyüğüdür.
        dakika = float(grup["MIN"].max())
        if dakika < 240 or (dakika - 240) % 25:
            raise KaynakHatasi(f"{mac_id}: beklenmeyen takım dakikası {dakika}")
        pozisyonlar = [pozisyon_sayisi(s.FGA, s.OREB, s.TOV, s.FTA) for s in grup.itertuples(index=False)]
        tempo = config.TEMPO_OLCEK * 48 * (sum(pozisyonlar) / 2) / (dakika / 5)
        for s, poz in zip(grup.to_dict("records"), pozisyonlar):
            ev_mi = int(s["TEAM_ID"]) == mac["ev_takim_id"]
            satir = {
                "takim_id": int(s["TEAM_ID"]), "mac_id": mac_id,
                "rakip_id": mac["dep_takim_id"] if ev_mi else mac["ev_takim_id"], "ev_mi": int(ev_mi),
                "dakika": dakika, "pozisyon_sayisi": float(poz), "tempo": float(tempo),
            }
            satir.update({hedef: _tam(s[kaynak]) for kaynak, hedef in TAKIM_SUTUN_ESLEME.items()})
            satirlar.append(satir)
    veritabani.yaz(conn, "takim_mac", satirlar)
    log.info("Takım maç kayıtları: %d satır (%d maç) yazıldı", len(satirlar), len(satirlar) // 2)
    return len(satirlar)


def kullanim_oranlarini_yaz(conn):
    """Her oyuncu-maç için kullanım oranını hesaplayıp oyuncu_mac.kullanim sütununa yazar (PLAN_EK etken 3).

    kullanım = 100 × (şut + 0,44 × SA + top kaybı) × (takım dakikası / 5) / (dakika × takımın (şut + 0,44 × SA + top kaybı))
    Takım kutu skoru (takim_mac) olmayan maçlarda boş kalır. Döndürür: dolu satır sayısı.
    """
    with conn:
        conn.execute("""
            UPDATE oyuncu_mac SET kullanim = (
                SELECT 100.0 * (oyuncu_mac.saha_ici_deneme + 0.44 * oyuncu_mac.serbest_deneme + oyuncu_mac.top_kaybi) * (tm.dakika / 5.0)
                       / (oyuncu_mac.dakika * (tm.saha_ici_deneme + 0.44 * tm.serbest_deneme + tm.top_kaybi))
                FROM takim_mac tm WHERE tm.mac_id = oyuncu_mac.mac_id AND tm.takim_id = oyuncu_mac.takim_id)
            WHERE dakika > 0""")
    dolu = conn.execute("SELECT COUNT(*) FROM oyuncu_mac WHERE kullanim IS NOT NULL").fetchone()[0]
    log.info("Kullanım oranı: %d oyuncu-maç satırı dolu", dolu)
    return dolu


def tempo_karsilastir(conn):
    """Takımların sezon temposunu nba.com değerleriyle karşılaştırır ve tabloyu yazdırır. Döndürür: en büyük mutlak fark."""
    nba = nba_stats.nba_com_tempo()
    bizim = conn.execute("""
        SELECT t.takim_id, t.kisaltma, COUNT(*) AS mac, AVG(tm.tempo) AS tempo, AVG(tm.tempo) / ? AS olceksiz
        FROM takim_mac tm JOIN takimlar t USING (takim_id) GROUP BY t.takim_id ORDER BY tempo""", (config.TEMPO_OLCEK,)).fetchall()
    print(f"\n=== Tempo karşılaştırması (ölçek {config.TEMPO_OLCEK}) ===")
    print(f"  {'takım':<6}{'maç':>4}{'bizim':>8}{'nba.com':>9}{'fark':>7}{'ölçeksiz fark':>15}")
    farklar, olceksiz_farklar = [], []
    for s in bizim:
        tempo, mac = nba[s["takim_id"]]
        farklar.append(s["tempo"] - tempo)
        olceksiz_farklar.append(s["olceksiz"] - tempo)
        print(f"  {s['kisaltma']:<6}{s['mac']:>4}{s['tempo']:>8.1f}{tempo:>9.1f}{farklar[-1]:>+7.2f}{olceksiz_farklar[-1]:>+15.2f}"
              + ("   (nba.com maç sayısı farklı)" if mac != s["mac"] else ""))
    en_buyuk = max(abs(f) for f in farklar)
    print(f"Ölçekli: ortalama fark {sum(farklar) / len(farklar):+.2f}, en büyük mutlak fark {en_buyuk:.2f}, "
          f"±1 dışında kalan takım: {sum(abs(f) > 1 for f in farklar)}")
    print(f"Ölçeksiz (ek plandaki formül): ortalama fark {sum(olceksiz_farklar) / len(olceksiz_farklar):+.2f}, "
          f"±1 dışında kalan takım: {sum(abs(f) > 1 for f in olceksiz_farklar)}")
    return en_buyuk


def takip_verisini_yukle(conn, tarihten=None):
    """Takip verisi henüz yazılmamış maç günleri için olası asist, ribaund fırsatı ve top dokunuşunu çeker.

    Bir gün alınamazsa atlanır ve sayılır; sonraki çalıştırmada yeniden denenir. Döndürür: özet sözlüğü.
    """
    gunler = [s[0] for s in conn.execute("""
        SELECT DISTINCT m.tarih FROM maclar m JOIN oyuncu_mac om USING (mac_id)
        WHERE m.durum = 'oynandi' AND m.tarih >= ? AND om.dakika > 0
          AND NOT EXISTS (SELECT 1 FROM takip_mac t JOIN maclar m2 USING (mac_id) WHERE m2.tarih = m.tarih)
        ORDER BY m.tarih""", (tarihten or config.SEZON_BASLANGIC,))]
    alinan, alinamayan, yazilan = 0, [], 0
    for sira, gun in enumerate(gunler, 1):
        try:
            veri = takip_kaynagi().takip_gunu(gun)
        except KaynakHatasi as e:
            log.warning("Takip verisi alınamadı (%s): %s", gun, e)
            alinamayan.append(gun)
            continue
        oynayan = {s["oyuncu_id"]: s["mac_id"] for s in conn.execute(
            "SELECT om.oyuncu_id, om.mac_id FROM oyuncu_mac om JOIN maclar m USING (mac_id) WHERE m.tarih = ? AND om.dakika > 0", (gun,))}
        yazilan += veritabani.yaz(conn, "takip_mac", [{"oyuncu_id": kimlik, "mac_id": oynayan[kimlik], **degerler}
                                                       for kimlik, degerler in veri.items() if kimlik in oynayan])
        alinan += 1
        if sira % 10 == 0 or sira == len(gunler):
            log.info("Takip verisi: %d/%d gün işlendi", sira, len(gunler))
    kapsam = conn.execute("""
        SELECT COUNT(*) AS satir, COUNT(t.oyuncu_id) AS takipli FROM oyuncu_mac om
        LEFT JOIN takip_mac t ON t.oyuncu_id = om.oyuncu_id AND t.mac_id = om.mac_id WHERE om.dakika > 0""").fetchone()
    ozet = {"gun": len(gunler), "alinan": alinan, "alinamayan": alinamayan, "yazilan": yazilan,
            "satir": kapsam["satir"], "takipli": kapsam["takipli"]}
    log.info("Takip verisi: %d günün %d tanesi alındı, %d satır yazıldı; oyuncu-maç satırlarının %%%.1f'inde takip verisi var%s",
             ozet["gun"], alinan, yazilan, 100 * kapsam["takipli"] / max(kapsam["satir"], 1),
             f"; ALINAMAYAN GÜNLER: {', '.join(alinamayan)}" if alinamayan else "")
    return ozet


def hakemleri_yukle(conn):
    """Oynanmış maçların hakemlerini kutu skorundan yazar (maç başına bir istek). Döndürür: (işlenen maç, alınamayan maç)."""
    maclar = [s[0] for s in conn.execute("""
        SELECT m.mac_id FROM maclar m WHERE m.durum = 'oynandi'
          AND NOT EXISTS (SELECT 1 FROM hakem_mac h WHERE h.mac_id = m.mac_id AND h.kaynak = 'kutu_skoru') ORDER BY m.tarih, m.mac_id""")]
    islenen, alinamayan = 0, 0
    for sira, mac_id in enumerate(maclar, 1):
        try:
            hakemler = nba_stats.mac_hakemleri(mac_id)
        except KaynakHatasi as e:
            log.warning("Hakemler alınamadı: %s", e)
            alinamayan += 1
            continue
        veritabani.yaz(conn, "hakemler", [{"hakem_id": h["hakem_id"], "isim": h["isim"], "forma_no": h["forma_no"]} for h in hakemler])
        veritabani.goruntu_yaz(conn, "hakem_mac", {"mac_id": mac_id}, [{"hakem_id": h["hakem_id"], "gorev": h["gorev"], "kaynak": "kutu_skoru"} for h in hakemler])
        islenen += 1
        if sira % 50 == 0 or sira == len(maclar):
            log.info("Hakemler: %d/%d maç işlendi", sira, len(maclar))
    log.info("Hakemler: %d maçın hakemleri yazıldı, %d maçınki alınamadı", islenen, alinamayan)
    return islenen, alinamayan


def _takim_adlari(conn):
    """Atama sayfasındaki yazımla takım eşlemesi: {'memphis': takim_id, 'la lakers': ..., 'golden state': ...}"""
    adlar = {}
    for s in conn.execute("SELECT takim_id, isim FROM takimlar"):
        kelimeler = s["isim"].split()
        takma = " ".join(kelimeler[-2:]) if s["isim"].endswith("Trail Blazers") else kelimeler[-1]
        yer = s["isim"][: -len(takma)].strip()
        if yer in ("Los Angeles", "LA"):
            adlar[f"la {takma.lower()}"] = s["takim_id"]
            adlar[f"los angeles {takma.lower()}"] = s["takim_id"]
        else:
            adlar[yer.lower()] = s["takim_id"]
    return adlar


def atamalari_yukle(conn, tarih=None):
    """Günün hakem atamalarını sayfadan okur ve henüz oynanmamış maçlara yazar; özet döndürür.

    Sayfadaki tarih bugün değilse (atamalar henüz yayımlanmadıysa) hiçbir şey yazılmaz.
    """
    tarih = tarih or veritabani.abd_bugun()
    sayfa = nba_resmi.hakem_atamalari()
    ozet = {"tarih": tarih, "sayfa_tarihi": sayfa["tarih"], "sayfadaki_mac": len(sayfa["maclar"]), "eslesen_mac": 0,
            "hakem": 0, "taninmayan_hakemler": [], "eslesmeyen_maclar": [], "yayimlandi": sayfa["tarih"] == tarih}
    if not ozet["yayimlandi"]:
        log.info("Hakem atamaları: sayfa %s tarihli, bugün %s; atamalar henüz yayımlanmamış", sayfa["tarih"], tarih)
        return ozet
    adlar = _takim_adlari(conn)
    maclar = {(s["dep_takim_id"], s["ev_takim_id"]): s["mac_id"] for s in conn.execute(
        "SELECT mac_id, ev_takim_id, dep_takim_id FROM maclar WHERE tarih = ? AND durum = 'oynanacak'", (tarih,))}
    hakemler = conn.execute("SELECT hakem_id, isim, forma_no FROM hakemler").fetchall()
    sade = lambda metin: " ".join(metin.lower().replace(".", "").split())
    for m in sayfa["maclar"]:
        dep, _, ev = m["mac"].partition("@")
        mac_id = maclar.get((adlar.get(sade(dep)), adlar.get(sade(ev))))
        if mac_id is None:
            ozet["eslesmeyen_maclar"].append(m["mac"])
            continue
        satirlar = []
        for isim, forma_no, gorev in m["hakemler"]:
            # Forma numarası ve isimle eşle; forma numarası değişmişse yalnızca isimle.
            aday = [h for h in hakemler if sade(h["isim"]) == sade(isim)]
            aday = [h for h in aday if h["forma_no"] == forma_no] or aday
            if len(aday) != 1:
                ozet["taninmayan_hakemler"].append(f"{isim} (#{forma_no})")
                continue
            satirlar.append({"hakem_id": aday[0]["hakem_id"], "gorev": gorev, "kaynak": "atama"})
        veritabani.goruntu_yaz(conn, "hakem_mac", {"mac_id": mac_id}, satirlar) if satirlar else None
        ozet["eslesen_mac"] += 1
        ozet["hakem"] += len(satirlar)
    log.info("Hakem atamaları (%s): sayfadaki %d maçın %d tanesi eşleşti, %d hakem yazıldı; tanınmayan hakem: %s; eşleşmeyen maç: %s",
             tarih, ozet["sayfadaki_mac"], ozet["eslesen_mac"], ozet["hakem"],
             ", ".join(ozet["taninmayan_hakemler"]) or "-", ", ".join(ozet["eslesmeyen_maclar"]) or "-")
    return ozet


def ilk_besleri_yukle(conn, tarih=None):
    """Günün maçları için ilk beş beslemesini yazar (maç başına görüntü yenilenir); özet döndürür."""
    tarih = tarih or veritabani.abd_bugun()
    maclar = {s[0] for s in conn.execute("SELECT mac_id FROM maclar WHERE tarih = ?", (tarih,))}
    simdi = veritabani.simdi_utc()
    mac_bazinda = {}
    for k in nba_stats.gunluk_ilk_besler(tarih):
        if k["mac_id"] in maclar:
            mac_bazinda.setdefault(k["mac_id"], []).append({key: k[key] for key in ("oyuncu_id", "takim_id", "pozisyon", "durum", "kadro_durumu")} | {"cekim_zamani": simdi})
    for mac_id, satirlar in mac_bazinda.items():
        veritabani.goruntu_yaz(conn, "ilk_bes_beklenti", {"mac_id": mac_id}, satirlar)
    tum = [s for satirlar in mac_bazinda.values() for s in satirlar]
    ozet = {"mac": len(mac_bazinda), "gunun_maci": len(maclar), "ilk_bes": sum(1 for s in tum if s["pozisyon"]),
            "kesin": sum(1 for s in tum if s["pozisyon"] and s["durum"] == "Confirmed"), "kadro_disi": sum(1 for s in tum if s["kadro_durumu"] != "Active")}
    log.info("İlk beşler (%s): %d maçın %d tanesinde ilk beş var; %d oyuncunun %d tanesi kesin; kadro dışı bildirilen %d",
             tarih, ozet["gunun_maci"], ozet["mac"], ozet["ilk_bes"], ozet["kesin"], ozet["kadro_disi"])
    return ozet


def _espn_mac_eslemesi(conn, tarih):
    """O günün ESPN maçlarını bizim maç kimliklerimizle eşler: [(mac_id, ESPN maç kaydı), ...]"""
    takim = {s["espn_id"]: s["takim_id"] for s in conn.execute("SELECT espn_id, takim_id FROM takimlar WHERE espn_id IS NOT NULL")}
    maclar = {(s["ev_takim_id"], s["dep_takim_id"]): s["mac_id"] for s in conn.execute("SELECT mac_id, ev_takim_id, dep_takim_id FROM maclar WHERE tarih = ?", (tarih,))}
    eslesen = []
    for m in espn.skor_tablosu(tarih):
        mac_id = maclar.get((takim.get(m["ev_espn_id"]), takim.get(m["dep_espn_id"])))
        if mac_id:
            eslesen.append((mac_id, m))
    return eslesen, len(maclar)


def oranlari_yukle(conn, tarih=None):
    """Günün maçlarının handikap ve toplam sayı çizgilerini 'guncel' olarak yazar. Döndürür: (oranı gelen maç, günün maç sayısı)."""
    tarih = tarih or veritabani.abd_bugun()
    eslesen, mac_sayisi = _espn_mac_eslemesi(conn, tarih)
    simdi = veritabani.simdi_utc()
    satirlar = [{"mac_id": mac_id, "tur": "guncel", "cekim_zamani": simdi, "handikap": m["handikap"], "toplam": m["toplam"],
                 "saglayici": m["saglayici"], "espn_mac_id": m["espn_mac_id"]}
                for mac_id, m in eslesen if m["handikap"] is not None or m["toplam"] is not None]
    veritabani.yaz(conn, "oranlar", satirlar)
    log.info("Oranlar (%s): %d maçın %d tanesinde oran var", tarih, mac_sayisi, len(satirlar))
    return len(satirlar), mac_sayisi


def oyuncu_baremlerini_yukle(conn, tarih=None, yeniden=False):
    """Günün henüz başlamamış maçlarında bahis sitesinin oyuncu baremlerini (ESPN üzerinden) oyuncu_barem tablosuna yazar.

    Günde bir kez, akşam çalıştırmasında çekilir: baremi daha önce yazılmış maç yeniden çekilmez (yeniden=True ise çekilir).
    Veri şimdilik yalnızca biriktirilir; tahminlerde ve günün seçimlerinde kullanılmaz.
    Döndürür: (baremi yazılan maç, yazılan satır, oyuncular tablosunda bulunamayan oyuncu sayısı)
    """
    tarih = tarih or veritabani.abd_bugun()
    simdi = veritabani.simdi_utc()
    baslamamis = {s[0] for s in conn.execute("SELECT mac_id FROM maclar WHERE tarih = ? AND durum = 'oynanacak' AND baslama_utc > ?",
                                             (tarih, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))}
    var = {s[0] for s in conn.execute("SELECT DISTINCT mac_id FROM oyuncu_barem WHERE tarih = ?", (tarih,))}
    if not (baslamamis if yeniden else baslamamis - var):
        log.info("Oyuncu baremleri (%s): çekilecek maç yok (başlamamış %d, daha önce yazılmış %d)", tarih, len(baslamamis), len(var))
        return 0, 0, 0                      # kaynağa hiç gidilmez
    eslesen, _ = _espn_mac_eslemesi(conn, tarih)
    oyuncu = {s["espn_id"]: s["oyuncu_id"] for s in conn.execute("SELECT espn_id, oyuncu_id FROM oyuncular WHERE espn_id IS NOT NULL")}
    mac_sayisi, satir_sayisi, bulunamayan, alinamayan = 0, 0, set(), []
    for mac_id, m in eslesen:
        if mac_id not in baslamamis or (mac_id in var and not yeniden):
            continue
        time.sleep(config.ESPN_BEKLEME_SN)
        try:
            saglayici, satirlar, atlanan = espn.oyuncu_baremleri(m["espn_mac_id"])
        except KaynakHatasi as e:              # bir maçın alınamaması ötekileri durdurmaz; adım sonunda hata olarak bildirilir
            log.warning("Oyuncu baremleri: maç %s alınamadı: %s", mac_id, e)
            alinamayan.append(mac_id)
            continue
        if atlanan:
            log.warning("Oyuncu baremleri: maç %s, beklenen iki kaydı olmayan %d oyuncu-pazar çifti atlandı", mac_id, atlanan)
        if not satirlar:
            continue
        bulunamayan |= {s["espn_oyuncu_id"] for s in satirlar if s["espn_oyuncu_id"] not in oyuncu}
        sabit = {"mac_id": mac_id, "tarih": tarih, "saglayici": saglayici, "cekim_zamani": simdi}
        satir_sayisi += veritabani.goruntu_yaz(conn, "oyuncu_barem", {"mac_id": mac_id},
                                                [{**s, **sabit, "oyuncu_id": oyuncu.get(s["espn_oyuncu_id"])} for s in satirlar])
        mac_sayisi += 1
    log.info("Oyuncu baremleri (%s): %d maçta %d barem yazıldı; başlamamış maç %d, daha önce yazılmış %d, eşlenemeyen oyuncu %d",
             tarih, mac_sayisi, satir_sayisi, len(baslamamis), len(var & baslamamis) if not yeniden else 0, len(bulunamayan))
    if alinamayan:
        raise KaynakHatasi(f"Oyuncu baremleri: {len(alinamayan)} maç alınamadı ({', '.join(alinamayan)}); {mac_sayisi} maç yazıldı")
    return mac_sayisi, satir_sayisi, len(bulunamayan)


def gecmis_oranlari_yukle(conn):
    """Oynanmış ve kapanış çizgisi henüz yazılmamış maçların oranlarını çeker (maç başına bir istek). Döndürür: (yazılan, oransız kalan)."""
    gunler = [s[0] for s in conn.execute("""
        SELECT DISTINCT m.tarih FROM maclar m
        WHERE m.durum = 'oynandi' AND NOT EXISTS (SELECT 1 FROM oranlar o WHERE o.mac_id = m.mac_id AND o.tur = 'kapanis') ORDER BY m.tarih""")]
    var = {s[0] for s in conn.execute("SELECT mac_id FROM oranlar WHERE tur = 'kapanis'")}
    yazilan, oransiz = 0, 0
    for gun in gunler:
        eslesen, _ = _espn_mac_eslemesi(conn, gun)
        satirlar = []
        for mac_id, m in eslesen:
            if mac_id in var:
                continue
            time.sleep(config.ESPN_BEKLEME_SN)
            o = espn.mac_orani(m["espn_mac_id"])
            if o["handikap"] is None and o["toplam"] is None:
                oransiz += 1
                continue
            satirlar.append({"mac_id": mac_id, "tur": "kapanis", "cekim_zamani": veritabani.simdi_utc(), "handikap": o["handikap"],
                             "toplam": o["toplam"], "saglayici": o["saglayici"], "espn_mac_id": m["espn_mac_id"]})
        yazilan += veritabani.yaz(conn, "oranlar", satirlar)
    log.info("Geçmiş oranlar: %d maçın kapanış çizgisi yazıldı, %d maçta oran bulunamadı", yazilan, oransiz)
    return yazilan, oransiz


def sakatliklari_yukle(conn):
    """ESPN sakatlık listesini bugünün görüntüsü olarak yazar; özetini döndürür.

    Aynı gün yeniden çalışırsa o günün görüntüsü yenisiyle değişir, çoğalmaz.
    """
    kayitlar = espn.sakatliklar()
    takim_id = {s["espn_id"]: s["takim_id"] for s in conn.execute("SELECT espn_id, takim_id FROM takimlar WHERE espn_id IS NOT NULL")}
    if len(takim_id) != 30:
        raise KaynakHatasi("takimlar tablosunda ESPN kimlikleri eksik; önce takımlar yüklenmeli")
    # NBA oyuncu kimliği, ESPN kimliği eşlenmiş oyuncular için dolar (eşleme 4. adımın işi).
    oyuncu_id = {s["espn_id"]: s["oyuncu_id"] for s in conn.execute("SELECT espn_id, oyuncu_id FROM oyuncular WHERE espn_id IS NOT NULL")}

    simdi = veritabani.simdi_utc()
    satirlar = {}
    for k in kayitlar:
        if k["espn_takim_id"] not in takim_id:
            raise KaynakHatasi(f"ESPN sakatlık: bilinmeyen takım kimliği {k['espn_takim_id']} ({k['isim']})")
        takim = takim_id[k["espn_takim_id"]]
        anahtar = str(k["espn_oyuncu_id"]) if k["espn_oyuncu_id"] else f"{k['isim']}|{takim}"
        satirlar[anahtar] = {
            "oyuncu_anahtari": anahtar,
            "cekim_zamani": simdi,
            "oyuncu_id": oyuncu_id.get(k["espn_oyuncu_id"]),
            "isim": k["isim"],
            "takim_id": takim,
            "durum": k["durum"],
            "aciklama": k["aciklama"],
            "tahmini_donus": k["tahmini_donus"],
        }
    tarih = veritabani.abd_bugun()
    veritabani.goruntu_yaz(conn, "sakatliklar", {"kaynak": "espn", "cekim_tarihi": tarih}, satirlar.values())
    ozet = sakatlik_ozeti(conn, tarih)
    log.info("Sakatlık (ESPN, %s): 30 takımın %d tanesinden %d kayıt geldi; veri yok: %s",
             tarih, 30 - len(ozet["veri_yok"]), ozet["kayit"], ", ".join(ozet["veri_yok"]) or "-")
    return ozet


def resmi_sakatliklari_yukle(conn, tarih=None):
    """NBA resmi sakatlık raporunun bugünün maçlarına ait kayıtlarını günün görüntüsü olarak yazar; özet döndürür.

    Oyuncular isim + takım üzerinden NBA kimliğiyle eşlenir. Raporu henüz vermemiş takım tek bir
    'BILDIRILMEDI' satırıyla yazılır: o takım için "listede yok", "sağlam" anlamına gelmez.
    """
    tarih = tarih or veritabani.abd_bugun()
    rapor = nba_sakatlik.resmi_rapor()
    takimlar = conn.execute("SELECT takim_id, isim FROM takimlar").fetchall()

    def takim_bul(ad):
        # Rapor "LA Clippers" yazar, bizde "Los Angeles Clippers": takma ad (son sözcükler) üzerinden eşle.
        eslesen = [t["takim_id"] for t in takimlar if ad.split()[-1] == t["isim"].split()[-1]]
        if len(eslesen) != 1:
            raise KaynakHatasi(f"resmi sakatlık raporu: takım eşleşmedi: {ad!r}")
        return eslesen[0]

    oyuncular = {}
    for s in conn.execute("SELECT oyuncu_id, isim, takim_id FROM oyuncular WHERE takim_id IS NOT NULL"):
        oyuncular.setdefault((s["takim_id"], kadro.sade_isim(s["isim"])), []).append(s["oyuncu_id"])
    simdi = veritabani.simdi_utc()
    satirlar, eslesmeyen = {}, []
    for k in rapor["kayitlar"]:
        if k["tarih"] != tarih:
            continue
        takim_id = takim_bul(k["takim"])
        aday = oyuncular.get((takim_id, kadro.sade_isim(k["isim"])), [])
        if len(aday) != 1:
            eslesmeyen.append(f"{k['isim']} ({k['takim']})")
        satirlar[f"{k['isim']}|{takim_id}"] = {
            "oyuncu_anahtari": f"{k['isim']}|{takim_id}", "cekim_zamani": simdi, "oyuncu_id": aday[0] if len(aday) == 1 else None,
            "isim": k["isim"], "takim_id": takim_id, "durum": k["durum"], "aciklama": k["neden"], "tahmini_donus": None}
    bildirmeyen = sorted({takim_bul(takim) for gun, takim in rapor["bildirmeyen"] if gun == tarih})
    for takim_id in bildirmeyen:
        satirlar[f"-|{takim_id}"] = {"oyuncu_anahtari": f"-|{takim_id}", "cekim_zamani": simdi, "oyuncu_id": None, "isim": "(rapor henüz verilmedi)",
                                     "takim_id": takim_id, "durum": "BILDIRILMEDI", "aciklama": None, "tahmini_donus": None}
    veritabani.goruntu_yaz(conn, "sakatliklar", {"kaynak": "nba_resmi", "cekim_tarihi": tarih}, satirlar.values())
    ozet = {"tarih": tarih, "rapor_zamani": rapor["rapor_zamani"], "kayit": len(satirlar) - len(bildirmeyen),
            "bildirmeyen_takim": len(bildirmeyen), "eslesmeyen": eslesmeyen}
    log.info("Resmi sakatlık raporu (%s; rapor %s): %d kayıt, raporu henüz vermeyen %d takım; NBA kimliğiyle eşleşmeyen: %s",
             tarih, rapor["rapor_zamani"], ozet["kayit"], len(bildirmeyen), ", ".join(eslesmeyen) or "-")
    return ozet


def sakatlik_ozeti(conn, tarih, kaynak="espn"):
    """Bir günün sakatlık görüntüsü: takım başına kayıt sayısı ve kayıt gelmeyen takımlar.

    Kayıt gelmeyen takım "sakatı yok" değil, "veri yok" sayılır.
    """
    takimlar = conn.execute("""
        SELECT t.kisaltma, COUNT(s.oyuncu_anahtari) AS kayit,
               COALESCE(SUM(s.durum = 'Out'), 0) AS disarida,
               COALESCE(SUM(s.durum = 'Day-To-Day'), 0) AS gunluk
        FROM takimlar t
        LEFT JOIN sakatliklar s ON s.takim_id = t.takim_id AND s.kaynak = ? AND s.cekim_tarihi = ?
        GROUP BY t.takim_id ORDER BY t.kisaltma""", (kaynak, tarih)).fetchall()
    durumlar = {s[0]: s[1] for s in conn.execute(
        "SELECT durum, COUNT(*) FROM sakatliklar WHERE kaynak = ? AND cekim_tarihi = ? GROUP BY durum", (kaynak, tarih))}
    return {
        "tarih": tarih,
        "kayit": sum(t["kayit"] for t in takimlar),
        "durumlar": durumlar,
        "takimlar": [dict(t) for t in takimlar],
        "veri_yok": [t["kisaltma"] for t in takimlar if t["kayit"] == 0],
        "eslesmeyen_oyuncu": conn.execute(
            "SELECT COUNT(*) FROM sakatliklar WHERE kaynak = ? AND cekim_tarihi = ? AND oyuncu_id IS NULL", (kaynak, tarih)).fetchone()[0],
    }


def sakatlik_raporu_yaz(ozet):
    print(f"\n=== Sakatlık raporu (ESPN, {ozet['tarih']}) ===")
    print(f"30 takımın {30 - len(ozet['veri_yok'])} tanesinden kayıt geldi; toplam {ozet['kayit']} kayıt: "
          + ", ".join(f"{d} {n}" for d, n in sorted(ozet["durumlar"].items(), key=lambda x: -x[1])))
    print("Kayıt gelmeyen takımlar (\"veri yok\" sayılır): " + (", ".join(ozet["veri_yok"]) or "-"))
    print("Takım başına kayıt (Out / Day-To-Day):")
    for i in range(0, 30, 6):
        print("  " + "   ".join(
            f"{t['kisaltma']} " + (f"{t['disarida']}/{t['gunluk']}" if t["kayit"] else "yok") for t in ozet["takimlar"][i:i + 6]))
    print(f"NBA kimliğiyle henüz eşlenmemiş kayıt: {ozet['eslesmeyen_oyuncu']} (kadro adımı çalışınca bağlanır)")


ADIMLAR = {
    "takimlar": takimlari_yukle,
    "fikstur": fiksturu_yukle,
    "mac_kayitlari": lambda conn: mac_kayitlarini_yukle(conn, tarihten=config.SEZON_BASLANGIC),
    "takim_mac": lambda conn: takim_kayitlarini_yukle(conn, tarihten=config.SEZON_BASLANGIC),
    "tempo_dogrula": tempo_karsilastir,
    "kullanim": kullanim_oranlarini_yaz,
    "oranlar": oranlari_yukle,
    "oyuncu_baremleri": lambda conn: oyuncu_baremlerini_yukle(conn, yeniden=True),      # elle çalıştırma: yazılmış olsa da yeniden çeker
    "takip": takip_verisini_yukle,
    "hakemler": hakemleri_yukle,
    "atamalar": atamalari_yukle,
    "gecmis_oranlar": gecmis_oranlari_yukle,
    "gecen_sezon": gecen_sezonu_yukle,
    "sakatlik": sakatliklari_yukle,
    "resmi_sakatlik": resmi_sakatliklari_yukle,
    "ilk_besler": ilk_besleri_yukle,
    "kadro": kadro.kadrolari_yukle,
}


def main(argv):
    if len(argv) != 1 or argv[0] not in ADIMLAR:
        print(f"Kullanım: python yukle.py <{' | '.join(ADIMLAR)}>")
        return 2
    ad = argv[0]
    log_kur("yukle")
    conn = veritabani.baglan()
    try:
        veritabani.sema_kur(conn)
        sonuc = adim(conn, f"yukle-{uuid.uuid4().hex[:8]}", ad, lambda: ADIMLAR[ad](conn))
        if ad == "sakatlik":
            sakatlik_raporu_yaz(sonuc)
        elif ad == "kadro":
            kadro.rapor_yaz(sonuc)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
