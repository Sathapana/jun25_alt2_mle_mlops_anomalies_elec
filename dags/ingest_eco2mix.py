"""DAG d'ingestion éCO2mix (squelette — à compléter par P3 avec P1).

Cible : toutes les 15 min, collecte incrémentale -> Data Quality Gate -> calendrier -> stockage,
via `anomalies_elec.pipelines.ingest_flow.run_ingestion_pipeline`.
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
    default_args=DEFAULT_ARGS,
    tags=["p1", "p3", "ingestion"],
)
def ingest_eco2mix():
    @task.external_python(python=ANOMALIES_PYTHON)
    def check_environment() -> str:
        """Vérifie que le package et la configuration sont accessibles depuis le virtualenv projet."""
        from anomalies_elec.config import load_config
        from anomalies_elec.pipelines import ingest_flow  # noqa: F401

        cfg = load_config()
        return f"backend={cfg.storage.backend} freq={cfg.project.freq}"

    # TODO(P3): remplacer par la chaîne réelle, p.ex. une tâche par jeu de données
    #   (national_tr, regional_tr, ...) appelant run_ingestion_pipeline(dataset_key=..., where=...)
    #   avec une fenêtre incrémentale basée sur data_interval_start / data_interval_end.
    check_environment()


ingest_eco2mix()
