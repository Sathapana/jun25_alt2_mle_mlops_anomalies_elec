# Ingestion temps réel nationale éCO2mix (`eco2mix-national-tr`)

Prend le relais de l'historique consolidé (voir [donnees-eco2mix-national.md](donnees-eco2mix-national.md)), qui s'arrête au 2026-08-31.
Constats établis le 2026-11-27 sur le jeu réel.

## 1. Commandes

```bash
# Rattrapage : tout le contenu du jeu temps réel (1 appel /exports). À lancer une fois.
uv run python -m anomalies_elec.ingestion.realtime --catch-up

# Rattrapage depuis un export déjà téléchargé (aucun appel API)
uv run python -m anomalies_elec.ingestion.realtime --catch-up --input data/raw/eco2mix_national_tr/exports/<fichier>.parquet

# Une exécution incrémentale (ce que fait le DAG toutes les 15 min)
uv run python -m anomalies_elec.ingestion.realtime
```

En production, l'incrémental tourne dans le DAG Airflow `ingest_eco2mix` (`*/15 * * * *`, en pause à la création : à activer dans l'UI).
Le stockage suit `STORAGE_BACKEND` (`parquet` ou `postgres`) ; les données vont dans `series` avec `source = 'national_tr'`.

## 2. Ce qu'il faut savoir sur le jeu temps réel

| Constat | Conséquence |
| :--- | :--- |
| Le jeu commence au **2026-08-31 22:00 UTC**, exactement après la fin de l'historique consolidé (21:45 UTC) | Il ne garde qu'une **fenêtre glissante** : les données temps réel disparaissent quand les données consolidées sont publiées. **Il faut les archiver nous-mêmes** (indispensable pour l'audit M+1). |
| `consommation` au **pas de 15 min** (contre 30 min dans l'historique consolidé) | Pas natif conservé en stockage ; le choix du pas de modélisation relève de P2. |
| Publication avec **~20 min de retard** | Fenêtre de recouvrement (voir 3.1). |
| Le jeu contient déjà **toutes les lignes du reste de la journée** (prévisions seules, `consommation` vide) | Ces points « pas encore publiés » sont écartés, et non marqués `MISSING_VALUE` (voir 3.2). |
| Passage à l'heure d'hiver du 2026-10-25 : **1 h manquante**, comme dans l'historique | Marqué `MISSING_GAP` par le contrôle qualité (1 point sur 8 358). |

## 3. Fonctionnement

### 3.1. Fenêtre de recouvrement
Chaque exécution relit les **6 dernières heures** (`ingestion.realtime_window_hours`), soit 25 lignes, en **1 seul appel** `/records` (limite : 100 lignes par appel, vérifiée au démarrage).
Chaque point est donc relu une vingtaine de fois : un point publié en retard ou révisé par RTE est récupéré aux exécutions suivantes.
L'upsert sur `(source, unique_id, ds)` empêche les doublons.

**Quota :** 96 appels/jour ≈ 3 000 par mois sur 50 000. Le quota restant est journalisé à chaque appel.

### 3.2. Points pas encore publiés
On retire les points futurs, puis tous les points situés après la dernière consommation publiée.
Une consommation vide **suivie** de valeurs publiées est conservée : c'est un vrai manque, marqué `MISSING_VALUE`.

### 3.3. Lignes de contexte non réécrites
Les contrôles « trou » (`MISSING_GAP`) et « capteur figé » (`FROZEN_SENSOR`) comparent chaque point aux précédents.
Les 4 premiers points de la fenêtre (`max_frozen_steps`) n'ont pas assez d'historique dans la fenêtre : ils servent de contexte mais **ne sont pas réécrits**.
Ils ont déjà été évalués correctement lors d'exécutions précédentes ; sans cette règle, un `MISSING_GAP` serait écrasé par `OK` (couvert par un test).

### 3.4. Archive brute
Avant tout nettoyage, chaque réponse de l'API est conservée telle quelle :
- incrémental : `data/raw/eco2mix_national_tr/fetched/date=YYYY-MM-DD.jsonl` (une ligne par appel, avec `fetched_at`). Un fichier par jour plutôt qu'un par appel, pour éviter ~35 000 petits fichiers par an ;
- rattrapage : `data/raw/eco2mix_national_tr/exports/eco2mix-national-tr_<horodatage>.parquet`.

L'archive permet de retraiter sans appel API et de savoir **ce que l'on savait à un instant donné** (audit M+1).

## 4. Vérifications réalisées
- Rattrapage réel : 8 448 lignes reçues, 8 357 stockées (91 points pas encore publiés écartés), en 1 appel.
- DAG Airflow exécuté deux fois avec `STORAGE_BACKEND=postgres` : 19 lignes écrites à chaque fois, aucune ligne en double (`ingested_at` mis à jour).
- Table `series` (`source = 'national_tr'`) : 8 358 lignes, `ds` unique, du 2026-08-31 22:00 au 2026-11-27 00:15 UTC.

## 5. Remarque Airflow
Le log de la tâche affiche `ModuleNotFoundError: No module named 'pendulum'` et un avertissement « Airflow is not properly installed ».
C'est attendu : Airflow n'est volontairement pas installé dans le virtualenv projet (`/opt/anomalies-venv`) ; les paramètres sont alors transmis par pickle et la tâche fonctionne normalement.
