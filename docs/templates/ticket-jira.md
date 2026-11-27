# Modèle de ticket Jira (projet SCRUM)

> **Statut : proposition à valider en équipe.** Règles détaillées : [CONTRIBUTING.md §5](../../CONTRIBUTING.md#5-tickets-jira--communication).

Copier le bloc ci-dessous dans la description du ticket. La partie **Création** est remplie avant le travail ; la partie **Livraison** au passage en *Verification*. Supprimer les lignes d'aide en italique.

## Modèle à copier

```markdown
**Responsable :** P_ (pôle) — @Prénom
**Contexte :** _1 à 3 phrases : pourquoi ce ticket, quel pôle en a besoin ensuite._

### Périmètre
- _Ce qui est livré._

### Hors périmètre
- _Ce qui ne l'est pas (et le ticket qui s'en charge, s'il existe)._

### Critères d'acceptation
- [ ] _Critère vérifiable : un chiffre, une commande, un fichier ou un test._
- [ ] Tests unitaires sur données synthétiques (pas d'appel réseau réel en CI)
- [ ] Documentation à jour (`docs/...`)

### Dépendances
- Bloqué par : SCRUM-__
- Bloque : SCRUM-__

---

### Livraison
- **PR :** <lien GitHub> — branche `feat/p_-SCRUM-__-sujet`
- **Commande :** `uv run python -m anomalies_elec....`
- **Doc :** [docs/....md](https://github.com/<org>/<repo>/blob/main/docs/....md)

### À savoir
- _Faits utiles aux autres pôles, chiffrés si possible (volumes, trous, conventions, pièges)._

### À discuter
- [ ] _Question_ — @personne ou pôle qui tranche — avant _date / Step N_
```

## Exemple rempli : SCRUM-21 (Step 8) reformaté

Contenu repris du ticket existant, réorganisé selon le modèle. Les questions *À discuter* restées ouvertes ont maintenant un responsable.

```markdown
**Responsable :** P1 (Data) — @Sathapana
**Contexte :** La température est le principal facteur explicatif de la consommation. P2 en a besoin pour les résidus du modèle (Step 10) et pour distinguer un régime saisonnier atypique d'une anomalie.

### Périmètre
- Backfill de `temperature_2m` via l'API Archive Open-Meteo (sans clé), 2012-01-01 → aujourd'hui.
- Moyenne nationale `"FR"` pondérée par la population INSEE + 12 séries régionales (codes INSEE).
- Alignement UTC sur la grille 15 min ; stockage Parquet et PostgreSQL (table `weather`).

### Hors périmètre
- Rafraîchissement planifié : géré plus tard par le DAG Airflow `ingest_eco2mix` (P3).

### Critères d'acceptation
- [x] Historique backfillé : `"FR"` pondéré + 12 capitales régionales
- [x] `ds` en UTC, grille 15 min (`:00`, `:15`, `:30`, `:45`)
- [x] Script idempotent (aucun doublon sur `(unique_id, ds)`), compatible Parquet + PostgreSQL
- [x] Documentation : `docs/collecte-meteo-open-meteo.md`

### Dépendances
- Bloqué par : SCRUM-13 (plage de l'historique éCO2mix)
- Bloque : SCRUM-22 (modèle « consommation attendue »)

---

### Livraison
- **PR :** #5 — branche `feat/p1-weather-open-meteo`
- **Commande :** `uv run python -m anomalies_elec.ingestion.weather_client` (options `--start-date`, `--end-date`)
- **Doc :** [docs/collecte-meteo-open-meteo.md](../collecte-meteo-open-meteo.md)

### À savoir
- ~15 appels HTTP au total (1 requête multi-coordonnées par an) ; 13 séries, 6 794 112 lignes, 0 valeur manquante.
- Données locales dans `data/processed/weather.parquet` (non versionné : lancer le script une fois).
- Table `weather` ajoutée à `docker/postgres/init/01_schema.sql` : faire `docker compose down -v && docker compose up -d` si le volume existait déjà.
- `PostgresStore` implémenté pour `series`, `alerts` (qualifications préservées via `COALESCE`) et `weather`.
- Pas horaire d'origine interpolé linéairement sur 15 min pour éviter des marches d'escalier dans les résidus.
- Pour P2 : `join_weather_to_series(series_df, weather_df)` dans `src/anomalies_elec/ingestion/weather_client.py`. La grille 15 min contient tous les points à 30 min, donc un `LEFT JOIN` sur `ds` suffit quel que soit le pas retenu.

### À discuter
- [ ] Rafraîchissement continu : endpoint Forecast (`minutely_15`, `past_days=1`) toutes les 15 min ou toutes les heures avec l'ingestion éCO2mix ? — @P3 — avant Step 18 (SCRUM-16)
- [ ] Exception « tâche simple » à la relecture croisée ? — équipe — à acter dans `wiki/Constats-et-decisions.md`
```
