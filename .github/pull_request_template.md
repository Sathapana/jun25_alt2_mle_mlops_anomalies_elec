<!-- Titre de la PR : [SCRUM-xx] <titre court> -->

**Ticket :** SCRUM-xx
**Pôle :** P_

## Résumé
<!-- Ce que la PR change et pourquoi, en 2-3 phrases. -->

## Comment vérifier
<!-- Commandes à lancer, données attendues, captures si utile. -->
```bash
uv run pytest -v
```

## À savoir / À discuter
<!-- Points pour les autres pôles et questions ouvertes (à reporter aussi dans le ticket Jira). -->

## Definition of Done (CONTRIBUTING §4.3)
- [ ] `uv run ruff check src/ tests/ dags/` et `uv run ruff format --check src/ tests/ dags/` passent
- [ ] `uv run pytest` passe ; nouvelle brique testée sur données synthétiques
- [ ] Aucun chemin, clé ou seuil codé en dur (`configs/default.yaml`)
- [ ] Appels HTTP mockés dans les tests (quota Opendatasoft)
- [ ] Relecture croisée demandée à : @
- [ ] Ticket Jira : section Livraison remplie, statut *Verification*
