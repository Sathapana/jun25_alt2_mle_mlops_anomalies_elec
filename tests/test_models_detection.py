"""Tests unitaires pour le pôle P2 (Baselines, Désaisonnalisation, Seuillage Dynamique, Corrélation) et P4 (Drift)."""

from __future__ import annotations

import pandas as pd

from anomalies_elec.models.baselines import RTEForecastBaseline, WeeklyLagBaseline
from anomalies_elec.models.correlator import shifted_cross_correlation
from anomalies_elec.models.deseasonalize import MultiSeasonalDeseasonalizer
from anomalies_elec.models.thresholding import DynamicThresholdDetector
from anomalies_elec.monitoring.drift import evaluate_drift_regime


def test_rte_forecast_baseline_and_dynamic_threshold_detect_injected_anomaly(
    synthetic_eco2mix_df: pd.DataFrame,
) -> None:
    baseline = RTEForecastBaseline()
    res_df = baseline.compute_residuals(synthetic_eco2mix_df)
    detector = DynamicThresholdDetector(ewma_span=4, pruning_p=0.13)
    scored = detector.detect(res_df)

    anom_indices = set(scored.index[scored["is_anomaly"]].tolist())
    assert any(idx in anom_indices for idx in (150, 151, 152))
    # Le taux global d'alerte doit rester très faible (< 5% des points)
    assert scored["is_anomaly"].mean() < 0.05


def test_weekly_lag_and_deseasonalizer_produce_valid_residuals(
    synthetic_eco2mix_df: pd.DataFrame,
) -> None:
    j7 = WeeklyLagBaseline(lag_steps=96).compute_residuals(synthetic_eco2mix_df)
    assert "residual" in j7.columns
    assert not j7["residual"].isna().any()

    mstl = MultiSeasonalDeseasonalizer(season_lengths=[96]).compute_residuals(synthetic_eco2mix_df)
    detector = DynamicThresholdDetector(ewma_span=4, pruning_p=0.13)
    scored = detector.detect(mstl)
    assert scored.loc[150:153, "is_anomaly"].any()


def test_shifted_cross_correlation_finds_lagged_peak() -> None:
    s1 = pd.Series([0.0, 0.0, 10.0, 20.0, 10.0, 0.0, 0.0, 0.0])
    s2 = pd.Series([0.0, 0.0, 0.0, 10.0, 20.0, 10.0, 0.0, 0.0])
    res = shifted_cross_correlation(s1, s2, max_shift_steps=2)
    assert float(res["coefficient"]) > 0.95
    assert int(res["best_shift"]) == 1


def test_drift_distinguishes_atypical_regime_from_model_degradation(
    synthetic_eco2mix_df: pd.DataFrame,
) -> None:
    base = RTEForecastBaseline().compute_residuals(synthetic_eco2mix_df)

    # Cas 1 : Régime saisonnier atypique (la consommation augmente de 8000 MW, mais la prévision suit)
    atypical = base.copy()
    atypical["y"] += 8000.0
    atypical["y_hat"] += 8000.0
    atypical["residual"] = atypical["y"] - atypical["y_hat"]
    report_atypical = evaluate_drift_regime(base, atypical)
    assert report_atypical["diagnosis"] == "ATYPICAL_SEASONAL_REGIME"

    # Cas 2 : Dégradation du modèle (biais fort sur les résidus)
    degraded = base.copy()
    degraded["residual"] += 5000.0
    report_degraded = evaluate_drift_regime(base, degraded)
    assert report_degraded["diagnosis"] == "MODEL_DEGRADATION_CONCEPT_DRIFT"
