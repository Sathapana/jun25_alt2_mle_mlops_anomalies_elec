"""Contrôles de qualité des données (Data Quality Gate) avant détection d'anomalies."""

from __future__ import annotations

import pandas as pd

from anomalies_elec.config import IngestionConfig

REQUIRED_COLUMNS = ("unique_id", "ds", "y", "prevision_j1", "prevision_j")


def apply_quality_checks(
    df: pd.DataFrame,
    config: IngestionConfig | None = None,
    expected_freq: str = "15min",
) -> pd.DataFrame:
    """Évalue la qualité de chaque point et renseigne la colonne `quality_flag`.

    Valeurs possibles de `quality_flag`:
    - "OK" : Donnée valide
    - "MISSING_VALUE" : Consommation `y` manquante (NaN)
    - "OUT_OF_BOUNDS" : Consommation hors des bornes physiques [min_mw, max_mw]
    - "FROZEN_SENSOR" : Valeur identique répétée sur plus de `max_frozen_steps` pas
    - "MISSING_GAP" : Trou de publication détecté juste avant ce point
    """
    cfg = config or IngestionConfig()
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Colonnes requises manquantes dans le DataFrame: {missing_cols}")

    out = df.copy()
    out["ds"] = pd.to_datetime(out["ds"], utc=True)
    out = out.sort_values(["unique_id", "ds"]).reset_index(drop=True)
    out["quality_flag"] = "OK"

    expected_delta = pd.to_timedelta(expected_freq)

    for _, group in out.groupby("unique_id", group_keys=False):
        idx = group.index

        # 1. Trous temporels de publication
        time_diffs = group["ds"].diff()
        gap_mask = time_diffs > expected_delta
        out.loc[idx[gap_mask], "quality_flag"] = "MISSING_GAP"

        # 2. Capteur figé (différence nulle consécutive sur N pas)
        val_diff = group["y"].diff()
        is_same = val_diff == 0
        run_groups = (~is_same).cumsum()
        frozen_run_len = is_same.groupby(run_groups).cumsum()
        frozen_mask = frozen_run_len >= cfg.max_frozen_steps
        out.loc[idx[frozen_mask], "quality_flag"] = "FROZEN_SENSOR"

        # 3. Bornes physiques plausibles (MW)
        bounds_mask = (group["y"] < cfg.min_consumption_mw) | (group["y"] > cfg.max_consumption_mw)
        out.loc[idx[bounds_mask], "quality_flag"] = "OUT_OF_BOUNDS"

        # 4. Valeurs manquantes (priorité maximale)
        na_mask = group["y"].isna()
        out.loc[idx[na_mask], "quality_flag"] = "MISSING_VALUE"

    return out
