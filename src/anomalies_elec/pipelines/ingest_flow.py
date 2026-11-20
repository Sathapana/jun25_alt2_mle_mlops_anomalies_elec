"""Pipeline d'ingestion, contrôle qualité et enrichissement calendaire."""

from __future__ import annotations

import pandas as pd

from anomalies_elec.config import AppConfig, load_config
from anomalies_elec.features.calendar_fr import enrich_french_calendar
from anomalies_elec.ingestion.eco2mix_client import Eco2MixClient
from anomalies_elec.ingestion.quality import apply_quality_checks
from anomalies_elec.storage.parquet_store import ParquetStore


def run_ingestion_pipeline(
    records: list[dict] | None = None,
    dataset_key: str = "national_tr",
    where: str | None = None,
    config: AppConfig | None = None,
) -> pd.DataFrame:
    """Exécute la chaîne P1 : collecte (ou injection) -> contrôle qualité -> calendrier -> Parquet."""
    cfg = config or load_config()
    client = Eco2MixClient(cfg.ingestion)

    if records is not None:
        raw_df = client.normalize_records(records, default_unique_id=cfg.project.default_unique_id)
    else:
        raw_df = client.fetch_records(
            dataset_key=dataset_key,
            where=where,
            unique_id=cfg.project.default_unique_id,
        )

    if raw_df.empty:
        return raw_df

    checked_df = apply_quality_checks(
        raw_df,
        config=cfg.ingestion,
        expected_freq=cfg.project.freq,
    )
    enriched_df = enrich_french_calendar(checked_df, timezone=cfg.project.timezone)

    store = ParquetStore(cfg.storage.data_dir)
    store.upsert_series(enriched_df, layer=cfg.storage.processed_subdir, name=dataset_key)
    return enriched_df
