"""Kadro ve pozisyon eşlemesi (PLAN adım 4).

- Oyuncuların güncel takımı NBA'in oyuncu listesinden gelir (takas, yeni oyuncu).
- Beşli pozisyon (PG/SG/SF/PF/C) ESPN derinlik çizelgesinden gelir.
- NBA ve ESPN kimlikleri farklıdır: oyuncular sadeleştirilmiş isim + takım üzerinden
  eşlenir. Bir kez eşlenen oyuncu sonraki günlerde ESPN kimliğiyle tanınır.
- pozisyon_duzeltme.csv dosyasındaki pozisyon, ESPN'den geleni ezer.
"""
import csv
import logging
import re
import time
import unicodedata
from collections import Counter, defaultdict

import config
import veritabani
from kaynak import KaynakHatasi, espn, mac_kaynagi

log = logging.getLogger("kadro")

_ISIM_EKLERI = {"jr", "sr", "ii", "iii", "iv", "v"}


def sade_isim(isim):
    """Karşılaştırma için: küçük harf, aksansız, noktalamasız, Jr./III ekleri atılmış."""
    s = unicodedata.normalize("NFKD", isim).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(p for p in s.split() if p not in _ISIM_EKLERI)


def oyuncu_esle(espn_oyunculari, nba_oyunculari, bilinen):
    """ESPN oyuncularını NBA oyuncularıyla eşler.

    espn_oyunculari: {espn_id: {'isim', 'takim_id'}}   (takim_id NBA takım kimliği)
    nba_oyunculari:  {oyuncu_id: {'isim', 'takim_id'}}
    bilinen:         {espn_id: oyuncu_id}  daha önce yapılmış eşlemeler

    Sıra: (1) bilinen ESPN kimliği, (2) aynı takımda aynı isim, (3) ligde tek olan
    aynı isim (iki kaynağın takım bilgisi farklıysa).
    Döndürür: (eslesme {espn_id: oyuncu_id}, takimi_farkli [espn_id], eslesmeyen [espn_id])
    """
    isimden = defaultdict(list)
    for oyuncu_id, o in nba_oyunculari.items():
        isimden[sade_isim(o["isim"])].append(oyuncu_id)

    eslesme, takimi_farkli, eslesmeyen = {}, [], []
    for espn_id, e in espn_oyunculari.items():
        if bilinen.get(espn_id) in nba_oyunculari:
            eslesme[espn_id] = bilinen[espn_id]
            continue
        adaylar = isimden.get(sade_isim(e["isim"]), [])
        ayni_takim = [a for a in adaylar if nba_oyunculari[a]["takim_id"] == e["takim_id"]]
        if len(ayni_takim) == 1:
            eslesme[espn_id] = ayni_takim[0]
        elif len(adaylar) == 1:
            eslesme[espn_id] = adaylar[0]
            takimi_farkli.append(espn_id)
        else:
            eslesmeyen.append(espn_id)

    # Bir NBA oyuncusuna iki ESPN oyuncusu düşmemeli.
    cift = [o for o, n in Counter(eslesme.values()).items() if n > 1]
    if cift:
        raise KaynakHatasi(f"Birden fazla ESPN oyuncusu aynı NBA oyuncusuyla eşleşti: {cift}")
    return eslesme, takimi_farkli, eslesmeyen


def duzeltmeleri_oku(yol=None):
    """pozisyon_duzeltme.csv -> {oyuncu_id: pozisyon}. Dosya yoksa boş sözlük."""
    yol = yol or config.POZISYON_DUZELTME_YOLU
    if not yol.exists():
        return {}
    duzeltme = {}
    with open(yol, encoding="utf-8-sig", newline="") as f:
        okuyucu = csv.DictReader(f)
        if not {"oyuncu_id", "pozisyon"} <= set(okuyucu.fieldnames or []):
            raise ValueError(f"{yol.name}: 'oyuncu_id' ve 'pozisyon' sütunları olmalı")
        for satir_no, s in enumerate(okuyucu, 2):
            if not (s["oyuncu_id"] or "").strip():
                continue
            pozisyon = (s["pozisyon"] or "").strip().upper()
            if not s["oyuncu_id"].strip().isdigit() or pozisyon not in config.POZISYONLAR:
                raise ValueError(f"{yol.name} satır {satir_no}: geçersiz kayıt {dict(s)}")
            duzeltme[int(s["oyuncu_id"])] = pozisyon
    return duzeltme


def kadrolari_yukle(conn):
    """Kadroları ve pozisyonları günceller, sakatlık kayıtlarını oyunculara bağlar; özet döndürür."""
    simdi = veritabani.simdi_utc()

    # 1) NBA oyuncu listesi: güncel takım ve aktiflik.
    nba_listesi = mac_kaynagi().oyuncu_listesi()
    veritabani.yaz(conn, "oyuncular", [
        {**o, "aktif": int(o["takim_id"] is not None), "guncelleme": simdi} for o in nba_listesi
    ])
    nba = {o["oyuncu_id"]: o for o in nba_listesi}
    with conn:  # listede artık olmayan eski kayıtlar
        conn.execute(
            f"UPDATE oyuncular SET aktif = 0, takim_id = NULL WHERE oyuncu_id NOT IN ({','.join('?' * len(nba))})", tuple(nba))

    # 2) ESPN kadroları ve derinlik çizelgeleri.
    takimlar = conn.execute("SELECT takim_id, kisaltma, espn_id FROM takimlar WHERE espn_id IS NOT NULL ORDER BY kisaltma").fetchall()
    if len(takimlar) != 30:
        raise KaynakHatasi("takimlar tablosunda ESPN kimlikleri eksik; önce takımlar yüklenmeli")
    espn_oyunculari, pozisyon = {}, {}
    for t in takimlar:
        for o in espn.kadro(t["espn_id"]):
            espn_oyunculari[o["espn_oyuncu_id"]] = {"isim": o["isim"], "takim_id": t["takim_id"]}
        time.sleep(config.ESPN_BEKLEME_SN)
        pozisyon.update(espn.derinlik(t["espn_id"]))
        time.sleep(config.ESPN_BEKLEME_SN)

    # 3) Kimlik eşlemesi.
    bilinen = {s["espn_id"]: s["oyuncu_id"] for s in conn.execute("SELECT espn_id, oyuncu_id FROM oyuncular WHERE espn_id IS NOT NULL")}
    eslesme, takimi_farkli, eslesmeyen = oyuncu_esle(espn_oyunculari, nba, bilinen)
    yeni = [e for e in eslesme if e not in bilinen]
    veritabani.yaz(conn, "oyuncular", [
        {"oyuncu_id": eslesme[e], "isim": nba[eslesme[e]]["isim"], "espn_id": e} for e in yeni
    ])

    # 4) Pozisyonlar: önce ESPN derinlik çizelgesi, üstüne elle düzeltmeler.
    #    Yeni pozisyonu bulunmayan oyuncunun eski pozisyonuna dokunulmaz.
    duzeltme = duzeltmeleri_oku()
    bilinmeyen = sorted(set(duzeltme) - set(nba))
    if bilinmeyen:
        raise ValueError(f"{config.POZISYON_DUZELTME_YOLU.name}: oyuncu listesinde olmayan kimlikler: {bilinmeyen}")
    satirlar = {
        eslesme[e]: {"oyuncu_id": eslesme[e], "isim": nba[eslesme[e]]["isim"], "pozisyon": p, "pozisyon_kaynagi": "espn_derinlik"}
        for e, (p, _) in pozisyon.items() if e in eslesme
    }
    for oyuncu_id, p in duzeltme.items():
        satirlar[oyuncu_id] = {"oyuncu_id": oyuncu_id, "isim": nba[oyuncu_id]["isim"], "pozisyon": p, "pozisyon_kaynagi": "elle_duzeltme"}
    veritabani.yaz(conn, "oyuncular", satirlar.values())

    # 5) Sakatlık kayıtlarını NBA kimliğine bağla.
    with conn:
        conn.execute("""
            UPDATE sakatliklar SET oyuncu_id = (SELECT oyuncu_id FROM oyuncular WHERE espn_id = CAST(sakatliklar.oyuncu_anahtari AS INTEGER))
            WHERE kaynak = 'espn' AND oyuncu_id IS NULL""")

    ozet = kadro_ozeti(conn)
    ozet.update({
        "espn_kadro": len(espn_oyunculari),
        "yeni_eslesme": len(yeni),
        "takimi_farkli": sorted(espn_oyunculari[e]["isim"] for e in takimi_farkli),
        "eslesmeyen_espn": sorted(espn_oyunculari[e]["isim"] for e in eslesmeyen),
        "elle_duzeltme": len(duzeltme),
    })
    log.info("Kadro: aktif %d oyuncunun %d tanesinin pozisyonu var (%%%.1f); ESPN ile eşleşmeyen %d",
             ozet["aktif"], ozet["aktif_pozisyonlu"], ozet["aktif_oran"], len(ozet["eslesmeyen_espn"]))
    return ozet


def kadro_ozeti(conn):
    """Pozisyon kapsamı: aktif oyuncular, bu sezon oynayanlar ve oynanan dakikalar üzerinden."""
    tek = lambda sql: conn.execute(sql).fetchone()[0]
    aktif = tek("SELECT COUNT(*) FROM oyuncular WHERE aktif = 1")
    aktif_pozisyonlu = tek("SELECT COUNT(*) FROM oyuncular WHERE aktif = 1 AND pozisyon IS NOT NULL")
    dakika = conn.execute("""
        SELECT SUM(om.dakika) AS toplam, SUM(CASE WHEN o.pozisyon IS NOT NULL THEN om.dakika END) AS pozisyonlu,
               COUNT(DISTINCT om.oyuncu_id) AS oynayan,
               COUNT(DISTINCT CASE WHEN o.pozisyon IS NOT NULL THEN om.oyuncu_id END) AS oynayan_pozisyonlu
        FROM oyuncu_mac om JOIN oyuncular o USING (oyuncu_id)""").fetchone()
    return {
        "aktif": aktif,
        "aktif_pozisyonlu": aktif_pozisyonlu,
        "aktif_oran": 100 * aktif_pozisyonlu / aktif if aktif else 0.0,
        "oynayan": dakika["oynayan"],
        "oynayan_pozisyonlu": dakika["oynayan_pozisyonlu"],
        "dakika_orani": 100 * (dakika["pozisyonlu"] or 0) / dakika["toplam"] if dakika["toplam"] else 0.0,
        "dagilim": [dict(s) for s in conn.execute("""
            SELECT o.pozisyon, COUNT(DISTINCT o.oyuncu_id) AS oyuncu, ROUND(COALESCE(SUM(om.dakika), 0)) AS dakika
            FROM oyuncular o LEFT JOIN oyuncu_mac om USING (oyuncu_id)
            WHERE o.pozisyon IS NOT NULL GROUP BY o.pozisyon
            ORDER BY CASE o.pozisyon WHEN 'PG' THEN 1 WHEN 'SG' THEN 2 WHEN 'SF' THEN 3 WHEN 'PF' THEN 4 ELSE 5 END""")],
        "pozisyonsuz": [dict(s) for s in conn.execute("""
            SELECT o.oyuncu_id, o.isim, COALESCE(t.kisaltma, '-') AS takim, o.aktif, o.espn_id IS NOT NULL AS eslesti,
                   ROUND(COALESCE(SUM(om.dakika), 0)) AS dakika
            FROM oyuncular o LEFT JOIN takimlar t USING (takim_id) LEFT JOIN oyuncu_mac om USING (oyuncu_id)
            WHERE o.pozisyon IS NULL GROUP BY o.oyuncu_id
            HAVING o.aktif = 1 OR dakika > 0 ORDER BY dakika DESC, o.isim""")],
        "sakatlik_eslesmeyen": [dict(s) for s in conn.execute("""
            SELECT s.isim, t.kisaltma AS takim FROM sakatliklar s JOIN takimlar t USING (takim_id)
            WHERE s.oyuncu_id IS NULL AND s.cekim_tarihi = (SELECT MAX(cekim_tarihi) FROM sakatliklar) ORDER BY s.isim""")],
    }


def rapor_metni(ozet):
    s = [f"=== Pozisyon eşlemesi raporu ({veritabani.abd_bugun()}) ==="]
    s.append(f"Aktif (bir takımın kadrosundaki) oyuncu: {ozet['aktif']}; beşli pozisyonu olan: {ozet['aktif_pozisyonlu']} (%{ozet['aktif_oran']:.1f})")
    s.append(f"Bu sezon oynayan oyuncu: {ozet['oynayan']}; pozisyonu olan: {ozet['oynayan_pozisyonlu']}; oynanan dakikaların %{ozet['dakika_orani']:.1f}'i pozisyona bağlı")
    if "espn_kadro" in ozet:
        s.append(f"ESPN kadrolarındaki oyuncu: {ozet['espn_kadro']}; bu çalıştırmada yeni eşlenen: {ozet['yeni_eslesme']}; elle düzeltme: {ozet['elle_duzeltme']}")
        s.append("ESPN'de olup NBA listesinde bulunamayan: " + (", ".join(ozet["eslesmeyen_espn"]) or "-"))
        s.append("İsimle eşlenen ama iki kaynakta takımı farklı olan (NBA'in takımı esas alındı): " + (", ".join(ozet["takimi_farkli"]) or "-"))
    s.append("\nPozisyon dağılımı:")
    toplam = sum(d["dakika"] for d in ozet["dagilim"]) or 1
    for d in ozet["dagilim"]:
        s.append(f"  {d['pozisyon']:<2}  {d['oyuncu']:>3} oyuncu   dakikaların %{100 * d['dakika'] / toplam:.1f}'i")
    s.append(f"\nPozisyonu olmayan oyuncular (aktif ya da bu sezon oynamış): {len(ozet['pozisyonsuz'])}")
    for p in ozet["pozisyonsuz"]:
        neden = "ESPN ile eşleşmedi" if not p["eslesti"] else "derinlik çizelgesinde yok"
        s.append(f"  {p['oyuncu_id']:>8}  {p['isim']:<24} {p['takim']:<4} {int(p['dakika']):>4} dk  {'aktif' if p['aktif'] else 'kadro dışı'}, {neden}")
    s.append(f"  (düzeltmek için {config.POZISYON_DUZELTME_YOLU.name} dosyasına oyuncu_id,isim,pozisyon satırı ekle)")
    s.append(f"\nNBA kimliğine bağlanamayan güncel sakatlık kaydı: {len(ozet['sakatlik_eslesmeyen'])}")
    for k in ozet["sakatlik_eslesmeyen"]:
        s.append(f"  {k['isim']} ({k['takim']})")
    return "\n".join(s)


def rapor_yaz(ozet):
    """Raporu ekrana ve raporlar/pozisyon_eslesme.txt dosyasına yazar."""
    metin = rapor_metni(ozet)
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "pozisyon_eslesme.txt").write_text(metin + "\n", encoding="utf-8")
    print("\n" + metin)
