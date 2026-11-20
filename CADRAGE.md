# Détection d'anomalies sur le réseau électrique français (MLOps)

> **Statut :** Kickoff & cadrage — Document à compléter et valider en équipe.
> **Spécification du projet :** [docs/anomalies-reseau-electrique.md](docs/anomalies-reseau-electrique.md)
> **Revue de littérature :** [docs/revue-litterature.md](docs/revue-litterature.md)

---

## Tâche 1 — Kickoff : Objectifs du projet & Métriques clés (Charte 1-page)

### 1.1. Énoncé du problème (*One-sentence problem statement*)
> *Proposition à valider / ajuster par l'équipe :*
> « Construire un service MLOps automatisé de bout en bout qui surveille en continu les données éCO2mix de RTE afin de détecter les anomalies de consommation, de production ou de mesure, tout en distinguant les vrais incidents des effets saisonniers et calendaires. »

- [ ] Validé par l'équipe *(ou remplacer ci-dessous)* :
  - **Énoncé retenu :** `[À compléter si modifié]`

---

### 1.2. Métriques clés & Budget d'alertes (*Success Criteria*)

| Catégorie | Métrique | Cible / Seuil retenu | Commentaire |
| :--- | :--- | :--- | :--- |
| **Performance (anomalies synthétiques)** | Précision / Rappel ($F_{0.5}$ ou $F_1$) | Précision $\ge$ `[ex: 80%]` / Rappel $\ge$ `[ex: 75%]` | Priorité à la précision pour limiter la fatigue d'alerte |
| **Réactivité** | Délai de détection (*Detection delay*) | $\le$ `[ex: 30 min (2 pas de 15 min)]` | Temps entre l'apparition de l'anomalie et l'alerte |
| **Volume opérationnel** | Budget d'alertes (*Alert budget*) | Max `[ex: 5]` alertes / semaine | Au-delà, ajustement du seuil / *pruning* |
| **Évaluation qualitative** | Comportement sur événements de référence | `[ex: Détecter X / Ne pas alerter en continu sur Y]` | Ex. : vague de froid, canicule, jours fériés, mouvements sociaux |

---

### 1.3. Répartition des rôles (P1 – P4)

| Rôle | Périmètre principal | Membre assigné |
| :--- | :--- | :--- |
| **P1 — Data & Ingestion** | API éCO2mix (temps réel & consolidé), contrôles qualité, stockage, calendrier | `[Nom / Prénom]` |
| **P2 — Modélisation & Détection** | Baselines ($J-7$, prévision RTE), désaisonnalisation (MSTL), seuillage dynamique | `[Nom / Prénom]` |
| **P3 — MLOps & Orchestration** | Pipeline automatisé, tracking MLflow, CI/CD, API FastAPI, réentraînement | `[Nom / Prénom]` |
| **P4 — Observabilité & Dashboard** | Monitoring (Evidently : qualité / drift), dashboard, boucle de qualification | `[Nom / Prénom]` |

---

## Tâche 2 — Choix de la stack technique (*Tool Stack*)

> Cocher l'option retenue pour chaque composant et compléter la justification en **une ligne**.

### 2.1. Orchestrateur / Scheduler
- [ ] **Prefect**
- [ ] **Apache Airflow**
- **Justification (1 ligne) :** `[À compléter — ex: Prefect choisi pour sa légèreté en Python natif et sa mise en place rapide vs Airflow]`

### 2.2. Stockage des données (*Storage*)
- [ ] **Parquet** (fichiers partitionnés / DuckDB)
- [ ] **PostgreSQL** (ou TimescaleDB)
- [ ] **Hybride** (Parquet pour l'historique analytique + Postgres pour les alertes/métadonnées)
- **Justification (1 ligne) :** `[À compléter — ex: Parquet partitionné par date pour les séries temporelles éCO2mix, simple et sans serveur]`

### 2.3. Suivi d'expériences & Registre de modèles (*Tracking*)
- [x] **MLflow** *(imposé)*
- **Justification (1 ligne) :** `[À compléter — ex: Standard pour versionner les modèles, paramètres de seuillage, métriques et artefacts]`

### 2.4. API de service (*Serving*)
- [x] **FastAPI** *(imposé)*
- **Justification (1 ligne) :** `[À compléter — ex: Framework Python asynchrone léger avec validation Pydantic et documentation OpenAPI native]`

### 2.5. Tableau de bord (*Dashboard*)
- [ ] **Streamlit**
- [ ] **Grafana**
- **Justification (1 ligne) :** `[À compléter — ex: Streamlit pour prototyper rapidement l'interface de qualification humaine des alertes]`

---

## Validation du Kickoff

- **Date de validation :** `[JJ/MM/AAAA]`
- **Participants :** `[Liste des membres présents]`
- [ ] Charte 1-page et choix de stack validés et commités sur `main`.
