"""Chargement et validation de la configuration du projet via Pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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
    data_dir: Path = Path("data")
    raw_subdir: str = "raw"
    processed_subdir: str = "processed"
    alerts_subdir: str = "alerts"


class MonitoringConfig(BaseModel):
    wasserstein_drift_threshold: float = 0.15
    psi_drift_threshold: float = 0.20


class AppConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Charge la configuration depuis un fichier YAML ou utilise les valeurs par défaut."""
    resolved_path = Path(
        config_path or os.environ.get("ANOMALIES_ELEC_CONFIG_PATH", "configs/default.yaml")
    )
    if resolved_path.exists():
        with resolved_path.open("r", encoding="utf-8") as f:
            raw_data: dict[str, Any] = yaml.safe_load(f) or {}
        return AppConfig.model_validate(raw_data)
    return AppConfig()


def load_reference_events(path: str | Path = "configs/reference_events.yaml") -> list[dict[str, Any]]:
    """Charge le catalogue d'événements historiques de référence."""
    resolved_path = Path(path)
    if not resolved_path.exists():
        return []
    with resolved_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("reference_events", []))
