"""Backend PostgreSQL — squelette à implémenter par P1.

Le schéma des tables (`series`, `alerts`, `monitoring_metrics`) est défini dans
`docker/postgres/init/01_schema.sql`, qui fait foi pour tous les pôles.

Pistes d'implémentation (P1) :
- écriture idempotente via `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update(...)`
  sur la clé primaire de chaque table ;
- le paramètre `name` de `upsert_series` / `read_series` correspond à la colonne `source` ;
- le paramètre `layer` n'a pas d'équivalent en base (il est propre au backend Parquet) ;
- `ds` doit être relu en `datetime64[ns, UTC]` pour rester compatible avec `ParquetStore`.

Tant que ce backend n'est pas implémenté, laisser `storage.backend: parquet` (valeur par défaut).
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class PostgresStore:
    """Implémentation PostgreSQL du contrat `anomalies_elec.storage.base.Store`."""

    def __init__(self, database_url: str) -> None:
        # `create_engine` n'ouvre aucune connexion : l'instanciation reste possible sans base active.
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True)

    def ping(self) -> bool:
        """Vérifie que la base répond (utilisable pour un healthcheck)."""
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    def upsert_series(self, df: pd.DataFrame, layer: str = "processed", name: str = "eco2mix_series") -> int:
        # TODO(P1): upsert dans `series` sur (source=name, unique_id, ds) ; retourner le nombre de lignes.
        raise NotImplementedError("PostgresStore.upsert_series — à implémenter par P1")

    def read_series(
        self,
        layer: str = "processed",
        name: str = "eco2mix_series",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        # TODO(P1): SELECT ... FROM series WHERE source = :name [AND unique_id = :unique_id] ORDER BY unique_id, ds
        raise NotImplementedError("PostgresStore.read_series — à implémenter par P1")

    def upsert_alerts(self, alerts_df: pd.DataFrame, name: str = "alerts") -> int:
        # TODO(P1): upsert dans `alerts` sur alert_id (en conservant les colonnes de qualification).
        raise NotImplementedError("PostgresStore.upsert_alerts — à implémenter par P1")

    def read_alerts(self, name: str = "alerts") -> pd.DataFrame:
        # TODO(P1): SELECT * FROM alerts ORDER BY ds
        raise NotImplementedError("PostgresStore.read_alerts — à implémenter par P1")
