# Constats et décisions

Page de référence pour **ce qu'on a appris sur les données**, **ce qu'on a décidé** et **ce qui reste ouvert**. Ajouter une ligne par PR (voir [Conventions d'équipe](Conventions-equipe)) ; la décision est aussi notée en commentaire `**Décision :**` dans le ticket Jira concerné.

## Constats sur les données

| # | Constat | Impact | Source |
| :--- | :--- | :--- | :--- |
| C1 | Historique consolidé : `consommation` et production au **pas de 30 min** (:15 et :45 toujours vides), prévisions RTE à 15 min | Série de 48 points/jour ; `mstl_season_lengths: [96, 672]` et `weekly_lag_steps: 672` supposent 15 min | SCRUM-13 |
| C2 | Flux temps réel : `consommation` au **pas de 15 min** | Pas différent de l'historique : choix du pas de modélisation à faire (Q1) | SCRUM-45 |
| C3 | Passage à l'heure d'été : **60 lignes fantômes** (heures locales inexistantes 02:xx) | Supprimées au backfill | SCRUM-13 |
| C4 | Passage à l'heure d'hiver : **1 h manquante** chaque année (14 trous 2012–2025, + 2026-10-25 en TR) | Non comblé en couche brute ; `MISSING_GAP` en couche traitée | SCRUM-13, SCRUM-45 |
| C5 | Valeurs texte `"ND"` dans `gaz_cogen` et `ech_comm_allemagne_belgique` | Convertir en `NaN` en couche traitée | SCRUM-13 |
| C6 | Une seule mesure manquante : `consommation` au 2026-01-01 00:00 (Paris) | Négligeable | SCRUM-13 |
| C7 | Historique consolidé arrêté au **2026-08-31** ; 2026 encore « consolidé », pas « définitif » | Relancer le backfill à la publication des définitives | SCRUM-13 |
| C8 | Le jeu temps réel est une **fenêtre glissante** (les lignes disparaissent à la publication du consolidé) | Archiver nous-mêmes chaque réponse API (audit M+1) | SCRUM-45 |
| C9 | Le TR contient les lignes futures de la journée (prévisions seules, consommation vide) et est publié avec ~20 min de retard | Points non publiés écartés ; fenêtre de recouvrement de 6 h | SCRUM-45 |
| C10 | Open-Meteo Archive est horaire | Interpolation linéaire sur 15 min (évite des marches dans les résidus) | SCRUM-21 |

## Journal des décisions

| Date | Décision | Raison | Ticket |
| :--- | :--- | :--- | :--- |
| 2026-11-25 | Stack : **Airflow**, **PostgreSQL**, **Grafana** (MLflow et FastAPI imposés) | Airflow enseigné et répandu ; PostgreSQL gère la concurrence API/workers/dashboard ; Grafana branché sur PostgreSQL | SCRUM-10 |
| 2026-11-26 | Tous les horodatages en **UTC** (`ds`) | Lags saisonniers fixes cassés par les changements d'heure en heure locale | SCRUM-13 |
| 2026-11-26 | Backfill via `/exports` (1 appel) plutôt que `/records` paginé | Quota 50 000/mois ; `/records` plafonné à 10 000 lignes | SCRUM-13 |
| 2026-11-26 | Accès au stockage uniquement via `get_store()` | Même code pour Parquet et PostgreSQL | CONTRIBUTING §2 |
| 2026-11-27 | Données stockées au **pas d'origine** ; le pas de modélisation est choisi par P2 en couche traitée | Ne pas perdre d'information à l'ingestion | SCRUM-45 |
| 2026-11-27 | Partition Parquet **par année** *(appliquée, à confirmer en équipe)* | ~5 400 petits fichiers si partition par jour | SCRUM-13 |

## Questions ouvertes

| # | Question | Qui tranche | Échéance |
| :--- | :--- | :--- | :--- |
| Q1 | Pas de modélisation : rééchantillonner à 30 min, ou garder 15 min et adapter MSTL / J-7 selon le jeu ? | P2 | avant Step 10 (SCRUM-22) |
| Q2 | Rafraîchissement météo : endpoint Forecast (`minutely_15`) toutes les 15 min, ou toutes les heures avec l'ingestion éCO2mix ? | P3 | avant Step 18 (SCRUM-16) |
| Q3 | Exception à la relecture croisée pour les « tâches simples » (docs, typo, config) ? | Équipe | prochaine réunion |
| Q4 | Format de ticket et conventions de communication ([proposition](Conventions-equipe)) | Équipe | prochaine réunion |
| Q5 | Cibles chiffrées des métriques et noms des rôles P1–P4 dans [CADRAGE.md](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/CADRAGE.md) | Équipe | clôture Step 1 |
