import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# =========================================
# Configuración de la página
# =========================================
st.set_page_config(
    page_title="Conciliaciones Payments",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================
# Login
# =========================================
from utils.auth import check_login, logout

if not check_login():
    st.stop()

# =========================================
# Sidebar - Navegación
# =========================================
with st.sidebar:
    st.image(
        "https://img.icons8.com/fluency/96/bank-building.png",
        width=60,
    )
    st.title("Conciliaciones")
    st.caption(f"Usuario: {st.session_state.get('user', '')}")
    st.divider()

    pagina = st.radio(
        "Selecciona la conciliación:",
        options=["Instant Payouts", "Payouts Regular"],
        index=0,
        label_visibility="collapsed",
    )

    st.divider()

    # Info de bancos según la conciliación seleccionada
    if pagina == "Instant Payouts":
        st.info("**Bancos:** BCP, BBVA, Yape")
    else:
        st.info("**Bancos:** BCP, BBVA, Interbank, Otros")

    st.divider()

    if st.button("Cerrar sesión", use_container_width=True):
        logout()

# =========================================
# Renderizar página seleccionada
# =========================================
if pagina == "Instant Payouts":
    from pages.instant_payouts import render
    render()
elif pagina == "Payouts Regular":
    from pages.payouts_regular import render
    render()
