"""Tests du contrat de stockage commun et de la sélection du backend (Pôle P1)."""

from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize("table", ["series", "alerts", "monitoring_metrics"])
def test_schema_sql_defines_shared_tables(table: str) -> None:
    assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL.read_text(encoding="utf-8")


def test_alerts_schema_matches_api_qualification_labels() -> None:
    """Les labels autorisés en base doivent rester alignés avec l'API (QualificationLabel)."""
    from typing import get_args

    from anomalies_elec.api.schemas import QualificationLabel

    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for label in get_args(QualificationLabel):
        assert f"'{label}'" in sql
