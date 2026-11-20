"""Corrélation croisée avec décalage temporel (inspiré de LinkedIn Luminol — Niveau 2)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def shifted_cross_correlation(
    series_a: pd.Series,
    series_b: pd.Series,
    max_shift_steps: int = 4,
    shift_penalty: float = 0.05,
) -> dict[str, float | int]:
    """Calcule le coefficient de corrélation maximal entre deux séries avec tolérance de décalage."""
    a = series_a.to_numpy(dtype=float)
    b = series_b.to_numpy(dtype=float)
    n = min(len(a), len(b))
    if n < 3:
        return {"coefficient": 0.0, "best_shift": 0, "weighted_coefficient": 0.0}

    a = a[:n]
    b = b[:n]

    best_raw = 0.0
    best_weighted = -1.0
    best_shift = 0

    for shift in range(-max_shift_steps, max_shift_steps + 1):
        if shift < 0:
            sub_a, sub_b = a[-shift:], b[: n + shift]
        elif shift > 0:
            sub_a, sub_b = a[: n - shift], b[shift:]
        else:
            sub_a, sub_b = a, b

        if len(sub_a) < 3 or np.std(sub_a) == 0 or np.std(sub_b) == 0:
            continue

        corr = float(np.corrcoef(sub_a, sub_b)[0, 1])
        weighted = abs(corr) * (1.0 - shift_penalty * abs(shift))
        if weighted > best_weighted:
            best_weighted = weighted
            best_raw = corr
            best_shift = shift

    return {
        "coefficient": best_raw,
        "best_shift": best_shift,
        "weighted_coefficient": max(best_weighted, 0.0),
    }
