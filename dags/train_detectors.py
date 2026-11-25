"""DAG d'entraînement / réévaluation des détecteurs (squelette — à compléter par P3 avec P2).

Cible : hebdomadaire, évaluer baselines + MSTL via `anomalies_elec.pipelines.train_flow`,
journaliser dans MLflow et promouvoir le meilleur détecteur.
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
    dag_id="train_detectors",
    schedule="@weekly",
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["p2", "p3", "training", "mlflow"],
)
def train_detectors():
    @task.external_python(python=ANOMALIES_PYTHON)
    def check_environment() -> str:
        import os

        from anomalies_elec.pipelines import train_flow  # noqa: F401

        return f"mlflow={os.environ.get('MLFLOW_TRACKING_URI', 'non défini')}"

    # TODO(P3): evaluate_detector(...) pour chaque détecteur -> mlflow.log_params/log_metrics
    #   -> enregistrement au Model Registry et promotion de l'alias « production ».
    check_environment()


train_detectors()
