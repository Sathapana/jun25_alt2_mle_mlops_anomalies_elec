# Architecture

Détail : [README §Architecture](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/README.md#vue-densemble-de-larchitecture) · [CONTRIBUTING §1–2](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/CONTRIBUTING.md#2-contrats-de-données-inter-modules-data-contracts) · [schéma SQL](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/docker/postgres/init/01_schema.sql).

## Stack

| Brique | Outil | Rôle |
| :--- | :--- | :--- |
| Orchestration | Apache Airflow 3 | DAGs d'ingestion (15 min), de détection et de réentraînement |
| Stockage | PostgreSQL (Parquet en dev/tests) | Séries, alertes, qualifications, météo ; upsert idempotent |
| Modèles | StatsForecast (MSTL) + NumPy/SciPy | Désaisonnalisation multi-saisonnière, seuillage dynamique |
| Tracking | MLflow | Expériences, registre de modèles, promotion |
| Service | FastAPI | `/health`, `/detect`, `/alerts`, `/alerts/{id}/qualify` |
| Dashboard | Grafana (lecture seule) | Séries, alertes, événements de référence |
| Drift | Evidently AI | Data drift vs concept drift, audit TR vs consolidé (M+1) |
| Outillage | uv · Ruff · Pytest · Docker · GitHub Actions | Dépendances, qualité, tests, conteneurs, CI |

## Modules par pôle (`src/anomalies_elec/`)

| Pôle | Modules | Ce qui existe sur `main` |
| :--- | :--- | :--- |
| **P1** Data & Ingestion | `ingestion/`, `storage/`, `features/` | Backfill national, météo, contrôle qualité, calendrier FR, `ParquetStore` + `PostgresStore` |
| **P2** Modélisation | `models/` | Baselines J-7 et prévision RTE, MSTL, seuillage EWMA + pruning, corrélateur (Niveau 2) |
| **P3** MLOps & API | `pipelines/`, `api/`, `dags/` | API FastAPI ; DAGs encore squelettes (`TODO(P3)`), pas encore de MLflow |
| **P4** Observabilité | `monitoring/`, `grafana/` | Prototypes drift (Wasserstein) et audit M+1 ; dashboard de départ |

Accès au stockage **toujours** via `anomalies_elec.storage.base.get_store(cfg.storage)` (backend choisi par `STORAGE_BACKEND`).

## Contrats de données (résumé)

**Série (P1 → P2)** — format StatsForecast `(unique_id, ds, y)` enrichi : `prevision_j1`, `prevision_j`, `is_holiday_fr`, `is_bridge_day`, `is_dst_transition`, `quality_flag` (`OK`, `MISSING_GAP`, `FROZEN_SENSOR`, `OUT_OF_BOUNDS`). `ds` toujours en UTC.

**Alerte (P2 → P3/P4)** — `alert_id` déterministe (`{unique_id}_{start_ds_iso}`), `y`, `y_hat`, `residual`, `ewma_error`, `threshold_eps`, `anomaly_score`, `is_anomaly`, `detector_name`, puis champs de qualification humaine (`qualification`, `qualification_comment`, `qualified_by`, `qualified_at`).

> **Règle d'or qualité vs anomalie :** si `quality_flag != "OK"`, on émet une **alerte technique** (chaîne de mesure) et le point n'entre pas dans le modèle comme anomalie physique.

## Niveaux du sujet
1. **Niveau 1** — série nationale `FR`, chaîne complète, 2 baselines, MSTL + seuillage, évaluation sur événements de référence.
2. **Niveau 2** — 12 régions au pas horaire, multivarié, déduplication inter-régions.
3. **Niveau 3** — qualification humaine, drift data vs concept, audit TR vs consolidé M+1.
