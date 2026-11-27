# Guide de Contribution — Détection d'Anomalies éCO2mix (MLOps)

Ce document définit l'organisation du travail en équipe, les conventions d'architecture, les contrats d'interface entre les pôles **P1 à P4**, ainsi que le workflow Git et CI/CD du projet.

---

## 1. Organisation par Pôles & Responsabilités (P1 – P4)

Pour éviter les conflits Git et garantir une intégration fluide de bout en bout, chaque membre de l'équipe est propriétaire d'un périmètre clairement délimité dans `src/anomalies_elec/` et `tests/` :

| Rôle | Modules principaux (`src/anomalies_elec/`) | Tests associés (`tests/`) | Responsabilités clés |
| :--- | :--- | :--- | :--- |
| **P1 — Data & Ingestion** | `ingestion/`, `storage/`, `features/calendar_fr.py`, `docker/postgres/init/` | `test_ingestion_quality.py`, `test_storage.py` | Client API Opendatasoft, gestion du quota (50k appels/mois), contrôles *Data Quality*, stockage PostgreSQL idempotent, calendrier français. |
| **P2 — Modélisation & Détection** | `models/`, `configs/reference_events.yaml` | `test_models_detection.py` | Baselines ($J-7$ et prévision RTE), désaisonnalisation MSTL (`StatsForecast`), seuillage dynamique non paramétrique + *pruning* (*Telemanom*), corrélation inter-séries (*Luminol*). |
| **P3 — MLOps, Orchestration & API** | `pipelines/`, `api/`, `dags/`, `docker/`, `docker-compose.yml`, `.github/workflows/` | `test_api.py` | DAGs Airflow (ingestion, entraînement, détection), tracking & registre MLflow, API REST FastAPI, conteneurisation Docker et CI/CD. |
| **P4 — Observabilité & Dashboard** | `monitoring/`, `grafana/` | `test_monitoring.py` (à créer) | Rapports Evidently (Data Quality, Data Drift vs Concept Drift), audit différé Temps Réel vs Consolidé ($M+1$), dashboards Grafana et boucle de qualification humaine. |

---

## 2. Contrats de Données Inter-Modules (*Data Contracts*)

Afin que les pôles P1, P2, P3 et P4 puissent développer indépendamment, tous les modules échangent des `pandas.DataFrame` (ou tables PostgreSQL) respectant des schémas stricts.

- **Schéma de référence en base :** [`docker/postgres/init/01_schema.sql`](docker/postgres/init/01_schema.sql) (tables `series`, `alerts`, `monitoring_metrics`). Toute modification passe par une PR relue par les pôles concernés.
- **Accès au stockage :** toujours via `anomalies_elec.storage.base.get_store(cfg.storage)`, jamais en instanciant directement `ParquetStore` / `PostgresStore`. Le backend est choisi par `storage.backend` (ou `STORAGE_BACKEND`).

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
| `qualification_comment` | `str \| None` | Commentaire libre de l'opérateur |
| `qualified_by` | `str \| None` | Identifiant de l'opérateur ayant qualifié l'alerte |
| `qualified_at` | `datetime64[ns, UTC] \| None` | Horodatage de la qualification (renseigné par l'API) |

> La qualification se fait **uniquement via l'API** (`POST /alerts/{alert_id}/qualify`) ; Grafana affiche les alertes en lecture seule.

---

## 3. Environnement de Développement & Outillage

Le projet utilise **[`uv`](https://docs.astral.sh/uv/)** pour la gestion des dépendances, **[`ruff`](https://docs.astral.sh/ruff/)** pour le linting et le formatage, et **[`pytest`](https://docs.pytest.org/)** pour les tests.

### Installation initiale
```bash
# Cloner le dépôt et installer l'environnement complet (Python 3.11 via .python-version)
uv sync --all-extras

# Installer les hooks pre-commit (ruff check/format, fins de ligne, YAML/JSON/TOML, clés privées)
uv run pre-commit install
```

| Commande | Base | Outils de dev (`[dependency-groups] dev`) | Extra `mlops` |
| :--- | :---: | :---: | :---: |
| `uv sync` | ✅ | ✅ | ❌ |
| `uv sync --all-extras` | ✅ | ✅ | ✅ |
| `uv sync --no-dev` (images Docker) | ✅ | ❌ | ❌ |

> Les outils de dev (pytest, ruff, pre-commit) sont un **groupe de dépendances** uv, installé par défaut : un simple `uv sync` ne les supprime plus. Pour ajouter un outil : `uv add --dev <paquet>`.

> - **Fins de ligne :** `.gitattributes` impose LF pour tous les fichiers texte, quel que soit l'OS ou le réglage `core.autocrlf`. Ne pas le contourner : des fichiers CRLF montés dans les conteneurs Linux (DAGs, SQL, scripts) peuvent casser.
> - **Version de Python :** 3.11 partout (`.python-version`, images Docker, CI). Ne pas ajouter de syntaxe ou de dépendance exigeant une version plus récente.

### Commandes quotidiennes
```bash
# 1. Vérifier le style et les imports (obligatoire avant tout commit)
uv run ruff check src/ tests/ dags/
uv run ruff format --check src/ tests/ dags/

# 2. Corriger automatiquement le formatage et les erreurs simples de lint
uv run ruff check --fix src/ tests/ dags/
uv run ruff format src/ tests/ dags/

# 3. Exécuter les tests unitaires et d'intégration avec couverture
uv run pytest -v --cov=anomalies_elec

# 4. Lancer tous les hooks pre-commit sur l'ensemble du dépôt (fichiers suivis par Git)
uv run pre-commit run --all-files
```

### Travailler avec Docker Compose
| Vous avez modifié… | Action nécessaire |
| :--- | :--- |
| `dags/*.py` | Rien : le dossier est monté dans les conteneurs Airflow (prise en compte en ~30 s) |
| `src/`, `configs/`, `pyproject.toml`, `uv.lock` | `docker compose up --build -d` (le code est copié dans les images au build) |
| `grafana/dashboards/*.json` | Rien : rechargé automatiquement par Grafana (~30 s) |
| `docker/postgres/init/*.sql` | `docker compose down -v` puis `docker compose up -d` (⚠️ efface les données locales) |

---

## 4. Workflow Git, Branches & Pull Requests

### 4.1. Nommage des branches
Ne jamais travailler directement sur `main` pour le développement des fonctionnalités. Créer une branche dédiée par fonctionnalité ou par pôle :
- `feat/p1-eco2mix-ingestion`
- `feat/p2-mstl-dynamic-threshold`
- `feat/p3-fastapi-mlflow`
- `feat/p4-grafana-evidently`
- `fix/p1-dst-timezone-handling`
- `docs/update-cadrage`

Quand la branche correspond à un ticket Jira, insérer sa clé après le pôle : `feat/p1-SCRUM-45-ingestion-temps-reel`, `fix/p2-SCRUM-23-seuil-ewma`.

### 4.2. Format des messages de commit (Conventional Commits)
Nous utilisons la convention **Conventional Commits** :
- `feat(p1): add Opendatasoft eco2mix client with quota guard`
- `feat(p2): implement Hundman nonparametric dynamic thresholding`
- `feat(p3): add FastAPI /detect and /alerts/{id}/qualify endpoints`
- `feat(p4): add Evidently Wasserstein drift report on residuals`
- `fix(p2): handle bridge days in calendar feature engineering`
- `test(p1): add unit tests for missing 15-min publication gaps`
- `docs: update README architecture diagram`

Quand le commit se rattache à un ticket Jira, terminer le titre par sa clé entre parenthèses : `feat(p1): ingestion temps réel nationale (SCRUM-45)`. Jira relie alors automatiquement le commit au ticket.

### 4.3. Critères d'acceptation d'une Pull Request (*Definition of Done*)
Avant de merger une branche dans `main` :
1. **Zéro erreur Ruff :** `uv run ruff check src/ tests/ dags/` et `uv run ruff format --check src/ tests/ dags/` passent (vérifiés par pre-commit et par la CI).
2. **Tests au vert :** `uv run pytest` passe à 100%, et toute nouvelle brique métier (P1, P2, P3, P4) inclut son test unitaire sur données synthétiques (ne dépendant pas d'un appel réseau réel à l'API Opendatasoft dans la CI).
3. **Configuration externalisée :** Aucun chemin local en dur, aucune clé ou seuil critique codé en dur dans `src/` — utiliser `configs/default.yaml` et `src/anomalies_elec/config.py`.
4. **Respect du quota API :** Les tests automatisés doivent mocker les appels HTTP vers `odre.opendatasoft.com` afin de préserver le quota mensuel de 50 000 appels.
5. **Revue croisée :** Au moins un autre membre de l'équipe (idéalement du pôle amont ou aval connecté au contrat de données) a relu et validé la PR.

> **À valider en équipe :** une exception pour les « tâches simples » (docs, typo, config sans impact sur un contrat de données) a été proposée dans SCRUM-13. Tant qu'aucune décision n'est actée (voir §5.3), la relecture croisée reste obligatoire.

---

## 5. Tickets Jira & Communication

> **Statut : proposition à valider en équipe.** Ce format reprend ce qui a bien fonctionné dans SCRUM-12, SCRUM-13, SCRUM-21 et SCRUM-45 (sections *À savoir* / *À discuter*, *Hors périmètre*, commandes prêtes à copier) et corrige ce qui a manqué : cases jamais cochées, questions laissées ouvertes dans des tickets fermés, liens `file:///` locaux, absence de lien vers la PR.

Le projet Jira est **SCRUM** (*Anomalie_Electric*). Le modèle complet à copier, avec un exemple rempli, se trouve dans [`docs/templates/ticket-jira.md`](docs/templates/ticket-jira.md).

### 5.1. Structure d'un ticket

- **Titre :** `Step N – <verbe à l'infinitif + objet>`, p. ex. `Step 8 – Collecter les données météo (Open-Meteo)`.
- **Champs :** un *assignee* nominatif, l'epic de la phase en parent, les labels `P1-data` / `P2-model` / `P3-mlops` / `P4-monitoring` + `phase-N`.
- **Langue :** titres de sections en français ; les termes techniques, noms de colonnes et commandes restent tels quels.

La description se remplit en **deux temps** :

| Moment | Sections | Rempli par |
| :--- | :--- | :--- |
| **Création** (avant le travail) | Responsable, Contexte, Périmètre, Hors périmètre, Critères d'acceptation, Dépendances | Personne qui crée le ticket |
| **Livraison** (passage en *Verification*) | Livraison (PR, commande, doc), À savoir, À discuter | Assignee |

Règles :
1. **Critères d'acceptation vérifiables** : un chiffre, une commande, un fichier ou un test. Cocher les cases au fur et à mesure ; un ticket *Done* a toutes ses cases cochées, ou le critère est barré avec une justification.
2. **À savoir** = faits utiles aux autres pôles (volumes, trous, conventions, pièges), chiffrés si possible.
3. **À discuter** = une question par ligne, avec la personne ou le pôle qui doit trancher et l'échéance : `- [ ] Pas de modélisation : 30 min ou 15 min ? — @P2 — avant Step 10`.
4. **Liens** : toujours relatifs au dépôt ou vers GitHub (`.../blob/main/docs/...`), jamais `file:///c:/...`.

### 5.2. Cycle de statuts

| Statut | Signifie |
| :--- | :--- |
| **To Do** | Partie « Création » complète, travail non commencé |
| **In Progress** | Assignee renseigné, branche créée |
| **Verification** | PR ouverte, partie « Livraison » remplie, relecture demandée |
| **Done** | PR **mergée sur `main`**, critères cochés, questions *À discuter* tranchées ou transférées |

Une question encore ouverte au moment de passer en *Done* devient un commentaire avec @mention, ou un ticket dédié si elle demande du travail.

### 5.3. Communication

| Besoin | Canal | Format |
| :--- | :--- | :--- |
| Question sur un ticket | Commentaire Jira | @mention de la personne concernée ; une question par commentaire |
| Décision prise | Commentaire Jira | Préfixe `**Décision :**` + quoi, qui, date ; puis report dans la doc concernée |
| Décision transverse (pas de temps, règle de merge, schéma SQL…) | [`docs/decisions.md`](docs/decisions.md) (à créer à la première décision) | Une ligne : date, décision, raison, ticket |
| Revue de code | PR GitHub | Commentaires sur le diff ; Jira ne garde que le lien et le résultat |
| Information urgente / blocage | Canal d'équipe | Puis trace dans le ticket concerné |

### 5.4. Traçabilité Git ↔ Jira

| Élément | Format | Exemple |
| :--- | :--- | :--- |
| Branche | `<type>/<pôle>-<CLÉ>-<sujet>` | `feat/p1-SCRUM-45-ingestion-temps-reel` |
| Commit | Conventional Commit + `(CLÉ)` | `feat(p1): ingestion temps réel nationale (SCRUM-45)` |
| Pull Request | `[CLÉ] <titre>` + champ *Ticket* du modèle de PR | `[SCRUM-45] Ingestion temps réel nationale` |

Le modèle de PR ([`.github/pull_request_template.md`](.github/pull_request_template.md)) reprend la *Definition of Done* du §4.3.
