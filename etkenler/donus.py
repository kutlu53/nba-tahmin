"""Sakatlıktan (uzun aradan) dönüş kısıtı (PLAN_EK bölüm 6, 4. halka): beklenen dakikayı düzeltir.

Oyuncu takımının üst üste 3 ya da daha fazla maçını kaçırdıktan sonraki ilk 2 maçta
daha az dakika alır. Azalma kendi verimizden öğrenilir (dönüş maçındaki dakika /
aradan önceki son maçların ortalaması) ve az örneklemde başlangıç değeri olan %15'e çekilir.
"""
import config
from etkenler import EtkenSonucu, kucuk_orneklem, veri_yok


def _takim_sirasi(baglam, k, takim_id):
    """Oyuncunun bu takımda oynadığı maçların, takımın maç listesindeki sıra numaraları ve dakikaları."""
    kt = k[k["takim_id"] == takim_id]
    dakika = dict(zip(kt["mac_id"], kt["dakika"]))
    maclar = baglam.takim_maclari[takim_id]
    return [(i, dakika[m]) for i, m in enumerate(maclar) if m in dakika], len(maclar)


def donus_durumu(baglam, oyuncu):
    """Bugünkü maç, uzun bir aradan sonraki kaçıncı maç? Döndürür: (1 ya da 2, kaçırılan maç sayısı) ya da None."""
    k = baglam.oyuncu_kayitlari.get(oyuncu.oyuncu_id)
    if k is None:
        return None
    sira, toplam = _takim_sirasi(baglam, k, oyuncu.takim_id)
    if not sira:
        return None
    sondaki_bosluk = toplam - 1 - sira[-1][0]            # takımın son maçlarından kaçını kaçırdı
    if sondaki_bosluk >= config.DONUS_MIN_KACIRILAN:
        return 1, sondaki_bosluk
    if sondaki_bosluk == 0 and len(sira) >= 2:
        onceki_bosluk = sira[-1][0] - sira[-2][0] - 1    # son oynadığı maçtan önceki ara
        if onceki_bosluk >= config.DONUS_MIN_KACIRILAN:
            return 2, onceki_bosluk
    return None


def donus_etkisi(baglam):
    """Geçmiş dönüşlerde dakika değişimi (örn. −0,12 = %12 az) ve dönüş maçı sayısı; başlangıç değerine çekilmiş."""
    if "donus" not in baglam.onbellek:
        taban_toplam, donus_toplam, n = 0.0, 0.0, 0
        for kimlik, k in baglam.oyuncu_kayitlari.items():
            for takim_id in k["takim_id"].unique():
                sira, _ = _takim_sirasi(baglam, k, takim_id)
                for j in range(1, len(sira)):
                    if sira[j][0] - sira[j - 1][0] - 1 < config.DONUS_MIN_KACIRILAN:
                        continue
                    onceki = [dk for _, dk in sira[max(0, j - 5):j]]
                    if len(onceki) < 3:
                        continue
                    for _, dk in sira[j:j + config.DONUS_MAC]:
                        taban_toplam += sum(onceki) / len(onceki)
                        donus_toplam += dk
                        n += 1
        ham = donus_toplam / taban_toplam - 1.0 if taban_toplam else 0.0
        baglam.onbellek["donus"] = (kucuk_orneklem(n, ham, config.DONUS_K, notr=-config.DONUS_KAYBI_BASLANGIC), n, ham)
    return baglam.onbellek["donus"]


def hesapla(oyuncu, mac, istatistik, baglam):
    if oyuncu.oyuncu_id not in baglam.oyuncu_kayitlari:
        return veri_yok("oyuncunun maç kaydı yok")
    durum = donus_durumu(baglam, oyuncu)
    if durum is None:
        return EtkenSonucu(1.0, True, 0, "uzun aradan dönmüyor")
    etki, n, _ = donus_etkisi(baglam)
    return EtkenSonucu(1.0 + etki, True, n, f"{durum[1]} maçlık aradan sonraki {durum[0]}. maç: dakika %{100 * etki:+.0f} ({n} dönüş maçından)")
