import os
import streamlit as st
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# Cargar .env desde la raíz del proyecto (donde está app.py)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

TABLA_METRICAS = "conciliaciones_metricas"


def get_supabase_client() -> Client | None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.warning("Supabase no configurado. Revisa SUPABASE_URL y SUPABASE_KEY en .env")
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def generar_session_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S_") + str(hash(datetime.now()))[-6:]


def subir_metricas(metricas: list[dict] | dict) -> bool:
    """
    Sube uno o varios registros de métricas a Supabase.
    Acepta un dict (1 registro) o una lista de dicts (varios registros).
    """
    client = get_supabase_client()
    if client is None:
        return False

    try:
        payload = metricas if isinstance(metricas, list) else [metricas]
        response = client.table(TABLA_METRICAS).insert(payload).execute()
        return len(response.data) > 0
    except Exception as e:
        st.error(f"Error al subir métricas a Supabase: {e}")
        return False


def construir_metricas(
    fecha_inicio: datetime,
    fecha_fin: datetime,
    operador_dispersion: str,
    tipo_conciliacion: str,
    monto_metabase: float | None,
    monto_banco_total: float | None,
    suma_diferencias: float,
    resultado_conciliacion: str,
    session_id: str,
    tx_metabase: int | None = None,
    tx_banco: int | None = None,
    tx_con_discrepancia: int | None = None,
    nota: str | None = None,
    estado: str = "SUCCESS",
) -> dict:
    """
    Construye un dict de métricas listo para subir a Supabase.

    - operador_dispersion identifica el banco/operador de cada fila.
    - tx_metabase, tx_banco, tx_con_discrepancia son opcionales:
        IPO los llena, PO los deja en None.
    - nota es opcional: se llena cuando hay DISCREPANCIAS.
    - session_id es el mismo para todas las filas del mismo run.
    """
    duracion_ms = int((fecha_fin - fecha_inicio).total_seconds() * 1000)

    return {
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "duracion_ms": duracion_ms,
        "operador_dispersion": operador_dispersion,
        "tipo_conciliacion": tipo_conciliacion,
        "monto_metabase": str(round(monto_metabase, 2)) if monto_metabase is not None else None,
        "monto_banco_total": str(round(monto_banco_total, 2)) if monto_banco_total is not None else None,
        "suma_diferencias": str(round(suma_diferencias, 2)),
        "resultado_conciliacion": resultado_conciliacion,
        "session_id": session_id,
        "tx_metabase": tx_metabase,
        "tx_banco": tx_banco,
        "tx_con_discrepancia": tx_con_discrepancia,
        "nota": nota if nota and nota.strip() else None,
        "estado": estado,
    }
