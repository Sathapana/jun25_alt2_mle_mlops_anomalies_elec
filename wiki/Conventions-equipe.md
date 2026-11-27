# Conventions d'équipe

> **Statut : proposition à valider en équipe.** Règles complètes : [CONTRIBUTING §4–5](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/CONTRIBUTING.md#5-tickets-jira--communication). Modèle de ticket : [docs/templates/ticket-jira.md](https://github.com/Sathapana/jun25_alt2_mle_mlops_anomalies_elec/blob/main/docs/templates/ticket-jira.md).

## Ticket Jira en deux temps

| Moment | Sections |
| :--- | :--- |
| **Création** (avant le travail) | Responsable · Contexte · Périmètre · Hors périmètre · Critères d'acceptation · Dépendances |
| **Livraison** (passage en *Verification*) | Livraison (PR, commande, doc) · À savoir · À discuter |

- Titre : `Step N – <verbe à l'infinitif + objet>`.
- Labels : pôle (`P1-data`, `P3-mlops`…) + `phase-N` ; epic de la phase en parent ; assignee nominatif.
- Critères **vérifiables** et cochés au fil de l'eau.
- *À discuter* : une question par ligne, avec qui tranche et pour quand.
- Liens vers GitHub, jamais `file:///`.

## Statuts

| Statut | Signifie |
| :--- | :--- |
| To Do | Partie « Création » complète |
| In Progress | Assignee + branche créée |
| Verification | PR ouverte, « Livraison » remplie, relecture demandée |
| Done | PR **mergée sur `main`**, critères cochés, questions tranchées ou transférées |

## Communication

| Besoin | Où |
| :--- | :--- |
| Question sur un ticket | Commentaire Jira avec @mention |
| Décision | Commentaire `**Décision :**` + ligne dans [Constats et décisions](Constats-et-decisions) |
| Revue de code | PR GitHub |
| Urgence / blocage | Canal d'équipe, puis trace dans le ticket |

## Git ↔ Jira

| Élément | Exemple |
| :--- | :--- |
| Branche | `feat/p1-SCRUM-45-ingestion-temps-reel` |
| Commit | `feat(p1): ingestion temps réel nationale (SCRUM-45)` |
| PR | `[SCRUM-45] Ingestion temps réel nationale` (modèle de PR pré-rempli) |

## Definition of Done d'une PR
1. Ruff (`check` + `format --check`) sans erreur.
2. `pytest` au vert ; nouvelle brique testée sur données synthétiques.
3. Pas de chemin, clé ou seuil codé en dur (`configs/default.yaml`).
4. Appels HTTP mockés dans les tests (quota Opendatasoft 50 000/mois).
5. Relecture croisée par un autre membre (exception « tâche simple » en discussion).
