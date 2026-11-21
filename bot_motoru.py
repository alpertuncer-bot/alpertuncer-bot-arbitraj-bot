from datetime import datetime
import json
import os
import re
import sqlite3
import time
from urllib.parse import quote
import gspread
from playwright.sync_api import sync_playwright
import requests

if os.name == "nt":
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), 128)
    except Exception:
        pass

DB_DOSYA = "arbitraj.db"
DURUM_DOSYA = "bot_durum.json"
SHEET_ADI = "Arbitraj_Firsatlari"
AKAKCE_FARK_ATAN_URL = "https://www.akakce.com/fark-atan-fiyatlar/"


def gizli_deger_oku(anahtar, varsayilan=None):
    deger = os.environ.get(anahtar)
    if deger:
        return deger
    try:
        import streamlit as st

        return st.secrets.get(anahtar, varsayilan)
    except Exception:
        return varsayilan


TELEGRAM_TOKEN = gizli_deger_oku("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = gizli_deger_oku("TELEGRAM_CHAT_ID", "")

VARSAYILAN_BAREMLER = [
    {"kategori": "Genel", "min_fiyat": 0.0, "max_fiyat": 1000.0, "komisyon": 0.0, "kargo": 75.0},
    {"kategori": "Genel", "min_fiyat": 1000.01, "max_fiyat": 2500.0, "komisyon": 0.0, "kargo": 95.0},
    {"kategori": "Genel", "min_fiyat": 2500.01, "max_fiyat": 999999.0, "komisyon": 0.0, "kargo": 115.0},
]

VARSAYILAN_AYARLAR = {
    "aktif": True,
    "min_roi": 15.0,
    "kampanya_min_roi": 5.0,
    "min_yorum": 150,
    "hizmet_bedeli": 10.0,
    "stopaj_orani": 1.0,
    "google_sheets_aktif": True,
    "kategoriler": [
        "bluetooth hoparlor",
        "sac kurutma makinesi",
        "sac duzlestirici",
        "tiras makinesi",
        "mekanik klavye",
        "oyuncu mouse",
        "ssd",
        "oyuncu kulakligi",
        "bluetooth kulaklik",
        "airfryer",
        "utu",
        "dikey supurge",
        "kahve makinesi",
    ],
}

KAYNAK_SITELER = [
    ("vatanbilgisayar.com", "Vatan", "https://www.vatanbilgisayar.com/arama/{q}/"),
    ("mediamarkt.com.tr", "MediaMarkt", "https://www.mediamarkt.com.tr/tr/search.html?query={q}"),
    ("a101.com.tr", "A101", "https://www.a101.com.tr/kapida/ara?q={q}"),
    ("akakce.com", "Akakce", "https://www.akakce.com/arama/?q={q}"),
    ("cimri.com", "Cimri", "https://www.cimri.com/arama?q={q}"),
]

MARKALAR = [
    "philips", "dyson", "karaca", "tefal", "rowenta", "braun", "fakir", "arzum", "sinbo",
    "delonghi", "nespresso", "krups", "siemens", "bosch", "grundig", "arcelik", "beko",
    "samsung", "xiaomi", "roborock", "dreame", "anker", "jbl", "sony", "huawei", "apple",
    "logitech", "steelseries", "razer", "hyperx", "asus", "msi", "corsair", "kingston",
    "sandisk", "crucial", "wd", "seagate", "powertec", "remington", "babyliss",
    "schafer", "korkmaz", "emsan", "homend", "goldmaster", "vestel", "altus", "profilo", "miele",
]

RENKLER = [
    "siyah", "beyaz", "gri", "mavi", "kirmizi", "kırmızı", "pembe", "mor",
    "gold", "altin", "altın", "inox", "lacivert", "yesil", "yeşil",
    "bej", "titanyum", "turuncu", "sari", "sarı", "gümüş", "gumus",
]

AKSESUAR_YASAKLI = [
    "yedek", "başlık", "baslik", "bıçak", "bicak", "filtre", "hazne",
    "fırça", "firca", "kablo", "adaptör", "adaptor", "toz torba", "torbası",
    "kılıf", "kilif", "stand", "askı", "aski", "conta", "hortum", "boru",
    "şarj aleti", "sarj aleti", "batarya", "pil ", "pad ", "pedi",
]


def tr_duzlestir(metin):
    m = (metin or "").lower()
    return (
        m.replace("ı", "i")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ş", "s")
        .replace("ç", "c")
        .replace("ğ", "g")
    )


def kategori_eslesir_mi(metin, kategoriler):
    m = (metin or "").lower()
    m_norm = tr_duzlestir(m)
    for kat in kategoriler or []:
        k = (kat or "").lower().strip()
        if not k:
            continue
        k_norm = tr_duzlestir(k)
        if k in m or k_norm in m_norm:
            return kat
    return ""


def renk_norm(r):
    r = r.lower().strip()
    harita = {
        "kırmızı": "kirmizi",
        "altın": "gold",
        "altin": "gold",
        "yeşil": "yesil",
        "sarı": "sari",
        "gümüş": "gumus",
    }
    return harita.get(r, r)


def renk_bul(metin):
    m = (metin or "").lower()
    bulunan = set()
    for r in RENKLER:
        if re.search(r"\b" + re.escape(r) + r"\b", m):
            bulunan.add(renk_norm(r))
    return bulunan


def renk_uyumlu_mu(kaynak_metin, ty_metin):
    r1 = renk_bul(kaynak_metin)
    r2 = renk_bul(ty_metin)
    if r1 and r2 and r1.isdisjoint(r2):
        return False, f"Renk farklı ({', '.join(sorted(r1))} vs {', '.join(sorted(r2))})"
    return True, ""


def db_baslat():
    conn = sqlite3.connect(DB_DOSYA)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS firsatlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarih TEXT,
            kategori TEXT,
            kod TEXT,
            marka TEXT,
            urun_adi TEXT,
            alis_site TEXT,
            alis_fiyat REAL,
            satis_fiyat REAL,
            satis_fiyat_2 REAL DEFAULT 0,
            fiyat_makasi_tl REAL DEFAULT 0,
            fiyat_makasi_pct REAL DEFAULT 0,
            komisyon_oran REAL,
            kargo_ucret REAL,
            net_kar REAL,
            roi REAL,
            net_kar_2 REAL DEFAULT 0,
            roi_2 REAL DEFAULT 0,
            yorum_sayisi INTEGER,
            stok_durumu TEXT,
            kampanya TEXT,
            barem_onerisi TEXT,
            alis_link TEXT,
            trendyol_link TEXT,
            durum TEXT DEFAULT 'Bekliyor'
        )
        """
    )

    c.execute("PRAGMA table_info(firsatlar)")
    mevcut_sutunlar = {row[1] for row in c.fetchall()}
    ek_sutunlar = {
        "satis_fiyat_2": "REAL DEFAULT 0",
        "fiyat_makasi_tl": "REAL DEFAULT 0",
        "fiyat_makasi_pct": "REAL DEFAULT 0",
        "net_kar_2": "REAL DEFAULT 0",
        "roi_2": "REAL DEFAULT 0",
    }
    for sutun, tanim in ek_sutunlar.items():
        if sutun not in mevcut_sutunlar:
            c.execute(f"ALTER TABLE firsatlar ADD COLUMN {sutun} {tanim}")

    c.execute(
        "CREATE TABLE IF NOT EXISTS baremler (id INTEGER PRIMARY KEY AUTOINCREMENT, kategori TEXT, min_fiyat REAL, max_fiyat REAL, komisyon REAL, kargo REAL)"
    )
    c.execute("CREATE TABLE IF NOT EXISTS ozel_tarife (kod TEXT PRIMARY KEY, komisyon REAL, aciklama TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS kara_liste (kod TEXT PRIMARY KEY, sebep TEXT, tarih TEXT)")

    c.execute("SELECT COUNT(*) FROM baremler")
    if c.fetchone()[0] == 0:
        for b in VARSAYILAN_BAREMLER:
            c.execute(
                "INSERT INTO baremler (kategori, min_fiyat, max_fiyat, komisyon, kargo) VALUES (?, ?, ?, ?, ?)",
                (b["kategori"], b["min_fiyat"], b["max_fiyat"], b["komisyon"], b["kargo"]),
            )
    conn.commit()
    conn.close()

    if not os.path.exists(DURUM_DOSYA):
        try:
            with open(DURUM_DOSYA, "w", encoding="utf-8") as f:
                json.dump(VARSAYILAN_AYARLAR, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def ayar_oku():
    try:
        if os.path.exists(DURUM_DOSYA):
            with open(DURUM_DOSYA, "r", encoding="utf-8") as f:
                veri = json.load(f)
                for k, v in VARSAYILAN_AYARLAR.items():
                    veri.setdefault(k, v)
                return veri
    except Exception:
        pass
    return VARSAYILAN_AYARLAR.copy()


def bugun_kayitli_mi(kod, bugun_str):
    if not os.path.exists(DB_DOSYA):
        return False
    try:
        conn = sqlite3.connect(DB_DOSYA)
        c = conn.cursor()
        c.execute("SELECT 1 FROM firsatlar WHERE kod = ? AND tarih LIKE ?", (kod, f"{bugun_str}%"))
        var = c.fetchone() is not None
        conn.close()
        return var
    except Exception:
        return False


def kara_listede_mi(kod):
    if not os.path.exists(DB_DOSYA):
        return False
    try:
        conn = sqlite3.connect(DB_DOSYA)
        c = conn.cursor()
        c.execute("SELECT 1 FROM kara_liste WHERE kod = ?", (kod,))
        res = c.fetchone() is not None
        conn.close()
        return res
    except Exception:
        return False


def barem_listesi_al(kategori="Genel"):
    satirlar = []
    if os.path.exists(DB_DOSYA):
        try:
            conn = sqlite3.connect(DB_DOSYA)
            c = conn.cursor()
            c.execute(
                "SELECT min_fiyat, max_fiyat, komisyon, kargo FROM baremler WHERE kategori = ? ORDER BY min_fiyat ASC",
                (kategori,),
            )
            satirlar = c.fetchall()
            if not satirlar:
                c.execute(
                    "SELECT min_fiyat, max_fiyat, komisyon, kargo FROM baremler WHERE kategori = 'Genel' ORDER BY min_fiyat ASC"
                )
                satirlar = c.fetchall()
            conn.close()
        except Exception:
            satirlar = []

    if not satirlar:
        satirlar = [(b["min_fiyat"], b["max_fiyat"], b["komisyon"], b["kargo"]) for b in VARSAYILAN_BAREMLER]
    return satirlar


def net_kar_hesapla(alis, satis, kod="", kategori="Genel"):
    ayar = ayar_oku()
    hizmet = float(ayar.get("hizmet_bedeli", 10.0))
    stopaj_oran = float(ayar.get("stopaj_orani", 1.0))

    satirlar = barem_listesi_al(kategori)
    secilen_kom = 0.0
    secilen_kargo = 95.0
    for min_f, max_f, kom, kargo in satirlar:
        if min_f <= satis <= max_f:
            secilen_kom = float(kom or 0.0)
            secilen_kargo = float(kargo or 95.0)
            break

    komisyon_tutar = satis * (secilen_kom / 100.0)
    stopaj_tutar = satis * (stopaj_oran / 100.0)
    net_kar = round(satis - alis - komisyon_tutar - secilen_kargo - hizmet - stopaj_tutar, 2)
    roi = round((net_kar / alis) * 100, 1) if alis > 0 else 0.0

    return net_kar, roi, secilen_kom, secilen_kargo, ""


def sheets_kaydet(veri):
    ayar = ayar_oku()
    if not ayar.get("google_sheets_aktif", True):
        return
    ham_json = gizli_deger_oku("GOOGLE_CREDENTIALS_JSON")
    if not ham_json:
        return
    try:
        creds = ham_json if isinstance(ham_json, dict) else json.loads(ham_json)
        gc = gspread.service_account_from_dict(creds)
        ws = gc.open(SHEET_ADI).worksheet("Sheet1")
        satir = [
            veri["tarih"],
            veri["kategori"],
            veri["kod"],
            veri["marka"],
            veri["urun_adi"],
            veri["alis_site"],
            veri["alis_fiyat"],
            veri["satis_fiyat"],
            veri["satis_fiyat_2"],
            veri["fiyat_makasi_tl"],
            veri["fiyat_makasi_pct"],
            veri["komisyon_oran"],
            veri["kargo_ucret"],
            veri["net_kar"],
            veri["roi"],
            veri["net_kar_2"],
            veri["roi_2"],
            veri["yorum_sayisi"],
            veri["stok_durumu"],
            veri["kampanya"],
            veri["alis_link"],
            veri["trendyol_link"],
            veri["durum"],
        ]
        ws.append_row(satir, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"    [!] Google Sheets kayit hatasi: {str(e)[:60]}")


def telegram_uyari_gonder(veri):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        mesaj = (
            f"🚨 *YENİ FIRSAT YAKALANDI*\n"
            f"📦 *Ürün:* [{veri['kod']}] {veri['urun_adi']}\n"
            f"🛒 *Alış ({veri['alis_site']}):* {veri['alis_fiyat']} TL\n"
            f"🏷️ *Trendyol 1. Fiyat:* {veri['satis_fiyat']} TL (2. Fiyat: {veri['satis_fiyat_2']} TL)\n"
            f"💰 *Net Kâr / ROI:* {veri['net_kar']} TL (*%{veri['roi']}*)\n"
            f"⭐ *Yorum:* {veri['yorum_sayisi']} | *Stok:* {veri['stok_durumu']}\n"
            f"🔗 [Alış Linki]({veri['alis_link']}) | [Trendyol]({veri['trendyol_link']})"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": mesaj,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"    [!] Telegram uyari hatasi: {str(e)[:45]}")


def aksesuar_mi(metin):
    m = (metin or "").lower()
    return any(k in m for k in AKSESUAR_YASAKLI)


def marka_bul(metin):
    m = (metin or "").lower()
    for marka in MARKALAR:
        if re.search(r"\b" + re.escape(marka) + r"\b", m):
            return marka.upper()
    return ""


def kod_cikar(ad, link=""):
    birlesik = f"{ad} {link}".upper()
    yasakli = {
        "SERISI", "BUHARLI", "WATT", "PLUS", "PRO", "MAX", "TURKIYE",
        "ORIJINAL", "GARANTILI", "TAKSIT", "KARGO", "BEDAVA", "INDIRIM",
        "KAMPANYA", "STOKTA", "HIZLI", "TESLIMAT", "TL", "TRY", "MAH", "GB", "TB", "A101",
        "SIYAH", "BEYAZ", "GRI", "MAVI", "KIRMIZI", "PEMBE", "MOR", "GOLD", "INOX",
    }
    adaylar = re.findall(r"\b[A-Z]{1,6}[-/]?\d{3,6}(?:[-/][A-Z0-9]{1,5})?\b", birlesik)
    adaylar += re.findall(r"\b[A-Z]{2,6}[-/]?\d{2,6}(?:[-/][A-Z0-9]{1,5})?\b", birlesik)
    adaylar += re.findall(r"\b\d{3,4}[-/]?[A-Z]{2,5}\b", birlesik)

    for k in adaylar:
        temiz_kod = k.replace("-", "").replace("/", "")
        if temiz_kod not in yasakli and len(temiz_kod) >= 4:
            if re.match(r"^\d+(TL|TRY|W|GB|TB|MAH|ML|LT|CM|MM|HZ|DB|RPM)$", temiz_kod):
                continue
            return temiz_kod
    return ""


def kampanya_bul(metin):
    bulunanlar = []
    desenler = [
        r"sepette\s*%?\s*\d+(?:\s*tl|\s*indirim)?",
        r"\d+\s*al\s*\d+\s*öde",
        r"2\.\s*ürün\s*%?\s*\d+",
        r"ikincisi\s*%?\s*\d+",
        r"\d+\s*tl\s*kupon",
        r"kupon\s*fırsatı|kuponlu",
    ]
    for d in desenler:
        eslesme = re.search(d, metin or "", re.IGNORECASE)
        if eslesme:
            bulunanlar.append(eslesme.group(0).strip())
    return " + ".join(dict.fromkeys(bulunanlar))


def temiz_fiyat_bul(metin):
    gecerli_satirlar = []
    yasakli_satir = ["taksit", "puan", "garanti", "sigorta", " x ", "kazanç", "peşin", "teslimat", "hadi", "indirim", "kupon", "fark"]
    for s in (metin or "").split("\n"):
        sl = s.lower()
        if any(w in sl for w in yasakli_satir):
            continue
        gecerli_satirlar.append(s)
    temiz = " ".join(gecerli_satirlar)
    bulunan = re.findall(r"(?:₺\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?))|(?:(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:TL|₺))", temiz)
    fiyatlar = []
    for g1, g2 in bulunan:
        ham = g1 or g2
        if not ham:
            continue
        val = float(ham.replace(".", "").replace(",", "."))
        if 300 <= val <= 250000:
            fiyatlar.append(val)
    return fiyatlar


def yorum_sayisi_bul(metin):
    m1 = re.search(r"\((\d+(?:\.\d+)?)\)|(\d+(?:\.\d+)?)\s*(?:değerlendirme|yorum)", metin or "", re.IGNORECASE)
    if m1:
        ham = m1.group(1) or m1.group(2)
        return int(ham.replace(".", ""))
    m2 = re.search(r"\b[1-5][.,]\d\s+(\d{1,3}(?:\.\d{3})*|\d{1,5})\b", metin or "")
    if m2:
        return int(m2.group(1).replace(".", ""))
    return 0


def popup_temizle(page):
    try:
        for secici in [
            "#sp-cc-accept",
            "#pwa-consent-layer-accept-all-button",
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "button:has-text('Tümünü Kabul Et')",
            "button:has-text('Kabul Et')",
            ".modal-close",
            "#onetrust-accept-btn-handler",
        ]:
            el = page.locator(secici).first
            if el.is_visible(timeout=150):
                el.click(force=True)
    except Exception:
        pass


def guvenli_git(page, url, timeout=17000):
    for _ in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            if "ERR_INTERNET_DISCONNECTED" in str(e) or "ERR_NAME_NOT_RESOLVED" in str(e):
                print("    [!] Internet kesildi, 15 sn bekleniyor...")
                time.sleep(15)
            else:
                raise e
    return False


def stok_ve_fiyat_dogrula(page, link, beklenen_alis):
    try:
        if not link:
            return True, beklenen_alis, "Link Yok / Varsayilan"
        guvenli_git(page, link, timeout=16000)
        page.wait_for_timeout(1200)
        govde = (page.inner_text("body") or "").lower()

        tukendi_ifadeleri = ["tükendi", "stokta yok", "temin edilemiyor", "satışa kapalı", "mağazalarda"]
        sepete_ekle_var = any(k in govde for k in ["sepete ekle", "hemen al", "sepete at"])

        if not sepete_ekle_var and any(t in govde for t in tukendi_ifadeleri):
            return False, beklenen_alis, "Stok Yok / Tükendi"

        fiyatlar = temiz_fiyat_bul(page.inner_text("body") or "")
        yakin_fiyatlar = [f for f in fiyatlar if beklenen_alis * 0.75 <= f <= beklenen_alis * 1.25]
        dogrulanmis_fiyat = min(yakin_fiyatlar) if yakin_fiyatlar else beklenen_alis

        if sepete_ekle_var:
            return True, dogrulanmis_fiyat, "Stokta Doğrulandı"
        return True, dogrulanmis_fiyat, "Manuel Kontrol Önerilir"
    except Exception:
        return True, beklenen_alis, "Sayfa Doğrulanamadı"


def akakce_fark_atan_topla(page, kategoriler, limit=50):
    urunler = []
    print(f"[Akakce Fark Atan] Sayfa aciliyor: {AKAKCE_FARK_ATAN_URL}")
    if not guvenli_git(page, AKAKCE_FARK_ATAN_URL, timeout=20000):
        return urunler
    page.wait_for_timeout(1500)
    popup_temizle(page)

    kartlar = page.query_selector_all("li.p, li[data-pr], ul.ch_v8 li, div[class*='product'], article")
    print(f"[Akakce Fark Atan] Sayfada {len(kartlar)} kart bulundu, kategorilerle eslestiriliyor...")

    for kart in kartlar[:limit]:
        try:
            metin = (kart.inner_text() or "").strip()
            if not metin or aksesuar_mi(metin):
                continue

            eslesen_kat = kategori_eslesir_mi(metin, kategoriler)
            if not eslesen_kat:
                continue

            fiyatlar = temiz_fiyat_bul(metin)
            if not fiyatlar:
                continue

            alis_fiyat = min(fiyatlar)
            link_el = kart.query_selector("a[href]")
            href = link_el.get_attribute("href") if link_el else ""
            if href and href.startswith("/"):
                href = f"https://www.akakce.com{href}"

            satirlar = [s.strip() for s in metin.split("\n") if len(s.strip()) > 6]
            urun_adi = satirlar[0] if satirlar else metin[:120]
            kod = kod_cikar(urun_adi, href)
            if not kod:
                continue

            urunler.append(
                {
                    "kategori": eslesen_kat,
                    "kod": kod,
                    "marka": marka_bul(urun_adi),
                    "urun_adi": urun_adi[:160],
                    "alis_site": "Akakce Fark Atan",
                    "alis_fiyat": alis_fiyat,
                    "alis_link": href,
                    "kampanya": kampanya_bul(metin) or "Fark Atan Fiyat",
                }
            )
        except Exception:
            continue

    print(f"[Akakce Fark Atan] Kategoriye uyan {len(urunler)} urun secildi.")
    return urunler


def trendyol_fiyat_ara(page, kod, marka, urun_adi, min_yorum):
    sorgu = quote(f"{marka} {kod}".strip() if marka else kod)
    url = f"https://www.trendyol.com/sr?q={sorgu}"
    if not guvenli_git(page, url, timeout=17000):
        return None
    page.wait_for_timeout(1200)
    popup_temizle(page)

    kartlar = page.query_selector_all("[data-testid='product-card'], .p-card-wrppr, div[class*='product-card']")
    adaylar = []
    for kart in kartlar[:12]:
        try:
            metin = (kart.inner_text() or "").strip()
            if not metin or aksesuar_mi(metin):
                continue
            uyumlu, _ = renk_uyumlu_mu(urun_adi, metin)
            if not uyumlu:
                continue
            fiyatlar = temiz_fiyat_bul(metin)
            if not fiyatlar:
                continue
            yorum = yorum_sayisi_bul(metin)
            if yorum < min_yorum:
                continue
            link_el = kart.query_selector("a[href]")
            href = link_el.get_attribute("href") if link_el else ""
            if href and href.startswith("/"):
                href = f"https://www.trendyol.com{href}"
            adaylar.append((min(fiyatlar), yorum, href))
        except Exception:
            continue

    if not adaylar:
        return None

    adaylar.sort(key=lambda x: x[0])
    fiyat_1, yorum_1, link_1 = adaylar[0]
    fiyat_2 = adaylar[1][0] if len(adaylar) > 1 else fiyat_1
    return fiyat_1, fiyat_2, yorum_1, link_1


def firsat_kaydet(veri):
    if os.path.exists(DB_DOSYA):
        try:
            conn = sqlite3.connect(DB_DOSYA)
            conn.execute(
                """
                INSERT INTO firsatlar (
                    tarih, kategori, kod, marka, urun_adi, alis_site, alis_fiyat,
                    satis_fiyat, satis_fiyat_2, fiyat_makasi_tl, fiyat_makasi_pct,
                    komisyon_oran, kargo_ucret, net_kar, roi, net_kar_2, roi_2,
                    yorum_sayisi, stok_durumu, kampanya, barem_onerisi,
                    alis_link, trendyol_link, durum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Bekliyor')
                """,
                (
                    veri["tarih"], veri["kategori"], veri["kod"], veri["marka"], veri["urun_adi"],
                    veri["alis_site"], veri["alis_fiyat"], veri["satis_fiyat"], veri["satis_fiyat_2"],
                    veri["fiyat_makasi_tl"], veri["fiyat_makasi_pct"], veri["komisyon_oran"],
                    veri["kargo_ucret"], veri["net_kar"], veri["roi"], veri["net_kar_2"],
                    veri["roi_2"], veri["yorum_sayisi"], veri["stok_durumu"], veri["kampanya"],
                    veri["barem_onerisi"], veri["alis_link"], veri["trendyol_link"],
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"    [!] SQLite kayit hatasi: {str(e)[:60]}")

    sheets_kaydet(veri)
    telegram_uyari_gonder(veri)


def calistir(tek_tur=True):
    db_baslat()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 900})
        page = context.new_page()

        try:
            while True:
                ayar = ayar_oku()
                if not ayar.get("aktif", True):
                    if tek_tur:
                        break
                    time.sleep(10)
                    continue

                bugun_str = datetime.now().strftime("%d.%m.%Y")
                min_roi = float(ayar.get("min_roi", 15.0))
                min_yorum = int(ayar.get("min_yorum", 150))
                kategoriler = ayar.get("kategoriler") or VARSAYILAN_AYARLAR["kategoriler"]

                fark_atan_urunler = akakce_fark_atan_topla(page, kategoriler, limit=50)

                for u in fark_atan_urunler:
                    kod = u["kod"]
                    print(f"  -> Kontrol ediliyor: [{u['kategori']}] {kod} ({u['alis_fiyat']} TL)")
                    if kara_listede_mi(kod) or bugun_kayitli_mi(kod, bugun_str):
                        print("     [=] Bugun zaten kayitli veya kara listede, atlaniyor.")
                        continue

                    ty_sonuc = trendyol_fiyat_ara(page, kod, u["marka"], u["urun_adi"], min_yorum)
                    if not ty_sonuc:
                        print("     [-] Trendyol'da uygun eslesme/yorum bulunamadi.")
                        continue

                    satis_1, satis_2, yorum_sayisi, ty_link = ty_sonuc
                    stok_ok, dogrulanmis_alis, stok_durumu = stok_ve_fiyat_dogrula(
                        page, u["alis_link"], u["alis_fiyat"]
                    )
                    if not stok_ok:
                        print(f"     [-] Stok uygun degil: {stok_durumu}")
                        continue

                    net_kar, roi, kom_oran, kargo_ucret, barem_oneri = net_kar_hesapla(
                        dogrulanmis_alis, satis_1, kod=kod, kategori=u["kategori"]
                    )
                    if roi < min_roi:
                        print(f"     [-] ROI dusuk (%{roi} < %{min_roi}).")
                        continue

                    net_kar_2, roi_2, _, _, _ = net_kar_hesapla(
                        dogrulanmis_alis, satis_2, kod=kod, kategori=u["kategori"]
                    )
                    makas_tl = round(satis_2 - satis_1, 2)
                    makas_pct = round(((satis_2 - satis_1) / satis_1) * 100, 1) if satis_1 > 0 else 0.0

                    veri = {
                        "tarih": datetime.now().strftime("%d.%m.%Y %H:%M"),
                        "kategori": u["kategori"],
                        "kod": kod,
                        "marka": u["marka"],
                        "urun_adi": u["urun_adi"],
                        "alis_site": u["alis_site"],
                        "alis_fiyat": dogrulanmis_alis,
                        "satis_fiyat": satis_1,
                        "satis_fiyat_2": satis_2,
                        "fiyat_makasi_tl": makas_tl,
                        "fiyat_makasi_pct": makas_pct,
                        "komisyon_oran": kom_oran,
                        "kargo_ucret": kargo_ucret,
                        "net_kar": net_kar,
                        "roi": roi,
                        "net_kar_2": net_kar_2,
                        "roi_2": roi_2,
                        "yorum_sayisi": yorum_sayisi,
                        "stok_durumu": stok_durumu,
                        "kampanya": u["kampanya"],
                        "barem_onerisi": barem_oneri,
                        "alis_link": u["alis_link"],
                        "trendyol_link": ty_link,
                        "durum": "Bekliyor",
                    }
                    print(f"     [+] FIRSAT KAYDEDILIYOR: {kod} | Net Kar: {net_kar} TL | ROI: %{roi}")
                    firsat_kaydet(veri)

                if tek_tur:
                    break
                time.sleep(300)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    calistir(tek_tur=True)
