"""Chargement et validation de la configuration du projet via Pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    name: str = "anomalies-reseau-electrique"
    version: str = "0.1.0"
    default_scope: str = "national"
    default_unique_id: str = "FR"
    freq: str = "15min"
    timezone: str = "Europe/Paris"


class IngestionConfig(BaseModel):
    base_url: str = "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets"
    datasets: dict[str, str] = Field(
        default_factory=lambda: {
            "national_tr": "eco2mix-national-tr",
            "national_cons_def": "eco2mix-national-cons-def",
            "regional_tr": "eco2mix-regional-tr",
            "regional_cons_def": "eco2mix-regional-cons-def",
        }
    )
    monthly_quota_limit: int = 50000
    page_size: int = 100
    min_consumption_mw: float = 15000.0
    max_consumption_mw: float = 120000.0
    max_frozen_steps: int = 4


class ModelsConfig(BaseModel):
    weekly_lag_steps: int = 672
    mstl_season_lengths: list[int] = Field(default_factory=lambda: [96, 672])
    prediction_interval_level: int = 99
    ewma_span: int = 4
    z_search_min: float = 2.0
    z_search_max: float = 10.0
    z_search_steps: int = 33
    pruning_min_decrease_p: float = 0.13
    alert_budget_per_week: int = 5


class StorageConfig(BaseModel):
    # "parquet" : fichiers locaux (dev / tests) — "postgres" : base partagée des services Docker
    backend: Literal["parquet", "postgres"] = "parquet"
    database_url: str = "postgresql+psycopg://anomalies:anomalies@localhost:5432/anomalies"
    data_dir: Path = Path("data")
    raw_subdir: str = "raw"
    processed_subdir: str = "processed"
    alerts_subdir: str = "alerts"


class MonitoringConfig(BaseModel):
    wasserstein_drift_threshold: float = 0.15
    psi_drift_threshold: float = 0.20


class WeatherLocationConfig(BaseModel):
    unique_id: str
    name: str
    latitude: float
    longitude: float
    weight: float


def _default_weather_locations() -> list[WeatherLocationConfig]:
    return [
        WeatherLocationConfig(unique_id="11", name="Paris", latitude=48.8566, longitude=2.3522, weight=0.1885),
        WeatherLocationConfig(unique_id="84", name="Lyon", latitude=45.7640, longitude=4.8357, weight=0.1257),
        WeatherLocationConfig(unique_id="75", name="Bordeaux", latitude=44.8378, longitude=-0.5792, weight=0.0940),
        WeatherLocationConfig(unique_id="76", name="Toulouse", latitude=43.6047, longitude=1.4442, weight=0.0937),
        WeatherLocationConfig(unique_id="32", name="Lille", latitude=50.6292, longitude=3.0573, weight=0.0919),
        WeatherLocationConfig(unique_id="44", name="Strasbourg", latitude=48.5734, longitude=7.7521, weight=0.0853),
        WeatherLocationConfig(unique_id="93", name="Marseille", latitude=43.2965, longitude=5.3698, weight=0.0793),
        WeatherLocationConfig(unique_id="52", name="Nantes", latitude=47.2184, longitude=-1.5536, weight=0.0598),
        WeatherLocationConfig(unique_id="53", name="Rennes", latitude=48.1173, longitude=-1.6778, weight=0.0528),
        WeatherLocationConfig(unique_id="28", name="Rouen", latitude=49.4432, longitude=1.0999, weight=0.0510),
        WeatherLocationConfig(unique_id="27", name="Dijon", latitude=47.3220, longitude=5.0415, weight=0.0430),
        WeatherLocationConfig(unique_id="24", name="Orléans", latitude=47.9029, longitude=1.9093, weight=0.0396),
    ]


class WeatherConfig(BaseModel):
    archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    default_start_date: str = "2012-01-01"
    extra_windows: list[tuple[str, str]] = Field(default_factory=list)
    max_days_per_chunk: int = 365
    timeout_seconds: float = 30.0
    locations: list[WeatherLocationConfig] = Field(default_factory=_default_weather_locations)


class AppConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Charge la configuration depuis un fichier YAML ou utilise les valeurs par défaut."""
    resolved_path = Path(config_path or os.environ.get("ANOMALIES_ELEC_CONFIG_PATH", "configs/default.yaml"))
    if resolved_path.exists():
        with resolved_path.open("r", encoding="utf-8") as f:
            raw_data: dict[str, Any] = yaml.safe_load(f) or {}
        cfg = AppConfig.model_validate(raw_data)
    else:
        cfg = AppConfig()
    return _apply_env_overrides(cfg)


def _apply_env_overrides(cfg: AppConfig) -> AppConfig:
    """Les variables d'environnement (docker-compose, .env) priment sur le YAML pour le stockage."""
    storage_updates: dict[str, Any] = {}
    if backend := os.environ.get("STORAGE_BACKEND"):
        storage_updates["backend"] = backend
    if database_url := os.environ.get("DATABASE_URL"):
        storage_updates["database_url"] = database_url
    if data_dir := os.environ.get("DATA_DIR"):
        storage_updates["data_dir"] = data_dir
    if not storage_updates:
        return cfg
    storage = StorageConfig.model_validate({**cfg.storage.model_dump(), **storage_updates})
    return cfg.model_copy(update={"storage": storage})


def load_reference_events(path: str | Path = "configs/reference_events.yaml") -> list[dict[str, Any]]:
    """Charge le catalogue d'événements historiques de référence."""
    resolved_path = Path(path)
    if not resolved_path.exists():
        return []
    with resolved_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("reference_events", []))
