"""Backend PostgreSQL implémentant le contrat `anomalies_elec.storage.base.Store`.

Le schéma des tables (`series`, `alerts`, `monitoring_metrics`, `weather`) est défini dans
`docker/postgres/init/01_schema.sql`, qui fait foi pour tous les pôles.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_CHUNK_SIZE = 2000


def _to_utc_datetime(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _to_float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _to_bool_or_none(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    return bool(value)


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
        """Insère ou met à jour les séries dans `series` de manière idempotente sur `(source, unique_id, ds)`."""
        if df.empty:
            return 0

        deduped = df.copy()
        deduped["ds"] = pd.to_datetime(deduped["ds"], utc=True)
        deduped = deduped.drop_duplicates(subset=["unique_id", "ds"], keep="last")

        records = [
            {
                "source": name,
                "unique_id": str(row.get("unique_id")),
                "ds": _to_utc_datetime(row.get("ds")),
                "y": _to_float_or_none(row.get("y")),
                "prevision_j1": _to_float_or_none(row.get("prevision_j1")),
                "prevision_j": _to_float_or_none(row.get("prevision_j")),
                "quality_flag": str(row.get("quality_flag") or "OK"),
                "is_holiday_fr": _to_bool_or_none(row.get("is_holiday_fr")),
                "is_bridge_day": _to_bool_or_none(row.get("is_bridge_day")),
                "is_dst_transition": _to_bool_or_none(row.get("is_dst_transition")),
            }
            for row in deduped.to_dict(orient="records")
        ]

        stmt = text(
            """
            INSERT INTO series (
                source, unique_id, ds, y, prevision_j1, prevision_j,
                quality_flag, is_holiday_fr, is_bridge_day, is_dst_transition
            )
            VALUES (
                :source, :unique_id, :ds, :y, :prevision_j1, :prevision_j,
                :quality_flag, :is_holiday_fr, :is_bridge_day, :is_dst_transition
            )
            ON CONFLICT (source, unique_id, ds) DO UPDATE SET
                y = EXCLUDED.y,
                prevision_j1 = EXCLUDED.prevision_j1,
                prevision_j = EXCLUDED.prevision_j,
                quality_flag = EXCLUDED.quality_flag,
                is_holiday_fr = EXCLUDED.is_holiday_fr,
                is_bridge_day = EXCLUDED.is_bridge_day,
                is_dst_transition = EXCLUDED.is_dst_transition,
                ingested_at = CURRENT_TIMESTAMP
            """
        )

        with self.engine.begin() as conn:
            for start in range(0, len(records), _CHUNK_SIZE):
                conn.execute(stmt, records[start : start + _CHUNK_SIZE])
        return len(records)

    def read_series(
        self,
        layer: str = "processed",
        name: str = "eco2mix_series",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        """Lit les séries d'un jeu de données depuis `series`, triées par `(unique_id, ds)`."""
        base_sql = (
            "SELECT unique_id, ds, y, prevision_j1, prevision_j, quality_flag, "
            "is_holiday_fr, is_bridge_day, is_dst_transition "
            "FROM series WHERE source = :source"
        )
        params: dict[str, Any] = {"source": name}
        if unique_id is not None:
            base_sql += " AND unique_id = :unique_id"
            params["unique_id"] = unique_id
        base_sql += " ORDER BY unique_id ASC, ds ASC"

        with self.engine.connect() as conn:
            df = pd.read_sql_query(text(base_sql), conn, params=params)

        if df.empty:
            return pd.DataFrame(
                columns=[
                    "unique_id",
                    "ds",
                    "y",
                    "prevision_j1",
                    "prevision_j",
                    "quality_flag",
                    "is_holiday_fr",
                    "is_bridge_day",
                    "is_dst_transition",
                ]
            )

        df["ds"] = pd.to_datetime(df["ds"], utc=True)
        for bool_col in ("is_holiday_fr", "is_bridge_day", "is_dst_transition"):
            if bool_col in df.columns:
                df[bool_col] = df[bool_col].astype("boolean")
        return df

    def upsert_alerts(self, alerts_df: pd.DataFrame, name: str = "alerts") -> int:
        """Insère ou met à jour les alertes dans `alerts` sur `alert_id` en préservant la qualification."""
        if alerts_df.empty:
            return 0

        deduped = alerts_df.copy()
        deduped["ds"] = pd.to_datetime(deduped["ds"], utc=True)
        deduped = deduped.drop_duplicates(subset=["alert_id"], keep="last")

        records = [
            {
                "alert_id": str(row["alert_id"]),
                "unique_id": str(row["unique_id"]),
                "ds": _to_utc_datetime(row["ds"]),
                "y": float(row["y"]),
                "y_hat": float(row["y_hat"]),
                "residual": float(row["residual"]),
                "ewma_error": float(row["ewma_error"]),
                "threshold_eps": float(row["threshold_eps"]),
                "anomaly_score": float(row["anomaly_score"]),
                "is_anomaly": bool(row["is_anomaly"]),
                "detector_name": str(row["detector_name"]),
                "quality_flag": str(row.get("quality_flag") or "OK"),
                "qualification": None if pd.isna(row.get("qualification")) else str(row.get("qualification")),
                "qualification_comment": (
                    None if pd.isna(row.get("qualification_comment")) else str(row.get("qualification_comment"))
                ),
                "qualified_by": None if pd.isna(row.get("qualified_by")) else str(row.get("qualified_by")),
                "qualified_at": _to_utc_datetime(row.get("qualified_at")),
            }
            for row in deduped.to_dict(orient="records")
        ]

        stmt = text(
            """
            INSERT INTO alerts (
                alert_id, unique_id, ds, y, y_hat, residual, ewma_error,
                threshold_eps, anomaly_score, is_anomaly, detector_name, quality_flag,
                qualification, qualification_comment, qualified_by, qualified_at
            )
            VALUES (
                :alert_id, :unique_id, :ds, :y, :y_hat, :residual, :ewma_error,
                :threshold_eps, :anomaly_score, :is_anomaly, :detector_name, :quality_flag,
                :qualification, :qualification_comment, :qualified_by, :qualified_at
            )
            ON CONFLICT (alert_id) DO UPDATE SET
                unique_id = EXCLUDED.unique_id,
                ds = EXCLUDED.ds,
                y = EXCLUDED.y,
                y_hat = EXCLUDED.y_hat,
                residual = EXCLUDED.residual,
                ewma_error = EXCLUDED.ewma_error,
                threshold_eps = EXCLUDED.threshold_eps,
                anomaly_score = EXCLUDED.anomaly_score,
                is_anomaly = EXCLUDED.is_anomaly,
                detector_name = EXCLUDED.detector_name,
                quality_flag = EXCLUDED.quality_flag,
                qualification = COALESCE(EXCLUDED.qualification, alerts.qualification),
                qualification_comment = COALESCE(EXCLUDED.qualification_comment, alerts.qualification_comment),
                qualified_by = COALESCE(EXCLUDED.qualified_by, alerts.qualified_by),
                qualified_at = COALESCE(EXCLUDED.qualified_at, alerts.qualified_at)
            """
        )

        with self.engine.begin() as conn:
            for start in range(0, len(records), _CHUNK_SIZE):
                conn.execute(stmt, records[start : start + _CHUNK_SIZE])
        return len(records)

    def read_alerts(self, name: str = "alerts") -> pd.DataFrame:
        """Retourne l'ensemble des alertes enregistrées dans `alerts`, triées par `ds`."""
        query = (
            "SELECT alert_id, unique_id, ds, y, y_hat, residual, ewma_error, threshold_eps, "
            "anomaly_score, is_anomaly, detector_name, quality_flag, created_at, "
            "qualification, qualification_comment, qualified_by, qualified_at "
            "FROM alerts ORDER BY ds ASC"
        )
        with self.engine.connect() as conn:
            df = pd.read_sql_query(text(query), conn)

        if df.empty:
            return df

        df["ds"] = pd.to_datetime(df["ds"], utc=True)
        if "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        if "qualified_at" in df.columns:
            df["qualified_at"] = pd.to_datetime(df["qualified_at"], utc=True, errors="coerce")
        if "is_anomaly" in df.columns:
            df["is_anomaly"] = df["is_anomaly"].astype(bool)
        return df

    def upsert_weather(self, df: pd.DataFrame, layer: str = "processed", name: str = "weather") -> int:
        """Insère ou met à jour les séries météo dans `weather` de manière idempotente sur `(unique_id, ds)`."""
        if df.empty:
            return 0

        deduped = df[["unique_id", "ds", "temperature_2m"]].copy()
        deduped["ds"] = pd.to_datetime(deduped["ds"], utc=True)
        deduped = deduped.drop_duplicates(subset=["unique_id", "ds"], keep="last")

        records = [
            {
                "unique_id": str(row["unique_id"]),
                "ds": _to_utc_datetime(row["ds"]),
                "temperature_2m": float(row["temperature_2m"]),
            }
            for row in deduped.to_dict(orient="records")
            if not pd.isna(row["temperature_2m"])
        ]
        if not records:
            return 0

        stmt = text(
            """
            INSERT INTO weather (unique_id, ds, temperature_2m)
            VALUES (:unique_id, :ds, :temperature_2m)
            ON CONFLICT (unique_id, ds) DO UPDATE SET
                temperature_2m = EXCLUDED.temperature_2m,
                ingested_at = CURRENT_TIMESTAMP
            """
        )

        with self.engine.begin() as conn:
            for start in range(0, len(records), _CHUNK_SIZE):
                conn.execute(stmt, records[start : start + _CHUNK_SIZE])
        return len(records)

    def read_weather(
        self,
        layer: str = "processed",
        name: str = "weather",
        unique_id: str | None = None,
    ) -> pd.DataFrame:
        """Lit les séries météo depuis `weather`, triées par `(unique_id, ds)`."""
        base_sql = "SELECT unique_id, ds, temperature_2m FROM weather"
        params: dict[str, Any] = {}
        if unique_id is not None:
            base_sql += " WHERE unique_id = :unique_id"
            params["unique_id"] = unique_id
        base_sql += " ORDER BY unique_id ASC, ds ASC"

        with self.engine.connect() as conn:
            df = pd.read_sql_query(text(base_sql), conn, params=params)

        if df.empty:
            return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

        df["ds"] = pd.to_datetime(df["ds"], utc=True)
        return df
