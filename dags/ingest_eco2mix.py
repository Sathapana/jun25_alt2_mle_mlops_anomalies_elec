"""DAG d'ingestion temps réel nationale éCO2mix (`eco2mix-national-tr`), toutes les 15 min.

Chaque exécution relit une fenêtre de recouvrement (`ingestion.realtime_window_hours`) en 1 appel API :
archive brute -> contrôle qualité -> calendrier -> upsert sur (source, unique_id, ds).
Le rattrapage initial (tout le jeu temps réel) se lance une fois à la main :
`uv run python -m anomalies_elec.ingestion.realtime --catch-up`.
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
    dag_id="ingest_eco2mix",
    schedule="*/15 * * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,  # pas deux fenêtres écrites en parallèle
    default_args=DEFAULT_ARGS,
    tags=["p1", "p3", "ingestion", "temps-reel"],
)
def ingest_eco2mix():
    @task.external_python(python=ANOMALIES_PYTHON)
    def ingest_national_tr(window_end: str) -> dict:
        """1 appel `/records` sur la fenêtre se terminant à `window_end` (fin d'intervalle du run).

        `window_end` vaut "None" pour un run manuel sans intervalle : la fenêtre se termine alors maintenant.
        Une erreur API (timeout, 5xx) fait échouer la tâche, relancée par Airflow (`retries`).
        """
        import logging

        from anomalies_elec.ingestion.realtime import run_incremental

        logging.basicConfig(level=logging.INFO)
        return run_incremental(end=window_end)

    ingest_national_tr(window_end="{{ data_interval_end }}")


ingest_eco2mix()
