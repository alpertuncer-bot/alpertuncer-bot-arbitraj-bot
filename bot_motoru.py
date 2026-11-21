import time, re, os, json, sqlite3, ctypes, gspread, requests
from datetime import datetime
from urllib.parse import quote
from playwright.sync_api import sync_playwright

try:
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), 128)
except Exception:
    pass

DB_DOSYA = "arbitraj.db"
DURUM_DOSYA = "bot_durum.json"

TELEGRAM_TOKEN = "9277087432:AAFjyJrBeESXrAcnOOOTfHHUT6FPNCsOzNw"
TELEGRAM_CHAT_ID = "8519579164"

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
        "bluetooth hoparlor", "sac kurutma makinesi", "sac duzlestirici", "tiras makinesi",
        "mekanik klavye", "oyuncu mouse", "ssd", "oyuncu kulakligi", "bluetooth kulaklik",
        "airfryer", "utu", "dikey supurge", "kahve makinesi"
    ]
}

MARKALAR = [
    "philips", "dyson", "karaca", "tefal", "rowenta", "braun", "fakir", "arzum", "sinbo",
    "delonghi", "nespresso", "krups", "siemens", "bosch", "grundig", "arcelik", "beko",
    "samsung", "xiaomi", "roborock", "dreame", "anker", "jbl", "sony", "huawei", "apple",
    "logitech", "steelseries", "razer", "hyperx", "asus", "msi", "corsair", "kingston",
    "sandisk", "crucial", "wd", "seagate", "powertec", "remington", "babyliss",
    "schafer", "korkmaz", "emsan", "homend", "goldmaster", "vestel", "altus", "profilo", "miele"
]

RENKLER = [
    "siyah", "beyaz", "gri", "mavi", "kirmizi", "kırmızı", "pembe", "mor",
    "gold", "altin", "altın", "inox", "lacivert", "yesil", "yeşil",
    "bej", "titanyum", "turuncu", "sari", "sarı", "gümüş", "gumus"
]

AKSESUAR_YASAKLI = [
    "yedek", "başlık", "baslik", "bıçak", "bicak", "filtre", "hazne",
    "fırça", "firca", "kablo", "adaptör", "adaptor", "toz torba", "torbası",
    "kılıf", "kilif", "stand", "askı", "aski", "conta", "hortum", "boru",
    "şarj aleti", "sarj aleti", "batarya", "pil ", "pad ", "pedi"
]

KAYNAK_SITELER = [
    ("akakce.com", "Akakce", "https://www.akakce.com/arama/?q={sorgu}"),
    ("vatanbilgisayar.com", "Vatan Bilgisayar", "https://www.vatanbilgisayar.com/arama/{sorgu}/"),
    ("mediamarkt.com.tr", "MediaMarkt", "https://www.mediamarkt.com.tr/tr/search.html?query={sorgu}"),
    ("a101.com.tr", "A101", "https://www.a101.com.tr/list/?search_text={sorgu}")
]

def renk_norm(r):
    r = r.lower().strip()
    harita = {
        "kırmızı": "kirmizi",
        "altın": "gold",
        "altin": "gold",
        "yeşil": "yesil",
        "sarı": "sari",
        "gümüş": "gumus"
    }
    return harita.get(r, r)

def renk_bul(metin):
    m = (metin or "").lower()
    bulunan = set()
    for r in RENKLER:
        if re.search(r'\b' + re.escape(r) + r'\b', m):
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
    c.execute("""
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
    """)

    c.execute("PRAGMA table_info(firsatlar)")
    mevcut_sutunlar = {row[1] for row in c.fetchall()}
    ek_sutunlar = {
        "satis_fiyat_2": "REAL DEFAULT 0",
        "fiyat_makasi_tl": "REAL DEFAULT 0",
        "fiyat_makasi_pct": "REAL DEFAULT 0",
        "net_kar_2": "REAL DEFAULT 0",
        "roi_2": "REAL DEFAULT 0"
    }
    for sutun, tanim in ek_sutunlar.items():
        if sutun not in mevcut_sutunlar:
            c.execute(f"ALTER TABLE firsatlar ADD COLUMN {sutun} {tanim}")

    c.execute("CREATE TABLE IF NOT EXISTS baremler (id INTEGER PRIMARY KEY AUTOINCREMENT, kategori TEXT, min_fiyat REAL, max_fiyat REAL, komisyon REAL, kargo REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS ozel_tarife (kod TEXT PRIMARY KEY, komisyon REAL, aciklama TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS kara_liste (kod TEXT PRIMARY KEY, sebep TEXT, tarih TEXT)")

    c.execute("SELECT COUNT(*) FROM baremler")
    if c.fetchone()[0] == 0:
        for b in VARSAYILAN_BAREMLER:
            c.execute("INSERT INTO baremler (kategori, min_fiyat, max_fiyat, komisyon, kargo) VALUES (?, ?, ?, ?, ?)",
                      (b["kategori"], b["min_fiyat"], b["max_fiyat"], b["komisyon"], b["kargo"]))
    conn.commit()
    conn.close()

    if not os.path.exists(DURUM_DOSYA):
        with open(DURUM_DOSYA, "w", encoding="utf-8") as f:
            json.dump(VARSAYILAN_AYARLAR, f, ensure_ascii=False, indent=2)

def bugun_kayitli_mi(kod, bugun_str):
    conn = sqlite3.connect(DB_DOSYA)
    c = conn.cursor()
    c.execute("SELECT 1 FROM firsatlar WHERE kod = ? AND tarih LIKE ?", (kod, f"{bugun_str}%"))
    var = c.fetchone() is not None
    conn.close()
    return var

def ayar_oku():
    try:
        with open(DURUM_DOSYA, "r", encoding="utf-8") as f:
            veri = json.load(f)
            for k, v in VARSAYILAN_AYARLAR.items():
                veri.setdefault(k, v)
            return veri
    except Exception:
        return VARSAYILAN_AYARLAR.copy()

def kara_listede_mi(kod):
    conn = sqlite3.connect(DB_DOSYA)
    c = conn.cursor()
    c.execute("SELECT 1 FROM kara_liste WHERE kod = ?", (kod,))
    res = c.fetchone() is not None
    conn.close()
    return res

def net_kar_hesapla(alis, satis, kod="", kategori="Genel"):
    ayar = ayar_oku()
    hizmet = float(ayar.get("hizmet_bedeli", 10.0))
    stopaj_oran = float(ayar.get("stopaj_orani", 1.0))

    conn = sqlite3.connect(DB_DOSYA)
    c = conn.cursor()
    c.execute("SELECT min_fiyat, max_fiyat, komisyon, kargo FROM baremler WHERE kategori = ? ORDER BY min_fiyat ASC", (kategori,))
    satirlar = c.fetchall()
    if not satirlar:
        c.execute("SELECT min_fiyat, max_fiyat, komisyon, kargo FROM baremler WHERE kategori = 'Genel' ORDER BY min_fiyat ASC")
        satirlar = c.fetchall()
    conn.close()

    secilen_kom = 0.0
    secilen_kargo = 95.0
    for min_f, max_f, _, kargo in satirlar:
        if min_f <= satis <= max_f:
            secilen_kargo = kargo
            break

    komisyon_tutar = 0.0
    stopaj_tutar = satis * (stopaj_oran / 100.0)
    net_kar = round(satis - alis - komisyon_tutar - secilen_kargo - hizmet - stopaj_tutar, 2)
    roi = round((net_kar / alis) * 100, 1) if alis > 0 else 0.0

    return net_kar, roi, secilen_kom, secilen_kargo, ""

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
                "disable_web_page_preview": True
            },
            timeout=10
        )
    except Exception as e:
        print(f"    [!] Telegram uyari hatasi: {str(e)[:45]}")

def aksesuar_mi(metin):
    m = metin.lower()
    return any(k in m for k in AKSESUAR_YASAKLI)

def marka_bul(metin):
    m = metin.lower()
    for marka in MARKALAR:
        if re.search(r'\b' + re.escape(marka) + r'\b', m):
            return marka.upper()
    return ""

def kod_cikar(ad, link=""):
    birlesik = f"{ad} {link}".upper()
    yasakli = {
        "SERISI", "BUHARLI", "WATT", "PLUS", "PRO", "MAX", "TURKIYE",
        "ORIJINAL", "GARANTILI", "TAKSIT", "KARGO", "BEDAVA", "INDIRIM",
        "KAMPANYA", "STOKTA", "HIZLI", "TESLIMAT", "TL", "TRY", "MAH", "GB", "TB", "A101",
        "SIYAH", "BEYAZ", "GRI", "MAVI", "KIRMIZI", "PEMBE", "MOR", "GOLD", "INOX"
    }
    adaylar = re.findall(r'\b[A-Z]{1,6}[-/]?\d{3,6}(?:[-/][A-Z0-9]{1,5})?\b', birlesik)
    adaylar += re.findall(r'\b[A-Z]{2,6}[-/]?\d{2,6}(?:[-/][A-Z0-9]{1,5})?\b', birlesik)
    adaylar += re.findall(r'\b\d{3,4}[-/]?[A-Z]{2,5}\b', birlesik)

    for k in adaylar:
        temiz_kod = k.replace("-", "").replace("/", "")
        if temiz_kod not in yasakli and len(temiz_kod) >= 4:
            if re.match(r'^\d+(TL|TRY|W|GB|TB|MAH|ML|LT|CM|MM|HZ|DB|RPM)$', temiz_kod):
                continue
            return temiz_kod
    return ""

def kampanya_bul(metin):
    bulunanlar = []
    desenler = [
        r'sepette\s*%?\s*\d+(?:\s*tl|\s*indirim)?',
        r'\d+\s*al\s*\d+\s*öde',
        r'2\.\s*ürün\s*%?\s*\d+',
        r'ikincisi\s*%?\s*\d+',
        r'\d+\s*tl\s*kupon',
        r'kupon\s*fırsatı|kuponlu'
    ]
    for d in desenler:
        eslesme = re.search(d, metin, re.IGNORECASE)
        if eslesme:
            bulunanlar.append(eslesme.group(0).strip())
    return " + ".join(dict.fromkeys(bulunanlar))

def temiz_fiyat_bul(metin):
    gecerli_satirlar = []
    yasakli_satir = ["taksit", "puan", "garanti", "sigorta", " x ", "kazanç", "peşin", "teslimat", "hadi", "indirim", "kupon", "fark"]
    for s in metin.split("\n"):
        sl = s.lower()
        if any(w in sl for w in yasakli_satir):
            continue
        gecerli_satirlar.append(s)
    temiz = " ".join(gecerli_satirlar)
    bulunan = re.findall(r'(?:₺\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?))|(?:(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:TL|₺))', temiz)
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
    m1 = re.search(r'\((\d+(?:\.\d+)?)\)|(\d+(?:\.\d+)?)\s*(?:değerlendirme|yorum)', metin, re.IGNORECASE)
    if m1:
        ham = m1.group(1) or m1.group(2)
        return int(ham.replace(".", ""))
    m2 = re.search(r'\b[1-5][.,]\d\s+(\d{1,3}(?:\.\d{3})*|\d{1,5})\b', metin)
    if m2:
        return int(m2.group(1).replace(".", ""))
    return 0

def popup_temizle(page):
    try:
        for secici in [
            "#sp-cc-accept", "#pwa-consent-layer-accept-all-button",
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "button:has-text('Tümünü Kabul Et')", "button:has-text('Kabul Et')",
            ".modal-close", "#onetrust-accept-btn-handler"
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

def sayfadan_urun_topla(page, domain, site_adi, urunler):
    if "vatanbilgisayar" in domain:
        kartlar = page.query_selector_all(".product-list, .product-list__content, div[class*='product-list']")
    elif "mediamarkt" in domain:
        kartlar = page.query_selector_all("[data-test='mms-search-srp-productlist-item'], article, div[class*='ProductWrapper']")
    elif "a101" in domain:
        kartlar = page.query_selector_all("article, a[href*='_p-'], div[class*='product-card'], div[class*='ProductCard']")
    elif "akakce" in domain:
        kartlar = page.query_selector_all("li.p, li[data-pr], div[class*='product'], article")
    elif "cimri" in domain:
        kartlar = page.query_selector_all("div.product-card")
    else:
        kartlar = []

    for kart in kartlar[:25]:
        try:
            metin = (kart.inner_text() or "").strip()
            if not metin or aksesuar_mi(metin):
                continue

            fiyatlar = temiz_fiyat_bul(metin)
            if not fiyatlar:
                continue
            alis_fiyat = min(fiyatlar)

            link_el = kart.query_selector("a[href]")
            href = (link_el.get_attribute("href") or "") if link_el else ""
            if href.startswith("/"):
                href = f"https://www.{domain}{href}"

            satirlar = [s.strip() for s in metin.split("\n") if len(s.strip()) > 6]
            urun_adi = max(satirlar, key=len) if satirlar else metin[:80]
            kod = kod_cikar(urun_adi, href) or f"PRD{abs(hash(urun_adi)) % 90000 + 10000}"
            marka = marka_bul(urun_adi) or "GENEL"
            kampanya = kampanya_bul(metin)

            urunler.append({
                "kod": kod,
                "marka": marka,
                "urun_adi": urun_adi[:140],
                "alis_site": domain,
                "alis_fiyat": alis_fiyat,
                "alis_link": href,
                "kampanya": kampanya
            })
        except Exception:
            continue

def trendyol_fiyat_bul(page, sorgu):
    ty_url = f"https://www.trendyol.com/sr?q={quote(sorgu)}"
    try:
        if not guvenli_git(page, ty_url, timeout=16000):
            return 0.0, 0.0, 0, ty_url, ""
        page.wait_for_timeout(1200)
        popup_temizle(page)
        kartlar = page.query_selector_all("[data-testid='product-card'], .p-card-wrppr, div.product-card")
        fiyat_adaylari = []
        baslik_adaylari = []
        yorum_toplam = 0

        for kart in kartlar[:8]:
            m = (kart.inner_text() or "").strip()
            if not m or aksesuar_mi(m):
                continue
            fl = temiz_fiyat_bul(m)
            if fl:
                fiyat_adaylari.append(min(fl))
            yorum_toplam = max(yorum_toplam, yorum_sayisi_bul(m))
            satirlar = [x.strip() for x in m.split("\n") if len(x.strip()) > 8]
            if satirlar:
                baslik_adaylari.append(max(satirlar, key=len))

        if not fiyat_adaylari:
            return 0.0, 0.0, yorum_toplam, ty_url, ""

        fiyat_adaylari.sort()
        fiyat_1 = fiyat_adaylari[0]
        fiyat_2 = fiyat_adaylari[1] if len(fiyat_adaylari) > 1 else fiyat_1
        baslik = baslik_adaylari[0] if baslik_adaylari else ""
        return fiyat_1, fiyat_2, yorum_toplam, ty_url, baslik
    except Exception:
        return 0.0, 0.0, 0, ty_url, ""

def sheets_satir_ekle(kaynak, aciklama, alis_fiyati, hedef, satis_fiyati):
    ham_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not ham_json:
        print("UYARI: GOOGLE_CREDENTIALS_JSON ortam değişkeni bulunamadı.")
        return

    creds_dict = json.loads(ham_json)
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open("Arbitraj_Firsatlari")
    ws = sh.worksheet("Sheet1")

    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    ws.append_row([tarih, kaynak, aciklama, alis_fiyati, hedef, satis_fiyati])

def firsat_kaydet_ve_yaz(veri, ayar):
    tarih_saat = datetime.now().strftime("%d.%m.%Y %H:%M")
    conn = sqlite3.connect(DB_DOSYA)
    c = conn.cursor()
    c.execute("""
        INSERT INTO firsatlar (
            tarih, kategori, kod, marka, urun_adi, alis_site, alis_fiyat,
            satis_fiyat, satis_fiyat_2, fiyat_makasi_tl, fiyat_makasi_pct,
            komisyon_oran, kargo_ucret, net_kar, roi, net_kar_2, roi_2,
            yorum_sayisi, stok_durumu, kampanya, barem_onerisi,
            alis_link, trendyol_link, durum
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Bekliyor')
    """, (
        tarih_saat, veri["kategori"], veri["kod"], veri["marka"], veri["urun_adi"],
        veri["alis_site"], veri["alis_fiyat"], veri["satis_fiyat"], veri["satis_fiyat_2"],
        veri["fiyat_makasi_tl"], veri["fiyat_makasi_pct"], veri["komisyon_oran"],
        veri["kargo_ucret"], veri["net_kar"], veri["roi"], veri["net_kar_2"],
        veri["roi_2"], veri["yorum_sayisi"], veri["stok_durumu"], veri["kampanya"],
        veri["barem_onerisi"], veri["alis_link"], veri["trendyol_link"]
    ))
    conn.commit()
    conn.close()

    if ayar.get("google_sheets_aktif", True):
        aciklama = (
            f"[{veri['kod']}] {veri['urun_adi']} "
            f"(ROI: %{veri['roi']}, Net: {veri['net_kar']} TL, Yorum: {veri['yorum_sayisi']})"
        )
        sheets_satir_ekle(
            veri["alis_site"],
            aciklama,
            veri["alis_fiyat"],
            "trendyol.com",
            veri["satis_fiyat"]
        )

    telegram_uyari_gonder(veri)

def bot_calistir():
    db_baslat()
    ayar = ayar_oku()
    if not ayar.get("aktif", True):
        print("Bot ayarlarda pasif durumda.")
        return

    bugun_str = datetime.now().strftime("%d.%m.%Y")
    min_roi = float(ayar.get("min_roi", 15.0))
    kampanya_min_roi = float(ayar.get("kampanya_min_roi", 5.0))
    min_yorum = int(ayar.get("min_yorum", 150))
    kategoriler = ayar.get("kategoriler") or VARSAYILAN_AYARLAR["kategoriler"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for kategori in kategoriler:
            urunler = []
            for domain, site_adi, sablon_url in KAYNAK_SITELER:
                url = sablon_url.format(sorgu=quote(kategori))
                if guvenli_git(page, url):
                    page.wait_for_timeout(1200)
                    popup_temizle(page)
                    sayfadan_urun_topla(page, domain, site_adi, urunler)

            for u in urunler:
                kod = u["kod"]
                if kara_listede_mi(kod) or bugun_kayitli_mi(kod, bugun_str):
                    continue

                sorgu = f"{u['marka']} {kod}".strip() if u["marka"] != "GENEL" else u["urun_adi"][:50]
                fiyat_1, fiyat_2, yorum_sayisi, ty_url, ty_baslik = trendyol_fiyat_bul(page, sorgu)
                if fiyat_1 <= 0 or yorum_sayisi < min_yorum:
                    continue

                uyumlu, _ = renk_uyumlu_mu(u["urun_adi"], ty_baslik)
                if not uyumlu:
                    continue

                stok_var, dogrulanmis_alis, stok_durum = stok_ve_fiyat_dogrula(page, u["alis_link"], u["alis_fiyat"])
                if not stok_var or dogrulanmis_alis <= 0:
                    continue

                net_kar, roi, kom_oran, kargo_ucret, barem_oneri = net_kar_hesapla(dogrulanmis_alis, fiyat_1, kod, kategori)
                net_kar_2, roi_2, _, _, _ = net_kar_hesapla(dogrulanmis_alis, fiyat_2, kod, kategori)
                hedef_roi = kampanya_min_roi if u["kampanya"] else min_roi

                if roi < hedef_roi or net_kar <= 0:
                    continue

                makas_tl = round(fiyat_1 - dogrulanmis_alis, 2)
                makas_pct = round((makas_tl / dogrulanmis_alis) * 100, 1)

                veri = {
                    "kategori": kategori,
                    "kod": kod,
                    "marka": u["marka"],
                    "urun_adi": u["urun_adi"],
                    "alis_site": u["alis_site"],
                    "alis_fiyat": dogrulanmis_alis,
                    "satis_fiyat": fiyat_1,
                    "satis_fiyat_2": fiyat_2,
                    "fiyat_makasi_tl": makas_tl,
                    "fiyat_makasi_pct": makas_pct,
                    "komisyon_oran": kom_oran,
                    "kargo_ucret": kargo_ucret,
                    "net_kar": net_kar,
                    "roi": roi,
                    "net_kar_2": net_kar_2,
                    "roi_2": roi_2,
                    "yorum_sayisi": yorum_sayisi,
                    "stok_durumu": stok_durum,
                    "kampanya": u["kampanya"],
                    "barem_onerisi": barem_oneri,
                    "alis_link": u["alis_link"],
                    "trendyol_link": ty_url
                }

                firsat_kaydet_ve_yaz(veri, ayar)
                print(f"[+] Kaydedildi: [{kod}] {u['urun_adi'][:40]} | Net: {net_kar} TL | ROI: %{roi}")

        browser.close()

if __name__ == "__main__":
    bot_calistir()
