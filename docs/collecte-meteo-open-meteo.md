# Collecte des Données Météorologiques (Open-Meteo)

Documentation technique de la brique de collecte, d'alignement temporel et de stockage des températures historiques issues de l'**API Archive Open-Meteo** (pôle **P1 — Data & Ingestion**).

---

## 1. Objectif & Critères d'Acceptation

La consommation électrique française présente une forte thermosensibilité (chauffage électrique en hiver, climatisation en été). Pour permettre aux détecteurs d'anomalies (P2) et au monitoring de dérive (P4) de distinguer un **régime météorologique extrême** (vague de froid, canicule) d'une **véritable anomalie réseau**, ce module fournit des séries de température à 2 m (`temperature_2m`, en °C) :

- **Backfill historique pondéré par la population** : calcul d'une série nationale `"FR"` à partir des 12 capitales régionales métropolitaines, tout en conservant chacune des 12 séries régionales (code INSEE) pour le passage au Niveau 2.
- **Stockage en UTC aligné sur la grille de 15 minutes** (`:00`, `:15`, `:30`, `:45`), compatible directement avec les séries éCO2mix (`unique_id`, `ds`).
- **Rafraîchissement planifié différé** : le script et le pipeline couvrent le backfill historique idempotent ; l'orchestration périodique est gérée ultérieurement par le service d'ingestion (DAG Airflow).

---

## 2. Couverture Géographique & Pondération Démographique

Les coordonnées et poids démographiques INSEE des 12 capitales régionales de France métropolitaine sont externalisés dans [`configs/default.yaml`](../configs/default.yaml) (section `weather.locations`) et validés par `WeatherLocationConfig` dans [`src/anomalies_elec/config.py`](../src/anomalies_elec/config.py) :

| Code INSEE (`unique_id`) | Ville représentative | Latitude | Longitude | Poids (`weight`) |
| :--- | :--- | :---: | :---: | :---: |
| `11` | Paris | `48.8566` | `2.3522` | `0.1885` |
| `84` | Lyon | `45.7640` | `4.8357` | `0.1257` |
| `75` | Bordeaux | `44.8378` | `-0.5792` | `0.0940` |
| `76` | Toulouse | `43.6047` | `1.4442` | `0.0937` |
| `32` | Lille | `50.6292` | `3.0573` | `0.0919` |
| `44` | Strasbourg | `48.5734` | `7.7521` | `0.0853` |
| `93` | Marseille | `43.2965` | `5.3698` | `0.0793` |
| `52` | Nantes | `47.2184` | `-1.5536` | `0.0598` |
| `53` | Rennes | `48.1173` | `-1.6778` | `0.0528` |
| `28` | Rouen | `49.4432` | `1.0999` | `0.0510` |
| `27` | Dijon | `47.3220` | `5.0415` | `0.0430` |
| `24` | Orléans | `47.9029` | `1.9093` | `0.0396` |

### Agrégation nationale pondérée (`FR`)

Pour chaque horodatage $t$ sur la grille de 15 minutes UTC, la fonction `compute_population_weighted_national` calcule la température nationale pondérée sur les régions disponibles :

$$T_{\text{FR}}(t) = \frac{\sum_{i} w_i \cdot T_i(t)}{\sum_{i} w_i}$$

Les **13 séries** (`"FR"` + les 12 codes INSEE) sont persistées conjointement.

---

## 3. Méthodologie d'Alignement 15 min UTC

L'API Archive d'Open-Meteo (`https://archive-api.open-meteo.com/v1/archive`) délivre `temperature_2m` au pas **horaire** en UTC (`timezone="UTC"`).

La fonction `align_weather_to_15min_utc` ([`src/anomalies_elec/ingestion/weather_client.py`](../src/anomalies_elec/ingestion/weather_client.py)) réalise les opérations suivantes pour chaque `unique_id` :

1. Normalisation des horodatages en UTC (`datetime64[ns, UTC]`), tri chronologique et dédoublonnage sur `ds`.
2. Construction d'une grille continue au pas de `15min` de `min_ds` jusqu'à `max_ds + 45 min` en UTC.
3. Réindexation sur la grille et **interpolation linéaire temporelle** (`interpolate(method="time")`) entre chaque heure pleine, suivie d'un `ffill()` / `bfill()` pour prolonger la dernière heure collectée sur ses quarts d'heure `:15`, `:30` et `:45`.

Cela évite les sauts artificiels en escalier toutes les heures dans les modèles de consommation.

---

## 4. Contrat de Données & Stockage Dual (`ParquetStore` / `PostgresStore`)

### Schéma PostgreSQL (`weather`)

Défini dans [`docker/postgres/init/01_schema.sql`](../docker/postgres/init/01_schema.sql) :

| Colonne | Type SQL | Type Pandas | Description |
| :--- | :--- | :--- | :--- |
| `unique_id` | `TEXT NOT NULL` | `str` | `"FR"` (moyenne pondérée) ou code INSEE région |
| `ds` | `TIMESTAMPTZ NOT NULL` | `datetime64[ns, UTC]` | Horodatage UTC aligné au pas de 15 min |
| `temperature_2m` | `DOUBLE PRECISION NOT NULL` | `float64` | Température à 2 m (°C) |
| `ingested_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | — | Horodatage d'insertion/mise à jour |

- **Clé primaire / d'idempotence** : `(unique_id, ds)` avec `ON CONFLICT (unique_id, ds) DO UPDATE`.
- **Index** : `idx_weather_ds` sur `(ds)`.

### Interface `Store`

Le protocole [`Store`](../src/anomalies_elec/storage/base.py) expose deux méthodes communes aux backends `ParquetStore` (par défaut en local/tests, fichier `data/processed/weather.parquet` interrogé via DuckDB) et `PostgresStore` :

- `upsert_weather(df, layer="processed", name="weather")`
- `read_weather(layer="processed", name="weather", unique_id=None)`

Pour enrichir un `DataFrame` de consommation éCO2mix côté modélisation, utiliser `join_weather_to_series(series_df, weather_df, default_unique_id="FR")` :
- Si `unique_id` est présent dans `series_df` (couche traitée), la jointure gauche s'effectue sur `["unique_id", "ds"]`.
- Si `unique_id` est absent (par exemple sur les fichiers bruts `data/raw/eco2mix_national_cons_def/`), la fonction filtre automatiquement `weather_df` sur `unique_id == default_unique_id` (`"FR"`) et joint sur `["ds"]`.

---

## 5. Backfill Historique & Utilisation CLI

### Plage par défaut

Lorsqu'aucune borne explicite n'est fournie, `backfill_weather` collecte l'intégralité de l'historique **`2012-01-01` → date du jour (UTC)**, aligné avec l'historique consolidé éCO2mix (`2012 → 2026`) et couvrant notamment tous les événements de référence de [`configs/reference_events.yaml`](../configs/reference_events.yaml) (dont la vague de froid de février 2012).

Les requêtes sont automatiquement découpées en tranches de `max_days_per_chunk` (365 jours par défaut). Si la date de fin demandée dépasse la date maximale disponible côté Open-Meteo (erreur HTTP `400`), `OpenMeteoClient` borne automatiquement `end_date` à la date maximale renvoyée par l'API.

### Commandes CLI

```bash
# Backfill complet par défaut (2012-01-01 -> aujourd'hui)
uv run python -m anomalies_elec.ingestion.weather_client

# Backfill sur une plage personnalisée
uv run python -m anomalies_elec.ingestion.weather_client --start-date 2024-01-01 --end-date 2024-12-31

# Appel programmatique via le pipeline d'ingestion
# from anomalies_elec.pipelines.ingest_flow import run_weather_backfill
```

---

## 6. Vérification & Tests

- **Tests unitaires** (appels HTTP Open-Meteo mockés via `monkeypatch`, zéro appel réseau en CI) :
  - [`tests/test_ingestion_quality.py`](../tests/test_ingestion_quality.py) : interpolation 15 min UTC, moyenne pondérée nationale `"FR"`, backfill complet mocké, jointure `join_weather_to_series` avec et sans `unique_id`.
  - [`tests/test_storage.py`](../tests/test_storage.py) : présence de la table `weather` dans `01_schema.sql`, idempotence `ParquetStore` et `PostgresStore`.
- **Résultat du backfill local** (`data/processed/weather.parquet`) :
  - **6 794 112 lignes** sur **13 séries** (`11`, `24`, `27`, `28`, `32`, `44`, `52`, `53`, `75`, `76`, `84`, `93`, `FR`), plage `2012-01-01 00:00:00+00:00` → `2026-11-26 23:45:00+00:00`, `0` valeur manquante, fuseau `UTC`, minutes `[0, 15, 30, 45]`.
