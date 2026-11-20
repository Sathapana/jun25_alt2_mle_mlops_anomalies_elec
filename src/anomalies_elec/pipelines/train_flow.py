"""Pipeline d'entraînement et d'évaluation avec journalisation MLflow optionnelle."""

from __future__ import annotations

from typing import Any

import pandas as pd

from anomalies_elec.config import AppConfig, load_config
from anomalies_elec.models.baselines import RTEForecastBaseline, WeeklyLagBaseline
from anomalies_elec.models.deseasonalize import MultiSeasonalDeseasonalizer
from anomalies_elec.models.thresholding import DynamicThresholdDetector


def evaluate_detector(
    df: pd.DataFrame,
    detector_type: str = "mstl",
    config: AppConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Exécute un détecteur ('baseline_j7', 'baseline_rte', 'mstl') et calcule les métriques."""
    cfg = config or load_config()

    if detector_type == "baseline_j7":
        model = WeeklyLagBaseline(lag_steps=cfg.models.weekly_lag_steps)
    elif detector_type == "baseline_rte":
        model = RTEForecastBaseline()
    else:
        model = MultiSeasonalDeseasonalizer(
            season_lengths=cfg.models.mstl_season_lengths,
            freq=cfg.project.freq,
        )

    res_df = model.compute_residuals(df)
    thresh = DynamicThresholdDetector(
        ewma_span=cfg.models.ewma_span,
        z_min=cfg.models.z_search_min,
        z_max=cfg.models.z_search_max,
        z_steps=cfg.models.z_search_steps,
        pruning_p=cfg.models.pruning_min_decrease_p,
    )
    scored_df = thresh.detect(res_df)

    n_anomalies = int(scored_df["is_anomaly"].sum())
    mae = float(scored_df["residual"].abs().mean())
    metrics: dict[str, Any] = {
        "detector": detector_type,
        "num_points": len(scored_df),
        "num_anomalies": n_anomalies,
        "residual_mae_mw": round(mae, 2),
        "threshold_eps": float(scored_df["threshold_eps"].iloc[0]) if not scored_df.empty else 0.0,
    }
    return scored_df, metrics
