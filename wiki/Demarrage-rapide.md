# Démarrage rapide

Détail complet : [README §Démarrage rapide](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/README.md#démarrage-rapide) et [CONTRIBUTING §3](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/CONTRIBUTING.md#3-environnement-de-développement--outillage).

## 1. Prérequis
- [`uv`](https://docs.astral.sh/uv/) : installe lui-même **Python 3.11** (fixé par `.python-version`, identique aux images Docker et à la CI).
- Docker Desktop / Docker Compose pour la stack complète.

## 2. Installer et vérifier

```bash
uv sync --all-extras            # base + outils de dev + extra MLOps
uv run pre-commit install       # une seule fois par clone
uv run ruff check src/ tests/ dags/
uv run pytest -v
```

## 3. Récupérer les données (une fois par poste)

Les données ne sont **pas versionnées** dans Git : chacun lance les backfills en local.

| Données | Commande | Appels API |
| :--- | :--- | :--- |
| Historique national éCO2mix (2012 → 2026-08-31) | `uv run python -m anomalies_elec.ingestion.backfill` | 1 |
| Météo Open-Meteo (2012 → aujourd'hui) | `uv run python -m anomalies_elec.ingestion.weather_client` | ~15 |
| Temps réel national (depuis 2026-08-31)¹ | `uv run python -m anomalies_elec.ingestion.realtime --catch-up` | 1 |

¹ Disponible après le merge de la branche `feat/p1-ingestion-temps-reel` (SCRUM-45).

## 4. Lancer l'API seule (backend Parquet, sans Docker)

```bash
uv run uvicorn anomalies_elec.api.main:app --reload --port 8000   # http://localhost:8000/docs
```

## 5. Lancer la stack complète

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps     # airflow-init "exited (0)", les autres "running"/"healthy"
```

| Service | URL | Identifiants (dev) |
| :--- | :--- | :--- |
| API FastAPI (Swagger) | http://localhost:8000/docs | — |
| Airflow 3 | http://localhost:8080 | aucun (SimpleAuthManager) |
| MLflow | http://localhost:5000 | — |
| Grafana | http://localhost:3000 | `admin` / `admin` |
| PostgreSQL | `localhost:5432` | `anomalies` / `anomalies` |

## 6. Après une modification

| J'ai modifié… | À faire |
| :--- | :--- |
| `dags/*.py` | Rien (dossier monté, pris en compte en ~30 s) |
| `src/`, `configs/`, `pyproject.toml`, `uv.lock` | `docker compose up --build -d` |
| `grafana/dashboards/*.json` | Rien (rechargé en ~30 s) |
| `docker/postgres/init/*.sql` | `docker compose down -v` puis `up -d` (⚠️ efface les données locales) |

## Problèmes fréquents
- **Le conteneur exécute l'ancien code** → oubli de `--build`.
- **Table `weather` absente** → le volume Postgres existait avant l'ajout du schéma : `docker compose down -v`.
- **DAG inactif** → les DAGs sont en pause à la création : les activer dans l'UI Airflow.
- **Log Airflow `No module named 'pendulum'`** → attendu : Airflow n'est pas installé dans le virtualenv projet, la tâche fonctionne.
