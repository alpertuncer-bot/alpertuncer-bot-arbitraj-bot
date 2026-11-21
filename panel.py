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
                filtre_min_roi = st.number_input("Min. ROI (%)", min_value=-50.0, max_value=500.0, value=0.0, step=1.0)
            with f5:
                filtre_min_yorum = st.number_input("Min. Yorum Sayısı", min_value=0, max_value=50000, value=0, step=50)

            siralama_secenek = st.radio(
                "Sıralama Ölçütü:",
                ["En Yeni Eklenen", "En Yüksek ROI (%)", "En Yüksek Net Kâr (TL)", "En Çok Yorum Alan", "En Düşük Alış Fiyatı"],
                horizontal=True
            )

            f_df = df.copy()
            if arama_metni:
                q = arama_metni.lower()
                f_df = f_df[
                    f_df["urun_adi"].str.lower().str.contains(q, na=False) |
                    f_df["kod"].str.lower().str.contains(q, na=False) |
                    f_df["marka"].str.lower().str.contains(q, na=False)
                ]
            if secili_site != "Tümü":
                f_df = f_df[f_df["alis_site"] == secili_site]
            if durum_filtre != "Tümü":
                f_df = f_df[f_df["durum"] == durum_filtre]

            f_df = f_df[(f_df["roi"] >= filtre_min_roi) & (f_df["yorum_sayisi"] >= filtre_min_yorum)]

            if siralama_secenek == "En Yüksek ROI (%)":
                f_df = f_df.sort_values(by="roi", ascending=False)
            elif siralama_secenek == "En Yüksek Net Kâr (TL)":
                f_df = f_df.sort_values(by="net_kar", ascending=False)
            elif siralama_secenek == "En Çok Yorum Alan":
                f_df = f_df.sort_values(by="yorum_sayisi", ascending=False)
            elif siralama_secenek == "En Düşük Alış Fiyatı":
                f_df = f_df.sort_values(by="alis_fiyat", ascending=True)

            st.caption(f"Gösterilen kayıt sayısı: **{len(f_df)}**")

            tablo_df = f_df[[
                "id", "kod", "urun_adi", "alis_site", "alis_fiyat", "alis_link",
                "satis_fiyat", "satis_fiyat_2", "fiyat_makasi_tl", "fiyat_makasi_pct",
                "yorum_sayisi", "trendyol_link", "net_kar", "roi", "net_kar_2", "roi_2", "durum"
            ]].copy()

            st.dataframe(
                tablo_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID", width="small"),
                    "kod": st.column_config.TextColumn("Model Kodu", width="small"),
                    "urun_adi": st.column_config.TextColumn("Ürün Adı", width="large"),
                    "alis_site": st.column_config.TextColumn("Alış Sitesi", width="medium"),
                    "alis_fiyat": st.column_config.NumberColumn("Alış Fiyatı", format="%.2f TL"),
                    "alis_link": st.column_config.LinkColumn("Alış Linki", display_text="🛒 Ürüne Git"),
                    "satis_fiyat": st.column_config.NumberColumn("1. Satış Fiyatı", format="%.2f TL"),
                    "satis_fiyat_2": st.column_config.NumberColumn("2. Satış Fiyatı", format="%.2f TL"),
                    "fiyat_makasi_tl": st.column_config.NumberColumn("Makas (TL)", format="+%.2f TL"),
                    "fiyat_makasi_pct": st.column_config.NumberColumn("Makas (%)", format="%%%.1f"),
                    "yorum_sayisi": st.column_config.NumberColumn("Satış Yorum", format="%d ⭐"),
                    "trendyol_link": st.column_config.LinkColumn("Satış Linki (TY)", display_text="🟠 TY İlanı"),
                    "net_kar": st.column_config.NumberColumn("Net Kâr (1. Fiyat)", format="%.2f TL"),
                    "roi": st.column_config.NumberColumn("ROI 1 (%)", format="%%%.1f"),
                    "net_kar_2": st.column_config.NumberColumn("Net Kâr (2. Fiyat)", format="%.2f TL"),
                    "roi_2": st.column_config.NumberColumn("ROI 2 (%)", format="%%%.1f"),
                    "durum": st.column_config.TextColumn("Durum")
                }
            )

            with st.expander("⚡ Hızlı İşlem & 1.-2. Fiyat Makas Detayı", expanded=True):
                for _, row in f_df.head(30).iterrows():
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([3.5, 2.2, 2.3, 2])
                        with c1:
                            st.markdown(f"**[{row['kod']}] {row['urun_adi']}**")
                            st.caption(f"📅 {row['tarih']} | Marka: `{row['marka'] or 'Belirsiz'}` | ⭐ **{row['yorum_sayisi']} Yorum** | {row['stok_durumu']}")
                            if row["kampanya"]:
                                st.warning(f"🎁 Kampanya: {row['kampanya']}")
                            if row["barem_onerisi"]:
                                st.info(f"💡 {row['barem_onerisi']}")
                        with c2:
                            st.markdown(f"**Alış ({row['alis_site']}):** `{row['alis_fiyat']:,.2f} TL`")
                            st.markdown(f"**1. Fiyat / 2. Fiyat:** `{row['satis_fiyat']:,.2f} TL` / `{row['satis_fiyat_2']:,.2f} TL`")
                            st.caption(f"Makas: `+{row['fiyat_makasi_tl']:,.2f} TL` (`%{row['fiyat_makasi_pct']}`) | Kom: `%{row['komisyon_oran']}`")
                        with c3:
                            st.markdown(f"### 💰 +{row['net_kar']:,.2f} TL (`%{row['roi']}`)")
                            st.caption(f"2. Fiyata Göre Kâr: `+{row['net_kar_2']:,.2f} TL` (`%{row['roi_2']}`)")
                            st.caption(f"Durum: **{row['durum']}**")
                        with c4:
                            st.link_button("🛒 Alış Sitesine Git", row["alis_link"], use_container_width=True)
                            if row["trendyol_link"]:
                                st.link_button("🟠 Trendyol İlanı", row["trendyol_link"], use_container_width=True)
                            b_al, b_red = st.columns(2)
                            with b_al:
                                if st.button("✅ Aldım", key=f"al_{row['id']}", use_container_width=True):
                                    conn = baglan()
                                    conn.execute("UPDATE firsatlar SET durum = 'Satın Alındı' WHERE id = ?", (row["id"],))
                                    conn.commit()
                                    conn.close()
                                    st.rerun()
                            with b_red:
                                if st.button("🚫 Engelle", key=f"bl_{row['id']}", use_container_width=True):
                                    conn = baglan()
                                    conn.execute(
                                        "INSERT OR IGNORE INTO kara_liste (kod, sebep, tarih) VALUES (?, ?, ?)",
                                        (row["kod"], "Panelden engellendi", datetime.now().strftime("%d.%m.%Y"))
                                    )
                                    conn.execute("UPDATE firsatlar SET durum = 'İptal / Stok Yok' WHERE id = ?", (row["id"],))
                                    conn.commit()
                                    conn.close()
                                    st.rerun()

with tab2:
    st.subheader("Trendyol Fiyat Baremli Komisyon & Kargo Tablosu")
    st.write("Haftada 2 kez değişen komisyon baremlerini tablodan düzenleyebilir veya Trendyol'dan indirdiğiniz güncel tarife Excel/CSV dosyasını yükleyebilirsiniz.")

    if os.path.exists(DB_DOSYA):
        conn = baglan()
        try:
            barem_df = pd.read_sql_query("SELECT kategori, min_fiyat, max_fiyat, komisyon, kargo FROM baremler", conn)
        except Exception:
            barem_df = pd.DataFrame(columns=["kategori", "min_fiyat", "max_fiyat", "komisyon", "kargo"])
        conn.close()

        duzenlenen = st.data_editor(barem_df, num_rows="dynamic", use_container_width=True)
        if st.button("💾 Barem Tablosunu Güncelle", type="primary"):
            conn = baglan()
            conn.execute("DELETE FROM baremler")
            for _, r in duzenlenen.iterrows():
                conn.execute(
                    "INSERT INTO baremler (kategori, min_fiyat, max_fiyat, komisyon, kargo) VALUES (?, ?, ?, ?, ?)",
                    (str(r["kategori"]), float(r["min_fiyat"]), float(r["max_fiyat"]), float(r["komisyon"]), float(r["kargo"]))
                )
            conn.commit()
            conn.close()
            st.success("Komisyon baremleri kaydedildi!")

    st.divider()
    st.subheader("📥 Trendyol Komisyon Tarifesi Excel / CSV Yükle")
    yuklenen = st.file_uploader("Dosya Seçin (.xlsx veya .csv)", type=["xlsx", "csv"])
    if yuklenen is not None:
        t_df = pd.read_csv(yuklenen) if yuklenen.name.endswith(".csv") else pd.read_excel(yuklenen)
        st.dataframe(t_df.head(10), use_container_width=True)
        kod_sutun = st.selectbox("Model Kodu / Barkod Sütunu", t_df.columns)
        kom_sutun = st.selectbox("Komisyon Oranı (%) Sütunu", t_df.columns)
        if st.button("🚀 Özel Komisyon Oranlarını Sisteme İşle"):
            conn = baglan()
            sayac = 0
            for _, r in t_df.iterrows():
                k_val = str(r[kod_sutun]).strip().upper().replace("-", "")
                try:
                    c_val = float(str(r[kom_sutun]).replace("%", "").replace(",", ".").strip())
                    if k_val and 0 < c_val < 60:
                        conn.execute(
                            "INSERT OR REPLACE INTO ozel_tarife (kod, komisyon, aciklama) VALUES (?, ?, ?)",
                            (k_val, c_val, yuklenen.name)
                        )
                        sayac += 1
                except Exception:
                    continue
            conn.commit()
            conn.close()
            st.success(f"{sayac} adet ürün için özel komisyon oranı tanımlandı!")

with tab3:
    st.subheader("🚫 Kara Liste (Bir Daha Taranmayacak Modeller)")
    if os.path.exists(DB_DOSYA):
        conn = baglan()
        try:
            kl_df = pd.read_sql_query("SELECT * FROM kara_liste", conn)
        except Exception:
            kl_df = pd.DataFrame()
        st.dataframe(kl_df, use_container_width=True)
        sil_kod = st.text_input("Kara Listeden Çıkarılacak Model Kodu")
        if st.button("Listeden Çıkar") and sil_kod:
            conn.execute("DELETE FROM kara_liste WHERE kod = ?", (sil_kod.strip().upper(),))
            conn.commit()
            st.success(f"{sil_kod} kara listeden çıkarıldı.")
            st.rerun()
        conn.close()

with tab4:
    st.subheader("☁️ Google Sheets Canlı Verileri")
    kayitlar, hata = sheet_verisi_cek()
    if hata:
        st.warning(hata)
    elif kayitlar:
        st.dataframe(pd.DataFrame(kayitlar), use_container_width=True)
    else:
        st.info("Google Sheets tablosunda kayıt bulunmuyor.")