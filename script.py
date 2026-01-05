import streamlit as st
import sqlite3
import pandas as pd
import re
import base64
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime

# ====== AJOUT (Google Sheets persistant) ======
import gspread
from google.oauth2.service_account import Credentials
# =============================================

# =====================================================
# CONFIGURATION GÉNÉRALE
# =====================================================

APP_TITLE = "Inscription – Compétition 1RM Bench Press & Pull-up"
DB_PATH = "app.db"  # fallback local seulement
MAX_PARTICIPANTS = 20

BG_PATH = "assets/affiche_competition.jpg"

# ===================== AJOUT (ADMIN) =====================
try:
    ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
except Exception:
    ADMIN_PASSWORD = ""

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
# =========================================================

# ===================== AJOUT (CONFIG SHEETS) =====================
# Si GSHEET_ID + gcp_service_account existent -> mode persistant Google Sheets
GSHEET_ID = ""
try:
    GSHEET_ID = st.secrets.get("GSHEET_ID", "")
except Exception:
    GSHEET_ID = ""

SHEET_TAB_NAME = "inscriptions"  # nom de l’onglet dans le Google Sheet
SHEET_HEADERS = ["nom_complet", "numero_membre", "frais_compris", "date_inscription"]
# ================================================================

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🏋️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# =====================================================
# BACKGROUND GLOBAL + OVERLAY (PALE + LISIBLE)
# =====================================================

def _guess_mime(path: str) -> str:
    return "image/png" if path.lower().endswith(".png") else "image/jpeg"

def load_image_as_base64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")

def inject_background_css(bg_path: str) -> None:
    if not Path(bg_path).exists():
        st.warning(
            f"Image de fond introuvable : `{bg_path}`\n"
            "Crée le dossier `assets/` et ajoute l’affiche."
        )
        return

    mime = _guess_mime(bg_path)
    bg_b64 = load_image_as_base64(bg_path)

    css = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800;900&display=swap');

    html, body, [class*="stApp"] {{
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    }}

    .stApp {{
      background-image: url("data:{mime};base64,{bg_b64}");
      background-repeat: no-repeat;
      background-position: top center;
      background-size: 100% auto;
      background-attachment: scroll;
      min-height: 100vh;
      position: relative;
    }}

    .stApp::before {{
      content: "";
      position: fixed;
      inset: 0;
      background: rgba(255, 255, 255, 0.92);
      z-index: 0;
      pointer-events: none;
    }}

    [data-testid="stAppViewContainer"] {{
      background: transparent;
    }}

    .block-container {{
      max-width: 760px;
      padding-top: 1.25rem;
      padding-bottom: 2rem;
      position: relative;
      z-index: 1;
    }}

    .overlay-card {{
      background: rgba(255, 255, 255, 0.97);
      border-radius: 22px;
      padding: 26px;
      margin-bottom: 26px;
      box-shadow:
        0 2px 6px rgba(0, 0, 0, 0.12),
        0 12px 20px rgba(0, 0, 0, 0.22),
        0 28px 50px rgba(0, 0, 0, 0.35),
        0 60px 90px rgba(0, 0, 0, 0.25);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
    }}

    .stApp {{
      color: #0b1220;
      font-size: 17.5px;
      font-weight: 700;
      line-height: 1.6;
    }}

    p, li, label {{
      color: #0b1220 !important;
      font-weight: 700 !important;
      letter-spacing: 0.15px;
      text-rendering: geometricPrecision;
    }}

    h1 {{
      font-size: 2.1rem !important;
      font-weight: 900 !important;
      text-shadow:
        0 1px 2px rgba(0,0,0,0.25),
        0 4px 8px rgba(0,0,0,0.25);
    }}

    h2 {{
      font-size: 1.6rem !important;
      font-weight: 900 !important;
      text-shadow:
        0 1px 2px rgba(0,0,0,0.20),
        0 3px 6px rgba(0,0,0,0.25);
    }}

    h3 {{
      font-size: 1.3rem !important;
      font-weight: 800 !important;
      text-shadow:
        0 1px 2px rgba(0,0,0,0.20),
        0 3px 6px rgba(0,0,0,0.25);
    }}

    .stButton > button {{
      width: 100%;
      height: 48px;
      border-radius: 12px;
      border: 2px solid #0077ee;
      color: #0077ee;
      font-weight: 900;
      background: #ffffff;
      box-shadow:
        0 4px 10px rgba(0,0,0,0.15),
        0 10px 24px rgba(0,0,0,0.20);
    }}

    .stTextInput input {{
      height: 48px;
      border-radius: 12px;
      background: #ffffff;
      font-weight: 800;
      color: #0b1220;
      box-shadow:
        inset 0 2px 4px rgba(0,0,0,0.15);
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

inject_background_css(BG_PATH)

# =====================================================
# STOCKAGE PERSISTANT (GOOGLE SHEETS) + FALLBACK SQLITE
# =====================================================

def using_gsheets() -> bool:
    return bool(GSHEET_ID) and ("gcp_service_account" in st.secrets)

@st.cache_resource
def _get_gspread_client():
    creds_info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

def _get_sheet():
    client = _get_gspread_client()
    sh = client.open_by_key(GSHEET_ID)
    try:
        ws = sh.worksheet(SHEET_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_TAB_NAME, rows=1000, cols=20)
    return ws

def init_storage():
    """Assure que la 'table' existe (headers)."""
    if using_gsheets():
        ws = _get_sheet()
        values = ws.get_all_values()
        if not values:
            ws.append_row(SHEET_HEADERS)
        else:
            # si le header n'est pas bon, on le force
            if [c.strip() for c in values[0]] != SHEET_HEADERS:
                ws.delete_rows(1)
                ws.insert_row(SHEET_HEADERS, 1)
    else:
        init_db_sqlite()

# -------------------- SQLITE (fallback) --------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS inscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_complet TEXT NOT NULL,
    numero_membre TEXT NOT NULL UNIQUE,
    frais_compris INTEGER NOT NULL,
    date_inscription TEXT DEFAULT (datetime('now'))
);
"""

@contextmanager
def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()

def init_db_sqlite():
    with db_connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()

# -------------------- API stockage (abstrait) --------------------

def count_registrations():
    if using_gsheets():
        ws = _get_sheet()
        # -1 pour l'entête
        n = max(len(ws.get_all_values()) - 1, 0)
        return n
    with db_connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM inscriptions").fetchone()[0]

def _gsheets_df_raw() -> pd.DataFrame:
    ws = _get_sheet()
    values = ws.get_all_values()
    if len(values) <= 1:
        return pd.DataFrame(columns=SHEET_HEADERS)
    header = values[0]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)

    # normalise types
    if "frais_compris" in df.columns:
        df["frais_compris"] = df["frais_compris"].astype(str).str.strip().replace({"True": "1", "False": "0"})
    return df

def insert_registration(nom_complet, numero_membre, frais_compris):
    if using_gsheets():
        try:
            ws = _get_sheet()
            df = _gsheets_df_raw()
            # unicité
            if not df.empty and (df["numero_membre"].astype(str).str.strip() == str(numero_membre).strip()).any():
                return False, "Ce numéro de membre est déjà inscrit."

            ws.append_row([
                str(nom_complet).strip(),
                str(numero_membre).strip(),
                str(int(bool(frais_compris))),
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ])
            return True, None
        except Exception:
            return False, "Erreur lors de l'inscription."

    # fallback sqlite
    try:
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO inscriptions (nom_complet, numero_membre, frais_compris)
                VALUES (?, ?, ?)
                """,
                (nom_complet, numero_membre, int(frais_compris)),
            )
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "Ce numéro de membre est déjà inscrit."
    except Exception:
        return False, "Erreur lors de l'inscription."

def get_registrations_df():
    if using_gsheets():
        df = _gsheets_df_raw()
        if df.empty:
            return pd.DataFrame(columns=["Nom complet", "Numéro de membre", "Frais compris", "Date d'inscription"])

        # tri desc par date si possible
        if "date_inscription" in df.columns:
            df["_date_sort"] = pd.to_datetime(df["date_inscription"], errors="coerce")
            df = df.sort_values("_date_sort", ascending=False).drop(columns=["_date_sort"], errors="ignore")

        # colonnes FR pour affichage/export
        out = df.rename(columns={
            "nom_complet": "Nom complet",
            "numero_membre": "Numéro de membre",
            "frais_compris": "Frais compris",
            "date_inscription": "Date d'inscription",
        })

        # garde l’ordre
        for c in ["Nom complet", "Numéro de membre", "Frais compris", "Date d'inscription"]:
            if c not in out.columns:
                out[c] = ""
        return out[["Nom complet", "Numéro de membre", "Frais compris", "Date d'inscription"]]

    # sqlite
    with db_connect() as conn:
        return pd.read_sql(
            """
            SELECT
                nom_complet AS "Nom complet",
                numero_membre AS "Numéro de membre",
                frais_compris AS "Frais compris",
                date_inscription AS "Date d'inscription"
            FROM inscriptions
            ORDER BY date_inscription DESC
            """,
            conn,
        )

def delete_registration_by_member(numero_membre: str):
    if using_gsheets():
        ws = _get_sheet()
        values = ws.get_all_values()
        if len(values) <= 1:
            return 0

        # Trouver les lignes à supprimer (exact match sur numero_membre)
        # Sheet rows are 1-indexed; values includes header at row 1
        target = str(numero_membre).strip()
        rows_to_delete = []
        for idx, row in enumerate(values[1:], start=2):
            if len(row) >= 2 and str(row[1]).strip() == target:
                rows_to_delete.append(idx)

        # supprimer en partant de la fin pour garder les index valides
        for r in reversed(rows_to_delete):
            ws.delete_rows(r)

        return len(rows_to_delete)

    with db_connect() as conn:
        cur = conn.execute(
            "DELETE FROM inscriptions WHERE numero_membre = ?",
            (numero_membre,),
        )
        conn.commit()
        return cur.rowcount

# init stockage au démarrage
init_storage()

# =====================================================
# VALIDATIONS
# =====================================================

def validate_full_name(name):
    return ["Nom complet invalide."] if not name or len(name.strip()) < 3 else []

def validate_member_number(number):
    if not number:
        return ["Numéro de membre requis."]
    number = number.strip()
    if not re.fullmatch(r"[A-Za-z0-9\- ]{3,30}", number):
        return ["Format du numéro de membre invalide."]
    return []

def validate_fee_ack(ack):
    return [] if ack else ["Tu dois confirmer que les frais sont compris."]

# ===================== UI ADMIN (sidebar) =====================
with st.sidebar:
    st.markdown("### Admin")
    if st.session_state.is_admin:
        st.success("Mode admin activé")
        if st.button("Se déconnecter", use_container_width=True):
            st.session_state.is_admin = False
            st.rerun()
    else:
        admin_pass = st.text_input("Mot de passe", type="password")
        if st.button("Connexion", use_container_width=True):
            if ADMIN_PASSWORD and admin_pass == ADMIN_PASSWORD:
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Mot de passe invalide.")
# =====================================================

# =====================================================
# UI
# =====================================================

st.title("🏋️ Inscription – Compétition 1RM")
st.caption("Bench Press & Pull-up · Inscription publique")

tabs = st.tabs(["Accueil", "Inscription"])

# ------------------ ACCUEIL ---------------------------
with tabs[0]:
    st.subheader("Accueil")
    st.write("Bienvenue! Inscris-toi dès maintenant à la compétition.")

    total = count_registrations()
    st.info(f"Inscriptions : **{total} / {MAX_PARTICIPANTS}**")

    with st.expander("Participants"):
        df = get_registrations_df()
        if df.empty:
            st.write("Aucune inscription.")
        else:
            st.download_button(
                "Télécharger les inscriptions",
                df.to_csv(index=False).encode("utf-8"),
                "inscriptions.csv",
                "text/csv",
            )
            df_affichage = df.drop(columns=["Frais compris"], errors="ignore")
            st.dataframe(df_affichage, use_container_width=True)

        if st.session_state.is_admin:
            st.markdown("---")
            st.markdown("### Supprimer un participant (Admin seulement)")

            if df.empty:
                st.info("Aucun participant à supprimer.")
            else:
                options = df["Numéro de membre"].astype(str).tolist()
                membre_cible = st.selectbox("Sélectionner le numéro de membre", options)

                confirm = st.checkbox("Je confirme vouloir supprimer ce participant définitivement.")
                if st.button("🗑️ Supprimer", use_container_width=True, disabled=not confirm):
                    nb = delete_registration_by_member(membre_cible)
                    if nb > 0:
                        st.success(f"Participant supprimé : {membre_cible}")
                        st.rerun()
                    else:
                        st.warning("Aucune suppression effectuée (participant introuvable).")

    st.markdown("## Informations générales")
    st.markdown("- **Date**: 21 mars 2026, 13h00")
    st.markdown("- **Prix**: 37.5 $ +tx")
    st.markdown(
        '**Pour toutes autres questions** : communiquer le Nautilus Plus Laval, '
        '<a href="tel:+14506682686" style="font-weight:700; color:#0077ee; text-decoration:none;">'
        '+1 450-668-2686</a>',
        unsafe_allow_html=True
    )

    st.markdown("---")

    st.markdown("## Règlements de la compétition")
    st.markdown("- **Échauffement**: 30 minutes avant le début")
    st.markdown("- **Tentatives**: 3 tentatives par épreuve 1RM")
    st.markdown("- **Équipement autorisé**: Ceinture de levage, protège-poignets, chaussures de levage, craie de magnésium")
    st.markdown("- **Jugement**: Respect strict des critères de technique")
    st.markdown("- **Disqualification**: Faux mouvement ou non-respect des règles")
    st.markdown("- **Résultats**: Classement par poids corporel, par catégorie et par âge")

    st.markdown("---")

    st.markdown("## Critères de réussite des mouvements")

    st.markdown("### BENCH PRESS")
    st.markdown("**Commandes de l’arbitre** (respectées durant l’essai) :")
    st.markdown('- **"Start"** : lorsque les bras sont en extension et que la barre est stabilisée, l’arbitre annonce cette commande pour débuter le mouvement.')
    st.markdown("- La barre touche le torse durant le mouvement. Aucune pause sur le torse n’est obligatoire.")
    st.markdown('- **"Rack"** : lorsque les bras sont en extension et que la barre est stabilisée, l’arbitre annonce cette commande pour déposer la barre sur les supports / barres de sécurité.')
    st.markdown("- Les talons, les fessiers et le haut du torse restent en contact avec le banc en tout temps durant le mouvement.")

    st.markdown("### PULL-UP")
    st.markdown("**Commande de l’arbitre** (respectée durant l’essai) :")
    st.markdown("- L'athlète doit avoir les bras complètement en extension avant de débuter le mouvement.")
    st.markdown("- L'athlète commence lorsqu'il le souhaite")
    st.markdown('- **"Down"** : lorsque le menton est au-dessus de la barre et que le mouvement est stable, l’arbitre annonce cette commande pour déplier les bras.')
    st.markdown('- Aucun élan n’est permis (**aucun "kipping"**).')

# ---------------- INSCRIPTION -------------------------
with tabs[1]:
    st.subheader("Inscription")

    remaining = MAX_PARTICIPANTS - count_registrations()
    if remaining <= 0:
        st.error("⛔ Inscriptions complètes.")
        st.stop()

    st.caption(f"Places restantes : {remaining}")

    with st.form("registration_form", clear_on_submit=True):
        nom_complet = st.text_input("Nom complet")
        numero_membre = st.text_input("Numéro de membre")
        frais_compris = st.checkbox("Je confirme que les frais d’inscription sont compris")
        submit = st.form_submit_button("Soumettre")

    if submit:
        errors = (
            validate_full_name(nom_complet)
            + validate_member_number(numero_membre)
            + validate_fee_ack(frais_compris)
        )

        if count_registrations() >= MAX_PARTICIPANTS:
            errors.append("Les inscriptions sont maintenant complètes.")

        if errors:
            st.error("Veuillez corriger les erreurs suivantes :")
            for e in errors:
                st.write(f"- {e}")
        else:
            ok, err = insert_registration(nom_complet.strip(), numero_membre.strip(), frais_compris)
            if ok:
                st.success("✅ Inscription confirmée! Merci 👊")
                st.balloons()
            else:
                st.error(err)
