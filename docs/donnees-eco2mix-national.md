# Historique national éCO2mix — backfill et constats sur les données

Jeu de données : `eco2mix-national-cons-def` (données nationales consolidées et définitives, RTE / ODRÉ).
Analyse réalisée le 2026-11-26 sur l'export complet (514 272 lignes).

## 1. Lancer le backfill

```bash
# Télécharge l'export complet (1 seul appel API) puis écrit les partitions
uv run python -m anomalies_elec.ingestion.backfill

# Rejouer à partir d'un export déjà téléchargé (aucun appel API)
uv run python -m anomalies_elec.ingestion.backfill --input data/raw/_downloads/eco2mix-national-cons-def.parquet
```

Le script est **rejouable** : chaque exécution réécrit chaque partition annuelle de façon atomique, sans doublon.
Il faut le relancer après les révisions de RTE (les données « consolidées » deviennent « définitives »).

## 2. Méthode et choix

| Choix | Raison |
| :--- | :--- |
| Endpoint `/exports/parquet` | 1 appel pour tout l'historique. Avec `/records` (100 lignes par appel, `offset + limit` ≤ 10 000), l'historique serait inatteignable et coûterait plus de 5 000 appels sur un quota de 50 000/mois. |
| Paramètre `timezone=UTC` | `date_heure` est renvoyé directement en UTC ; la colonne `ds` (UTC) est ajoutée. Les colonnes locales `date` / `heure` sont conservées pour la traçabilité. |
| Partition **par année** (`year=YYYY/data.parquet`) | Une partition par jour produirait ~5 400 fichiers de 96 lignes (problème des petits fichiers : lecture lente, métadonnées lourdes). Une année ≈ 35 000 lignes ≈ 1,7 Mo (26 Mo au total). |
| Réécriture complète des partitions | Plus simple et plus sûr qu'un upsert ligne à ligne pour un historique complet ; prend en compte les révisions de RTE. |
| Couche brute fidèle à la source | Aucune valeur n'est modifiée ni interpolée ; seules les lignes fantômes du passage à l'heure d'été sont retirées (voir 3.3). |

Lecture :

```python
from pathlib import Path
from anomalies_elec.ingestion.backfill import read_partitions

df = read_partitions(Path("data/raw/eco2mix_national_cons_def"))
```

Le rapport complet est écrit dans `data/raw/eco2mix_national_cons_def/_time_step_report.json`.

## 3. Constats sur le pas de temps

### 3.1. Lignes : 15 min, sans changement sur tout l'historique
Une ligne toutes les 15 minutes du 2012-01-01 au 2026-08-31 (heure de Paris), sans changement de pas d'une année à l'autre.

### 3.2. ⚠️ Mesures : 30 min seulement
| Colonnes | Pas effectif |
| :--- | :--- |
| `consommation` et production par filière (`nucleaire`, `eolien`, ...) , `taux_co2` | **30 min** (valeurs aux minutes :00 et :30 ; :15 et :45 toujours vides) |
| `prevision_j1`, `prevision_j` | 15 min |

Même constat de 2012 à 2026 : aucun changement de pas sur l'historique.

**Impact pour P2 :** sur ce jeu de données, la série de consommation a **48 points par jour** et **336 par semaine**.
La configuration actuelle (`freq: 15min`, `mstl_season_lengths: [96, 672]`, `weekly_lag_steps: 672`) suppose 15 min.
Il faut soit rééchantillonner à 30 min, soit adapter ces paramètres pour l'historique consolidé.
Le pas du flux temps réel (`eco2mix-national-tr`) reste à vérifier.

### 3.3. Passage à l'heure d'été (mars) : lignes fantômes supprimées
Les jours de passage à l'heure d'été, la source contient aussi les heures locales **inexistantes** 02:00–02:45.
L'API les convertit vers les mêmes instants UTC que 03:00–03:45, d'où **60 doublons** (4 lignes × 15 ans).
Le backfill supprime ces 60 lignes fantômes et garde les vraies lignes 03:xx. La liste est dans le rapport (`dropped_dst_phantom_rows`).

### 3.4. Passage à l'heure d'hiver (octobre) : 1 heure manquante à la source
La première occurrence de 02:00–02:45 (heure d'été) est absente de la source. En UTC, cela donne **un trou de 1 h** (pas de 75 min) chaque année : **14 trous** (2012 à 2025).
Le trou n'est pas comblé dans la couche brute. Il devra être signalé par le contrôle qualité (`quality_flag = "MISSING_GAP"`) en couche traitée.

### 3.5. Autres points
- **Une seule mesure manquante** : `consommation` au 2026-01-01 00:00 (heure de Paris).
- **2026 = données consolidées** (23 320 lignes), non encore définitives : relancer le backfill après publication des définitives.
- **Colonnes texte** : `gaz_cogen` et `ech_comm_allemagne_belgique` contiennent la valeur `"ND"` (non disponible) ; à convertir en numérique (`NaN`) en couche traitée.
- **Fin de couverture au 2026-08-31** : la suite (septembre à aujourd'hui) doit venir du flux temps réel `eco2mix-national-tr` (tâche séparée).
- **Partition `year=2011`** : 4 lignes au 2011-12-31 23:00–23:45 UTC, qui correspondent au 2012-01-01 00:00–00:45 heure de Paris (partitionnement en année UTC).
