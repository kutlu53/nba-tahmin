# NBA oyuncu istatistik tahmini

Her NBA maç günü için oyuncuların sayı, ribaund, asist, üçlük, top çalma, blok ve top kaybı tahminlerini üreten,
ertesi gün gerçek sonuçlarla puanlayan bir sistem. Python ve SQLite ile yazıldı; bu depoda GitHub Actions üzerinde
kendiliğinden çalışır.

Tahminler istatistiksel bir modelin çıktısıdır; kesinlik taşımaz.

## Nasıl çalışır

`Akış` iş akışı 15 dakikada bir tetiklenir ve `bulut.py` sırası gelen işi seçer (saatler Türkiye saati, `config.py`):

| akış | ne zaman | ne yapar |
|---|---|---|
| sabah (`gunluk.py`) | 10:00'dan sonra, günde bir kez | dünkü maçları ve güncel verileri toplar, dünkü tahminleri puanlar, günün ön tahminlerini üretir |
| maç öncesi (`mac_oncesi.py`) | 20:30'dan sonra, günde bir kez | sakatlık, oran, hakem ve ilk beşleri yeniden çeker; başlamamış maçların tahminini yeniler |
| yaklaşan maç (`mac_oncesi.py --yaklasan 40`) | 40 dakika içinde başlayacak maç varsa | kesin ilk beşle o maçların tahminini yeniler |
| haftalık (`haftalik.py`) | pazartesi 11:00'den sonra | haftalık hata raporu ve etken katkı testi |

Yapılacak iş yoksa çalıştırma birkaç saniyede biter. GitHub'ın zamanlanmış tetiklemeleri gecikebildiği için saatler
"en erken" saatlerdir; geciken ya da atlanan bir tetiklemenin işini sonraki tetikleme yapar.

Veritabanı (`nba.db`) depoda değil, [`veri` sürümünün](../../releases/tag/veri) ekinde durur: her çalıştırma onu indirir,
iş bitince yenisini yükler. `nba-onceki.db` bir önceki günün yedeğidir. Her çalıştırmanın logları, Excel raporu ve
sayfa verisi çalıştırmanın çıktıları (Artifacts) arasında 14 gün saklanır; adım adım sonuç çalıştırmanın özet
sayfasında görünür.

## Veri kaynakları

- Fikstür, oyuncu listesi, kutu skorları, hakemler, günlük ilk beşler: nba.com'un sayfa dosyaları (`kaynak/nba_cdn.py`)
- Günün hakem atamaları: official.nba.com
- Sakatlıklar: NBA'in resmi sakatlık raporu ve ESPN
- Kadro, pozisyon ve bahis çizgileri: ESPN
- Takip verisi (olası asist, ribaund fırsatı): yalnızca stats.nba.com sorgularından alınabiliyor ve bu sorgular
  GitHub'ın makinelerine yanıt vermiyor. Bu veriyi ayrı bir bilgisayar çekip `takip_verisi/` klasörüne günlük dosyalar
  olarak gönderir (`takip_aktar.py`). Bir günün dosyası gelmemişse o gün atlanır, geldiğinde işlenir.

## Elle çalıştırma

Actions sekmesinde `Akış` iş akışını `Run workflow` ile başlatıp akışı seçebilirsiniz. Kendi bilgisayarınızda:

    pip install -r requirements.txt
    python -m unittest discover -s testler -t .
    NBA_VERI_KAYNAGI=cdn python gunluk.py        # nba.db dosyası proje klasöründe olmalı

Resmi sakatlık raporu için Java 8 ya da üstü gerekir.

## Bilinmesi gerekenler

- GitHub, 60 gün boyunca hiçbir gönderim yapılmayan açık depolarda zamanlanmış iş akışlarını durdurur.
- `Testler` iş akışı her gönderimde sınamaları çalıştırır.
