-- =============================================================================
-- Contrat de données partagé (P1 ↔ P2 ↔ P3 ↔ P4) — base "anomalies"
-- =============================================================================
-- Ce fichier est la référence du schéma : toute modification doit passer par une PR
-- relue par les pôles concernés. Il n'est exécuté qu'à la création du volume Postgres
-- (`docker compose down -v` pour repartir de zéro après une modification).
--
-- Les colonnes reprennent le format multi-séries (`unique_id`, `ds`, `y`) utilisé
-- dans tout le code Python (cf. CONTRIBUTING.md, « Contrats d'interface »).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- [P1] Séries temporelles éCO2mix après contrôle qualité et enrichissement calendaire
-- Clé d'idempotence : (source, unique_id, ds) → upsert via INSERT ... ON CONFLICT
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS series (
    source             TEXT             NOT NULL,  -- clé du jeu de données : national_tr, national_cons_def, regional_tr, ...
    unique_id          TEXT             NOT NULL,  -- "FR" (national) ou code INSEE de la région
    ds                 TIMESTAMPTZ      NOT NULL,  -- horodatage UTC
    y                  DOUBLE PRECISION,           -- consommation (MW)
    prevision_j1       DOUBLE PRECISION,           -- prévision RTE J-1 (MW)
    prevision_j        DOUBLE PRECISION,           -- prévision RTE J (MW)
    quality_flag       TEXT             NOT NULL DEFAULT 'OK',
    is_holiday_fr      BOOLEAN,
    is_bridge_day      BOOLEAN,
    is_dst_transition  BOOLEAN,
    ingested_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (source, unique_id, ds)
);

CREATE INDEX IF NOT EXISTS idx_series_ds ON series (ds);

-- -----------------------------------------------------------------------------
-- [P2 → P3/P4] Alertes émises par les détecteurs + qualification humaine (via l'API)
-- Clé d'idempotence : alert_id
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    alert_id               TEXT             PRIMARY KEY,
    unique_id              TEXT             NOT NULL,
    ds                     TIMESTAMPTZ      NOT NULL,
    y                      DOUBLE PRECISION NOT NULL,
    y_hat                  DOUBLE PRECISION NOT NULL,
    residual               DOUBLE PRECISION NOT NULL,
    ewma_error             DOUBLE PRECISION NOT NULL,
    threshold_eps          DOUBLE PRECISION NOT NULL,
    anomaly_score          DOUBLE PRECISION NOT NULL,
    is_anomaly             BOOLEAN          NOT NULL,
    detector_name          TEXT             NOT NULL,
    quality_flag           TEXT             NOT NULL DEFAULT 'OK',
    created_at             TIMESTAMPTZ      NOT NULL DEFAULT now(),

    -- Boucle de qualification humaine (POST /alerts/{alert_id}/qualify)
    qualification          TEXT CHECK (
        qualification IN ('true_positive', 'false_positive', 'seasonal_regime', 'sensor_fault')
    ),
    qualification_comment  TEXT,
    qualified_by           TEXT,
    qualified_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alerts_unique_id_ds ON alerts (unique_id, ds);

-- -----------------------------------------------------------------------------
-- [P4] Métriques de monitoring (dérive, qualité, audit M+1) lues par Grafana
-- Format « long » : une ligne par (calcul, série, métrique).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monitoring_metrics (
    id            BIGSERIAL        PRIMARY KEY,
    computed_at   TIMESTAMPTZ      NOT NULL DEFAULT now(),
    unique_id     TEXT             NOT NULL,
    metric_name   TEXT             NOT NULL,  -- ex : wasserstein_y, wasserstein_residual, psi_y, audit_precision_m1
    value         DOUBLE PRECISION NOT NULL,
    threshold     DOUBLE PRECISION,
    is_alert      BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_monitoring_metrics_lookup
    ON monitoring_metrics (metric_name, unique_id, computed_at);
