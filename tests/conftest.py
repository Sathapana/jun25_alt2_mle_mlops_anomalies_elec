"""Fixtures de séries temporelles éCO2mix synthétiques avec anomalies injectées."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _isolate_storage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empêche un `.env` ou un shell de dev (STORAGE_BACKEND=postgres, ...) de fuiter dans les tests."""
    for var in ("STORAGE_BACKEND", "DATABASE_URL", "DATA_DIR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def synthetic_eco2mix_df() -> pd.DataFrame:
    """Génère 3 jours de consommation nationale au pas de 15 minutes (288 points) avec un pic anormal."""
    rng = np.random.default_rng(42)
    n_points = 96 * 3
    ds = pd.date_range("2025-01-13 00:00:00", periods=n_points, freq="15min", tz="UTC")

    t = np.arange(n_points)
    daily_cycle = 8000.0 * np.sin(2.0 * np.pi * t / 96.0)
    base_load = 60000.0 + daily_cycle
    noise = rng.normal(0.0, 250.0, size=n_points)

    y = base_load + noise
    prevision_j = base_load.copy()
    prevision_j1 = base_load + rng.normal(0.0, 150.0, size=n_points)

    # Injection d'une anomalie franche (+12 000 MW) sur 3 pas consécutifs autour de l'indice 150
    y[150:153] += 12000.0

    return pd.DataFrame(
        {
            "unique_id": "FR",
            "ds": ds,
            "y": y,
            "prevision_j1": prevision_j1,
            "prevision_j": prevision_j,
        }
    )
