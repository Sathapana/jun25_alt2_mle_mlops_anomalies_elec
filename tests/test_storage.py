"""Tests du contrat de stockage commun et de la sélection du backend (Pôle P1)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from anomalies_elec.config import StorageConfig, load_config
from anomalies_elec.storage.base import Store, get_store
from anomalies_elec.storage.parquet_store import ParquetStore
from anomalies_elec.storage.postgres_store import PostgresStore

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "docker" / "postgres" / "init" / "01_schema.sql"


def test_default_backend_is_parquet(tmp_path: Path) -> None:
    store = get_store(StorageConfig(data_dir=tmp_path))
    assert isinstance(store, ParquetStore)
    assert isinstance(store, Store)


def test_postgres_backend_is_selectable_without_live_database() -> None:
    store = get_store(StorageConfig(backend="postgres", database_url="postgresql+psycopg://u:p@localhost:1/db"))
    assert isinstance(store, PostgresStore)
    assert isinstance(store, Store)


def test_env_overrides_storage_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANOMALIES_ELEC_CONFIG_PATH", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/anomalies")
    cfg = load_config()
    assert cfg.storage.backend == "postgres"
    assert cfg.storage.database_url == "postgresql+psycopg://x:y@db:5432/anomalies"


@pytest.mark.parametrize("table", ["series", "alerts", "monitoring_metrics", "weather"])
def test_schema_sql_defines_shared_tables(table: str) -> None:
    assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL.read_text(encoding="utf-8")


def test_parquet_store_weather_upsert_and_read(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    ds = pd.to_datetime(["2025-01-15 00:00:00+00:00", "2025-01-15 00:15:00+00:00"], utc=True)
    batch1 = pd.DataFrame({"unique_id": ["FR", "FR"], "ds": ds, "temperature_2m": [4.0, 4.2]})
    batch2 = pd.DataFrame(
        {
            "unique_id": ["FR", "11"],
            "ds": [ds[1], ds[0]],
            "temperature_2m": [4.5, 3.1],
        }
    )

    store.upsert_weather(batch1)
    store.upsert_weather(batch2)

    all_weather = store.read_weather()
    assert len(all_weather) == 3
    assert str(all_weather["ds"].dt.tz) == "UTC"

    fr_weather = store.read_weather(unique_id="FR")
    assert len(fr_weather) == 2
    assert float(fr_weather.iloc[1]["temperature_2m"]) == pytest.approx(4.5)


def test_postgres_store_series_alerts_weather_with_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "test_store.db"
    store = PostgresStore(f"sqlite:///{db_path}")
    assert store.ping() is True

    with store.engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE series (
                    source TEXT NOT NULL,
                    unique_id TEXT NOT NULL,
                    ds TIMESTAMP NOT NULL,
                    y REAL,
                    prevision_j1 REAL,
                    prevision_j REAL,
                    quality_flag TEXT NOT NULL DEFAULT 'OK',
                    is_holiday_fr BOOLEAN,
                    is_bridge_day BOOLEAN,
                    is_dst_transition BOOLEAN,
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source, unique_id, ds)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE alerts (
                    alert_id TEXT PRIMARY KEY,
                    unique_id TEXT NOT NULL,
                    ds TIMESTAMP NOT NULL,
                    y REAL NOT NULL,
                    y_hat REAL NOT NULL,
                    residual REAL NOT NULL,
                    ewma_error REAL NOT NULL,
                    threshold_eps REAL NOT NULL,
                    anomaly_score REAL NOT NULL,
                    is_anomaly BOOLEAN NOT NULL,
                    detector_name TEXT NOT NULL,
                    quality_flag TEXT NOT NULL DEFAULT 'OK',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    qualification TEXT,
                    qualification_comment TEXT,
                    qualified_by TEXT,
                    qualified_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE weather (
                    unique_id TEXT NOT NULL,
                    ds TIMESTAMP NOT NULL,
                    temperature_2m REAL NOT NULL,
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (unique_id, ds)
                )
                """
            )
        )

    # 1. Series upsert idempotency
    ds_series = pd.to_datetime(["2025-01-15 00:00:00+00:00", "2025-01-15 00:15:00+00:00"], utc=True)
    series_df = pd.DataFrame(
        {
            "unique_id": ["FR", "FR"],
            "ds": ds_series,
            "y": [70000.0, 71000.0],
            "prevision_j1": [69500.0, 70500.0],
            "prevision_j": [69800.0, 70800.0],
            "quality_flag": ["OK", "OK"],
            "is_holiday_fr": [False, False],
            "is_bridge_day": [False, False],
            "is_dst_transition": [False, False],
        }
    )
    assert store.upsert_series(series_df, name="national_tr") == 2
    series_update = series_df.iloc[[1]].copy()
    series_update["y"] = 72000.0
    assert store.upsert_series(series_update, name="national_tr") == 1
    loaded_series = store.read_series(name="national_tr", unique_id="FR")
    assert len(loaded_series) == 2
    assert float(loaded_series.iloc[1]["y"]) == pytest.approx(72000.0)

    # 2. Alerts upsert preserves existing qualification when re-detected
    alert_df = pd.DataFrame(
        [
            {
                "alert_id": "FR_2025-01-15T00:15:00Z",
                "unique_id": "FR",
                "ds": ds_series[1],
                "y": 72000.0,
                "y_hat": 70000.0,
                "residual": 2000.0,
                "ewma_error": 1800.0,
                "threshold_eps": 1500.0,
                "anomaly_score": 1.2,
                "is_anomaly": True,
                "detector_name": "mstl_telemanom_v1",
                "quality_flag": "OK",
                "qualification": "true_positive",
                "qualification_comment": "Peak verified",
                "qualified_by": "ops",
                "qualified_at": ds_series[1],
            }
        ]
    )
    assert store.upsert_alerts(alert_df) == 1
    redetect_df = alert_df.copy()
    redetect_df["qualification"] = None
    redetect_df["qualification_comment"] = None
    redetect_df["qualified_by"] = None
    redetect_df["qualified_at"] = pd.NaT
    assert store.upsert_alerts(redetect_df) == 1
    loaded_alerts = store.read_alerts()
    assert len(loaded_alerts) == 1
    assert loaded_alerts.iloc[0]["qualification"] == "true_positive"

    # 3. Weather upsert idempotency
    weather_df = pd.DataFrame(
        {
            "unique_id": ["FR", "11"],
            "ds": [ds_series[0], ds_series[0]],
            "temperature_2m": [5.2, 4.8],
        }
    )
    assert store.upsert_weather(weather_df) == 2
    assert store.upsert_weather(pd.DataFrame({"unique_id": ["FR"], "ds": [ds_series[0]], "temperature_2m": [5.6]})) == 1
    loaded_weather = store.read_weather(unique_id="FR")
    assert len(loaded_weather) == 1
    assert float(loaded_weather.iloc[0]["temperature_2m"]) == pytest.approx(5.6)


def test_alerts_schema_matches_api_qualification_labels() -> None:
    """Les labels autorisés en base doivent rester alignés avec l'API (QualificationLabel)."""
    from typing import get_args

    from anomalies_elec.api.schemas import QualificationLabel

    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for label in get_args(QualificationLabel):
        assert f"'{label}'" in sql
