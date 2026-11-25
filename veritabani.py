"""SQLite şeması ve yazma işlevleri (PLAN bölüm 4).

Tüm yazmalar "varsa güncelle, yoksa ekle" biçimindedir; aynı veri iki kez
yazılırsa satır çoğalmaz.
"""
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config

SEMA = """
CREATE TABLE IF NOT EXISTS takimlar (
    takim_id        INTEGER PRIMARY KEY,          -- NBA takım kimliği
    kisaltma        TEXT NOT NULL UNIQUE,         -- NBA kısaltması (BOS, GSW ...)
    isim            TEXT NOT NULL,
    espn_id         INTEGER UNIQUE,
    espn_kisaltma   TEXT                          -- ESPN'de farklı olabilir (GS, NY, SA ...)
) STRICT;

CREATE TABLE IF NOT EXISTS oyuncular (
    oyuncu_id        INTEGER PRIMARY KEY,         -- NBA oyuncu kimliği
    espn_id          INTEGER UNIQUE,
    isim             TEXT NOT NULL,
    takim_id         INTEGER REFERENCES takimlar(takim_id),   -- güncel takım; boşsa kadro dışı
    pozisyon         TEXT CHECK (pozisyon IN ('PG','SG','SF','PF','C')),
    pozisyon_kaynagi TEXT,                        -- espn_derinlik, elle_duzeltme ...
    aktif            INTEGER NOT NULL DEFAULT 1 CHECK (aktif IN (0,1)),
    guncelleme       TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS maclar (
    mac_id        TEXT PRIMARY KEY,               -- NBA maç kimliği, baştaki sıfırlar korunur
    tarih         TEXT NOT NULL,                  -- ABD (Doğu) tarihi, YYYY-AA-GG
    baslama_utc   TEXT,
    ev_takim_id   INTEGER NOT NULL REFERENCES takimlar(takim_id),
    dep_takim_id  INTEGER NOT NULL REFERENCES takimlar(takim_id),
    durum         TEXT NOT NULL CHECK (durum IN ('oynandi','oynanacak','ertelendi')),
    ev_sayi       INTEGER,
    dep_sayi      INTEGER
) STRICT;
CREATE INDEX IF NOT EXISTS ix_maclar_tarih ON maclar(tarih);

CREATE TABLE IF NOT EXISTS oyuncu_mac (
    oyuncu_id        INTEGER NOT NULL REFERENCES oyuncular(oyuncu_id),
    mac_id           TEXT    NOT NULL REFERENCES maclar(mac_id),
    takim_id         INTEGER NOT NULL REFERENCES takimlar(takim_id),  -- oyuncunun O MAÇTAKİ takımı
    rakip_id         INTEGER NOT NULL REFERENCES takimlar(takim_id),
    ev_mi            INTEGER NOT NULL CHECK (ev_mi IN (0,1)),
    ilk_bes          INTEGER CHECK (ilk_bes IN (0,1)),
    dakika           REAL,
    sayi             INTEGER,
    ribaund          INTEGER,
    asist            INTEGER,
    ucluk            INTEGER,                     -- üçlük isabeti
    top_calma        INTEGER,
    blok             INTEGER,
    top_kaybi        INTEGER,
    saha_ici_isabet  INTEGER,
    saha_ici_deneme  INTEGER,
    ucluk_deneme     INTEGER,
    serbest_isabet   INTEGER,
    serbest_deneme   INTEGER,
    PRIMARY KEY (oyuncu_id, mac_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_oyuncu_mac_mac ON oyuncu_mac(mac_id);
CREATE INDEX IF NOT EXISTS ix_oyuncu_mac_rakip ON oyuncu_mac(rakip_id);

CREATE TABLE IF NOT EXISTS oyuncu_sezon (
    oyuncu_id        INTEGER NOT NULL,            -- NBA oyuncu kimliği (artık ligde olmayanlar da olabilir)
    sezon            TEXT NOT NULL,               -- örn. 2025-26
    mac_sayisi       INTEGER NOT NULL,
    dakika           REAL,
    sayi             INTEGER,
    ribaund          INTEGER,
    asist            INTEGER,
    ucluk            INTEGER,                     -- üçlük isabeti
    top_calma        INTEGER,
    blok             INTEGER,
    top_kaybi        INTEGER,
    saha_ici_isabet  INTEGER,
    saha_ici_deneme  INTEGER,
    ucluk_deneme     INTEGER,
    serbest_isabet   INTEGER,
    serbest_deneme   INTEGER,
    faul             INTEGER,
    PRIMARY KEY (oyuncu_id, sezon)
) STRICT;

CREATE TABLE IF NOT EXISTS takim_mac (
    takim_id         INTEGER NOT NULL REFERENCES takimlar(takim_id),
    mac_id           TEXT    NOT NULL REFERENCES maclar(mac_id),
    rakip_id         INTEGER NOT NULL REFERENCES takimlar(takim_id),
    ev_mi            INTEGER NOT NULL CHECK (ev_mi IN (0,1)),
    dakika           REAL NOT NULL,               -- maçın takım dakikası: 240, uzatma başına +25
    sayi             INTEGER,
    saha_ici_isabet  INTEGER,
    saha_ici_deneme  INTEGER,
    ucluk_isabet     INTEGER,
    ucluk_deneme     INTEGER,
    serbest_isabet   INTEGER,
    serbest_deneme   INTEGER,
    hucum_ribaund    INTEGER,
    savunma_ribaund  INTEGER,
    asist            INTEGER,
    top_calma        INTEGER,
    blok             INTEGER,
    top_kaybi        INTEGER,
    faul             INTEGER,
    pozisyon_sayisi  REAL,                        -- şut denemesi − hücum ribaundu + top kaybı + 0,44 × serbest atış denemesi
    tempo            REAL,                        -- maçın 48 dakika başına pozisyonu (iki takımın ortalaması, ölçekli)
    PRIMARY KEY (takim_id, mac_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_takim_mac_mac ON takim_mac(mac_id);

CREATE TABLE IF NOT EXISTS sakatliklar (
    kaynak          TEXT NOT NULL,                -- espn, nba_resmi
    oyuncu_anahtari TEXT NOT NULL,                -- kaynağın kendi kimliği (ESPN kimliği ya da isim|takım)
    cekim_tarihi    TEXT NOT NULL,                -- YYYY-AA-GG; kaynak başına günde tek görüntü
    cekim_zamani    TEXT NOT NULL,                -- o günün son çekimi (UTC)
    oyuncu_id       INTEGER REFERENCES oyuncular(oyuncu_id),  -- eşleşmediyse boş
    isim            TEXT NOT NULL,
    takim_id        INTEGER REFERENCES takimlar(takim_id),
    durum           TEXT NOT NULL,                -- Out, Day-To-Day ...
    aciklama        TEXT,
    tahmini_donus   TEXT,
    PRIMARY KEY (kaynak, oyuncu_anahtari, cekim_tarihi)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_sakatliklar_oyuncu ON sakatliklar(oyuncu_id, cekim_tarihi);

CREATE TABLE IF NOT EXISTS savunma_profili (
    takim_id         INTEGER NOT NULL REFERENCES takimlar(takim_id),
    pozisyon         TEXT NOT NULL CHECK (pozisyon IN ('PG','SG','SF','PF','C')),
    istatistik       TEXT NOT NULL,
    hesap_tarihi     TEXT NOT NULL,
    verilen_ort      REAL,                        -- 36 dakika başına
    lig_ort          REAL,
    oran             REAL,                        -- verilen_ort / lig_ort
    duzeltilmis_oran REAL,                        -- küçük örneklem düzeltmesi sonrası
    sira             INTEGER CHECK (sira BETWEEN 1 AND 30),
    mac_sayisi       INTEGER NOT NULL,
    PRIMARY KEY (takim_id, pozisyon, istatistik, hesap_tarihi)
) STRICT;

CREATE TABLE IF NOT EXISTS tahminler (
    tahmin_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    tur          TEXT NOT NULL DEFAULT 'canli' CHECK (tur IN ('canli','geri_test')),
    tarih        TEXT NOT NULL,                   -- maçın ABD tarihi
    oyuncu_id    INTEGER NOT NULL REFERENCES oyuncular(oyuncu_id),
    mac_id       TEXT    NOT NULL REFERENCES maclar(mac_id),
    istatistik   TEXT NOT NULL,                   -- birleşik değerler de olabilir
    tahmin       REAL NOT NULL,
    guven        REAL NOT NULL CHECK (guven BETWEEN 0 AND 100),
    girdiler     TEXT,                            -- JSON
    gerceklesen  REAL,
    hata         REAL,                            -- tahmin - gerceklesen
    olusturma    TEXT NOT NULL,
    UNIQUE (tur, oyuncu_id, mac_id, istatistik)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_tahminler_tarih ON tahminler(tarih);

CREATE TABLE IF NOT EXISTS tahmin_etken (
    tahmin_id  INTEGER NOT NULL REFERENCES tahminler(tahmin_id) ON DELETE CASCADE,
    etken      TEXT NOT NULL,                     -- etkenler/ klasöründeki dosya adı
    carpan     REAL NOT NULL,                     -- sınır uygulanmış çarpan
    veri_var   INTEGER NOT NULL CHECK (veri_var IN (0,1)),
    orneklem   INTEGER NOT NULL DEFAULT 0,
    aciklama   TEXT,
    PRIMARY KEY (tahmin_id, etken)
) STRICT;

CREATE TABLE IF NOT EXISTS ilk_bes_beklenti (
    mac_id         TEXT    NOT NULL REFERENCES maclar(mac_id),
    oyuncu_id      INTEGER NOT NULL,              -- NBA oyuncu kimliği
    takim_id       INTEGER NOT NULL REFERENCES takimlar(takim_id),
    pozisyon       TEXT,                          -- ilk beşteki yeri (PG ... C); ilk beşte değilse boş
    durum          TEXT,                          -- Expected (beklenen) ya da Confirmed (kesin)
    kadro_durumu   TEXT,                          -- Active ya da Inactive
    cekim_zamani   TEXT NOT NULL,
    PRIMARY KEY (mac_id, oyuncu_id)
) STRICT;

CREATE TABLE IF NOT EXISTS hakemler (
    hakem_id  INTEGER PRIMARY KEY,                -- NBA kişi kimliği
    isim      TEXT NOT NULL,
    forma_no  INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS hakem_mac (
    mac_id    TEXT    NOT NULL REFERENCES maclar(mac_id),
    hakem_id  INTEGER NOT NULL REFERENCES hakemler(hakem_id),
    gorev     TEXT,                               -- bas_hakem, hakem, yardimci
    kaynak    TEXT NOT NULL CHECK (kaynak IN ('atama','kutu_skoru')),   -- atama: maç öncesi sayfa; kutu_skoru: oynanmış maç
    PRIMARY KEY (mac_id, hakem_id)
) STRICT;

CREATE TABLE IF NOT EXISTS hakem_profili (
    hakem_id                  INTEGER PRIMARY KEY REFERENCES hakemler(hakem_id),
    hesap_tarihi              TEXT NOT NULL,
    mac_sayisi                INTEGER NOT NULL,
    faul_endeksi              REAL NOT NULL,      -- hakemin maçlarındaki toplam faul / beklenen toplam
    serbest_atis_endeksi      REAL NOT NULL,
    faul_duzeltilmis          REAL NOT NULL,      -- küçük örneklem düzeltmesi sonrası
    serbest_atis_duzeltilmis  REAL NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS salonlar (
    sehir        TEXT PRIMARY KEY,                -- fikstürdeki maç şehri
    takim        TEXT,                            -- ev sahibi takımın kısaltması; tarafsız ya da ikinci salonsa boş
    salon        TEXT,
    enlem        REAL NOT NULL,
    boylam       REAL NOT NULL,
    saat_dilimi  TEXT NOT NULL,
    rakim_m      REAL NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS yolculuk (
    takim_id           INTEGER NOT NULL REFERENCES takimlar(takim_id),
    mac_id             TEXT    NOT NULL REFERENCES maclar(mac_id),
    ev_mi              INTEGER NOT NULL CHECK (ev_mi IN (0,1)),
    dinlenme_gunu      INTEGER,                   -- önceki maçla arasındaki boş gün; arka arkaya maçta 0, sezonun ilk maçında boş
    km                 REAL NOT NULL,             -- önceki maçın şehrinden bu maçın şehrine kuş uçuşu
    saat_dilimi_farki  REAL NOT NULL,             -- bu şehrin saati − önceki şehrin saati (artı: doğuya)
    rakim_m            REAL NOT NULL,
    uc_dortte          INTEGER NOT NULL,          -- son 4 günde 3. maç mı
    dort_altida        INTEGER NOT NULL,          -- son 6 günde 4. maç mı
    deplasman_sirasi   INTEGER NOT NULL,          -- deplasman serisinin kaçıncı maçı; evdeyse 0
    PRIMARY KEY (takim_id, mac_id)
) STRICT;

CREATE TABLE IF NOT EXISTS takip_mac (
    oyuncu_id        INTEGER NOT NULL REFERENCES oyuncular(oyuncu_id),
    mac_id           TEXT    NOT NULL REFERENCES maclar(mac_id),
    olasi_asist      INTEGER,                     -- şutla sonuçlanan pas (şut girse asist olacaktı)
    pas              INTEGER,
    ribaund_firsati  INTEGER,                     -- oyuncunun topa en yakın olduğu ribaund pozisyonu
    top_dokunusu     INTEGER,
    PRIMARY KEY (oyuncu_id, mac_id)
) STRICT;

CREATE TABLE IF NOT EXISTS oranlar (
    mac_id        TEXT NOT NULL REFERENCES maclar(mac_id),
    tur           TEXT NOT NULL CHECK (tur IN ('guncel','kapanis')),   -- guncel: maç öncesi son çekim; kapanis: maç bittikten sonra okunan çizgi
    cekim_zamani  TEXT NOT NULL,
    handikap      REAL,                           -- ev sahibinin çizgisi: −5 ise ev sahibi 5 sayı farkla favori
    toplam        REAL,                           -- toplam sayı çizgisi
    saglayici     TEXT,
    espn_mac_id   INTEGER,
    PRIMARY KEY (mac_id, tur)
) STRICT;

CREATE TABLE IF NOT EXISTS oyuncu_barem (       -- bahis sitesinin oyuncu baremleri (ESPN üzerinden); günde bir kez, maç öncesi çekilir
    mac_id          TEXT NOT NULL REFERENCES maclar(mac_id),
    espn_oyuncu_id  INTEGER NOT NULL,
    istatistik      TEXT NOT NULL,                -- sayi, ribaund, asist, ucluk ve birleşikleri (sayi+ribaund+asist ...)
    oyuncu_id       INTEGER REFERENCES oyuncular(oyuncu_id),   -- ESPN kimliği oyuncular tablosunda bulunamadıysa boş
    tarih           TEXT NOT NULL,                -- maçın tarihi (ABD)
    cizgi           REAL NOT NULL,                -- çekim anındaki barem
    acilis_cizgi    REAL,                         -- baremin ilk açıldığı değer
    oran_1          REAL,                         -- iki tarafın ondalık oranı, beslemedeki sırayla. Hangisinin üst olduğu beslemede yazmaz;
    oran_2          REAL,                         -- sıra üst, alt görünüyor (25 Kasım 2026: bir tarafı belirgin favori 217 baremin 165'i bununla tutarlı)
    acilis_oran_1   REAL,
    acilis_oran_2   REAL,
    saglayici       TEXT,
    guncelleme      TEXT,                         -- ESPN'in 'lastUpdated' alanı, geldiği gibi
    cekim_zamani    TEXT NOT NULL,
    PRIMARY KEY (mac_id, espn_oyuncu_id, istatistik)
) STRICT;

CREATE TABLE IF NOT EXISTS onsuz_etkisi (
    oyuncu_id      INTEGER NOT NULL REFERENCES oyuncular(oyuncu_id),
    arkadas_id     INTEGER NOT NULL REFERENCES oyuncular(oyuncu_id),   -- önemli takım arkadaşı
    istatistik     TEXT NOT NULL,                 -- yedi istatistik + 'kullanim' (yüzde)
    hesap_tarihi   TEXT NOT NULL,
    onunla_36      REAL,                          -- arkadaş oynarken 36 dk başına (kullanımda: %)
    onsuz_36       REAL,                          -- arkadaş oynamazken
    onunla_mac     INTEGER NOT NULL,
    onsuz_mac      INTEGER NOT NULL,
    onunla_dakika  REAL,                          -- maç başına dakika
    onsuz_dakika   REAL,
    PRIMARY KEY (oyuncu_id, arkadas_id, istatistik)
) STRICT;

CREATE TABLE IF NOT EXISTS calisma_kaydi (
    kayit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    calisma_id   TEXT NOT NULL,                   -- aynı çalıştırmanın adımlarını bağlar
    zaman        TEXT NOT NULL,
    adim         TEXT NOT NULL,
    sonuc        TEXT NOT NULL CHECK (sonuc IN ('tamam','hata')),
    hata_iletisi TEXT,
    sure_sn      REAL
) STRICT;
"""

# Sonradan eklenen sütunlar: (tablo, sütun, tür). sema_kur eksik olanı ekler,
# böylece var olan nba.db silinmeden güncellenir.
EK_SUTUNLAR = [
    ("oyuncu_mac", "faul", "INTEGER"),
    ("maclar", "salon_sehri", "TEXT"),                           # maçın oynandığı şehir (tarafsız saha ve ikinci salonlar için)
    ("tahminler", "alt", "REAL"),                                # %10'luk değer (tahmin sütunu orta, %50'lik değerdir)
    ("tahminler", "ust", "REAL"),                                # %90'lık değer
    ("tahminler", "calistirma", "TEXT"),                         # tahmini en son yazan çalıştırma: sabah, mac_oncesi, geri_test
    ("tahminler", "on_tahmin", "REAL"),                          # sabah çalıştırmasının (ön) tahmini; maç öncesi çalıştırma bunu değiştirmez
    ("tahminler", "on_guven", "REAL"),
    ("tahminler", "on_hata", "REAL"),                            # on_tahmin − gerceklesen
    ("oyuncu_mac", "kullanim", "REAL"),                          # maç bazında kullanım oranı (%)
    ("savunma_profili", "beklenene_gore_oran", "REAL"),          # gerçekleşen / oyuncuların kendi üretiminden beklenen
    ("savunma_profili", "beklenene_gore_duzeltilmis", "REAL"),   # küçük örneklem düzeltmesi sonrası
    ("savunma_profili", "beklenene_gore_sira", "INTEGER"),
    ("savunma_profili", "oyuncu_dakika", "REAL"),                # beklenene göre orana giren oyuncu-dakikası
]

# "Varsa güncelle" için her tablonun çakışma anahtarı.
ANAHTARLAR = {
    "takimlar": ("takim_id",),
    "oyuncular": ("oyuncu_id",),
    "maclar": ("mac_id",),
    "oyuncu_mac": ("oyuncu_id", "mac_id"),
    "takim_mac": ("takim_id", "mac_id"),
    "oyuncu_sezon": ("oyuncu_id", "sezon"),
    "sakatliklar": ("kaynak", "oyuncu_anahtari", "cekim_tarihi"),
    "savunma_profili": ("takim_id", "pozisyon", "istatistik", "hesap_tarihi"),
    "tahminler": ("tur", "oyuncu_id", "mac_id", "istatistik"),
    "tahmin_etken": ("tahmin_id", "etken"),
    "onsuz_etkisi": ("oyuncu_id", "arkadas_id", "istatistik"),
    "oranlar": ("mac_id", "tur"),
    "oyuncu_barem": ("mac_id", "espn_oyuncu_id", "istatistik"),
    "takip_mac": ("oyuncu_id", "mac_id"),
    "salonlar": ("sehir",),
    "hakemler": ("hakem_id",),
    "ilk_bes_beklenti": ("mac_id", "oyuncu_id"),
    "hakem_mac": ("mac_id", "hakem_id"),
    "hakem_profili": ("hakem_id",),
    "yolculuk": ("takim_id", "mac_id"),
}


def simdi_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def abd_bugun():
    """Maç takviminin esas aldığı saat dilimindeki bugünün tarihi (YYYY-AA-GG)."""
    return datetime.now(ZoneInfo(config.MAC_SAAT_DILIMI)).date().isoformat()


def baglan(yol=None):
    conn = sqlite3.connect(yol or config.DB_YOLU)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def tablo_sutunlari(conn, tablo):
    return [s["name"] for s in conn.execute(f'PRAGMA table_info("{tablo}")')]


def sema_kur(conn):
    conn.executescript(SEMA)
    for tablo, sutun, tur in EK_SUTUNLAR:
        if sutun not in tablo_sutunlari(conn, tablo):
            conn.execute(f"ALTER TABLE {tablo} ADD COLUMN {sutun} {tur}")
    conn.commit()


def yaz(conn, tablo, satirlar):
    """Sözlük listesini tabloya yazar: anahtar varsa verilen sütunları günceller, yoksa ekler.

    Yalnızca satırda verilen sütunlara dokunur; böylece örneğin maç kaydından
    gelen oyuncu satırı, daha önce yazılmış pozisyonu silmez. Yazılan satır
    sayısını döndürür. Bilinmeyen tablo ya da sütun hata verir.
    """
    if tablo not in ANAHTARLAR:
        raise ValueError(f"Bilinmeyen tablo: {tablo}")
    satirlar = list(satirlar)
    if not satirlar:
        return 0
    sutunlar = list(satirlar[0])
    if any(set(s) != set(sutunlar) for s in satirlar):
        raise ValueError(f"{tablo}: satırların sütunları birbirini tutmuyor")
    bilinmeyen = set(sutunlar) - set(tablo_sutunlari(conn, tablo))
    if bilinmeyen:
        raise ValueError(f"{tablo}: bilinmeyen sütun {sorted(bilinmeyen)}")
    anahtar = ANAHTARLAR[tablo]
    eksik = set(anahtar) - set(sutunlar)
    if eksik:
        raise ValueError(f"{tablo}: anahtar sütunu eksik {sorted(eksik)}")

    guncellenecek = [s for s in sutunlar if s not in anahtar]
    eylem = (
        "DO UPDATE SET " + ", ".join(f"{s} = excluded.{s}" for s in guncellenecek)
        if guncellenecek
        else "DO NOTHING"
    )
    sql = (
        f"INSERT INTO {tablo} ({', '.join(sutunlar)}) "
        f"VALUES ({', '.join(':' + s for s in sutunlar)}) "
        f"ON CONFLICT ({', '.join(anahtar)}) {eylem}"
    )
    # numpy/pandas sayılarını düz Python türüne çevir
    duz = [{k: (v.item() if hasattr(v, "item") else v) for k, v in s.items()} for s in satirlar]
    with conn:
        conn.executemany(sql, duz)
    return len(duz)


def goruntu_yaz(conn, tablo, sabit, satirlar):
    """Bir görüntüyü yenisiyle değiştirir (tek işlemde).

    `sabit` sözlüğündeki değerleri taşıyan eski satırlar silinir, yenileri yazılır.
    Böylece aynı gün ikinci çekimde listeden çıkmış kayıtlar da kalkar. Yazma
    başarısız olursa silme de geri alınır.
    """
    if tablo not in ANAHTARLAR:
        raise ValueError(f"Bilinmeyen tablo: {tablo}")
    satirlar = [{**s, **sabit} for s in satirlar]
    kosul = " AND ".join(f"{s} = ?" for s in sabit)
    try:
        conn.execute(f"DELETE FROM {tablo} WHERE {kosul}", tuple(sabit.values()))
        sayi = yaz(conn, tablo, satirlar)  # silme ile aynı işlemin parçası
        conn.commit()
        return sayi
    except Exception:
        conn.rollback()
        raise


def kayit_yaz(conn, calisma_id, adim, sonuc, hata_iletisi=None, sure_sn=None):
    """calisma_kaydi tablosuna bir satır ekler (bu tablo bilerek yalnızca büyür)."""
    with conn:
        conn.execute(
            "INSERT INTO calisma_kaydi (calisma_id, zaman, adim, sonuc, hata_iletisi, sure_sn) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (calisma_id, simdi_utc(), adim, sonuc, hata_iletisi, sure_sn),
        )


def ozet(conn):
    """Tablo adı -> satır sayısı."""
    tablolar = [
        s["name"]
        for s in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tablolar}


if __name__ == "__main__":
    with baglan() as conn:
        sema_kur(conn)
        print(f"Veri tabanı: {config.DB_YOLU}")
        for tablo, sayi in ozet(conn).items():
            print(f"  {tablo:<16} {sayi:>6} satır | {len(tablo_sutunlari(conn, tablo))} sütun")
    conn.close()
