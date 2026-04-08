import streamlit as st
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto (donde está app.py)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


def check_login():
    """
    Muestra la pantalla de login y retorna True si el usuario
    está autenticado, False si no.
    """
    if st.session_state.get("authenticated", False):
        return True

    st.markdown(
        """
        <div style="display:flex; justify-content:center; margin-top:60px;">
            <div style="max-width:400px; width:100%; text-align:center;">
                <h2>Conciliaciones Payments</h2>
                <p style="color:#888;">Ingresa tus credenciales para continuar</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Ingresar", use_container_width=True)

            if submitted:
                valid_user = os.getenv("APP_USERNAME", "")
                valid_pass = os.getenv("APP_PASSWORD", "")

                if not valid_user or not valid_pass:
                    st.error("Credenciales no configuradas. Revisa el archivo .env")
                elif username == valid_user and password == valid_pass:
                    st.session_state["authenticated"] = True
                    st.session_state["user"] = username
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos")

    return False


def logout():
    """Cierra la sesión del usuario."""
    st.session_state["authenticated"] = False
    st.session_state.pop("user", None)
    st.rerun()
