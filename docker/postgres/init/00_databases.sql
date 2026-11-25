-- Exécuté une seule fois par l'image officielle postgres, au premier démarrage (volume vide).
-- La base métier (POSTGRES_DB = "anomalies") est créée automatiquement par l'image ;
-- on ajoute ici les bases techniques des autres services.

CREATE DATABASE mlflow;   -- Backend store MLflow (runs, registre de modèles)
CREATE DATABASE airflow;  -- Métadonnées Airflow (DAG runs, task instances)
