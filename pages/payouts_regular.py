import pandas as pd
import streamlit as st
from datetime import datetime
import re
import io

from utils.supabase_client import construir_metricas, subir_metricas, generar_session_id


# =========================================
# Funciones de procesamiento de bancos
# =========================================

def procesar_bcp(archivo, **kwargs):
    """Procesa estado de cuenta BCP para Payouts Regular."""
    bcp_eecc = pd.read_excel(archivo, skiprows=4)
    bcp_eecc["Operación - Número"] = bcp_eecc["Operación - Número"].astype(str)
    bcp_eecc = bcp_eecc[bcp_eecc["Referencia2"].str.contains("PAYOUT", case=False, na=False)]

    bcp_eecc["Hora"] = pd.to_datetime(
        bcp_eecc["Operación - Hora"], format="%H:%M:%S", errors="coerce"
    ).dt.hour

    suma_monto_por_hora = bcp_eecc.groupby("Hora")["Monto"].sum().reset_index()

    pagos_negativos = bcp_eecc[bcp_eecc["Monto"] < 0]
    fila_negativa_por_hora = pagos_negativos.sort_values("Hora").groupby("Hora").first().reset_index()

    bcp_consolidado = pd.merge(fila_negativa_por_hora, suma_monto_por_hora, on="Hora")

    cols_drop = [
        "Fecha valuta", "Descripción operación", "Saldo",
        "Sucursal - agencia", "Usuario", "UTC", "Hora",
        "Operación - Hora", "Monto_x",
    ]
    bcp_consolidado = bcp_consolidado.drop(columns=cols_drop, errors="ignore")
    bcp_consolidado = bcp_consolidado.rename(columns={"Monto_y": "Monto"})
    bcp_consolidado["name"] = "(BCP) - Banco de Crédito del Perú"

    return bcp_consolidado


def procesar_interbank(archivo, **kwargs):
    """Procesa estado de cuenta Interbank."""
    ibk_eecc = pd.read_excel(archivo, skiprows=13)
    ibk_eecc = ibk_eecc.drop(columns=["Unnamed: 0"], errors="ignore")

    columns_name = {
        "Fecha de Proc.": "Fecha",
        "Cargos": "Monto",
        "Detalle": "Referencia2",
        "Cod. de Operación": "Operación - Número",
    }
    ibk_eecc = ibk_eecc.rename(columns=columns_name)

    ibk_eecc = ibk_eecc[
        ibk_eecc["Referencia2"].str.contains(r"\bPA(Y|YOU|YOUT|YO)?\b", case=False, na=False)
    ]

    ibk_eecc["Operación - Número"] = ibk_eecc["Operación - Número"].astype(int).astype(str)
    ibk_eecc["name"] = "(Interbank) - Banco International del Perú"

    cols_drop = [
        "Fecha de Op.", "Movimiento", "Canal",
        "Cod. de Ubicación", "Abonos", "Saldo contable",
    ]
    ibk_eecc = ibk_eecc.drop(columns=cols_drop, errors="ignore")

    return ibk_eecc


def procesar_bbva_otros(archivo, payouts_metabase_df=None, **kwargs):
    """Procesa estado de cuenta BBVA y Otros bancos."""
    bancos_bbva = pd.read_excel(archivo, skiprows=10)

    columns_name = {
        "F. Operación": "Fecha",
        "Concepto": "Referencia2",
        "Importe": "Monto",
        "Nº. Doc.": "Operación - Número",
    }
    bancos_bbva = bancos_bbva.rename(columns=columns_name)

    # --- BBVA directo ---
    if payouts_metabase_df is not None:
        valores_metabase = (
            payouts_metabase_df[payouts_metabase_df["name"] == "(BBVA) - BBVA Continental"]["ope_psp"]
            .dropna()
            .astype(str)
            .unique()
        )
    else:
        valores_metabase = []

    df_bbva = bancos_bbva[
        bancos_bbva["Operación - Número"]
        .astype(str)
        .apply(lambda x: any(valor in x for valor in valores_metabase))
    ].copy()
    df_bbva["Operación - Número"] = df_bbva["Operación - Número"].astype(int).astype(str)
    df_bbva["name"] = "(BBVA) - BBVA Continental"

    # --- Otros bancos (BXI) ---
    df_otros = bancos_bbva[
        bancos_bbva["Referencia2"].astype(str).str.contains("BXI", case=False, na=False)
    ].copy()

    df_otros["Operación - Número"] = df_otros["Referencia2"].astype(str).apply(
        lambda x: str(int(re.search(r"(\d{5,})$", x).group(1)))
        if re.search(r"(\d{5,})$", x)
        else None
    )
    df_otros["name"] = "Otros bancos"

    bancos_bbva_filtrado = pd.concat([df_bbva, df_otros], ignore_index=True)
    bancos_bbva_filtrado = bancos_bbva_filtrado.drop(
        columns=["F. Valor", "Código", "Oficina"], errors="ignore"
    )

    return bancos_bbva_filtrado


PROCESADORES_BANCO = {
    "bcp": procesar_bcp,
    "ibk": procesar_interbank,
    "bbva": procesar_bbva_otros,
}


# =========================================
# Página principal de Payouts Regular
# =========================================

def render():
    """Renderiza la página de conciliación de Payouts Regular."""

    st.title("Conciliación Payouts Regular")
    st.caption("Conciliación diaria de operaciones Payouts Regular vs estados de cuenta bancarios")

    # --- Inicializar session_state ---
    defaults = {
        "po_metabase_df": None,
        "po_metricas_subidas": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # =========================================
    # PARTE 1: Subida y lectura de Metabase
    # =========================================
    st.header("1. Archivo Metabase")

    payouts_metabase = st.file_uploader(
        "Sube el archivo de payouts del metabase:",
        type=["xlsx"],
        key="po_uploader_metabase",
    )

    if payouts_metabase is not None:
        payouts_metabase_df = pd.read_excel(payouts_metabase)

        payouts_metabase_df["ope_psp"] = (
            pd.to_numeric(payouts_metabase_df["ope_psp"], errors="coerce")
            .astype("Int64")
            .astype(str)
        )

        payouts_metabase_df["fecha_proceso"] = pd.to_datetime(
            payouts_metabase_df["fecha pagado / rechazado"]
        ).dt.date
        payouts_metabase_df["fecha_proceso"] = pd.to_datetime(payouts_metabase_df["fecha_proceso"])

        payouts_metabase_df["hora"] = payouts_metabase_df["fecha proceso"].dt.hour
        payouts_metabase_df["date"] = payouts_metabase_df["fecha proceso"].dt.date

        fecha = pd.to_datetime(payouts_metabase_df["fecha_proceso"].unique()[0]).strftime("%Y%m%d")

        payouts_metabase_df = payouts_metabase_df[payouts_metabase_df["estado"] == "Pagado"]
        payouts_metabase_df = payouts_metabase_df[payouts_metabase_df["moneda"] == "PEN"]
        payouts_metabase_df = payouts_metabase_df[
            payouts_metabase_df["name"] != "(Scotiabank)- Scotiabank"
        ]

        st.session_state.po_metabase_df = payouts_metabase_df

        pivot_payouts = payouts_metabase_df.groupby(["fecha_proceso", "name"])[
            "monto total"
        ].sum().reset_index()

        group_hour = (
            payouts_metabase_df.groupby(["name", "ope_psp"])
            .agg({"monto total": "sum"})
            .reset_index()
        )
        group_hour = group_hour.rename(columns={"ope_psp": "Operación - Número"})

        # --- KPIs Metabase ---
        kpi1, kpi2, kpi3 = st.columns(3)
        with kpi1:
            st.metric("Transacciones Metabase", len(payouts_metabase_df))
        with kpi2:
            st.metric("Monto Total Metabase", f"S/ {pivot_payouts['monto total'].sum():,.2f}")
        with kpi3:
            st.metric("Bancos", len(pivot_payouts["name"].unique()))

        st.dataframe(pivot_payouts, use_container_width=True)

        # =========================================
        # PARTE 2: Estados de cuenta
        # =========================================
        st.header("2. Estados de Cuenta")

        estado_cuenta = st.file_uploader(
            "Subir estados de cuenta (BCP / IBK / BBVA):",
            type=["xlsx", "xls"],
            accept_multiple_files=True,
            key="po_uploader_eecc",
        )

        df_consolidados = []

        if estado_cuenta:
            for archivo in estado_cuenta:
                nombre_archivo = archivo.name.lower()
                procesador = None
                for clave, funcion in PROCESADORES_BANCO.items():
                    if clave in nombre_archivo:
                        procesador = funcion
                        break

                if procesador:
                    try:
                        df = procesador(archivo, payouts_metabase_df=payouts_metabase_df)
                        df_consolidados.append(df)
                        st.success(f"Archivo procesado: {archivo.name}")
                    except Exception as e:
                        st.error(f"Error al procesar {archivo.name}: {e}")
                else:
                    st.warning(
                        f"No se encontró procesador para: {archivo.name}. "
                        "El nombre debe contener 'bcp', 'ibk' o 'bbva'."
                    )

        if df_consolidados:
            # Marcar inicio de conciliación para métricas
            tiempo_inicio = datetime.now()

            df_final = pd.concat(df_consolidados, ignore_index=True)

            st.subheader("Datos consolidados de bancos")

            df_final_group = (
                df_final.groupby(["name", "Operación - Número"])
                .agg({"Monto": "sum"})
                .reset_index()
            )

            group_hour = (
                payouts_metabase_df.groupby(["name", "ope_psp"])
                .agg({"monto total": "sum", "hora": lambda x: x.unique()[0]})
                .reset_index()
            )
            group_hour = group_hour.rename(columns={"ope_psp": "Operación - Número"})

            with st.expander("Ver datos consolidados de bancos"):
                st.dataframe(df_final, use_container_width=True)

            merge_op = pd.merge(df_final_group, group_hour, on="Operación - Número", how="outer")
            merge_op["Diferencias"] = round((merge_op["monto total"] + merge_op["Monto"]), 2)
            merge_op = merge_op[merge_op["Diferencias"] != 0]

            bancos_montos = df_final.groupby("name")["Monto"].sum().reset_index()
            bancos_montos["Monto"] = bancos_montos["Monto"].abs()

            # =========================================
            # PARTE 3: Conciliación
            # =========================================
            st.header("3. Conciliación")
            st.write(
                "Comparación de montos entre estados de cuenta y metabase "
                "para analizar los cortes de payouts regulares."
            )

            conciliacion_payouts = pd.merge(pivot_payouts, bancos_montos, on="name", how="outer")
            conciliacion_payouts["Diferencia"] = round(
                conciliacion_payouts["monto total"] - conciliacion_payouts["Monto"], 2
            )
            conciliacion_payouts["Estado"] = conciliacion_payouts["Diferencia"].apply(
                lambda x: "Conciliado" if x == 0 else "Diferencias"
            )

            columns_rename = {
                "fecha_proceso": "FechaTexto",
                "name": "BANCO",
                "monto total": "Monto Kashio",
                "Monto": "Monto Banco",
            }
            conciliacion_payouts = conciliacion_payouts.rename(columns=columns_rename)
            conciliacion_payouts["FechaTexto"] = conciliacion_payouts["FechaTexto"].fillna(
                conciliacion_payouts["FechaTexto"].values[0]
            )

            # --- KPIs de conciliación ---
            total_diferencia = round(conciliacion_payouts["Diferencia"].sum(), 2)
            bancos_conciliados = len(conciliacion_payouts[conciliacion_payouts["Estado"] == "Conciliado"])
            bancos_con_dif = len(conciliacion_payouts[conciliacion_payouts["Estado"] == "Diferencias"])

            kpi_c1, kpi_c2, kpi_c3 = st.columns(3)
            with kpi_c1:
                st.metric("Bancos conciliados", bancos_conciliados)
            with kpi_c2:
                st.metric("Bancos con diferencias", bancos_con_dif)
            with kpi_c3:
                st.metric(
                    "Diferencia total",
                    f"S/ {total_diferencia:,.2f}",
                    delta_color="inverse" if total_diferencia != 0 else "off",
                )

            st.dataframe(conciliacion_payouts, use_container_width=True)

            payouts_metabase_df["Estado"] = f"Conciliacion_{fecha}"

            # --- Subida de métricas a Supabase (1 fila por banco) ---
            tiempo_fin = datetime.now()

            if not st.session_state.po_metricas_subidas:
                nota_input = st.text_area(
                    "Nota (opcional — explica diferencias si las hay):",
                    placeholder="Ej: Diferencia de 200 corresponde a rechazo no ejecutado de Inswitch...",
                    key="po_nota",
                )

                registrar = st.button(
                    "REGISTRAR CONCILIACIÓN EN SUPABASE",
                    use_container_width=True,
                    key="po_btn_supabase",
                )
                if registrar:
                    session_id = generar_session_id()
                    registros = []

                    for _, fila in conciliacion_payouts.iterrows():
                        banco_nombre = fila["BANCO"]
                        monto_meta = fila["Monto Kashio"]
                        monto_bco = fila["Monto Banco"]
                        diferencia = fila["Diferencia"]
                        resultado_banco = "CONCILIADO" if diferencia == 0 else "DISCREPANCIAS"

                        registros.append(construir_metricas(
                            fecha_inicio=tiempo_inicio,
                            fecha_fin=tiempo_fin,
                            operador_dispersion=str(banco_nombre),
                            tipo_conciliacion="payouts_regular_diaria",
                            monto_metabase=float(monto_meta) if pd.notna(monto_meta) else None,
                            monto_banco_total=float(monto_bco) if pd.notna(monto_bco) else None,
                            suma_diferencias=float(diferencia) if pd.notna(diferencia) else 0.0,
                            resultado_conciliacion=resultado_banco,
                            session_id=session_id,
                            nota=nota_input or None,
                        ))

                    if subir_metricas(registros):
                        st.success(f"Métricas registradas en Supabase ({len(registros)} bancos)")
                        st.session_state.po_metricas_subidas = True
                    else:
                        st.error("No se pudieron registrar las métricas")

            # --- Diferencias ---
            if "Diferencias" in conciliacion_payouts["Estado"].values:
                st.warning("Se detectaron diferencias en la conciliación")

                if "Banco metabase" not in merge_op.columns:
                    cols_rename_merge = {
                        "name_x": "Banco estados de cuenta",
                        "Operación - Número": "Numero operacion banco",
                        "Monto": "Monto bancos",
                        "name_y": "Banco metabase",
                        "monto total": "Monto metabase",
                    }
                    merge_op = merge_op.rename(columns=cols_rename_merge)

                    merge_op["Banco final"] = merge_op["Banco metabase"].combine_first(
                        merge_op["Banco estados de cuenta"]
                    )
                    bancos_con_diferencias = conciliacion_payouts[
                        conciliacion_payouts["Diferencia"] != 0
                    ]["BANCO"].unique()

                    merge_op_filtrado = merge_op[merge_op["Banco final"].isin(bancos_con_diferencias)]

                    with st.expander("Detalle de diferencias"):
                        st.dataframe(merge_op_filtrado.iloc[:, :7], use_container_width=True)

                    diferencias_ = payouts_metabase_df["ope_psp"].isin(merge_op["Numero operacion banco"])
                    payouts_metabase_df.loc[diferencias_, "Estado"] = (
                        f"Conciliacion_{fecha} - Diferencias"
                    )

            else:
                st.success("No se encontraron diferencias en la conciliación")

            # =========================================
            # PARTE 4: Descarga
            # =========================================
            st.header("4. Descarga")

            archivo_nombre = f"Conciliacion_{fecha}.xlsx"
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                payouts_metabase_df.to_excel(writer, sheet_name="Payouts_Metabase", index=False)
                df_final.to_excel(writer, sheet_name="Operaciones Bancos", index=False)

            st.download_button(
                label="Descargar conciliación completa",
                data=excel_buffer.getvalue(),
                file_name=archivo_nombre,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="po_download_conciliacion",
            )
