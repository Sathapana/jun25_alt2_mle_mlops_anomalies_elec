"""Calcul de dérive par distance de Wasserstein normalisée pour distinguer :
- Régime saisonnier atypique (la consommation `y` dérive mais le résidu par rapport à la prévision reste stable).
- Véritable dégradation du modèle / Concept Drift (le résidu `residual` dérive fortement).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance


def normalized_wasserstein(ref: pd.Series, cur: pd.Series) -> float:
    """Calcule la distance de Wasserstein normalisée par l'écart-type de la référence."""
    r = ref.dropna().to_numpy(dtype=float)
    c = cur.dropna().to_numpy(dtype=float)
    if len(r) == 0 or len(c) == 0:
        return 0.0
    std = float(np.std(r))
    dist = float(wasserstein_distance(r, c))
    return dist / std if std > 1e-9 else dist


def evaluate_drift_regime(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    drift_threshold: float = 0.15,
) -> dict[str, Any]:
    """Compare la distribution de la consommation et des résidus entre référence et fenêtre courante."""
    y_drift = normalized_wasserstein(reference_df["y"], current_df["y"])
    res_drift = (
        normalized_wasserstein(reference_df["residual"], current_df["residual"])
        if "residual" in reference_df.columns and "residual" in current_df.columns
        else 0.0
    )

    is_y_drifted = y_drift > drift_threshold
    is_res_drifted = res_drift > drift_threshold

    if is_res_drifted:
        diagnosis = "MODEL_DEGRADATION_CONCEPT_DRIFT"
    elif is_y_drifted and not is_res_drifted:
        diagnosis = "ATYPICAL_SEASONAL_REGIME"
    else:
        diagnosis = "NOMINAL"

    return {
        "y_wasserstein_norm": round(y_drift, 4),
        "residual_wasserstein_norm": round(res_drift, 4),
        "is_input_drifted": is_y_drifted,
        "is_residual_drifted": is_res_drifted,
        "diagnosis": diagnosis,
    }
