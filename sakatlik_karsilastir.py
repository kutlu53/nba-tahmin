"""ESPN sakatlık listesi ile NBA resmi raporunun karşılaştırması (PLAN adım 10).

Günün maçlarındaki takımlar için iki kaynağın kayıtları oyuncu oyuncu yan yana getirilir ve
çelişenler işaretlenir:

- ÇELİŞKİ: bir kaynak "Out" diyor, diğeri demiyor. En önemlisi resmi raporda "Out" olup ESPN'de
  öyle görünmeyen oyuncudur: model ESPN listesini kullandığı için ona tahmin üretmiş olabilir.
- fark: daha hafif ayrılıklar (resmi raporda "Questionable" / "Doubtful" olup ESPN'de olmayan vb.).
- G Ligi kayıtları ("G League - Two-Way" vb.) sakatlık değildir; çelişki sayılmaz. Ancak o oyuncuya tahmin üretilmişse çelişki olarak işaretlenir.
- Takım resmi raporu henüz vermediyse ya da ESPN o takım için hiç kayıt döndürmediyse karşılaştırma yapılamaz; öyle yazılır.

Elle çalıştırma:  .venv\\Scripts\\python.exe sakatlik_karsilastir.py [YYYY-AA-GG]
"""
import sys

import pandas as pd

import config
import veritabani

BILDIRILMEDI = "BILDIRILMEDI"       # sakatliklar tablosunda: takım resmi raporu henüz vermedi
HAFIF = ("Available", "Probable")   # resmi raporda oynaması beklenen


def _hukum(espn, resmi, neden, takim_bildirdi, espn_veri_var, tahmin_var=False):
    """İki kaynağın durumuna göre işaret metni; uyumluysa boş."""
    # G Ligi'ne gönderilen oyuncu sakat değildir; ama ona tahmin ürettiysek bu da bir çelişkidir (bu gece oynamayacak).
    if resmi and neden and neden.startswith("G League") and not tahmin_var:
        return "G Ligi (sakatlık değil)" if espn != "Out" else ""
    if not takim_bildirdi:
        return "resmi rapor henüz verilmedi"
    if resmi == "Out" and espn != "Out":
        return "ÇELİŞKİ: resmi raporda Out; ESPN " + (espn if espn else ("listesinde yok" if espn_veri_var else "veri yok"))
    if espn == "Out" and resmi != "Out":
        return "ÇELİŞKİ: ESPN Out; resmi rapor " + (resmi if resmi else "listesinde yok")
    if resmi in ("Doubtful", "Questionable") and not espn:
        return f"fark: resmi raporda {resmi}; ESPN " + ("listesinde yok" if espn_veri_var else "veri yok")
    if espn == "Day-To-Day" and (resmi in HAFIF or not resmi):
        return "fark: ESPN Day-To-Day; resmi rapor " + (resmi if resmi else "listesinde yok")
    return ""


def karsilastir(conn, tarih=None):
    """Günün maçlarındaki takımlar için karşılaştırma tablosu; çelişkiler en üstte.

    Sütunlar: Takım, Oyuncu, ESPN, Resmi rapor, İşaret, Tahmin üretildi, ESPN açıklaması, Resmi neden.
    Resmi rapor o gün için hiç yazılmadıysa boş tablo döner.
    """
    tarih = tarih or veritabani.abd_bugun()
    takimlar = {s["takim_id"]: s["kisaltma"] for s in conn.execute("""
        SELECT DISTINCT t.takim_id, t.kisaltma FROM maclar m JOIN takimlar t ON t.takim_id IN (m.ev_takim_id, m.dep_takim_id) WHERE m.tarih = ?""", (tarih,))}
    kayitlar = conn.execute("SELECT kaynak, oyuncu_id, isim, takim_id, durum, aciklama FROM sakatliklar WHERE cekim_tarihi = ?", (tarih,)).fetchall()
    resmi = [k for k in kayitlar if k["kaynak"] == "nba_resmi"]
    if not resmi:
        return pd.DataFrame()
    bildirmeyen = {k["takim_id"] for k in resmi if k["durum"] == BILDIRILMEDI}
    espn_takimlari = {k["takim_id"] for k in kayitlar if k["kaynak"] == "espn"}
    tahmin_edilen = {s[0] for s in conn.execute("SELECT DISTINCT oyuncu_id FROM tahminler WHERE tur = 'canli' AND tarih = ?", (tarih,))}

    oyuncular = {}     # (takım, oyuncu kimliği ya da sadeleştirilmiş isim) -> satır
    for k in kayitlar:
        if k["takim_id"] not in takimlar or k["durum"] == BILDIRILMEDI:
            continue
        anahtar = (k["takim_id"], k["oyuncu_id"] if k["oyuncu_id"] is not None else k["isim"].lower())
        satir = oyuncular.setdefault(anahtar, {"takim_id": k["takim_id"], "oyuncu_id": k["oyuncu_id"], "isim": k["isim"],
                                               "espn": None, "resmi": None, "espn_aciklama": None, "neden": None})
        if k["kaynak"] == "espn":
            satir["espn"], satir["espn_aciklama"] = k["durum"], k["aciklama"]
        else:
            satir["resmi"], satir["neden"] = k["durum"], k["aciklama"]

    satirlar = []
    for s in oyuncular.values():
        isaret = _hukum(s["espn"], s["resmi"], s["neden"], s["takim_id"] not in bildirmeyen, s["takim_id"] in espn_takimlari,
                        s["oyuncu_id"] in tahmin_edilen)
        satirlar.append({
            "Takım": takimlar[s["takim_id"]], "Oyuncu": s["isim"], "ESPN": s["espn"] or "-", "Resmi rapor": s["resmi"] or "-", "İşaret": isaret,
            "Tahmin üretildi": "EVET" if s["oyuncu_id"] in tahmin_edilen else "",
            "ESPN açıklaması": s["espn_aciklama"], "Resmi neden": s["neden"],
        })
    for takim_id in sorted(bildirmeyen & set(takimlar)):
        satirlar.append({"Takım": takimlar[takim_id], "Oyuncu": "(takım raporu henüz vermedi)", "ESPN": "-", "Resmi rapor": "bildirilmedi",
                         "İşaret": "resmi rapor henüz verilmedi", "Tahmin üretildi": "", "ESPN açıklaması": None, "Resmi neden": None})
    df = pd.DataFrame(satirlar)
    if df.empty:
        return df
    oncelik = df["İşaret"].map(lambda x: 0 if x.startswith("ÇELİŞKİ") else 1 if x.startswith("fark") else 2 if x.startswith("resmi rapor henüz") else 3 if x else 4)
    return df.assign(_o=oncelik).sort_values(["_o", "Takım", "Oyuncu"]).drop(columns="_o").reset_index(drop=True)


def ozet_metni(df, tarih):
    if df.empty:
        return f"{tarih}: resmi sakatlık raporu kaydı yok; karşılaştırma yapılamadı."
    celiski, fark = df[df["İşaret"].str.startswith("ÇELİŞKİ")], df[df["İşaret"].str.startswith("fark")]
    s = [f"=== Sakatlık karşılaştırması: ESPN ve NBA resmi raporu ({tarih}) ===",
         f"Karşılaştırılan kayıt: {len(df)}; ÇELİŞKİ: {len(celiski)}; fark: {len(fark)}; uyumlu: {(df['İşaret'] == '').sum()}; "
         f"G Ligi: {df['İşaret'].str.startswith('G Ligi').sum()}; raporu henüz vermeyen takım: {(df['Resmi rapor'] == 'bildirilmedi').sum()}"]
    riskli = celiski[(celiski["Resmi rapor"] == "Out") & (celiski["Tahmin üretildi"] == "EVET")]
    s.append(f"Resmi raporda Out olduğu halde tahmin üretilmiş oyuncu: {len(riskli)}" + (": " + ", ".join(riskli["Oyuncu"]) if len(riskli) else ""))
    for baslik, parca in (("ÇELİŞKİLER", celiski), ("FARKLAR", fark)):
        if len(parca):
            s.append(f"\n{baslik}")
            for _, r in parca.iterrows():
                s.append(f"  {r['Takım']:<4} {r['Oyuncu'][:26]:<26} {r['İşaret']}" + ("   [tahmin üretildi]" if r["Tahmin üretildi"] else "")
                         + (f"   ({r['Resmi neden']})" if r["Resmi neden"] else ""))
    return "\n".join(s)


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    gun = sys.argv[1] if len(sys.argv) > 1 else veritabani.abd_bugun()
    baglanti = veritabani.baglan()
    metin = ozet_metni(karsilastir(baglanti, gun), gun)
    config.RAPOR_KLASORU.mkdir(exist_ok=True)
    (config.RAPOR_KLASORU / "sakatlik_karsilastirma.txt").write_text(metin + "\n", encoding="utf-8")
    print(metin)
    baglanti.close()
