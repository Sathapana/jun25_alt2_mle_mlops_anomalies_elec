"""Interface commune des backends de stockage et sélection du backend actif."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pandas as pd

if TYPE_CHECKING:
    from anomalies_elec.config import StorageConfig


@runtime_checkable
class Store(Protocol):
    """Contrat implémenté par `ParquetStore` (local / tests) et `PostgresStore` (services Docker).

    Tout le code applicatif (API, pipelines, DAGs) doit passer par `get_store()` et ne dépendre
    que de ces quatre méthodes, afin de pouvoir changer de backend sans toucher aux appelants.
    """

    def upsert_series(self, df: pd.DataFrame, layer: str = "processed", name: str = "eco2mix_series") -> object:
        """Insère/met à jour les séries de manière idempotente sur `(name, unique_id, ds)`."""
        ...

    def read_series(
        self,
        layer: str = "processed",
        name: str = "eco2mix_series",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        """Lit les séries d'un jeu de données, triées par `(unique_id, ds)`."""
        ...

    def upsert_alerts(self, alerts_df: pd.DataFrame, name: str = "alerts") -> object:
        """Insère/met à jour les alertes de manière idempotente sur `alert_id`."""
        ...

    def read_alerts(self, name: str = "alerts") -> pd.DataFrame:
        """Retourne toutes les alertes enregistrées."""
        ...

    def upsert_weather(self, df: pd.DataFrame, layer: str = "processed", name: str = "weather") -> object:
        """Insère/met à jour les séries météo de manière idempotente sur `(unique_id, ds)`."""
        ...

    def read_weather(
        self,
        layer: str = "processed",
        name: str = "weather",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        """Lit les séries météo triées par `(unique_id, ds)`."""
        ...


def get_store(config: StorageConfig) -> Store:
    """Instancie le backend de stockage choisi par `storage.backend` (ou la variable `STORAGE_BACKEND`)."""
    if config.backend == "postgres":
        from anomalies_elec.storage.postgres_store import PostgresStore

        return PostgresStore(config.database_url)

    from anomalies_elec.storage.parquet_store import ParquetStore

    return ParquetStore(config.data_dir)
