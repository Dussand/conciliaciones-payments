-- ============================================
-- TABLA DE METRICAS DE CONCILIACIONES v3
-- ============================================
-- Ejecutar en: Supabase > SQL Editor
-- Elimina la tabla anterior antes de ejecutar.
-- ============================================

CREATE TABLE IF NOT EXISTS conciliaciones_metricas (
    id                      BIGSERIAL PRIMARY KEY,
    fecha_inicio            TIMESTAMPTZ NOT NULL,
    fecha_fin               TIMESTAMPTZ NOT NULL,
    duracion_ms             INTEGER NOT NULL,
    tipo_conciliacion       TEXT NOT NULL CHECK (tipo_conciliacion IN ('instant_payouts_diaria', 'payouts_regular_diaria')),
    operador_dispersion     TEXT NOT NULL,
    monto_metabase          NUMERIC(15, 2),
    monto_banco_total       NUMERIC(15, 2),
    suma_diferencias        NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    resultado_conciliacion  TEXT NOT NULL CHECK (resultado_conciliacion IN ('CONCILIADO', 'DISCREPANCIAS')),
    tx_metabase             INTEGER,
    tx_banco                INTEGER,
    tx_con_discrepancia     INTEGER,
    session_id              TEXT NOT NULL,
    nota                    TEXT,
    estado                  TEXT NOT NULL DEFAULT 'SUCCESS' CHECK (estado IN ('SUCCESS', 'ERROR')),
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_conci_operador     ON conciliaciones_metricas (operador_dispersion);
CREATE INDEX IF NOT EXISTS idx_conci_tipo         ON conciliaciones_metricas (tipo_conciliacion);
CREATE INDEX IF NOT EXISTS idx_conci_fecha        ON conciliaciones_metricas (fecha_inicio);
CREATE INDEX IF NOT EXISTS idx_conci_resultado    ON conciliaciones_metricas (resultado_conciliacion);
CREATE INDEX IF NOT EXISTS idx_conci_session      ON conciliaciones_metricas (session_id);

-- RLS
ALTER TABLE conciliaciones_metricas ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Permitir insert desde app" ON conciliaciones_metricas
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Permitir lectura desde app" ON conciliaciones_metricas
    FOR SELECT USING (true);

-- Comentarios
COMMENT ON TABLE  conciliaciones_metricas                        IS 'Métricas por banco/operador por cada conciliación ejecutada';
COMMENT ON COLUMN conciliaciones_metricas.operador_dispersion    IS 'Banco u operador: BCP, BBVA, Yape, Interbank, Otros bancos';
COMMENT ON COLUMN conciliaciones_metricas.tipo_conciliacion      IS 'instant_payouts_diaria o payouts_regular_diaria';
COMMENT ON COLUMN conciliaciones_metricas.tx_metabase            IS 'IPO: nro de operaciones por banco. PO: nulo';
COMMENT ON COLUMN conciliaciones_metricas.tx_banco               IS 'IPO: nro de operaciones en eecc por banco. PO: nulo';
COMMENT ON COLUMN conciliaciones_metricas.tx_con_discrepancia    IS 'IPO: operaciones no encontradas por banco. PO: nulo';
COMMENT ON COLUMN conciliaciones_metricas.nota                   IS 'Explicación manual de la diferencia encontrada';
COMMENT ON COLUMN conciliaciones_metricas.session_id             IS 'ID único del run — mismo valor para todas las filas del mismo proceso';
