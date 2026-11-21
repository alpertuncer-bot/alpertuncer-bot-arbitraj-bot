from datetime import datetime
import json
import os
import sqlite3
import subprocess
import gspread
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Arbitraj Kontrol Merkezi", page_icon="📊", layout="wide")

DB_DOSYA = "arbitraj.db"
DURUM_DOSYA = "bot_durum.json"
SHEET_ADI = "Arbitraj_Firsatlari"

VARSAYILAN_AYARLAR = {
    "aktif": True,
    "min_roi": 15.0,
    "kampanya_min_roi": 5.0,
    "min_yorum": 150,
    "hizmet_bedeli": 10.0,
    "stopaj_orani": 1.0,
    "google_sheets_aktif": True,
    "kategoriler": [],
}


def gizli_deger_oku(anahtar, varsayilan=None):
    deger = os.environ.get(anahtar)
    if deger:
        return deger
    try:
        return st.secrets.get(anahtar, varsayilan)
    except Exception:
        return varsayilan


def giris_kontrol():
    if st.session_state.get("giris_yapildi"):
        return True

    dogru_kullanici = gizli_deger_oku("PANEL_USERNAME", "admin")
    dogru_sifre = gizli_deger_oku("PANEL_PASSWORD", "123456")

    st.title("Giriş Yap")
    with st.form("login_form"):
        kullanici = st.text_input("Kullanıcı Adı")
        sifre = st.text_input("Şifre", type="password")
        gonder = st.form_submit_button("Giriş")

    if gonder:
        if kullanici == dogru_kullanici and sifre == dogru_sifre:
            st.session_state["giris_yapildi"] = True
            st.rerun()
        else:
            st.error("Kullanıcı adı veya şifre hatalı.")
    return False


def ayar_oku():
    if os.path.exists(DURUM_DOSYA):
        try:
            with open(DURUM_DOSYA, "r", encoding="utf-8") as f:
                veri = json.load(f)
            for k, v in VARSAYILAN_AYARLAR.items():
                veri.setdefault(k, v)
            return veri
        except Exception:
            pass
    return VARSAYILAN_AYARLAR.copy()


def ayar_yaz(veri):
    try:
        with open(DURUM_DOSYA, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Ayar dosyası yazılamadı: {e}")


def baglan():
    conn = sqlite3.connect(DB_DOSYA)
    c = conn.cursor()
    c.execute("PRAGMA table_info(firsatlar)")
    mevcut = {r[1] for r in c.fetchall()}
    if mevcut:
        eksikler = {
            "satis_fiyat_2": "REAL DEFAULT 0",
            "fiyat_makasi_tl": "REAL DEFAULT 0",
            "fiyat_makasi_pct": "REAL DEFAULT 0",
            "net_kar_2": "REAL DEFAULT 0",
            "roi_2": "REAL DEFAULT 0",
        }
        for s, t in eksikler.items():
            if s not in mevcut:
                c.execute(f"ALTER TABLE firsatlar ADD COLUMN {s} {t}")
        conn.commit()
    return conn


def sheet_verisi_cek():
    ham_json = gizli_deger_oku("GOOGLE_CREDENTIALS_JSON")
    if not ham_json:
        return [], "GOOGLE_CREDENTIALS_JSON bulunamadı."

    if isinstance(ham_json, dict):
        ham_json = json.dumps(ham_json)

    try:
        creds = json.loads(ham_json)
        gc = gspread.service_account_from_dict(creds)
        ws = gc.open(SHEET_ADI).worksheet("Sheet1")
        kayitlar = ws.get_all_records()
        return kayitlar, ""
    except Exception as e:
        return [], f"Tablo okunamadı: {e}"


if not giris_kontrol():
    st.stop()

st.title("📊 Trendyol Retail Arbitraj Kontrol Merkezi")

if st.button("Çıkış Yap"):
    st.session_state["giris_yapildi"] = False
    st.rerun()

with st.sidebar:
    st.header("⚙️ Bot & Tarama Ayarları")
    ayar = ayar_oku()

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("▶️ Başlat / Devam", use_container_width=True):
            ayar["aktif"] = True
            ayar_yaz(ayar)
            st.success("Bot aktif edildi!")
    with col_b2:
        if st.button("⏸️ Duraklat", use_container_width=True):
            ayar["aktif"] = False
            ayar_yaz(ayar)
            st.warning("Bot duraklatıldı!")

    if st.button("🚀 Arka Plan Motorunu Yeni Pencerede Aç", use_container_width=True):
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "python", "bot_motoru.py"], shell=True)
            st.info("Tarama motoru ayrı pencerede başlatıldı.")
        else:
            st.warning("Bu buton yalnızca yerel Windows ortamında yeni pencere açar.")

    st.divider()
    yeni_min_roi = st.slider("Tarama Min. Net Kâr Oranı (%)", 5.0, 50.0, float(ayar.get("min_roi", 15.0)), 1.0)
    yeni_kamp_roi = st.slider("Kampanyalı Min. Kâr (%)", 0.0, 25.0, float(ayar.get("kampanya_min_roi", 5.0)), 1.0)
    yeni_min_yorum = st.number_input("Tarama Min. Yorum Sayısı", min_value=0, max_value=5000, value=int(ayar.get("min_yorum", 150)), step=25)
    yeni_hizmet = st.number_input("Platform Hizmet Bedeli (TL)", min_value=0.0, max_value=100.0, value=float(ayar.get("hizmet_bedeli", 10.0)), step=1.0)
    yeni_stopaj = st.number_input("E-Ticaret Stopaj (%)", min_value=0.0, max_value=10.0, value=float(ayar.get("stopaj_orani", 1.0)), step=0.5)
    sheets_aktif = st.checkbox("Google Sheets'e Eşzamanlı Yaz", value=bool(ayar.get("google_sheets_aktif", True)))

    if st.button("💾 Tarama Ayarlarını Kaydet", type="primary", use_container_width=True):
        ayar["min_roi"] = yeni_min_roi
        ayar["kampanya_min_roi"] = yeni_kamp_roi
        ayar["min_yorum"] = int(yeni_min_yorum)
        ayar["hizmet_bedeli"] = yeni_hizmet
        ayar["stopaj_orani"] = yeni_stopaj
        ayar["google_sheets_aktif"] = sheets_aktif
        ayar_yaz(ayar)
        st.success("Ayarlar güncellendi!")

tab1, tab2, tab3, tab4 = st.tabs([
    "🔥 Doğrulanmış Fırsatlar (1.-2. Fiyat & Makas)",
    "📈 Komisyon Baremleri & Tarife Yükle",
    "🚫 Kara Liste (Blacklist)",
    "☁️ Google Sheets Canlı Verileri"
])

with tab1:
    if not os.path.exists(DB_DOSYA):
        st.info("Henüz veritabanı oluşturulmadı (`arbitraj.db` bulunamadı). Yerel motoru çalıştırabilir veya Google Sheets sekmesini kullanabilirsiniz.")
    else:
        conn = baglan()
        try:
            df = pd.read_sql_query("SELECT * FROM firsatlar ORDER BY id DESC", conn)
        except Exception as e:
            df = pd.DataFrame()
            st.warning(f"`firsatlar` tablosu okunamadı: {e}")
        finally:
            conn.close()

        if df.empty:
            st.warning("Henüz doğrulanmış fırsat kaydı yok. Bot taramaya devam ediyor...")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Toplam Doğrulanmış Fırsat", len(df))
            m2.metric("Ort. Net Kâr (1. Fiyat)", f"{df['net_kar'].mean():.2f} TL")
            m3.metric("Ort. ROI (1. Fiyat)", f"%{df['roi'].mean():.1f}")
            m4.metric("Satın Alınan", len(df[df["durum"] == "Satın Alındı"]))

            st.divider()
            st.subheader("🔍 Fırsat Filtreleme & Sıralama")
            f1, f2, f3, f4, f5 = st.columns([2, 1.5, 1.5, 1.5, 1.5])
            with f1:
                arama_metni = st.text_input("Ürün Adı / Model Kodu / Marka Ara", placeholder="Örn: Philips, TR1000, Kahve...")
            with f2:
                siteler = ["Tümü"] + sorted(df["alis_site"].dropna().unique().tolist())
                secili_site = st.selectbox("Alış Sitesi", siteler)
            with f3:
                durum_filtre = st.selectbox("İşlem Durumu", ["Tümü", "Bekliyor", "Satın Alındı", "İptal / Stok Yok"])
            with f4:
                filtre_min_roi = st.number_input("Min.
