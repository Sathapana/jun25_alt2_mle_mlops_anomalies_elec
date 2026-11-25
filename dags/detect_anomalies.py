"""DAG de détection continue (squelette — à compléter par P3 avec P2).

Cible : après chaque ingestion, scorer les nouveaux points et persister les alertes,
via `anomalies_elec.pipelines.detect_flow.run_detection_pipeline`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.sdk import dag, task

# Virtualenv du projet construit par docker/Dockerfile.airflow (le package n'est pas dans l'env Airflow).
# Les fonctions `@task.external_python` doivent être autonomes : imports dans le corps, pas de globales.
ANOMALIES_PYTHON = "/opt/anomalies-venv/bin/python"
DEFAULT_ARGS = {"owner": "p3-mlops", "retries": 1, "retry_delay": timedelta(minutes=2)}
START_DATE = datetime(2025, 1, 1)


@dag(
    dag_id="detect_anomalies",
    schedule="@hourly",  # TODO(P3): déclencher plutôt sur un Asset publié par ingest_eco2mix
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["p2", "p3", "detection"],
)
def detect_anomalies():
    @task.external_python(python=ANOMALIES_PYTHON)
    def check_environment() -> str:
        from anomalies_elec.config import load_config
        from anomalies_elec.pipelines import detect_flow  # noqa: F401

        cfg = load_config()
        return f"backend={cfg.storage.backend} season_lengths={cfg.models.mstl_season_lengths}"

    # TODO(P3): lire la fenêtre récente (store.read_series), appeler run_detection_pipeline,
    #   charger le modèle/seuil « Production » depuis le registre MLflow.
    check_environment()


detect_anomalies()
