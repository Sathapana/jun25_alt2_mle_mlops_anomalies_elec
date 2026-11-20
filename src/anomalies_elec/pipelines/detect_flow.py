"""Pipeline de détection continue et persistance des alertes dans le store Parquet."""

from __future__ import annotations

import pandas as pd

from anomalies_elec.config import AppConfig, load_config
from anomalies_elec.pipelines.train_flow import evaluate_detector
from anomalies_elec.storage.parquet_store import ParquetStore


def run_detection_pipeline(
    df: pd.DataFrame,
    detector_type: str = "mstl",
    config: AppConfig | None = None,
    persist_alerts: bool = True,
) -> pd.DataFrame:
    """Exécute la détection d'anomalies et sauvegarde les alertes déclenchées."""
    cfg = config or load_config()
    scored_df, _ = evaluate_detector(df, detector_type=detector_type, config=cfg)

    alerts_df = scored_df.loc[scored_df["is_anomaly"]].copy()
    if persist_alerts and not alerts_df.empty:
        store = ParquetStore(cfg.storage.data_dir)
        store.upsert_alerts(alerts_df)

    return scored_df
