"""Stockage Parquet idempotent avec dédoublonnage SQL via DuckDB."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


class ParquetStore:
    """Gestionnaire de lecture/écriture Parquet idempotent pour séries temporelles et alertes."""

    def __init__(self, base_dir: str | Path = "data") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _dataset_path(self, layer: str, name: str) -> Path:
        target_dir = self.base_dir / layer
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{name}.parquet"

    def upsert_series(
        self,
        df: pd.DataFrame,
        layer: str = "processed",
        name: str = "eco2mix_series",
    ) -> Path:
        """Sauvegarde ou fusionne de manière idempotente sur la clé `(unique_id, ds)`."""
        path = self._dataset_path(layer, name)
        incoming = df.copy()
        incoming["ds"] = pd.to_datetime(incoming["ds"], utc=True)

        if path.exists():
            existing = pd.read_parquet(path)
            existing["ds"] = pd.to_datetime(existing["ds"], utc=True)
            combined = pd.concat([existing, incoming], ignore_index=True)
        else:
            combined = incoming

        deduped = (
            combined.drop_duplicates(subset=["unique_id", "ds"], keep="last")
            .sort_values(["unique_id", "ds"])
            .reset_index(drop=True)
        )
        deduped.to_parquet(path, index=False)
        return path

    def read_series(
        self,
        layer: str = "processed",
        name: str = "eco2mix_series",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        """Lit les séries stockées en filtrant optionnellement via DuckDB."""
        path = self._dataset_path(layer, name)
        if not path.exists():
            return pd.DataFrame()

        con = duckdb.connect()
        try:
            if unique_id:
                query = "SELECT * FROM read_parquet(?) WHERE unique_id = ? ORDER BY ds ASC"
                df = con.execute(query, [str(path), unique_id]).df()
            else:
                query = "SELECT * FROM read_parquet(?) ORDER BY unique_id, ds ASC"
                df = con.execute(query, [str(path)]).df()
        finally:
            con.close()

        if "ds" in df.columns:
            df["ds"] = pd.to_datetime(df["ds"], utc=True)
        return df

    def upsert_alerts(
        self,
        alerts_df: pd.DataFrame,
        name: str = "alerts",
    ) -> Path:
        """Sauvegarde ou met à jour les alertes de manière idempotente sur `alert_id`."""
        path = self._dataset_path("alerts", name)
        incoming = alerts_df.copy()
        if "ds" in incoming.columns:
            incoming["ds"] = pd.to_datetime(incoming["ds"], utc=True)

        if path.exists():
            existing = pd.read_parquet(path)
            if "ds" in existing.columns:
                existing["ds"] = pd.to_datetime(existing["ds"], utc=True)
            combined = pd.concat([existing, incoming], ignore_index=True)
        else:
            combined = incoming

        deduped = combined.drop_duplicates(subset=["alert_id"], keep="last").sort_values("ds").reset_index(drop=True)
        deduped.to_parquet(path, index=False)
        return path

    def read_alerts(self, name: str = "alerts") -> pd.DataFrame:
        """Retourne l'ensemble des alertes enregistrées."""
        path = self._dataset_path("alerts", name)
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        if "ds" in df.columns:
            df["ds"] = pd.to_datetime(df["ds"], utc=True)
        return df

    def upsert_weather(
        self,
        df: pd.DataFrame,
        layer: str = "processed",
        name: str = "weather",
    ) -> Path:
        """Sauvegarde ou fusionne les données météo de manière idempotente sur `(unique_id, ds)`."""
        path = self._dataset_path(layer, name)
        incoming = df[["unique_id", "ds", "temperature_2m"]].copy()
        incoming["unique_id"] = incoming["unique_id"].astype(str)
        incoming["ds"] = pd.to_datetime(incoming["ds"], utc=True)
        incoming["temperature_2m"] = pd.to_numeric(incoming["temperature_2m"], errors="coerce")

        if path.exists():
            existing = pd.read_parquet(path)
            existing["ds"] = pd.to_datetime(existing["ds"], utc=True)
            combined = pd.concat([existing, incoming], ignore_index=True)
        else:
            combined = incoming

        deduped = (
            combined.drop_duplicates(subset=["unique_id", "ds"], keep="last")
            .sort_values(["unique_id", "ds"])
            .reset_index(drop=True)
        )
        deduped.to_parquet(path, index=False)
        return path

    def read_weather(
        self,
        layer: str = "processed",
        name: str = "weather",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        """Lit les séries météo stockées en filtrant optionnellement via DuckDB."""
        path = self._dataset_path(layer, name)
        if not path.exists():
            return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

        con = duckdb.connect()
        try:
            if unique_id:
                query = "SELECT unique_id, ds, temperature_2m FROM read_parquet(?) WHERE unique_id = ? ORDER BY ds ASC"
                df = con.execute(query, [str(path), unique_id]).df()
            else:
                query = "SELECT unique_id, ds, temperature_2m FROM read_parquet(?) ORDER BY unique_id, ds ASC"
                df = con.execute(query, [str(path)]).df()
        finally:
            con.close()

        if "ds" in df.columns:
            df["ds"] = pd.to_datetime(df["ds"], utc=True)
        return df
