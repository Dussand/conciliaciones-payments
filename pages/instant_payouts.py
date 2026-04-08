import pandas as pd
import streamlit as st
from datetime import datetime, time, date
import io

from utils.supabase_client import construir_metricas, subir_metricas, generar_session_id


# =========================================
# Funciones de procesamiento de bancos
# =========================================

def extraer_codigo(row):
    banco   = row['banco']
    concepto = str(row['numero de operacion'])
    monto   = str(row['monto'])

    if banco == '(BCP) - Banco de Crédito del Perú':
        codigo = concepto[18:27]
    elif banco == '(BBVA) - BBVA Continental':
        codigo = concepto[:10]
    elif banco == 'Yape':
        codigo = concepto[-11:]
    else:
        codigo = ''

    monto_cuatro_digitos = monto.replace('.', '').replace(',', '')[:4]
    return f'{codigo}{monto_cuatro_digitos}'


def procesar_bcp(estado_cuenta):
    estado_cuenta_df = pd.read_excel(estado_cuenta, skiprows=4)

    columns_drop_eecc = [
        'Fecha valuta', 'Saldo', 'Sucursal - agencia',
        'Usuario', 'UTC', 'Referencia2',
    ]
    estado_cuenta_df.drop(columns=columns_drop_eecc, inplace=True)

    columnas_name = {
        'Fecha': 'fecha',
        'Descripción operación': 'descripcion_operacion',
        'Monto': 'importe',
        'Operación - Número': 'numero_operacion',
        'Operación - Hora': 'hora_operacion',
    }
    estado_cuenta_df.rename(columns=columnas_name, inplace=True)
    estado_cuenta_df['numero_operacion'] = estado_cuenta_df['numero_operacion'].astype(str)

    def clasificacion_bancos(valor):
        if valor.startswith('YPP'):
            return 'Yape'
        elif valor.startswith('A'):
            return 'BCP'
        else:
            return 'Otros'

    estado_cuenta_df['clasificacion_banco'] = estado_cuenta_df['descripcion_operacion'].apply(clasificacion_bancos)
    estado_cuenta_df = estado_cuenta_df[estado_cuenta_df['clasificacion_banco'] != 'Otros']

    estado_cuenta_df['codigo_operacion'] = estado_cuenta_df.apply(
        lambda x: (
            str(x['descripcion_operacion'])[-11:]
            if str(x['descripcion_operacion'])[:3] == 'YPP'
            else str(x['numero_operacion']).zfill(8)
        ) + str(abs(x['importe']) * -1).replace('.', '').replace(',', '')[1:5],
        axis=1,
    )

    estado_cuenta_df['banco'] = estado_cuenta_df.apply(
        lambda x: 'Yape' if str(x['descripcion_operacion'])[:3] == 'YPP' else '(BCP) - Banco de Crédito del Perú',
        axis=1,
    )

    return estado_cuenta_df


def procesar_bbva(estado_cuenta):
    estado_cuenta_df = pd.read_excel(estado_cuenta, skiprows=10)

    columns_drop_eecc = ['F. Valor', 'Código', 'Oficina']
    estado_cuenta_df.drop(columns=columns_drop_eecc, inplace=True)

    columnas_name = {
        'F. Operación': 'fecha',
        'Nº. Doc.': 'descripcion_operacion',
        'Importe': 'importe',
    }
    estado_cuenta_df.rename(columns=columnas_name, inplace=True)
    estado_cuenta_df = estado_cuenta_df[estado_cuenta_df['fecha'].notna()]

    filtro = estado_cuenta_df['Concepto'].astype(str).str.startswith('*C/PROV')
    estado_cuenta_df = estado_cuenta_df[filtro]

    estado_cuenta_df['descripcion_operacion'] = estado_cuenta_df['descripcion_operacion'].astype(str)

    estado_cuenta_df['codigo_operacion'] = (
        estado_cuenta_df['Concepto'].astype(str).str[-10:]
        + estado_cuenta_df['importe']
        .apply(lambda x: str(abs(x) * -1))
        .str.replace('.', '', regex=False)
        .str.replace(',', '', regex=False)
        .str[1:5]
    )

    estado_cuenta_df['banco'] = '(BBVA) - BBVA Continental'
    return estado_cuenta_df


procesadores_banck = {
    'bcp': procesar_bcp,
    'bbva': procesar_bbva,
}


# =========================================
# Página principal
# =========================================

def render():
    st.title('Conciliacion Instant - Payouts')

    # --- Inicializar session_state ---
    if 'ipo_data' not in st.session_state:
        st.session_state.ipo_data = None

    if 'ipo_data_despues_corte' not in st.session_state:
        st.session_state.ipo_data_despues_corte = None

    if 'ipo_df_pendientes' not in st.session_state:
        st.session_state.ipo_df_pendientes = None

    if 'ipo_pendientes_procesados' not in st.session_state:
        st.session_state.ipo_pendientes_procesados = False

    if 'ipo_metricas_subidas' not in st.session_state:
        st.session_state.ipo_metricas_subidas = False

    # =========================================
    # PARTE 1: Metabase
    # =========================================
    st.header('Metabase')

    file_uploader_metabase = st.file_uploader(
        'Arrastra el archivo de metabase aquí: ',
        type=['xlsx'],
        accept_multiple_files=True,
        key='ipo_uploader_metabase',
    )

    if file_uploader_metabase:

        if isinstance(file_uploader_metabase, list):
            ipayouts_metabase_df = file_uploader_metabase[0]
            if len(file_uploader_metabase) > 1:
                st.session_state.ipo_df_pendientes = file_uploader_metabase[1]
            else:
                st.session_state.ipo_df_pendientes = None
        else:
            ipayouts_metabase_df = file_uploader_metabase
            st.session_state.ipo_df_pendientes = None

        ipayouts_metabase_df = pd.read_excel(ipayouts_metabase_df)

        columns_drop = [
            'descripcion', 'referencia', 'payout process',
            'ID cliente', 'correo cliente', 'motivo',
        ]
        ipayouts_metabase_df.drop(columns=columns_drop, inplace=True, errors='ignore')
        ipayouts_metabase_df['documento'] = ipayouts_metabase_df['documento'].astype(str)
        ipayouts_metabase_df['fecha_creacion'] = ipayouts_metabase_df['fecha creacion'].dt.date

        alcance_bancos = [
            '(BCP) - Banco de Crédito del Perú',
            'Yape',
            '(BBVA) - BBVA Continental',
        ]
        ipayouts_metabase_df = ipayouts_metabase_df[ipayouts_metabase_df['banco'].isin(alcance_bancos)]
        ipayouts_metabase_df = ipayouts_metabase_df[ipayouts_metabase_df['estado'] == 'Pagado']
        ipayouts_metabase_df['codigo_operacion'] = ipayouts_metabase_df.apply(extraer_codigo, axis=1)

        if st.session_state.ipo_data is None:
            st.session_state.ipo_data = ipayouts_metabase_df.copy()
            st.session_state.ipo_pendientes_procesados = False

        # =========================================
        # Selector de fecha
        # =========================================
        if 'ipo_fecha_sel' not in st.session_state:
            st.session_state.ipo_fecha_sel = date.today() - pd.Timedelta(days=1)

        fecha_sel = st.date_input(
            'SELECCIONAR FECHA DE DIA DE CONCILIACION: ',
            value=st.session_state.ipo_fecha_sel,
            key='ipo_fecha_sel',
        )

        if 'ipo_ultima_fecha_sel' not in st.session_state:
            st.session_state.ipo_ultima_fecha_sel = fecha_sel

        if st.session_state.ipo_ultima_fecha_sel != fecha_sel:
            st.session_state.ipo_ayer_corte = (fecha_sel - pd.Timedelta(days=1))
            st.session_state.ipo_data_despues_corte = None
            st.session_state.ipo_ultima_fecha_sel = fecha_sel

        if 'ipo_ayer_corte' not in st.session_state:
            st.session_state.ipo_ayer_corte = (st.session_state.ipo_fecha_sel - pd.Timedelta(days=1))

        ayer_para_cortes = st.session_state.ipo_ayer_corte
        fecha_sel = st.session_state.ipo_fecha_sel

        # --- Pendientes ---
        if st.session_state.ipo_df_pendientes is not None and not st.session_state.ipo_pendientes_procesados:
            try:
                df_pendientes = pd.read_excel(st.session_state.ipo_df_pendientes)
                df_pendientes = df_pendientes.iloc[:, :18]
                df_pendientes['fecha_creacion'] = df_pendientes['fecha creacion'].dt.date
                df_pendientes['codigo_operacion'] = df_pendientes.apply(extraer_codigo, axis=1)

                st.session_state.ipo_data = pd.concat(
                    [st.session_state.ipo_data, df_pendientes], ignore_index=True
                )
                st.session_state.ipo_pendientes_procesados = True
                st.success(f'Se agregaron los movimientos pendientes del {ayer_para_cortes}.')
            except Exception as e:
                st.warning(f'No se pudo cargar pendientes del {ayer_para_cortes}: {e}')

        # =========================================
        # Horarios de corte
        # =========================================
        hora_corte_bbva     = time(22, 0)
        hora_corte_bcp_yape = time(21, 15)

        dt_corte_bbva     = datetime.combine(fecha_sel, hora_corte_bbva)
        dt_corte_bcp_yape = datetime.combine(fecha_sel, hora_corte_bcp_yape)

        st.session_state.ipo_data['corte_datetime'] = st.session_state.ipo_data['banco'].apply(
            lambda b: dt_corte_bbva if '(BBVA) - BBVA Continental' in b else dt_corte_bcp_yape
        )

        st.session_state.ipo_data['estado_corte'] = st.session_state.ipo_data.apply(
            lambda row: 'Antes de corte'
            if row['fecha creacion'] < datetime.combine(
                fecha_sel,
                hora_corte_bbva if 'BBVA' in row['banco'] else hora_corte_bcp_yape
            )
            else 'Después de corte',
            axis=1,
        )

        if st.session_state.ipo_data_despues_corte is None:
            movimientos_pendientes = st.session_state.ipo_data[
                st.session_state.ipo_data['estado_corte'] == 'Después de corte'
            ].copy()
            st.session_state.ipo_data_despues_corte = movimientos_pendientes.sort_values(
                'fecha creacion', ascending=True
            )

        st.session_state.ipo_data = st.session_state.ipo_data[
            st.session_state.ipo_data['estado_corte'] == 'Antes de corte'
        ]
        st.session_state.ipo_data.sort_values('fecha creacion', ascending=True, inplace=True)

        montos_ipayouts = st.session_state.ipo_data.groupby(['banco'])['monto'].sum().reset_index()
        st.session_state.ipo_data
        st.dataframe(montos_ipayouts, use_container_width=True)

        # =========================================
        # PARTE 2: Estados de cuenta
        # =========================================
        st.header('Estados de cuenta')

        estado_cuenta = st.file_uploader(
            'Subir estados de cuenta',
            type=['xlsx', 'xls'],
            accept_multiple_files=True,
            key='ipo_uploader_eecc',
        )

        df_consolidados = []

        if estado_cuenta:
            for archivo in estado_cuenta:
                nombre_archivo = archivo.name.lower()
                procesador = None
                for clave, funcion in procesadores_banck.items():
                    if clave in nombre_archivo:
                        procesador = funcion
                        break

                if procesador:
                    try:
                        df = procesador(archivo)
                        df_consolidados.append(df)
                        st.success(f'Archivo procesado: {archivo.name}')
                    except Exception as e:
                        st.error(f'Error al procesar {archivo.name}: {e}')
                else:
                    st.warning(f'No se encontro una funcion para procesar: {archivo.name}')

        if st.session_state.ipo_data is not None and df_consolidados:

            tiempo_inicio = datetime.now()

            df_final = pd.concat(df_consolidados, ignore_index=True)
            df_final = df_final[['fecha', 'importe', 'codigo_operacion', 'banco']]
            df_final['fecha'] = pd.to_datetime(df_final['fecha']).dt.date

            montos_bancos_eecc = df_final.groupby(['fecha', 'banco'])['importe'].sum().abs().reset_index()
            st.dataframe(montos_bancos_eecc, use_container_width=True)

            # =========================================
            # PARTE 3: Conciliacion
            # =========================================
            st.header('Conciliacion')

            codigo_bancos_set = set(df_final['codigo_operacion'])

            st.session_state.ipo_data['resultado_busqueda'] = st.session_state.ipo_data['codigo_operacion'].apply(
                lambda x: x if x in codigo_bancos_set else 'No encontrado'
            )

            st.subheader('Diferencias despues de cruce de numero de operacion')
            st.write(
                '''
                Esta tabla muestra las diferencias despues de el cruce de numeros de operacion entre el archivo metabase
                y los estados de cuenta subidos. Las diferencias encontradas vendrían a ser operaciones que se pagaron al día siguiente
                por lo que se deberá descargar y registrar los montos para poder conciliarlos el día de mañana.
                '''
            )

            if 'ipo_merge_realizado' not in st.session_state:
                st.session_state.ipo_merge_realizado = False

            if not st.session_state.ipo_merge_realizado:
                st.session_state.ipo_data = st.session_state.ipo_data.merge(
                    df_final[['codigo_operacion', 'importe']],
                    on='codigo_operacion',
                    how='left',
                )
                st.session_state.ipo_merge_realizado = True

            st.session_state.ipo_data['saldo'] = (
                st.session_state.ipo_data['monto'] + st.session_state.ipo_data['importe']
            ).fillna('No valor')

            if 'ipo_codigos_encontrados_df' not in st.session_state:
                st.session_state.ipo_codigos_encontrados_df = None

            if st.session_state.ipo_codigos_encontrados_df is None:
                codigos_encontrados = st.session_state.ipo_data[
                    st.session_state.ipo_data['resultado_busqueda'] != 'No encontrado'
                ]
                st.session_state.ipo_codigos_encontrados_df = codigos_encontrados

            codigos_encontrados = st.session_state.ipo_codigos_encontrados_df

            codigos_encontrados_pivot = codigos_encontrados.groupby('banco')[['importe']].sum().reset_index()
            merge_meta_banco = pd.merge(montos_ipayouts, codigos_encontrados_pivot, on='banco', how='inner')
            merge_meta_banco['Diferencia'] = merge_meta_banco['monto'] + merge_meta_banco['importe']

            rename_columns = {
                'banco': 'BANCO',
                'monto': 'Monto Kashio',
                'importe': 'Monto Banco',
            }
            merge_meta_banco = merge_meta_banco.rename(columns=rename_columns)
            merge_meta_banco.insert(0, 'FechaTexto', fecha_sel)
            st.dataframe(merge_meta_banco, use_container_width=True)

            # --- Supabase ---
            tiempo_fin = datetime.now()

            if not st.session_state.ipo_metricas_subidas:
                nota_input = st.text_area(
                    'Nota (opcional — explica diferencias si las hay):',
                    placeholder='Ej: Diferencia en Yape corresponde a operación procesada fuera de horario...',
                    key='ipo_nota',
                )
                registrar = st.button('REGISTRAR CONCILIACIÓN EN SUPABASE', use_container_width=True, key='ipo_btn_supabase')
                if registrar:
                    session_id = generar_session_id()
                    registros = []

                    for _, fila_banco in merge_meta_banco.iterrows():
                        banco_nombre = fila_banco['BANCO']

                        meta_banco  = st.session_state.ipo_data[st.session_state.ipo_data['banco'] == banco_nombre]
                        tx_meta     = len(meta_banco)
                        monto_meta  = float(meta_banco['monto'].sum())

                        eecc_banco  = df_final[df_final['banco'] == banco_nombre]
                        tx_bco      = len(eecc_banco)
                        monto_bco   = float(eecc_banco['importe'].abs().sum())

                        no_encontrados = st.session_state.ipo_data[
                            (st.session_state.ipo_data['banco'] == banco_nombre)
                            & (st.session_state.ipo_data['resultado_busqueda'] == 'No encontrado')
                        ]
                        tx_dif           = len(no_encontrados)
                        diferencia_banco = float(fila_banco['Diferencia'])
                        resultado_banco  = 'CONCILIADO' if diferencia_banco == 0 else 'DISCREPANCIAS'

                        registros.append(construir_metricas(
                            fecha_inicio=tiempo_inicio,
                            fecha_fin=tiempo_fin,
                            operador_dispersion=str(banco_nombre),
                            tipo_conciliacion='instant_payouts_diaria',
                            monto_metabase=monto_meta,
                            monto_banco_total=monto_bco,
                            suma_diferencias=diferencia_banco,
                            resultado_conciliacion=resultado_banco,
                            session_id=session_id,
                            tx_metabase=tx_meta,
                            tx_banco=tx_bco,
                            tx_con_discrepancia=tx_dif,
                            nota=nota_input or None,
                        ))

                    if subir_metricas(registros):
                        st.success(f'Métricas registradas en Supabase ({len(registros)} bancos)')
                        st.session_state.ipo_metricas_subidas = True
                    else:
                        st.error('No se pudieron registrar las métricas')

            # --- Diferencias encontradas ---
            with st.expander('Diferencias encontradas'):

                concicliacion_mañana_no_encontrado = st.session_state.ipo_data[
                    st.session_state.ipo_data['resultado_busqueda'] == 'No encontrado'
                ]

                bancos_unicos    = ['Todos'] + sorted(st.session_state.ipo_data['banco'].unique())
                bancos_unicos_sb = st.selectbox('Filtrar por banco', bancos_unicos, key='ipo_filtro_banco')

                diferencias_filtro = merge_meta_banco[merge_meta_banco['BANCO'] == bancos_unicos_sb]

                if bancos_unicos_sb == 'Todos':
                    concicliacion_mañana_filtrado = concicliacion_mañana_no_encontrado
                    diferencias_filtro = merge_meta_banco
                else:
                    concicliacion_mañana_filtrado = concicliacion_mañana_no_encontrado[
                        concicliacion_mañana_no_encontrado['banco'] == bancos_unicos_sb
                    ]

                columnas_mostrar = [
                    'empresa', 'fecha creacion', 'fecha operacion', 'inv public_id',
                    'po_public_id', 'Cliente', 'documento', 'numero de cuenta',
                    'CCI', 'monto', 'banco', 'numero de operacion', 'estado', 'codigo_operacion',
                ]
                columnas_disponibles = [c for c in columnas_mostrar if c in concicliacion_mañana_filtrado.columns]
                concicliacion_mañana_filtrado = concicliacion_mañana_filtrado[columnas_disponibles]

                st.dataframe(concicliacion_mañana_filtrado, use_container_width=True)

                suma_monto             = round(concicliacion_mañana_filtrado['monto'].sum(), 2)
                suma_diferencias_filtro = round(diferencias_filtro['Diferencia'].sum(), 2)
                diferencia_montos      = round(suma_monto - suma_diferencias_filtro, 2)
                cantidad_diferencias   = len(concicliacion_mañana_filtrado)

                if cantidad_diferencias == 0:
                    st.success('Sin diferencias')
                else:
                    st.warning(f'{cantidad_diferencias} diferencias encontradas')

                if diferencia_montos == 0:
                    st.success('Montos iguales')
                else:
                    st.warning('Montos desiguales')

            # =========================================
            # PARTE 4: Descargas
            # =========================================
            if 'ipo_guardad_registros_pendientes' not in st.session_state:
                st.session_state.ipo_guardad_registros_pendientes = False

            c1, c2 = st.columns(2)

            with c1:
                cantidad_movimientos = len(st.session_state.ipo_data_despues_corte)
                if cantidad_movimientos > 0:
                    archivo_nombre = f'Pendiente_Conciliar_{fecha_sel}.xlsx'
                    excel_buffer   = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                        st.session_state.ipo_data_despues_corte.to_excel(
                            writer, sheet_name='Pendientes_conciliar', index=False
                        )
                        df_final.to_excel(writer, sheet_name='eecc_consolidados', index=False)

                    st.download_button(
                        label=f'DESCARGAR {cantidad_movimientos} MOVIMIENTOS PENDIENTES',
                        data=excel_buffer.getvalue(),
                        file_name=archivo_nombre,
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        use_container_width=True,
                        key='ipo_download_pendientes',
                    )
                else:
                    st.info('No hay movimientos pendientes para descargar.')

            with c2:
                cantidad_movimientos_conciliados = len(codigos_encontrados)
                if cantidad_movimientos_conciliados > 0:
                    archivo_nombre_parquet = f'OperacionesPagadas_{fecha_sel}.parquet'
                    if 'documento' in codigos_encontrados.columns:
                        codigos_encontrados['documento'] = (
                            codigos_encontrados['documento'].astype('string').fillna('')
                        )
                    parquet_buffer = io.BytesIO()
                    codigos_encontrados.to_parquet(parquet_buffer, index=False, engine='pyarrow')

                    st.download_button(
                        label=f'DESCARGAR {cantidad_movimientos_conciliados} REGISTROS PAGADOS',
                        data=parquet_buffer.getvalue(),
                        file_name=archivo_nombre_parquet,
                        mime='application/octet-stream',
                        use_container_width=True,
                        key='ipo_download_pagados',
                    )
                else:
                    st.info('No hay registros pagados para descargar.')
