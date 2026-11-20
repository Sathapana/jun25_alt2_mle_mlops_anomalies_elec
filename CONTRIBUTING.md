# Guide de Contribution — Détection d'Anomalies éCO2mix (MLOps)

Ce document définit l'organisation du travail en équipe, les conventions d'architecture, les contrats d'interface entre les pôles **P1 à P4**, ainsi que le workflow Git et CI/CD du projet.

---

## 1. Organisation par Pôles & Responsabilités (P1 – P4)

Pour éviter les conflits Git et garantir une intégration fluide de bout en bout, chaque membre de l'équipe est propriétaire d'un périmètre clairement délimité dans `src/anomalies_elec/` et `tests/` :

| Rôle | Modules principaux (`src/anomalies_elec/`) | Tests associés (`tests/`) | Responsabilités clés |
| :--- | :--- | :--- | :--- |
| **P1 — Data & Ingestion** | `ingestion/`, `storage/`, `features/calendar_fr.py` | `test_ingestion_quality.py` | Client API Opendatasoft, gestion du quota (50k appels/mois), contrôles *Data Quality*, stockage Parquet/DuckDB idempotent, calendrier français. |
| **P2 — Modélisation & Détection** | `models/`, `configs/reference_events.yaml` | `test_models_detection.py` | Baselines ($J-7$ et prévision RTE), désaisonnalisation MSTL (`StatsForecast`), seuillage dynamique non paramétrique + *pruning* (*Telemanom*), corrélation inter-séries (*Luminol*). |
| **P3 — MLOps, Orchestration & API** | `pipelines/`, `api/`, `docker/`, `docker-compose.yml`, `.github/workflows/` | `test_api.py` | Flows Prefect (ingestion, entraînement, détection), tracking & registre MLflow, API REST FastAPI, conteneurisation Docker et CI/CD. |
| **P4 — Observabilité & Dashboard** | `monitoring/`, `dashboard/` | `test_monitoring.py` | Rapports Evidently (Data Quality, Data Drift vs Concept Drift), audit différé Temps Réel vs Consolidé ($M+1$), interface Streamlit et boucle de qualification humaine. |

---

## 2. Contrats de Données Inter-Modules (*Data Contracts*)

Afin que les pôles P1, P2, P3 et P4 puissent développer indépendamment, tous les modules échangent des `pandas.DataFrame` (ou tables Parquet/DuckDB) respectant des schémas stricts.

### 2.1. Contrat de Série Temporelle (Sortie P1 $\to$ Entrée P2)
Compatible nativement avec la convention `StatsForecast` (`unique_id`, `ds`, `y`) et enrichi des variables métier éCO2mix :

| Colonne | Type | Description | Exemple |
| :--- | :--- | :--- | :--- |
| `unique_id` | `str` | Identifiant de la série (`"FR"` au Niveau 1, code région au Niveau 2) | `"FR"` |
| `ds` | `datetime64[ns, UTC]` | Horodatage normalisé en UTC (pas de 15 min ou 1 h) | `2025-01-15 18:00:00+00:00` |
| `y` | `float64` | Consommation réalisée en MW (`consommation` éCO2mix) | `72450.0` |
| `prevision_j1` | `float64` | Prévision de consommation établie par RTE la veille ($J-1$) | `71800.0` |
| `prevision_j` | `float64` | Prévision de consommation réactualisée par RTE le jour même ($J$) | `72100.0` |
| `is_holiday_fr` | `bool` | Jour férié en France métropolitaine | `False` |
| `is_bridge_day` | `bool` | Jour de pont (lundi/vendredi entre un férié et un week-end) | `False` |
| `is_dst_transition` | `bool` | Jour de changement d'heure (été/hiver) | `False` |
| `quality_flag` | `str` | Statut du contrôle qualité P1 (`"OK"`, `"MISSING_GAP"`, `"FROZEN_SENSOR"`, `"OUT_OF_BOUNDS"`) | `"OK"` |

> [!IMPORTANT]
> **Règle d'or Qualité vs Anomalie :** Si `quality_flag != "OK"`, le pipeline génère une **alerte technique** (*défaillance de la chaîne de mesure*) et ne fait pas passer le point comme une anomalie physique de consommation dans le modèle P2.

### 2.2. Contrat de Résultat de Détection & Alerte (Sortie P2 $\to$ Entrée P3 & P4)

| Colonne | Type | Description |
| :--- | :--- | :--- |
| `alert_id` | `str` | Identifiant déterministe (`"{unique_id}_{start_ds_iso}"`) garantissant l'idempotence |
| `unique_id` | `str` | Périmètre géographique (`"FR"` ou code région) |
| `ds` | `datetime64[ns, UTC]` | Horodatage du point ou du pic de la séquence d'anomalie |
| `y` | `float64` | Valeur observée (MW) |
| `y_hat` | `float64` | Valeur attendue par le modèle désaisonnalisé / baseline (MW) |
| `residual` | `float64` | Résidu brut $R_t = y_t - \hat{y}_t$ |
| `ewma_error` | `float64` | Erreur absolue lissée par EWMA |
| `threshold_eps` | `float64` | Seuil dynamique non paramétrique $\epsilon^*$ calculé sur la fenêtre |
| `anomaly_score` | `float64` | Score normalisé de sévérité ($\text{ewma\_error} / \epsilon^*$) |
| `is_anomaly` | `bool` | `True` si la séquence franchit $\epsilon^*$ **et** survit à l'élagage (*pruning*) |
| `detector_name` | `str` | Nom et version du détecteur (`"baseline_j7"`, `"baseline_rte"`, `"mstl_telemanom_v1"`) |
| `qualification` | `str \| None` | Qualification humaine Niveau 3 (`None`, `"true_positive"`, `"false_positive"`, `"seasonal_regime"`, `"sensor_fault"`) |

---

## 3. Environnement de Développement & Outillage

Le projet utilise **[`uv`](https://docs.astral.sh/uv/)** pour la gestion des dépendances, **[`ruff`](https://docs.astral.sh/ruff/)** pour le linting et le formatage, et **[`pytest`](https://docs.pytest.org/)** pour les tests.

### Installation initiale
```bash
# Cloner le dépôt et installer l'environnement complet
uv sync --all-extras
```

### Commandes quotidiennes
```bash
# 1. Vérifier le style et les imports (obligatoire avant tout commit)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 2. Corriger automatiquement le formatage et les erreurs simples de lint
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/

# 3. Exécuter les tests unitaires et d'intégration avec couverture
uv run pytest -v --cov=anomalies_elec
```

---

## 4. Workflow Git, Branches & Pull Requests

### 4.1. Nommage des branches
Ne jamais travailler directement sur `main` pour le développement des fonctionnalités. Créer une branche dédiée par fonctionnalité ou par pôle :
- `feat/p1-eco2mix-ingestion`
- `feat/p2-mstl-dynamic-threshold`
- `feat/p3-fastapi-mlflow`
- `feat/p4-streamlit-evidently`
- `fix/p1-dst-timezone-handling`
- `docs/update-cadrage`

### 4.2. Format des messages de commit (Conventional Commits)
Nous utilisons la convention **Conventional Commits** :
- `feat(p1): add Opendatasoft eco2mix client with quota guard`
- `feat(p2): implement Hundman nonparametric dynamic thresholding`
- `feat(p3): add FastAPI /detect and /alerts/{id}/qualify endpoints`
- `feat(p4): add Evidently Wasserstein drift report on residuals`
- `fix(p2): handle bridge days in calendar feature engineering`
- `test(p1): add unit tests for missing 15-min publication gaps`
- `docs: update README architecture diagram`

### 4.3. Critères d'acceptation d'une Pull Request (*Definition of Done*)
Avant de merger une branche dans `main` :
1. **Zéro erreur Ruff :** `uv run ruff check src/ tests/` passe sans avertissement.
2. **Tests au vert :** `uv run pytest` passe à 100%, et toute nouvelle brique métier (P1, P2, P3, P4) inclut son test unitaire sur données synthétiques (ne dépendant pas d'un appel réseau réel à l'API Opendatasoft dans la CI).
3. **Configuration externalisée :** Aucun chemin local en dur, aucune clé ou seuil critique codé en dur dans `src/` — utiliser `configs/default.yaml` et `src/anomalies_elec/config.py`.
4. **Respect du quota API :** Les tests automatisés doivent mocker les appels HTTP vers `odre.opendatasoft.com` afin de préserver le quota mensuel de 50 000 appels.
5. **Revue croisée :** Au moins un autre membre de l'équipe (idéalement du pôle amont ou aval connecté au contrat de données) a relu et validé la PR.
