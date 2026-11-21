import json
import os
import gspread
import streamlit as st

st.set_page_config(page_title="Arbitraj Paneli", layout="wide")

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

DURUM_DOSYA = "bot_durum.json"
SHEET_ADI = "Arbitraj_Firsatlari"


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


def ayar_yukle():
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


def ayar_kaydet(veri):
    with open(DURUM_DOSYA, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)


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

st.title("Arbitraj Fırsat Paneli")

if st.button("Çıkış Yap"):
    st.session_state["giris_yapildi"] = False
    st.rerun()

ayar = ayar_yukle()
kayitlar, hata = sheet_verisi_cek()

col1, col2, col3 = st.columns(3)
col1.metric("Toplam Kayıt", len(kayitlar))
col2.metric("Bot Durumu", "Aktif" if ayar.get("aktif", True) else "Pasif")
col3.metric("Min ROI", f"%{ayar.get('min_roi', 15.0)}")

st.subheader("Son Fırsatlar (Google Sheets)")
if hata:
    st.warning(hata)
elif kayitlar:
    st.dataframe(kayitlar, use_container_width=True)
else:
    st.info("Henüz kayıt bulunmuyor.")

st.subheader("Bot Ayarları")
with st.form("ayar_form"):
    aktif = st.checkbox("Bot Aktif", value=bool(ayar.get("aktif", True)))
    sheets_aktif = st.checkbox("Google Sheets Kaydı Aktif", value=bool(ayar.get("google_sheets_aktif", True)))
    min_roi = st.number_input("Minimum ROI (%)", min_value=0.0, value=float(ayar.get("min_roi", 15.0)), step=1.0)
    kampanya_min_roi = st.number_input("Kampanyalı Minimum ROI (%)", min_value=0.0, value=float(ayar.get("kampanya_min_roi", 5.0)), step=1.0)
    min_yorum = st.number_input("Minimum Yorum Sayısı", min_value=0, value=int(ayar.get("min_yorum", 150)), step=10)
    kategoriler_metin = st.text_area(
        "Kategoriler (her satıra bir kategori)",
        value="\n".join(ayar.get("kategoriler", []))
    )
    kaydet = st.form_submit_button("Ayarları Kaydet")

if kaydet:
    yeni_ayar = ayar.copy()
    yeni_ayar["aktif"] = aktif
    yeni_ayar["google_sheets_aktif"] = sheets_aktif
    yeni_ayar["min_roi"] = min_roi
    yeni_ayar["kampanya_min_roi"] = kampanya_min_roi
    yeni_ayar["min_yorum"] = int(min_yorum)
    yeni_ayar["kategoriler"] = [satir.strip() for satir in kategoriler_metin.splitlines() if satir.strip()]
    ayar_kaydet(yeni_ayar)
    st.success("Ayarlar kaydedildi.")
