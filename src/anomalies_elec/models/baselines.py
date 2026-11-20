"""Baselines documentées du Niveau 1 :
1. Écart à la même heure du même jour de la semaine précédente (J-7).
2. Écart à la prévision publiée par RTE (J ou J-1).
"""

from __future__ import annotations

import pandas as pd


class WeeklyLagBaseline:
    """Baseline 1 : Prédiction par persistance hebdomadaire (J-7, soit 672 pas de 15 min)."""

    name: str = "baseline_j7"

    def __init__(self, lag_steps: int = 672) -> None:
        self.lag_steps = lag_steps

    def compute_residuals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.sort_values(["unique_id", "ds"]).copy()
        out["y_hat"] = out.groupby("unique_id")["y"].shift(self.lag_steps)
        # Fallback sur la médiane locale si l'historique est inférieur à 7 jours
        fallback = out.groupby("unique_id")["y"].transform("median")
        out["y_hat"] = out["y_hat"].fillna(fallback)
        out["residual"] = out["y"] - out["y_hat"]
        out["detector_name"] = self.name
        return out


class RTEForecastBaseline:
    """Baseline 2 : Écart entre la consommation réalisée et la prévision officielle RTE."""

    name: str = "baseline_rte"

    def compute_residuals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.sort_values(["unique_id", "ds"]).copy()
        # Utilise la prévision du jour même (prevision_j) en priorité, sinon veille (prevision_j1)
        out["y_hat"] = out["prevision_j"].combine_first(out["prevision_j1"]).fillna(out["y"])
        out["residual"] = out["y"] - out["y_hat"]
        out["detector_name"] = self.name
        return out
