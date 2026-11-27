# Feuille de route

> **Instantané au 2026-11-27.** La source de vérité est le [board Jira SCRUM](https://sathapanachawananon.atlassian.net/jira/software/projects/SCRUM/boards) ; mettre à jour cette page à chaque jalon.

Légende : ✅ Done · 🔍 Verification · 🚧 In Progress · ⬜ To Do · 🏁 jalon

## Phase 1 — Fondations & conteneurisation (SCRUM-5)

| Step | Ticket | Sujet | Statut |
| :--- | :--- | :--- | :--- |
| 1 | SCRUM-9 | Kickoff : objectifs & métriques | ✅ |
| 2 | SCRUM-10 | Choix de la stack | ✅ |
| 3 | SCRUM-12 | Environnement de dev reproductible (repo + Docker) | 🔍 |
| 4 | SCRUM-13 | Backfill de l'historique national | ✅ |
| 4.1 | SCRUM-45 | Ingestion temps réel nationale | ✅ (branche à merger) |
| 5 | SCRUM-14 | Exploration & prétraitement (électricité) | 🚧 |
| 6 | SCRUM-15 | Liste des événements de référence | 🔍 |
| 7 | SCRUM-20 | Variables calendaires | 🚧 |
| 8 | SCRUM-21 | Données météo (Open-Meteo) | ✅ |
| 9 | SCRUM-17 | Deux baselines + tests unitaires | ⬜ |
| 10 | SCRUM-22 | Modèle « consommation attendue » saisonnier | ⬜ |
| 11 | SCRUM-23 | Seuil dynamique sur les résidus | ⬜ |
| 12 | SCRUM-27 | Script d'évaluation (anomalies synthétiques + événements) | ⬜ |
| 13 | SCRUM-18 | API d'inférence simple | ⬜ |
| 14 | SCRUM-28 | 🏁 Modèle de base évalué et servi | ⬜ |

## Phase 2 — Microservices, tracking & versioning (SCRUM-6)

| Step | Ticket | Sujet | Statut |
| :--- | :--- | :--- | :--- |
| 15 | SCRUM-25 | Suivi d'expériences MLflow | ⬜ |
| 16 | SCRUM-39 | Versioning données & modèles (DVC + registre MLflow) | ⬜ |
| 17 | SCRUM-11 | Conception microservices : frontières & interfaces | ⬜ |
| 18 | SCRUM-16 | Service d'ingestion (temps réel 15 min) | ⬜ |
| 19 | SCRUM-24 | Contrôles qualité des données | ⬜ |
| 20 | SCRUM-26 | Le service d'inférence charge le modèle du registre | ⬜ |
| 21 | SCRUM-40 | 🏁 Orchestration simple des services | ⬜ |

## Phase 3 — Orchestration & déploiement (SCRUM-7)

| Step | Ticket | Sujet | Statut |
| :--- | :--- | :--- | :--- |
| 22 | SCRUM-41 | Pipeline CI (GitHub Actions) — *déjà amorcé : `ci.yml`* | ⬜ |
| 23 | SCRUM-42 | Sécuriser et optimiser l'API avec NGINX | ⬜ |
| 24 | SCRUM-43 | Scalabilité Docker/Kubernetes | ⬜ |
| 25 | SCRUM-19 | 🏁 Orchestration de bout en bout finalisée et déployée | ⬜ |

## Phase 4 — Monitoring & maintenance (SCRUM-8)

| Step | Ticket | Sujet | Statut |
| :--- | :--- | :--- | :--- |
| 26 | SCRUM-32 | Monitoring de performance Prometheus/Grafana | ⬜ |
| 27 | SCRUM-29 | Détection de drift avec Evidently | ⬜ |
| 28 | SCRUM-30 | Politique d'alerting | ⬜ |
| 29 | SCRUM-31 | Mises à jour automatiques du modèle et des composants | ⬜ |
| 30 | SCRUM-34 | 🏁 Exécution sans surveillance | ⬜ |
| 31 | SCRUM-33 | *(Bonus)* Régions, partie 1 : ingestion + stratégie de modèle | ⬜ |
| 32 | SCRUM-35 | *(Bonus)* Régions, partie 2 : flotte de modèles dans le registre | ⬜ |
| 33 | SCRUM-36 | Gel du code (une semaine avant l'échéance) | ⬜ |
| 34 | SCRUM-37 | Documentation technique finale et rapport | ⬜ |
| 35 | SCRUM-38 | 🏁 Démo prête pour la soutenance | ⬜ |
