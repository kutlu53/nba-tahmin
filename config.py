"""Sezon, yollar, ağırlıklar ve bekleme süreleri. Ayarlanacak her değer burada durur."""
import os
from pathlib import Path

KOK = Path(__file__).resolve().parent
DB_YOLU = KOK / "nba.db"
RAPOR_KLASORU = KOK / "raporlar"
LOG_KLASORU = KOK / "log"
POZISYON_DUZELTME_YOLU = KOK / "pozisyon_duzeltme.csv"  # elle pozisyon düzeltmeleri
SALONLAR_YOLU = KOK / "salonlar.csv"                    # elle hazırlanmış: maç şehirlerinin konumu, saat dilimi, rakımı

# --- Sezon ---
SEZON = "2026-27"
SEZON_TURU = "Regular Season"
ONCEKI_SEZON = "2025-26"      # ön bilgi (başlangıç değeri) olarak kullanılan sezon
SEZON_BASLANGIC = "2026-10-20"
SEZON_BITIS = "2027-04-11"
MAC_SAAT_DILIMI = "America/New_York"  # "bugünün maçları" ABD tarihine göre belirlenir

# --- İstatistikler ---
POZISYONLAR = ("PG", "SG", "SF", "PF", "C")
ISTATISTIKLER = ("sayi", "ribaund", "asist", "ucluk", "top_calma", "blok", "top_kaybi")
BIRLESIK = {
    "sayi+ribaund+asist": ("sayi", "ribaund", "asist"),
    "sayi+ribaund": ("sayi", "ribaund"),
    "sayi+asist": ("sayi", "asist"),
    "ribaund+asist": ("ribaund", "asist"),
}

# --- Ağ istekleri ---
# Fikstür, oyuncu listesi ve maç kutu skorlarının alındığı yer:
#   "stats": stats.nba.com sorguları (varsayılan; bu bilgisayarda kullanılan)
#   "cdn":   nba.com'un sayfa dosyaları (kaynak/nba_cdn.py); stats.nba.com'un yanıt vermediği bulut makineleri için
# Ortam değişkeni NBA_VERI_KAYNAGI ile seçilir; ayarlanmamışsa "stats".
VERI_KAYNAGI = os.environ.get("NBA_VERI_KAYNAGI", "stats")
# Takip verisi (olası asist, ribaund fırsatı) yalnızca stats.nba.com'dan alınabiliyor. "cdn" kipinde bu klasördeki
# günlük dosyalardan okunur; dosyaları stats.nba.com'a ulaşabilen bilgisayar takip_aktar.py ile yazar.
TAKIP_KLASORU = KOK / "takip_verisi"
ISTEK_BEKLEME_SN = 1.5   # stats.nba.com istekleri arasında
ZAMAN_ASIMI_SN = 60
DENEME_SAYISI = 3        # her denemede bekleme artar
ESPN_BEKLEME_SN = 0.4    # ESPN istekleri arasında
ESPN_TABAN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_SAKATLIK_URL = f"{ESPN_TABAN}/injuries"
ESPN_TAKIMLAR_URL = f"{ESPN_TABAN}/teams?limit=40"
ESPN_KADRO_URL = f"{ESPN_TABAN}/teams/{{espn_id}}/roster"
ESPN_DERINLIK_URL = f"{ESPN_TABAN}/teams/{{espn_id}}/depthcharts"

# --- Savunma profili (bölüm 5) ---
SAVUNMA_MIN_DAKIKA = 10
NORMALLESTIRME_DAKIKA = 36
KUCUK_ORNEKLEM_K = 10         # ham oran: maç
ESLESME_K_DAKIKA = 150        # beklenene göre oran: oyuncu-dakikası (PLAN_EK etken 1)

# --- Tahmin (bölüm 6) ---
TEMEL_AGIRLIK = {"sezon": 0.40, "son10": 0.35, "son5": 0.25}
DAKIKA_PENCERE = 5           # beklenen dakika: son 5 maç ortalaması
DAKIKA_PENCERE_ROL = 3       # ilk beş / yedek rolü değiştiyse son 3 maç
# 23 Kasım 2026: 0'dan 0,5'e çıkarıldı; geriye dönük denemede yedi istatistiğin hepsinde hatayı düşürdü (sayı −0,025 ± 0,017).
DAKIKA_SEZON_AGIRLIK = 0.5   # beklenen dakika = (1 − a) × son maçlar + a × sezon ortalaması; 0: yalnız son maçlar (PLAN bölüm 6)
TAHMIN_MIN_MAC = 3           # bu sezon en az bu kadar maç oynamış oyuncuya tahmin üretilir
TAHMIN_MIN_DAKIKA = 10       # beklenen dakikası bunun altındaysa tahmin üretilmez
ROTASYON_PENCERE = 5         # takımının son 5 maçının en az birinde oynamış olmalı
BIRLESIK_TAHMIN = True       # sayı+ribaund+asist gibi birleşik değerler de üretilsin

# Etkenlerin küçük örneklem sabitleri: (n × değer + k × nötr) / (n + k)
EV_DEPLASMAN_K = 20          # oyuncunun o sahadaki maç sayısına karşı
ARKA_ARKAYA_K = 60           # ligdeki arka arkaya takım-maç sayısına karşı
EKSIK_ARKADAS_PENCERE = DAKIKA_PENCERE  # boşalan dakika, beklenen dakikayla aynı pencerede ölçülür (çift sayma olmasın)

# --- Etken zinciri (PLAN_EK bölüm 2) ---
# Her etken etkenler/<ad>.py dosyasıdır. Sözlükteki sıra zincirdeki uygulama sırasıdır.
# "acik": False yapılan etken hiç çağrılmaz; "alt"/"ust" o etkenin çarpan sınırıdır.
# "tur" etkenin zincirdeki yerini söyler (PLAN_EK bölüm 2):
#   "carpan" (varsayılan): tahmini çarpan; çarpanların çarpımı genel sınıra çekilir.
#   "temel":  36 dk başına temel oranın yeniden tahmini; genel sınıra girmez.
#   "dakika": beklenen dakikanın düzeltmesi; genel sınıra girmez.
# 23 Kasım 2026 etken katkı testi (katki_testi.py; raporlar/etken_katki_testi.txt): hatayı düşürdüğü kanıtlanmayan
# etkenler kapatıldı. Açık kalanlar: sut_duzeltme, firsat, tempo, donus, yorgunluk. Test, veri biriktikçe yeniden
# çalıştırılmalı; kapalı etkenlerin kodu ve verisi yerinde durur.
ETKENLER = {
    # E11: kutu skorundan eksik bilgisiyle bile istatistik hatasını düşürmedi (sayı +0,001 ± 0,003).
    "eksik_dakika":  {"acik": False, "alt": 0.85, "ust": 1.25, "tur": "dakika"}, # eksik önemli arkadaş: "onsuz" verisindeki dakika farkı
    # E11: etkisiz (sayı +0,002 ± 0,003); handikap farklı maçları ayırt edemiyor.
    "fark_riski":    {"acik": False, "alt": 0.90, "ust": 1.10, "tur": "dakika"}, # farklı maç olasılığına göre dakika
    "donus":         {"acik": True, "alt": 0.70, "ust": 1.00, "tur": "dakika"},  # uzun aradan dönüşte dakika kısıtı
    "ilk_bes":       {"acik": True, "alt": 0.75, "ust": 1.40, "tur": "dakika"},  # bu geceki ilk beş: rolü değişen oyuncunun dakikası
    "sut_duzeltme":  {"acik": True, "alt": 0.40, "ust": 2.50, "tur": "temel"},   # şut yüzdelerinin ön yüzdeye çekilmesi (sayı ve üçlük)
    "firsat":        {"acik": True, "alt": 0.50, "ust": 2.00, "tur": "temel"},   # takip verisinden asist ve ribaund
    "tempo":         {"acik": True, "alt": 0.94, "ust": 1.06},  # maçın beklenen pozisyon sayısı
    # E11: kutu skorundan eksik bilgisiyle bile yararsız; üçlük ve blokta hatayı biraz artırdı.
    "kullanim":      {"acik": False, "alt": 0.85, "ust": 1.35}, # eksik önemli takım arkadaşı: "onsuz" verisi ve kullanım payı
    # 23 Kasım 2026: geriye dönük denemede sayı hatasını artırdığı için kapatıldı (+0,036 ± 0,023); E11'de yeniden denenecek.
    "eslesme":       {"acik": False, "alt": 0.90, "ust": 1.10}, # rakibe göre düzeltilmiş pozisyon savunması
    "eslesme_ham":   {"acik": False, "alt": 0.90, "ust": 1.10}, # PLAN bölüm 5'teki ham hesap; yalnızca karşılaştırma için
    # E11: yedi istatistiğin hepsinde hatayı artırdı (ribaund +0,006 ± 0,005; blok ve top kaybında da anlamlı).
    "ev_deplasman":  {"acik": False, "alt": 0.95, "ust": 1.05},
    "yorgunluk":     {"acik": True, "alt": 0.97, "ust": 1.02},  # yolculuk ve dinlenme; arka arkaya maçı da kapsar
    # E11: yönü doğru ama etkisi kanıtlanamadı (sayı −0,0007 ± 0,0012). Hakem verisi toplanmaya devam ediyor.
    "hakem":         {"acik": False, "alt": 0.97, "ust": 1.03}, # hakem ekibinin serbest atış eğilimi (yalnızca sayı)
    "arka_arkaya":   {"acik": False, "alt": 0.95, "ust": 1.03}, # PLAN bölüm 6'daki sürüm; yerini yorgunluk aldı
    # 23 Kasım 2026: kutu skorundan eksik bilgisiyle yapılan denemede sayı hatasını artırdığı için kapatıldı (+0,147 ± 0,043).
    "eksik_arkadas": {"acik": False, "alt": 1.00, "ust": 1.15}, # "Out" takım arkadaşlarının boşalttığı dakika (kaba dağıtım)
}
GENEL_CARPAN_SINIRI = (0.70, 1.45)  # tüm çarpanların çarpımı için

# --- Şut düzeltmesi (PLAN_EK etken 5) ---
# düzeltilmiş % = (isabet + k × ön yüzde) / (deneme + k); k deneme sayısı cinsinden
SUT_K = {"iki": 150, "ucluk": 300, "serbest": 100}
# ön yüzde = (geçen sezon isabet + k × pozisyonun lig yüzdesi) / (geçen sezon deneme + k)
ON_YUZDE_K = {"iki": 100, "ucluk": 100, "serbest": 50}

# --- Fark riski (PLAN_EK etken 4) ve beklenen dakika (PLAN_EK bölüm 6) ---
BUYUK_FARK_ESIGI = 20              # son fark bu kadar ya da fazlaysa "farklı maç"
FARK_SIGMA_BASLANGIC = 12.0        # fark dağılımının standart sapması; kendi verimizden yeniden hesaplanır
IC_SAHA_BASLANGIC = 2.5            # iç saha avantajı (sayı)
BUYUK_FARK_ORANI_BASLANGIC = 0.15  # ligde farklı maç oranı
FARK_K_MAC = 50                    # maç; yukarıdaki üç değer az maçta başlangıç değerine çekilir
FARK_DAKIKA_K = 100                # oyuncu-maç; farklı maçlardaki dakika etkisi sıfıra çekilir
NET_K = 10                         # maç; kendi fark tahminimizde takım net gücü sıfıra çekilir
TOPLAM_CIZGISI_HARMAN = True       # sayı ve üçlükte tempo çarpanı, toplam sayı çizgisiyle yarı yarıya harmanlansın
DONUS_MIN_KACIRILAN = 3            # üst üste bu kadar maç kaçıran oyuncu "aradan dönüyor" sayılır
DONUS_MAC = 2                      # kısıt, dönüşten sonraki ilk 2 maçta uygulanır
DONUS_KAYBI_BASLANGIC = 0.15       # dakika kaybı; kendi verimizden yeniden hesaplanır
DONUS_K = 30                       # dönüş maçı; az örneklemde başlangıç değerine çekilir

# --- Kullanım ve "onsuz" (PLAN_EK etken 3) ---
KULLANIM_ONEMLI_ORAN = 20.0        # önemli takım arkadaşı: kullanım oranı en az %20 ...
KULLANIM_ONEMLI_MIN_DAKIKA = 15.0  # ... ve maç başına en az 15 dk (az oynayan yüksek kullanımlı yedekleri eler)
KULLANIM_ONEMLI_DAKIKA = 28.0      # ... ya da maç başına en az 28 dk
KULLANIM_MIN_MAC = 5               # önemli sayılmak için takımda en az bu kadar maç
KULLANIM_LIG_ORT = 20.0            # beş oyuncunun payı 100 eder: ortalama %20
ONSUZ_MIN_MAC = 3                  # onsuz (ve onunla) maç sayısı bunun altındaysa yalnızca genel dağıtım kullanılır
ONSUZ_K = 5                        # maç; onsuz/onunla oranı genel dağıtım tahminine çekilir

# --- Fırsat verileri (PLAN_EK etken 6) ---
# dönüşüm oranı = (gerçekleşen + k × lig oranı) / (fırsat + k); k fırsat sayısı cinsinden
FIRSAT_K = {"asist": 100, "ribaund": 150}
FIRSAT_MIN_MAC = 3           # takip verisi olan maç sayısı bunun altındaysa etken devre dışı
FIRSAT_RAKIP_K = 10          # maç; takım şut yüzdeleri az maçta lig ortalamasına çekilir
FIRSAT_RAKIP_USSU = 0.5      # asistte rakibin şut savunması "hafifçe" uygulanır: oranın karekökü

# --- Yorgunluk (PLAN_EK etken 7) ---
YORGUNLUK_K = 2000                 # oyuncu-maç; koşulların etkisi güçlü biçimde 1,00'e çekilir (kanıt karışık)
YORGUNLUK_UZUN_KM = 1500           # önceki maçtan bu yana bu kadar ya da fazla yol "uzun yolculuk"
YORGUNLUK_SAAT_FARKI = 2           # saat; bu kadar ya da fazla saat dilimi değişimi
YORGUNLUK_RAKIM_M = 1200           # deplasman takımı için "yüksek rakım" (Denver, Salt Lake City, Mexico City)
YORGUNLUK_DEPLASMAN_SIRASI = 4     # deplasman serisinin bu ve sonraki maçları

# --- Hakem (PLAN_EK etken 8) ---
HAKEM_K = 20                       # maç; hakem endeksleri güçlü biçimde 1,00'e çekilir
CDN_BEKLEME_SN = 0.4               # cdn.nba.com istekleri arasında (maç başına hakem listesi)

# --- Tempo (PLAN_EK etken 2) ---
# Formül (şut denemesi − hücum ribaundu + top kaybı + 0,44 × SA denemesi), nba.com sitesinin saydığı
# pozisyonlardan her takımda yaklaşık %2 fazla çıkıyor (23 Kasım 2026 ölçümü: 101,4 yerine 99,4).
# Bu sabit yalnızca değerleri nba.com ölçeğine getirir; çarpan oranlardan hesaplandığı için etkilenmez.
TEMPO_OLCEK = 0.98
TEMPO_SON10_AGIRLIK = 0.5    # takım temposu = (1 − a) × sezon + a × son 10 maç
TEMPO_K = 5                  # maç; az maçta takım temposu lig ortalamasına çekilir

# --- Güven puanı (PLAN_EK bölüm 8; toplam 100) ---
GUVEN_AGIRLIK = {
    "orneklem": 15,                # oyuncunun bu sezon maç sayısı
    "istikrar": 15,                # istatistiğin değişim katsayısı
    "dakika_sabitligi": 15,        # son 5 maçta dakika oynaklığı, takımın maçlarına katılım, faul eğilimi
    "veri_butunlugu": 15,          # açık etkenlerin kaçında veri var
    "sakatlik_belirsizligi": 15,   # oyuncuda ve önemli takım arkadaşlarında "Day-To-Day" yok; uzun aradan dönmüyor
    "fark_riski": 10,              # farklı maç olasılığı düşük
    "sut_sansi": 10,               # güncel yüzde / dönüşüm ile düzeltilmiş değer yakın
    "eslesme_netligi": 5,          # düzeltilmiş savunma oranının örneklemi yeterli
}
GUVEN_TAM_PUAN_MAC = 15
GUVEN_ISTIKRAR_CV = (0.25, 1.25)      # değişim katsayısı: bu değerin altı tam puan, üstü sıfır
GUVEN_DAKIKA_SS = (2.0, 10.0)         # son 5 maçta dakika standart sapması: altı tam puan, üstü sıfır
GUVEN_FAUL_36 = (3.5, 6.0)            # 36 dk başına faul: altı etkisiz, üstünde dakika sabitliği puanı %40 düşer
GUVEN_FARK_OLASILIGI = (0.15, 0.40)   # farklı maç olasılığı: altı tam puan, üstü sıfır
GUVEN_SANS_UZAKLIGI = (0.03, 0.25)    # şut / fırsat düzeltme çarpanının 1'den uzaklığı: altı tam puan, üstü sıfır
GUVEN_ESLESME_DAKIKA = 600            # savunma oranına giren oyuncu-dakikası bu kadarsa tam puan
GUVEN_ROTASYON_DAKIKA = 15            # "Day-To-Day" takım arkadaşı bu kadar dakika alıyorsa belirsizlik sayılır

# --- Tahmin aralığı (alt %10, üst %90) ---
ARALIK_Z = 1.2816                     # normal dağılımın %90'lık değeri
ARALIK_MIN_MAC = 5                    # oyuncunun kendi oynaklığı en az bu kadar maçla hesaplanır
ARALIK_K = 10                         # maç; oyuncunun oynaklığı lig geneline çekilir
ARALIK_OLCEK = {  # standart sapma çarpanı; 23 Kasım 2026 geriye dönük denemesinde üst sınırın aşılma oranı %10 olacak biçimde ölçüldü
    "asist": 1.26,
    "blok": 1.24,
    "ribaund": 1.2,
    "ribaund+asist": 1.09,
    "sayi": 1.37,
    "sayi+asist": 1.04,
    "sayi+ribaund": 1.08,
    "sayi+ribaund+asist": 1.12,
    "top_calma": 1.28,
    "top_kaybi": 1.22,
    "ucluk": 1.25,
}

# --- Sakatlık kaynakları ve ilk beş ---
RESMI_RAPOR_KULLAN = True             # NBA resmi raporu ESPN'in önüne geçer: resmi "Out" ise tahmin üretilmez; ESPN "Out", resmi "Probable/Available" ise üretilir
ILK_BES_K = 100                       # oyuncu-maç; rol değişiminin dakika etkisi 1,00'e çekilir

# --- Çalıştırma saatleri (Türkiye saati; Görev Zamanlayıcı bu saatlerle kurulur: gorev_kur.py) ---
SABAH_SAATI = "10:00"                 # gunluk.py: veri toplama ve ön tahmin
MAC_ONCESI_SAATI = "20:30"            # mac_oncesi.py: sakatlık, oran, hakem ve ilk beş yeniden çekilir; henüz başlamamış maçlar yenilenir
YAKLASAN_ARALIK_DK = 15               # mac_oncesi.py --yaklasan: bu aralıkla çalışır ...
MAC_YAKLASAN_DK = 40                  # ... ve bu kadar dakika içinde başlayacak maçları kesin ilk beşle yeniler
GOREV_UYANDIR = False                 # True: yaklaşan maç görevi bilgisayarı uykudan uyandırır
TAKIP_GONDER_ARALIK_DK = 60           # takip_gonder.py: bu aralıkla çalışır; eksik takip verisini çekip GitHub deposuna gönderir (iş yoksa hemen çıkar)
HAFTALIK_GUN = "Monday"               # haftalik.py: haftalık rapor ve etken katkı testi
HAFTALIK_SAATI = "11:00"

# --- Geri test (bölüm 8) ---
GUVEN_DILIMLERI = (0, 40, 60, 80, 100)
ISABET_ORANI = 0.25                   # isabet: |hata| ≤ tahminin %25'i ...
ISABET_MUTLAK = 1.0                   # ... ya da ≤ 1 birim (hangisi büyükse)
