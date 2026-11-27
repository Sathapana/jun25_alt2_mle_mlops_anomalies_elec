# Données

Détail : [donnees-eco2mix-national.md](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/docs/donnees-eco2mix-national.md) · [collecte-meteo-open-meteo.md](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/docs/collecte-meteo-open-meteo.md) · [eda-preprocessing-methodology.md](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/docs/eda-preprocessing-methodology.md) · [ingestion-temps-reel.md](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/feat/p1-ingestion-temps-reel/docs/ingestion-temps-reel.md) (branche en attente de merge).

## Sources

| Jeu | Couverture | Pas | Accès | Ticket |
| :--- | :--- | :--- | :--- | :--- |
| `eco2mix-national-cons-def` (consolidé/définitif) | 2012-01-01 → 2026-08-31 · 514 272 lignes | lignes 15 min, **mesures 30 min** | 1 appel `/exports/parquet` | SCRUM-13 |
| `eco2mix-national-tr` (temps réel) | depuis 2026-08-31 22:00 UTC (**fenêtre glissante**) | 15 min, publié ~20 min après | rattrapage `/exports` + incrémental `/records` toutes les 15 min | SCRUM-45 |
| Open-Meteo Archive (`temperature_2m`) | 2012-01-01 → aujourd'hui · 13 séries, 6 794 112 lignes | horaire → interpolé 15 min | ~15 appels, sans clé | SCRUM-21 |
| `eco2mix-regional-*` | — | horaire | prévu Niveau 2 (Steps 31–32) | SCRUM-33 |

Quota Opendatasoft : **50 000 appels/mois**. Cible de l'ingestion temps réel : ~3 000/mois (96/jour).

## Couches de stockage

| Couche | Emplacement (backend Parquet) | Contenu |
| :--- | :--- | :--- |
| Brute | `data/raw/eco2mix_national_cons_def/year=YYYY/` | Fidèle à la source, partition par année UTC ; seules les lignes fantômes DST retirées |
| Brute TR | `data/raw/eco2mix_national_tr/fetched/date=…jsonl`, `…/exports/` | Chaque réponse API archivée telle quelle (indispensable pour l'audit M+1) |
| Traitée | `data/processed/` (dont `weather.parquet`) | Contrôle qualité + calendrier + météo, format `(unique_id, ds, y, …)` |
| PostgreSQL | tables `series`, `alerts`, `weather`, `monitoring_metrics` | Clé `(source, unique_id, ds)` pour `series`, `(unique_id, ds)` pour `weather` |

## Séries météo
- `"FR"` : moyenne nationale pondérée par la population INSEE des 12 régions métropolitaines.
- `11`, `24`, `27`, `28`, `32`, `44`, `52`, `53`, `75`, `76`, `84`, `93` : séries régionales (codes INSEE), prêtes pour le Niveau 2.
- Jointure prête pour P2 : `join_weather_to_series(series_df, weather_df)` dans `ingestion/weather_client.py`.

## Événements de référence
Catalogue dans [`configs/reference_events.yaml`](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/configs/reference_events.yaml) (SCRUM-15) : vague de froid février 2012, pont du 15 août 2023, canicule août 2023, mouvements sociaux mars 2023.
