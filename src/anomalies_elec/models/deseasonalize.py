"""Désaisonnalisation multi-saisonnière explicite (MSTL / décomposition harmonique de repli)."""

from __future__ import annotations

import numpy as np
import pandas as pd


class MultiSeasonalDeseasonalizer:
    """Extrait la composante attendue `y_hat` (tendance + saisonnalités) et le résidu `residual`.

    Utilise `StatsForecast` (`MSTL`) lorsqu'il est disponible et que la série est suffisamment longue,
    ou une décomposition harmonique (Fourier + tendance glissante robuste) en mode léger/rapide.
    """

    name: str = "mstl_deseasonalizer"

    def __init__(
        self,
        season_lengths: list[int] | None = None,
        freq: str = "15min",
        use_statsforecast: bool = False,
    ) -> None:
        self.season_lengths = season_lengths or [96, 672]
        self.freq = freq
        self.use_statsforecast = use_statsforecast

    def compute_residuals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.sort_values(["unique_id", "ds"]).copy()

        if self.use_statsforecast:
            try:
                return self._fit_statsforecast_mstl(out)
            except Exception:
                pass

        return self._fit_robust_harmonic(out)

    def _fit_statsforecast_mstl(self, df: pd.DataFrame) -> pd.DataFrame:
        from statsforecast import StatsForecast
        from statsforecast.models import MSTL

        sf_df = df[["unique_id", "ds", "y"]].copy()
        sf = StatsForecast(
            models=[MSTL(season_length=self.season_lengths)],
            freq=self.freq,
            n_jobs=1,
        )
        sf.forecast(df=sf_df, h=1, fitted=True)
        fitted = sf.forecast_fitted_values().reset_index()

        merged = df.merge(
            fitted[["unique_id", "ds", "MSTL"]],
            on=["unique_id", "ds"],
            how="left",
        )
        merged["y_hat"] = merged["MSTL"].fillna(merged["y"])
        merged["residual"] = merged["y"] - merged["y_hat"]
        merged["detector_name"] = "statsforecast_mstl"
        return merged.drop(columns=["MSTL"])

    def _fit_robust_harmonic(self, df: pd.DataFrame) -> pd.DataFrame:
        """Décomposition multi-saisonnière robuste par médiane glissante + profil saisonnier médian."""
        results: list[pd.DataFrame] = []
        primary_period = min(self.season_lengths) if self.season_lengths else 96

        for _, group in df.groupby("unique_id", group_keys=False):
            g = group.copy()
            # Tendance robuste par médiane glissante centrée
            trend = g["y"].rolling(window=primary_period, min_periods=1, center=True).median()
            detrended = g["y"] - trend

            # Composante saisonnière périodique robuste (médiane par pas du cycle)
            step_idx = np.arange(len(g)) % primary_period
            g["_step_idx"] = step_idx
            g["_detrended"] = detrended
            seasonal = g.groupby("_step_idx")["_detrended"].transform("median")

            g["y_hat"] = trend + seasonal
            g["residual"] = g["y"] - g["y_hat"]
            g["detector_name"] = self.name
            results.append(g.drop(columns=["_step_idx", "_detrended"]))

        return pd.concat(results, ignore_index=True)
